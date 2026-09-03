"""
Compute evacuation clearance metrics from tripinfo/summary output and plot the
clearance-time comparison curve for two or more release strategies (e.g.
simultaneous vs. staged).

Metrics per strategy: clearance time at 90%/95%/100% of vehicles evacuated
(from sorted tripinfo arrival times), peak simultaneous in-network vehicle
count (from summary.xml's "running" attribute -- read directly, not
estimated), mean travel time, mean depart delay.

Usage:
    python analyze_clearance.py \
        --run "Simultaneous (0-300s)=runs/simultaneous" \
        --run "Staged (0-900s, 3 zones)=runs/staged" \
        --out-json metrics.json --out-plot clearance_comparison.png
"""

import argparse
import json
import os
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args():
    p = argparse.ArgumentParser(description="Compute and plot evacuation clearance-time comparison across release strategies.")
    p.add_argument("--run", action="append", required=True, help="label=run_dir (containing tripinfo.xml and summary.xml), repeatable")
    p.add_argument("--out-json", default="metrics.json")
    p.add_argument("--out-plot", default="clearance_comparison.png")
    return p.parse_args()


def parse_tripinfo(path):
    arrivals, durations, departs, depdelays = [], [], [], []
    for _, el in ET.iterparse(path):
        if el.tag == "tripinfo":
            arrivals.append(float(el.get("arrival")))
            durations.append(float(el.get("duration")))
            departs.append(float(el.get("depart")))
            depdelays.append(float(el.get("departDelay")))
            el.clear()
    return arrivals, durations, departs, depdelays


def parse_summary(path):
    times, running = [], []
    for _, el in ET.iterparse(path):
        if el.tag == "step":
            times.append(float(el.get("time")))
            running.append(int(el.get("running")))
            el.clear()
    return times, running


def pct_time(sorted_arrivals, frac):
    n = len(sorted_arrivals)
    k = min(max(int(frac * n) - 1, 0), n - 1)
    return sorted_arrivals[k]


def main():
    args = parse_args()
    results, curves, peak_curves = {}, {}, {}

    for spec in args.run:
        label, run_dir = spec.split("=", 1)
        arr, dur, dep, dd = parse_tripinfo(os.path.join(run_dir, "tripinfo.xml"))
        times, running = parse_summary(os.path.join(run_dir, "summary.xml"))
        arr_sorted = sorted(arr)
        n = len(arr_sorted)
        peak = max(running)
        peak_t = times[running.index(peak)]
        res = {
            "n_evacuated": n,
            "clearance_90pct_s": round(pct_time(arr_sorted, 0.90), 1),
            "clearance_95pct_s": round(pct_time(arr_sorted, 0.95), 1),
            "clearance_100pct_s": round(arr_sorted[-1], 1),
            "peak_in_network_vehicles": peak,
            "peak_time_s": round(peak_t, 1),
            "mean_travel_time_s": round(sum(dur) / n, 1),
            "mean_depart_delay_s": round(sum(dd) / n, 1),
            "last_depart_s": round(max(dep), 1),
        }
        results[label] = res
        curves[label] = arr_sorted
        peak_curves[label] = (times, running)
        print(label)
        for k, v in res.items():
            print(f"   {k}: {v}")
        print()

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w") as f:
        json.dump(results, f, indent=2)

    palette = ["#d1495b", "#2e86ab", "#3a9679", "#f4a261"]
    colors = {label: palette[i % len(palette)] for i, label in enumerate(curves)}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))
    for label, arr_sorted in curves.items():
        n = len(arr_sorted)
        frac = [(i + 1) / n * 100 for i in range(n)]
        ax1.plot(arr_sorted, frac, color=colors[label], lw=2.2, label=label)
        for p in (90, 95, 100):
            t = pct_time(arr_sorted, p / 100.0)
            ax1.plot([t], [p], "o", color=colors[label], ms=5)
    ax1.axhline(90, color="gray", ls=":", lw=0.8)
    ax1.axhline(95, color="gray", ls=":", lw=0.8)
    ax1.set_xlabel("Simulation time (s)")
    ax1.set_ylabel("Vehicles evacuated (cumulative %)")
    ax1.set_title("Network clearance curve")
    ax1.legend(loc="lower right", fontsize=9)
    ax1.grid(alpha=0.3)

    for label, (times, running) in peak_curves.items():
        ax2.plot(times, running, color=colors[label], lw=1.8, label=label)
    ax2.set_xlabel("Simulation time (s)")
    ax2.set_ylabel("Vehicles simultaneously in network")
    ax2.set_title("In-network accumulation (peak load)")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(alpha=0.3)

    fig.suptitle("Emergency evacuation: release-strategy comparison", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(args.out_plot) or ".", exist_ok=True)
    fig.savefig(args.out_plot, dpi=130)
    print(f"saved plot: {args.out_plot}")


if __name__ == "__main__":
    main()
