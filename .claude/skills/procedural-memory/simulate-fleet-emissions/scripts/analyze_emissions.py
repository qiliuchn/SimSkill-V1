"""
Post-process SUMO emission outputs for a heterogeneous-fleet study.

Usage:
    python analyze_emissions.py --tripinfo tripinfo.xml --edge-emissions edge_emissions.xml \
        --net-file grid.net.xml --out-dir analysis/

Inputs:
    --tripinfo <FILE>          tripinfo.xml with a per-vehicle <emissions> child on each
                               <tripinfo>, present when the run used --device.emissions.probability 1
                               (or another nonzero probability/assignment). Mass units are mg
                               (CO2/CO/HC/NOx/PMx and fuel), routeLength is in meters.
    --edge-emissions <FILE>    the edgeData meandata file produced by an <edgeData type="emissions">
                               additional file — per-edge aggregated <edge ... CO2_abs=... .../>.
    --net-file <FILE>          the .net.xml used for the run, for edge geometry (hotspot plot).
    --out-dir <DIR>            where to write emission_summary.csv, edge_co2_ranking.csv, and the
                               two plots (created if missing).

Outputs (in --out-dir):
    emission_summary.csv   - per-vehicle-type totals (g), fleet-wide pollutant share (%), and
                              per-vehicle-km rate (mg/vkm), for CO2/NOx/PMx/fuel
    edge_co2_ranking.csv    - every edge's total CO2 (g), sorted descending
    emissions_by_type.png   - grouped bar chart, each pollutant split by vType (bars labeled
                              with each type's share of that pollutant's network total)
    co2_hotspot.png         - edge geometry colored+width-scaled by per-edge CO2 total, with the
                              top-5 edges annotated

Prints the same tables to stdout. Requires matplotlib (pip3 install matplotlib --break-system-packages
if missing, same as analyze-simulation-outputs).
"""

import argparse
import csv
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

POLLUTANTS = ["CO2_abs", "NOx_abs", "PMx_abs", "fuel_abs"]
NICE = {"CO2_abs": "CO2", "NOx_abs": "NOx", "PMx_abs": "PMx", "fuel_abs": "fuel"}


def parse_args():
    p = argparse.ArgumentParser(description="Analyze SUMO emission outputs by vehicle type and by edge.")
    p.add_argument("--tripinfo", required=True, help="tripinfo.xml with per-vehicle <emissions> children")
    p.add_argument("--edge-emissions", required=True, help="edgeData meandata file (type=\"emissions\")")
    p.add_argument("--net-file", required=True, help="the .net.xml used for the run (edge geometry)")
    p.add_argument("--out-dir", default="analysis", help="output directory (default: analysis/)")
    p.add_argument("--top-n", type=int, default=5, help="number of top CO2 edges to annotate on the hotspot plot (default: 5)")
    return p.parse_args()


