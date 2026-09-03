#!/usr/bin/env python3
"""Generate the measurement layer + signal programs for the corridor.

Writes <outdir>/additional.xml containing:
  (a) E1 induction loops -- 12 mainline stations x per-lane, incl. the
      breakdown-onset detector just upstream of the lane drop and the
      bottleneck-discharge detector just downstream of it;
      plus per-ramp meter-discharge E1s (realized-rate verification).
  (b) E2 lane-area detectors spanning the FULL ramp storage segment, the full
      surface approach lanes and the full cross-street approach (queue length,
      storage-exceeded flag, spillback instrumentation).
  (c) tlLogic programs for the 3 ramp terminals (2-phase) and the 3 ramp meters.
  (d) edgeData (per-edge vehicle-seconds + timeLoss) for the TSTT decomposition.

Detector output file paths are ABSOLUTE and per-run (see the
implement-alinea-ramp-metering gotcha about clobbering detector output).
"""
import argparse
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

# (station id, edge, pos along edge, approx x on corridor)
STATIONS = [
    ("s01", "ml_0", 500.0),
    ("s02", "ml_0", 1900.0),
    ("s03", "ml_1", 300.0),
    ("s04", "ml_1", 1500.0),
    ("s05", "ml_2", 500.0),
    ("s06", "ml_3", 200.0),
    ("s07", "ml_3", 1100.0),
    ("s08", "ml_4", 600.0),
    ("s09", "ml_5", 200.0),
    ("s10", "ml_5", 1000.0),   # BREAKDOWN-ONSET detector, just upstream of lane drop
    ("s11", "ml_6", 300.0),    # bottleneck DISCHARGE detector
    ("s12", "ml_6", 1300.0),
]
# cumulative x of the upstream end of each mainline edge (from the compiled net)
RAMPS = ["r1", "r2", "r3"]
# which mainline station each ramp's *local* (isolated-ALINEA) controller reads
LOCAL_DET = {"r1": "s03", "r2": "s06", "r3": "s09"}
BOTTLENECK_DET = "s10"
DISCHARGE_DET = "s11"


