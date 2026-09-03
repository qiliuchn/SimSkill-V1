"""
Generate random trips/routes for a SUMO network via randomTrips.py.

Usage:
    python random_trips.py -n net.xml -o trips.trips.xml
    python random_trips.py -n net.xml -o trips.trips.xml --period 18
    python random_trips.py -n net.xml --route-file routes.rou.xml
    python random_trips.py -n net.xml -o trips.trips.xml --fringe-factor 10
    python random_trips.py -n net.xml -o peds.trips.xml --pedestrians --max-distance 2000
    python random_trips.py -n net.xml -o trips.trips.xml --extra "--intermediate 2"

randomTrips.py lives at $SUMO_HOME/tools/randomTrips.py — SUMO_HOME must be set.
"""

import argparse
import os
import subprocess
import sys


def find_random_trips() -> str:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo "
            "(randomTrips.py lives at $SUMO_HOME/tools/)."
        )
    candidate = os.path.join(sumo_home, "tools", "randomTrips.py")
    if not os.path.isfile(candidate):
        sys.exit(f"Could not find {candidate}. Check your SUMO_HOME install.")
    return candidate


def parse_args():
    p = argparse.ArgumentParser(description="Generate random trips/routes via randomTrips.py.")

    p.add_argument("-n", "--net-file", required=True, help="Input .net.xml")
    p.add_argument("-o", "--output", default="trips.trips.xml", help="Output trips file (ignored if --route-file given)")
    p.add_argument("-b", "--begin", type=float, help="Start time in seconds (default: 0)")
    p.add_argument("-e", "--end", type=float, help="End time in seconds (default: 3600)")

    volume = p.add_mutually_exclusive_group()
    volume.add_argument("--period", help="Seconds between departures (comma/space list for sub-intervals)")
    volume.add_argument("--insertion-rate", help="Vehicles/hour")
    volume.add_argument("--insertion-density", help="Vehicles/hour/km of road")

    p.add_argument("--seed", type=int, help="Reproducible random seed")
    p.add_argument("--random", action="store_true", help="Use true (non-reproducible) randomness")
    p.add_argument("--prefix", help="Id prefix for generated trips")

    p.add_argument("--fringe-factor", help="Relative probability boost for fringe edges, or 'max'")
    p.add_argument("--min-distance", type=float, help="Minimum straight-line start->end distance (m)")
    p.add_argument("--max-distance", type=float, help="Maximum straight-line start->end distance (m)")
    p.add_argument("--intermediate", type=int, help="Number of via-waypoints per trip")

    p.add_argument("--vehicle-class", help="e.g. passenger, bus, truck")
    p.add_argument("--pedestrians", action="store_true", help="Generate pedestrians instead of vehicles")
    p.add_argument("--persontrips", action="store_true", help="Generate persontrips (mode-choice)")

    p.add_argument("--route-file", help="Output validated .rou.xml via duarouter (instead of raw trips)")
    p.add_argument("--validate", action="store_true", help="With --route-file, also emit validated trips")

    p.add_argument("--trip-attributes", help='Raw XML attributes added to every trip, e.g. \'departLane="best"\'')
    p.add_argument("--weights-prefix", help="Load custom edge src/dst/via probabilities from <prefix>.{src,dst,via}.xml")
    p.add_argument("--weights-output-prefix", help="Save the edge probabilities actually used")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw randomTrips.py argument(s), can be repeated, e.g. --extra '--angle-factor 2'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(random_trips_path: str, args: argparse.Namespace) -> list:
    cmd = [sys.executable, random_trips_path, "-n", args.net_file]

    if args.route_file:
        cmd += ["--route-file", args.route_file]
    else:
        cmd += ["-o", args.output]

    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]

    if args.period is not None:
        cmd += ["--period", args.period]
    if args.insertion_rate is not None:
        cmd += ["--insertion-rate", args.insertion_rate]
    if args.insertion_density is not None:
        cmd += ["--insertion-density", args.insertion_density]

    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    if args.random:
        cmd += ["--random"]
    if args.prefix:
        cmd += ["--prefix", args.prefix]

    if args.fringe_factor is not None:
        cmd += ["--fringe-factor", args.fringe_factor]
    if args.min_distance is not None:
        cmd += ["--min-distance", str(args.min_distance)]
    if args.max_distance is not None:
        cmd += ["--max-distance", str(args.max_distance)]
    if args.intermediate is not None:
        cmd += ["--intermediate", str(args.intermediate)]

    if args.vehicle_class:
        cmd += ["--vehicle-class", args.vehicle_class]
    if args.pedestrians:
        cmd += ["--pedestrians"]
    if args.persontrips:
        cmd += ["--persontrips"]

    if args.validate:
        cmd += ["--validate"]

    if args.trip_attributes:
        cmd += ["--trip-attributes", args.trip_attributes]
    if args.weights_prefix:
        cmd += ["--weights-prefix", args.weights_prefix]
    if args.weights_output_prefix:
        cmd += ["--weights-output-prefix", args.weights_output_prefix]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    random_trips_path = "randomTrips.py" if args.dry_run else find_random_trips()
    cmd = build_command(random_trips_path, args)

    print("Running:", " ".join(cmd))
    if args.dry_run:
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    out = args.route_file or args.output
    print(f"Output written to {out}")


if __name__ == "__main__":
    main()
