#!/usr/bin/env python3
"""STEP 8 -- deliverables: tables (markdown/CSV) and the two spatial figures.

Figures follow the project's chart conventions: fixed-order categorical hues
(validated: light surface #fcfcfb, all six checks pass), one y-axis per chart,
legend always present, recessive grid, direct labels where the mark contrast is
low.  Every number plotted comes from a raw SUMO output file parsed by
lc_common.py -- nothing is hand-entered.
"""
import os, sys, json, math, csv, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#4a3aa7"]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURF = "#fcfcfb"
SEEDS = tuple(5000 + 13 * i for i in range(6))
BIN = 100.0


def style(ax):
    ax.set_facecolor(SURF)
    ax.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.label.set_color(INK2); ax.yaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def collect_profiles(name, p, ctx=None):
    """Run `len(SEEDS)` replications, keep the raw dirs, and build
    (i) LC density vs distance-to-gore per reason, LC per 100 m per 1000 veh
    (ii) cumulative fraction of exiting vehicles that have reached an
         exit-capable lane, vs distance to gore."""
    r = evaluate_runs([p], seeds=SEEDS, ctx=ctx, want_profiles=True, keep=True)[0]
    reps = [x for x in r["reps"] if x.get("ok")]
    dens = collections.defaultdict(lambda: collections.defaultdict(float))
    nveh = 0.0
    arrive = []
    for rep in reps:
        wd = rep["wd"]
        ev = L.parse_lanechanges(os.path.join(wd, "lanechanges.xml"))
        ed = L.parse_edgedata(os.path.join(wd, "edgedata.xml"))
        nveh += float(ed["A"]["entered"]) + float(ed["A"]["departed"])
        for e in ev:
            if not (L.WARMUP <= e["t"] < L.T_END_MEAS):
                continue
            d = L.GORE_X - e["x"]
            if d < 0 or d > L.GORE_X:
                continue
            b = int(d // BIN) * BIN
            dens[b][L.reason_class(e["reason"])] += 1.0
            dens[b]["all"] += 1.0
        arrive.extend(rep["arrive_curve"])
    # normalise: LC per 100 m per 1000 vehicles
    prof = {}
    for b, c in dens.items():
        prof[b] = {k: v / (nveh / 1000.0) for k, v in c.items()}
    n_ex = sum(rep["n_cohort"] for rep in reps)
    return dict(name=name, prof=prof, n_veh=nveh, arrive=sorted(arrive),
                n_exiters=n_ex, agg=r, n_rep=len(reps))


def fig_lc_density(sets, path):
    fig, ax = plt.subplots(figsize=(9.5, 5.2), facecolor=SURF)
    style(ax)
    reasons = ["strategic", "speedGain", "keepRight", "cooperative"]
    s = sets[0]
    xs = sorted(s["prof"].keys())
    centres = [b + BIN / 2 for b in xs]
    for i, rs in enumerate(reasons):
        y = [s["prof"][b].get(rs, 0.0) for b in xs]
        if max(y) <= 0:
            continue
        ax.plot(centres, y, lw=2.0, color=CAT[i], label=rs, zorder=3)
    ytot = [s["prof"][b].get("all", 0.0) for b in xs]
    ax.plot(centres, ytot, lw=2.0, ls="--", color=INK2, label="all reasons",
            zorder=2)
    ax.axvspan(0, 300, color="#eda100", alpha=0.10, zorder=1,
               label="300 m deceleration / aux lane")
    ax.set_xlabel("distance to gore (m)")
    ax.set_ylabel("lane changes per 100 m per 1000 vehicles")
    ax.set_title("LC density vs distance to gore — %s" % s["name"], fontsize=12)
    ax.invert_xaxis()
    ax.set_yscale("log")
    leg = ax.legend(frameon=False, fontsize=9, labelcolor=INK2)
    fig.tight_layout(); fig.savefig(path, dpi=150, facecolor=SURF)
    plt.close(fig)


def fig_lc_density_compare(sets, path):
    fig, ax = plt.subplots(figsize=(9.5, 5.2), facecolor=SURF)
    style(ax)
    for i, s in enumerate(sets):
        xs = sorted(s["prof"].keys())
        centres = [b + BIN / 2 for b in xs]
        y = [s["prof"][b].get("all", 0.0) for b in xs]
        ax.plot(centres, y, lw=2.0, color=CAT[i], label=s["name"], zorder=3)
    ax.axvspan(0, 300, color="#eda100", alpha=0.10, zorder=1,
               label="300 m deceleration / aux lane")
    ax.set_xlabel("distance to gore (m)")
    ax.set_ylabel("lane changes per 100 m per 1000 vehicles (all reasons)")
    ax.set_title("LC density vs distance to gore — parameter vectors compared",
                 fontsize=12)
    ax.invert_xaxis(); ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2)
    fig.tight_layout(); fig.savefig(path, dpi=150, facecolor=SURF)
    plt.close(fig)


