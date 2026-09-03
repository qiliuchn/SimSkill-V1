#!/usr/bin/env python3
"""
Deliverable figures:
  (ii) budget-vs-best-achievable-benefit Pareto frontier
  (iii) 10x10 pairwise project-interaction heatmap

Colour follows the dataviz skill's rules: the interaction matrix encodes
POLARITY (complementary vs substitutive) so it uses a diverging blue<->red ramp
with a neutral gray midpoint, symmetric about zero; the frontier is a single
series so it carries no legend box, direct labels only.
"""
import os, sys, json, csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "outputs")

SURFACE = "#fcfcfb"; INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; SERIES1 = "#2a78d6"; SERIES2 = "#eb6834"
DIVERGING = LinearSegmentedColormap.from_list(
    "bluegray_red", ["#0d366b", "#256abf", "#86b6ef", "#f0efec",
                     "#f0a3a2", "#d03b3b", "#8a1f1f"])


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7"); ax.spines[s].set_linewidth(1.0)
    ax.tick_params(colors=MUTED, labelsize=9, length=3)
    ax.yaxis.grid(True, color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)


def heatmap():
    d = json.load(open(os.path.join(OUT, "interaction_matrix.json")))
    ids = d["project_ids"]
    M = np.array([[np.nan if v is None else v for v in r] for r in d["matrix"]],
                 dtype=float)
    lim = np.nanmax(np.abs(M))
    fig, ax = plt.subplots(figsize=(8.2, 7.0), facecolor=SURFACE)
    im = ax.imshow(M, cmap=DIVERGING, norm=TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim))
    ax.set_xticks(range(len(ids))); ax.set_xticklabels(ids)
    ax.set_yticks(range(len(ids))); ax.set_yticklabels(ids)
    ax.set_xticks(np.arange(-.5, len(ids), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(ids), 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)   # 2px surface gap between cells
    ax.tick_params(which="minor", length=0)
    ax.tick_params(colors=INK2, labelsize=10, length=0)
    for i in range(len(ids)):
        for j in range(len(ids)):
            if i == j:
                ax.text(j, i, "-", ha="center", va="center", color=MUTED, fontsize=9)
                continue
            v = M[i, j]
            rel = abs(v) / lim
            ax.text(j, i, "%+.0f" % (v / 1000.0), ha="center", va="center",
                    fontsize=7.5,
                    color=("#ffffff" if rel > 0.55 else INK))
    cb = fig.colorbar(im, ax=ax, fraction=0.043, pad=0.03)
    cb.set_label("interaction  I(i,j) = B(i+j) - B(i) - B(j)   [vehicle-seconds]",
                 color=INK2, fontsize=9)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_visible(False)
    ax.set_title("Pairwise project interaction at user equilibrium\n"
                 "cells in thousands of vehicle-seconds\n"
                 "red = complementary (pair worth more than the sum of its parts)\n"
                 "blue = substitutive (pair worth less)",
                 color=INK, fontsize=11, pad=12, loc="left")
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(os.path.join(OUT, "interaction_heatmap.png"), dpi=170,
                facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def frontier():
    rows = list(csv.DictReader(open(os.path.join(OUT, "pareto_frontier.csv"))))
    B = [float(r["budget"]) for r in rows]
    Y = [float(r["best_benefit_s"]) / 1000.0 for r in rows]
    lab = [r["best_subset"] for r in rows]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8.6, 7.4), facecolor=SURFACE,
                                  gridspec_kw=dict(height_ratios=[2.1, 1.0], hspace=0.42))
    style(ax); style(ax2)
    ax.plot(B, Y, color=SERIES1, linewidth=2.0, marker="o", markersize=7,
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    # chord from first to last point: a concave frontier lies ON OR ABOVE it
    ax.plot([B[0], B[-1]], [Y[0], Y[-1]], color=MUTED, linewidth=1.2,
            linestyle=(0, (4, 3)), zorder=2)
    for x, y, t in zip(B, Y, lab):
        ax.annotate(t, (x, y), textcoords="offset points", xytext=(0, 11),
                    ha="center", fontsize=7.6, color=INK2)
    ax.set_xlabel("budget  [monetary units]", color=INK2, fontsize=10)
    ax.set_ylabel("best achievable TSTT benefit\n[thousand vehicle-seconds]",
                  color=INK2, fontsize=10)
    ax.set_title("Budget vs best achievable benefit\n"
                 "(exhaustive over every budget-feasible subset at each budget level)\n"
                 "dashed line = chord; the frontier dipping BELOW it marks a non-concave region",
                 color=INK, fontsize=11.5, pad=12, loc="left")

    marg = [(Y[k] - Y[k - 1]) / (B[k] - B[k - 1]) for k in range(1, len(B))]
    xm = [B[k] for k in range(1, len(B))]
    cols = [SERIES1 if (k == 0 or marg[k] <= marg[k - 1] + 1e-9) else SERIES2
            for k in range(len(marg))]
    ax2.bar(xm, marg, width=1.9, color=cols, edgecolor=SURFACE, linewidth=2)
    ax2.axhline(0, color="#c3c2b7", linewidth=1)
    ax2.set_xlabel("budget  [monetary units]", color=INK2, fontsize=10)
    ax2.set_ylabel("marginal benefit\nper extra MU  [k veh-s / MU]", color=INK2, fontsize=10)
    ax2.set_title("Marginal return on the last budget increment  "
                  "(orange = increased vs the previous step, i.e. NON-concave)",
                  color=INK, fontsize=10.5, pad=10, loc="left")
    fig.savefig(os.path.join(OUT, "pareto_frontier.png"), dpi=170,
                facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    heatmap(); frontier()
    print("wrote", os.path.join(OUT, "interaction_heatmap.png"))
    print("wrote", os.path.join(OUT, "pareto_frontier.png"))
