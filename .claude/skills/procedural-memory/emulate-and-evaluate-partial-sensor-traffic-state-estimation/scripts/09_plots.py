#!/usr/bin/env python3
"""09_plots.py -- figures for the traffic-state-estimation study."""
import csv
import json
import math
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
PLT = os.path.abspath(os.path.join(HERE, "..", "plots"))
os.makedirs(PLT, exist_ok=True)
plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})


def rd(name):
    return list(csv.DictReader(open(os.path.join(RES, name))))


# --------------------------------------------------- 1. corridor TT estimators
r = [x for x in rd("estA_corridor_tt.csv") if x["agg"] == "60"]
t = [float(x["begin"]) / 60 for x in r]
fig, ax = plt.subplots(figsize=(7.2, 3.2))
ax.plot(t, [float(x["tt_gt_instantaneous"]) for x in r], "k-", lw=1.6, label="ground truth (instantaneous)")
ax.plot(t, [float(x["tt_harmonic"]) for x in r], "-", color="#2166ac", lw=1.2,
        label="loop estimate, harmonic (space-mean) speed")
ax.plot(t, [float(x["tt_timemean"]) for x in r], "-", color="#d6604d", lw=1.2,
        label="loop estimate, time-mean spot speed")
ax.set_xlabel("time (min)"); ax.set_ylabel("corridor travel time (s)")
ax.set_title("Estimator A: corridor travel time from mid-link spot speeds (60 s aggregation)")
ax.legend(fontsize=7.5)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "A_corridor_tt_timemean_vs_harmonic.png")); plt.close(fig)

# speed gap vs implied CV
w = rd("estA_speed_bias.csv")
fig, ax = plt.subplots(figsize=(4.4, 3.2))
ax.scatter([float(x["v_harmonic"]) for x in w], [float(x["diff"]) for x in w],
           s=5, alpha=0.35, color="#2166ac")
ax.set_xlabel("space-mean (harmonic) spot speed (m/s)")
ax.set_ylabel(r"$v_{time-mean} - v_{space-mean}$ (m/s)")
ax.set_title("Time-mean minus space-mean speed gap")
fig.tight_layout(); fig.savefig(os.path.join(PLT, "A_speed_gap.png")); plt.close(fig)

# --------------------------------------------------- 2. hysteresis
h = rd("estB_hysteresis.csv")
col = {"build": "#d6604d", "clear": "#2166ac", "offpeak": "#999999"}
fig, axs = plt.subplots(1, 2, figsize=(8.4, 3.4))
tt = [float(x["begin"]) / 60 for x in h]
axs[0].plot(tt, [float(x["tt_experienced_true"]) for x in h], "k-", lw=1.5, label="experienced")
axs[0].plot(tt, [float(x["tt_instantaneous_true"]) for x in h], "-", color="#d95f02", lw=1.3,
            label="instantaneous")
axs[0].set_xlabel("time (min)"); axs[0].set_ylabel("corridor travel time (s)")
axs[0].set_title("Instantaneous vs experienced"); axs[0].legend(fontsize=8)
for ph in ["offpeak", "build", "clear"]:
    g = [x for x in h if x["phase"] == ph]
    axs[1].scatter([float(x["tt_experienced_true"]) for x in g],
                   [float(x["tt_instantaneous_true"]) for x in g],
                   s=12, color=col[ph], label=ph, alpha=0.8)
lim = [min(float(x["tt_experienced_true"]) for x in h) - 10,
       max(float(x["tt_experienced_true"]) for x in h) + 10]
axs[1].plot(lim, lim, "k--", lw=0.8)
axs[1].set_xlabel("experienced TT (s)"); axs[1].set_ylabel("instantaneous TT (s)")
axs[1].set_title("Hysteresis loop"); axs[1].legend(fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "B_hysteresis.png")); plt.close(fig)

