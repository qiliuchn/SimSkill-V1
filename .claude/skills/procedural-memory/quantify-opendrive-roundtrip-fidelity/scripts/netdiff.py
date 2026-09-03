#!/usr/bin/env python3
"""
netdiff.py -- structural fidelity diff between two SUMO .net.xml files.

Designed for FORMAT ROUND-TRIP evaluation (e.g. SUMO -> OpenDRIVE -> SUMO), where
edge/junction IDs are NOT preserved.  Everything is therefore matched
GEOMETRICALLY, not by id:

  * coordinates are first put in a common frame by undoing each net's <location
    netOffset="...">, then a residual translation is estimated robustly
    (iterated median of nearest-neighbour junction offsets) and removed;
  * junctions are matched by mutual nearest neighbour within --junc-tol;
  * edges are matched on (midpoint, heading) within --edge-tol / --angle-tol,
    greedily by increasing cost.

Reported (countable, no hand-waving):
  counts       edges / lanes / connections / junctions-by-type / roundabout decls
  geometry     total lane-km, matched per-edge length-difference distribution,
               junction position offset distribution
  speed        matched per-edge speed differences, speed histogram
  permissions  lane-km allowed per vClass (passenger/pedestrian/bicycle/bus/truck/...)
  signals      #tlLogic, per-TLS phase count / cycle length / phase strings,
               matched by junction position

Usage:
    python netdiff.py ORIG.net.xml ROUNDTRIP.net.xml [--json out.json] [--label NAME]
"""
import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

# vClasses we report lane-km for.  (Full SUMO list is longer; these are the ones
# that actually change traffic-simulation behaviour in an urban net.)
VCLASSES = ["passenger", "pedestrian", "bicycle", "bus", "truck", "delivery",
            "taxi", "emergency", "motorcycle", "moped", "tram", "rail"]
# SUMO's "all" default: every vClass is allowed when neither allow nor disallow is set.
ALL = set(VCLASSES)


def parse_perm(lane):
    allow = lane.get("allow")
    disallow = lane.get("disallow")
    if allow is not None:
        toks = allow.split()
        if "all" in toks:
            return set(ALL)
        return set(toks) & ALL
    if disallow is not None:
        toks = disallow.split()
        if "all" in toks:
            return set()
        return ALL - set(toks)
    return set(ALL)


def shape_pts(s):
    if not s:
        return []
    out = []
    for p in s.split():
        c = p.split(",")
        out.append((float(c[0]), float(c[1])))
    return out


class Net:
    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.root = root
        loc = root.find("location")
        self.netOffset = (0.0, 0.0)
        if loc is not None and loc.get("netOffset"):
            x, y = loc.get("netOffset").split(",")
            self.netOffset = (float(x), float(y))
        self.projParameter = loc.get("projParameter") if loc is not None else None

        self.edges = []      # dicts
        self.lanes = []
        for e in root.findall("edge"):
            if e.get("function") == "internal":
                continue
            lns = e.findall("lane")
            if not lns:
                continue
            pts = shape_pts(e.get("shape")) or shape_pts(lns[0].get("shape"))
            length = sum(float(l.get("length")) for l in lns) / len(lns)
            rec = {
                "id": e.get("id"),
                "from": e.get("from"),
                "to": e.get("to"),
                "type": e.get("type"),
                "nlanes": len(lns),
                "length": length,
                "speed": max(float(l.get("speed")) for l in lns),
                "pts": pts,
                "perm": [parse_perm(l) for l in lns],
                "lane_len": [float(l.get("length")) for l in lns],
                "lane_speed": [float(l.get("speed")) for l in lns],
                "priority": e.get("priority"),
                "name": e.get("name"),
            }
            self.edges.append(rec)
            self.lanes.extend(lns)

        self.junctions = []
        for j in root.findall("junction"):
            if j.get("type") == "internal":
                continue
            self.junctions.append({
                "id": j.get("id"), "type": j.get("type"),
                "x": float(j.get("x")), "y": float(j.get("y")),
                "incLanes": (j.get("incLanes") or "").split(),
            })
        self.conns = [c for c in root.findall("connection")
                      if not (c.get("from") or "").startswith(":")]
        self.roundabouts = root.findall("roundabout")
        self.tls = []
        jpos = {j["id"]: (j["x"], j["y"]) for j in self.junctions}
        for t in root.findall("tlLogic"):
            phases = t.findall("phase")
            self.tls.append({
                "id": t.get("id"), "type": t.get("type"),
                "nphases": len(phases),
                "cycle": sum(float(p.get("duration")) for p in phases),
                "states": [p.get("state") for p in phases],
                "durations": [float(p.get("duration")) for p in phases],
                "pos": jpos.get(t.get("id")),
                "nlinks": len(phases[0].get("state")) if phases else 0,
            })

    # --- geometry helpers -------------------------------------------------
    # VERIFIED: netconvert's OpenDRIVE export writes the SUMO net's *internal*
    # (already netOffset-shifted) coordinates straight into the .xodr, and the
    # reimport keeps them, emitting netOffset="0,0".  Undoing netOffset would
    # therefore INTRODUCE a spurious shift.  We compare raw internal coordinates
    # and let est_translation() absorb any genuine residual offset.
    use_netoffset = False

    def orig_xy(self, x, y):
        if self.use_netoffset:
            return (x - self.netOffset[0], y - self.netOffset[1])
        return (x, y)

    def junc_xy(self):
        return [self.orig_xy(j["x"], j["y"]) for j in self.junctions]

    def edge_feat(self):
        """(midpoint_orig, heading_rad, length) per edge."""
        out = []
        for e in self.edges:
            p = e["pts"]
            if len(p) < 2:
                out.append((None, None))
                continue
            # midpoint along the polyline
            segs = [(p[i], p[i + 1]) for i in range(len(p) - 1)]
            tot = sum(math.dist(a, b) for a, b in segs)
            half, acc, mid = tot / 2.0, 0.0, p[0]
            for a, b in segs:
                d = math.dist(a, b)
                if acc + d >= half and d > 0:
                    f = (half - acc) / d
                    mid = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
                    break
                acc += d
            head = math.atan2(p[-1][1] - p[0][1], p[-1][0] - p[0][0])
            out.append((self.orig_xy(*mid), head))
        return out


