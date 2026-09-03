#!/usr/bin/env python3
"""Locate the crossover demand by linear interpolation of the paired difference,
with a bootstrap CI on the crossing point, and draw the sweep figure."""
import argparse
import csv
import random
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

C = {"twoway": "#1f4e9c", "oneway_fair": "#c0392b", "oneway_naive": "#7f8c8d"}
LBL = {"twoway": "A  two-way (2 lanes/cross-section)",
       "oneway_fair": "B  one-way pair, lane-matched (2 lanes/cross-section)",
       "oneway_naive": "C  one-way naive, UNFAIR (1 lane/cross-section)"}


def zero_cross(xs, ys):
    """First sign change of ys(xs), linearly interpolated."""
    for i in range(1, len(xs)):
        a, b = ys[i - 1], ys[i]
        # require a STRICT sign change: a metric that is identically zero across
        # the sweep (e.g. throughput while every trip still completes) has no
        # crossover, and must not be reported as crossing at the first level.
        if a * b < 0:
            return xs[i - 1] + (xs[i] - xs[i - 1]) * a / (a - b)
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", required=True)
    p.add_argument("--out-fig", required=True)
    p.add_argument("--out-csv", required=True)
    p.add_argument("--boot", type=int, default=4000)
    a = p.parse_args()

    runs = list(csv.DictReader(open(a.runs)))
    demands = sorted(set(int(r["demand"]) for r in runs))
    seeds = sorted(set(int(r["seed"]) for r in runs))
    val = {(int(r["demand"]), r["variant"], int(r["seed"])): r for r in runs}

    metrics = ["mean_duration_s", "mean_speed_ms", "mean_stops", "n_arrived",
               "vht_vehh"]
    res = []
    rng = random.Random(12345)
    for m in metrics:
        diffs = {}
        for d in demands:
            v = []
            for s in seeds:
                A = val.get((d, "twoway", s))
                B = val.get((d, "oneway_fair", s))
                if A and B:
                    v.append(float(B[m]) - float(A[m]))
            diffs[d] = v
        pt = zero_cross(demands, [sum(diffs[d]) / len(diffs[d]) for d in demands])
        boots = []
        for _ in range(a.boot):
            means = []
            for d in demands:
                v = diffs[d]
                means.append(sum(rng.choice(v) for _ in v) / len(v))
            z = zero_cross(demands, means)
            if z is not None:
                boots.append(z)
        boots.sort()
        lo = boots[int(0.025 * len(boots))] if boots else float("nan")
        hi = boots[int(0.975 * len(boots))] if boots else float("nan")
        res.append(dict(metric=m, crossover_vph=pt, boot_ci_lo=lo, boot_ci_hi=hi,
                        n_boot_with_crossing=len(boots), n_boot=a.boot))
        print("%-18s crossover = %s veh/h   bootstrap 95%% CI [%.0f, %.0f]"
              % (m, ("%.0f" % pt) if pt else "none", lo, hi))

    with open(a.out_csv, "w") as f:
        w = csv.DictWriter(f, list(res[0]))
        w.writeheader()
        for r in res:
            w.writerow(r)

    # ---------------- figure ----------------
    fig, axes = plt.subplots(1, 4, figsize=(19.5, 4.8))
    panels = [("mean_speed_ms", "network mean speed [m/s]"),
              ("mean_duration_s", "mean trip duration [s]"),
              ("mean_stops", "mean stops per vehicle")]
    for ax, (m, ylab) in zip(axes, panels):
        for v in ("twoway", "oneway_fair", "oneway_naive"):
            xs, ys, es = [], [], []
            for d in demands:
                vv = [float(val[(d, v, s)][m]) for s in seeds if (d, v, s) in val]
                if not vv:
                    continue
                mu = sum(vv) / len(vv)
                sd = (sum((x - mu) ** 2 for x in vv) / (len(vv) - 1)) ** 0.5
                xs.append(d)
                ys.append(mu)
                es.append(2.262 * sd / len(vv) ** 0.5)
            ax.errorbar(xs, ys, yerr=es, marker="o", ms=3.5, lw=1.5, capsize=2.5,
                        color=C[v], label=LBL[v])
        xc = next((r["crossover_vph"] for r in res if r["metric"] == m), None)
        if xc:
            ax.axvline(xc, color="#444444", ls="--", lw=1)
            ax.annotate("crossover\n%.0f veh/h" % xc, xy=(xc, ax.get_ylim()[1]),
                        xytext=(4, -14), textcoords="offset points",
                        fontsize=8, color="#444444", va="top")
        ax.set_xlabel("total demand [veh/h]")
        ax.set_ylabel(ylab)
        ax.grid(alpha=0.25, lw=0.5)
    axes[2].set_yscale("log")
    axes[0].legend(fontsize=7.5, loc="lower left")

    # 4th panel: the paired (CRN) difference itself, where the crossover lives
    ax = axes[3]
    for m, col, lab in (("mean_duration_s", "#c0392b", "mean trip duration [s]"),
                        ("mean_stops", "#e08a1e", "mean stops/veh (x50 s)")):
        xs, ys, es = [], [], []
        scale = 50.0 if m == "mean_stops" else 1.0
        for d in demands:
            v = [float(val[(d, "oneway_fair", s)][m]) -
                 float(val[(d, "twoway", s)][m]) for s in seeds if (d, "twoway", s) in val]
            mu = sum(v) / len(v)
            sd = (sum((x - mu) ** 2 for x in v) / (len(v) - 1)) ** 0.5
            xs.append(d)
            ys.append(mu * scale)
            es.append(2.262 * sd / len(v) ** 0.5 * scale)
        ax.errorbar(xs, ys, yerr=es, marker="o", ms=3.5, lw=1.5, capsize=2.5,
                    color=col, label=lab)
    ax.axhline(0, color="#000000", lw=1)
    ax.set_ylim(-60, 60)
    ax.set_xlabel("total demand [veh/h]")
    ax.set_ylabel("one-way MINUS two-way  (paired, CRN)")
    ax.set_title("below 0 = one-way better", fontsize=9)
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=7.5, loc="lower left")
    for m, col in (("mean_duration_s", "#c0392b"), ("mean_stops", "#e08a1e")):
        xc = next((r["crossover_vph"] for r in res if r["metric"] == m), None)
        if xc:
            ax.axvline(xc, color=col, ls="--", lw=1)
    fig.suptitle("One-way vs two-way grid: demand sweep, 10 CRN replications per "
                 "cell, error bars = 95% CI", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(a.out_fig, dpi=150)
    print("wrote", a.out_fig)


if __name__ == "__main__":
    main()
