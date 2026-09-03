#!/usr/bin/env python3
"""Figures for the CAV-penetration bottleneck-capacity study.

Palette: validated categorical slots 1-3 (blue/orange/aqua) from the project's
default data-viz palette -- passes the all-pairs CVD and normal-vision floors in
light mode.  Aqua sits below 3:1 contrast on the light surface, so every series
also carries a direct label and a distinct marker (the documented relief rule),
and the same numbers appear in results_table.md.
"""
import os
import sys
import json
import math
import statistics as st

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))

C = {"ACC": "#2a78d6", "CACC": "#eb6834", "HUMAN_FAST": "#1baf7a",
     "HUMAN": "#52514e", "HUMAN_SIGMA0": "#8a887f", "CACC_TIGHT": "#4a3aa7"}
MK = {"ACC": "o", "CACC": "s", "HUMAN_FAST": "^", "HUMAN": "D",
      "HUMAN_SIGMA0": "v", "CACC_TIGHT": "P"}
LBL = {"ACC": "ACC", "CACC": "CACC", "HUMAN_FAST": "HUMAN-FAST (control)",
       "HUMAN": "HUMAN", "HUMAN_SIGMA0": "HUMAN sigma=0", "CACC_TIGHT": "CACC tau=0.6"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e3e2dd"
PLAT_DY = {"ACC": 14, "CACC": -16, "HUMAN_FAST": 0}      # stagger overlapping labels
END_DY = {"ACC": 9, "CACC": -1, "HUMAN_FAST": -11}


def style(ax, title, xlab, ylab):
    ax.set_title(title, color=INK, fontsize=11, loc="left", pad=10)
    ax.set_xlabel(xlab, color=INK2, fontsize=9)
    ax.set_ylabel(ylab, color=INK2, fontsize=9)
    ax.grid(True, color=GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8.5, length=0)


def fig_capacity_vs_p(R):
    sw = R.get("penetration_sweeps", {})
    if not sw:
        return
    fig, ax = plt.subplots(figsize=(8.2, 5.2), dpi=170)
    style(ax, "Bottleneck queue-discharge capacity vs. CAV market penetration",
          "AV market penetration p", "sustained discharge flow  (veh/h, 2-lane bottleneck)")
    for arm in ["HUMAN_FAST", "ACC", "CACC"]:
        if arm not in sw:
            continue
        d = sw[arm]
        p = np.array(d["p"], float)
        y = np.array(d["discharge_mean"], float)
        ci = np.array([c if c is not None else 0.0 for c in d["ci95"]], float)
        ax.fill_between(p, y - ci, y + ci, color=C[arm], alpha=0.16, lw=0, zorder=2)
        ax.plot(p, y, color=C[arm], lw=2.0, marker=MK[arm], ms=6.5,
                mec="white", mew=1.4, zorder=3, label=LBL[arm])
        ax.annotate(LBL[arm], (p[-1], y[-1]), textcoords="offset points",
                    xytext=(8, 0), color=C[arm], fontsize=9, va="center", weight="bold")
        # the fitted quadratic, to show the fit is real and not eyeballed
        f = d.get("fit", {}).get("2")
        if f is None:
            f = d.get("fit", {}).get(2)
        if f:
            xs = np.linspace(0, 1, 100)
            ax.plot(xs, np.polyval(f["coef"], xs), color=C[arm], lw=1.0,
                    ls=(0, (4, 3)), alpha=0.75, zorder=2)
    ax.axhline(sw.get("ACC", {}).get("discharge_mean", [0])[0], color=INK2, lw=1,
               ls=":", zorder=1)
    b0 = sw.get("ACC", {}).get("discharge_mean", [0])[0]
    ax.annotate("all-human baseline (%.0f veh/h)" % b0, (1.02, b0),
                color=INK2, fontsize=8, va="center", ha="left")
    ax.set_xlim(-0.02, 1.24)
    ax.set_xticks([0, .2, .4, .5, .6, .8, 1.0])
    ax.set_xticklabels(["0%", "20%", "40%", "50%", "60%", "80%", "100%"])
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)
    fig.text(0.5, 0.012, "shaded band = 95% t confidence interval over 8 replications "
             "(Common Random Numbers across p);  dashed = fitted quadratic",
             ha="center", color=INK2, fontsize=8)
    fig.tight_layout(rect=[0, 0.035, 1, 1])
    fig.savefig(os.path.join(OUTDIR, "fig1_capacity_vs_penetration.png"))
    plt.close(fig)


