#!/usr/bin/env python3
"""
Instrument cut-through as a first-class metric and build the variant comparison.

Reads, per (variant, seed) run:  tripinfo, summary, vehroute, edgedata, emissions,
sumo.log (teleports) and, for the first seed, ssm.xml.
Writes analysis/metrics_by_run.csv, analysis/variant_comparison.csv,
analysis/interior_volumes_<V>.csv, analysis/assertions.json and the spatial maps.
"""
import collections
import csv
import glob
import json
import os
import re
import statistics as st
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "runs", "analysis"))
os.makedirs(ANA, exist_ok=True)

VARIANTS = list("ABCDEF")
SEEDS = [101, 202, 303, 404, 505]
CLASSES = ["ee", "bg", "ei", "ie", "ii"]
LABEL = {"A": "A baseline", "B": "B 20 km/h", "C": "C modal filter",
         "D": "D diagonal diverters", "E": "E one-way loop cells", "F": "F filter + 20 km/h"}

sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
FILTERED = set(sets["FILTERED"])
ONEWAY_REMOVED = set(sets["ONEWAY_REMOVED"])
INTERIOR = set(sets["INTERIOR_STREETS"])
ACCESS = set(sets["ACCESS_CONNECTORS"])
RING = set(sets["RING"])
EXTERNAL = set(sets["EXTERNAL"])

net = sumolib.net.readNet(os.path.join(NET, "A.net.xml"))
LEN = {e.getID(): e.getLength() for e in net.getEdges() if not e.getFunction()}
# ring edges that feed a signalised junction
SIGNAL_APPROACH = set()
for e in net.getEdges():
    if e.getFunction():
        continue
    if e.getID() in RING and e.getToNode().getType() == "traffic_light":
        SIGNAL_APPROACH.add(e.getID())

# banned movements at the diagonal diverters (edge pairs that must never appear
# consecutively in any variant-D route)
DIVERTERS = dict(x.split(":") for x in sets["DIVERTERS"])
netD = sumolib.net.readNet(os.path.join(NET, "D.net.xml"), withConnections=True)
netA = sumolib.net.readNet(os.path.join(NET, "A.net.xml"), withConnections=True)


def movements(n, jid):
    node = n.getNode(jid)
    out = set()
    for e in node.getIncoming():
        for l in e.getLanes():
            for c in l.getOutgoing():
                out.add((e.getID(), c.getTo().getID()))
    return out


BANNED_D = set()
for jid in DIVERTERS:
    BANNED_D |= movements(netA, jid) - movements(netD, jid)


def _open(p):
    """accept either the plain file or a .gz of it (outputs are gzipped after analysis
    to keep the episode folder small; re-running must still work)"""
    if os.path.exists(p):
        return p
    import gzip as _gz
    if os.path.exists(p + ".gz"):
        return _gz.open(p + ".gz")
    raise FileNotFoundError(p)


def cls_of(vid):
    return vid.split("_")[0]


def parse_tripinfo(p):
    return ET.parse(_open(p)).getroot().findall("tripinfo")


def parse_vehroutes(p):
    out = {}
    for v in ET.parse(_open(p)).getroot().iter("vehicle"):
        r = v.find("route")
        if r is None:
            rs = v.find("routeDistribution")
            r = rs.findall("route")[-1] if rs is not None else None
        if r is not None:
            out[v.get("id")] = r.get("edges").split()
    return out


def parse_edgedata(p):
    """aggregate the 300 s intervals; also keep peak-interval density and peak-hour volume"""
    agg = {}
    root = ET.parse(_open(p)).getroot()
    for iv in root.findall("interval"):
        b = float(iv.get("begin"))
        for e in iv.findall("edge"):
            d = agg.setdefault(e.get("id"), collections.Counter())
            for a in ("entered", "sampledSeconds", "waitingTime", "timeLoss", "departed", "left"):
                if e.get(a) is not None:
                    d[a] += float(e.get(a))
            if e.get("speed") is not None and e.get("sampledSeconds") is not None:
                d["_spd_num"] += float(e.get("speed")) * float(e.get("sampledSeconds"))
            if e.get("density") is not None:
                d["_maxdens"] = max(d["_maxdens"], float(e.get("density")))
            if b < 3600 and e.get("entered") is not None:
                d["peakhour_entered"] += float(e.get("entered"))
    return agg