def mg_to_g(x):
    return x / 1000.0


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    import matplotlib.colors as mcolors
    import numpy as np

    # 1. Per-vehicle-type totals from tripinfo
    type_totals = defaultdict(lambda: defaultdict(float))  # vType -> pollutant -> mg
    type_count = defaultdict(int)
    type_km = defaultdict(float)
    net_totals = defaultdict(float)
    total_veh = 0
    total_km = 0.0

    for _, elem in ET.iterparse(args.tripinfo, events=("end",)):
        if elem.tag == "tripinfo":
            vt = elem.get("vType")
            rlen_km = float(elem.get("routeLength", 0.0)) / 1000.0
            em = elem.find("emissions")
            type_count[vt] += 1
            type_km[vt] += rlen_km
            total_veh += 1
            total_km += rlen_km
            if em is not None:
                for p in POLLUTANTS:
                    v = float(em.get(p, 0.0))
                    type_totals[vt][p] += v
                    net_totals[p] += v
            elem.clear()

    if total_veh == 0:
        raise SystemExit(f"No <tripinfo> elements found in {args.tripinfo} — did the run actually produce vehicles?")

    types = sorted(type_count, key=lambda t: -type_totals[t]["CO2_abs"])

    print("=" * 78)
    print(f"NETWORK-WIDE EMISSION TOTALS ({total_veh} arrived vehicles, {total_km:.1f} veh-km)")
    print("=" * 78)
    for p in POLLUTANTS:
        tot_g = mg_to_g(net_totals[p])
        rate = net_totals[p] / total_km if total_km else 0.0
        unit = "g fuel" if p == "fuel_abs" else "g"
        print(f"  {NICE[p]:<6} total = {tot_g:12.1f} {unit:<7}   |  {rate:10.2f} mg/veh-km")

    print()
    print("=" * 78)
    print("BREAKDOWN BY VEHICLE TYPE")
    print("=" * 78)
    rows = []
    for t in types:
        n = type_count[t]
        fleetpct = 100.0 * n / total_veh
        row = {"vType": t, "n": n, "fleet_pct": fleetpct, "veh_km": type_km[t]}
        line = f"{t:<12} {n:6d} {fleetpct:6.1f}%"
        for p in POLLUTANTS:
            g = mg_to_g(type_totals[t][p])
            shr = 100.0 * type_totals[t][p] / net_totals[p] if net_totals[p] else 0.0
            rate = type_totals[t][p] / type_km[t] if type_km[t] else 0.0
            line += f" | {g:8.1f}g {shr:4.1f}% {rate:8.2f}mg/vkm"
            row[f"{NICE[p]}_g"] = g
            row[f"{NICE[p]}_share_pct"] = shr
            row[f"{NICE[p]}_mg_per_vkm"] = rate
        print(line)
        rows.append(row)

    with open(os.path.join(args.out_dir, "emission_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # 2. Plot: emissions per pollutant split by vehicle type
    fig, axes = plt.subplots(1, len(POLLUTANTS), figsize=(15, 5))
    for ax, p in zip(axes, POLLUTANTS):
        vals = [mg_to_g(type_totals[t][p]) for t in types]
        bars = ax.bar(range(len(types)), vals)
        ax.set_title(f"{NICE[p]} total by vType")
        ax.set_xticks(range(len(types)))
        ax.set_xticklabels(types, rotation=40, ha="right", fontsize=8)
        ax.set_ylabel("grams")
        for b, t in zip(bars, types):
            shr = 100.0 * type_totals[t][p] / net_totals[p] if net_totals[p] else 0
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{shr:.0f}%", ha="center", va="bottom", fontsize=8)
    fig.suptitle("Total emissions per pollutant, split by vehicle type (bar label = fleet-wide share)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(os.path.join(args.out_dir, "emissions_by_type.png"), dpi=110)
    plt.close(fig)

    # 3. Per-edge CO2 hotspot map from edge_emissions + net geometry
    edge_co2 = {}
    for _, elem in ET.iterparse(args.edge_emissions, events=("end",)):
        if elem.tag == "edge":
            edge_co2[elem.get("id")] = float(elem.get("CO2_abs", 0.0))
            elem.clear()

    net = ET.parse(args.net_file).getroot()
    edge_shapes = {}
    for edge in net.findall("edge"):
        if edge.get("function") == "internal":
            continue
        lane = edge.find("lane")
        if lane is None:
            continue
        shape = lane.get("shape")
        pts = [tuple(map(float, c.split(","))) for c in shape.split()]
        edge_shapes[edge.get("id")] = pts

    ranking = sorted(edge_co2.items(), key=lambda kv: -kv[1])
    with open(os.path.join(args.out_dir, "edge_co2_ranking.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["edge", "CO2_g"])
        for eid, v in ranking:
            w.writerow([eid, v / 1000.0])

    segments, vals = [], []
    for eid, pts in edge_shapes.items():
        co2 = edge_co2.get(eid, 0.0)
        for a, b in zip(pts[:-1], pts[1:]):
            segments.append([a, b])
            vals.append(co2 / 1000.0)

    fig, ax = plt.subplots(figsize=(9, 8))
    if vals:
        vmax = max(vals) or 1.0
        norm = mcolors.Normalize(vmin=0, vmax=vmax)
        cmap = matplotlib.colormaps["inferno"]
        widths = [1.5 + 6.0 * (v / vmax) for v in vals]
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidths=widths)
        lc.set_array(np.array(vals))
        ax.add_collection(lc)
        cb = fig.colorbar(lc, ax=ax)
        cb.set_label("per-edge CO2 total (g)")
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_title("Per-edge CO2 emission hotspots\nwidth & color = CO2 total")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    for eid, v in ranking[: args.top_n]:
        pts = edge_shapes.get(eid)
        if pts:
            mx = sum(x for x, y in pts) / len(pts)
            my = sum(y for x, y in pts) / len(pts)
            ax.annotate(eid, (mx, my), fontsize=7, color="cyan")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "co2_hotspot.png"), dpi=110)
    plt.close(fig)

    print()
    print("=" * 78)
    print(f"TOP {args.top_n} CO2 HOTSPOT EDGES (g CO2 over the run)")
    print("=" * 78)
    for eid, v in ranking[: args.top_n]:
        print(f"  {eid:<8}  {v / 1000.0:10.1f} g")

    print()
    print(f"Saved: {args.out_dir}/emissions_by_type.png, {args.out_dir}/co2_hotspot.png")
    print(f"Saved: {args.out_dir}/emission_summary.csv, {args.out_dir}/edge_co2_ranking.csv")


if __name__ == "__main__":
    main()
