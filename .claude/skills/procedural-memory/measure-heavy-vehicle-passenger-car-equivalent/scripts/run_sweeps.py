#!/usr/bin/env python3
"""STEP 2 -- run every simulation cell of the PCE study.

Design
------
Truck-share sweep       p in {0, 5, 10, 20, 30, 50}%  -- TOTAL demand (veh/h)
                        held constant, only the composition changes.  p=0 is the
                        pure-car control arm.
Replications            3 seeds per cell, Common Random Numbers: for a given
                        seed the arrival TIMES are identical in every arm and the
                        heavy-vehicle set is NESTED across p (p=5% trucks are a
                        subset of the p=10% trucks), so arms are paired.
Signal cells            x 4 green durations {16,24,32,40} s for the window-free
                        green-duration regression (the primary saturation-flow
                        estimator).
Grade cells             freeway only, grades {0,2,4,6}% at p in {0, 20}%.
Decomposition cells     7 single-parameter heavy-vehicle variants at p=30% on
                        BOTH testbeds.

Each run gets its OWN directory: detector `file` paths resolve relative to the
additional file's own directory, so parallel runs sharing a directory would
silently overwrite each other's detector output.
"""
import os
import sys
import json
import time
from multiprocessing import Pool

from common import (WORK, CAR, TRUCK_DEFAULT, HV_VARIANTS, GREENS, GRADES, SEEDS)
import signal_rig as S
import freeway_rig as F

# p=1.00 (an all-heavy fleet) is included as a LINEARISATION-FREE anchor: there
# E_T is just the ratio of the pure-heavy to the pure-car capacity, with no
# division by p and no assumption that f_HV is linear in p.
SHARES = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00]
DECOMP_P = 0.30
GRADE_SHARES = [0.0, 0.20]
RUNS = os.path.join(WORK, "runs")


def sig_dir(var, p, g, seed):
    return os.path.join(RUNS, "sig", "%s_p%03d_g%02d_s%d" % (var, round(p * 100), g, seed))


def fwy_dir(var, p, gr, seed):
    return os.path.join(RUNS, "fwy", "%s_p%03d_gr%g_s%d" % (var, round(p * 100), gr, seed))


def build_jobs():
    jobs = []
    seen = set()

    def add(kind, var, p, x, seed):
        key = (kind, var, round(p, 4), x, seed)
        if key in seen:
            return
        seen.add(key)
        jobs.append(key)

    # ---- signal: truck-share sweep (variant = SUMO's own default truck)
    for p in SHARES:
        for g in GREENS:
            for s in SEEDS:
                add("sig", "hv_full", p, g, s)
    # ---- signal: single-parameter decomposition at p = 30%
    for var in HV_VARIANTS:
        for g in GREENS:
            for s in SEEDS:
                add("sig", var, DECOMP_P, g, s)
    # ---- freeway: truck-share sweep at 0% grade
    for p in SHARES:
        for s in SEEDS:
            add("fwy", "hv_full", p, 0.0, s)
    # ---- freeway: grade sensitivity
    for gr in GRADES:
        for p in GRADE_SHARES:
            for s in SEEDS:
                add("fwy", "hv_full", p, gr, s)
    # ---- freeway: single-parameter decomposition at p = 30%
    for var in HV_VARIANTS:
        for s in SEEDS:
            add("fwy", var, DECOMP_P, 0.0, s)
    return jobs


def do(job):
    kind, var, p, x, seed = job
    attrs = HV_VARIANTS[var]
    t0 = time.time()
    if kind == "sig":
        d = sig_dir(var, p, x, seed)
        if not os.path.exists(os.path.join(d, "stats.xml")):
            S.run(d, float(x), p, seed, attrs, CAR)
    else:
        d = fwy_dir(var, p, x, seed)
        if not os.path.exists(os.path.join(d, "stats.xml")):
            F.run(d, float(x), p, seed, attrs, CAR)
    return job, round(time.time() - t0, 1)


def main():
    jobs = build_jobs()
    # freeway runs are ~10x longer; run them first so they overlap the short ones
    jobs.sort(key=lambda j: 0 if j[0] == "fwy" else 1)
    print("%d cells to simulate" % len(jobs), flush=True)
    t0 = time.time()
    done = 0
    with Pool(8) as pool:
        for job, dt in pool.imap_unordered(do, jobs):
            done += 1
            if done % 10 == 0 or dt > 30:
                print("  [%3d/%3d] %-4s %-10s p=%.2f x=%-4s s=%d  %5.1fs   (elapsed %.0fs)"
                      % (done, len(jobs), job[0], job[1], job[2], job[3], job[4], dt,
                         time.time() - t0), flush=True)
    print("ALL DONE in %.0f s" % (time.time() - t0))
    with open(os.path.join(WORK, "jobs.json"), "w") as f:
        json.dump([list(j) for j in jobs], f, indent=1)


if __name__ == "__main__":
    main()
