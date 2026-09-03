"""Experiment matrix + parallel driver for the cruising-for-parking study.

Every arm is replicated over the SAME seed set (Common Random Numbers): a seed
fixes the parker cohort (origins, destinations, departure times, dwell, VOT,
walk speed), the through-traffic OD set, and SUMO's own RNG, so cross-arm
differences are policy differences, not demand differences.

The demand index `occ` is normalised against the BASELINE curb capacity (144);
the calibration sweep in data/calibration.json maps it to realised curb
occupancy (0.60 -> 0.58 ... 1.15 -> 0.96).
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from common import RUN_DIR, DATA_DIR

SEEDS = list(range(1, 9))                                   # 8 seeds, CRN
OCC_LEVELS = [0.60, 0.70, 0.80, 0.88, 0.94, 1.00, 1.06, 1.15]
INFO_OCC = [0.80, 0.94, 1.06]
H4_OCC = 1.06
H5_OCC = 1.00
H6_OCC = [1.30, 1.50, 1.75]

H4_ARMS = {
    "flat_cheap":  dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0),
    "curb_eq_gar": dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0),
    "perf_080":    dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0, price_target=0.80),
    "perf_085":    dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0, price_target=0.85),
    "perf_090":    dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0, price_target=0.90),
    "perf_095":    dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0, price_target=0.95),
    "supply_p12":  dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0, supply="supply_p12"),
    "supply_p24":  dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0, supply="supply_p24"),
    "guide_naive": dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0,
                        informed_share=1.0, informed_mode="naive"),
    "guide_resv":  dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0,
                        informed_share=1.0, informed_mode="reserve"),
    "guide_walk":  dict(policy="selfselect", fee_curb=0.5, fee_garage=2.0,
                        informed_share=1.0, informed_mode="reserve_walk"),
    "perf085_guidewalk": dict(policy="selfselect", fee_curb=2.0, fee_garage=2.0,
                              price_target=0.85, informed_share=1.0,
                              informed_mode="reserve_walk"),
}


def matrix():
    jobs = {}
    for s in SEEDS:
        # ---- H1 base occupancy sweep (no policy, no guidance, visible=false) --
        for occ in OCC_LEVELS:
            jobs["base_occ%.2f_s%d" % (occ, s)] = dict(seed=s, occ=occ, label="b")
        # ---- H2 controlled-removal counterfactual ----------------------------
        for occ in OCC_LEVELS:
            jobs["nosrch_occ%.2f_s%d" % (occ, s)] = dict(seed=s, occ=occ,
                                                         nosearch_cohort=0.25, label="n")
        # ---- H3 information: penetration x guidance mode + native reference ---
        for occ in INFO_OCC:
            for pen in (0.25, 0.50, 0.75, 1.0):
                jobs["infoN_p%.2f_occ%.2f_s%d" % (pen, occ, s)] = dict(
                    seed=s, occ=occ, informed_share=pen, informed_mode="naive", label="i")
            for pen in (0.25, 1.0):
                jobs["infoR_p%.2f_occ%.2f_s%d" % (pen, occ, s)] = dict(
                    seed=s, occ=occ, informed_share=pen, informed_mode="reserve", label="i")
            for pen in (0.25, 1.0):
                jobs["infoW_p%.2f_occ%.2f_s%d" % (pen, occ, s)] = dict(
                    seed=s, occ=occ, informed_share=pen, informed_mode="reserve_walk", label="i")
            jobs["visall_occ%.2f_s%d" % (occ, s)] = dict(seed=s, occ=occ, visible=True, label="v")
        # ---- H4 price vs supply vs information -------------------------------
        for k, v in H4_ARMS.items():
            cfg = dict(seed=s, occ=H4_OCC, label="h4")
            cfg.update(v)
            jobs["h4_%s_s%d" % (k, s)] = cfg
        # ---- H5 manoeuvre externality (curb occupancy held at 0.85 by price) --
        for sup in ("baseline", "curb_high", "curb_low"):
            for man in (False, True):
                jobs["h5_%s_man%d_s%d" % (sup, int(man), s)] = dict(
                    seed=s, occ=H5_OCC, supply=sup, maneuver=man, policy="selfselect",
                    fee_curb=2.0, fee_garage=2.0, price_target=0.85, label="h5")
        # ---- H6 failure mode --------------------------------------------------
        for occ in H6_OCC:
            jobs["h6_occ%.2f_s%d" % (occ, s)] = dict(seed=s, occ=occ, label="h6")
    return jobs


def _one(args):
    name, cfg = args
    d = os.path.join(RUN_DIR, name)
    rj = os.path.join(d, "result.json")
    if os.path.exists(rj) and os.path.getsize(rj) > 1000:
        return name, "cached"
    os.makedirs(d, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.run([sys.executable, os.path.join(here, "run_scenario.py"),
                        "--out", d, "--cfg", json.dumps(cfg)],
                       capture_output=True, text=True, cwd=here)
    if p.returncode != 0:
        return name, "FAIL: " + p.stderr[-800:]
    for f in ("tripinfo.xml", "stopinfo.xml", "summary.xml", "demand.rou.xml",
              "demand.meta.csv", "sumo.log"):
        fp = os.path.join(d, f)
        if os.path.exists(fp) and name not in KEEP_RAW:
            os.remove(fp)
    return name, "ok"


# a few arms keep their full raw SUMO output so the analysis can be re-verified
KEEP_RAW = {"base_occ0.60_s1", "base_occ1.06_s1", "h4_perf_085_s1",
            "h5_baseline_man1_s1", "h5_baseline_man0_s1", "h6_occ1.75_s1"}


def main(workers=8, only=None):
    jobs = matrix()
    if only:
        jobs = {k: v for k, v in jobs.items() if k.startswith(only)}
    items = sorted(jobs.items())
    print("%d runs" % len(items), flush=True)
    t0 = time.time()
    done, fails = 0, []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for name, status in ex.map(_one, items, chunksize=1):
            done += 1
            if status.startswith("FAIL"):
                fails.append((name, status))
                print("FAIL", name, status[:300], flush=True)
            if done % 40 == 0:
                el = time.time() - t0
                print("%d/%d  %.0fs elapsed, eta %.0fs" %
                      (done, len(items), el, el / done * (len(items) - done)), flush=True)
    print("done in %.0fs, %d failures" % (time.time() - t0, len(fails)))
    with open(os.path.join(DATA_DIR, "run_status.json"), "w") as f:
        json.dump(dict(n=len(items), failures=fails), f, indent=2)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    main(a.workers, a.only)