def parse_emissions(p):
    agg = collections.Counter()
    per_edge = collections.defaultdict(collections.Counter)
    for iv in ET.parse(_open(p)).getroot().findall("interval"):
        for e in iv.findall("edge"):
            for a in ("CO2_abs", "NOx_abs", "PMx_abs", "fuel_abs"):
                if e.get(a) is not None:
                    agg[a] += float(e.get(a))
                    per_edge[e.get("id")][a] += float(e.get(a))
    return agg, per_edge


def parse_summary(p):
    last = None
    for s in ET.parse(_open(p)).getroot().findall("step"):
        last = s
    return dict(teleports=int(last.get("teleports")), running=int(last.get("running")),
                inserted=int(last.get("inserted")), ended=int(last.get("ended")))


TELE_RE = re.compile(r"Vehicle '([^']+)'.*teleporting", re.I)


def parse_teleports(p):
    ids = set()
    for line in open(p, errors="ignore"):
        if "teleporting" in line:
            m = TELE_RE.search(line)
            if m:
                ids.add(m.group(1))
    return ids


INTERIOR_BBOX = (190.0, 860.0, 190.0, 860.0)   # x0,x1,y0,y1 of the residential grid


def _inside(pos):
    """SSM sub-elements carry position="x,y"; True if inside the residential grid."""
    if not pos or pos == "NA":
        return False
    try:
        x, y = (float(v) for v in pos.split(",")[:2])
    except ValueError:
        return False
    x0, x1, y0, y1 = INTERIOR_BBOX
    return x0 <= x <= x1 and y0 <= y <= y1


def parse_ssm(p):
    """conflict statistics network-wide AND restricted to the residential interior"""
    if not (os.path.exists(p) or os.path.exists(p + ".gz")):
        return None
    root = ET.parse(_open(p)).getroot()
    res = {}
    for scope in ("net", "interior"):
        ttc, pet, drac, types, n = [], [], [], collections.Counter(), 0
        for c in root.findall("conflict"):
            hit = False
            for tag, lst in (("minTTC", ttc), ("PET", pet), ("maxDRAC", drac)):
                el = c.find(tag)
                if el is None or el.get("value") in (None, "NA"):
                    continue
                if scope == "interior" and not _inside(el.get("position")):
                    continue
                lst.append(float(el.get("value")))
                types[el.get("type")] += 1
                hit = True
            if hit or scope == "net":
                n += 1
        res[scope] = dict(
            conflicts=n, n_ttc=len(ttc), min_ttc=round(min(ttc), 3) if ttc else None,
            ttc_lt_1p5=sum(1 for v in ttc if v < 1.5),
            n_pet=len(pet), min_pet=round(min(pet), 3) if pet else None,
            pet_lt_1p0=sum(1 for v in pet if v < 1.0),
            max_drac=round(max(drac), 3) if drac else None,
            conflict_types=dict(types))
    return res


