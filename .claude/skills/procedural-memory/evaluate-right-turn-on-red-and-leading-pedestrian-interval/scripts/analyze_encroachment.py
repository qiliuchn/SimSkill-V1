#!/usr/bin/env python3
"""Analyse the supplementary runs made with the extended pedestrian-conflict
instrument, decomposing ped-vehicle conflict exposure into

  ENCROACHMENT      the vehicle was physically PAST the stop line, on the right
                    turn's internal via lane, when it came within 8 m of a
                    pedestrian on one of that turn's foe crossings, with
                    d / v < 2 s and v >= 1 m/s.
  APPROACH EXPOSURE the same proximity gate but the vehicle was still upstream
                    of the stop line (queue creep / deceleration).

Only the ENCROACHMENT count is a turn-on-red / permitted-turn violation of
pedestrian right of way; the approach component is a congestion artefact and
is what makes the aggregate conflict count of a heavily-queued No-Turn-on-Red
baseline look large.
"""
import json
import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze                                     # noqa: E402

BASE = analyze.BASE
OUT = analyze.OUT
RUNS = os.path.join(OUT, "runs_encroach")
WARMUP, WIN_END = analyze.WARMUP, analyze.WIN_END
WIN_H = analyze.WIN_H
SEEDS = [101, 102, 103]


def one(variant, cell, seed):
    tag = f"{variant}__{cell}__operational__s{seed}"
    p = os.path.join(RUNS, "operational", f"{variant}__{cell}", tag + "_traci.json")
    if not os.path.exists(p):
        return None
    T = json.load(open(p))
    cf = [c for c in T["conflicts"] if WARMUP <= c["t0"] < WIN_END]
    te = [e for e in T["turn_events"] if WARMUP <= e["t"] < WIN_END]
    enc = [c for c in cf if c.get("encroach_ttc", 1e9) < 2.0 and c.get("encroach_dist", 1e9) <= 8.0]
    sev = [c for c in cf if c["min_ttc"] < 2.0 and c["max_vspeed"] >= 1.0]
    appr = [c for c in sev if c not in enc]
    return {
        "variant": variant, "cell": cell, "seed": seed,
        "rt_total_vph": len(te) / WIN_H,
        "all_conflicts_per_h": len(sev) / WIN_H,
        "encroach_per_h": len(enc) / WIN_H,
        "approach_only_per_h": len(appr) / WIN_H,
        "encroach_onred_per_h": sum(1 for c in enc if c["on_red"]) / WIN_H,
        "encroach_ongreen_per_h": sum(1 for c in enc if not c["on_red"]) / WIN_H,
        "encroach_per_1000rt": 1000.0 * len(enc) / len(te) if te else float("nan"),
        "encroach_min_dist_mean": float(np.mean([c["encroach_dist"] for c in enc])) if enc else float("nan"),
        "encroach_min_ttc_mean": float(np.mean([c["encroach_ttc"] for c in enc])) if enc else float("nan"),
        "encroach_veh_stopped_frac": (float(np.mean([c["min_vspeed"] < 0.3 for c in enc]))
                                      if enc else float("nan")),
    }


if __name__ == "__main__":
    rows = [r for (v, c) in analyze.CELLS for s in SEEDS
            for r in [one(v, c, s)] if r]
    json.dump(rows, open(os.path.join(OUT, "encroachment_per_run.json"), "w"), indent=1)
    L = ["# Pedestrian-conflict decomposition (3 supplementary seeds per cell, "
         "extended instrument)\n",
         "`encroach` = vehicle PAST the stop line (inside the junction) within 8 m of a "
         "pedestrian on a foe crossing, d/v < 2 s, v >= 1 m/s.  "
         "`approach only` = same proximity gate but the vehicle was still upstream of the "
         "stop line.\n",
         "| geometry | treatment | RT served (veh/h) | all conflicts /h | ENCROACHMENT /h | "
         "approach-only /h | encroach on-red /h | encroach on-green /h | encroach per 1000 RT | "
         "mean min dist (m) | mean min d/v (s) |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    agg = {}
    for v, c in analyze.CELLS:
        sel = [r for r in rows if r["variant"] == v and r["cell"] == c]
        if not sel:
            continue
        a = {k: analyze.ci95([r[k] for r in sel]) for k in sel[0]
             if isinstance(sel[0][k], (int, float)) and k != "seed"}
        agg[f"{v}|{c}"] = {k: {"mean": x[0], "ci95": x[1]} for k, x in a.items()}

        def g(k, d=1):
            return f"{a[k][0]:.{d}f} ± {a[k][1]:.{d}f}"
        L.append(f"| {v} | {c} | {g('rt_total_vph')} | {g('all_conflicts_per_h')} | "
                 f"{g('encroach_per_h')} | {g('approach_only_per_h')} | "
                 f"{g('encroach_onred_per_h')} | {g('encroach_ongreen_per_h')} | "
                 f"{g('encroach_per_1000rt')} | {g('encroach_min_dist_mean',2)} | "
                 f"{g('encroach_min_ttc_mean',3)} |")
    json.dump(agg, open(os.path.join(OUT, "encroachment_per_cell.json"), "w"), indent=1)
    txt = "\n".join(L) + "\n"
    open(os.path.join(OUT, "ENCROACHMENT_TABLE.md"), "w").write(txt)
    print(txt)