def edge_lane_counts(net):
    root = ET.parse(net).getroot()
    nl, elen = {}, {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        nl[e.get("id")] = len(lanes)
        elen[e.get("id")] = float(lanes[0].get("length"))
    tls = defaultdict(dict)
    for c in root.findall("connection"):
        if c.get("tl"):
            tls[c.get("tl")][int(c.get("linkIndex"))] = (
                c.get("from"), c.get("fromLane"), c.get("to"))
    return nl, elen, tls


def station_x(net):
    """cumulative corridor x for each station, using compiled edge lengths"""
    _, elen, _ = edge_lane_counts(net)
    order = [f"ml_{i}" for i in range(7)]
    x0, cum = {}, 0.0
    for e in order:
        x0[e] = cum
        cum += elen[e]
    return {sid: x0[e] + p for sid, e, p in STATIONS}, cum


def build(net, outdir, period=60):
    outdir = os.path.abspath(outdir)   # detector `file` paths resolve relative to
    os.makedirs(outdir, exist_ok=True)  # the ADDITIONAL file dir -> always absolutize
    nl, elen, tls = edge_lane_counts(net)
    det_e1 = os.path.join(outdir, "det_e1.xml")
    det_e2 = os.path.join(outdir, "det_e2.xml")
    edata = os.path.join(outdir, "edgedata.xml")
    L = []
    L.append("<additional>")

    # ---------- (a) E1 mainline stations ----------
    for sid, e, p in STATIONS:
        for l in range(nl[e]):
            L.append(f'  <inductionLoop id="e1_{sid}_{l}" lane="{e}_{l}" pos="{p}" '
                     f'period="{period}" file="{det_e1}" friendlyPos="true"/>')
    # ---------- (a) per-ramp meter-discharge + ramp-entry E1 ----------
    for r in RAMPS:
        L.append(f'  <inductionLoop id="e1_{r}_disch_0" lane="{r}_mrg_0" pos="25" '
                 f'period="{period}" file="{det_e1}" friendlyPos="true"/>')
        L.append(f'  <inductionLoop id="e1_{r}_entry_0" lane="{r}_stor_0" pos="5" '
                 f'period="{period}" file="{det_e1}" friendlyPos="true"/>')

    # ---------- (b) E2 queue detectors ----------
    for r in RAMPS:
        L.append(f'  <laneAreaDetector id="e2_{r}_stor" lane="{r}_stor_0" pos="0" '
                 f'length="{elen[r+"_stor"]:.2f}" period="{period}" file="{det_e2}" '
                 f'friendlyPos="true"/>')
        for l in range(nl[f"{r}_sapp"]):
            L.append(f'  <laneAreaDetector id="e2_{r}_sapp_{l}" lane="{r}_sapp_{l}" pos="0" '
                     f'length="{elen[r+"_sapp"]:.2f}" period="{period}" file="{det_e2}" '
                     f'friendlyPos="true"/>')
        L.append(f'  <laneAreaDetector id="e2_{r}_capp" lane="{r}_capp_0" pos="0" '
                 f'length="{elen[r+"_capp"]:.2f}" period="{period}" file="{det_e2}" '
                 f'friendlyPos="true"/>')
    # mainline E2 over the last 600 m before the drop (bottleneck occupancy sensing)
    for l in range(nl["ml_5"]):
        L.append(f'  <laneAreaDetector id="e2_bn_{l}" lane="ml_5_{l}" '
                 f'pos="{elen["ml_5"]-600:.2f}" length="600" period="{period}" '
                 f'file="{det_e2}" friendlyPos="true"/>')

    # ---------- (c) signal programs ----------
    for r in RAMPS:
        n = len(tls[f"{r}_term"])
        cross_idx = [i for i, v in tls[f"{r}_term"].items() if v[0].endswith("_capp")]
        art_idx = [i for i, v in tls[f"{r}_term"].items() if v[0].endswith("_sapp")]
        assert len(cross_idx) + len(art_idx) == n, (cross_idx, art_idx, n)

        def st(green_set, yellow_set=()):
            return "".join("G" if i in green_set else ("y" if i in yellow_set else "r")
                           for i in range(n))
        L.append(f'  <tlLogic id="{r}_term" type="static" programID="ctl" offset="0">')
        L.append(f'    <phase duration="44" state="{st(set(art_idx))}"/>')       # arterial+ramp
        L.append(f'    <phase duration="4"  state="{st(set(), set(art_idx))}"/>')
        L.append(f'    <phase duration="16" state="{st(set(cross_idx))}"/>')     # cross street
        L.append(f'    <phase duration="4"  state="{st(set(), set(cross_idx))}"/>')
        L.append('  </tlLogic>')
        # ramp meter: single controlled link, default = permanent green (the
        # controller overrides it every step via setRedYellowGreenState)
        L.append(f'  <tlLogic id="{r}_met" type="static" programID="ctl" offset="0">')
        L.append('    <phase duration="600" state="G"/>')
        L.append('  </tlLogic>')

    # ---------- (d) edgeData for the TSTT decomposition ----------
    L.append(f'  <edgeData id="ed" file="{edata}" freq="100000" excludeEmpty="false" '
             f'withInternal="true"/>')
    L.append("</additional>")
    path = os.path.join(outdir, "additional.xml")
    open(path, "w").write("\n".join(L) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("outdir")
    ap.add_argument("--period", type=int, default=60)
    a = ap.parse_args()
    p = build(a.net, a.outdir, a.period)
    xs, tot = station_x(a.net)
    print("wrote", p)
    print("station x (m):", {k: round(v, 1) for k, v in xs.items()}, "corridor", round(tot, 1))
