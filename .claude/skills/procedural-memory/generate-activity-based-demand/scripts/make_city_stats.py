"""
Generate an activitygen <city> statistics file for a grid network built with
create-grid-network-style junction ids (letters for columns, digits for rows,
e.g. "B1C1" = the edge from junction B1 to junction C1).

Classifies grid (junction-to-junction) edges into a central CBD/work block
(both endpoint junctions inside the given column/row ranges) vs. residential
(everything else), designates a couple of residential edges as schools, and
picks fringe/attach edges (matched by --gate-prefix-regex) as city gates for
incoming/outgoing commuter traffic.

Usage:
    python make_city_stats.py \
        --net grid.net.xml --out city.stat.xml \
        --grid-id-regex '^([A-E])([0-4])([A-E])([0-4])$' \
        --cbd-cols BCD --cbd-rows 123 \
        --n-schools 2 --n-gates 6 --gate-prefix-regex '^(bottom|left|top|right)\\d' \
        --inhabitants 1000 --households 450 --car-rate 0.60 \
        --work-open "07:30:0.25,08:00:0.55,08:30:0.20" \
        --work-close "16:00:0.20,17:00:0.55,18:00:0.25" \
        --school-open 08:00 --school-close 16:00

Adjust --grid-id-regex/--cbd-cols/--cbd-rows to match the actual edge-naming
convention of the network being used; this script assumes create-grid-network's
netgenerate-style ids. See SUMO's Demand/Activity-based_Demand_Generation docs
for the full <city> schema (no XSD ships with SUMO for this file, unlike most
other SUMO XML formats -- verify field names against the docs/a working run,
not by assuming symmetry with an XSD you find elsewhere in $SUMO_HOME).
"""

