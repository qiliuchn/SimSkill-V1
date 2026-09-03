#!/usr/bin/env python3
"""
Test for clockwise hysteresis in the ungated core MFD by pooling all ungated
seeds.  For each run the interval of maximum accumulation splits the trajectory
into a LOADING branch (before) and an UNLOADING branch (after); both are binned
by accumulation and compared.  Clockwise hysteresis => at the same accumulation,
production on the unloading branch is LOWER than on the loading branch.
"""
import argparse
import csv
import glob
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--out-png", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--width", type=float, default=25.0)
    args = ap.parse_args()

    load = defaultdict(list)
    unload = defaultdict(list)
    nruns = 0
    for p in sorted(glob.glob(args.pattern)):
        rows = list(csv.DictReader(open(p)))
        nruns += 1
        pts = [(float(r["t_end"]), float(r["n_mean"]), float(r["production_vehkm_h"]))
               for r in rows]
        t_peak = max(pts, key=lambda x: x[1])[0]
        for t, n, q in pts:
            if n <= 5:
                continue
            b = int(n // args.width)
            (load if t <= t_peak else unload)[b].append(q)

    bins = sorted(set(load) | set(unload))
    rowsout = []
    for b in bins:
        c = (b + 0.5) * args.width
        rowsout.append({
            "n_bin_center_veh": c,
            "loading_production_vehkm_h": round(mean(load[b]), 2) if load[b] else "",
            "loading_n_intervals": len(load[b]),
            "unloading_production_vehkm_h": round(mean(unload[b]), 2) if unload[b] else "",
            "unloading_n_intervals": len(unload[b]),
        })
    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rowsout[0].keys()))
        w.writeheader()
        w.writerows(rowsout)

    both = [r for r in rowsout
            if r["loading_n_intervals"] >= 5 and r["unloading_n_intervals"] >= 5]
    gap = [(r["n_bin_center_veh"],
            r["loading_production_vehkm_h"] - r["unloading_production_vehkm_h"])
           for r in both]

    fig, ax = plt.subplots(figsize=(8.5, 6))
    lx = [r["n_bin_center_veh"] for r in rowsout if r["loading_n_intervals"] >= 3]
    ly = [r["loading_production_vehkm_h"] for r in rowsout if r["loading_n_intervals"] >= 3]
    ux = [r["n_bin_center_veh"] for r in rowsout if r["unloading_n_intervals"] >= 3]
    uy = [r["unloading_production_vehkm_h"] for r in rowsout if r["unloading_n_intervals"] >= 3]
    ax.plot(lx, ly, "o-", color="#2a6f97", lw=2, label="loading branch (before n peaks)")
    ax.plot(ux, uy, "s--", color="#d1495b", lw=2, label="unloading branch (after n peaks)")
    ax.set_xlabel("core accumulation n(t) [veh]")
    ax.set_ylabel("core production [veh·km/h]")
    ax.set_title(f"Ungated core MFD, loading vs unloading branch ({nruns} seeds pooled)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.out_png, dpi=150)

    print(f"{nruns} ungated runs pooled")
    print("bin  loading  unloading  gap(load-unload)")
    for c, g in gap:
        print(f"{c:6.0f}  {dict((r['n_bin_center_veh'], r['loading_production_vehkm_h']) for r in both)[c]:8.0f}"
              f"  {dict((r['n_bin_center_veh'], r['unloading_production_vehkm_h']) for r in both)[c]:9.0f}  {g:8.0f}")
    if gap:
        print(f"mean gap over overlapping bins = {mean(g for _, g in gap):.1f} veh-km/h "
              f"({sum(1 for _, g in gap if g > 0)}/{len(gap)} bins positive "
              f"=> clockwise)")


if __name__ == "__main__":
    main()
