#!/usr/bin/env python3
"""
Noise floor of the enumeration protocol, derived from the capacity-paradox
replication runs (which use the IDENTICAL cold-start protocol as the
enumeration, only varying the seed).

The 229-subset enumeration uses one seed (CRN), so every reported TSTT
difference has to be read against the seed-to-seed standard deviation of a
single evaluation.  Anything smaller than ~2 sigma is not interpretable.
Also reports the within-evaluation tail oscillation SD for comparison: the two
are different noise sources (seed vs duaIterate limit cycle).
"""
import os, sys, csv, json
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "outputs")


def main():
    rows = list(csv.DictReader(open(os.path.join(OUT, "paradox_replication_runs.csv"))))
    by = {}
    for r in rows:
        if not r["tstt"]:
            continue
        by.setdefault(r["arm"], []).append(r)
    out = []
    for arm, rs in by.items():
        v = [float(r["tstt"]) for r in rs]
        tails = [float(r["tstt_sd_tail"]) for r in rs if r["tstt_sd_tail"]]
        out.append(dict(design=arm, n_seeds=len(v),
                        mean=round(st.mean(v), 1),
                        sd_across_seeds=round(st.stdev(v), 1) if len(v) > 1 else None,
                        cv_pct=round(100 * st.stdev(v) / st.mean(v), 4) if len(v) > 1 else None,
                        two_sigma=round(2 * st.stdev(v), 1) if len(v) > 1 else None,
                        min=round(min(v), 1), max=round(max(v), 1),
                        mean_within_eval_tail_sd=round(st.mean(tails), 1) if tails else None,
                        values=[round(x, 1) for x in v]))
    out.sort(key=lambda d: d["design"])
    sds = [d["sd_across_seeds"] for d in out if d["sd_across_seeds"]]
    res = dict(protocol="cold start, %d duaIterate iterations, tail-4 objective, "
                        "identical to the enumeration except for the seed" % 13,
               designs=out,
               pooled_sd_across_seeds=round(st.mean(sds), 1) if sds else None,
               interpretability_threshold_2sigma=round(2 * st.mean(sds), 1) if sds else None)
    with open(os.path.join(OUT, "noise_floor.json"), "w") as f:
        json.dump(res, f, indent=2)
    print("%-8s %6s %12s %10s %8s %12s %14s" %
          ("design", "n", "mean TSTT", "SD(seed)", "CV %", "2 sigma", "within-eval SD"))
    for d in out:
        print("%-8s %6d %12.0f %10.0f %8.4f %12.0f %14.0f" %
              (d["design"], d["n_seeds"], d["mean"], d["sd_across_seeds"] or 0,
               d["cv_pct"] or 0, d["two_sigma"] or 0,
               d["mean_within_eval_tail_sd"] or 0))
    print("\npooled seed-to-seed SD = %.0f veh-s -> anything below %.0f veh-s "
          "(2 sigma) is not interpretable" %
          (res["pooled_sd_across_seeds"], res["interpretability_threshold_2sigma"]))


if __name__ == "__main__":
    main()
