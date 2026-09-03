"""Replicated experiment driver: N_SEEDS independent 'days' x {incident, control} x demand level.

Matched (CRN) design -- seed s appears in both arms at every demand level, and the incident
draw is a deterministic function of s alone, so the incident and control day for a given
(level, seed) share identical traffic up to the injection instant.
"""
import os, sys, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
from multiprocessing import Pool


def one(job):
    level, seed, arm = job
    d = os.path.join(RUNS_DIR, level, f"{arm}_s{seed:03d}")
    try:
        if os.path.exists(os.path.join(d, "meta.json")) and os.path.exists(os.path.join(d, "det.npz")):
            return (job, "cached")
        from run_day import run
        run(d, level, seed, arm, label=f"{level}_{arm}_{seed}")
        return (job, "ok")
    except Exception:
        return (job, "FAIL:" + traceback.format_exc()[-400:])


if __name__ == "__main__":
    levels = sys.argv[1].split(",") if len(sys.argv) > 1 else list(DEMAND_LEVELS)
    jobs = [(lv, s, arm) for lv in levels for s in range(1, N_SEEDS + 1)
            for arm in ("incident", "control")]
    print(f"{len(jobs)} runs over {len(levels)} demand levels")
    with Pool(8) as p:
        bad = 0
        for i, (job, st) in enumerate(p.imap_unordered(one, jobs), 1):
            if st.startswith("FAIL"):
                bad += 1
                print("FAILED", job, st)
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)} done ({bad} failures)")
    print("done, failures:", bad)
