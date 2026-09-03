"""
Compare two SUMO runs' tripinfo output split by vType (mode), for scenarios
where a network change (e.g. a lane-permission variant) is expected to
affect different vClasses differently.

Usage:
    python compare_by_vclass.py \
        --run baseline=outputs/baseline/tripinfo.xml \
        --run variant=outputs/variant/tripinfo.xml \
        --vtypes car_passenger,bike_bicycle \
        --out-csv outputs/comparison_table.csv

Prints a per-vType (mean travel time, mean waiting time, mean time loss,
mean route length, throughput) comparison table plus network-wide totals,
with %-change from the first --run to each subsequent one, and writes the
same to CSV. All numbers are computed directly from the tripinfo XML files.
"""

import argparse
import csv
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare tripinfo runs split by vType.")
    p.add_argument("--run", action="append", required=True, help="name=path/to/tripinfo.xml, repeatable, first is the baseline for %%-change")
    p.add_argument("--vtypes", required=True, help="Comma-separated vType names to break out")
    p.add_argument("--out-csv", default="comparison_table.csv")
    return p.parse_args()


def parse_tripinfo(path, vtypes):
    by_type = {vt: [] for vt in vtypes}
    total_timeloss = total_waiting = 0.0
    n_total = 0
    for _, t in ET.iterparse(path, events=("end",)):
        if t.tag == "tripinfo":
            rec = {
                "duration": float(t.get("duration")),
                "waitingTime": float(t.get("waitingTime")),
                "timeLoss": float(t.get("timeLoss")),
                "routeLength": float(t.get("routeLength")),
            }
            vt = t.get("vType")
            if vt in by_type:
                by_type[vt].append(rec)
            total_timeloss += rec["timeLoss"]
            total_waiting += rec["waitingTime"]
            n_total += 1
            t.clear()
    return by_type, total_timeloss, total_waiting, n_total


def mean(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else float("nan")


def pct(old, new):
    return (new - old) / old * 100.0 if old else float("nan")


def main():
    args = parse_args()
    vtypes = args.vtypes.split(",")
    runs = {}
    order = []
    for spec in args.run:
        name, path = spec.split("=", 1)
        order.append(name)
        by_type, tl, tw, n = parse_tripinfo(path, vtypes)
        runs[name] = {"by_type": by_type, "total_timeLoss": tl, "total_waiting": tw, "n_total": n}

    baseline = order[0]

    metrics = []
    for vt in vtypes:
        metrics.append((f"{vt} throughput (trips)", lambda d, vt=vt: len(d["by_type"][vt])))
        metrics.append((f"{vt} mean travel time (s)", lambda d, vt=vt: mean(d["by_type"][vt], "duration")))
        metrics.append((f"{vt} mean waiting time (s)", lambda d, vt=vt: mean(d["by_type"][vt], "waitingTime")))
        metrics.append((f"{vt} mean time loss (s)", lambda d, vt=vt: mean(d["by_type"][vt], "timeLoss")))
        metrics.append((f"{vt} mean route length (m)", lambda d, vt=vt: mean(d["by_type"][vt], "routeLength")))
    metrics.append(("Total throughput (all vTypes)", lambda d: d["n_total"]))
    metrics.append(("Total network time loss (s)", lambda d: d["total_timeLoss"]))
    metrics.append(("Total network waiting time (s)", lambda d: d["total_waiting"]))

    header = ["metric"] + order + [f"pct_change_{n}_vs_{baseline}" for n in order[1:]]
    csv_rows = [header]

    col_w = 40
    print(f"{'metric':<{col_w}}" + "".join(f"{n:>16}" for n in order) + "".join(f"{'%chg_' + n:>16}" for n in order[1:]))
    for label, fn in metrics:
        vals = {n: fn(runs[n]) for n in order}
        pcts = {n: pct(vals[baseline], vals[n]) for n in order[1:]}
        line = f"{label:<{col_w}}" + "".join(f"{vals[n]:>16.2f}" for n in order)
        line += "".join(f"{pcts[n]:>+15.1f}%" for n in order[1:])
        print(line)
        csv_rows.append([label] + [f"{vals[n]:.2f}" for n in order] + [f"{pcts[n]:.1f}" for n in order[1:]])

    with open(args.out_csv, "w", newline="") as f:
        csv.writer(f).writerows(csv_rows)
    print(f"\nCSV written: {args.out_csv}")


if __name__ == "__main__":
    main()