def fig_fd(fd):
    order = [t for t in ["HUMAN", "HUMAN_SIGMA0", "HUMAN_FAST", "ACC", "CACC", "CACC_TIGHT"]
             if t in fd]
    n = len(order)
    if not n:
        return
    fig, axes = plt.subplots(2, 3, figsize=(11.0, 6.6), dpi=170, sharex=True, sharey=True)
    axes = axes.ravel()
    for i, ty in enumerate(order):
        ax = axes[i]
        pts = np.array(fd[ty], float)          # (k_per_lane, q_per_lane, v)
        if not len(pts):
            continue
        k = pts[:, 0]
        q = pts[:, 1]
        m = (k > 0) & (q > 0)
        ax.scatter(k[m], q[m], s=7, color=C[ty], alpha=0.35, lw=0, zorder=3)
        style(ax, LBL[ty], "density  (veh/km/lane)", "flow  (veh/h/lane)")
        if m.sum():
            qmax = np.percentile(q[m], 99)
            kc = k[m][int(np.argmax(q[m]))]
            ax.annotate("peak %.0f veh/h/ln\nat %.0f veh/km/ln" % (qmax, kc),
                        (0.97, 0.72), xycoords="axes fraction", ha="right",
                        color=INK2, fontsize=8)
    for j in range(n, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("Fundamental diagram per homogeneous fleet  (spatial edgeData over the whole "
                 "2496 m approach, 60 s aggregation, all replications pooled)",
                 color=INK, fontsize=11, x=0.012, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(OUTDIR, "fig2_fundamental_diagrams.png"))
    plt.close(fig)


def fig_leader(R):
    L = R.get("leader_is_av_fraction", {})
    if not L:
        return
    fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=170)
    style(ax, "Measured fraction of AV vehicles whose immediate leader is also an AV",
          "AV market penetration p", "P(leader is an AV | ego is an AV)")
    xs = np.linspace(0, 1, 50)
    ax.plot(xs, xs, color=INK2, lw=1.2, ls="--", zorder=2)
    ax.plot(xs, xs ** 2, color=INK2, lw=1.2, ls=":", zorder=2)
    ax.annotate("naive  p", (0.955, 0.905), color=INK2, fontsize=8.5, rotation=31)
    ax.annotate("naive  p$^2$", (0.86, 0.75 ** 2), color=INK2, fontsize=8.5, rotation=33)
    for arm, seq in L.items():
        rnd = [(s["p"], s["measured"]) for s in seq
               if s.get("arrangement") != "platoon" and s.get("measured") not in (None, "")]
        plat = [(s["p"], s["measured"]) for s in seq
                if s.get("arrangement") == "platoon" and s.get("measured") not in (None, "")]
        if rnd:
            rnd.sort()
            ax.plot([a for a, _ in rnd], [b for _, b in rnd], color=C[arm], lw=2.0,
                    marker=MK[arm], ms=6.5, mec="white", mew=1.4, zorder=4,
                    label="%s, random" % LBL[arm])
            ax.annotate(LBL[arm], rnd[-1], textcoords="offset points",
                        xytext=(9, END_DY[arm]), color=C[arm], fontsize=8.5, weight="bold")
        for a, b in plat:
            ax.scatter([a], [b], s=110, marker="*", color=C[arm], zorder=5,
                       edgecolors="white", linewidths=1.0)
            ax.annotate("%s platooned  %.2f" % (LBL[arm].split(" (")[0], b), (a, b),
                        textcoords="offset points", xytext=(-12, PLAT_DY[arm]),
                        color=C[arm], fontsize=8, weight="bold", ha="right")
    ax.set_xlim(0, 1.30)
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)
    fig.text(0.5, 0.030, "Measured directly from SUMO leader queries in the FCD output, over the last 1000 m "
             "of the approach plus the bottleneck, t >= 1200 s.",
             ha="center", color=INK2, fontsize=8)
    fig.text(0.5, 0.008, "Stars = the deliberately platooned arrangement carrying the IDENTICAL 50% AV count. "
             "Random placement tracks p, not p-squared.",
             ha="center", color=INK2, fontsize=8)
    fig.tight_layout(rect=[0, 0.062, 1, 1])
    fig.savefig(os.path.join(OUTDIR, "fig3_leader_is_av_fraction.png"))
    plt.close(fig)


