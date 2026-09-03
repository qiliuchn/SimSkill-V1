#!/usr/bin/env python3
"""
Step 6 -- extract emissions at THREE spatial resolutions from the SAME run, and
reconcile them.

  R1  fleet total     : sum over the whole network, analysis hour
  R2  whole edge      : SUMO's own edgeData type="emissions" (withInternal)
  R3  25 m segments   : per-vehicle --emission-output records binned by
                        longitudinal position along the approach/departure

Plus:
  * back-of-queue statistics per approach (from the same trajectory),
  * the fraction of approach emissions produced inside the queue storage length,
  * a mass reconciliation R1 vs R2 vs R3 vs tripinfo.

CRITICAL UNIT FINDING (verified, see outputs/analysis/emission_output_units.txt):
--emission-output values are RATES in mg/s, NOT per-step masses.  Mass therefore
requires multiplying by --step-length.  At step-length 1.0 the two coincide
numerically, which hides the bug; at 0.5 s a naive sum is exactly 2x too high.

Segment geometry convention
---------------------------
Distance is measured from the STOP LINE (the junction end of an incoming edge /
the junction end of an outgoing edge):
    incoming edge in_X : d = laneLength - pos   (d=0 at stop line, grows upstream)
    outgoing edge out_X: d = pos                (d=0 at stop line, grows downstream)
Bin index = floor(d / 25).  Junction-internal lanes (":center_*") are kept as
their own single segments at their own geometry.
"""
import argparse
import csv
import gzip
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import sumolib  # noqa: E402

POLL = ["CO2", "CO", "HC", "NOx", "PMx", "fuel"]
SEG_LEN = 25.0
WARMUP, END = 900, 4500
STEP = 1.0
STOP_SPEED = 1.39      # m/s (5 km/h) -- "in queue" threshold

VEH_RE = re.compile(r'<vehicle ([^>]*)/>')
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def edge_centerline(net, eid):
    """Mean of the edge's lane shapes, resampled to a common parameterisation."""
    e = net.getEdge(eid)
    lanes = e.getLanes()
    n = 21
    pts = []
    for i in range(n):
        s = i / (n - 1) * e.getLength()
        xs, ys = 0.0, 0.0
        for ln in lanes:
            x, y = sumolib.geomhelper.positionAtShapeOffset(
                ln.getShape(), min(s, ln.getLength() - 1e-6))
            xs += x; ys += y
        pts.append((xs / len(lanes), ys / len(lanes)))
    return pts