# --------------------------------------------------- 3. probe RMSE vs penetration
s = rd("estC_penetration_sweep.csv")
fig, axs = plt.subplots(1, 2, figsize=(8.6, 3.4))
for i, reg in enumerate(["freeflow", "oversat"]):
    ax = axs[i]
    for T, c in zip([1, 10, 30, 60], ["#2166ac", "#4393c3", "#f4a582", "#d6604d"]):
        g = sorted([x for x in s if x["regime"] == reg and int(x["ping_s"]) == T],
                   key=lambda x: float(x["pen_pct"]))
        ax.plot([float(x["pen_pct"]) for x in g], [float(x["rmse_pct"]) for x in g],
                "o-", ms=3.5, color=c, label=f"ping {T}s")
    # 1/sqrt(n) reference through the T=1, p=1 point
    g = sorted([x for x in s if x["regime"] == reg and int(x["ping_s"]) == 1],
               key=lambda x: float(x["pen_pct"]))
    p0, r0 = float(g[1]["pen_pct"]), float(g[1]["rmse_pct"])
    xs = [float(x["pen_pct"]) for x in g]
    ax.plot(xs, [r0 * math.sqrt(p0 / x) for x in xs], "k--", lw=0.8, label=r"$1/\sqrt{n}$ ref")
    ax.axhline(10, color="green", ls=":", lw=1.0)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("probe penetration (%)"); ax.set_ylabel("RMSE (% of true mean TT)")
    ax.set_title(reg); ax.legend(fontsize=7)
fig.suptitle("Estimator C: probe mean-travel-time RMSE vs penetration (green = ±10 % target)",
             fontsize=9.5)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "C_probe_rmse_vs_penetration.png")); plt.close(fig)

# --------------------------------------------------- 4. queue estimators
q = rd("estD_queue.csv")
SET = [40, 80, 120, 160, 200, 250, 320]
fig, axs = plt.subplots(1, 2, figsize=(9.0, 3.4))
tc = [float(x["cycle"]) / 60 for x in q]
axs[0].plot(tc, [float(x["truth"]) for x in q], "k-", lw=1.8, label="true back-of-queue")
for d, c in zip([80, 200, 320], ["#d6604d", "#f4a582", "#2166ac"]):
    axs[0].plot(tc, [float(x[f"occ{d}"]) for x in q], "-", lw=1.0, color=c,
                label=f"occupancy, setback {d} m")
    axs[0].axhline(d, color=c, ls=":", lw=0.7)
axs[0].set_xlabel("cycle start (min)"); axs[0].set_ylabel("queue (m)")
axs[0].set_title("Occupancy estimator saturates at its setback"); axs[0].legend(fontsize=7)
axs[1].plot(tc, [float(x["truth"]) for x in q], "k-", lw=1.8, label="true back-of-queue")
for d, c in zip([80, 200, 320], ["#d6604d", "#f4a582", "#2166ac"]):
    axs[1].plot(tc, [float(x[f"io{d}"]) for x in q], "-", lw=1.0, color=c,
                label=f"input-output, setback {d} m")
axs[1].set_xlabel("cycle start (min)"); axs[1].set_ylabel("queue (m)")
axs[1].set_title("Input-output cumulative-count estimator"); axs[1].legend(fontsize=7)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "D_queue_estimators.png")); plt.close(fig)

# --------------------------------------------------- 5. fine positioning
f = rd("estD_fine_positioning.csv")
fig, ax = plt.subplots(figsize=(7.4, 3.0))
ax.plot([float(x["setback_m"]) for x in f],
        [float(x["mean_max_occupancy_pct_deep_cycles"]) for x in f], "-", lw=1.0, color="#2166ac")
ax.axhline(30, color="green", ls=":", lw=1.0, label="detection threshold (30 %)")
ax.set_xlabel("detector setback from stop bar (m)")
ax.set_ylabel("mean max 30 s occupancy (%)")
ax.set_title("Occupancy on cycles where the true queue is past the whole ladder\n"
             "(1 m detector spacing; 7.5 m periodicity = vehicle length 5.0 m + minGap 2.5 m)")
ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "D_fine_positioning.png")); plt.close(fig)

# --------------------------------------------------- 6. ping-period selection bias
b = rd("H1b_ping_selection_bias.csv")
fig, ax = plt.subplots(figsize=(5.0, 3.2))
for T, c in zip([10, 30, 60], ["#4393c3", "#f4a582", "#d6604d"]):
    g = sorted([x for x in b if int(x["ping_s"]) == T], key=lambda x: int(x["link"]))
    ax.plot([int(x["link"]) for x in g],
            [float(x["selection_bias_pct"]) if x["selection_bias_pct"] else 0 for x in g],
            "o-", ms=4, color=c, label=f"ping {T}s")
ax.axhline(0, color="k", lw=0.8)
ax.set_xlabel("corridor link index"); ax.set_ylabel("selection bias in true link TT (%)")
ax.set_title("Bias hypothesis 1b: long ping periods drop fast traversals")
ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(PLT, "H1b_ping_selection_bias.png")); plt.close(fig)

print("wrote plots to", PLT)
for p in sorted(os.listdir(PLT)):
    print("  ", p)
