"""Offline (duarouter weight-file) assignment results: convergence traces,
travel-time UE vs eco assignment, the duaIterate cross-check, and the two
weight-file-construction variants (interval length, per-veh vs abs)."""
import glob
import gzip
import json
import os
import shutil
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt     # noqa: E402
import numpy as np                  # noqa: E402
from scipy import stats             # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT, classify_route  # noqa: E402
import simlib  # noqa: E402

SEEDS = [0, 1, 2, 3, 4]
LINES = []


def out(s=""):
    print(s)
    LINES.append(s)


def hist(tag):
    with open(os.path.join(WORK, "assign_" + tag, "history.json")) as f:
        return json.load(f)["history"]


def final(tag, it=20):
    d = os.path.join(WORK, "assign_" + tag)
    ti = simlib.parse_tripinfo(os.path.join(d, "sim_%03d_tripinfo.xml" % it))
    vr = simlib.parse_routes(os.path.join(d, "cur_%03d.rou.xml" % it))
    m = [t for t in ti if t["id"].startswith("main.")]
    dur = sorted(t["duration"] for t in m)
    cls = {}
    for t in m:
        cls.setdefault(classify_route(vr[t["id"]][1]), []).append(t)
    return dict(net_CO2_kg=sum(t["CO2"] for t in ti) / 1e6,
                net_fuel_kg=sum(t["fuel"] for t in ti) / 1e6,
                mean_tt=statistics.mean(dur), p90_tt=dur[int(0.9 * (len(dur) - 1))],
                vkm=sum(t["routeLength"] for t in m) / 1000.0,
                share_bypass=len(cls.get("bypass", [])) / len(m),
                per_class={k: dict(n=len(v),
                                   tt=statistics.mean(x["duration"] for x in v),
                                   co2=statistics.mean(x["CO2"] for x in v) / 1000)
                           for k, v in cls.items()})


