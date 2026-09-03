#!/usr/bin/env python3
"""Deliverable figures.  Palette values come from the dataviz skill's validated
reference instance (references/palette.md): sequential = single blue hue
100->700 for magnitude; categorical slots 1/2/3 = blue/orange/aqua for identity.
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
import numpy as np                                     # noqa: E402

BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
             "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
             "#0d366b"]
SEQ = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#b8b7b2"
SURFACE = "#fcfcfb"

SETBACKS = [0, 10, 25, 40, 60, 90]
MAXGAPS = [1.0, 2.0, 3.0, 5.0, 8.0]
LEVELS = ["low", "med", "high"]


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=8, length=3, width=0.8)


# ---------------------------------------------------------------------------
def surface_fig(A, out):
    """Delay surface over (setback x max-gap), one panel per demand level."""
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.3), facecolor=SURFACE)
    for ax, lv in zip(axes, LEVELS):
        g = A["E1_surface"][lv]["grid"]
        M = np.array([[g[f"{sb:g}|{mg:g}"]["delay"] for mg in MAXGAPS]
                      for sb in SETBACKS])
        im = ax.imshow(M, cmap=SEQ, aspect="auto", origin="lower")
        best_sb = A["E1_surface"][lv]["best_setback"]
        best_mg = A["E1_surface"][lv]["best_max_gap"]
        vmin, vmax = M.min(), M.max()
        for i, sb in enumerate(SETBACKS):
            for j, mg in enumerate(MAXGAPS):
                v = M[i, j]
                key = f"sb{sb:g}_mg{mg:g}"
                tie = not A["E1_surface"][lv]["cells"][key][
                    "worse_than_best_significant"]
                col = "#ffffff" if (v - vmin) / max(1e-9, vmax - vmin) > 0.55 else INK
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=8.5, color=col,
                        fontweight="bold" if tie else "normal")
                if tie:
                    ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False,
                                               ec="#eb6834", lw=1.6))
        ax.plot([MAXGAPS.index(best_mg)], [SETBACKS.index(best_sb)], marker="o",
                ms=13, mfc="none", mec="#eb6834", mew=2.4)
        ax.set_xticks(range(len(MAXGAPS)))
        ax.set_xticklabels([f"{m:g}" for m in MAXGAPS])
        ax.set_yticks(range(len(SETBACKS)))
        ax.set_yticklabels([f"{s:g}" for s in SETBACKS])
        ax.set_xlabel("max-gap  (s)", fontsize=9, color=INK2)
        if lv == "low":
            ax.set_ylabel("detector setback from stop line  (m)",
                          fontsize=9, color=INK2)
        ax.set_title(f"{lv} demand", fontsize=10.5, color=INK, pad=8)
        style(ax)
        cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
        cb.ax.tick_params(colors=INK2, labelsize=7.5, length=2)
        cb.outline.set_visible(False)
    fig.suptitle("Mean vehicle delay (s/veh) over detector setback x max-gap  "
                 "— 5 CRN seeds per cell", fontsize=12, color=INK, y=0.99)
    fig.text(0.5, 0.005, "orange outline = not statistically distinguishable "
             "from the best cell (paired 95% CI on the CRN difference); "
             "circle = best cell", ha="center", fontsize=8, color=INK2)
    fig.tight_layout(rect=[0, 0.035, 1, 0.94])
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------------------
def mechanism_fig(A, out):
    """The two failure mechanisms on either side of the optimum, per approach."""
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 7.4), facecolor=SURFACE)
    for col, lv in enumerate(LEVELS):
        for row, (road, pre) in enumerate((("major", "A"), ("minor", "C"))):
            ax = axes[row][col]
            d = A["E3_per_approach"].get(f"{road}_{lv}")
            if not d:
                continue
            sb = [r["setback"] for r in d["rows"]]
            prem = [r["f_premature_gapout"] for r in d["rows"]]
            cut = [r["f_cut_with_blind_queue"] for r in d["rows"]]
            dly = [r["delay"] for r in d["rows"]]
            ci = [r["ci"] for r in d["rows"]]
            ax.plot(sb, prem, lw=2, color=CAT[0], marker="o", ms=7,
                    label="premature gap-out\n(vehicle arriving within 5 s, unserved)")
            ax.plot(sb, cut, lw=2, color=CAT[1], marker="s", ms=7,
                    label="green cut with blind-zone queue\n(queued veh between detector & stop line)")
            ax.axvline(d["sumo_default_setback"], color=MUTED, lw=1.4, ls="--")
            ax.text(d["sumo_default_setback"], 1.02,
                    f"SUMO default {d['sumo_default_setback']:.0f} m",
                    fontsize=7.5, color=INK2, ha="center",
                    transform=ax.get_xaxis_transform())
            ax.axvline(d["best_setback"], color=CAT[2], lw=1.6)
            ax.set_ylim(-0.03, 1.05)
            ax.set_xlabel("detector setback (m)", fontsize=9, color=INK2)
            if col == 0:
                ax.set_ylabel(f"{road} approach\nfraction of green ends",
                              fontsize=9, color=INK2)
            ax.set_title(f"{road} ({'60' if road=='major' else '40'} km/h) — "
                         f"{lv} demand", fontsize=10, color=INK)
            style(ax)
            ax2 = ax.twiny()      # secondary axis carries NO second y-scale;
            ax2.set_axis_off()    # delay is drawn as annotated text instead
            for x, y, c in zip(sb, dly, ci):
                ax.annotate(f"{y:.0f}±{c:.0f}s", (x, 0.02), fontsize=7,
                            color=INK2, ha="center", rotation=90, va="bottom")
            if row == 0 and col == 0:
                ax.legend(fontsize=7.5, frameon=False, loc="upper center",
                          labelcolor=INK2)
    fig.suptitle("The two detector-placement failure mechanisms  "
                 "(vertical green line = empirical best setback; "
                 "annotations = mean delay ± 95% CI)",
                 fontsize=11.5, color=INK, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------------------
def fault_fig(A, out):
    """Fault degradation vs healthy actuated AND vs the Webster fixed-time plan."""
    order = ["webster", "healthy", "stuckon_partial", "stuckon_major",
             "stuckoff_partial", "stuckoff_minor", "stuckoff_major",
             "failsafe_healthy", "failsafe_stuckon_major",
             "failsafe_stuckoff_major"]
    lab = {"webster": "Webster fixed-time", "healthy": "actuated, healthy",
           "stuckon_partial": "stuck-ON, 1 lane", "stuckon_major": "stuck-ON, both major thru",
           "stuckoff_partial": "stuck-OFF, 1 lane", "stuckoff_minor": "stuck-OFF, minor thru",
           "stuckoff_major": "stuck-OFF, both major thru",
           "failsafe_healthy": "fail-safe maxDur, healthy",
           "failsafe_stuckon_major": "fail-safe maxDur, stuck-ON",
           "failsafe_stuckoff_major": "fail-safe maxDur, stuck-OFF"}
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 5.6), facecolor=SURFACE,
                             sharey=True)
    for ax, lv in zip(axes, LEVELS):
        T = A["E4_E5_faults"][lv]
        names = [n for n in order if n in T]
        vals = [T[n]["delay_robust"] for n in names]
        cis = [T[n].get("delay_robust_ci") or 0 for n in names]
        cols = []
        for n in names:
            if n == "webster":
                cols.append(MUTED)
            elif n in ("healthy", "failsafe_healthy"):
                cols.append(CAT[2])
            elif n.startswith("failsafe"):
                cols.append(CAT[3])
            else:
                cols.append(CAT[1])
        y = np.arange(len(names))
        ax.barh(y, vals, xerr=cis, color=cols, height=0.68,
                error_kw=dict(ecolor=INK2, lw=1, capsize=2.5))
        ax.axvline(T["webster"]["delay_robust"], color=INK2, lw=1.2, ls="--")
        ax.set_yticks(y)
        ax.set_yticklabels([lab[n] for n in names], fontsize=8.5, color=INK2)
        ax.invert_yaxis()
        ax.set_xscale("log")
        ax.set_xlabel("system delay per scheduled vehicle (s), log scale",
                      fontsize=9, color=INK2)
        ax.set_title(f"{lv} demand", fontsize=10.5, color=INK)
        style(ax)
        for yy, v, ci in zip(y, vals, cis):
            ax.text((v + ci) * 1.10, yy, f"{v:.0f}", va="center", fontsize=7.8,
                    color=INK2)
    fig.suptitle("Detector-fault degradation, censoring-robust delay  "
                 "(dashed line = Webster fixed-time baseline; bars = 95% CI, "
                 "5 CRN seeds)", fontsize=11.5, color=INK, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    A = json.load(open(sys.argv[1]))
    od = sys.argv[2]
    os.makedirs(od, exist_ok=True)
    surface_fig(A, os.path.join(od, "delay_surface_setback_x_maxgap.png"))
    mechanism_fig(A, os.path.join(od, "failure_mechanisms_by_setback.png"))
    fault_fig(A, os.path.join(od, "fault_degradation.png"))
    print("figures written to", od)
