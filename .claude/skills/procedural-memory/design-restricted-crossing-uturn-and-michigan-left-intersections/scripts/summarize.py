#!/usr/bin/env python3
"""
Build every results table used in FINDINGS.md from results_runs.csv /
results_classes.csv.  All comparisons are PAIRED by seed (common random numbers):
the per-seed difference alternative-minus-conventional is what gets averaged and
tested, never the difference of two independently-averaged means.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
NUM = ("D", "Q", "m", "seed", "ttt", "n_phases", "cycle_s", "Y_flow_ratio", "routed",
       "loaded", "inserted", "arrived", "running_end", "teleports", "collisions",
       "completed", "unfinished", "never_inserted", "mean_duration_s",
       "mean_distance_m", "mean_timeloss_s", "mean_departdelay_s",
       "mean_totaltime_s", "VMT_km", "VHT_h", "n_uturn_users")


def load(p):
    rows = []
    with open(p) as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if k in ("run", "tag", "variant", "movement_class", "ssm"):
                    continue
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
            rows.append(r)
    return rows


def key(r):
    return (int(r["D"]), int(r["Q"]), round(float(r["m"]), 2))


def mean(x):
    x = [v for v in x if v == v]
    return sum(x) / len(x) if x else float("nan")


def sd(x):
    x = [v for v in x if v == v]
    if len(x) < 2:
        return float("nan")
    mu = sum(x) / len(x)
    return math.sqrt(sum((v - mu) ** 2 for v in x) / (len(x) - 1))


TQ = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
      9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201, 13: 2.179, 14: 2.160, 15: 2.145}


def paired(runs, cell, metric, alt, base="conv", tag="base"):
    """Per-seed paired difference alt-base for one metric in one cell."""
    by = defaultdict(dict)
    for r in runs:
        if r["tag"] != tag or key(r) != cell:
            continue
        by[int(r["seed"])][r["variant"]] = r
    d = [by[s][alt][metric] - by[s][base][metric]
         for s in by if alt in by[s] and base in by[s]]
    if not d:
        return None
    n = len(d)
    md, s = mean(d), sd(d)
    t = md / (s / math.sqrt(n)) if s and s > 0 else float("inf") if md else 0.0
    tq = TQ.get(n, 2.0)
    return {"n": n, "mean_diff": md, "sd_diff": s, "t": t, "tcrit": tq,
            "ci95": (md - tq * s / math.sqrt(n), md + tq * s / math.sqrt(n)),
            "base_mean": mean([by[s][base][metric] for s in by if base in by[s]]),
            "alt_mean": mean([by[s][alt][metric] for s in by if alt in by[s]])}


def cell_means(runs, tag="base"):
    out = defaultdict(lambda: defaultdict(dict))
    grp = defaultdict(list)
    for r in runs:
        if r["tag"] != tag:
            continue
        grp[(key(r), r["variant"])].append(r)
    for (c, v), rs in grp.items():
        for k in NUM:
            if k in ("D", "Q", "m", "seed", "ttt"):
                continue
            out[c][v][k] = mean([x[k] for x in rs])
        out[c][v]["nseeds"] = len(rs)
    return out


def class_cell_means(classes, tag="base"):
    grp = defaultdict(list)
    for r in classes:
        if r["tag"] != tag:
            continue
        grp[(key(r), r["variant"], r["movement_class"])].append(r)
    out = {}
    for k, rs in grp.items():
        out[k] = {m: mean([x[m] for x in rs]) for m in
                  ("mean_distance_m", "mean_duration_s", "mean_timeloss_s",
                   "mean_totaltime_s", "mean_departdelay_s", "VMT_km", "VHT_h",
                   "completed", "unfinished", "routed", "uses_uturn")}
    return out


def paired_class(classes, cell, cls, metric, alt, base="conv", tag="base"):
    by = defaultdict(dict)
    for r in classes:
        if r["tag"] != tag or key(r) != cell or r["movement_class"] != cls:
            continue
        by[int(r["seed"])][r["variant"]] = r
    d = [by[s][alt][metric] - by[s][base][metric]
         for s in by if alt in by[s] and base in by[s]
         and by[s][alt][metric] == by[s][alt][metric] and by[s][base][metric] == by[s][base][metric]]
    if not d:
        return None
    n, md, s = len(d), mean(d), sd(d)
    return {"n": n, "mean_diff": md, "sd_diff": s,
            "t": md / (s / math.sqrt(n)) if s and s > 0 else float("nan"),
            "base_mean": mean([by[s][base][metric] for s in by if base in by[s]]),
            "alt_mean": mean([by[s][alt][metric] for s in by if alt in by[s]])}


def main():
    runs = load(os.path.join(RES, "results_runs.csv"))
    classes = load(os.path.join(RES, "results_classes.csv"))
    cm = cell_means(runs)
    ccm = class_cell_means(classes)
    out = {"cells": {}, "paired": {}, "classes": {}, "thresholds": {}}

    cells = sorted(cm)
    for c in cells:
        out["cells"][str(c)] = {v: cm[c][v] for v in cm[c]}
        out["paired"][str(c)] = {}
        for alt in ("rcut", "mut"):
            out["paired"][str(c)][alt] = {
                m: paired(runs, c, m, alt) for m in
                ("mean_totaltime_s", "mean_duration_s", "mean_distance_m",
                 "VMT_km", "VHT_h", "mean_timeloss_s", "completed", "teleports")}
    for c in cells:
        for cls in ("ART_THRU", "ART_LEFT", "ART_RIGHT", "MIN_THRU", "MIN_LEFT", "MIN_RIGHT"):
            for v in ("conv", "rcut", "mut"):
                if (c, v, cls) in ccm:
                    out["classes"][f"{c}|{v}|{cls}"] = ccm[(c, v, cls)]
    with open(os.path.join(RES, "summary.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    return runs, classes, cm, ccm, out


if __name__ == "__main__":
    main()
    print("wrote", os.path.join(RES, "summary.json"))
