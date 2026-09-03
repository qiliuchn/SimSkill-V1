#!/usr/bin/env python3
"""
Warrant plots.

  warrant_curves.png   hourly (major total, minor higher approach) points for
                       every scenario plotted against the MUTCD Warrant 2
                       (Figure 4C-1) and Warrant 3 (Figure 4C-3) threshold
                       curves, at both the 100 % and the 70 % column.  Points
                       are shown on BOTH the demand basis (open) and the
                       detector basis (filled), joined by a line so the
                       metering displacement is visible per hour.
  metering_curve.png   served / generated driveway volume vs the driveway's
                       nominal v/c, over the whole site-intensity sweep.
"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, SCEN, TABLES, N_HOURS, hour_label
import mutcd_warrants as W
import analyze as A

FIG = os.path.join(OUT, "figures")
os.makedirs(FIG, exist_ok=True)
CAT = ("2+", "1")     # 2+ major lanes each approach, 1 minor lane


def curve_xy(curves, floors, pct):
    xs = [x for x in range(300, 2001, 10)]
    ys = [max(W._interp(curves[CAT], x), floors[CAT[1]]) * pct / 100.0 for x in xs]
    return xs, ys


def main():
    man = json.load(open(os.path.join(SCEN, "demand", "demand_manifest.json")))
    scen_style = {"nobuild": ("tab:green", "o"), "build": ("tab:orange", "s"),
                  "build_high": ("tab:red", "^")}
    data = {}
    for scen in scen_style:
        data[scen] = {
            "demand": A.volumes_from_demand(scen, man),
            "detector": A.volumes_from_detectors(A.rundir(scen, "twsc", 11)),
        }

    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))
    for ax, (title, curves, floors) in zip(
            axes,
            [("MUTCD Warrant 2 - Four-Hour Vehicular Volume (Fig. 4C-1)",
              W.W2_CURVES, W.W2_FLOOR),
             ("MUTCD Warrant 3 - Peak Hour (Fig. 4C-3)",
              W.W3_CURVES, W.W3_FLOOR)]):
        xs, ys = curve_xy(curves, floors, 100)
        ax.plot(xs, ys, "k-", lw=2, label="threshold, 100% column")
        xs7, ys7 = curve_xy(curves, floors, 70)
        ax.plot(xs7, ys7, "k--", lw=1.6, label="threshold, 70% column")
        for scen, (c, m) in scen_style.items():
            dd = data[scen]["demand"]
            de = data[scen]["detector"]
            for h in range(N_HOURS):
                ax.plot([dd[h]["major"], de[h]["major"]],
                        [dd[h]["minor"], de[h]["minor"]],
                        color=c, lw=0.7, alpha=0.55, zorder=1)
            ax.scatter([r["major"] for r in dd], [r["minor"] for r in dd],
                       facecolors="none", edgecolors=c, marker=m, s=58,
                       label=f"{scen} - demand basis", zorder=3)
            ax.scatter([r["major"] for r in de], [r["minor"] for r in de],
                       color=c, marker=m, s=44, label=f"{scen} - detector basis",
                       zorder=4)
            # label the PM peak hour point on each series
            ax.annotate("17:00", (de[10]["major"], de[10]["minor"]),
                        textcoords="offset points", xytext=(5, -11),
                        fontsize=7.5, color=c)
        ax.set_xlim(600, 2000)
        ax.set_ylim(0, 430)
        ax.set_xlabel("Major-street total, both approaches (veh/h)")
        ax.set_ylabel("Higher-volume minor-street approach (veh/h)")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7.4, loc="upper right", ncol=2)
    fig.suptitle("Driveway TIA - hourly volumes (07:00-19:00) vs MUTCD volume-warrant curves\n"
                 "open marker = demand basis, filled = stop-bar detector basis; "
                 "the gap between them IS the metering error",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    p = os.path.join(FIG, "warrant_curves.png")
    fig.savefig(p, dpi=150)
    print("[plot] wrote", p)

    # ------------------------------------------------ metering vs v/c
    rows = list(csv.DictReader(open(os.path.join(TABLES, "sweep_demand_vs_served.csv"))))
    pts = [(float(r["driveway_vc_nominal"]), float(r["stopbar_over_generated"]))
           for r in rows if r["stopbar_over_generated"] not in ("", None)
           and float(r["driveway_nominal"]) > 20]
    fig2, ax = plt.subplots(figsize=(7.6, 5.2))
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=26, color="tab:blue", alpha=0.75)
    ax.axhline(1.0, color="k", lw=0.8, ls=":")
    ax.axvline(1.0, color="tab:red", lw=1.0, ls="--")
    ax.text(1.03, 0.06, "nominal v/c = 1", color="tab:red", fontsize=8.5)
    ax.set_xlabel("Driveway approach nominal v/c  (nominal demand / empirical hourly capacity)")
    ax.set_ylabel("stop-bar detector count / realised generated demand")
    ax.set_title("Stop-bar volume understates driveway demand exactly where the\n"
                 "warrant is close to being met", fontsize=10.5)
    ax.set_xlim(0, 7)
    ax.set_ylim(0, 1.1)
    ax.grid(alpha=0.25)
    fig2.tight_layout()
    p2 = os.path.join(FIG, "metering_curve.png")
    fig2.savefig(p2, dpi=150)
    print("[plot] wrote", p2)


if __name__ == "__main__":
    main()
