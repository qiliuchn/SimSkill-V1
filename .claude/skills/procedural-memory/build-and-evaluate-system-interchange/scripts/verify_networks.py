#!/usr/bin/env python3
"""
Verify the three compiled system-interchange networks DIRECTLY FROM THE .net.xml
(never from the authored source XML), and write a machine-readable report.

Checks
------
1  grade separation   : zero <connection> elements join a freeway-A edge to a
                        freeway-B edge; no node is shared between the two mainlines;
                        actual z separation at the crossing.
2  weaving topology   : the lane fed by the loop-ON ramp and the lane drained by the
                        loop-OFF ramp are the SAME lane of the SAME edge (the shared
                        auxiliary lane that defines a weaving section), and the
                        measured length of that edge.
3  ramp geometry      : compiled length, fitted radius, max grade, posted speed of
                        every ramp; minimum plan clearance between every pair of ramp
                        polylines, and the z separation wherever two roadways cross.
4  connection health  : every lane has >=1 predecessor and >=1 successor (except at
                        the network's own terminals); internal-link speed reductions.
5  routability        : all 12 OD movements route with duarouter.
"""
import itertools
import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NETDIR = os.path.join(EPISODE, "outputs", "networks")

CW = ["EB", "NB", "WB", "SB"]
FWY_A = {"EB", "WB"}          # freeway A carriageways (z = 0)
FWY_B = {"NB", "SB"}          # freeway B carriageways (elevated)

# the 12 movements: (origin leg, destination leg) -> (from-edge suffix, to-edge suffix)
LEG_ORIGIN = {"A-West": "EB", "B-South": "NB", "A-East": "WB", "B-North": "SB"}
LEG_DEST = {"A-East": "EB", "B-North": "NB", "A-West": "WB", "B-South": "SB"}
MOVEMENTS = [(o, d) for o in LEG_ORIGIN for d in LEG_DEST
             if LEG_DEST[d] != {"EB": "WB", "NB": "SB", "WB": "EB", "SB": "NB"}[LEG_ORIGIN[o]]]


def load(variant):
    path = os.path.join(NETDIR, variant, "%s.net.xml" % variant)
    root = ET.parse(path).getroot()
    edges, lanes = {}, {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            continue
        ls = []
        for l in e.findall("lane"):
            pts = [tuple(float(v) for v in p.split(",")) for p in l.get("shape").split()]
            pts = [p if len(p) == 3 else (p[0], p[1], 0.0) for p in pts]
            rec = dict(id=l.get("id"), index=int(l.get("index")),
                       length=float(l.get("length")), speed=float(l.get("speed")),
                       shape=pts, edge=e.get("id"))
            ls.append(rec)
            lanes[rec["id"]] = rec
        edges[e.get("id")] = dict(id=e.get("id"), frm=e.get("from"), to=e.get("to"),
                                  lanes=ls, n=len(ls),
                                  length=ls[0]["length"] if ls else 0.0,
                                  speed=ls[0]["speed"] if ls else 0.0)
    conns = [dict(f=c.get("from"), t=c.get("to"),
                  fl=int(c.get("fromLane")), tl=int(c.get("toLane")),
                  via=c.get("via"))
             for c in root.iter("connection") if not c.get("from", "").startswith(":")]
    internal = {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            for l in e.findall("lane"):
                internal[l.get("id")] = dict(length=float(l.get("length")),
                                             speed=float(l.get("speed")))
    junctions = {j.get("id"): (float(j.get("x")), float(j.get("y")), float(j.get("z") or 0.0))
                 for j in root.iter("junction") if j.get("type") != "internal"}
    return edges, lanes, conns, internal, junctions


def z_near_origin(edges, group):
    """z of the given freeway's mainline where it passes the crossing point, obtained by
    interpolating along the compiled lane polyline (shape points can be far apart)."""
    best = (float("inf"), 0.0)
    for e in edges.values():
        if carriageway_of(e["id"]) not in group:
            continue
        for l in e["lanes"]:
            sh = l["shape"]
            for i in range(len(sh) - 1):
                a, b = sh[i], sh[i + 1]
                dx, dy = b[0] - a[0], b[1] - a[1]
                dd = dx * dx + dy * dy
                t = 0.0 if dd == 0 else max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / dd))
                px, py = a[0] + t * dx, a[1] + t * dy
                d = math.hypot(px, py)
                if d < best[0]:
                    best = (d, a[2] + t * (b[2] - a[2]))
    return round(best[1], 2)


