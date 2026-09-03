#!/usr/bin/env python3
"""
10_probe_queue_and_recommendation.py

(1) A PROBE-BASED queue estimator, so that the practical recommendation compares
    like with like: at penetration p, the estimated back-of-queue is the furthest
    upstream position of any *probe* that is stopped (< 1.39 m/s) on the approach
    during the cycle.  Offline subsampling of the master 100 % FCD (identical
    traffic by construction).  Includes the standard 1/p spacing correction.

(2) The cross-layer comparison table used for the sensing recommendation:
    RMSE of every estimator for each of the two estimation targets, plus the
    deployment unit each one costs.
"""
import csv
import gzip
import json
import math
import os
import random
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
FCD = os.path.join(RUNS, "master", "fcd.xml.gz")

APPROACH_LANES = ("eb_2_0", "eb_2_1")
L_APPROACH = 385.60
CYCLE, OFF = 90, 58
STOP = 1.39
PENS = [0.5, 1, 2, 5, 10, 20, 50, 100]
NREP = 200
SEED = 7

RT = re.compile(r'<timestep time="([\d.]+)"')
RV = re.compile(r'<vehicle id="([^"]+)" speed="([-\d.]+)" pos="([-\d.]+)" lane="([^"]+)"')


def scan():
    """cycle -> list of (veh_id, back_of_queue_metres) for every stopped observation"""
    per = defaultdict(list)
    t = None
    for line in gzip.open(FCD, "rt"):
        m = RT.search(line)
        if m:
            t = float(m.group(1)); continue
        m = RV.search(line)
        if not m:
            continue
        if m.group(4) not in APPROACH_LANES:
            continue
        spd, pos = float(m.group(2)), float(m.group(3))
        if spd >= STOP:
            continue
        c = OFF + int((t - OFF) // CYCLE) * CYCLE
        per[c].append((m.group(1), L_APPROACH - (pos - 5.0)))
    return per


def main():
    rng = random.Random(SEED)
    per = scan()
    truth = {}
    for r in csv.DictReader(open(os.path.join(RES, "gt_queue_percycle.csv"))):
        if int(r["junction"]) == 3:
            truth[int(r["cycle_start"])] = float(r["max_extent_1p39"])
    cycles = sorted(c for c in truth if c in per or truth[c] == 0)
    allveh = sorted({v for obs in per.values() for v, _ in obs})

    rows = []
    for p in PENS:
        raw_err, corr_err = [], []
        raw_bias, corr_bias = [], []
        for _ in range(NREP):
            eq = {v for v in allveh if rng.random() * 100.0 < p}
            for c in cycles:
                tr = truth[c]
                obs = [q for v, q in per.get(c, []) if v in eq]
                est = max(obs) if obs else 0.0
                # spacing correction: with penetration p the deepest probe is on
                # average 1/p queued vehicles short of the true back of queue
                corr = est + (7.5 * (100.0 / p - 1.0) if obs else 0.0)
                raw_err.append(est - tr); corr_err.append(min(corr, L_APPROACH + 5) - tr)
        rows.append(dict(
            pen_pct=p, n=len(raw_err),
            raw_bias_m=sum(raw_err) / len(raw_err),
            raw_rmse_m=math.sqrt(sum(x * x for x in raw_err) / len(raw_err)),
            corrected_bias_m=sum(corr_err) / len(corr_err),
            corrected_rmse_m=math.sqrt(sum(x * x for x in corr_err) / len(corr_err))))
        print(f"  probe queue p={p:5.1f}%  raw bias {rows[-1]['raw_bias_m']:8.1f} m "
              f"RMSE {rows[-1]['raw_rmse_m']:7.1f} m | corrected bias "
              f"{rows[-1]['corrected_bias_m']:8.1f} m RMSE {rows[-1]['corrected_rmse_m']:7.1f} m")

    # congested-only slice
    congested = [c for c in cycles if truth[c] >= 150]
    rows_c = []
    for p in PENS:
        errs = []
        for _ in range(NREP):
            eq = {v for v in allveh if rng.random() * 100.0 < p}
            for c in congested:
                obs = [q for v, q in per.get(c, []) if v in eq]
                errs.append((max(obs) if obs else 0.0) - truth[c])
        rows_c.append(dict(pen_pct=p, bias_m=sum(errs) / len(errs),
                           rmse_m=math.sqrt(sum(x * x for x in errs) / len(errs))))

    with open(os.path.join(RES, "estD_probe_queue.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})

    mean_truth = sum(truth[c] for c in cycles) / len(cycles)
    mean_truth_c = sum(truth[c] for c in congested) / len(congested)

    # ---------------------------------------------------- cross-layer comparison
    e1 = json.load(open(os.path.join(RES, "e1_estimators.json")))
    pr = json.load(open(os.path.join(RES, "probe_estimators.json")))
    sweep = list(csv.DictReader(open(os.path.join(RES, "estC_penetration_sweep.csv"))))

    def probe_rmse_pct(reg, p, T=1):
        g = [x for x in sweep if x["regime"] == reg and float(x["pen_pct"]) == p
             and int(x["ping_s"]) == T]
        return float(g[0]["rmse_pct"]) if g else None

    tt_tbl = []
    for agg in [60, 300]:
        a = e1[f"A_agg{agg}"]
        tt_tbl.append(dict(layer=f"loops, time-mean spot speed, {agg}s agg",
                           deployment="12 mid-link loops (2/link x 6 links)",
                           bias_pct=a["bias_timemean_pct"],
                           rmse_pct=100 * a["rmse_timemean_s"] / a["mean_tt_gt_instantaneous_s"]))
        tt_tbl.append(dict(layer=f"loops, harmonic (space-mean) speed, {agg}s agg",
                           deployment="12 mid-link loops (2/link x 6 links)",
                           bias_pct=a["bias_harmonic_pct"],
                           rmse_pct=100 * a["rmse_harmonic_s"] / a["mean_tt_gt_instantaneous_s"]))
    for p in PENS:
        g = [x for x in sweep if x["regime"] == "all" and float(x["pen_pct"]) == p
             and int(x["ping_s"]) == 1]
        if g:
            tt_tbl.append(dict(layer=f"probes {p}% @ 1 s ping",
                               deployment=f"{p}% fleet equipage",
                               bias_pct=float(g[0]["bias_pct"]),
                               rmse_pct=float(g[0]["rmse_pct"])))

    q_tbl = []
    d = e1["D_queue_estimators"]["all_cycles"]
    for k, v in d.items():
        if v is None:
            continue
        q_tbl.append(dict(layer=f"loops, {k}", deployment="1-2 loops on the approach",
                          bias_m=v["bias_m"], rmse_m=v["rmse_m"],
                          rmse_pct=100 * v["rmse_m"] / mean_truth))
    for r in rows:
        q_tbl.append(dict(layer=f"probes {r['pen_pct']}% (raw)",
                          deployment=f"{r['pen_pct']}% fleet equipage",
                          bias_m=r["raw_bias_m"], rmse_m=r["raw_rmse_m"],
                          rmse_pct=100 * r["raw_rmse_m"] / mean_truth))
        q_tbl.append(dict(layer=f"probes {r['pen_pct']}% (1/p spacing-corrected)",
                          deployment=f"{r['pen_pct']}% fleet equipage",
                          bias_m=r["corrected_bias_m"], rmse_m=r["corrected_rmse_m"],
                          rmse_pct=100 * r["corrected_rmse_m"] / mean_truth))

    out = dict(mean_true_queue_all_cycles_m=mean_truth,
               mean_true_queue_congested_cycles_m=mean_truth_c,
               n_cycles=len(cycles), n_congested_cycles=len(congested),
               probe_queue_all_cycles=rows,
               probe_queue_congested_cycles=rows_c,
               travel_time_comparison=sorted(tt_tbl, key=lambda r: r["rmse_pct"]),
               queue_comparison=sorted(q_tbl, key=lambda r: r["rmse_m"]))
    json.dump(out, open(os.path.join(RES, "sensing_recommendation.json"), "w"), indent=1)

    print("\nTRAVEL TIME -- best layers by RMSE:")
    for r in out["travel_time_comparison"][:8]:
        print(f"   {r['rmse_pct']:7.2f}%  bias {r['bias_pct']:+7.2f}%   {r['layer']}")
    print("\nQUEUE LENGTH -- best layers by RMSE (mean true queue %.1f m):" % mean_truth)
    for r in out["queue_comparison"][:10]:
        print(f"   {r['rmse_m']:7.1f} m  bias {r['bias_m']:+8.1f} m   {r['layer']}")
    print("\nwrote", os.path.join(RES, "sensing_recommendation.json"))


if __name__ == "__main__":
    main()
