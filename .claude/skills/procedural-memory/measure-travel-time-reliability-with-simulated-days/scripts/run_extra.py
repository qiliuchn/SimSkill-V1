#!/usr/bin/env python3
"""
Two extra blocks that the main matrix cannot provide.

SEEDREP -- a proper simulator-noise-floor estimate.  The plain SEED block only
           measures seed variance AT demand multiplier 1.0, and seed variance
           is strongly demand-dependent (it peaks at the congestion knee).
           SEEDREP is a stratified 10 x 6 design: 10 demand levels placed at the
           5th,15th,...,95th percentile of the SAME lognormal used for the day
           draws, times 6 independent seeds each, incidents disabled.
           -> Var_seed = mean over strata of the within-stratum variance,
              i.e. E_m[Var_s(T|m)], averaged over the demand distribution.

TTT     -- teleport sensitivity.  The 6 most-loaded incident days re-run with
           --time-to-teleport in {-1 (disabled), 120, 200 (main setting)} to
           check for the survivorship-censoring reversal described in
           `validate-congested-scenario-results-against-teleport-artifacts`.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import sys
import traceback

import numpy as np
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_lib as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
def netfile(la, lm):
    return os.path.join(WORK, "net", S.NETNAME[(la, lm)] + ".net.xml")


def one(job):
    block, scen, day, tag, ttt = job
    la, lm, eq = S.SCENARIOS[scen]
    rd = os.path.join(WORK, "runs", block, scen, tag)
    try:
        res = S.run_cell(rd, netfile(la, lm), day, eq, lm, ttt=ttt)
    except Exception:
        return dict(block=block, scenario=scen, tag=tag, ok=0,
                    err=traceback.format_exc()[-400:])
    res.update(block=block, scenario=scen, tag=tag, ok=1, day=day["day"],
               mult=day["mult"], incident=day["incident"],
               inc_lanes=day["inc_lanes"], inc_edge=day["inc_edge"],
               inc_start=day["inc_start"], inc_dur=day["inc_dur"],
               seed=day["seed"], equip=eq, approach_lanes=la,
               mid_lanes=lm,
               ttt=(S.TIME_TO_TELEPORT if ttt is None else ttt), rundir=rd)
    tp = os.path.join(rd, "tripinfo.xml")
    if os.path.exists(tp):
        os.remove(tp)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv", type=float, default=0.20)
    ap.add_argument("--strata", type=int, default=10)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--master-seed", type=int, default=20260801)
    ap.add_argument("--workers", type=int, default=9)
    a = ap.parse_args()

    days = json.load(open(os.path.join(WORK, "days.json")))

    sigma = np.sqrt(np.log(1.0 + a.cv ** 2))
    mu = -0.5 * sigma ** 2
    qs = (np.arange(a.strata) + 0.5) / a.strata
    levels = np.exp(mu + sigma * norm.ppf(qs))
    rng = np.random.default_rng(a.master_seed + 4242)

    jobs = []
    seedrep_meta = []
    for k, m in enumerate(levels):
        for r in range(a.reps):
            d = dict(day=k * 100 + r, mult=float(round(m, 6)), incident=0,
                     inc_start=0.0, inc_dur=0.0, inc_lanes=0, inc_edge="",
                     seed=int(rng.integers(1, 1_000_000)))
            seedrep_meta.append(dict(stratum=k, rep=r, **d))
            for scen in S.SCENARIOS:
                jobs.append(("SEEDREP", scen, d, f"s{k:02d}r{r}", None))
    json.dump(dict(levels=[float(x) for x in levels], meta=seedrep_meta),
              open(os.path.join(WORK, "seedrep.json"), "w"), indent=1)

    inc_days = [d for d in days if d["incident"]]
    inc_days.sort(key=lambda d: -(d["mult"] * (1 + d["inc_lanes"])))
    worst = inc_days[:6]
    json.dump(worst, open(os.path.join(WORK, "ttt_days.json"), "w"), indent=1)
    for d in worst:
        for scen in S.SCENARIOS:
            for ttt in (-1, 120, 200):
                jobs.append(("TTT", scen, d, f"day{d['day']:03d}_ttt{ttt}",
                             ttt))

    print(f"{len(jobs)} extra runs ...", flush=True)
    rows, done = [], 0
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(one, jobs):
            rows.append(r)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    bad = [r for r in rows if not r.get("ok")]
    if bad:
        print("FAILURES", len(bad), bad[0])
        sys.exit(2)
    keys = sorted({k for r in rows for k in r})
    out = os.path.join(WORK, "cells_extra.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", out, len(rows))


if __name__ == "__main__":
    main()
