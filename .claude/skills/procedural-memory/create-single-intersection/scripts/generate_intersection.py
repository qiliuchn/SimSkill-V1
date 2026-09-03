"""
Generate a SUMO network with exactly one intersection (N configurable arms)
via plain-XML node/edge files compiled by netconvert.

Usage:
    python generate_intersection.py -o intersection.net.xml
    python generate_intersection.py -o intersection.net.xml --arms 4 --arm-length 250 --lanes-in 2 --lanes-out 2
    python generate_intersection.py -o t_junction.net.xml --arms 3
    python generate_intersection.py -o intersection.net.xml --config arms.json
    python generate_intersection.py -o intersection.net.xml --junction-type traffic_light --turn-lanes 1

--config expects a JSON list of per-arm dicts, e.g.:
[
  {"name": "N", "length": 300, "lanes_in": 3, "lanes_out": 3, "speed": 16.67},
  {"name": "E", "length": 150, "lanes_in": 2, "lanes_out": 2, "speed": 11.11}
]
Any field omitted from an arm falls back to the script's --arm-length/--lanes-in/
--lanes-out/--speed defaults.

netconvert ships next to `sumo`/`sumo-gui`/`netgenerate` but is not always on
$PATH (common on macOS framework installs). Resolution order: $PATH, the
directory containing `sumo`, then $SUMO_HOME/bin.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile


def find_netconvert() -> str:
    found = shutil.which("netconvert")
    if found:
        return found

    sumo_path = shutil.which("sumo")
    if sumo_path:
        candidate = os.path.join(os.path.dirname(sumo_path), "netconvert")
        if os.path.isfile(candidate):
            return candidate

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = os.path.join(sumo_home, "bin", "netconvert")
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        "Could not locate netconvert. Checked $PATH, the directory of the "
        "`sumo` binary, and $SUMO_HOME/bin. Pass its full path directly or "
        "add it to PATH."
    )


# Compass-ish default names for common arm counts, starting north, clockwise.
DEFAULT_NAMES = {
    3: ["N", "SE", "SW"],
    4: ["N", "E", "S", "W"],
}

# 0 degrees = north, clockwise. Used so a config's "name" fixes its position
# by compass meaning rather than by its position in the list.
COMPASS_ANGLES = {
    "N": 0, "NE": 45, "E": 90, "SE": 135,
    "S": 180, "SW": 225, "W": 270, "NW": 315,
}


def build_arms(args) -> list:
    if args.config:
        with open(args.config) as f:
            raw_arms = json.load(f)
        n = len(raw_arms)
        arms = []
        for i, a in enumerate(raw_arms):
            name = a.get("name", f"arm{i}")
            if "angle" in a:
                angle_deg = a["angle"]
            elif name.upper() in COMPASS_ANGLES:
                angle_deg = COMPASS_ANGLES[name.upper()]
            else:
                angle_deg = 360.0 * i / n  # even spacing fallback for non-compass names
            arms.append(
                {
                    "name": a.get("name", f"arm{i}"),
                    "length": a.get("length", args.arm_length),
                    "lanes_in": a.get("lanes_in", args.lanes_in),
                    "lanes_out": a.get("lanes_out", args.lanes_out),
                    "speed": a.get("speed", args.speed),
                    "angle_deg": angle_deg,
                }
            )
        return arms

    n = args.arms
    names = DEFAULT_NAMES.get(n, [f"arm{i}" for i in range(n)])
    arms = []
    for i in range(n):
        arms.append(
            {
                "name": names[i],
                "length": args.arm_length,
                "lanes_in": args.lanes_in,
                "lanes_out": args.lanes_out,
                "speed": args.speed,
                "angle_deg": 360.0 * i / n,
            }
        )
    return arms


def arm_position(angle_deg: float, length: float):
    # 0 degrees = north (+y), clockwise positive, matching compass convention.
    rad = math.radians(angle_deg)
    x = length * math.sin(rad)
    y = length * math.cos(rad)
    return round(x, 2), round(y, 2)


def write_node_file(path: str, arms: list, junction_type: str):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    lines.append(f'    <node id="center" x="0" y="0" type="{junction_type}"/>')
    for arm in arms:
        x, y = arm_position(arm["angle_deg"], arm["length"])
        lines.append(f'    <node id="{arm["name"]}" x="{x}" y="{y}"/>')
    lines.append("</nodes>")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_edge_file(path: str, arms: list):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for arm in arms:
        name = arm["name"]
        lines.append(
            f'    <edge id="in_{name}" from="{name}" to="center" '
            f'numLanes="{arm["lanes_in"]}" speed="{arm["speed"]}"/>'
        )
        lines.append(
            f'    <edge id="out_{name}" from="center" to="{name}" '
            f'numLanes="{arm["lanes_out"]}" speed="{arm["speed"]}"/>'
        )
    lines.append("</edges>")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def parse_args():
    p = argparse.ArgumentParser(description="Generate a single-intersection SUMO network via netconvert.")
    p.add_argument("-o", "--output", default="intersection.net.xml", help="Output .net.xml path")

    p.add_argument("--arms", type=int, default=4, help="Number of arms for a uniform intersection (ignored if --config given)")
    p.add_argument("--arm-length", type=float, default=200, help="Distance from center to each arm's fringe node (m)")
    p.add_argument("--lanes-in", type=int, default=1, help="Lanes on each incoming approach")
    p.add_argument("--lanes-out", type=int, default=1, help="Lanes on each outgoing departure")
    p.add_argument("--speed", type=float, default=13.89, help="Default speed limit in m/s (default: 13.89 ≈ 50 km/h)")

    p.add_argument("--config", help="JSON file with a list of per-arm overrides")

    p.add_argument(
        "--junction-type",
        default="traffic_light",
        help="Center junction type: traffic_light, priority, right_before_left, allway_stop (default: traffic_light)",
    )
    p.add_argument("--turn-lanes", type=int, default=0, help="Add INT dedicated left-turn lane(s), passed to netconvert")
    p.add_argument("--keep-plain", action="store_true", help="Keep the intermediate .nod.xml/.edg.xml files")
    p.add_argument("--dry-run", action="store_true", help="Print generated XML and command without running netconvert")
    return p.parse_args()


def main():
    args = parse_args()
    arms = build_arms(args)
    if len(arms) < 2:
        sys.exit("Need at least 2 arms to form an intersection.")

    workdir = os.path.dirname(os.path.abspath(args.output)) if args.keep_plain else tempfile.mkdtemp()
    os.makedirs(workdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.output))[0]
    nod_path = os.path.join(workdir, f"{base}.nod.xml")
    edg_path = os.path.join(workdir, f"{base}.edg.xml")

    write_node_file(nod_path, arms, args.junction_type)
    write_edge_file(edg_path, arms)

    if args.dry_run:
        print(f"--- {nod_path} ---")
        print(open(nod_path).read())
        print(f"--- {edg_path} ---")
        print(open(edg_path).read())

    netconvert_bin = "netconvert" if args.dry_run else find_netconvert()
    cmd = [
        netconvert_bin,
        "--node-files", nod_path,
        "--edge-files", edg_path,
        "-o", args.output,
    ]
    if args.turn_lanes:
        cmd += ["--turn-lanes", str(args.turn_lanes)]

    print("Running:", " ".join(cmd))
    if args.dry_run:
        if not args.keep_plain:
            shutil.rmtree(workdir, ignore_errors=True)
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        if not args.keep_plain:
            shutil.rmtree(workdir, ignore_errors=True)
        sys.exit(result.returncode)

    if not args.keep_plain:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"Network written to {args.output}")
    print(f"Arms: {', '.join(a['name'] for a in arms)}")


if __name__ == "__main__":
    main()
