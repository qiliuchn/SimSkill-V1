#!/usr/bin/env python3
"""Second batch:

(a) the CRN-vs-independent treatment experiment at the oversaturated level
    L110 (the first batch only covered L050 and L090), and
(b) 12 replications per loading level re-run with keep_raw=True so that full
    tripinfo traces are available for the warm-up truncation-sensitivity
    analysis (mean trip duration as a function of the truncation point).

Output: replication_metrics_extra.csv (same schema, merged by analyze_stats.py)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_replications as R  # noqa: E402
import run_all as A           # noqa: E402

WORK = A.WORK


def build():
    jobs = []
    # (a) treatment experiment at L110
    lvl, rate = "L110", A.LEVELS["L110"]
    for s in A.TRT_SEEDS_A:
        jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="BASE_A",
                         id="%s_BASE_A_%04d" % (lvl, s),
                         out_dir=os.path.join(WORK, lvl, "TRT_BASE_A", "s%04d" % s),
                         demand_seed=s, sumo_seed=s, stochastic_driver=True))
        jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="TRT_A",
                         id="%s_TRT_A_%04d" % (lvl, s),
                         out_dir=os.path.join(WORK, lvl, "TRT_TRT_A", "s%04d" % s),
                         demand_seed=s, sumo_seed=s, cycle_scale=A.CYCLE_SCALE,
                         stochastic_driver=True))
    for s in A.TRT_SEEDS_B:
        jobs.append(dict(rate=rate, level=lvl, family="TRT", arm="TRT_B",
                         id="%s_TRT_B_%04d" % (lvl, s),
                         out_dir=os.path.join(WORK, lvl, "TRT_TRT_B", "s%04d" % s),
                         demand_seed=s, sumo_seed=s, cycle_scale=A.CYCLE_SCALE,
                         stochastic_driver=True))
    # (b) keep-raw replications for the truncation analysis
    for lvl, rate in A.LEVELS.items():
        for s in A.BOTH_SEEDS[:12]:
            jobs.append(dict(rate=rate, level=lvl, family="RAW",
                             id="%s_RAW_%04d" % (lvl, s),
                             out_dir=os.path.join(WORK, lvl, "RAW", "s%04d" % s),
                             demand_seed=s, sumo_seed=s, stochastic_driver=True,
                             keep_raw=True))
    return jobs


if __name__ == "__main__":
    jobs = build()
    print("planned: %d" % len(jobs))
    csv_out = os.path.join(HERE, "replication_metrics_extra.csv")
    recs, errs = R.run_batch(jobs, csv_out, workers=8)
    print("ok=%d err=%d -> %s" % (len(recs), len(errs), csv_out))
    for e in errs[:5]:
        print(" ERR", e["id"], e["error"][:200])
