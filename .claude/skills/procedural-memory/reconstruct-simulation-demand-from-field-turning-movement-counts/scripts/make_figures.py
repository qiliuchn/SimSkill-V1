#!/usr/bin/env python3
"""Figures. Every series is parsed from raw SUMO output or from a
counts_to_demand report; nothing is hand-entered."""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import OUT, SCEN, RUNS, BIN, N_BINS
import demand as D
from export_tmc import movement_counts

# validated categorical palette (dataviz reference instance, light mode;
# checked with scripts/validate_palette.js -> ALL CHECKS PASS)
C = dict(true="#0b0b0b", count="#eb6834", storage="#2a78d6",
         jam="#1baf7a", trust="#4a3aa7", grey="#8a8985")
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e3e2dd"
X = [b * BIN / 3600.0 for b in range(N_BINS)]


def style(ax, title, ylab, xlab="time from start of count period (h)"):
    ax.set_title(title, fontsize=10.5, color=INK, loc="left", pad=8)
    ax.set_ylabel(ylab, fontsize=9, color=INK2)
    ax.set_xlabel(xlab, fontsize=9, color=INK2)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(labelsize=8, colors=INK2, length=3)


def recovered(pref, arm, key="J1|EB|T"):
    p = os.path.join(SCEN, "%s_%s_report.json" % (pref, arm))
    if not os.path.exists(p):
        return None
    return json.load(open(p))["recovered_movement_volumes"].get(key)


def fig_main():
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.3), sharey=True)
    for ax, arm, ttl in zip(axes, ("over", "under"),
                            ("OVER arm  (peak arterial v/c = 1.15)",
                             "UNDER arm  (peak arterial v/c = 0.75)")):
        tm = D.true_movement_volumes(arm)[("J1", "EB", "T")]
        obs = movement_counts(os.path.join(RUNS, "gt_" + arm))
        cnt = [obs.get(("J1", "EB", "T", b), (0, 0))[0] for b in range(N_BINS)]
        ax.plot(X, tm, color=C["true"], lw=2.0, marker="o", ms=4.5,
                label="TRUE injected demand", zorder=5)
        ax.plot(X, cnt, color=C["count"], lw=2.0, marker="s", ms=4.5,
                label="observed stop-bar count", zorder=4)
        for pref, lab, col, mk in (("recq", "corrected: approach storage", "storage", "^"),
                                   ("recqt", "corrected: storage + trust-propagation",
                                    "trust", "v"),
                                   ("recqj", "corrected: E2 residual jam length", "jam", "D")):
            v = recovered(pref, arm)
            if v:
                ax.plot(X, v, color=C[col], lw=1.8, marker=mk, ms=4.0, label=lab,
                        alpha=0.95)
        ax.axvspan(7 * BIN / 3600.0, 11 * BIN / 3600.0, color="#eda100", alpha=0.10,
                   lw=0, zorder=0)
        ax.annotate("true peak hour (bins 7-10)", (9 * BIN / 3600.0, ax.get_ylim()[0]),
                    xytext=(0, 6), textcoords="offset points", ha="center",
                    fontsize=8, color=INK2)
        style(ax, ttl, "vehicles per 15 min, J1 eastbound THROUGH")
    axes[0].legend(fontsize=8, frameon=False, loc="upper left", labelcolor=INK2)
    fig.suptitle("Field stop-bar counts truncate the peak of a saturated movement; "
                 "a storage-based queue correction restores it",
                 fontsize=11.5, color=INK, x=0.012, ha="left", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    p = os.path.join(OUT, "fig1_demand_vs_counts.png")
    fig.savefig(p, dpi=170, facecolor="#fcfcfb")
    return p


def fig_queue_metric():
    rows = {}
    with open(os.path.join(RUNS, "gt_over", "queue_bins.csv")) as f:
        for r in csv.DictReader(f):
            rows.setdefault(r["det"], {})[int(r["bin"])] = r
    dets = ["q_J1_EB_F0", "q_J1_EB_F1", "q_J1_EB_BAY"]
    storage, jam = [], []
    for b in range(N_BINS):
        storage.append(sum(float(rows[d][b]["n_end_veh"] or 0) for d in dets))
        jam.append(sum(float(rows[d][b]["q_resid_veh"] or 0) for d in dets))
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.plot(X, storage, color=C["storage"], lw=2.0, marker="^", ms=4.5,
            label="vehicles PRESENT on the approach (E2 storage)")
    ax.plot(X, jam, color=C["jam"], lw=2.0, marker="D", ms=4.0,
            label="E2 residual jam length (per-cycle minimum)")
    style(ax, "The two candidate queue measurements do not agree\n"
              "J1 eastbound approach, OVER arm", "vehicles")
    ax.legend(fontsize=8, frameon=False, loc="upper left", labelcolor=INK2)
    fig.tight_layout()
    p = os.path.join(OUT, "fig2_queue_metric.png")
    fig.savefig(p, dpi=170, facecolor="#fcfcfb")
    return p


def fig_equifinality():
    base = json.load(open(os.path.join(OUT, "iterative_over_base.json")))
    infl = json.load(open(os.path.join(OUT, "iterative_over_infl.json")))
    true = base[0]["J1EB_peak_demand_true"]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))
    for series, lab, col, mk in ((base, "loop started at the truncated demand", "storage", "^"),
                                 (infl, "loop started at 1.5x the truncated demand",
                                  "count", "s")):
        it = [r["iteration"] for r in series]
        axes[0].plot(it, [r["J1EB_peak_demand_emitted"] for r in series], color=C[col],
                     lw=2.0, marker=mk, ms=5, label=lab)
        axes[1].plot(it, [r["count_fit_all"]["pct_lt5"] for r in series], color=C[col],
                     lw=2.0, marker=mk, ms=5, label=lab)
    axes[0].axhline(true, color=C["true"], lw=1.6, ls="--")
    axes[0].annotate("TRUE demand = %.0f veh" % true, (0.05, true), xytext=(0, 6),
                     textcoords="offset points", fontsize=8, color=INK)
    axes[1].axhline(85, color=C["grey"], lw=1.2, ls=":")
    axes[1].annotate("conventional 85% GEH<5 bar", (0.05, 85), xytext=(0, 5),
                     textcoords="offset points", fontsize=8, color=INK2)
    style(axes[0], "The demand the loop converges on", "J1 EB peak-hour demand (veh)",
          "iteration")
    style(axes[1], "...while the objective it optimises barely moves",
          "% of movement-bins with GEH < 5", "iteration")
    axes[1].set_ylim(80, 101)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left", labelcolor=INK2)
    fig.suptitle("Equifinality: two demands 1.6x apart reproduce the same field counts",
                 fontsize=11.5, color=INK, x=0.012, ha="left", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    p = os.path.join(OUT, "fig3_equifinality.png")
    fig.savefig(p, dpi=170, facecolor="#fcfcfb")
    return p


if __name__ == "__main__":
    for f in (fig_main, fig_queue_metric, fig_equifinality):
        try:
            print("wrote", f())
        except Exception as e:
            print("SKIP %s: %s" % (f.__name__, e))
