"""
Coordinate traffic-light offsets across a network via SUMO's
tlsCoordinator.py, so vehicles following common routes hit consecutive
green lights ("green wave") instead of stopping at each intersection.

Usage:
    python coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml
    python coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml -a cycles.add.xml
    python coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --ignore-priority
    python coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --speed-factor 0.9
    python coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --evaluate --verbose

IMPORTANT: -r/--route-file takes exactly ONE file (unlike the plural
-r/--route-files in the sibling tlsCycleAdaptation skill). It must be a
routed file (<route> elements with resolved edges) — see SKILL.md.

tlsCoordinator.py lives at $SUMO_HOME/tools/tlsCoordinator.py —
SUMO_HOME must be set.
"""

import argparse
import os
import subprocess
import sys


def find_tls_coordinator() -> str:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo "
            "(tlsCoordinator.py lives at $SUMO_HOME/tools/)."
        )
    candidate = os.path.join(sumo_home, "tools", "tlsCoordinator.py")
    if not os.path.isfile(candidate):
        sys.exit(f"Could not find {candidate}. Check your SUMO_HOME install.")
    return candidate


def parse_args():
    p = argparse.ArgumentParser(description="Coordinate TLS offsets via tlsCoordinator.py.")

    p.add_argument("-n", "--net-file", required=True, help="Input .net.xml")
    p.add_argument("-r", "--route-file", required=True, help="Routed demand file (single file, <route> elements with edges)")
    p.add_argument("-o", "--output-file", default="tlsOffsets.add.xml", help="Output additional file (default: tlsOffsets.add.xml)")
    p.add_argument("-a", "--additional-file", help="Replacement tlLogic programs to coordinate instead of the network's own (e.g. tlsCycleAdaptation.py output)")

    p.add_argument("-i", "--ignore-priority", action="store_true", help="Ignore road priority when sorting which TLS pairs get coordinated first")
    p.add_argument("--speed-factor", type=float, help="Assumed avg vehicle speed as a fraction of the speed limit (default: 0.8)")
    p.add_argument("-e", "--evaluate", action="store_true", help="After writing offsets, run sumo with the result and print duration statistics")
    p.add_argument("-v", "--verbose", action="store_true", help="Print pairing/merging decisions as they're made")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw tlsCoordinator.py argument(s), can be repeated",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the command without running it")
    return p.parse_args()


def build_command(script_path: str, args: argparse.Namespace) -> list:
    cmd = [
        sys.executable, script_path,
        "-n", args.net_file,
        "-r", args.route_file,
        "-o", args.output_file,
    ]

    if args.additional_file:
        cmd += ["-a", args.additional_file]
    if args.ignore_priority:
        cmd += ["-i"]
    if args.speed_factor is not None:
        cmd += ["--speed-factor", str(args.speed_factor)]
    if args.evaluate:
        cmd += ["-e"]
    if args.verbose:
        cmd += ["-v"]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    script_path = "tlsCoordinator.py" if args.dry_run else find_tls_coordinator()
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