def fig_mechanism(R):
    hb = R.get("homogeneous_baselines", [])
    if not hb:
        return
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=170)
    style(ax, "Homogeneous-fleet bottleneck capacity: the mechanism control changes the story",
          "", "sustained discharge flow  (veh/h, 2-lane bottleneck)")
    names = [h["fleet"] for h in hb]
    y = [h["discharge"] for h in hb]
    e = [h["ci95"] if isinstance(h["ci95"], (int, float)) else 0 for h in hb]
    cols = [C[n] for n in names]
    xpos = np.arange(len(names))
    ax.bar(xpos, y, width=0.62, color=cols, zorder=3,
           edgecolor="white", linewidth=2.0)
    ax.errorbar(xpos, y, yerr=e, fmt="none", ecolor=INK, elinewidth=1.3,
                capsize=4, zorder=4)
    base = y[names.index("HUMAN")] if "HUMAN" in names else y[0]
    ax.axhline(base, color=INK2, lw=1, ls=":", zorder=2)
    for i, (n, v) in enumerate(zip(names, y)):
        ax.annotate("%.0f\n%+.1f%%" % (v, 100 * (v - base) / base), (i, v),
                    textcoords="offset points", xytext=(0, 10), ha="center",
                    color=INK, fontsize=8.6, weight="bold")
    ax.set_xticks(xpos)
    ax.set_xticklabels(["%s\n%s, tau=%.1f" % (LBL[n].split(" (")[0],
                                              {"HUMAN": "Krauss s=0.5", "HUMAN_SIGMA0": "Krauss s=0",
                                               "HUMAN_FAST": "Krauss s=0", "ACC": "ACC model",
                                               "CACC": "CACC model", "CACC_TIGHT": "CACC model"}[n],
                                              {"HUMAN": 1.3, "HUMAN_SIGMA0": 1.3, "HUMAN_FAST": 0.9,
                                               "ACC": 0.9, "CACC": 0.9, "CACC_TIGHT": 0.6}[n])
                        for n in names], fontsize=8)
    ax.set_ylim(0, max(y) * 1.22)
    fig.text(0.5, 0.012, "error bars = 95% t CI over 8 replications; dotted line = all-human "
             "baseline.  HUMAN-FAST is Krauss with the SAME tau as ACC/CACC.",
             ha="center", color=INK2, fontsize=8)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(os.path.join(OUTDIR, "fig4_mechanism_control.png"))
    plt.close(fig)


def fig_capdrop(R):
    hb = R.get("homogeneous_baselines", [])
    if not hb:
        return
    fig, ax = plt.subplots(figsize=(8.6, 4.6), dpi=170)
    style(ax, "Capacity drop: pre-breakdown peak flow vs. sustained queue-discharge flow",
          "", "flow  (veh/h, 2-lane bottleneck)")
    names = [h["fleet"] for h in hb]
    xpos = np.arange(len(names))
    pk = [h["pre_breakdown_peak"] for h in hb]
    dc = [h["discharge"] for h in hb]
    ax.bar(xpos - 0.19, pk, width=0.34, color="#8a887f", zorder=3,
           edgecolor="white", linewidth=2.0, label="pre-breakdown peak (uncongested upstream)")
    ax.bar(xpos + 0.19, dc, width=0.34, color=[C[n] for n in names], zorder=3,
           edgecolor="white", linewidth=2.0, label="queue-discharge (congested upstream)")
    for i, h in enumerate(hb):
        ax.annotate("%+.1f%%" % (-h["capacity_drop_pct"]), (i + 0.19, dc[i]),
                    textcoords="offset points", xytext=(0, 6), ha="center",
                    color=INK, fontsize=8.4, weight="bold")
    ax.set_xticks(xpos)
    ax.set_xticklabels([LBL[n].split(" (")[0] for n in names], fontsize=8.5)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)
    ax.set_ylim(0, max(pk + dc) * 1.2)
    fig.text(0.5, 0.012, "percentages are discharge relative to the pre-breakdown peak; "
             "negative = a genuine capacity drop", ha="center", color=INK2, fontsize=8)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(os.path.join(OUTDIR, "fig5_capacity_drop.png"))
    plt.close(fig)


def main():
    R = json.load(open(os.path.join(OUTDIR, "results.json")))
    fig_capacity_vs_p(R)
    fig_leader(R)
    fig_mechanism(R)
    fig_capdrop(R)
    fp = os.path.join(ROOT, "fd_points.json")
    if os.path.exists(fp):
        fig_fd(json.load(open(fp)))
    print("figures written to", OUTDIR)


if __name__ == "__main__":
    main()
