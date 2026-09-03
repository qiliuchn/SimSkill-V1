"""
Generate a SUMO grid network via netgenerate.

Usage:
    python generate_grid.py -o grid.net.xml
    python generate_grid.py -o grid.net.xml --x-number 5 --y-number 3 --x-length 200 --y-length 150 --lanes 2
    python generate_grid.py -o grid.net.xml --tls-guess
    python generate_grid.py -o grid.net.xml --junction-type traffic_light
    python generate_grid.py -o grid.net.xml --extra "--seed 42" --extra "--no-turnarounds"

netgenerate ships next to `sumo`/`sumo-gui` but is not always on $PATH
(common on macOS framework installs). This script resolves it by checking,
in order: $PATH, the directory containing `sumo`, and $SUMO_HOME/bin.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_netgenerate() -> str:
    # 1. Already on PATH
    found = shutil.which("netgenerate")
    if found:
        return found

    # 2. Same directory as the `sumo` binary
    sumo_path = shutil.which("sumo")
    if sumo_path:
        candidate = os.path.join(os.path.dirname(sumo_path), "netgenerate")
        if os.path.isfile(candidate):
            return candidate

    # 3. $SUMO_HOME/bin
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = os.path.join(sumo_home, "bin", "netgenerate")
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        "Could not locate netgenerate. Checked $PATH, the directory of the "
        "`sumo` binary, and $SUMO_HOME/bin. Pass its full path directly or "
        "add it to PATH."
    )


def parse_args():
    p = argparse.ArgumentParser(description="Generate a SUMO grid network via netgenerate.")
    p.add_argument("-o", "--output", default="grid.net.xml", help="Output .net.xml path")

    p.add_argument("--number", type=int, help="Junctions per side (square grid); overridden by --x-number/--y-number")
    p.add_argument("--x-number", type=int, help="Junctions along x")
    p.add_argument("--y-number", type=int, help="Junctions along y")

    p.add_argument("--length", type=float, help="Street length in both directions")
    p.add_argument("--x-length", type=float, help="Street length along x")
    p.add_argument("--y-length", type=float, help="Street length along y")

    p.add_argument("--attach-length", type=float, help="Length of dangling boundary streets (0 = none)")

    p.add_argument("--lanes", type=int, default=1, help="Default lanes per edge (default: 1)")
    p.add_argument("--speed", type=float, default=13.89, help="Default speed limit in m/s (default: 13.89 ≈ 50 km/h)")
    p.add_argument(
        "--junction-type",
        default=None,
        help="e.g. traffic_light, priority, right_before_left, allway_stop",
    )
    p.add_argument("--tls-guess", action="store_true", help="Auto-assign traffic lights at appropriate junctions")
    p.add_argument("--seed", type=int, help="Random seed")

    p.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra raw netgenerate argument(s), can be repeated, e.g. --extra '--no-turnarounds'",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the netgenerate command without running it")
    return p.parse_args()


def build_command(netgenerate_bin: str, args: argparse.Namespace) -> list:
    cmd = [netgenerate_bin, "--grid", "-o", args.output]

    if args.number is not None:
        cmd += ["--grid.number", str(args.number)]
    if args.x_number is not None:
        cmd += ["--grid.x-number", str(args.x_number)]
    if args.y_number is not None:
        cmd += ["--grid.y-number", str(args.y_number)]

    if args.length is not None:
        cmd += ["--grid.length", str(args.length)]
    if args.x_length is not None:
        cmd += ["--grid.x-length", str(args.x_length)]
    if args.y_length is not None:
        cmd += ["--grid.y-length", str(args.y_length)]

    if args.attach_length is not None:
        cmd += ["--grid.attach-length", str(args.attach_length)]

    cmd += ["--default.lanenumber", str(args.lanes)]
    cmd += ["--default.speed", str(args.speed)]

    if args.junction_type:
        cmd += ["--default-junction-type", args.junction_type]
    if args.tls_guess:
        cmd += ["--tls.guess", "true"]
    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]

    for extra in args.extra:
        cmd += extra.split()

    return cmd


def main():
    args = parse_args()
    netgenerate_bin = "netgenerate" if args.dry_run else find_netgenerate()
    cmd = build_command(netgenerate_bin, args)

    print("Running:", " ".join(cmd))
    if args.dry_run:
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    print(f"Network written to {args.output}")


if __name__ == "__main__":
    main()
