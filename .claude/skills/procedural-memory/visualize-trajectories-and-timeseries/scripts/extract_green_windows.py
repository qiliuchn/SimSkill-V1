"""
Run a short TraCI session and record, for one or more traffic lights, the time
intervals during which a specific controlled-link index shows green (G/g).

Writes JSON: {tls_id: [[start, end], ...]}.

Usage:
    python extract_green_windows.py --net net.net.xml --routes routes.rou.xml \
        --additional signals.add.xml --tls A0,B0,C0,D0,E0 --link-index 10 \
        --horizon 700 --out green_windows.json

Finding the right --link-index for a movement: traci.trafficlight.getControlledLinks(tls_id)
returns (incoming_lane, outgoing_lane, via_lane) tuples index-aligned with the RYG state
string (see implement-maxpressure-traci-controller's phase-mapping technique for the same
lookup) -- find the index whose incoming lane matches the movement you want to track, rather
than guessing. On a network built uniformly (e.g. the same grid/corridor pattern repeated at
every junction), the same movement typically lands at the same link index at every junction,
but verify this per network rather than assuming.
"""

import argparse
import json
import os
import sys

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Extract green/red time windows for a movement at one or more traffic lights via TraCI.")
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--additional", help="Additional file(s), comma-separated (e.g. the signal plan to use)")
    p.add_argument("--tls", required=True, help="Comma-separated traffic-light ids to track")
    p.add_argument("--link-index", type=int, required=True, help="Controlled-link index within each TLS's RYG state string for the movement to track")
    p.add_argument("--horizon", type=float, default=700.0, help="Seconds to simulate (default: 700 -- a few cycles is usually enough for a static program)")
    p.add_argument("--out", default="green_windows.json")
    return p.parse_args()


def main():
    args = parse_args()
    tls_ids = args.tls.split(",")

    cmd = ["sumo", "-n", args.net, "-r", args.routes, "--begin", "0", "--no-step-log", "true"]
    if args.additional:
        cmd += ["-a", args.additional]
    traci.start(cmd)

    green = {t: [] for t in tls_ids}
    prev = {t: False for t in tls_ids}
    start = {t: None for t in tls_ids}
    step = 0.0
    while step < args.horizon:
        traci.simulationStep()
        step = traci.simulation.getTime()
        for t in tls_ids:
            state = traci.trafficlight.getRedYellowGreenState(t)
            is_green = state[args.link_index] in ("G", "g")
            if is_green and not prev[t]:
                start[t] = step
            elif not is_green and prev[t]:
                green[t].append([start[t], step])
            prev[t] = is_green
    for t in tls_ids:
        if prev[t] and start[t] is not None:
            green[t].append([start[t], step])
    traci.close()

    with open(args.out, "w") as f:
        json.dump(green, f)
    for t in tls_ids:
        print(t, "green windows (first 3):", green[t][:3])
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