def analyse_run(v, seed):
    d = os.path.join(RUNS, "sim", "%s_s%d" % (v, seed))
    ti = parse_tripinfo(os.path.join(d, "tripinfo.xml"))
    vr = parse_vehroutes(os.path.join(d, "vehroute.xml"))
    ed = parse_edgedata(os.path.join(d, "edgedata.xml"))
    em, em_edge = parse_emissions(os.path.join(d, "emissions.xml"))
    sm = parse_summary(os.path.join(d, "summary.xml"))
    tele = parse_teleports(os.path.join(d, "sumo.log"))

    r = dict(variant=v, seed=seed)
    # ---------------- trip-level, by OD class ----------------
    by = collections.defaultdict(list)
    for t in ti:
        by[cls_of(t.get("id"))].append(t)
    r["completed_total"] = len(ti)
    r["still_running"] = sm["running"]
    r["inserted"] = sm["inserted"]
    r["teleports_summary"] = sm["teleports"]
    r["teleport_vehicles"] = len(tele)
    r["teleport_share_pct"] = round(100.0 * len(tele) / max(1, len(ti)), 3)
    vkt = vht = 0.0
    for c in CLASSES:
        ts = by[c]
        dur = [float(t.get("duration")) for t in ts]
        rl = [float(t.get("routeLength")) for t in ts]
        tl = [float(t.get("timeLoss")) for t in ts]
        dd = [float(t.get("departDelay")) for t in ts]
        r["n_%s" % c] = len(ts)
        r["dur_%s" % c] = round(st.mean(dur), 2)
        r["totalcost_%s" % c] = round(st.mean([a + b for a, b in zip(dur, dd)]), 2)
        r["dist_%s" % c] = round(st.mean(rl), 1)
        r["timeloss_%s" % c] = round(st.mean(tl), 2)
        r["departdelay_%s" % c] = round(st.mean(dd), 2)
        vkt += sum(rl) / 1000.0
        vht += sum(dur) / 3600.0
    r["VKT_km"] = round(vkt, 1)
    r["VHT_h"] = round(vht, 2)
    r["VHT_incl_departdelay_h"] = round(
        vht + sum(float(t.get("departDelay")) for t in ti) / 3600.0, 2)

    # ---------------- cut-through, from the DRIVEN routes ----------------
    cut = collections.Counter()
    tot = collections.Counter()
    ikm = collections.Counter()      # interior-street veh-km by class
    akm = collections.Counter()      # access-connector veh-km by class
    for vid, edges in vr.items():
        c = cls_of(vid)
        tot[c] += 1
        touched = any(e in INTERIOR for e in edges)
        if touched:
            cut[c] += 1
        ikm[c] += sum(LEN.get(e, 0.0) for e in edges if e in INTERIOR) / 1000.0
        akm[c] += sum(LEN.get(e, 0.0) for e in edges if e in ACCESS) / 1000.0
    for c in CLASSES:
        r["cut_share_%s" % c] = round(100.0 * cut[c] / max(1, tot[c]), 2)
        r["interior_vehkm_%s" % c] = round(ikm[c], 1)
        r["access_vehkm_%s" % c] = round(akm[c], 1)
    r["interior_vehkm_total"] = round(sum(ikm.values()), 1)
    r["cutthrough_vehkm"] = round(ikm["ee"] + ikm["bg"], 1)     # PRIMARY OBJECTIVE
    r["resident_interior_vehkm"] = round(ikm["ei"] + ikm["ie"] + ikm["ii"], 1)

    # ---------------- boundary arterial ----------------
    ring_veh_km = sum(ed.get(e, {}).get("entered", 0.0) * LEN[e] / 1000.0 for e in RING)
    ring_sec = sum(ed.get(e, {}).get("sampledSeconds", 0.0) for e in RING)
    ring_spd = sum(ed.get(e, {}).get("_spd_num", 0.0) for e in RING) / max(1e-9, ring_sec)
    r["ring_vehkm"] = round(ring_veh_km, 1)
    r["ring_vehh"] = round(ring_sec / 3600.0, 2)
    r["ring_mean_speed_ms"] = round(ring_spd, 3)
    r["ring_timeloss_vehh"] = round(sum(ed.get(e, {}).get("timeLoss", 0.0) for e in RING) / 3600.0, 2)
    r["ring_waiting_vehh"] = round(sum(ed.get(e, {}).get("waitingTime", 0.0) for e in RING) / 3600.0, 2)
    r["signal_approach_waiting_vehh"] = round(
        sum(ed.get(e, {}).get("waitingTime", 0.0) for e in SIGNAL_APPROACH) / 3600.0, 2)
    r["ring_max_edge_flow"] = round(max(ed.get(e, {}).get("entered", 0.0) for e in RING), 0)
    # queue proxy: peak vehicles standing on any signal approach
    r["signal_approach_max_waiting_vehh"] = round(
        max(ed.get(e, {}).get("waitingTime", 0.0) for e in SIGNAL_APPROACH) / 3600.0, 3)
    r["ring_peak_density_max_vehkm"] = round(
        max(ed.get(e, {}).get("_maxdens", 0.0) for e in RING), 2)
    r["ring_peak_density_mean_vehkm"] = round(
        st.mean([ed.get(e, {}).get("_maxdens", 0.0) for e in RING]), 2)
    r["ring_peakhour_max_flow"] = round(
        max(ed.get(e, {}).get("peakhour_entered", 0.0) for e in RING), 0)

    # ---------------- interior streets ----------------
    isec = sum(ed.get(e, {}).get("sampledSeconds", 0.0) for e in INTERIOR)
    r["interior_mean_speed_ms"] = round(
        sum(ed.get(e, {}).get("_spd_num", 0.0) for e in INTERIOR) / max(1e-9, isec), 3)
    r["interior_edge_vehkm_edgedata"] = round(
        sum(ed.get(e, {}).get("entered", 0.0) * LEN[e] / 1000.0 for e in INTERIOR), 1)
    vols = {e: ed.get(e, {}).get("peakhour_entered", 0.0) for e in INTERIOR}
    r["interior_max_street_vol"] = round(max(vols.values()), 0)
    nz = [x for x in vols.values() if x > 0]
    r["interior_streets_used"] = len(nz)
    r["interior_p90_street_vol"] = round(sorted(vols.values())[int(0.9 * len(vols))], 0)
    # Gini of interior volume concentration
    xs = sorted(vols.values())
    n = len(xs)
    s = sum(xs)
    r["interior_volume_gini"] = round(
        (sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(xs)) / (n * s)) if s else 0.0, 4)

    # ---------------- emissions ----------------
    for a, k in (("CO2_abs", "CO2_kg"), ("NOx_abs", "NOx_g"), ("PMx_abs", "PMx_g"), ("fuel_abs", "fuel_kg")):
        val = em[a]
        r["net_" + k] = round(val / 1000.0 if k.endswith("kg") else val, 2)
        iv = sum(em_edge[e][a] for e in INTERIOR)
        r["interior_" + k] = round(iv / 1000.0 if k.endswith("kg") else iv, 2)

    # ---------------- SSM (first seed only) ----------------
    r["ssm"] = parse_ssm(os.path.join(d, "ssm.xml"))

    # ---------------- assertions ----------------
    a = {}
    a["filtered_edge_entries_edgedata"] = {e: ed.get(e, {}).get("entered", 0.0) for e in sorted(FILTERED)}
    a["filtered_edge_routes"] = sum(1 for edges in vr.values() if any(e in FILTERED for e in edges))
    a["oneway_removed_in_routes"] = sum(1 for edges in vr.values()
                                        if any(e in ONEWAY_REMOVED for e in edges))
    bad = 0
    for edges in vr.values():
        for p in zip(edges, edges[1:]):
            if p in BANNED_D:
                bad += 1
    a["banned_diverter_movements_in_routes"] = bad
    r["_assert"] = a
    r["_interior_volumes"] = vols
    r["_interior_speed"] = {e: (ed.get(e, {}).get("_spd_num", 0.0) /
                                max(1e-9, ed.get(e, {}).get("sampledSeconds", 0.0)))
                            for e in INTERIOR}
    return r