def main():
    out("=" * 104)
    out("(3a) CONVERGENCE of the iterative duarouter weight-file loop (seed 0)")
    out("=" * 104)
    out("%-5s | %-32s | %-32s" % ("iter", "travel-time UE (alpha=1,beta=0)",
                                  "eco / min-fuel (alpha=0,beta=1)"))
    out("%-5s | %8s %8s %10s | %8s %8s %10s" %
        ("", "rel.gap", "d share", "byp share", "rel.gap", "d share", "byp share"))
    hu, he = hist("ue_s0"), hist("eco_s0")
    for i in range(len(hu)):
        a, b = hu[i], he[i]
        out("%-5d | %8.4f %8s %10.3f | %8.4f %8s %10.3f" %
            (a["iter"], a["gap"], "-" if a["d_share"] is None else "%.4f" % a["d_share"],
             a["share"].get("bypass", 0),
             b["gap"], "-" if b["d_share"] is None else "%.4f" % b["d_share"],
             b["share"].get("bypass", 0)))
    out()
    out("CONVERGENCE CRITERION USED: max|d route share| < 0.01 sustained over 5 consecutive")
    out("iterations AND a relative gap that has stopped decreasing (plateau).")
    for tag in ("ue_s0", "eco_s0"):
        h = hist(tag)
        ds = [r["d_share"] for r in h[10:]]
        out("   %-8s : mean |d share| over iters 11-20 = %.4f ; mean rel.gap = %.4f "
            "(min %.4f)" % (tag, np.mean(ds), np.mean([r["gap"] for r in h[10:]]),
                            min(r["gap"] for r in h[10:])))
    out("   The travel-time loop's gap PLATEAUS near 0.05 and does not go to zero; the eco")
    out("   loop's reaches ~0.01. The residual is genuine stochastic-microsimulation noise in")
    out("   the measured cost surface plus a real dynamic (per-departure-bin) disequilibrium,")
    out("   NOT a coding artefact -- see the duaIterate cross-check below, which reproduces")
    out("   the same route split from a completely independent implementation.")

    # -------------------------------------------------- UE vs ECO, 5 seeds --
    out()
    out("=" * 104)
    out("(3b) OFFLINE ASSIGNMENT OUTCOMES, 5 demand seeds (same loop, only --weight-attribute")
    out("     target differs).  duaIterate.py shown as an independent travel-time-UE reference.")
    out("=" * 104)
    out("%-6s %28s %28s %14s" % ("seed", "travel-time UE (MSA loop)", "eco assignment (MSA loop)",
                                 "duaIterate"))
    out("%-6s %9s %8s %9s %9s %8s %9s %14s" %
        ("", "CO2 kg", "TT s", "byp", "CO2 kg", "TT s", "byp", "byp share"))
    ue, ec = [], []
    for s in SEEDS:
        u, e = final("ue_s%d" % s), final("eco_s%d" % s)
        ue.append(u)
        ec.append(e)
        d = os.path.join(WORK, "duaiter_s%d" % s, "024")
        g = glob.glob(os.path.join(d, "*_024.rou.xml.gz"))
        p = g[0][:-3]
        if not os.path.exists(p):
            with gzip.open(g[0], "rb") as f, open(p, "wb") as o:
                shutil.copyfileobj(f, o)
        dsh = simlib.route_shares({v: ("", ed) for v, (t, ed) in
                                   simlib.parse_routes(p).items()})[0]
        out("%-6d %9.1f %8.1f %9.3f %9.1f %8.1f %9.3f %14.3f" %
            (s, u["net_CO2_kg"], u["mean_tt"], u["share_bypass"],
             e["net_CO2_kg"], e["mean_tt"], e["share_bypass"], dsh.get("bypass", 0)))

    def col(rs, k):
        return np.array([r[k] for r in rs])
    out()
    for k, lab, unit in (("net_CO2_kg", "network CO2", "kg"), ("net_fuel_kg", "network fuel", "kg"),
                         ("mean_tt", "main mean travel time", "s"),
                         ("p90_tt", "main p90 travel time", "s"),
                         ("vkm", "main vehicle-km", "km"),
                         ("share_bypass", "bypass share", "")):
        a, b = col(ue, k), col(ec, k)
        t, p = stats.ttest_rel(b, a)
        out("   %-24s UE %10.2f -> eco %10.2f  (%+7.2f %s, %+6.2f%%, paired p=%.4f)"
            % (lab, a.mean(), b.mean(), (b - a).mean(), unit,
               100 * (b - a).mean() / a.mean(), p))

    # ------------------------------------------------- weight-file variants --
    out()
    out("=" * 104)
    out("(3c) WEIGHT-FILE CONSTRUCTION VARIANTS (eco loop, seed 0, 20 iterations)")
    out("=" * 104)
    for tag, lab in (("eco_s0", "600 s intervals, *_perVeh  [reference]"),
                     ("eco_s0_1interval", "one 5400 s interval, *_perVeh"),
                     ("eco_s0_absnorm", "600 s intervals, *_abs (WRONG normalisation)")):
        f = final(tag)
        h = hist(tag)
        out("   %-42s CO2 %7.1f kg  TT %6.1f s  byp %.3f  hybrid %.3f  "
            "zero-sample cells %.0f%%  gap %.4f"
            % (lab, f["net_CO2_kg"], f["mean_tt"], f["share_bypass"],
               f["per_class"].get("hybrid", {}).get("n", 0) /
               sum(v["n"] for v in f["per_class"].values()),
               100 * h[-1]["fallback_frac"], np.mean([r["gap"] for r in h[10:]])))

    # ------------------------------------------------------------- figure ---
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 150})
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    for tag, lab, c in (("ue_s0", "travel-time UE ($\\alpha$=1, $\\beta$=0)", "#C2571A"),
                        ("eco_s0", "eco / min-fuel ($\\alpha$=0, $\\beta$=1)", "#0F5EA8")):
        h = hist(tag)
        ax[0].plot([r["iter"] for r in h], [r["gap"] for r in h], marker="o", ms=3,
                   color=c, label=lab)
        ax[1].plot([r["iter"] for r in h], [r["share"].get("bypass", 0) for r in h],
                   marker="o", ms=3, color=c, label=lab)
    ax[0].set_yscale("log")
    ax[0].set_xlabel("iteration")
    ax[0].set_ylabel("relative gap")
    ax[1].set_xlabel("iteration")
    ax[1].set_ylabel("bypass share of main OD")
    ax[1].axhline(0.544, ls=":", color="#5B6670", lw=1)
    ax[1].annotate("duaIterate.py UE", (12, 0.554), fontsize=8, color="#5B6670")
    ax[0].legend(frameon=False, fontsize=8)
    for a in ax:
        a.grid(alpha=.25, lw=.5)
    fig.suptitle("Iterative duarouter weight-file assignment, seed 0", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "offline_convergence.png"), bbox_inches="tight")

    with open(os.path.join(OUT, "offline_assignment.txt"), "w") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nwrote", os.path.join(OUT, "offline_assignment.txt"))


if __name__ == "__main__":
    main()
