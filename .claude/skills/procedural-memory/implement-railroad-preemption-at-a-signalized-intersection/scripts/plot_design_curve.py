#!/usr/bin/env python3
"""Plot the advance-preemption-time design curve and the occupancy sweep.
Every point is read from outputs/tables/*.csv / *.json -- nothing is hardcoded."""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import common as C  # noqa: E402

TAB = os.path.join(C.ROOT, "outputs", "tables")
FIG = os.path.join(C.ROOT, "outputs", "figures")
os.makedirs(FIG, exist_ok=True)

curve = list(csv.DictReader(open(os.path.join(TAB, "design_curve.csv"))))
ite = json.load(open(os.path.join(TAB, "ite_comparison.json")))
APTS = [0, 5, 10, 15, 20, 25, 30]

fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))

# --- left: occupancy vs advance preemption time, one line per demand --------
for r in curve:
    y = [float(r[f"occ_mean_apt{a}"]) for a in APTS]
    ax[0].plot(APTS, y, marker="o", label=f"EB {r['eb_vph']} veh/h")
    ax[0].axhline(float(r["baseline_occ_mean"]), ls=":", lw=0.8, color="grey")
ax[0].set_xlabel("advance preemption time (s)")
ax[0].set_ylabel("mean vehicles on the crossing at gate-down")
ax[0].set_title("Track occupancy vs. advance preemption time\n"
                "(dotted = no-preemption baseline)")
ax[0].legend()
ax[0].grid(alpha=.3)

# --- right: design curve -- required APT vs design queue --------------------
n = [float(r["design_queue_veh_max"]) for r in curve]
req = [float(r["min_apt_for_zero_occupancy_s"]) if r["min_apt_for_zero_occupancy_s"]
       not in ("", "None") else float("nan") for r in curve]
ax[1].plot(n, req, marker="s", color="C3", label="simulated minimum APT\n(zero occupancy, all events)")
xs = sorted(set(n))
worst = [c["ite_apt_required_worst_case_s"] for c in ite["cells"]]
best = [c["ite_apt_required_best_case_s"] for c in ite["cells"]]
ax[1].plot(n, worst, marker="^", ls="--", color="C0", label="ITE closed form, worst-case ROW")
ax[1].plot(n, best, marker="v", ls="--", color="C2", label="ITE closed form, best-case ROW")
for x, y, r in zip(n, req, curve):
    ax[1].annotate(f"{r['eb_vph']} veh/h", (x, y), textcoords="offset points",
                   xytext=(6, -12), fontsize=8)
ax[1].set_xlabel("design queue that must be cleared (vehicles)")
ax[1].set_ylabel("advance preemption time (s)")
ax[1].set_title("Advance-preemption-time design curve")
ax[1].legend(fontsize=8)
ax[1].grid(alpha=.3)

fig.tight_layout()
out = os.path.join(FIG, "design_curve.png")
fig.savefig(out, dpi=150)
print("wrote", out)