import argparse
import re
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Generate an activitygen <city> statistics file for a grid network.")
    p.add_argument("--net", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--grid-id-regex", default=r"^([A-Z])(\d+)([A-Z])(\d+)$")
    p.add_argument("--cbd-cols", default="BCD", help="Column letters counted as the central/CBD block")
    p.add_argument("--cbd-rows", default="123", help="Row digits counted as the central/CBD block")
    p.add_argument("--n-schools", type=int, default=2)
    p.add_argument("--n-gates", type=int, default=6)
    p.add_argument("--gate-prefix-regex", default=r"^(bottom|left|top|right)\d")
    p.add_argument("--inhabitants", type=int, default=1000)
    p.add_argument("--households", type=int, default=450)
    p.add_argument("--children-age-limit", type=int, default=18)
    p.add_argument("--retirement-age-limit", type=int, default=65)
    p.add_argument("--car-rate", type=float, default=0.60)
    p.add_argument("--unemployment-rate", type=float, default=0.08)
    p.add_argument("--foot-distance-limit", type=float, default=250)
    p.add_argument("--incoming-traffic", type=float, default=150)
    p.add_argument("--outgoing-traffic", type=float, default=120)
    p.add_argument("--mean-time-per-km-in-city", type=float, default=360)
    p.add_argument("--free-time-activity-rate", type=float, default=0.15)
    p.add_argument("--uniform-random-traffic", type=float, default=0.10)
    p.add_argument("--departure-variation", type=float, default=600)
    p.add_argument("--work-open", default="07:30:0.25,08:00:0.55,08:30:0.20", help="Comma-separated HH:MM:proportion triples")
    p.add_argument("--work-close", default="16:00:0.20,17:00:0.55,18:00:0.25")
    p.add_argument("--school-open", default="08:00")
    p.add_argument("--school-close", default="16:00")
    p.add_argument("--residential-population", type=int, default=10)
    p.add_argument("--work-position", type=int, default=30)
    return p.parse_args()


def hhmm_to_seconds(s):
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def parse_triples(spec):
    out = []
    for part in spec.split(","):
        hh, mm, prop = part.split(":")
        out.append((hhmm_to_seconds(f"{hh}:{mm}"), float(prop)))
    return out


def main():
    args = parse_args()
    root = ET.parse(args.net).getroot()
    edges = [e.get("id") for e in root.findall("edge") if e.get("function") != "internal"]

    grid_re = re.compile(args.grid_id_regex)
    cbd_cols, cbd_rows = set(args.cbd_cols), set(args.cbd_rows)

    residential, work, fringe = [], [], []
    for eid in edges:
        m = grid_re.match(eid)
        if m:
            c1, r1, c2, r2 = m.groups()
            if c1 in cbd_cols and r1 in cbd_rows and c2 in cbd_cols and r2 in cbd_rows:
                work.append(eid)
            else:
                residential.append(eid)
        else:
            fringe.append(eid)

    schools = residential[:args.n_schools]
    gate_re = re.compile(args.gate_prefix_regex)
    gates = [e for e in fringe if gate_re.match(e)][: args.n_gates]

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<city>"]
    lines.append("    <general")
    lines.append(f'        inhabitants="{args.inhabitants}"')
    lines.append(f'        households="{args.households}"')
    lines.append(f'        childrenAgeLimit="{args.children_age_limit}"')
    lines.append(f'        retirementAgeLimit="{args.retirement_age_limit}"')
    lines.append(f'        carRate="{args.car_rate}"')
    lines.append(f'        unemploymentRate="{args.unemployment_rate}"')
    lines.append(f'        footDistanceLimit="{args.foot_distance_limit}"')
    lines.append(f'        incomingTraffic="{args.incoming_traffic}"')
    lines.append(f'        outgoingTraffic="{args.outgoing_traffic}"/>')
    lines.append("    <parameters")
    lines.append(f'        carPreference="{args.car_rate}"')
    lines.append(f'        meanTimePerKmInCity="{args.mean_time_per_km_in_city}"')
    lines.append(f'        freeTimeActivityRate="{args.free_time_activity_rate}"')
    lines.append(f'        uniformRandomTraffic="{args.uniform_random_traffic}"')
    lines.append(f'        departureVariation="{args.departure_variation}"/>')
    lines.append("    <population>")
    lines.append(f'        <bracket beginAge="0" endAge="{args.children_age_limit}" peopleNbr="{round(args.inhabitants * 0.2)}"/>')
    lines.append(f'        <bracket beginAge="{args.children_age_limit}" endAge="{args.retirement_age_limit}" peopleNbr="{round(args.inhabitants * 0.65)}"/>')
    lines.append(f'        <bracket beginAge="{args.retirement_age_limit}" endAge="90" peopleNbr="{round(args.inhabitants * 0.15)}"/>')
    lines.append("    </population>")
    lines.append("    <workHours>")
    for sec, prop in parse_triples(args.work_open):
        lines.append(f'        <opening hour="{sec}" proportion="{prop}"/>')
    for sec, prop in parse_triples(args.work_close):
        lines.append(f'        <closing hour="{sec}" proportion="{prop}"/>')
    lines.append("    </workHours>")
    lines.append("    <streets>")
    for e in residential:
        lines.append(f'        <street edge="{e}" population="{args.residential_population}" workPosition="0"/>')
    for e in work:
        lines.append(f'        <street edge="{e}" population="0" workPosition="{args.work_position}"/>')
    lines.append("    </streets>")
    lines.append("    <schools>")
    for e in schools:
        lines.append(f'        <school edge="{e}" pos="100" beginAge="6" endAge="{args.children_age_limit}" '
                     f'capacity="350" opening="{hhmm_to_seconds(args.school_open)}" closing="{hhmm_to_seconds(args.school_close)}"/>')
    lines.append("    </schools>")
    lines.append("    <cityGates>")
    for e in gates:
        lines.append(f'        <entrance edge="{e}" pos="50" incoming="0.5" outgoing="0.5"/>')
    lines.append("    </cityGates>")
    lines.append("</city>")

    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"residential edges: {len(residential)}")
    print(f"work (CBD) edges:  {len(work)} -> {work}")
    print(f"school edges:      {schools}")
    print(f"city gates:        {gates}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
