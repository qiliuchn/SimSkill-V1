"""
Analyze SUMO tripinfo output (with <personinfo>) for intermodal walk-vs-ride modal split.

Usage:
    python analyze_modal_split.py --tripinfo tripinfo.xml --out-dir analysis/
    python analyze_modal_split.py --tripinfo tripinfo.xml --out-dir analysis/ --line-prefix bus_

Classification: a person with at least one <ride> sub-element used public transport for at least
part of their trip; everyone else walked the whole way. Per group, reports person count, share of
total, mean travel time, mean walking distance (sum of <walk>/<access> routeLength), and mean
waiting time. Also reports per-line boardings (parsed from each <ride>'s `vehicle` id, matched
against --line-prefix + "<line-id>_") and mean bus vehicle travel time (from each bus's own
<tripinfo vType="bus">).

Requires matplotlib for the plot (pip3 install matplotlib --break-system-packages if missing).
"""

import argparse
import csv
import os
import re
import statistics as st
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Analyze intermodal walk-vs-ride modal split from SUMO tripinfo output.")
    p.add_argument("--tripinfo", required=True, help="tripinfo.xml containing <personinfo> elements")
    p.add_argument("--out-dir", default="analysis", help="Output directory (default: analysis/)")
    p.add_argument("--bus-vtype", default="bus", help="vType id used for PT vehicles, to compute mean bus travel time (default: bus)")
    p.add_argument(
        "--vehicle-id-pattern",
        default=r"^(?:bus_)?([A-Za-z0-9]+)_\d+$",
        help="Regex with one capture group extracting the line id from a ride's vehicle id "
        r'(default matches "bus_<line>_<n>" or "<line>_<n>")',
    )
    p.add_argument("--no-plot", action="store_true", help="Skip generating the PNG plot (CSV/stdout only)")
    return p.parse_args()


def mean(xs):
    return st.mean(xs) if xs else 0.0


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    root = ET.parse(args.tripinfo).getroot()
    vehicle_line_re = re.compile(args.vehicle_id_pattern)

    walk_persons, ride_persons = [], []
    line_boardings = {}

    for pi in root.findall("personinfo"):
        dur = float(pi.get("duration", 0.0))
        wait = float(pi.get("waitingTime", 0.0))
        walk_dist = sum(float(w.get("routeLength", 0)) for w in pi.findall("walk"))
        walk_dist += sum(float(a.get("routeLength", 0)) for a in pi.findall("access"))
        rides = pi.findall("ride")
        rec = {"id": pi.get("id"), "dur": dur, "wait": wait, "walk_dist": walk_dist}
        if rides:
            rec["ride_wait"] = sum(float(r.get("waitingTime", 0.0)) for r in rides)
            ride_persons.append(rec)
            for r in rides:
                m = vehicle_line_re.match(r.get("vehicle", ""))
                line = m.group(1) if m else "unknown"
                line_boardings[line] = line_boardings.get(line, 0) + 1
        else:
            walk_persons.append(rec)

    n_total = len(walk_persons) + len(ride_persons)
    if n_total == 0:
        raise SystemExit(f"No <personinfo> elements found in {args.tripinfo} — was person demand actually loaded?")

    bus_durs = [float(t.get("duration")) for t in root.findall("tripinfo") if t.get("vType") == args.bus_vtype]

    rows = []
    for name, grp in [("WALK (whole trip)", walk_persons), ("RIDE (walk+ride)", ride_persons)]:
        rows.append(
            {
                "mode": name,
                "persons": len(grp),
                "share_pct": 100.0 * len(grp) / n_total,
                "mean_travel_time_s": mean([r["dur"] for r in grp]),
                "mean_walk_dist_m": mean([r["walk_dist"] for r in grp]),
                "mean_wait_s": mean([r["wait"] for r in grp]),
                "mean_stop_wait_s": mean([r.get("ride_wait", 0) for r in grp]) if grp is ride_persons else 0.0,
            }
        )

    print(f"\n=== MODAL SPLIT (n={n_total} persons) ===")
    hdr = ["Mode", "Persons", "Share%", "MeanTravelT(s)", "MeanWalkDist(m)", "MeanWait(s)", "MeanStopWait(s)"]
    print("| " + " | ".join(hdr) + " |")
    for r in rows:
        print(
            f"| {r['mode']} | {r['persons']} | {r['share_pct']:.1f} | {r['mean_travel_time_s']:.1f} | "
            f"{r['mean_walk_dist_m']:.1f} | {r['mean_wait_s']:.1f} | {r['mean_stop_wait_s']:.1f} |"
        )

    print("\n=== PT RIDERSHIP ===")
    for line, n in sorted(line_boardings.items()):
        print(f"  line {line}: {n} boardings")
    print(f"  total boardings: {sum(line_boardings.values())}")
    print(f"  mean PT vehicle travel time: {mean(bus_durs):.1f} s (n={len(bus_durs)})")

    with open(os.path.join(args.out_dir, "modal_split.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(hdr)
        for r in rows:
            w.writerow(
                [
                    r["mode"], r["persons"], f"{r['share_pct']:.1f}", f"{r['mean_travel_time_s']:.1f}",
                    f"{r['mean_walk_dist_m']:.1f}", f"{r['mean_wait_s']:.1f}", f"{r['mean_stop_wait_s']:.1f}",
                ]
            )
        w.writerow([])
        w.writerow(["line", "boardings"])
        for line, n in sorted(line_boardings.items()):
            w.writerow([line, n])
        w.writerow(["mean_pt_vehicle_travel_time_s", f"{mean(bus_durs):.1f}"])

    if not args.no_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        modes = [r["mode"] for r in rows]
        counts = [r["persons"] for r in rows]
        tt = [r["mean_travel_time_s"] for r in rows]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
        ax1.bar(modes, counts)
        ax1.set_title("Modal split: person count per mode")
        ax1.set_ylabel("persons")
        for i, c in enumerate(counts):
            ax1.text(i, c, f"{c}\n({100*c/n_total:.0f}%)", ha="center", va="bottom")
        ax2.bar(modes, tt)
        ax2.set_title("Mean person travel time per mode")
        ax2.set_ylabel("seconds")
        for i, v in enumerate(tt):
            ax2.text(i, v, f"{v:.0f}s", ha="center", va="bottom")
        fig.suptitle(f"Intermodal scenario — walk vs ride (n={n_total} persons)")
        fig.tight_layout()
        p = os.path.join(args.out_dir, "modal_split.png")
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"\nSaved: {p}")

    print(f"Saved: {os.path.join(args.out_dir, 'modal_split.csv')}")


if __name__ == "__main__":
    main()
