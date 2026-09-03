"""
Verify, from real simulation output (not assumption), that a rail_signal
genuinely resolved a single-track meet between two opposing trains: which
train was held, where, for how long, and confirm the two trains were never
co-located on the same single-track bidirectional edge (no head-on).

Station dwell windows are read automatically from stop-output (so a train
sitting still at a scheduled station stop isn't misreported as a signal
hold) -- pass --stop-output pointing at SUMO's --stop-output file.

Single-track sections are identified by grouping edge ids into "base" names
via --edge-pairs (opposite-direction edge id pairs sharing one physical
section, e.g. a bidi pair or two parallel siding tracks): a section is
"single-track" if only one edge id maps to that base (a bidi pair with no
parallel siding), and both trains passing through it at overlapping times is
a genuine head-on hazard.

Usage:
    python verify_rail_meet.py --fcd outputs/fcd.xml --stop-output outputs/stops.xml \
        --trains train_AB,train_BA \
        --edge-pairs "SA_W=SA-W,W_SA=SA-W,E_SB=E-SB,SB_E=E-SB,main_WE=main,main_EW=main,sid_WE=sid,sid_EW=sid" \
        --single-track-bases SA-W,E-SB
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Verify a rail_signal-arbitrated single-track meet from FCD/stop-output.")
    p.add_argument("--fcd", required=True)
    p.add_argument("--stop-output", required=True)
    p.add_argument("--trains", required=True, help="Comma-separated vehicle ids of the two (or more) trains to check")
    p.add_argument("--edge-pairs", required=True, help='Comma-separated "edge_id=base_name" pairs mapping each direction of a section to a shared base name')
    p.add_argument("--single-track-bases", required=True, help="Comma-separated base names that are genuinely single-track (co-occupancy = head-on hazard)")
    p.add_argument("--halt-speed", type=float, default=0.1, help="m/s below which a train is considered stationary")
    return p.parse_args()


def load_station_windows(stop_output_path):
    windows = defaultdict(list)
    for _, el in ET.iterparse(stop_output_path, events=("end",)):
        if el.tag == "stopinfo":
            vid = el.get("id")
            started, ended = el.get("started"), el.get("ended")
            if started is not None and ended is not None:
                windows[vid].append((float(started), float(ended)))
            el.clear()
    return windows


def in_station(windows, vid, t):
    return any(a <= t <= b for a, b in windows.get(vid, []))


def load_fcd(fcd_path):
    frames = {}
    for _, elem in ET.iterparse(fcd_path, events=("end",)):
        if elem.tag == "timestep":
            t = float(elem.get("time"))
            for v in elem.findall("vehicle"):
                frames.setdefault(t, {})[v.get("id")] = (float(v.get("x")), float(v.get("speed")), v.get("lane"))
            elem.clear()
    return frames


def main():
    args = parse_args()
    trains = args.trains.split(",")
    base_of = {}
    for pair in args.edge_pairs.split(","):
        edge_id, base = pair.split("=")
        base_of[edge_id] = base
    single_track_bases = set(args.single_track_bases.split(","))

    def base(lane):
        edge = lane.rsplit("_", 1)[0]
        return base_of.get(edge, edge)

    windows = load_station_windows(args.stop_output)
    frames = load_fcd(args.fcd)
    times = sorted(frames)

    print("=== Per-train signal holds (stationary, NOT at a scheduled station stop) ===")
    for vid in trains:
        hold = [t for t in times if vid in frames[t] and frames[t][vid][1] < args.halt_speed and not in_station(windows, vid, t)]
        hold = [t for t in hold if t > 5]  # drop the initial accel-from-rest frame at simulation start
        if hold:
            # group into contiguous runs
            runs, run = [], [hold[0]]
            for t in hold[1:]:
                if t - run[-1] <= 2:
                    run.append(t)
                else:
                    runs.append(run)
                    run = [t]
            runs.append(run)
            for run in runs:
                t0, t1 = run[0], run[-1]
                x0, _, lane0 = frames[t0][vid]
                print(f"  {vid}: held t={t0:.0f}..{t1:.0f}s (~{t1 - t0:.0f}s), at x={x0:.1f} on lane {lane0} [{base(lane0)}]")
        else:
            print(f"  {vid}: no hold outside scheduled station stops")

    print("\n=== Single-track section occupancy over time ===")
    for b in sorted(single_track_bases):
        for vid in trains:
            ts = [t for t in times if vid in frames[t] and base(frames[t][vid][2]) == b]
            if ts:
                print(f"  {b}  {vid}: t={min(ts):.0f}..{max(ts):.0f}s")

    print("\n=== Head-on check: any two trains on the same single-track section at once? ===")
    head_on = []
    for t in times:
        f = frames[t]
        present = [(vid, base(f[vid][2])) for vid in trains if vid in f]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                v1, b1 = present[i]
                v2, b2 = present[j]
                if b1 == b2 and b1 in single_track_bases:
                    head_on.append((t, v1, v2, b1))
    if head_on:
        print(f"  HEAD-ON DETECTED: {head_on[:10]}")
    else:
        print("  none — no two trains ever co-located on the same single-track section")


if __name__ == "__main__":
    main()
