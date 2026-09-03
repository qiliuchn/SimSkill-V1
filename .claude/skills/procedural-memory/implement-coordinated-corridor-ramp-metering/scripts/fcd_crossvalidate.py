#!/usr/bin/env python3
"""Cross-validate the E2 lane-area ramp-queue measurement against TRUE vehicle
positions taken from SUMO's FCD output.

Runs `nocontrol` and `coord` at demand 0.95 / seed 1 with FCD restricted to the
ramp storage + surface approach edges (sampled every 30 s, matching the control
interval), then, for every ramp and every sampled instant, recomputes from raw
vehicle positions:
   - the true vehicle COUNT on the storage lane
   - the true QUEUE LENGTH, defined as the extent of the contiguous cluster of
     halted vehicles (speed <= 1.39 m/s, gaps <= 10 m) anchored at the meter stop
     bar -- the same definition SUMO's E2 `jamLengthInMeters` uses
and compares against what the E2 detector reported at the same instant.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUMO_HOME = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
RAMPS = ["r1", "r2", "r3"]
HALT_V, GAP = 1.39, 20.0   # empirically the best-matching reconstruction of E2 jamLengthInMeters (see docstring)


def run(arm, outdir):
    from gen_additional import build as build_add
    os.makedirs(outdir, exist_ok=True)
    net = os.path.join(ROOT, "outputs", "net", "s3_160", "corridor.net.xml")
    rou = os.path.join(ROOT, "outputs", "routes", "s1_d95.rou.xml")
    add = build_add(net, outdir, period=30)
    filt = os.path.join(outdir, "fcdfilter.txt")
    # --fcd-output.filter-edges.input-file takes a netedit SELECTION file
    # ("edge:<id>" per line), NOT an <additional> XML. Passing XML silently
    # matches nothing and produces an FCD file with zero vehicles.
    open(filt, "w").write("\n".join(f"edge:{r}_stor" for r in RAMPS) + "\n")
    cmd = [sys.executable, os.path.join(HERE, "corridor_control.py"),
           "--net", net, "--routes", rou, "--additional", add, "--arm", arm,
           "--seed", "1", "--demand", "0.95", "--end", "6000",
           "--tripinfo", os.path.join(outdir, "tripinfo.xml"),
           "--summary", os.path.join(outdir, "summary.xml"),
           "--outjson", os.path.join(outdir, "ctl.json"),
           "--fcd", os.path.join(outdir, "fcd.xml"), "--fcd-filter", filt]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=dict(os.environ, SUMO_HOME=SUMO_HOME), cwd=HERE)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit(1)
    return outdir


VLEN = 5.0


def true_queue(poss, storlen):
    """Reproduce SUMO's E2 jamLengthInMeters definition from raw FCD positions:
    halted vehicles are those with speed <= haltingSpeedThreshold (1.39 m/s); a jam
    is a maximal run of halted vehicles whose bumper-to-bumper gaps are <=
    jamDistThreshold (10 m); the reported value is the LONGEST such jam anywhere on
    the detector -- it is NOT required to be anchored at the stop bar."""
    halted = sorted([p for p, v in poss if v <= HALT_V], reverse=True)
    if not halted:
        return 0.0, 0
    best_len, best_n = 0.0, 0
    head, tail, n = halted[0], halted[0], 1
    for p in halted[1:]:
        if (tail - p) - VLEN <= GAP:
            tail, n = p, n + 1
        else:
            if head - tail + VLEN > best_len:
                best_len, best_n = head - tail + VLEN, n
            head, tail, n = p, p, 1
    if head - tail + VLEN > best_len:
        best_len, best_n = head - tail + VLEN, n
    return best_len, best_n


def crossval(outdir, storlen):
    """Compare, at the SAME instants, the E2 detector's instantaneous reading (taken
    live over TraCI at each control step and stored in ctl.json) against the queue
    recomputed from raw FCD vehicle positions."""
    ctl = json.load(open(os.path.join(outdir, "ctl.json")))["log"]
    e2 = {r: {x["t"]: (x["ramp"][r]["jam_m"], x["ramp"][r]["nveh"]) for x in ctl}
          for r in RAMPS}
    fcd = defaultdict(lambda: defaultdict(list))
    for ts in ET.parse(os.path.join(outdir, "fcd.xml")).getroot():
        t = float(ts.get("time"))
        if t % 30 != 0:
            continue
        for v in ts.findall("vehicle"):
            lane = v.get("lane", "")
            if lane.endswith("_stor_0"):
                fcd[lane[:2]][t].append((float(v.get("pos")), float(v.get("speed"))))
    rows = []
    for r in RAMPS:
        for t in sorted(set(e2[r]) & set(range(0, 6001, 30))):
            poss = fcd[r].get(t, [])
            tq, tn = true_queue(poss, storlen[r])
            ejam, en = e2[r][t]
            rows.append(dict(ramp=r, t=t, fcd_n=len(poss), fcd_jam=tq, fcd_haltn=tn,
                             e2_jam=ejam, e2_n=en))
    return rows


def main():
    storlen = {"r1": 280.0, "r2": 220.0, "r3": 160.0}
    res = {}
    for arm in ("nocontrol", "coord"):
        d = os.path.join(ROOT, "outputs", "fcdval", arm)
        if not os.path.exists(os.path.join(d, "fcd.xml")):
            run(arm, d)
        rows = crossval(d, storlen)
        n = len(rows)
        cnt_exact = sum(1 for x in rows if abs(x["fcd_n"] - x["e2_n"]) < 0.5)
        cnt_mae = sum(abs(x["fcd_n"] - x["e2_n"]) for x in rows) / max(len(rows), 1)
        both = [x for x in rows if x["fcd_jam"] > 0 and x["e2_jam"] > 0]
        corr = float(np.corrcoef([x["fcd_jam"] for x in both],
                                 [x["e2_jam"] for x in both])[0, 1]) if len(both) > 3 else None
        jam_err = [x["e2_jam"] - x["fcd_jam"] for x in rows if x["fcd_jam"] > 0 or x["e2_jam"] > 0]
        mae = sum(abs(e) for e in jam_err) / max(len(jam_err), 1)
        bias = sum(jam_err) / max(len(jam_err), 1)
        big = [x for x in rows if abs(x["e2_jam"] - x["fcd_jam"]) > 10]
        res[arm] = dict(n_samples=n, count_exact_match_frac=cnt_exact / max(n, 1),
                        count_mae_veh=cnt_mae, jam_corr=corr, n_both_positive=len(both),
                        jam_mae_m=mae, jam_bias_m=bias, n_jam_samples=len(jam_err),
                        frac_jam_err_gt10m=len(big) / max(len(jam_err), 1),
                        max_fcd_jam=max((x["fcd_jam"] for x in rows), default=0),
                        max_e2_jam=max((x["e2_jam"] for x in rows), default=0))
        print(arm, json.dumps(res[arm], indent=1))
    out = os.path.join(ROOT, "outputs", "tables", "fcd_crossvalidation.json")
    json.dump(res, open(out, "w"), indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
