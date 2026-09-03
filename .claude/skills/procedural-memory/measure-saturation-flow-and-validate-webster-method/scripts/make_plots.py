#!/usr/bin/env python3
"""Figures for the Webster-from-first-principles study.

Palette: categorical slots 1-6 of the dataviz reference palette (light mode),
assigned in fixed order and never cycled.  Static PNG => light surface only.
"""
import os
import sys
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT

CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#dcdcd8"
SURF = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "grid.color": GRID, "grid.linewidth": 0.8,
    "font.size": 10, "axes.titlesize": 12, "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False,
})


def style(ax):
    ax.grid(True, axis="y", alpha=0.9)
    ax.set_axisbelow(True)


# ------------------------------------------------ Fig 1: headway vs position
def fig_headway(sat):
    sat_names = list(sat)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    ax = axes[0]
    for i, (vt, r) in enumerate(sat.items()):
        h = r["headway"]["mean_headway_by_n"]
        ns = sorted(int(k) for k in h)
        ns = [n for n in ns if r["headway"]["n_obs_by_n"][str(n)] >= 0.9 * r["headway"]["cycles_used"]]
        ax.plot(ns, [h[str(n)] for n in ns], "-o", color=CAT[i], lw=2, ms=5,
                mec=SURF, mew=1.2, label=vt)
    xmax = max(ns) + 2
    ax.set_xlim(0.5, xmax)
    ax.set_ylim(1.15, 3.15)
    r1 = ax.axhline(2.0, color=INK2, ls=":", lw=1.2,
                    label="tlsCycleAdaptation $-H$ default: 2.0 s = 1800 veh/h/ln")
    r2 = ax.axhline(3600 / 1900.0, color=INK2, ls="--", lw=1.2,
                    label="HCM-textbook 1900 veh/h/ln: $h_s$ = 1.89 s")
    ref = ax.legend(handles=[r1, r2], fontsize=8, loc="upper right")
    ax.add_artist(ref)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_xlabel("queue position n (vehicle after green onset)")
    ax.set_ylabel("mean discharge headway $h_n$  [s]")
    ax.set_title("Discharge headway vs queue position\n(rear-bumper stop-line crossings, E1 instant loop)",
                 loc="left")
    ax.legend(handles=[l for l in ax.lines if l.get_label() in sat_names],
              ncol=3, fontsize=8, loc="lower right", columnspacing=1.0)
    style(ax)

    # right: the green-duration regression
    ax = axes[1]
    for i, (vt, r) in enumerate(sat.items()):
        rg = r["regression"]
        ax.plot(rg["greens"], rg["veh_per_cycle"], "o", color=CAT[i], ms=7,
                mec=SURF, mew=1.2, label=vt)
        xs = [0, max(rg["greens"]) + 4]
        ax.plot(xs, [rg["intercept"] + rg["slope"] * x for x in xs],
                "-", color=CAT[i], lw=2, alpha=0.85)
    ax.set_xlabel("displayed green g  [s]")
    ax.set_ylabel("vehicles discharged per cycle  $N_d$")
    ax.set_title("Window-free estimator: $N_d(g)=(s/3600)(g-l_1+e)$\nslope $\\rightarrow s$, intercept $\\rightarrow l_1$",
                 loc="left")
    ax.legend(ncol=2, fontsize=8, loc="upper left")
    ax.set_xlim(0, max(rg["greens"]) + 4)
    style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig1_headway_vs_queue_position.png"), dpi=160)
    plt.close(fig)


# --------------------------------- Fig 2: Webster vs simulated delay-vs-cycle
LEVEL_TITLE = {"under": "Undersaturated", "critical": "Near-critical",
               "over": "Oversaturated"}


def fig_sweep(sw):
    order = ["under", "critical", "over"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), sharex=True)
    for k, lvl in enumerate(order):
        L = sw["levels"][lvl]
        ax = axes[k]
        cs = sorted(int(c) for c in L["sim"])
        sim = [L["sim"][str(c)]["mean_timeLoss"] for c in cs]
        web = [L["webster"][str(c)]["delay"] for c in cs]
        wc = [c for c, w in zip(cs, web) if w is not None]
        wv = [w for w in web if w is not None]
        ax.plot(cs, sim, "-o", color=CAT[0], lw=2.2, ms=5, mec=SURF, mew=1.2,
                label="simulated mean timeLoss (tripinfo)")
        if wv:
            ax.plot(wc, wv, "-s", color=CAT[1], lw=2.2, ms=5, mec=SURF, mew=1.2,
                    label="Webster predicted delay $d(C)$")
        # empirical optimum + flatness band
        bi = min(range(len(cs)), key=lambda i: sim[i])
        ax.plot([cs[bi]], [sim[bi]], "o", ms=12, mfc="none", mec=CAT[0], mew=2)
        best = sim[bi]
        b5 = [c for c, v in zip(cs, sim) if v <= 1.05 * best]
        ax.axvspan(min(b5), max(b5), color=CAT[0], alpha=0.10, lw=0)
        if L["C_opt"]:
            ax.axvline(L["C_opt"], color=CAT[1], ls="--", lw=1.4)
            ax.text(L["C_opt"] + 2, ax.get_ylim()[0], "Webster $C_{opt}$=%.0f s" % L["C_opt"],
                    fontsize=8, color=CAT[1], va="bottom", ha="left")
        else:
            ax.text(0.5, 0.55, "Webster's $C_{opt}=(1.5L+5)/(1-Y)$ is\nUNDEFINED here: "
                               "$Y$=%.2f $\\geq$ 1\n(and $d(C)$ diverges: $x\\geq$1 at every $C$)"
                    % L["Y"], transform=ax.transAxes, fontsize=9, color=CAT[1],
                    ha="center", va="center")
        ax.set_title("%s  (Y=%.2f)\nsim opt C=%d s; within 5%%: %d-%d s"
                     % (LEVEL_TITLE[lvl], L["Y"], cs[bi], min(b5), max(b5)), loc="left")
        ax.set_xlabel("cycle length C  [s]")
        if k == 0:
            ax.set_ylabel("mean delay per vehicle  [s]")
        ax.legend(fontsize=8, loc="upper left" if k == 0 else "upper right")
        style(ax)
    fig.suptitle("Webster's analytical delay vs brute-force SUMO cycle-length sweep "
                 "(identical demand, seed and network at every C)", x=0.005, ha="left",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(OUT, "fig2_webster_vs_simulated_delay.png"), dpi=160)
    plt.close(fig)


def main():
    sat = json.load(open(os.path.join(WORK, "saturation_results.json")))
    fig_headway(sat)
    sw = json.load(open(os.path.join(WORK, "sweep_results.json")))
    fig_sweep(sw)
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
