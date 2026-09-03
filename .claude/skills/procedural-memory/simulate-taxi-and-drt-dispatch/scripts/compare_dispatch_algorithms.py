"""
Compare two (or more) taxi/DRT dispatch-algorithm runs (e.g. solo "greedy" vs.
pooling "greedyShared") produced by run_taxi_scenario.py.

Parses personinfo <ride> legs from each run's tripinfo.xml for wait/in-vehicle
ride time/detour-ratio metrics, folds in each run's occupancy_summary.json for
fleet mileage/pooling numbers, and writes a comparison table (CSV + markdown).

Usage:
    python compare_dispatch_algorithms.py \
        --net net.xml --persons persons.rou.xml \
        --run solo=out/solo --run pool=out/pool \
        --out-dir analysis/
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare taxi dispatch-algorithm runs.")
    p.add_argument("--net", required=True)
    p.add_argument("--persons", required=True, help="The shared persons.rou.xml all runs used (for direct O-D distance / detour ratio)")
    p.add_argument("--run", action="append", required=True, help="label=outdir, repeatable (outdir must contain tripinfo.xml + occupancy_summary.json from run_taxi_scenario.py)")
    p.add_argument("--out-dir", default="analysis")
    return p.parse_args()


def pct(vals, p):
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def mean(vals):
    return sum(vals) / len(vals) if vals else float("nan")


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib  # noqa: E402

    net = sumolib.net.readNet(args.net)
    od = {}
    for person in ET.parse(args.persons).getroot().findall("person"):
        ride = person.find("ride")
        od[person.get("id")] = (ride.get("from"), ride.get("to"))

    direct_cache = {}

    def direct_dist(o, d):
        if (o, d) not in direct_cache:
            path, _ = net.getShortestPath(net.getEdge(o), net.getEdge(d))
            direct_cache[(o, d)] = sum(e.getLength() for e in path) if path else float("nan")
        return direct_cache[(o, d)]

    def n_shared(outdir):
        try:
            root = ET.parse(os.path.join(outdir, "dispatch.xml")).getroot()
            elems = root.findall("dispatchShared") if root.tag == "DispatchInfo" else root.findall(".//dispatchShared")
            return len(elems), sum(1 for e in elems if e.get("type") == "2")
        except Exception:
            return 0, 0

    def analyze_run(label, outdir):
        tri = ET.parse(os.path.join(outdir, "tripinfo.xml")).getroot()
        waits, ride_times, detours, ride_len = [], [], [], []
        served = 0
        for pi in tri.findall("personinfo"):
            rides = pi.findall("ride")
            if not rides:
                continue
            r = rides[0]
            arr = r.get("arrival")
            if arr is None or float(arr) < 0:
                continue
            served += 1
            w, dur, rl = float(r.get("waitingTime")), float(r.get("duration")), float(r.get("routeLength"))
            waits.append(w); ride_times.append(dur); ride_len.append(rl)
            o, d = od[pi.get("id")]
            dd = direct_dist(o, d)
            if dd and dd > 0:
                detours.append(rl / dd)

        occ = json.load(open(os.path.join(outdir, "occupancy_summary.json")))
        shared_n, shared_type2 = n_shared(outdir)
        total_persons = len(od)
        return {
            "label": label, "requests": total_persons, "served": served,
            "unserved_or_timedout": total_persons - served,
            "mean_wait_s": mean(waits), "p90_wait_s": pct(waits, 90),
            "mean_ride_time_s": mean(ride_times), "mean_detour_ratio": mean(detours),
            "mean_ride_len_m": mean(ride_len),
            "fleet_total_km": occ["fleet_total_km"], "fleet_empty_km": occ["fleet_empty_km"],
            "empty_mileage_frac": occ["empty_mileage_frac"],
            "taxis_that_pooled": occ["taxis_that_pooled"], "max_fleet_occupancy": occ["max_fleet_occupancy"],
            "total_pooled_taxi_seconds": occ["total_pooled_seconds"], "sim_end_s": occ["end_time_s"],
            "shared_dispatches": shared_n, "shared_dispatches_type2": shared_type2,
        }

    rows = []
    for spec in args.run:
        label, outdir = spec.split("=", 1)
        rows.append(analyze_run(label, outdir))

    metrics = [
        ("Ride requests", "requests", "{:.0f}"),
        ("Served", "served", "{:.0f}"),
        ("Unserved / timed-out", "unserved_or_timedout", "{:.0f}"),
        ("Mean wait (reservation->pickup) [s]", "mean_wait_s", "{:.1f}"),
        ("90th-pct wait [s]", "p90_wait_s", "{:.1f}"),
        ("Mean in-vehicle ride time [s]", "mean_ride_time_s", "{:.1f}"),
        ("Mean detour ratio (ride/direct dist)", "mean_detour_ratio", "{:.3f}"),
        ("Mean ride length [m]", "mean_ride_len_m", "{:.1f}"),
        ("Fleet total veh-km", "fleet_total_km", "{:.2f}"),
        ("Fleet empty veh-km", "fleet_empty_km", "{:.2f}"),
        ("Empty-mileage fraction", "empty_mileage_frac", "{:.3f}"),
        ("Taxis that pooled (occ>=2)", "taxis_that_pooled", "{:.0f}"),
        ("Max fleet occupancy", "max_fleet_occupancy", "{:.0f}"),
        ("Total pooled taxi-seconds", "total_pooled_taxi_seconds", "{:.0f}"),
        ("Shared-dispatch assignments (log)", "shared_dispatches", "{:.0f}"),
        ("  ...of which type=2 (both aboard)", "shared_dispatches_type2", "{:.0f}"),
        ("Sim end time [s]", "sim_end_s", "{:.0f}"),
    ]

    lines = ["| Metric | " + " | ".join(r["label"] for r in rows) + " |", "|---|" + "|".join("---" for _ in rows) + "|"]
    for name, key, fmt in metrics:
        cells = [fmt.format(r[key]) if isinstance(r[key], (int, float)) else str(r[key]) for r in rows]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    table_md = "\n".join(lines)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "comparison_table.md"), "w") as f:
        f.write(table_md + "\n")
    with open(os.path.join(args.out_dir, "comparison_table.csv"), "w") as f:
        f.write("metric," + ",".join(r["label"] for r in rows) + "\n")
        for name, key, fmt in metrics:
            f.write(name.replace(",", ";") + "," + ",".join(str(r[key]) for r in rows) + "\n")
    with open(os.path.join(args.out_dir, "metrics.json"), "w") as f:
        json.dump({r["label"]: r for r in rows}, f, indent=2)

    print(table_md)


if __name__ == "__main__":
    main()
