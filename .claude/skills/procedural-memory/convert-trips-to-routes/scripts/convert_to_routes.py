"""
Convert a SUMO trips file into a routes file via duarouter.

Usage:
    python convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml
    python convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml --ignore-errors --repair
    python convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml -b 0 -e 3600
    python convert_to_routes.py -n net.xml -r trips.trips.xml -o checked.trips.xml --write-trips
    python convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml --extra "--routing-algorithm astar"

duarouter ships next to `sumo`/`sumo-gui`/`netconvert`/`netgenerate` but is
not always on $PATH (common on macOS framework installs). Resolution
order: $PATH, the directory containing `sumo`, then $SUMO_HOME/bin.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_duarouter() -> str:
    found = shutil.which("duarouter")
    if found:
        return found

    sumo_path = shutil.which("sumo")
    if sumo_path:
        candidate = os.path.join(os.path.dirname(sumo_path), "duarouter")
        if os.path.isfile(candidate):
            return candidate

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = os.path.join(sumo_home, "bin", "duarouter")
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        "Could not locate duarouter. Checked $PATH, the directory of the "
        "`sumo` binary, and $SUMO_HOME/bin. Pass its full path directly or "
        "add it to PATH."
    )


def parse_args():
    p = argparse.ArgumentParser(description="Convert a SUMO trips file to routes via duarouter.")

    p.add_argument("-n", "--net-file", required=True, help="Input .net.xml")
    p.add_argument("-r", "--route-files", required=True, help="Input trips/routes/flows file(s), comma-separated")
    p.add_argument("-o", "--output-file", default="routes.rou.xml", help="Output .rou.xml (default: routes.rou.xml)")
    p.add_argument("-a", "--additional-files", help="Extra network data (districts/TAZ, bus stops), comma-separated")

    p.add_argument("-b", "--begin", type=float, help="Discard trips departing before this time (s)")
    p.add_argument("-e", "--end", type=float, help="Discard trips departing after this time (s)")

    p.add_argument("--ignore-errors", action="store_true", help="Continue instead of aborting when a route can't be built")
    p.add_argument("--repair", action="store_true", help="Try to fix an invalid route by patching around the gap")
    p.add_argument("--repair-from", action="store_true", help="Fix an invalid start edge by using the first usable edge")
    p.add_argument("--repair-to", action="store_true", help="Fix an invalid destination edge by using the last usable edge")
    p.add_argument("--remove-loops", action="store_true", help="Strip loops and start/end turnarounds")

    p.add_argument(
        "--routing-algorithm",
        choices=["dijkstra", "astar", "CH", "CHWrapper"],
        help="Routing algorithm (default: dijkstra)",
    )
    p.add_argument("--weight-files", help="Edge-weight file(s) to route against instead of static net speeds")
    p.add_argument("--scale", type=float, help="Scale demand by this factor")

    p.add_argument("--seed", type=int, help="Reproducible random seed")
    p.add_argument("--random", action="store_true", help="Use true (non-reproducible) randomness")

    p.add_argument("--write-trips", action="store_true", help="Write back out as trips (validated) instead of routes")
    p.add_argument("--max-alternatives", type=int, help="Number of route alternatives kept per vehicle (default: 5)")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw duarouter argument(s), can be repeated, e.g. --extra '--scale 1.5'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(duarouter_bin: str, args: argparse.Namespace) -> list:
    cmd = [
        duarouter_bin,
        "-n", args.net_file,
        "-r", args.route_files,
        "-o", args.output_file,
    ]

    if args.additional_files:
        cmd += ["-a", args.additional_files]
    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]

    if args.ignore_errors:
        cmd += ["--ignore-errors"]
    if args.repair:
        cmd += ["--repair"]
    if args.repair_from:
        cmd += ["--repair.from"]
    if args.repair_to:
        cmd += ["--repair.to"]
    if args.remove_loops:
        cmd += ["--remove-loops"]

    if args.routing_algorithm:
        cmd += ["--routing-algorithm", args.routing_algorithm]
    if args.weight_files:
        cmd += ["--weight-files", args.weight_files]
    if args.scale is not None:
        cmd += ["--scale", str(args.scale)]

    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    if args.random:
        cmd += ["--random"]

    if args.write_trips:
        cmd += ["--write-trips"]
    if args.max_alternatives is not None:
        cmd += ["--max-alternatives", str(args.max_alternatives)]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    duarouter_bin = "duarouter" if args.dry_run else find_duarouter()
    cmd = build_command(duarouter_bin, args)

    print("Running:", " ".join(cmd))
    if args.dry_run:
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    print(f"Output written to {args.output_file}")


if __name__ == "__main__":
    main()
