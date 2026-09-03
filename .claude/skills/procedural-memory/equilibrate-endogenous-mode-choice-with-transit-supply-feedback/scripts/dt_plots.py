"""Figures for the Downs-Thomson episode.

  fig1_cost_vs_mode_share.png   4 panels: base|expanded x feedback on|off, with the
                                measured car and transit generalized-cost curves and
                                every equilibrium (stable = filled, unstable = hollow)
  fig2_demand_sweep.png         equilibrium common cost and car share vs total demand

Colours are the validated categorical slots 1 (blue) and 2 (orange) from the dataviz
reference palette; every series is direct-labelled as well as legended, so identity is
never carried by colour alone.
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RES = os.path.join(OUT, "results")
FIG = os.path.join(OUT, "figures")
os.makedirs(FIG, exist_ok=True)

CAR = "#2a78d6"
TRANSIT = "#eb6834"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#dcdcd8"


def read(name):
    with open(os.path.join(RES, name)) as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def roots_from(ps, gaps):
    """Sign changes of the measured gap curve; '-> +' stable, '+ -> -' unstable."""
    out = []
    for i in range(len(ps) - 1):
        g0, g1 = gaps[i], gaps[i + 1]
        if g0 == g1:
            continue
        if g0 < 0 <= g1 or g0 > 0 >= g1:
            t = -g0 / (g1 - g0)
            out.append((ps[i] + t * (ps[i + 1] - ps[i]), "stable" if g0 < 0 else "unstable"))
    return out


def fig1():
    rows = read("cost_curves.csv")
    eqs = {e["cell"]: e for e in read("equilibria.csv")}
    cells = [("base_fbON", "BASE road  ·  Mohring feedback ON"),
             ("expanded_fbON", "EXPANDED road  ·  Mohring feedback ON"),
             ("base_fbOFF", "BASE road  ·  feedback OFF (headway frozen)"),
             ("expanded_fbOFF", "EXPANDED road  ·  feedback OFF (headway frozen)")]
    fig, axes = plt.subplots(2, 2, figsize=(12.6, 9.0), sharex=True)
    base_cost = fnum(eqs["base_fbON"]["common_cost"]) if "base_fbON" in eqs else None

    for ax, (cell, title) in zip(axes.ravel(), cells):
        r = sorted([x for x in rows if x["cell"] == cell], key=lambda x: float(x["p_car"]))
        ps = [fnum(x["p_car"]) for x in r]
        cc = [fnum(x["car_cost"]) for x in r]
        tc = [fnum(x["transit_cost"]) for x in r]
        gg = [c - t for c, t in zip(cc, tc)]

        ax.plot(ps, cc, color=CAR, lw=2.0, zorder=3)
        ax.plot(ps, tc, color=TRANSIT, lw=2.0, zorder=3)
        ax.set_yscale("log")
        ax.set_title(title, fontsize=11, color=INK, loc="left", pad=10)
        ax.grid(True, which="major", color=GRID, lw=0.7, zorder=0)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9)

        # direct labels at the right edge
        ax.annotate("car", (ps[-1], cc[-1]), xytext=(4, 0), textcoords="offset points",
                    color=CAR, fontsize=9, va="center", fontweight="bold")
        ax.annotate("transit", (ps[-1], tc[-1]), xytext=(4, 0), textcoords="offset points",
                    color=TRANSIT, fontsize=9, va="center", fontweight="bold")

        # every equilibrium visible in the measured curves
        for p_r, kind in roots_from(ps, gg):
            y = None
            for i in range(len(ps) - 1):
                if ps[i] <= p_r <= ps[i + 1]:
                    f = (p_r - ps[i]) / (ps[i + 1] - ps[i])
                    y = tc[i] + f * (tc[i + 1] - tc[i])
                    break
            if y is None:
                continue
            filled = kind == "stable"
            ax.plot([p_r], [y], "o", ms=10, mfc=INK if filled else "white",
                    mec=INK, mew=1.8, zorder=5)
            ax.annotate(f"{'stable' if filled else 'unstable'} eq\np*={p_r:.2f}, C={y:.0f}s",
                        (p_r, y), xytext=(0, 16 if filled else -34),
                        textcoords="offset points", ha="center", fontsize=8.5, color=INK)

        if base_cost and cell != "base_fbON":
            ax.axhline(base_cost, color=INK2, lw=1.0, ls=(0, (4, 3)), zorder=2)
            ax.annotate(f"BASE equilibrium cost {base_cost:.0f}s",
                        (0.94, base_cost), xytext=(0, -13), textcoords="offset points",
                        ha="right", fontsize=8, color=INK2)

    for ax in axes[1]:
        ax.set_xlabel("car mode share  p", fontsize=10, color=INK2)
    for ax in axes[:, 0]:
        ax.set_ylabel("door-to-door generalized cost  (s, log scale)", fontsize=10, color=INK2)

    handles = [plt.Line2D([], [], color=CAR, lw=2.0, label="car: mean (tripinfo duration + departDelay)"),
               plt.Line2D([], [], color=TRANSIT, lw=2.0, label="transit: mean (ride waitingTime + ride duration)"),
               plt.Line2D([], [], marker="o", ls="", mfc=INK, mec=INK, ms=8, label="stable equilibrium"),
               plt.Line2D([], [], marker="o", ls="", mfc="white", mec=INK, mew=1.8, ms=8,
                          label="unstable equilibrium (tipping point)")]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, -0.005))
    fig.suptitle("Mode-choice equilibrium on a road+transit corridor: where the two cost curves cross",
                 fontsize=13, color=INK, x=0.012, ha="left", y=0.985)
    fig.tight_layout(rect=(0, 0.055, 1, 0.96))
    p = os.path.join(FIG, "fig1_cost_vs_mode_share.png")
    fig.savefig(p, dpi=150, facecolor="#fcfcfb")
    print("wrote", p)


def fig2():
    rows = read("demand_sweep.csv")
    ns = sorted({int(float(r["n_total"])) for r in rows})
    sel = {c: {int(float(r["n_total"])): r for r in rows if r["cell"] == c}
           for c in ("base_fbON", "expanded_fbON")}

    def meancost(r):
        # demand-weighted mean cost per traveller -- unlike the mid-point of the two
        # modal costs, this stays meaningful at a corner where one mode carries ~nobody
        return fnum(r["person_hours"]) * 3600 / fnum(r["n_total"])

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.8))

    # shade every demand level at which the expansion made the average traveller worse off
    par = [n for n in ns if meancost(sel["expanded_fbON"][n]) > meancost(sel["base_fbON"][n])]
    if par:
        lo = 0.5 * (max([n for n in ns if n < min(par)], default=min(par)) + min(par))
        for ax in axes:
            ax.axvspan(lo, max(ns) * 1.02, color="#eb6834", alpha=0.08, zorder=0)
        axes[0].annotate("PARADOX: expansion made\neveryone worse off",
                         (lo, 1.0), xycoords=("data", "axes fraction"),
                         xytext=(8, -14), textcoords="offset points",
                         fontsize=9, color="#b4441c", va="top")
        axes[0].annotate("expansion\nhelps", (lo, 0.0), xycoords=("data", "axes fraction"),
                         xytext=(-8, 10), textcoords="offset points", ha="right",
                         fontsize=9, color=INK2, va="bottom")

    for cell, colour, lab, dy in (("base_fbON", CAR, "BASE road", -20),
                                  ("expanded_fbON", TRANSIT, "EXPANDED road", 12)):
        d = sel[cell]
        y0 = [meancost(d[n]) for n in ns]
        y1 = [fnum(d[n]["p_car_eq"]) for n in ns]
        corner = [d[n]["equilibrium_type"] == "corner" for n in ns]
        for ax, y in ((axes[0], y0), (axes[1], y1)):
            ax.plot(ns, y, "-", color=colour, lw=2.0, zorder=3)
            for n, v, c in zip(ns, y, corner):
                ax.plot([n], [v], "o", ms=8, mfc="white" if c else colour,
                        mec=colour, mew=2.0, zorder=4)
        axes[0].annotate(lab, (ns[-1], y0[-1]), xytext=(-4, dy), ha="right",
                         textcoords="offset points", color=colour, fontsize=9,
                         fontweight="bold")
        axes[1].annotate(lab, (ns[-1], y1[-1]), xytext=(-4, dy), ha="right",
                         textcoords="offset points", color=colour, fontsize=9,
                         fontweight="bold")

    axes[0].set_yscale("log")
    axes[0].set_title("Equilibrium mean generalized cost per traveller",
                      fontsize=11, color=INK, loc="left")
    axes[0].set_ylabel("mean cost per traveller (s, log scale)", fontsize=10, color=INK2)
    axes[1].set_title("Equilibrium car mode share", fontsize=11, color=INK, loc="left")
    axes[1].set_ylabel("car share  p*", fontsize=10, color=INK2)
    for ax in axes:
        ax.set_xlabel("total O-D demand  N  (travellers per 1200 s)", fontsize=10, color=INK2)
        ax.grid(True, color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9)

    handles = [plt.Line2D([], [], color=CAR, lw=2.0, label="BASE road (r2 = 1 lane)"),
               plt.Line2D([], [], color=TRANSIT, lw=2.0, label="EXPANDED road (r2 = 2 lanes)"),
               plt.Line2D([], [], marker="o", ls="", mfc=INK, mec=INK, ms=7,
                          label="interior stable equilibrium"),
               plt.Line2D([], [], marker="o", ls="", mfc="white", mec=INK, mew=2, ms=7,
                          label="corner: transit line collapses")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Demand sweep: where the Downs-Thomson paradox switches on",
                 fontsize=13, color=INK, x=0.012, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 0.93))
    pth = os.path.join(FIG, "fig2_demand_sweep.png")
    fig.savefig(pth, dpi=150, facecolor="#fcfcfb")
    print("wrote", pth)


if __name__ == "__main__":
    fig1()
    if os.path.exists(os.path.join(RES, "demand_sweep.csv")):
        fig2()
