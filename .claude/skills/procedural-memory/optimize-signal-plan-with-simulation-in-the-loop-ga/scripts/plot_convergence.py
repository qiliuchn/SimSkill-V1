#!/usr/bin/env python3
"""Convergence plot: best-so-far and generation-mean objective vs generation for the
GA runs, with the analytic baseline objective as a horizontal reference."""
import os, csv, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    gens, best, mean, bsf = [], [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            gens.append(int(row["generation"]))
            best.append(float(row["best_obj"]))
            mean.append(float(row["mean_obj"]))
            bsf.append(float(row["best_so_far"]))
    return gens, best, mean, bsf


baseline_obj = json.load(open(os.path.join(HERE, "comparison.json")))["baseline"]["objective"]

fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=False)
runs = [("ga_log.csv", "GA spec-bounded (cycle 40-120, min-green 6)", axes[0]),
        ("ga_log_matched.csv", "GA matched to baseline (cycle 20-120, min-green 4)", axes[1])]

for fname, title, ax in runs:
    g_, best, mean, bsf = load(os.path.join(HERE, fname))
    ax.plot(g_, mean, "o-", color="#bbbbbb", label="generation mean", zorder=1)
    ax.plot(g_, best, "s--", color="#4c78a8", label="generation best", zorder=2)
    ax.plot(g_, bsf, "-", color="#e45756", lw=2.5, label="best-so-far", zorder=3)
    ax.axhline(baseline_obj, color="#54a24b", ls=":", lw=2,
               label=f"analytic baseline = {baseline_obj:.0f}")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("generation")
    ax.set_ylabel("objective = total time loss (s)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

fig.suptitle("GA convergence: coordinated fixed-time arterial signal optimization (SUMO-in-the-loop)",
             fontsize=12)
fig.tight_layout(rect=(0, 0, 1, 0.96))
out = os.path.join(HERE, "convergence.png")
fig.savefig(out, dpi=130)
print("wrote", out)
