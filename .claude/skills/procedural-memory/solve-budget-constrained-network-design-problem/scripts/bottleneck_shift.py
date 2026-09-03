#!/usr/bin/env python3
"""
Mechanism evidence for the interaction matrix: where does the BINDING BOTTLENECK
move when two projects are built together rather than separately?

Re-runs the cold-start equilibrium for do-nothing, i alone, j alone and i+j with
edgeData enabled, then reports the top-loaded edges by v/c (using the calibrated
effective saturation flow and the compiled green ratios) for each design.

usage: bottleneck_shift.py "L2+L4" "N1+NB" ...      (each argument is one design)
"""
import os, sys, json, shutil, csv
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import mask_from_subset, subset_from_mask
from demand_sweep import edge_green_ratios, edge_lanes, peak_flows
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "bneck")
OUT = os.path.join(ROOT, "outputs")
TRIPS = os.path.join(ROOT, "work", "trips_main.xml")


def job(mask):
    wd = os.path.join(WORK, "m%04d" % mask)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(wd, exist_ok=True)
    r = EV.score(mask, TRIPS, wd, seed=1, last_step=EV.COLD_STEPS, edgedata=True,
                 keep=True)
    net = os.path.join(wd, "net.net.xml")
    ed = os.path.join(wd, "rec", "edgedata.xml")
    s_eff = json.load(open(os.path.join(OUT, "vc_calibration.json")))["s_eff_veh_h_lane"]
    gr = edge_green_ratios(net); ln = edge_lanes(net); fl = peak_flows(ed)
    vc = {}
    for e, f in fl.items():
        if e.split("_")[0][0] in "WESN" or e.split("_")[1][0] in "WESN":
            continue
        vc[e] = f / (ln.get(e, 1) * s_eff * gr.get(e, 1.0))
    top = sorted(vc.items(), key=lambda kv: -kv[1])[:10]
    out = dict(mask=mask, subset="+".join(subset_from_mask(mask)) or "(none)",
               tstt=r["tstt"], top_vc=[[e, round(v, 3)] for e, v in top],
               all_vc={e: round(v, 4) for e, v in vc.items()})
    shutil.rmtree(wd, ignore_errors=True)
    return out


def main():
    designs = sys.argv[1:]
    masks = {0}
    for d in designs:
        parts = [p for p in d.split("+") if p]
        masks.add(mask_from_subset(parts))
        for p in parts:
            masks.add(mask_from_subset([p]))
    masks = sorted(masks)
    os.makedirs(WORK, exist_ok=True)
    with ProcessPoolExecutor(max_workers=min(10, len(masks))) as ex:
        res = list(ex.map(job, masks))
    res.sort(key=lambda r: r["mask"])
    with open(os.path.join(OUT, "bottleneck_shift.json"), "w") as f:
        json.dump(res, f, indent=2)
    for r in res:
        print("\n=== %-12s TSTT=%.0f" % (r["subset"], r["tstt"]))
        for e, v in r["top_vc"]:
            print("    %-12s v/c=%.3f" % (e, v))
    # explicit per-edge delta table between the pair and each single
    with open(os.path.join(OUT, "bottleneck_shift.csv"), "w", newline="") as f:
        allv = sorted({e for r in res for e in r["all_vc"]})
        w = csv.writer(f)
        w.writerow(["edge"] + [r["subset"] for r in res])
        for e in allv:
            w.writerow([e] + [r["all_vc"].get(e, "") for r in res])


if __name__ == "__main__":
    main()
