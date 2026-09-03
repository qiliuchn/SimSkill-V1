#!/usr/bin/env python3
"""
FIGURE 2 - mainline queue-length time series showing the spillback onset, read straight from
the e2 laneAreaDetector `maxJamLengthInMeters` on the two mainline approach lanes, for
several booth counts at the fixed design-hour demand.
"""
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plaza_lib as P

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(EP, "attempts", "attempt-1", "runs", "design")
OUT = os.path.join(EP, "outputs")
STORAGE = 1196.0
DEMAND = 1500.0
SEFF = 12.438

# ordered family (queue severity falls with c) -> sequential ramp + selective direct labels
RAMP = {3: "#1c3468", 4: "#2f57a8", 5: "#4d7bd8", 6: "#7ba0e4", 7: "#a8c2ee"}
INK, INK2, GRID = "#22201d", "#5b5651", "#dedbd5"

fig, ax = plt.subplots(figsize=(10.0, 5.8), dpi=170)
fig.patch.set_facecolor("#fcfcfb")
ax.set_facecolor("#fcfcfb")
ax.grid(True, color=GRID, lw=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(GRID)
ax.tick_params(colors=INK2, labelsize=9)

summary = {}
for c in sorted(RAMP):
    e2 = P.parse_e2(os.path.join(RUNS, "c%d_s101" % c, "e2.xml"))
    t0 = np.array([x[0] for x in e2["q_app_0"]])
    j = np.maximum(np.array([x[1] for x in e2["q_app_0"]]),
                   np.array([x[1] for x in e2["q_app_1"]]))
    cap = c * 3600.0 / SEFF
    lab = "c=%d  ($\\rho$=%.2f)" % (c, DEMAND / cap)
    ax.plot(t0, j, lw=2.0, color=RAMP[c], label=lab)
    onset = t0[np.argmax(j > 1.0)] if (j > 1.0).any() else None
    summary[c] = dict(rho=DEMAND / cap, max_jam_m=float(j.max()),
                      spillback_onset_s=float(onset) if onset is not None else None,
                      frac_time_on_mainline=float((j > 1.0).mean()))
    if j.max() > 500:
        k = int(np.argmax(j))
        ax.annotate(lab, xy=(t0[k], j[k]), xytext=(6, 4), textcoords="offset points",
                    color=RAMP[c], fontsize=9, fontweight="bold")

ax.axhline(STORAGE, color="#b5468f", lw=2.0, ls=(0, (5, 3)))
ax.annotate("available mainline storage = %.0f m (2 lanes)" % STORAGE,
            xy=(0.015, STORAGE), xycoords=("axes fraction", "data"),
            xytext=(0, 7), textcoords="offset points", color="#b5468f", fontsize=9.5)
ax.axvspan(0, 900, color=GRID, alpha=0.55, lw=0)
ax.annotate("warm-up\n(excluded)", xy=(450, ax.get_ylim()[1] * 0.93), ha="center",
            color=INK2, fontsize=8.5, va="top")
ax.set_xlabel("simulation time (s)   —   demand offered 0–5400 s", color=INK, fontsize=11)
ax.set_ylabel("mainline queue length (e2 maxJamLengthInMeters)", color=INK, fontsize=11)
ax.set_title("Toll-plaza queue spillback onto the mainline as booths are removed",
             color=INK, fontsize=13, loc="left", pad=16)
ax.text(0, 1.015, "design demand %.0f veh/h, exponential 8 s manual service, seed 101; "
        "queue is off the mainline entirely for c$\\geq$6" % DEMAND,
        transform=ax.transAxes, color=INK2, fontsize=9.5)
ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="center right")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig2_spillback_timeseries.png"), facecolor="#fcfcfb")
json.dump(summary, open(os.path.join(OUT, "fig2_spillback_values.json"), "w"), indent=1)
for c, v in summary.items():
    print("c=%d rho=%.2f  max mainline jam=%7.1f m  onset=%s s  frac of time queue on "
          "mainline=%.3f" % (c, v["rho"], v["max_jam_m"], v["spillback_onset_s"],
                             v["frac_time_on_mainline"]))
print("wrote fig2")
