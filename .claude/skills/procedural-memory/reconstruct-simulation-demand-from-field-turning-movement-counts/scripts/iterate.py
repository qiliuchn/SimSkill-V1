#!/usr/bin/env python3
"""
Correction (b): an iterative demand-scaling loop that inflates movement demand
until the SIMULATED stop-bar counts match the OBSERVED stop-bar counts.

Run from two different starting points -- the truncated count-derived demand and
a deliberately inflated one -- to test whether the loop converges to the TRUE
demand or merely to an equifinal family of demands that all reproduce the counts.
"""
import argparse
import json
import math
import os
import subprocess
import sys

from common import RUNS, OUT, SCEN, NET, N_BINS, JUNCTIONS, geh
import demand as D
import metrics as M
from export_tmc import movement_counts
import run_sim

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CFG = os.path.join(SCEN, "corridor_config.json")
PEAK = M.PEAK_BINS
MOVES = ("L", "T", "R")


def sh(*a):
    p = subprocess.run([str(x) for x in a], cwd=HERE, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-3000:], p.stderr[-3000:])
        raise SystemExit("failed " + " ".join(str(x) for x in a))
    return p


def geh_summary(obs, sim, subset=None):
    v = []
    for j in JUNCTIONS:
        for app in ("EB", "WB", "NB", "SB"):
            for m in MOVES:
                for b in range(N_BINS):
                    if subset and not subset(j, app, m, b):
                        continue
                    v.append(geh(sim.get((j, app, m, b), (0, 0))[0],
                                 obs.get((j, app, m, b), (0, 0))[0]))
    v.sort()
    return dict(n=len(v), mean=sum(v) / len(v), max=v[-1],
                p85=v[int(0.85 * (len(v) - 1))],
                pct_lt5=100.0 * sum(1 for x in v if x < 5) / len(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="over")
    ap.add_argument("--start", type=float, default=1.0)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--iters", type=int, default=3)
    a = ap.parse_args()

    tmc = os.path.join(OUT, "tmc_counts_%s.csv" % a.arm)
    atr = os.path.join(OUT, "atr_profile_%s.csv" % a.arm)
    base_rep = json.load(open(os.path.join(SCEN, "rec_%s_report.json" % a.arm)))
    obs = movement_counts(os.path.join(RUNS, "gt_" + a.arm))
    truth = D.true_movement_volumes(a.arm)
    seqs = {k: [tuple(s.split()) for s in v["seq"]] for k, v in base_rep["paths"].items()}

    scale = {k: [a.start] * N_BINS for k in seqs}
    log = []
    for it in range(a.iters + 1):
        sf = os.path.join(SCEN, "scale_%s_%d.json" % (a.tag, it))
        json.dump(scale, open(sf, "w"))
        rou = os.path.join(SCEN, "it_%s_%d.rou.xml" % (a.tag, it))
        rep = os.path.join(SCEN, "it_%s_%d_report.json" % (a.tag, it))
        sh(PY, "counts_to_demand.py", "--tmc", tmc, "--atr", atr, "--net", NET,
           "--config", CFG, "--out", rou, "--report", rep, "--scale-file", sf)
        name = "it_%s_%d" % (a.tag, it)
        sh(PY, "run_sim.py", "--route", rou, "--name", name)
        rd = os.path.join(RUNS, name)
        sim = movement_counts(rd)

        r = json.load(open(rep))
        recmv = r["recovered_movement_volumes"]
        # input demand actually emitted (recovered volumes x scale) per movement
        emitted = {}
        for k, seq in seqs.items():
            vol = base_rep["paths"][k]["per_bin"]
            for (j, app, m) in seq:
                arr = emitted.setdefault((j, app, m), [0.0] * N_BINS)
                for b in range(N_BINS):
                    arr[b] += vol[b] * scale[k][b]

        d = M.approach_delay(rd, PEAK)
        q = M.back_of_queue(rd, PEAK)
        rec = dict(
            iteration=it,
            count_fit_all=geh_summary(obs, sim),
            count_fit_J1EB=geh_summary(obs, sim,
                                       lambda j, app, m, b: (j, app) == ("J1", "EB")),
            count_fit_J1EB_peak=geh_summary(
                obs, sim, lambda j, app, m, b: (j, app) == ("J1", "EB") and b in PEAK),
            J1EB_peak_demand_true=sum(truth[("J1", "EB", m)][b] for m in MOVES for b in PEAK),
            J1EB_peak_demand_emitted=sum(emitted[("J1", "EB", m)][b]
                                         for m in MOVES for b in PEAK),
            J1EB_peak_counts_obs=sum(obs.get(("J1", "EB", m, b), (0, 0))[0]
                                     for m in MOVES for b in PEAK),
            J1EB_peak_counts_sim=sum(sim.get(("J1", "EB", m, b), (0, 0))[0]
                                     for m in MOVES for b in PEAK),
            total_demand_emitted=sum(sum(v) for v in emitted.values()),
            J1EB_delay=d.get(("J1", "EB"), {}).get("delay"),
            J1EB_los=d.get(("J1", "EB"), {}).get("los"),
            J1EB_q95=q[("J1", "EB")]["q95_veh"],
            J1EB_residual=q[("J1", "EB")]["residual_end_of_peak_veh"],
            mean_scale=sum(sum(v) / N_BINS for v in scale.values()) / len(scale))
        rec["J1EB_peak_demand_err_pct"] = 100.0 * (
            rec["J1EB_peak_demand_emitted"] - rec["J1EB_peak_demand_true"]) \
            / rec["J1EB_peak_demand_true"]
        log.append(rec)
        print("[%s it=%d] meanGEH=%.2f %%<5=%.1f | J1EB peak demand true=%.0f "
              "emitted=%.0f (%+.1f%%) | counts obs=%d sim=%d | delay=%.1f Q95=%.1f"
              % (a.tag, it, rec["count_fit_all"]["mean"], rec["count_fit_all"]["pct_lt5"],
                 rec["J1EB_peak_demand_true"], rec["J1EB_peak_demand_emitted"],
                 rec["J1EB_peak_demand_err_pct"], rec["J1EB_peak_counts_obs"],
                 rec["J1EB_peak_counts_sim"], rec["J1EB_delay"], rec["J1EB_q95"]))

        if it == a.iters:
            break
        # ---- proportional update:  scale *= geometric mean of obs/sim over the
        #      movements the path traverses, in that bin
        new = {}
        for k, seq in seqs.items():
            new[k] = list(scale[k])
            for b in range(N_BINS):
                rs = []
                for (j, app, m) in seq:
                    s = sim.get((j, app, m, b), (0, 0))[0]
                    o = obs.get((j, app, m, b), (0, 0))[0]
                    if s > 0 and o > 0:
                        rs.append(o / s)
                if not rs:
                    continue
                g = math.exp(sum(math.log(x) for x in rs) / len(rs))
                g = min(max(g, 0.7), 1.5)
                new[k][b] = min(max(scale[k][b] * g, 0.2), 5.0)
        scale = new

    with open(os.path.join(OUT, "iterative_%s_%s.json" % (a.arm, a.tag)), "w") as f:
        json.dump(log, f, indent=1)


if __name__ == "__main__":
    main()