def carriageway_of(eid):
    """which mainline carriageway (if any) an edge belongs to."""
    for c in CW:
        if eid.startswith(c + "_"):
            return c
    return None


def fitted_radius(pts):
    """median local radius of curvature of a polyline (3-point circumcircle)."""
    rs = []
    for i in range(1, len(pts) - 1):
        (x1, y1), (x2, y2), (x3, y3) = pts[i - 1][:2], pts[i][:2], pts[i + 1][:2]
        a = math.dist((x1, y1), (x2, y2))
        b = math.dist((x2, y2), (x3, y3))
        c = math.dist((x1, y1), (x3, y3))
        area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0
        if area > 1e-6:
            rs.append(a * b * c / (4 * area))
    if not rs:
        return float("inf")
    rs.sort()
    return rs[len(rs) // 2]


def max_grade(pts):
    g = 0.0
    for i in range(len(pts) - 1):
        d = math.dist(pts[i][:2], pts[i + 1][:2])
        if d > 1.0:
            g = max(g, abs(pts[i + 1][2] - pts[i][2]) / d * 100.0)
    return g


def polyline_crossings(p, q):
    """all planar intersections of two 3-D polylines; yields (x, y, z_on_p, z_on_q)."""
    out = []
    for i in range(len(p) - 1):
        a, b = p[i], p[i + 1]
        rx, ry = b[0] - a[0], b[1] - a[1]
        for j in range(len(q) - 1):
            c, d = q[j], q[j + 1]
            sx, sy = d[0] - c[0], d[1] - c[1]
            den = rx * sy - ry * sx
            if abs(den) < 1e-12:
                continue
            t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
            u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                out.append((a[0] + t * rx, a[1] + t * ry,
                            a[2] + t * (b[2] - a[2]), c[2] + u * (d[2] - c[2])))
    return out


def seg_min_dist(p, q):
    """min 2-D distance between two polylines, plus the z gap at the closest approach."""
    best = (float("inf"), None, None)
    for i in range(len(p) - 1):
        for j in range(len(q) - 1):
            for a in (p[i], p[i + 1]):
                for b in (q[j], q[j + 1]):
                    d = math.dist(a[:2], b[:2])
                    if d < best[0]:
                        best = (d, a, b)
    return best


def verify(variant):
    edges, lanes, conns, internal, junctions = load(variant)
    rep = {"variant": variant}

    # ---- 1 grade separation ------------------------------------------------
    cross = []
    for c in conns:
        ca, cb = carriageway_of(c["f"]), carriageway_of(c["t"])
        if ca and cb and ((ca in FWY_A) != (cb in FWY_A)):
            cross.append((c["f"], c["t"]))
    a_nodes = {e["frm"] for e in edges.values() if carriageway_of(e["id"]) in FWY_A}
    a_nodes |= {e["to"] for e in edges.values() if carriageway_of(e["id"]) in FWY_A}
    b_nodes = {e["frm"] for e in edges.values() if carriageway_of(e["id"]) in FWY_B}
    b_nodes |= {e["to"] for e in edges.values() if carriageway_of(e["id"]) in FWY_B}
    rep["grade_separation"] = {
        "direct_A_to_B_connections": len(cross),
        "examples": cross[:5],
        "shared_mainline_nodes": sorted(a_nodes & b_nodes),
        "z_at_crossing_A": z_near_origin(edges, FWY_A),
        "z_at_crossing_B": z_near_origin(edges, FWY_B),
    }
    rep["grade_separation"]["deck_clearance_m"] = round(
        rep["grade_separation"]["z_at_crossing_B"] - rep["grade_separation"]["z_at_crossing_A"], 2)

    # ---- 2 weaving topology ------------------------------------------------
    weave = {}
    for c in CW:
        loop_on = [x for x in conns if x["f"].lower().startswith(("loop", "cdloop"))
                   and x["f"].endswith("_" + c)]
        loop_off = [x for x in conns if x["t"].lower().startswith(("loop", "cdloop"))
                    and x["t"].split("_")[1] == c]
        if not loop_on or not loop_off:
            weave[c] = {"shared_aux_lane": False,
                        "note": "no loop-on/loop-off pair on this carriageway "
                                "(%d on, %d off)" % (len(loop_on), len(loop_off))}
            continue
        on_lane = "%s_%d" % (loop_on[0]["t"], loop_on[0]["tl"])
        off_lane = "%s_%d" % (loop_off[0]["f"], loop_off[0]["fl"])
        eid = loop_on[0]["t"]
        weave[c] = {
            "shared_aux_lane": on_lane == off_lane,
            "loop_on_feeds": on_lane,
            "loop_off_drains": off_lane,
            "weave_edge": eid,
            "weave_edge_lanes": edges[eid]["n"] if eid in edges else None,
            "weave_length_m": round(edges[eid]["length"], 1) if eid in edges else None,
            "weave_speed_ms": edges[eid]["speed"] if eid in edges else None,
            "loop_on_edge": loop_on[0]["f"],
            "loop_off_edge": loop_off[0]["t"],
        }
    rep["weaving"] = weave

    # ---- 3 ramp geometry ---------------------------------------------------
    ramp_ids = [e for e in edges if e.startswith(("loop", "cdloop", "outer", "cdouter", "fly"))]
    ramps = {}
    for rid in sorted(ramp_ids):
        sh = edges[rid]["lanes"][0]["shape"]
        ramps[rid] = dict(length_m=round(edges[rid]["length"], 1),
                          lanes=edges[rid]["n"],
                          speed_ms=edges[rid]["speed"],
                          speed_kmh=round(edges[rid]["speed"] * 3.6, 1),
                          fitted_radius_m=round(fitted_radius(sh), 1),
                          max_grade_pct=round(max_grade(sh), 2))
    rep["ramps"] = ramps

    # min plan clearance between ramp centrelines
    worst = []
    for a, b in itertools.combinations(sorted(ramp_ids), 2):
        pa = edges[a]["lanes"][0]["shape"]
        pb = edges[b]["lanes"][0]["shape"]
        d, ka, kb = seg_min_dist(pa, pb)
        if d < 40.0:
            worst.append(dict(pair=[a, b], plan_clearance_m=round(d, 1),
                              z_gap_m=round(abs(ka[2] - kb[2]), 1) if ka else None,
                              at=[round(ka[0], 1), round(ka[1], 1)] if ka else None))
    worst.sort(key=lambda r: r["plan_clearance_m"])
    rep["ramp_pair_min_clearance"] = worst[:12]

    # ---- 3b every PLANAR CROSSING of two edges that share no junction ------
    # This is the real grade-separation test: SUMO will not create a junction where two
    # edges merely cross in plan, so any such crossing is a physical structure that must
    # have vertical clearance.  Checking connection topology alone would not catch a
    # flyover that passes through a mainline at the same elevation.
    ids = sorted(edges)
    crossings = []
    for a, b in itertools.combinations(ids, 2):
        ea, eb = edges[a], edges[b]
        if {ea["frm"], ea["to"]} & {eb["frm"], eb["to"]}:
            continue                       # adjacent edges: they meet at a junction
        for hit in polyline_crossings(ea["lanes"][0]["shape"], eb["lanes"][0]["shape"]):
            crossings.append(dict(edges=[a, b], at=[round(hit[0], 1), round(hit[1], 1)],
                                  z_a=round(hit[2], 2), z_b=round(hit[3], 2),
                                  clearance_m=round(abs(hit[2] - hit[3]), 2)))
    crossings.sort(key=lambda r: r["clearance_m"])
    rep["planar_crossings"] = {
        "n_crossings": len(crossings),
        "min_clearance_m": crossings[0]["clearance_m"] if crossings else None,
        "violations_below_4.5m": [c for c in crossings if c["clearance_m"] < 4.5],
        "tightest": crossings[:8],
    }

    # ---- 4 connection health ----------------------------------------------
    have_succ, have_pred = set(), set()
    for c in conns:
        have_succ.add("%s_%d" % (c["f"], c["fl"]))
        have_pred.add("%s_%d" % (c["t"], c["tl"]))
    terminals = set()
    for e in edges.values():
        if e["frm"].endswith("_n0"):
            terminals |= {l["id"] for l in e["lanes"]}
    sinks = set()
    for e in edges.values():
        if e["to"].endswith(("_n5", "_n7", "_n9")) and e["id"].endswith(("_out", "_out2")):
            sinks |= {l["id"] for l in e["lanes"]}
    dead_lanes = sorted(l for l in lanes
                        if l not in have_succ and not lanes[l]["edge"].endswith(("_out", "_out2")))
    orphan_lanes = sorted(l for l in lanes if l not in have_pred and l not in terminals)
    rep["connection_health"] = {
        "lanes_without_successor": dead_lanes,
        "lanes_without_predecessor": orphan_lanes,
        "n_internal_lanes": len(internal),
        "longest_internal_lane_m": round(max(v["length"] for v in internal.values()), 1),
        # netconvert silently caps the speed of a curved internal link; a big cap at a
        # gore would throttle the ramp independently of its posted speed limit
        "internal_links_below_15ms": sorted(
            [(k, round(v["speed"], 2), round(v["length"], 1))
             for k, v in internal.items() if v["speed"] < 15.0],
            key=lambda t: t[1])[:10],
    }

    # ---- 5 routability -----------------------------------------------------
    net = os.path.join(NETDIR, variant, "%s.net.xml" % variant)
    tdir = os.path.join(NETDIR, variant)
    trips = os.path.join(tdir, "verify12.trips.xml")
    with open(trips, "w") as fh:
        fh.write("<routes>\n")
        for i, (o, d) in enumerate(MOVEMENTS):
            fh.write('  <trip id="%s__%s" depart="%d" from="%s" to="%s"/>\n'
                     % (o, d, i, from_edge(edges, LEG_ORIGIN[o]), to_edge(edges, LEG_DEST[d])))
        fh.write("</routes>\n")
    out = os.path.join(tdir, "verify12.rou.xml")
    r = subprocess.run(["duarouter", "-n", net, "-r", trips, "-o", out,
                        "--ignore-errors", "false", "--no-step-log", "true"],
                       capture_output=True, text=True)
    routed = {}
    if os.path.exists(out):
        for v in ET.parse(out).getroot().iter("vehicle"):
            rt = v.find("route")
            edges_seq = rt.get("edges").split()
            dist = sum(edges[e]["length"] for e in edges_seq if e in edges)
            routed[v.get("id")] = dict(n_edges=len(edges_seq),
                                       edge_length_sum_m=round(dist, 1),
                                       route=" ".join(edges_seq))
    rep["routability"] = {
        "duarouter_rc": r.returncode,
        "movements_expected": len(MOVEMENTS),
        "movements_routed": len(routed),
        "all_routed": len(routed) == len(MOVEMENTS),
        "stderr_tail": (r.stderr or "").strip().splitlines()[-3:],
        "routes": routed,
    }
    return rep


def from_edge(edges, cwname):
    for cand in ("%s_in" % cwname,):
        if cand in edges:
            return cand
    raise KeyError(cwname)


def to_edge(edges, cwname):
    for cand in ("%s_out" % cwname,):
        if cand in edges:
            return cand
    raise KeyError(cwname)


def main():
    reports = {}
    for v in (sys.argv[1:] or ["clover", "cd", "flyover"]):
        reports[v] = verify(v)
    outp = os.path.join(EPISODE, "outputs", "tables", "network_verification.json")
    with open(outp, "w") as fh:
        json.dump(reports, fh, indent=1)

    for v, rep in reports.items():
        print("=" * 78)
        print("VARIANT:", v)
        g = rep["grade_separation"]
        print("  grade separation : direct A<->B connections = %d (want 0); shared mainline nodes = %s"
              % (g["direct_A_to_B_connections"], g["shared_mainline_nodes"] or "none"))
        print("                     z at crossing: freeway A = %.2f m, freeway B = %.2f m"
              % (g["z_at_crossing_A"], g["z_at_crossing_B"]))
        for c, w in rep["weaving"].items():
            if w["shared_aux_lane"]:
                print("  weave %-3s        : SHARED aux lane %s on %s (%d lanes, %.1f m, %.0f km/h)"
                      % (c, w["loop_on_feeds"], w["weave_edge"], w["weave_edge_lanes"],
                         w["weave_length_m"], w["weave_speed_ms"] * 3.6))
            else:
                print("  weave %-3s        : NO shared aux lane -- %s"
                      % (c, w.get("note", "on=%s off=%s" % (w.get("loop_on_feeds"),
                                                            w.get("loop_off_drains")))))
        print("  ramps:")
        for rid, rr in rep["ramps"].items():
            print("    %-16s %6.1f m  %d lane(s)  R=%7.1f m  %4.0f km/h  max grade %.2f%%"
                  % (rid, rr["length_m"], rr["lanes"], rr["fitted_radius_m"],
                     rr["speed_kmh"], rr["max_grade_pct"]))
        print("  tightest ramp-pair clearances (plan / z):")
        for w in rep["ramp_pair_min_clearance"][:4]:
            print("    %-32s %6.1f m  (z gap %.1f m)"
                  % (" x ".join(w["pair"]), w["plan_clearance_m"], w["z_gap_m"]))
        pc = rep["planar_crossings"]
        print("  planar crossings : %d structures; min vertical clearance %.2f m; "
              "%d below 4.5 m" % (pc["n_crossings"], pc["min_clearance_m"] or 0.0,
                                  len(pc["violations_below_4.5m"])))
        for c in pc["tightest"][:3]:
            print("    %-28s at (%7.1f,%7.1f)  z %5.2f / %5.2f -> %.2f m"
                  % (" x ".join(c["edges"]), c["at"][0], c["at"][1],
                     c["z_a"], c["z_b"], c["clearance_m"]))
        ch = rep["connection_health"]
        print("  connections      : %d lanes w/o successor, %d w/o predecessor; "
              "longest internal lane %.1f m"
              % (len(ch["lanes_without_successor"]), len(ch["lanes_without_predecessor"]),
                 ch["longest_internal_lane_m"]))
        if ch["lanes_without_successor"]:
            print("      no successor:", ch["lanes_without_successor"][:6])
        if ch["lanes_without_predecessor"]:
            print("      no predecessor:", ch["lanes_without_predecessor"][:6])
        if ch["internal_links_below_15ms"]:
            print("      slow internal links (speed-capped by turn radius):",
                  ch["internal_links_below_15ms"][:4])
        rt = rep["routability"]
        print("  routability      : %d/%d movements routed by duarouter (rc=%d)"
              % (rt["movements_routed"], rt["movements_expected"], rt["duarouter_rc"]))
    print("\nreport ->", outp)
    ok = all(r["grade_separation"]["direct_A_to_B_connections"] == 0
             and not r["grade_separation"]["shared_mainline_nodes"]
             and r["routability"]["all_routed"] for r in reports.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