def fig_cumulative(sets, path):
    fig, ax = plt.subplots(figsize=(9.5, 5.2), facecolor=SURF)
    style(ax)
    for i, s in enumerate(sets):
        a = np.array(s["arrive"])
        if len(a) == 0:
            continue
        d = np.sort(a)[::-1]          # descending distance-to-gore
        frac = np.arange(1, len(d) + 1) / float(s["n_exiters"])
        ax.plot(d, frac, lw=2.0, color=CAT[i], label=s["name"], zorder=3)
    ax.axhline(0.85, color=MUTED, lw=1.0, ls=":", zorder=2)
    ax.axvline(L.TARGET_P85, color="#d03b3b", lw=1.4, ls="--", zorder=2)
    ax.text(L.TARGET_P85, 0.06, " field target:\n 85th pctile at 400 m",
            fontsize=9, color="#d03b3b", ha="left")
    ax.axvspan(0, 300, color="#eda100", alpha=0.10, zorder=1,
               label="300 m deceleration / aux lane")
    ax.set_xlabel("distance to gore (m)")
    ax.set_ylabel("fraction of exiting vehicles already in an exit-capable lane")
    ax.set_title("Cumulative exit-lane arrival vs distance to gore", fontsize=12)
    ax.set_xlim(L.GORE_X, 0)
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    fig.tight_layout(); fig.savefig(path, dpi=150, facecolor=SURF)
    plt.close(fig)


def main():
    cal = json.load(open(os.path.join(L.TBL, "calibration.json")))
    calp = {k: float(v) for k, v in cal["best_params"].items()}
    sets = [collect_profiles("SUMO default LC2013", L.full_params()),
            collect_profiles("calibrated", calp)]
    dur = dict(calp); dur["lcDuration"] = 3.0
    sets.append(collect_profiles("calibrated, --lanechange.duration 3 s", dur))

    fig_lc_density(sets, os.path.join(L.FIG, "lc_density_vs_distance_default.png"))
    fig_lc_density_compare(sets, os.path.join(L.FIG, "lc_density_vs_distance_compare.png"))
    fig_cumulative(sets, os.path.join(L.FIG, "cumulative_exit_lane_arrival.png"))

    # --- CSV backing both figures -----------------------------------------
    with open(os.path.join(L.TBL, "lc_density_profile.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vector", "d_to_gore_lo_m", "d_to_gore_hi_m", "all",
                    "strategic", "speedGain", "keepRight", "cooperative",
                    "units"])
        for s in sets:
            for b in sorted(s["prof"]):
                c = s["prof"][b]
                w.writerow([s["name"], int(b), int(b + BIN),
                            round(c.get("all", 0), 4), round(c.get("strategic", 0), 4),
                            round(c.get("speedGain", 0), 4),
                            round(c.get("keepRight", 0), 4),
                            round(c.get("cooperative", 0), 4),
                            "LC per 100m per 1000 veh"])
    with open(os.path.join(L.TBL, "cumulative_exit_arrival.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vector", "d_to_gore_m", "cum_fraction_in_exit_lane"])
        for s in sets:
            a = np.sort(np.array(s["arrive"]))[::-1]
            for d in np.arange(3600, -1, -100.0):
                frac = float((a >= d).sum()) / s["n_exiters"]
                w.writerow([s["name"], int(d), round(frac, 5)])
    json.dump({s["name"]: dict(n_veh=s["n_veh"], n_exiters=s["n_exiters"],
                               n_rep=s["n_rep"],
                               agg={k: v for k, v in s["agg"].items() if k != "reps"})
               for s in sets},
              open(os.path.join(L.TBL, "profile_runs.json"), "w"), indent=2,
              default=str)
    print("wrote figures to", L.FIG)


if __name__ == "__main__":
    main()
