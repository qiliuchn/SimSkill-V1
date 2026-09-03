"""
Build a time-space mean-speed contour (heatmap) from E2 lane-area detector
output: distance along the corridor (y-axis) vs. simulation time (x-axis),
mean speed as color. Plots two runs side by side (e.g. baseline vs. VSL) so a
backward-propagating congestion shockwave -- and whether a control scheme
suppresses or delays it -- is visible directly.

Reads stations.json (from gen_e2_stations.py) for each station's cumulative
distance along the corridor, and each run's det_e2.xml for the per-interval
per-detector meanSpeed, averaged across all lanes at a station.

Usage:
    python plot_speed_contour.py \
        --stations detectors/stations.json \
        --run baseline=outputs/baseline/det_e2.xml \
        --run vsl=outputs/vsl/det_e2.xml \
        --bottleneck-dist 4500 --out plots/speed_contour.png
"""

import argparse
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="Build a time-space speed-contour heatmap from E2 detector output.")
    p.add_argument("--stations", required=True, help="stations.json written by gen_e2_stations.py")
    p.add_argument("--run", action="append", required=True, help="label=path/to/det_e2.xml, repeatable")
    p.add_argument("--bottleneck-dist", type=float, default=None, help="Distance along the corridor to mark with a dashed line (e.g. the lane-drop location)")
    p.add_argument("--out", default="speed_contour.png")
    return p.parse_args()


def station_of_detector(det_id, stations):
    # detector ids are "e2_s{station_index:02d}_{edge}_l{lane}"
    parts = det_id.split("_")
    si = int(parts[1][1:])
    return stations[si]


def build_grid(det_e2_path, stations):
    """{station_index: {time: [speeds across lanes]}} -> averaged (dist, times, speed_grid)."""
    per_station_time = defaultdict(lambda: defaultdict(list))
    for _, interval in ET.iterparse(det_e2_path, events=("end",)):
        if interval.tag != "interval":
            continue
        det_id = interval.get("id")
        si = int(det_id.split("_")[1][1:])
        t = float(interval.get("begin"))
        speed = float(interval.get("meanSpeed"))
        per_station_time[si][t].append(speed if speed >= 0 else np.nan)
        interval.clear()

    times = sorted({t for st in per_station_time.values() for t in st})
    station_idxs = sorted(per_station_time.keys())
    dist = np.array([stations[si]["dist"] for si in station_idxs])
    grid = np.full((len(station_idxs), len(times)), np.nan)
    for row, si in enumerate(station_idxs):
        for col, t in enumerate(times):
            vals = per_station_time[si].get(t)
            if vals:
                grid[row, col] = np.nanmean(vals)
    return dist, np.array(times), grid


def main():
    args = parse_args()
    stations = json.load(open(args.stations))["stations"]

    runs = []
    for spec in args.run:
        label, path = spec.split("=", 1)
        dist, times, grid = build_grid(path, stations)
        runs.append((label, dist, times, grid))

    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("#c9c9c9")

    fig, axes = plt.subplots(1, len(runs), figsize=(7.5 * len(runs), 6), sharey=True)
    if len(runs) == 1:
        axes = [axes]
    pc = None
    for ax, (label, dist, times, grid) in zip(axes, runs):
        spd_kmh = np.ma.masked_invalid(grid) * 3.6
        dd = np.concatenate(([dist[0] - (dist[1] - dist[0]) / 2 if len(dist) > 1 else dist[0] - 250],
                              (dist[:-1] + dist[1:]) / 2,
                              [dist[-1] + (dist[-1] - dist[-2]) / 2 if len(dist) > 1 else dist[-1] + 250]))
        step = times[1] - times[0] if len(times) > 1 else 30
        tt = np.concatenate(([times[0] - step / 2], (times[:-1] + times[1:]) / 2, [times[-1] + step / 2]))
        pc = ax.pcolormesh(tt, dd, spd_kmh, cmap=cmap, vmin=0, vmax=120, shading="flat")
        if args.bottleneck_dist is not None:
            ax.axhline(args.bottleneck_dist, color="black", ls="--", lw=1.2)
            ax.text(times[-1] * 0.99, args.bottleneck_dist + 60, "bottleneck", ha="right", va="bottom", fontsize=8)
        ax.set_title(label, fontsize=11)
        ax.set_xlabel("Simulation time (s)")
    axes[0].set_ylabel("Distance along corridor (m)")
    cbar = fig.colorbar(pc, ax=axes, fraction=0.035, pad=0.02)
    cbar.set_label("Mean speed (km/h)")
    fig.suptitle("Time-space speed contour from E2 detectors — low speed (red) = congestion; "
                 "backward tilt = upstream-propagating shockwave", fontsize=12)
    fig.savefig(args.out, dpi=130, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
