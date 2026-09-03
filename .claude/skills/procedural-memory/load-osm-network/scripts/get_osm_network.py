"""
Download an OpenStreetMap area and build a SUMO network from it, using
SUMO's own osmGet.py (download) and osmBuild.py (convert) tools.

Usage:
    python get_osm_network.py --bbox -122.43,37.76,-122.40,37.79 --prefix sf_downtown
    python get_osm_network.py --area 62422 --prefix some_place
    python get_osm_network.py --bbox ... --prefix mynet --vehicle-classes passenger --pedestrians
    python get_osm_network.py --bbox ... --prefix mynet --lefthand
    python get_osm_network.py --bbox ... --prefix mynet --extra-netconvert-options "--remove-edges.isolated"
    python get_osm_network.py --bbox ... --prefix mynet --dry-run

osmGet.py / osmBuild.py live in $SUMO_HOME/tools/ (not next to the sumo/
netconvert binaries) — SUMO_HOME must be set.
"""

import argparse
import os
import subprocess
import sys


def find_osm_tools():
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo "
            "(osmGet.py/osmBuild.py live at $SUMO_HOME/tools/)."
        )
    tools_dir = os.path.join(sumo_home, "tools")
    osm_get = os.path.join(tools_dir, "osmGet.py")
    osm_build = os.path.join(tools_dir, "osmBuild.py")
    missing = [p for p in (osm_get, osm_build) if not os.path.isfile(p)]
    if missing:
        sys.exit(f"Could not find: {', '.join(missing)}. Check your SUMO_HOME install.")
    return osm_get, osm_build, sumo_home


TYPEMAP_SHORTCUTS = {
    "pedestrians": "osmNetconvertPedestrians.typ.xml",
    "bicycles": "osmNetconvertBicycle.typ.xml",
    "urban_de": "osmNetconvertUrbanDe.typ.xml",
}

# osmBuild.py's own recommended cleanup defaults (its DEFAULT_NETCONVERT_OPTS) -- passing
# --netconvert-options to osmBuild.py REPLACES these entirely rather than adding to them, so
# whenever this wrapper needs to pass --netconvert-options at all (for --lefthand or
# --extra-netconvert-options), it must re-include this full set explicitly or the cleanup
# silently disappears. Verified against the installed osmBuild.py's actual source -- does NOT
# include --tls.default-type actuated, contrary to an earlier version of this script's assumption.
DEFAULT_NETCONVERT_OPTS = [
    "--geometry.remove",
    "--ramps.guess",
    "--junctions.join",
    "--tls.guess-signals",
    "--tls.discard-simple",
    "--tls.join",
    "--output.original-names",
    "--output.street-names",
]


def parse_args():
    p = argparse.ArgumentParser(description="Download + build a SUMO network from OpenStreetMap.")

    area_group = p.add_mutually_exclusive_group(required=True)
    area_group.add_argument("--bbox", help="west,south,east,north in geo coords (lon/lat)")
    area_group.add_argument("--area", help="OSM area/relation ID")
    area_group.add_argument("--polygon", help="Polygon file to compute bbox from")

    p.add_argument("--prefix", default="osm", help="Filename prefix for downloaded/generated files (default: osm)")
    p.add_argument("--tiles", type=int, help="Split a large --bbox download into INT tiles")
    p.add_argument("--output-dir", default=".", help="Directory for downloaded/generated files (default: cwd)")

    p.add_argument(
        "--vehicle-classes",
        choices=["all", "road", "passenger", "publicTransport"],
        default="all",
        help="Which OSM ways to import (default: all)",
    )

    p.add_argument("--pedestrians", action="store_true", help="Add the pedestrian typemap")
    p.add_argument("--bicycles", action="store_true", help="Add the bicycle typemap")
    p.add_argument("--urban-de", action="store_true", dest="urban_de", help="Add the urban-Germany speed typemap")
    p.add_argument("--typemap", help="Additional typemap file(s), comma-separated, appended after the default")

    p.add_argument("--lefthand", action="store_true", help="Add --lefthand for left-hand-driving regions")
    p.add_argument("--extra-netconvert-options", default="", help="Raw passthrough to osmBuild.py --netconvert-options")
    p.add_argument("--extra-polyconvert-options", default="", help="Raw passthrough to osmBuild.py --polyconvert-options")

    p.add_argument("--keep-osm-file", action="store_true", default=True, help=argparse.SUPPRESS)
    p.add_argument("--no-keep-osm-file", action="store_false", dest="keep_osm_file", help="Delete the intermediate .osm.xml after building")

    p.add_argument("--dry-run", action="store_true", help="Print commands without running them")
    return p.parse_args()


