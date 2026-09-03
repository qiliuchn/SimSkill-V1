"""
Cross-check a congestion heatmap against raw edgeData: rank every edge, per
interval, by the attributes plot_net_dump.py colored the map with, and confirm
the visually-worst edge is genuinely the expected bottleneck -- don't just
eyeball the PNG.

Usage:
    python verify_hotspot.py --edgedata edgedata_congestion.out.xml --expected-bottleneck CD
"""

import argparse
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Cross-check a congestion heatmap's implied hotspot against raw edgeData values.")
    p.add_argument("--edgedata", required=True)
    p.add_argument("--expected-bottleneck", required=True, help="Edge id expected to be the true bottleneck (e.g. the lane-drop edge)")
    p.add_argument("--attributes", default="speed,speedRelative,occupancy,density", help="Comma-separated edgeData attributes to rank by")
    return p.parse_args()


def main():
    args = parse_args()
    attrs = args.attributes.split(",")
    root = ET.parse(args.edgedata).getroot()

    for iv in root.findall("interval"):
        b, e = iv.get("begin"), iv.get("end")
        rows = {}
        for ed in iv.findall("edge"):
            vals = {}
            for a in attrs:
                v = ed.get(a)
                vals[a] = float(v) if v is not None else float("nan")
            rows[ed.get("id")] = vals
        if not rows:
            continue

        print(f"\n=== interval {b}-{e} ===")
        if "speed" in attrs:
            slow = min(rows, key=lambda k: rows[k]["speed"])
            print(f"  slowest edge (speed)      : {slow}  ({rows[slow]['speed']:.2f} m/s)")
        if "occupancy" in attrs:
            hi_occ = max(rows, key=lambda k: rows[k]["occupancy"])
            print(f"  highest occupancy edge    : {hi_occ}  ({rows[hi_occ]['occupancy']:.2f} %)")
            match = hi_occ == args.expected_bottleneck
            print(f"  expected bottleneck '{args.expected_bottleneck}' flagged by occupancy? {match}")
        if "density" in attrs:
            hi_den = max(rows, key=lambda k: rows[k]["density"])
            print(f"  highest density edge      : {hi_den}  ({rows[hi_den]['density']:.2f} veh/km)")
            if hi_den != args.expected_bottleneck:
                print(f"  NOTE: density flags '{hi_den}', not the expected bottleneck -- density is "
                      f"per-edge, not per-lane, and can mis-rank a wider feeder above a narrower bottleneck. "
                      f"Prefer occupancy or speedRelative to localize a lane-count-change bottleneck.")
        if "speed" in attrs:
            order = sorted(rows, key=lambda k: rows[k]["speed"])
            print("  edges slow->fast          :", " < ".join(f"{k}({rows[k]['speed']:.1f})" for k in order))


if __name__ == "__main__":
    main()
