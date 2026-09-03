"""
Build a simple SUMO TAZ (traffic assignment zone) file from a JSON
zone -> edges mapping, for use as od2trips' -n/--taz-files input.

Usage:
    python make_taz_file.py --zones zones.json -o taz.xml

zones.json:
{
  "Z1": ["edge1", "edge2", "edge3"],
  "Z2": ["edge4", "edge5"]
}

Produces the undifferentiated <taz id="..." edges="..."/> format, where
every listed edge is usable as both a source and a sink with equal
probability. For weighted/differentiated source vs. sink edges, write
the TAZ XML by hand (see SKILL.md) — not covered by this script.
"""

import argparse
import json
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Build a simple TAZ file from a zone->edges JSON mapping.")
    p.add_argument("--zones", required=True, help="JSON file mapping zone id -> list of edge ids")
    p.add_argument("-o", "--output", default="taz.xml", help="Output TAZ file path (default: taz.xml)")
    return p.parse_args()


def build_taz_xml(zones: dict) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<tazs>"]
    for zone_id, edges in zones.items():
        if not edges:
            print(f"Warning: zone '{zone_id}' has no edges, skipping.", file=sys.stderr)
            continue
        edge_list = " ".join(edges)
        lines.append(f'    <taz id="{zone_id}" edges="{edge_list}"/>')
    lines.append("</tazs>")
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    with open(args.zones) as f:
        zones = json.load(f)

    if not zones:
        sys.exit("Zones file is empty.")

    xml = build_taz_xml(zones)
    with open(args.output, "w") as f:
        f.write(xml)

    print(f"TAZ file written to {args.output} ({len(zones)} zone(s))")


if __name__ == "__main__":
    main()
