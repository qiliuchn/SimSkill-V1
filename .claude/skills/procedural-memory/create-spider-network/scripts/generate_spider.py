"""
Generate a SUMO spider (radial) network via netgenerate.

Usage:
    python generate_spider.py -o spider.net.xml
    python generate_spider.py -o spider.net.xml --arm-number 10 --circle-number 3 --space-radius 150
    python generate_spider.py -o spider.net.xml --omit-center --tls-guess
    python generate_spider.py -o spider.net.xml --extra "--seed 42" --extra "--no-turnarounds"

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
    p = argparse.ArgumentParser(description="Generate a SUMO spider network via netgenerate.")
    p.add_argument("-o", "--output", default="spider.net.xml", help="Output .net.xml path")

    p.add_argument("--arm-number", type=int, help="Number of radiating arms/spokes (default: 7)")
    p.add_argument("--circle-number", type=int, help="Number of concentric circles (default: 5)")
    p.add_argument("--space-radius", type=float, help="Radial distance between circles (default: 100)")
    p.add_argument("--omit-center", action="store_true", help="Omit the central junction")
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
    cmd = [netgenerate_bin, "--spider", "-o", args.output]

    if args.arm_number is not None:
        cmd += ["--spider.arm-number", str(args.arm_number)]
    if args.circle_number is not None:
        cmd += ["--spider.circle-number", str(args.circle_number)]
    if args.space_radius is not None:
        cmd += ["--spider.space-radius", str(args.space_radius)]
    if args.omit_center:
        cmd += ["--spider.omit-center", "true"]
    if args.attach_length is not None:
        cmd += ["--spider.attach-length", str(args.attach_length)]

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
