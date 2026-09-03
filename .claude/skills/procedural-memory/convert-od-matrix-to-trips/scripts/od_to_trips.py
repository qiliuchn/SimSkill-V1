"""
Convert an O/D matrix into a SUMO trips file via od2trips.

Usage:
    python od_to_trips.py -n taz.xml -d matrix.od -o trips.trips.xml
    python od_to_trips.py -n taz.xml -d am.od,pm.od -o trips.trips.xml --scale 1.2
    python od_to_trips.py -n taz.xml -d matrix.od -o trips.trips.xml --spread-uniform
    python od_to_trips.py -n taz.xml -z relations.xml -o trips.trips.xml
    python od_to_trips.py -n taz.xml -d truck_matrix.od -o truck_trips.trips.xml --vtype truck --prefix truck_

od2trips ships next to `sumo`/`sumo-gui`/`netconvert`/`netgenerate`/`duarouter`
but is not always on $PATH (common on macOS framework installs). Resolution
order: $PATH, the directory containing `sumo`, then $SUMO_HOME/bin.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_od2trips() -> str:
    found = shutil.which("od2trips")
    if found:
        return found

    sumo_path = shutil.which("sumo")
    if sumo_path:
        candidate = os.path.join(os.path.dirname(sumo_path), "od2trips")
        if os.path.isfile(candidate):
            return candidate

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = os.path.join(sumo_home, "bin", "od2trips")
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        "Could not locate od2trips. Checked $PATH, the directory of the "
        "`sumo` binary, and $SUMO_HOME/bin. Pass its full path directly or "
        "add it to PATH."
    )


def parse_args():
    p = argparse.ArgumentParser(description="Convert an O/D matrix to a SUMO trips file via od2trips.")

    p.add_argument("-n", "--taz-files", required=True, help="TAZ/district file(s), comma-separated")

    matrix = p.add_mutually_exclusive_group(required=True)
    matrix.add_argument("-d", "--od-matrix-files", help="O/V-format matrix file(s), comma-separated")
    matrix.add_argument("-z", "--tazrelation-files", help="tazRelation-format (XML) matrix file(s), comma-separated")
    matrix.add_argument("--od-amitran-files", help="Amitran-format (XML) matrix file(s), comma-separated")

    p.add_argument("-o", "--output-file", default="trips.trips.xml", help="Output .trips.xml (default: trips.trips.xml)")
    p.add_argument("-b", "--begin", type=float, help="Discard trips departing before this time (s) (default: 0)")
    p.add_argument("-e", "--end", type=float, help="Discard trips departing after this time (s) (default: 86400)")

    p.add_argument("--scale", type=float, help="Multiply all matrix counts by this factor")
    p.add_argument("--spread-uniform", action="store_true", help="Space departures evenly instead of randomly within each period")
    p.add_argument("--different-source-sink", action="store_true", help="Never pick identical source and sink edge")

    p.add_argument("--vtype", help="Vehicle type name attached to every trip")
    p.add_argument("--prefix", help="Id prefix, needed when combining multiple od2trips calls")

    p.add_argument("--pedestrians", action="store_true", help="Generate pedestrians instead of vehicles")
    p.add_argument("--persontrips", action="store_true", help="Generate persontrips instead of vehicles")

    p.add_argument("--seed", type=int, help="Reproducible random seed")
    p.add_argument("--random", action="store_true", help="Use true (non-reproducible) randomness")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw od2trips argument(s), can be repeated, e.g. --extra '--timeline.day-in-hours'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(od2trips_bin: str, args: argparse.Namespace) -> list:
    cmd = [od2trips_bin, "-n", args.taz_files, "-o", args.output_file]

    if args.od_matrix_files:
        cmd += ["-d", args.od_matrix_files]
    elif args.tazrelation_files:
        cmd += ["-z", args.tazrelation_files]
    else:
        cmd += ["--od-amitran-files", args.od_amitran_files]

    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]

    if args.scale is not None:
        cmd += ["--scale", str(args.scale)]
    if args.spread_uniform:
        cmd += ["--spread.uniform"]
    if args.different_source_sink:
        cmd += ["--different-source-sink"]

    if args.vtype:
        cmd += ["--vtype", args.vtype]
    if args.prefix:
        cmd += ["--prefix", args.prefix]

    if args.pedestrians:
        cmd += ["--pedestrians"]
    if args.persontrips:
        cmd += ["--persontrips"]

    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    if args.random:
        cmd += ["--random"]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    od2trips_bin = "od2trips" if args.dry_run else find_od2trips()
    cmd = build_command(od2trips_bin, args)

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
