#!/usr/bin/env python3
"""STEP 7 -- VALIDATION on hold-out conditions the vector was never fitted to.

Training condition : 1600 veh/h/ln mainline, 20% off-ramp share, 10% HGV.
Hold-out conditions: a different mainline demand AND a different exit share.

HOLD-OUT TARGET PROVENANCE (declared up front, exactly like the training
targets -- these are stated field values, not simulation output):
  the two empirical regularities used are (i) right-lane share RISES as total
  mainline flow falls (less overtaking pressure pushing traffic left) and
  (ii) right-lane share RISES with off-ramp share (exiting traffic
  pre-positions).  Both are applied to the training target 28/35/37.

  H1  1200 veh/h/ln, 20% exit  ->  32 / 35 / 33
  H2  1600 veh/h/ln, 35% exit  ->  34 / 34 / 32
  H3  1200 veh/h/ln, 35% exit  ->  38 / 34 / 28

Because those numbers are declared rather than measured, the report ALSO gives
the target-free comparison that does not depend on them: calibrated vs default
at the same hold-out condition, and the spatial mandatory-LC statistics.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

SEEDS = tuple(4000 + 11 * i for i in range(8))

HOLDOUT = [
    dict(name="TRAIN", per_lane=1600.0, exit_share=0.20,
         target={0: 0.28, 1: 0.35, 2: 0.37}),
    dict(name="H1_low_demand", per_lane=1200.0, exit_share=0.20,
         target={0: 0.32, 1: 0.35, 2: 0.33}),
    dict(name="H2_high_exit", per_lane=1600.0, exit_share=0.35,
         target={0: 0.34, 1: 0.34, 2: 0.32}),
    dict(name="H3_both", per_lane=1200.0, exit_share=0.35,
         target={0: 0.38, 1: 0.34, 2: 0.28}),
]


def main():
    cal = json.load(open(os.path.join(L.TBL, "calibration.json")))
    vectors = [("default", L.full_params()),
               ("calibrated", {k: float(v) for k, v in cal["best_params"].items()})]
    rows = []
    for h in HOLDOUT:
        ctx = dict(mainline_per_lane=h["per_lane"], exit_share=h["exit_share"],
                   _target_lane={str(k): v for k, v in h["target"].items()})
        res = evaluate_runs([v for _, v in vectors], seeds=SEEDS, ctx=ctx)
        for (name, _), r in zip(vectors, res):
            tot = r["flow"]
            gehs = [L.geh(r["share"][i] * tot, h["target"][i] * tot)
                    for i in range(3)]
            rows.append(dict(condition=h["name"], per_lane=h["per_lane"],
                             exit_share=h["exit_share"], vector=name,
                             target=[h["target"][i] for i in range(3)],
                             share=r["share"],
                             lane_flow=[r["share"][i] * tot for i in range(3)],
                             target_flow=[h["target"][i] * tot for i in range(3)],
                             geh=gehs, geh_max=max(gehs),
                             pass_geh5=bool(max(gehs) < 5.0),
                             rmsn_lane=r["rmsn_lane"], dlc=r["dlc"],
                             p85=r["p85"], p50=r["p50"],
                             fail_frac=r["fail_frac"], flow=tot,
                             ramp_entered=r["ramp_entered"],
                             teleports=r["teleports"], collisions=r["collisions"],
                             not_inserted=r["not_inserted"],
                             depart_delay=r["depart_delay"], obj=r["obj"]))
            print("%-14s %-11s share=%s  GEH=%s  max=%.2f %s  p85=%5.0f  "
                  "dlc=%.3f  fail=%.4f  tel=%.1f"
                  % (h["name"], name,
                     "/".join("%.4f" % x for x in r["share"]),
                     "/".join("%.2f" % x for x in gehs), max(gehs),
                     "PASS" if max(gehs) < 5 else "FAIL", r["p85"], r["dlc"],
                     r["fail_frac"], r["teleports"]))
    json.dump(dict(seeds=list(SEEDS), holdout=HOLDOUT, rows=rows),
              open(os.path.join(L.TBL, "validation.json"), "w"), indent=2,
              default=str)
    print("\nwrote", os.path.join(L.TBL, "validation.json"))


if __name__ == "__main__":
    main()
