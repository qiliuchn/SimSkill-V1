#!/usr/bin/env python3
"""Throughput / delay surfaces and failure-mode plots for the bay-length sweep.

Colour: validated categorical slots 1-4 (blue/orange/aqua/yellow) for the four
SIGNAL conditions (identity), and the single-hue blue sequential ramp for the
throughput heatmap (magnitude). Aqua and yellow sit below 3:1 on the light
surface, so every series also carries a direct end-label (the relief rule).
Bay length is drawn on a CATEGORICAL axis because the last level ("full") is a
different kind of thing, not a longer number.
"""
import argparse
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt              # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

BAYS = ["10", "20", "30", "50", "75", "100", "150", "full"]
XLAB = ["10", "20", "30", "50", "75", "100", "150", "full\n(400 m)"]
SHARES = ["0.1", "0.25", "0.4"]
SIGS = ["split08", "split16", "split24", "actuated"]
SIGLAB = {"split08": "8 s left green", "split16": "16 s left green",
          "split24": "24 s left green", "actuated": "actuated"}
CAT = {"split08": "#2a78d6", "split16": "#eb6834",
       "split24": "#1baf7a", "actuated": "#eda100"}
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
       "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
INK, INK2, MUTED, SURF = "#0b0b0b", "#52514e", "#8b8a85", "#fcfcfb"
# as-designed plan per share = best feasible fixed-time split
PLAN = {"0.1": "split08", "0.25": "split16", "0.4": "split24"}


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
        ax.spines[s].set_linewidth(0.8)
    ax.grid(axis="y", color="#e6e5e1", lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=8, length=3, color=MUTED)


