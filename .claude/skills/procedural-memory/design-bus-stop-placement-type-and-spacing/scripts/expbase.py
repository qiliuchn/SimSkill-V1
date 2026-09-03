"""Replication / CRN harness + paired statistics.

CRN discipline follows `quantify-sumo-run-to-run-variability`: the SAME seed list
is used in every arm, and every stochastic stream in the scenario builder is keyed
off that seed (car departures, person OD+departures, sumo --seed), so paired
differences cancel demand noise.  Paired t confidence intervals throughout, plus
the measured paired correlation so it is visible whether CRN actually helped.
"""
import os
import sys
import json
import math
import traceback
from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from runner import run_cell  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs")
RES = os.path.join(ROOT, "results")
os.makedirs(RES, exist_ok=True)

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
        15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        24: 2.064, 29: 2.045, 39: 2.023, 49: 2.010, 99: 1.984}


def tcrit(df):
    if df <= 0:
        return float("nan")
    ks = sorted(T975)
    for k in ks:
        if df <= k:
            return T975[k]
    return 1.96


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    n = len(xs)
    if n < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def ci(xs):
    n = len(xs)
    m, s = mean(xs), sd(xs)
    if n < 2 or math.isnan(s):
        return m, float("nan"), (float("nan"), float("nan"))
    h = tcrit(n - 1) * s / math.sqrt(n)
    return m, h, (m - h, m + h)


def paired(a, b):
    """b - a, paired by index (CRN)."""
    d = [y - x for x, y in zip(a, b)]
    m, h, (lo, hi) = ci(d)
    ma, mb = mean(a), mean(b)
    n = len(d)
    if n >= 3 and sd(a) > 0 and sd(b) > 0:
        mA, mB = ma, mb
        cov = sum((x - mA) * (y - mB) for x, y in zip(a, b)) / (n - 1)
        r = cov / (sd(a) * sd(b))
    else:
        r = float("nan")
    return {"n": n, "mean_a": ma, "mean_b": mb, "diff": m, "half_width": h,
            "ci_lo": lo, "ci_hi": hi,
            "pct": (100.0 * m / ma) if ma else float("nan"),
            "significant": (not math.isnan(h)) and (lo > 0 or hi < 0),
            "paired_corr": r}


def _job(args):
    name, cfgd, seed, tsp, keep, detail = args
    cfg = Cfg(**cfgd)
    d = os.path.join(RUNS, name, f"s{seed}")
    try:
        m = run_cell(cfg, d, seed, tsp=tsp, keep=keep)
        if not detail:
            m.pop("rider_access_lens", None)
            m.pop("rider_totals", None)
            m.pop("person_records", None)
        return name, seed, m, None
    except Exception:
        return name, seed, None, traceback.format_exc()


def run_arms(arms, seeds, workers=9, tag="exp", detail=False, keep=()):
    """arms: dict name -> (Cfg, tsp_mode). Returns dict name -> list[metrics]."""
    jobs = []
    for name, spec in arms.items():
        cfg, tsp = (spec if isinstance(spec, tuple) else (spec, "none"))
        for s in seeds:
            jobs.append((name, cfg.__dict__.copy(), s, tsp, keep, detail))
    out = {n: {} for n in arms}
    errs = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for name, seed, m, err in ex.map(_job, jobs):
            if err:
                errs.append((name, seed, err))
            else:
                out[name][seed] = m
    if errs:
        print(f"[{tag}] {len(errs)} FAILED runs; first:\n{errs[0][2][-1500:]}")
    res = {n: [out[n][s] for s in seeds if s in out[n]] for n in arms}
    return res, errs


def validity(ms):
    """Aggregate the teleport / completion / stop-service validity counters."""
    return {
        "runs": len(ms),
        "teleports_total": sum(m["teleports"] for m in ms),
        "teleport_warnings_total": sum(m["teleport_warnings"] for m in ms),
        "cars_unfinished_total": sum(m["cars_unfinished"] for m in ms),
        "cars_total": sum(m["n_cars"] for m in ms),
        "riders_incomplete_total": sum(m["riders_incomplete"] for m in ms),
        "riders_still_waiting": sum(m["riders_still_waiting"] for m in ms),
        "riders_still_riding": sum(m["riders_still_riding"] for m in ms),
        "riders_total": sum(m["n_riders"] for m in ms),
        "missed_stop_services": sum(m["missed_stop_services"] for m in ms),
        "stop_events": sum(m["stop_events"] for m in ms),
        "stop_events_expected": sum(m["stop_events_expected"] for m in ms),
        "final_running_max": max(m["final_running"] for m in ms) if ms else None,
    }


def col(ms, k):
    return [m[k] for m in ms]


def save(obj, name):
    p = os.path.join(RES, name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    print("wrote", p)
    return p