def main():
    rows = []
    for v in VARIANTS:
        for s in SEEDS:
            _ti = os.path.join(RUNS, "sim", "%s_s%d" % (v, s), "tripinfo.xml")
            if not (os.path.exists(_ti) or os.path.exists(_ti + ".gz")):
                print("MISSING run %s seed %d" % (v, s))
                continue
            rows.append(analyse_run(v, s))
            print("analysed %s s%d" % (v, s), flush=True)

    scalar_keys = [k for k in rows[0] if not k.startswith("_") and k != "ssm"
                   and isinstance(rows[0][k], (int, float))]
    with open(os.path.join(ANA, "metrics_by_run.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "seed"] + scalar_keys)
        for r in rows:
            w.writerow([r["variant"], r["seed"]] + [r[k] for k in scalar_keys])

    # ---- aggregate over seeds ----
    agg = {}
    for v in VARIANTS:
        rs = [r for r in rows if r["variant"] == v]
        if not rs:
            continue
        a = {}
        for k in scalar_keys:
            xs = [r[k] for r in rs]
            a[k] = round(st.mean(xs), 3)
            a[k + "_sd"] = round(st.pstdev(xs) if len(xs) > 1 else 0.0, 3)
        a["n_seeds"] = len(rs)
        a["ssm"] = rs[0]["ssm"]
        a["assert"] = rs[0]["_assert"]
        agg[v] = a
    json.dump(agg, open(os.path.join(ANA, "variant_aggregate.json"), "w"), indent=1)

    # assertions across ALL runs (not just seed 1)
    asserts = {}
    for v in VARIANTS:
        rs = [r for r in rows if r["variant"] == v]
        if not rs:
            continue
        asserts[v] = dict(
            filtered_edge_entries_max=max(max(r["_assert"]["filtered_edge_entries_edgedata"].values())
                                          for r in rs),
            filtered_edge_routes_max=max(r["_assert"]["filtered_edge_routes"] for r in rs),
            oneway_removed_in_routes_max=max(r["_assert"]["oneway_removed_in_routes"] for r in rs),
            banned_diverter_movements_max=max(r["_assert"]["banned_diverter_movements_in_routes"] for r in rs),
            teleport_share_pct_max=max(r["teleport_share_pct"] for r in rs),
            still_running_max=max(r["still_running"] for r in rs),
            completed_min=min(r["completed_total"] for r in rs))
    asserts["_n_banned_diverter_movements_defined"] = len(BANNED_D)
    json.dump(asserts, open(os.path.join(ANA, "assertions.json"), "w"), indent=1)

    # ---- interior spatial volumes (seed-mean) ----
    for v in VARIANTS:
        rs = [r for r in rows if r["variant"] == v]
        if not rs:
            continue
        with open(os.path.join(ANA, "interior_volumes_%s.csv" % v), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["edge", "x_from", "y_from", "x_to", "y_to", "length_m",
                        "veh_per_hour_mean", "mean_speed_ms"])
            for e in sorted(INTERIOR):
                ed = net.getEdge(e)
                (x0, y0) = ed.getFromNode().getCoord()
                (x1, y1) = ed.getToNode().getCoord()
                w.writerow([e, x0, y0, x1, y1, round(LEN[e], 1),
                            round(st.mean([r["_interior_volumes"][e] for r in rs]), 1),
                            round(st.mean([r["_interior_speed"][e] for r in rs]), 3)])

    # ---- comparison table ----
    keys = ["cutthrough_vehkm", "cut_share_ee", "cut_share_bg", "interior_vehkm_total",
            "resident_interior_vehkm", "interior_mean_speed_ms", "interior_max_street_vol",
            "interior_streets_used", "interior_volume_gini",
            "ring_vehkm", "ring_mean_speed_ms", "ring_timeloss_vehh",
            "signal_approach_waiting_vehh", "ring_max_edge_flow", "ring_peakhour_max_flow",
            "ring_peak_density_max_vehkm",
            "VKT_km", "VHT_h", "VHT_incl_departdelay_h",
            "dur_ee", "dist_ee", "dur_bg", "dist_bg", "dur_ei", "dist_ei",
            "dur_ie", "dist_ie", "dur_ii", "dist_ii",
            "net_CO2_kg", "interior_CO2_kg", "net_NOx_g", "interior_NOx_g",
            "completed_total", "still_running", "teleport_vehicles", "teleport_share_pct"]
    with open(os.path.join(ANA, "variant_comparison.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric"] + [LABEL[v] for v in VARIANTS if v in agg] +
                   ["%s_vs_A_pct" % v for v in VARIANTS if v in agg and v != "A"])
        for k in keys:
            base = agg["A"][k]
            row = [k] + [agg[v][k] for v in VARIANTS if v in agg]
            row += [round(100.0 * (agg[v][k] - base) / base, 2) if base else ""
                    for v in VARIANTS if v in agg and v != "A"]
            w.writerow(row)
    print("wrote", os.path.join(ANA, "variant_comparison.csv"))


if __name__ == "__main__":
    main()
