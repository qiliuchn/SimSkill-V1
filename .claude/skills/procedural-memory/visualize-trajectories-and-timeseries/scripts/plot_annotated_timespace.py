"""
Custom time-space (distance vs. time) diagram with traffic-signal state overlaid, built
directly from FCD output and TraCI-extracted green windows (see extract_green_windows.py).

Only works directly for a STRAIGHT corridor where a vehicle's FCD x-coordinate (or y, if the
corridor runs north-south) equals its distance along the corridor -- for a general/curved
route, derive a proper along-route distance instead (e.g. from SUMO's own lane position /
odometer, or by projecting onto the route) before plotting.

Usage:
    python plot_annotated_timespace.py --fcd fcd.xml --green-windows green_windows.json \
        --intersections "A0=200,B0=600,C0=1000,D0=1400,E0=1800" \
        --vehicle-prefix main_ --tmin 100 --tmax 600 --ymax 2000 \
        --title "Coordinated (green wave)" --out timespace_coord.png
"""

import argparse
import json
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def parse_args():
    p = argparse.ArgumentParser(description="Plot a time-space diagram with signal state overlaid, from FCD output.")
    p.add_argument("--fcd", required=True, help="FCD output XML (--fcd-output)")
    p.add_argument("--green-windows", required=True, help="JSON from extract_green_windows.py: {tls_id: [[start,end],...]}")
    p.add_argument("--intersections", required=True, help='Comma-separated "id=distance" pairs, e.g. "A0=200,B0=600"')
    p.add_argument("--vehicle-prefix", default="", help="Only plot vehicles whose id starts with this prefix (e.g. to isolate mainline traffic)")
    p.add_argument("--tmin", type=float, required=True)
    p.add_argument("--tmax", type=float, required=True)
    p.add_argument("--ymax", type=float, required=True, help="Max distance along corridor to show (m)")
    p.add_argument("--title", default="")
    p.add_argument("--out", required=True)
    return p.parse_args()


def main():
    args = parse_args()
    intersections = {}
    for pair in args.intersections.split(","):
        tid, dist = pair.split("=")
        intersections[tid] = float(dist)

    green = json.load(open(args.green_windows))

    traj = {}
    for ts in ET.parse(args.fcd).getroot().iter("timestep"):
        t = float(ts.get("time"))
        if t < args.tmin - 2 or t > args.tmax + 2:
            continue
        for v in ts.iter("vehicle"):
            vid = v.get("id")
            if args.vehicle_prefix and not vid.startswith(args.vehicle_prefix):
                continue
            traj.setdefault(vid, []).append((t, float(v.get("x"))))

    fig, ax = plt.subplots(figsize=(13, 7))
    barw = 7  # line width for signal bars
    for tid, xi in intersections.items():
        gw = [w for w in green.get(tid, []) if w[1] >= args.tmin and w[0] <= args.tmax]
        ax.add_line(Line2D([args.tmin, args.tmax], [xi, xi], color="#d62728", lw=barw, alpha=0.35, zorder=1, solid_capstyle="butt"))
        for a, b in gw:
            ax.add_line(Line2D([max(a, args.tmin), min(b, args.tmax)], [xi, xi], color="#2ca02c", lw=barw, alpha=0.85, zorder=2, solid_capstyle="butt"))
        ax.text(args.tmin - (args.tmax - args.tmin) * 0.012, xi, tid, va="center", ha="right", fontsize=11, weight="bold")

    for vid, pts in traj.items():
        pts.sort()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, color="#1f77b4", lw=0.8, alpha=0.5, zorder=3)

    ax.set_xlim(args.tmin, args.tmax)
    ax.set_ylim(0, args.ymax)
    ax.set_xlabel("Simulation time (s)", fontsize=12)
    ax.set_ylabel("Distance along corridor (m)", fontsize=12)
    ax.set_title(args.title, fontsize=13)
    legend = [
        Line2D([0], [0], color="#2ca02c", lw=barw, alpha=0.85, label="signal GREEN"),
        Line2D([0], [0], color="#d62728", lw=barw, alpha=0.35, label="signal RED"),
        Line2D([0], [0], color="#1f77b4", lw=1.2, label="vehicle trajectory"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=10)
    ax.grid(axis="y", ls=":", alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.out, dpi=130)
    print(f"Saved: {args.out} with {len(traj)} trajectories")


if __name__ == "__main__":
    main()
