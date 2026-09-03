"""
Optimize traffic-light cycle lengths and green splits via Webster's
equation using SUMO's tlsCycleAdaptation.py.

Usage:
    python optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml
    python optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml -b 3600
    python optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --existing-cycle
    python optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --unified-cycle
    python optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --skip cluster_12_34,tls_5

IMPORTANT: -r/--route-files must be a routed file (<vehicle> with <route>
children), not a raw trips/flows file — see SKILL.md.

tlsCycleAdaptation.py lives at $SUMO_HOME/tools/tlsCycleAdaptation.py —
SUMO_HOME must be set.
"""

import argparse
import os
import subprocess
import sys


def find_tls_cycle_adaptation() -> str:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo "
            "(tlsCycleAdaptation.py lives at $SUMO_HOME/tools/)."
        )
    candidate = os.path.join(sumo_home, "tools", "tlsCycleAdaptation.py")
    if not os.path.isfile(candidate):
        sys.exit(f"Could not find {candidate}. Check your SUMO_HOME install.")
    return candidate


def parse_args():
    p = argparse.ArgumentParser(description="Optimize TLS cycle length/green splits via tlsCycleAdaptation.py.")

    p.add_argument("-n", "--net-file", required=True, help="Input .net.xml")
    p.add_argument("-r", "--route-files", required=True, help="Routed demand file(s) (<vehicle>+<route>), comma-separated")
    p.add_argument("-o", "--output-file", default="tlsAdaptation.add.xml", help="Output additional file (default: tlsAdaptation.add.xml)")

    p.add_argument("-b", "--begin", type=float, help="Start of the 1-hour demand window (default: first vehicle's departure time)")

    p.add_argument("-y", "--yellow-time", type=int, help="Yellow phase duration, s (default: 4)")
    p.add_argument("-a", "--all-red", type=int, help="All-red time per cycle, s (default: 0)")
    p.add_argument("-l", "--lost-time", type=int, help="Start-up/clearance lost time per phase, s (default: 4)")
    p.add_argument("-g", "--min-green", type=int, help="Minimum green time for a phase with no traffic (default: 4)")
    p.add_argument("--green-filter-time", type=int, help="Ignore phases with green time below this when computing critical flows (default: 0)")

    p.add_argument("--min-cycle", type=int, help="Minimum cycle length, s (default: 20)")
    p.add_argument("--max-cycle", type=int, help="Maximum cycle length, s (default: 120)")

    p.add_argument("-e", "--existing-cycle", action="store_true", help="Keep each intersection's current cycle length; only re-split green times")
    p.add_argument("-u", "--unified-cycle", action="store_true", help="Use the largest computed cycle length for every intersection")
    p.add_argument("-R", "--restrict-cyclelength", action="store_true", help="Hard-cap the cycle at --max-cycle")

    p.add_argument("-H", "--saturation-headway", type=float, help="Seconds/vehicle used to derive lane capacity (default: 2)")
    p.add_argument("-p", "--program", help="Program id assigned to the new tlLogic (default: 'a')")
    p.add_argument("--skip", help="Comma-separated tls ids to leave untouched")

    p.add_argument("--write-critical-flows", action="store_true", help="Print the critical flow ratio per phase per intersection")
    p.add_argument("--sorted", action="store_true", help="Assume the route file is departure-time-sorted")
    p.add_argument("-v", "--verbose", action="store_true", help="Print progress and intermediate values")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw tlsCycleAdaptation.py argument(s), can be repeated",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(script_path: str, args: argparse.Namespace) -> list:
    cmd = [
        sys.executable, script_path,
        "-n", args.net_file,
        "-r", args.route_files,
        "-o", args.output_file,
    ]

    if args.begin is not None:
        cmd += ["-b", str(args.begin)]
    if args.yellow_time is not None:
        cmd += ["-y", str(args.yellow_time)]
    if args.all_red is not None:
        cmd += ["-a", str(args.all_red)]
    if args.lost_time is not None:
        cmd += ["-l", str(args.lost_time)]
    if args.min_green is not None:
        cmd += ["-g", str(args.min_green)]
    if args.green_filter_time is not None:
        cmd += ["--green-filter-time", str(args.green_filter_time)]
    if args.min_cycle is not None:
        cmd += ["--min-cycle", str(args.min_cycle)]
    if args.max_cycle is not None:
        cmd += ["--max-cycle", str(args.max_cycle)]

    if args.existing_cycle:
        cmd += ["-e"]
    if args.unified_cycle:
        cmd += ["-u"]
    if args.restrict_cyclelength:
        cmd += ["-R"]

    if args.saturation_headway is not None:
        cmd += ["-H", str(args.saturation_headway)]
    if args.program:
        cmd += ["-p", args.program]
    if args.skip:
        cmd += ["--skip", args.skip]

    if args.write_critical_flows:
        cmd += ["--write-critical-flows"]
    if args.sorted:
        cmd += ["--sorted"]
    if args.verbose:
        cmd += ["-v"]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    script_path = "tlsCycleAdaptation.py" if args.dry_run else find_tls_cycle_adaptation()
    cmd = build_command(script_path, args)

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
