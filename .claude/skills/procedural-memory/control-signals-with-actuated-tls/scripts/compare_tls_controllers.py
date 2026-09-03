"""
Compare SUMO traffic-light controller types (e.g. static vs actuated vs delay_based) across one
or more demand levels, using tripinfo/summary output already produced by run-simulation.

Usage:
    python compare_tls_controllers.py \
        --run fixed:low=runs/low_fixed/tripinfo.xml,runs/low_fixed/summary.xml \
        --run actuated:low=runs/low_actuated/tripinfo.xml,runs/low_actuated/summary.xml \
        --run delay_based:low=runs/low_delay/tripinfo.xml,runs/low_delay/summary.xml \
        --baseline fixed --out-dir comparison/

Each --run is "<controller>:<demand-level>=<tripinfo>,<summary>[,<edgedata>]" and can be repeated
for any number of controllers x demand levels (not just 3x3). Reuses the same metric extraction
as analyze-simulation-outputs (mean/total travel time, mean waiting time, mean time loss, mean
speed, throughput, total teleports), then adds a %-vs-baseline column computed per demand level
against whichever --baseline controller name you specify.

This is deliberately a separate script from analyze-simulation-outputs' scripts/analyze_outputs.py
rather than an extension of it: that script's %-change column is defined for exactly 2 runs, and
generalizing it to an arbitrary controller x demand-level grid (with a chosen baseline column
rather than a fixed left/right pair) is a different enough shape of comparison to keep separate.
"""

import argparse
import csv
import os
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Compare TLS controller types across demand levels.")
    p.add_argument(
        "--run",
        action="append",
        required=True,
        dest="runs",
        help='"<controller>:<demand-level>=<tripinfo>,<summary>[,<edgedata>]", repeatable',
    )
    p.add_argument("--baseline", required=True, help="Controller name to compute %% change against (e.g. fixed)")
    p.add_argument("--out-dir", default="comparison", help="Output directory (default: comparison/)")
    return p.parse_args()


def parse_tripinfo(path):
    durations, waits, losses, speeds = [], [], [], []
    n = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "tripinfo":
            n += 1
            dur = float(elem.get("duration"))
            rlen = float(elem.get("routeLength"))
            durations.append(dur)
            waits.append(float(elem.get("waitingTime")))
            losses.append(float(elem.get("timeLoss")))
            speeds.append(rlen / dur if dur else 0.0)
            elem.clear()
    if n == 0:
        raise SystemExit(f"No <tripinfo> elements in {path} — did this run produce any completed trips?")
    return {
        "throughput": n,
        "mean_travel_time_s": sum(durations) / n,
        "mean_waiting_time_s": sum(waits) / n,
        "mean_time_loss_s": sum(losses) / n,
        "mean_speed_mps": sum(speeds) / n,
    }


def parse_summary_teleports(path):
    # summary.xml's "teleports" attribute is a CUMULATIVE running count, not a
    # per-step delta -- take the last step's value, don't sum across steps
    # (summing would wildly over-count; verified against raw output).
    total = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "step":
            total = int(float(elem.get("teleports", 0)))
            elem.clear()
    return total


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    data = {}  # (controller, level) -> metrics dict
    levels_order, controllers_order = [], []
    for spec in args.runs:
        key, _, files = spec.partition("=")
        controller, _, level = key.partition(":")
        parts = files.split(",")
        tripinfo, summary = parts[0], parts[1]
        metrics = parse_tripinfo(tripinfo)
        metrics["total_teleports"] = parse_summary_teleports(summary)
        data[(controller, level)] = metrics
        if level not in levels_order:
            levels_order.append(level)
        if controller not in controllers_order:
            controllers_order.append(controller)

    if args.baseline not in controllers_order:
        raise SystemExit(f"--baseline {args.baseline!r} not found among controllers: {controllers_order}")

    metric_keys = ["mean_travel_time_s", "mean_waiting_time_s", "mean_time_loss_s", "mean_speed_mps", "throughput", "total_teleports"]
    higher_is_better = {"throughput", "mean_speed_mps"}

    rows = []
    for level in levels_order:
        base = data.get((args.baseline, level))
        for controller in controllers_order:
            m = data.get((controller, level))
            if m is None:
                continue
            row = {"demand_level": level, "controller": controller}
            for k in metric_keys:
                row[k] = m[k]
                if base and base[k]:
                    pct = 100.0 * (m[k] - base[k]) / base[k]
                    row[f"{k}_pct_vs_{args.baseline}"] = pct
                else:
                    row[f"{k}_pct_vs_{args.baseline}"] = 0.0
            rows.append(row)

    fieldnames = ["demand_level", "controller"] + metric_keys + [f"{k}_pct_vs_{args.baseline}" for k in metric_keys]
    out_csv = os.path.join(args.out_dir, "comparison_table.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"{'level':<10} {'controller':<14} " + " ".join(f"{k:>22}" for k in metric_keys))
    for r in rows:
        print(f"{r['demand_level']:<10} {r['controller']:<14} " + " ".join(f"{r[k]:22.2f}" for k in metric_keys))
    print(f"\nSaved: {out_csv}")


if __name__ == "__main__":
    main()