def point_on(pts, edge_len, s):
    """Interpolate the resampled centerline at arclength s (0..edge_len)."""
    n = len(pts)
    t = max(0.0, min(1.0, s / edge_len)) * (n - 1)
    i = int(math.floor(t))
    if i >= n - 1:
        return pts[-1]
    f = t - i
    return (pts[i][0] + f * (pts[i + 1][0] - pts[i][0]),
            pts[i][1] + f * (pts[i + 1][1] - pts[i][1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scenario", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    net = sumolib.net.readNet(a.net, withInternal=True)
    # GOTCHA: netconvert re-origins the network so all coordinates are positive
    # (the junction that generate_intersection.py placed at (0,0) ends up at
    # exactly (400.0, 400.0), verified from both the pre-netconvert .nod.xml
    # and the compiled .net.xml). Every geometry written below is TRANSLATED so the
    # signalised junction sits at (0,0) -- otherwise the dispersion model
    # receives sources ~570 m from its receptor grid origin and silently
    # produces a monotone field with its peak pinned to a grid corner.
    CX, CY = net.getNode("center").getCoord()
    print(f"junction 'center' raw coordinate = ({CX:.2f}, {CY:.2f}); "
          f"all segment geometry translated by (-{CX:.2f}, -{CY:.2f})")

    approach = {f"in_{x}": net.getEdge(f"in_{x}").getLength() for x in "NESW"}
    depart = {f"out_{x}": net.getEdge(f"out_{x}").getLength() for x in "NESW"}
    center = {eid: (edge_centerline(net, eid), L)
              for eid, L in list(approach.items()) + list(depart.items())}

    # ---------------- R3: bin the trajectory --------------------------------
    seg = {}          # (edge, bin) -> {pollutant: mg}
    internal = {}     # internal lane id -> {pollutant: mg}
    fleet = {p: 0.0 for p in POLL}
    boq = {e: {} for e in approach}      # edge -> time -> back-of-queue (m)
    nrec = 0
    path = os.path.join(a.run_dir, "emissions.xml.gz")
    opener = gzip.open if path.endswith(".gz") else open
    t = None
    with opener(path, "rt") as f:
        for line in f:
            if "<timestep" in line:
                t = float(line.split('time="')[1].split('"')[0])
                continue
            if "<vehicle " not in line:
                continue
            if t is None or not (WARMUP <= t < END):
                continue
            m = VEH_RE.search(line)
            d = dict(ATTR_RE.findall(m.group(1)))
            lane = d["lane"]
            nrec += 1
            vals = {p: float(d[p]) * STEP for p in POLL}   # mg/s * s = mg
            for p in POLL:
                fleet[p] += vals[p]
            if lane.startswith(":"):
                tgt = internal.setdefault(lane, {p: 0.0 for p in POLL})
                for p in POLL:
                    tgt[p] += vals[p]
                continue
            eid = lane.rsplit("_", 1)[0]
            pos = float(d["pos"])
            if eid in approach:
                L = approach[eid]
                dist = L - pos
                spd = float(d["speed"])
                if spd < STOP_SPEED:
                    cur = boq[eid].get(t, 0.0)
                    if dist > cur:
                        boq[eid][t] = dist
            elif eid in depart:
                dist = pos
            else:
                continue
            b = int(dist // SEG_LEN)
            tgt = seg.setdefault((eid, b), {p: 0.0 for p in POLL})
            for p in POLL:
                tgt[p] += vals[p]

    # ---------------- R2: edgeData ------------------------------------------
    edge_tot = {}
    root = ET.parse(os.path.join(a.run_dir, "edge_emissions.xml")).getroot()
    for iv in root.iter("interval"):
        for e in iv.iter("edge"):
            edge_tot[e.get("id")] = {p: float(e.get(f"{p}_abs", 0.0)) for p in POLL}

    # ---------------- tripinfo totals (whole trips) -------------------------
    tri = {p: 0.0 for p in POLL}
    tri_win = {p: 0.0 for p in POLL}
    for _, el in ET.iterparse(os.path.join(a.run_dir, "tripinfo.xml"), events=("end",)):
        # GOTCHA (verified bug, cost one full re-run): do NOT el.clear() the
        # non-<tripinfo> elements here.  <emissions> is a CHILD of <tripinfo>
        # and its "end" event fires FIRST; clearing it wipes its attributes, so
        # the parent's later el.find("emissions").get("NOx_abs") silently
        # returns the default 0.0 and the whole tripinfo cross-check reads zero.
        if el.tag != "tripinfo":
            continue
        em = el.find("emissions")
        if em is not None:
            for p in POLL:
                v = float(em.get(f"{p}_abs", 0.0))
                tri[p] += v
                if WARMUP <= float(el.get("depart")) < END:
                    tri_win[p] += v
        el.clear()

    # ---------------- queue storage length ----------------------------------
    qstats = {}
    for e in approach:
        series = [boq[e].get(float(tt), 0.0) for tt in range(WARMUP, END)]
        series_sorted = sorted(series)
        n = len(series_sorted)
        qstats[e] = {
            "mean_back_of_queue_m": sum(series) / n,
            "p50_m": series_sorted[int(0.50 * n)],
            "p95_m": series_sorted[int(0.95 * n)],
            "max_m": series_sorted[-1],
            "definition": ("per-second max over stopped (<1.39 m/s) vehicles of "
                           "distance from stop line, on the whole edge (all lanes)"),
        }
    # one storage length used for the "queue zone" fraction: max over approaches
    # of the per-approach p95 back-of-queue, rounded UP to a 25 m segment edge
    p95max = max(q["p95_m"] for q in qstats.values())
    storage = math.ceil(p95max / SEG_LEN) * SEG_LEN

    # ---------------- write segment table -----------------------------------
    rows = []
    for (eid, b), v in sorted(seg.items()):
        pts, L = center[eid]
        d0, d1 = b * SEG_LEN, min((b + 1) * SEG_LEN, L)
        if eid in approach:            # d measured upstream from stop line
            s0, s1 = L - d0, L - d1    # arclength along the edge (start=fringe)
        else:                          # d measured downstream from stop line
            s0, s1 = d0, d1
        (x0, y0) = point_on(pts, L, s0)
        (x1, y1) = point_on(pts, L, s1)
        seglen = math.hypot(x1 - x0, y1 - y0)
        row = {"scenario": a.scenario, "edge": eid, "kind":
               "approach" if eid in approach else "departure",
               "bin": b, "d_from_stopline_start_m": d0, "d_from_stopline_end_m": d1,
               "x0": x0 - CX, "y0": y0 - CY, "x1": x1 - CX, "y1": y1 - CY,
               "length_m": seglen}
        for p in POLL:
            row[f"{p}_mg"] = v[p]
        rows.append(row)
    for lane, v in sorted(internal.items()):
        ln = net.getLane(lane)
        sh = ln.getShape()
        row = {"scenario": a.scenario, "edge": lane, "kind": "junction", "bin": 0,
               "d_from_stopline_start_m": 0.0, "d_from_stopline_end_m": ln.getLength(),
               "x0": sh[0][0] - CX, "y0": sh[0][1] - CY,
               "x1": sh[-1][0] - CX, "y1": sh[-1][1] - CY,
               "length_m": max(1.0, math.hypot(sh[-1][0] - sh[0][0], sh[-1][1] - sh[0][1]))}
        for p in POLL:
            row[f"{p}_mg"] = v[p]
        rows.append(row)

    seg_csv = os.path.join(a.out_dir, f"segments_{a.scenario}.csv")
    with open(seg_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # ---------------- queue-zone emission fraction --------------------------
    qz = {}
    for p in POLL:
        appr = sum(r[f"{p}_mg"] for r in rows if r["kind"] == "approach")
        inq = sum(r[f"{p}_mg"] for r in rows if r["kind"] == "approach"
                  and r["d_from_stopline_end_m"] <= storage + 1e-9)
        junc = sum(r[f"{p}_mg"] for r in rows if r["kind"] == "junction")
        dep = sum(r[f"{p}_mg"] for r in rows if r["kind"] == "departure")
        tot = appr + junc + dep
        qz[p] = {"approach_mg": appr, "queue_zone_mg": inq,
                 "junction_mg": junc, "departure_mg": dep, "total_mg": tot,
                 "frac_of_approach_in_queue_zone": inq / appr if appr else 0.0,
                 "frac_of_total_in_queue_zone": inq / tot if tot else 0.0,
                 "frac_of_total_in_queue_zone_plus_junction":
                     (inq + junc) / tot if tot else 0.0}

    # ---------------- reconciliation ----------------------------------------
    r2_sum = {p: sum(v[p] for v in edge_tot.values()) for p in POLL}
    r3_sum = {p: sum(r[f"{p}_mg"] for r in rows) for p in POLL}
    rec = {p: {"R1_trajectory_network_total_mg": fleet[p],
               "R2_edgeData_sum_mg": r2_sum[p],
               "R3_segment_sum_mg": r3_sum[p],
               "tripinfo_all_vehicles_mg": tri[p],
               "tripinfo_departed_in_window_mg": tri_win[p],
               "R3_minus_R1_rel": (r3_sum[p] - fleet[p]) / fleet[p] if fleet[p] else 0,
               "R2_minus_R1_rel": (r2_sum[p] - fleet[p]) / fleet[p] if fleet[p] else 0,
               "tripinfoWin_minus_R1_rel":
                   (tri_win[p] - fleet[p]) / fleet[p] if fleet[p] else 0}
           for p in POLL}

    out = {"scenario": a.scenario, "analysis_window_s": [WARMUP, END],
           "step_length_s": STEP, "n_trajectory_records_in_window": nrec,
           "segment_length_m": SEG_LEN,
           "R1_fleet_total_mg": fleet,
           "R2_edge_totals_mg": edge_tot,
           "reconciliation": rec,
           "back_of_queue": qstats,
           "queue_storage_length_used_m": storage,
           "queue_storage_basis": ("ceil(max over 4 approaches of the p95 "
                                   "per-second back-of-queue / 25 m) * 25 m"),
           "queue_zone_fraction": qz}
    with open(os.path.join(a.out_dir, f"emissions_{a.scenario}.json"), "w") as f:
        json.dump(out, f, indent=2)

    print(f"[{a.scenario}] records={nrec}  storage={storage:.0f} m")
    for p in ("CO", "NOx", "CO2"):
        r = rec[p]
        print(f"  {p:4s} R1={r['R1_trajectory_network_total_mg']/1e6:9.3f} kg  "
              f"R2/R1-1={r['R2_minus_R1_rel']*100:+.3f}%  "
              f"R3/R1-1={r['R3_minus_R1_rel']*100:+.4f}%  "
              f"queue-zone frac of approach={qz[p]['frac_of_approach_in_queue_zone']*100:.1f}%")


if __name__ == "__main__":
    main()
