"""
Calibrate OD demand against traffic counts via routeSampler.py.

Usage:
    python route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml
    python route_sampler.py -r pool.rou.xml -d edge_counts.xml -t turn_counts.xml \
        -o calibrated.rou.xml --mismatch-output mismatch.xml -i 3600 --optimize full
    python route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml \
        --geh-ok 5 --seed 42 --attributes 'departSpeed="max" departLane="best"'
    python route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml \
        --extra "--min-count 2" --extra "--threads 4"

routeSampler.py lives at $SUMO_HOME/tools/routeSampler.py — SUMO_HOME must be set.
"""

import argparse
import os
import subprocess
import sys


def find_route_sampler() -> str:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo "
            "(routeSampler.py lives at $SUMO_HOME/tools/)."
        )
    candidate = os.path.join(sumo_home, "tools", "routeSampler.py")
    if not os.path.isfile(candidate):
        sys.exit(f"Could not find {candidate}. Check your SUMO_HOME install.")
    return candidate


def parse_args():
    p = argparse.ArgumentParser(description="Calibrate OD demand to match traffic counts via routeSampler.py.")

    p.add_argument("-r", "--route-files", required=True, help="Input candidate route pool (comma-separated), e.g. from randomTrips.py + duarouter")
    p.add_argument("-d", "--edgedata-files", help="Input edgeData-format file(s) with target edge counts, comma-separated")
    p.add_argument("-t", "--turn-files", help="Input turn-count file(s), comma-separated")
    p.add_argument("-o", "--output-file", default="calibrated.rou.xml", help="Output calibrated route file (default: calibrated.rou.xml)")
    p.add_argument("--mismatch-output", help="Write per-location overflow/underflow + GEH info to this file")

    p.add_argument("-b", "--begin", help="Custom begin time (seconds or H:M:S)")
    p.add_argument("-e", "--end", help="Custom end time (seconds or H:M:S)")
    p.add_argument("-i", "--interval", help="Aggregation interval (seconds or H:M:S) — should match the counts file's own interval")

    p.add_argument("--optimize", help="Optimization method level: 'full' for an exact LP-based fit (needs the PuLP/HiGHS solver), or an INT boundary for greedy sampling with local refinement")
    p.add_argument("--geh-ok", type=float, help="GEH threshold routeSampler itself uses internally to judge a location 'good enough' (does not by itself validate the eventual simulated volumes — see the skill's Validation section)")
    p.add_argument("--min-count", type=int, help="Minimum number of counting locations a route must visit to be eligible")
    p.add_argument("--minimize-vehicles", type=float, help="Optimization factor in [0,1) for preferring routes that pass multiple counting locations")
    p.add_argument("--total-count", help="Target total vehicle count (single value split proportionally, or a list per interval)")

    p.add_argument("-s", "--seed", type=int, help="Random seed")
    p.add_argument("--weighted", action="store_true", help="Sample routes according to their probability/count instead of uniformly")
    p.add_argument("-a", "--attributes", help='Extra XML attributes injected into every output vehicle, e.g. \'departSpeed="max" departLane="best"\'')
    p.add_argument("--prefix", help="Prefix for output vehicle ids")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw routeSampler.py argument(s), can be repeated, e.g. --extra '--threads 4'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(route_sampler_path: str, args: argparse.Namespace) -> list:
    cmd = [sys.executable, route_sampler_path, "-r", args.route_files, "-o", args.output_file]

    if args.edgedata_files:
        cmd += ["-d", args.edgedata_files]
    if args.turn_files:
        cmd += ["-t", args.turn_files]
    if args.mismatch_output:
        cmd += ["--mismatch-output", args.mismatch_output]

    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]
    if args.interval is not None:
        cmd += ["-i", str(args.interval)]

    if args.optimize is not None:
        cmd += ["--optimize", str(args.optimize)]
    if args.geh_ok is not None:
        cmd += ["--geh-ok", str(args.geh_ok)]
    if args.min_count is not None:
        cmd += ["--min-count", str(args.min_count)]
    if args.minimize_vehicles is not None:
        cmd += ["--minimize-vehicles", str(args.minimize_vehicles)]
    if args.total_count is not None:
        cmd += ["--total-count", str(args.total_count)]

    if args.seed is not None:
        cmd += ["-s", str(args.seed)]
    if args.weighted:
        cmd += ["--weighted"]
    if args.attributes:
        cmd += ["-a", args.attributes]
    if args.prefix:
        cmd += ["--prefix", args.prefix]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    route_sampler_path = "routeSampler.py" if args.dry_run else find_route_sampler()
    cmd = build_command(route_sampler_path, args)

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