def est_translation(A, B, tol, iters=4):
    """Robust residual translation B->A frame: iterated median of NN offsets."""
    tx = ty = 0.0
    for _ in range(iters):
        offs = []
        for bx, by in B:
            bxx, byy = bx + tx, by + ty
            best, bd = None, 1e18
            for ax, ay in A:
                d = (ax - bxx) ** 2 + (ay - byy) ** 2
                if d < bd:
                    bd, best = d, (ax, ay)
            if best and bd < (tol * 5) ** 2:
                offs.append((best[0] - bxx, best[1] - byy))
        if not offs:
            break
        offs.sort(key=lambda o: o[0])
        mx = offs[len(offs) // 2][0]
        offs.sort(key=lambda o: o[1])
        my = offs[len(offs) // 2][1]
        tx += mx
        ty += my
        if abs(mx) < 1e-9 and abs(my) < 1e-9:
            break
    return tx, ty


def greedy_match(costfn, na, nb, maxcost):
    """Greedy min-cost 1:1 matching. Returns list of (ia, ib, cost)."""
    cand = []
    for ia in range(na):
        for ib in range(nb):
            c = costfn(ia, ib)
            if c is not None and c <= maxcost:
                cand.append((c, ia, ib))
    cand.sort()
    ua, ub, out = set(), set(), []
    for c, ia, ib in cand:
        if ia in ua or ib in ub:
            continue
        ua.add(ia)
        ub.add(ib)
        out.append((ia, ib, c))
    return out


def stats(v):
    if not v:
        return {"n": 0}
    s = sorted(v)
    n = len(s)
    mean = sum(s) / n

    def q(p):
        return s[min(n - 1, int(p * n))]
    return {"n": n, "mean": round(mean, 4), "median": round(q(.5), 4),
            "p90": round(q(.9), 4), "p95": round(q(.95), 4),
            "min": round(s[0], 4), "max": round(s[-1], 4),
            "abs_mean": round(sum(abs(x) for x in s) / n, 4)}


def lane_km_by_vclass(net):
    out = {}
    for vc in VCLASSES:
        m = 0.0
        for e in net.edges:
            for L, perm in zip(e["lane_len"], e["perm"]):
                if vc in perm:
                    m += L
        out[vc] = round(m / 1000.0, 4)
    return out


def lane_km_by_role(net):
    """Functional lane roles -- much more diagnostic than raw per-vclass totals,
    because a round trip that turns a sidewalk into an unrestricted lane keeps
    'pedestrian lane-km' roughly constant while completely destroying the
    sidewalk/carriageway distinction."""
    roles = {"car": 0.0, "ped_only": 0.0, "bike_only": 0.0,
             "ped_or_bike_only": 0.0, "blocked": 0.0, "unrestricted": 0.0}
    for e in net.edges:
        for L, p in zip(e["lane_len"], e["perm"]):
            if not p:
                roles["blocked"] += L
            elif "passenger" in p:
                roles["car"] += L
                if p >= ALL:
                    roles["unrestricted"] += L
            elif p == {"pedestrian"}:
                roles["ped_only"] += L
            elif p == {"bicycle"}:
                roles["bike_only"] += L
            elif p <= {"pedestrian", "bicycle", "delivery", "moped"}:
                roles["ped_or_bike_only"] += L
    return {k: round(v / 1000.0, 4) for k, v in roles.items()}


def diff(a_path, b_path, junc_tol=25.0, edge_tol=25.0, angle_tol=35.0):
    A, B = Net(a_path), Net(b_path)
    ja, jb = A.junc_xy(), B.junc_xy()
    tx, ty = est_translation(ja, jb, junc_tol)
    jb_t = [(x + tx, y + ty) for x, y in jb]

    # --- junction matching
    jm = greedy_match(lambda i, k: math.dist(ja[i], jb_t[k]), len(ja), len(jb_t), junc_tol)
    joff = [c for _, _, c in jm]

    # --- edge matching
    fa, fb = A.edge_feat(), B.edge_feat()
    fb_t = [((p[0] + tx, p[1] + ty), h) if p else (None, None) for p, h in fb]
    at = math.radians(angle_tol)

    def ecost(i, k):
        pa, ha = fa[i]
        pb, hb = fb_t[k]
        if pa is None or pb is None:
            return None
        d = math.dist(pa, pb)
        if d > edge_tol:
            return None
        dh = abs((ha - hb + math.pi) % (2 * math.pi) - math.pi)
        if dh > at:
            return None
        return d + 5.0 * dh
    em = greedy_match(ecost, len(fa), len(fb_t), edge_tol + 5 * at)

    dlen = [B.edges[k]["length"] - A.edges[i]["length"] for i, k, _ in em]
    rlen = [(B.edges[k]["length"] - A.edges[i]["length"]) / A.edges[i]["length"] * 100
            for i, k, _ in em if A.edges[i]["length"] > 0]
    dspd = [B.edges[k]["speed"] - A.edges[i]["speed"] for i, k, _ in em]
    dlan = [B.edges[k]["nlanes"] - A.edges[i]["nlanes"] for i, k, _ in em]

    # --- tls matching by junction position
    ta = [t for t in A.tls if t["pos"]]
    tb = [t for t in B.tls if t["pos"]]
    tap = [A.orig_xy(*t["pos"]) for t in ta]
    tbp = [(lambda p: (p[0] + tx, p[1] + ty))(B.orig_xy(*t["pos"])) for t in tb]
    tm = greedy_match(lambda i, k: math.dist(tap[i], tbp[k]), len(tap), len(tbp), junc_tol * 2)
    tls_pairs = []
    for i, k, c in tm:
        pa, pb = ta[i], tb[k]
        tls_pairs.append({
            "orig_id": pa["id"], "rt_id": pb["id"], "pos_offset_m": round(c, 2),
            "phases": [pa["nphases"], pb["nphases"]],
            "cycle_s": [pa["cycle"], pb["cycle"]],
            "nlinks": [pa["nlinks"], pb["nlinks"]],
            "states_identical": pa["states"] == pb["states"],
            "type": [pa["type"], pb["type"]],
        })

    def counts(N):
        return {
            "edges": len(N.edges),
            "lanes": sum(e["nlanes"] for e in N.edges),
            "connections": len(N.conns),
            "junctions_by_type": dict(Counter(j["type"] for j in N.junctions)),
            "junctions_total": len(N.junctions),
            "roundabout_decls": len(N.roundabouts),
            "tlLogic": len(N.tls),
            "lane_km": round(sum(sum(e["lane_len"]) for e in N.edges) / 1000.0, 4),
            "edge_km": round(sum(e["length"] for e in N.edges) / 1000.0, 4),
            "speed_hist": dict(Counter(round(e["speed"], 2) for e in N.edges).most_common(10)),
            "lane_km_by_vclass": lane_km_by_vclass(N),
            "lane_km_by_role": lane_km_by_role(N),
            "edge_priority_hist": dict(Counter(e["priority"] for e in N.edges).most_common(8)),
            "edges_with_name": sum(1 for e in N.edges if e.get("name")),
            "netOffset": N.netOffset,
        }

    return {
        "orig_file": a_path, "rt_file": b_path,
        "frame_residual_translation_m": [round(tx, 3), round(ty, 3)],
        "orig": counts(A), "roundtrip": counts(B),
        "matching": {
            "junctions_matched": len(jm),
            "junctions_orig": len(ja), "junctions_rt": len(jb),
            "junction_match_rate": round(len(jm) / max(1, len(ja)), 4),
            "junction_offset_m": stats(joff),
            "edges_matched": len(em),
            "edges_orig": len(fa), "edges_rt": len(fb),
            "edge_match_rate": round(len(em) / max(1, len(fa)), 4),
            "edge_len_diff_m": stats(dlen),
            "edge_len_diff_pct": stats(rlen),
            "edge_len_exact_(<0.01m)": sum(1 for d in dlen if abs(d) < 0.01),
            "edge_speed_diff_ms": stats(dspd),
            "edge_speed_exact": sum(1 for d in dspd if abs(d) < 1e-6),
            "edge_lanecount_diff": dict(Counter(dlan)),
        },
        "tls": {"orig": len(A.tls), "roundtrip": len(B.tls),
                "matched": len(tls_pairs),
                "phase_count_identical": sum(1 for p in tls_pairs if p["phases"][0] == p["phases"][1]),
                "cycle_identical": sum(1 for p in tls_pairs if abs(p["cycle_s"][0] - p["cycle_s"][1]) < 1e-6),
                "state_strings_identical": sum(1 for p in tls_pairs if p["states_identical"]),
                "pairs": tls_pairs[:40]},
    }


def render(d, label=""):
    o, r, m = d["orig"], d["roundtrip"], d["matching"]
    L = []
    A = L.append
    A(f"### {label or ''}  {d['orig_file']}  ->  {d['rt_file']}")
    A(f"frame residual translation applied to round-trip: {d['frame_residual_translation_m']} m")
    A("")
    A("| metric | original | round-trip | delta |")
    A("|---|---|---|---|")

    def row(k, a, b, fmt="{}"):
        try:
            dl = f"{b - a:+g}"
        except TypeError:
            dl = "-"
        A(f"| {k} | {fmt.format(a)} | {fmt.format(b)} | {dl} |")
    for k in ["edges", "lanes", "connections", "junctions_total", "roundabout_decls", "tlLogic"]:
        row(k, o[k], r[k])
    row("lane-km", o["lane_km"], r["lane_km"])
    row("edge-km", o["edge_km"], r["edge_km"])
    allt = sorted(set(o["junctions_by_type"]) | set(r["junctions_by_type"]))
    for t in allt:
        row(f"junction type '{t}'", o["junctions_by_type"].get(t, 0), r["junctions_by_type"].get(t, 0))
    for vc in VCLASSES:
        a, b = o["lane_km_by_vclass"][vc], r["lane_km_by_vclass"][vc]
        if a or b:
            row(f"lane-km allow '{vc}'", a, b)
    for k in o["lane_km_by_role"]:
        row(f"lane-km role '{k}'", o["lane_km_by_role"][k], r["lane_km_by_role"][k])
    A(f"| edge priority hist | {o['edge_priority_hist']} | {r['edge_priority_hist']} | - |")
    row("edges carrying street name", o["edges_with_name"], r["edges_with_name"])
    A("")
    A(f"junctions matched {m['junctions_matched']}/{m['junctions_orig']} "
      f"(rate {m['junction_match_rate']}), offset m: {m['junction_offset_m']}")
    A(f"edges matched {m['edges_matched']}/{m['edges_orig']} (rate {m['edge_match_rate']})")
    A(f"  edge length diff (m): {m['edge_len_diff_m']}")
    A(f"  edge length diff (%): {m['edge_len_diff_pct']}")
    A(f"  edges with |dlen|<0.01 m: {m['edge_len_exact_(<0.01m)']}/{m['edges_matched']}")
    A(f"  edge speed diff (m/s): {m['edge_speed_diff_ms']}   exact: {m['edge_speed_exact']}/{m['edges_matched']}")
    A(f"  matched-edge lane-count delta histogram: {m['edge_lanecount_diff']}")
    t = d["tls"]
    A(f"TLS: orig {t['orig']} -> rt {t['roundtrip']}, matched {t['matched']}; "
      f"same phase count {t['phase_count_identical']}, same cycle {t['cycle_identical']}, "
      f"identical phase strings {t['state_strings_identical']}")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("roundtrip")
    ap.add_argument("--json")
    ap.add_argument("--label", default="")
    ap.add_argument("--junc-tol", type=float, default=25.0)
    ap.add_argument("--edge-tol", type=float, default=25.0)
    ap.add_argument("--angle-tol", type=float, default=35.0)
    a = ap.parse_args()
    d = diff(a.orig, a.roundtrip, a.junc_tol, a.edge_tol, a.angle_tol)
    print(render(d, a.label))
    if a.json:
        json.dump(d, open(a.json, "w"), indent=1, default=str)