def build_typemap_list(args, sumo_home):
    typemap_dir = os.path.join(sumo_home, "data", "typemap")
    files = [os.path.join(typemap_dir, "osmNetconvert.typ.xml")]

    for flag, fname in (
        (args.pedestrians, TYPEMAP_SHORTCUTS["pedestrians"]),
        (args.bicycles, TYPEMAP_SHORTCUTS["bicycles"]),
        (args.urban_de, TYPEMAP_SHORTCUTS["urban_de"]),
    ):
        if flag:
            files.append(os.path.join(typemap_dir, fname))

    if args.typemap:
        for extra in args.typemap.split(","):
            extra = extra.strip()
            if not extra:
                continue
            # Accept a bare filename (resolved against the typemap dir) or a full path
            files.append(extra if os.path.isabs(extra) or os.path.dirname(extra) else os.path.join(typemap_dir, extra))

    return files


def run(cmd, cwd, dry_run):
    print("Running:", " ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)


def main():
    args = parse_args()
    osm_get, osm_build, sumo_home = find_osm_tools()
    os.makedirs(args.output_dir, exist_ok=True)

    # --- Stage 1: download ---
    get_cmd = [sys.executable, osm_get, "--prefix", args.prefix]
    if args.bbox:
        # NOTE: must be ONE argv token joined with "=".  osmGet.py uses argparse, and a
        # space-separated value beginning with "-" (any western-hemisphere longitude,
        # e.g. -87.6,41.8,-87.6,41.9) is read as an option string -- the commas defeat
        # argparse's negative-number heuristic.  Passing it as two tokens fails with
        # "argument -b/--bbox: expected one argument" and exits 2 at the download stage,
        # so this skill silently failed for every bbox in the Americas until 2026-08-18.
        get_cmd += ["--bbox=" + args.bbox]
    elif args.area:
        get_cmd += ["--area", args.area]
    else:
        get_cmd += ["--polygon", args.polygon]
    if args.tiles:
        get_cmd += ["--tiles", str(args.tiles)]

    run(get_cmd, cwd=args.output_dir, dry_run=args.dry_run)

    # --- Stage 2: build ---
    osm_file = f"{args.prefix}.osm.xml"
    typemap_files = build_typemap_list(args, sumo_home)

    # osmBuild.py's --netconvert-options REPLACES its own recommended defaults rather than
    # extending them, so build_cmd must always carry the full recommended set explicitly
    # (see DEFAULT_NETCONVERT_OPTS above) once we're passing --netconvert-options at all.
    netconvert_opts = list(DEFAULT_NETCONVERT_OPTS)
    if args.lefthand:
        netconvert_opts.append("--lefthand")
    if args.extra_netconvert_options:
        netconvert_opts.append(args.extra_netconvert_options)

    build_cmd = [
        sys.executable, osm_build,
        "--osm-file", osm_file,
        "--vehicle-classes", args.vehicle_classes,
        "--netconvert-typemap", ",".join(typemap_files),
        "--netconvert-options", ",".join(netconvert_opts),
    ]
    if args.extra_polyconvert_options:
        build_cmd += ["--polyconvert-options", args.extra_polyconvert_options]

    run(build_cmd, cwd=args.output_dir, dry_run=args.dry_run)

    if args.dry_run:
        return

    if not args.keep_osm_file:
        osm_path = os.path.join(args.output_dir, osm_file)
        if os.path.isfile(osm_path):
            os.remove(osm_path)

    print(f"\nDone. Contents of {args.output_dir}:")
    for f in sorted(os.listdir(args.output_dir)):
        print(" ", f)


if __name__ == "__main__":
    main()