def decollide(vals, minsep):
    """Push overlapping end-labels apart vertically, preserving order."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = list(vals)
    for k in range(1, len(order)):
        i, j = order[k - 1], order[k]
        if out[j] - out[i] < minsep:
            out[j] = out[i] + minsep
    return out


def series(agg, share, sig, metric):
    y = [agg[f"{b}|{share}|{sig}"][metric] for b in BAYS]
    e = [agg[f"{b}|{share}|{sig}"].get(metric + "_ci", 0.0) or 0.0 for b in BAYS]
    e = [0.0 if (isinstance(v, float) and math.isnan(v)) else v for v in e]
    return y, e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agg", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    agg = json.load(open(a.agg))
    x = range(len(BAYS))

    # ---------------- Fig 1: throughput surface ----------------
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.1), sharey=True, facecolor=SURF)
    for ax, sh in zip(axes, SHARES):
        style(ax)
        ends = []
        for sig in SIGS:
            y, e = series(agg, sh, sig, "throughput_vph")
            ax.errorbar(x, y, yerr=e, color=CAT[sig], lw=2.0, marker="o", ms=5,
                        capsize=2.5, elinewidth=1.0, zorder=3,
                        markeredgecolor=SURF, markeredgewidth=1.2,
                        label=SIGLAB[sig] if sh == SHARES[0] else None)
            ends.append(y[-1])
        for sig, yl in zip(SIGS, decollide(ends, 26)):
            ax.annotate(SIGLAB[sig], (len(BAYS) - 1, yl), textcoords="offset points",
                        xytext=(8, 0), fontsize=7.5, color=CAT[sig], va="center",
                        annotation_clip=False)
        ax.axhline(800, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)
        ax.set_xticks(list(x))
        ax.set_xticklabels(XLAB, fontsize=7.5)
        ax.set_title(f"left turns = {int(float(sh)*100)}% of approach demand",
                     fontsize=9.5, color=INK, pad=8)
        ax.set_xlabel("left-turn bay length (m)", fontsize=8.5, color=INK2)
    axes[0].set_ylabel("north approach throughput (veh/h)", fontsize=8.5, color=INK2)
    axes[0].annotate("demand = 800 veh/h", (0.05, 806), fontsize=7, color=MUTED)
    fig.suptitle("Approach throughput vs left-turn bay length, by signal split",
                 fontsize=12, color=INK, x=0.012, ha="left", y=0.99)
    fig.text(0.012, 0.015, "mean of 5 seeds; bars = 95% t confidence interval. "
             "Total approach demand held at 800 veh/h in every cell.",
             fontsize=7.5, color=MUTED)
    fig.legend(loc="upper right", bbox_to_anchor=(0.995, 1.005), ncol=4,
               frameon=False, fontsize=8, labelcolor=INK2, handlelength=1.6,
               columnspacing=1.4)
    fig.tight_layout(rect=(0, 0.045, 0.90, 0.925))
    fig.savefig(os.path.join(a.outdir, "fig1_throughput_surface.png"), dpi=170,
                facecolor=SURF)
    plt.close(fig)

    # ---------------- Fig 2: per-movement delay ----------------
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.2), sharex=True, facecolor=SURF)
    for j, sh in enumerate(SHARES):
        for i, sig in enumerate([PLAN[sh], "actuated"]):
            ax = axes[i][j]
            style(ax)
            for metric, col, lab in (("timeloss_L", "#2a78d6", "LEFT movement"),
                                     ("timeloss_TR", "#eb6834", "THROUGH + right")):
                y, e = series(agg, sh, sig, metric)
                ax.errorbar(x, y, yerr=e, color=col, lw=2.0, marker="o", ms=5,
                            capsize=2.5, elinewidth=1.0, zorder=3,
                            markeredgecolor=SURF, markeredgewidth=1.2,
                            label=lab if (i == 0 and j == 0) else None)
            ax.set_title(f"{int(float(sh)*100)}% left  |  {SIGLAB[sig]}",
                         fontsize=9, color=INK, pad=6)
            ax.set_xticks(list(x))
            ax.set_xticklabels(XLAB, fontsize=7.5)
            if j == 0:
                ax.set_ylabel("mean time loss (s/veh)", fontsize=8.5, color=INK2)
            if i == 1:
                ax.set_xlabel("left-turn bay length (m)", fontsize=8.5, color=INK2)
    fig.suptitle("Who pays for a short bay: left-movement vs through-movement delay",
                 fontsize=12, color=INK, x=0.012, ha="left", y=0.99)
    fig.legend(loc="upper right", bbox_to_anchor=(0.995, 1.003), ncol=2,
               frameon=False, fontsize=8.5, labelcolor=INK2, handlelength=1.6,
               columnspacing=1.6)
    fig.text(0.012, 0.012, "Top row: best feasible fixed-time split for that left share. "
             "Bottom row: actuated. Mean of 5 seeds, 95% CI. Note the differing y-scales "
             "per panel.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.035, 1, 0.945))
    fig.savefig(os.path.join(a.outdir, "fig2_delay_by_movement.png"), dpi=170,
                facecolor=SURF)
    plt.close(fig)

    # ---------------- Fig 3: the two failure modes ----------------
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.0), sharex=True, facecolor=SURF)
    for j, sh in enumerate(SHARES):
        sig = PLAN[sh]
        ax = axes[0][j]
        style(ax)
        for metric, col, lab in (("overflow_s_per_cycle", "#2a78d6",
                                  "(a) BAY OVERFLOW"),
                                 ("blockage_s_per_cycle", "#eb6834",
                                  "(b) BAY BLOCKAGE")):
            y, e = series(agg, sh, sig, metric)
            ax.errorbar(x, y, yerr=e, color=col, lw=2.0, marker="o", ms=5,
                        capsize=2.5, elinewidth=1.0, zorder=3,
                        markeredgecolor=SURF, markeredgewidth=1.2)
            ax.annotate(lab, (0, y[0]), textcoords="offset points",
                        xytext=(6, 14 if "OVERFLOW" in lab else -18),
                        fontsize=7.5, color=col,
                        bbox=dict(fc=SURF, ec="none", pad=0.8))
        ax.set_title(f"{int(float(sh)*100)}% left  |  {SIGLAB[sig]}",
                     fontsize=9, color=INK, pad=6)
        if j == 0:
            ax.set_ylabel("seconds per cycle in which\nthe mode is active",
                          fontsize=8.5, color=INK2)

        ax = axes[1][j]
        style(ax)
        y, e = series(agg, sh, sig, "wasted_left_green_frac")
        ax.errorbar(x, [v * 100 for v in y], yerr=[v * 100 for v in e],
                    color="#1baf7a", lw=2.0, marker="o", ms=5, capsize=2.5,
                    elinewidth=1.0, zorder=3, markeredgecolor=SURF, markeredgewidth=1.2)
        ax.annotate("wasted left arrow", (0, y[0] * 100), textcoords="offset points",
                    xytext=(6, 14), fontsize=7.5, color="#1baf7a",
                    bbox=dict(fc=SURF, ec="none", pad=0.8))
        ax.set_ylim(-3, 100)
        ax.set_xticks(list(x))
        ax.set_xticklabels(XLAB, fontsize=7.5)
        ax.set_xlabel("left-turn bay length (m)", fontsize=8.5, color=INK2)
        if j == 0:
            ax.set_ylabel("% of protected left green with\nan empty bay but a "
                          "waiting left-turner", fontsize=8.5, color=INK2)
    fig.suptitle("The two failure modes, measured separately from per-second vehicle state",
                 fontsize=12, color=INK, x=0.012, ha="left", y=0.99)
    fig.text(0.012, 0.012, "(a) bay full -> a left-turner stops in the upstream through lane. "
             "(b) through queue past the bay entrance -> left-turners cannot reach the bay. "
             "Mean of 5 seeds, 95% CI.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.035, 1, 0.955))
    fig.savefig(os.path.join(a.outdir, "fig3_failure_modes.png"), dpi=170, facecolor=SURF)
    plt.close(fig)

    # ---------------- Fig 4: throughput heatmap surface ----------------
    cmap = LinearSegmentedColormap.from_list("seqblue", SEQ)
    fig, axes = plt.subplots(1, 3, figsize=(13.0, 3.9), facecolor=SURF)
    for ax, sh in zip(axes, SHARES):
        ref = max(agg[f"full|{sh}|{g}"]["throughput_vph"] for g in SIGS)
        M = [[100 * agg[f"{b}|{sh}|{sig}"]["throughput_vph"] / ref for b in BAYS]
             for sig in SIGS]
        im = ax.imshow(M, cmap=cmap, vmin=30, vmax=100, aspect="auto")
        ax.set_xticks(range(len(BAYS)))
        ax.set_xticklabels(XLAB, fontsize=7.5, color=INK2)
        ax.set_yticks(range(len(SIGS)))
        if sh == SHARES[0]:
            ax.set_yticklabels([SIGLAB[s] for s in SIGS], fontsize=8, color=INK2)
        else:
            ax.set_yticklabels([])
        for r in range(len(SIGS)):
            for c in range(len(BAYS)):
                v = M[r][c]
                ax.text(c, r, f"{v:.0f}", ha="center", va="center", fontsize=7,
                        color="#ffffff" if v > 72 else INK)
        ax.set_title(f"left turns = {int(float(sh)*100)}%", fontsize=9.5, color=INK, pad=7)
        ax.set_xlabel("bay length (m)", fontsize=8.5, color=INK2)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=axes, fraction=0.02, pad=0.015)
    cb.set_label("approach throughput, % of best unconstrained-lane result",
                 fontsize=8, color=INK2)
    cb.ax.tick_params(labelsize=7.5, colors=INK2, length=0)
    cb.outline.set_visible(False)
    fig.suptitle("Throughput surface over (bay length x left green split)",
                 fontsize=12, color=INK, x=0.012, ha="left", y=0.99)
    fig.text(0.012, -0.06, "Cell values are % of that left-share's best full-length-lane "
             "throughput; mean of 5 seeds. Numbers are printed in every cell, so the "
             "colour is redundant encoding.", fontsize=7.5, color=MUTED)
    fig.savefig(os.path.join(a.outdir, "fig4_throughput_heatmap.png"), dpi=170,
                facecolor=SURF, bbox_inches="tight")
    plt.close(fig)
    print("wrote 4 figures to", a.outdir)


if __name__ == "__main__":
    main()
