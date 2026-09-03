"""
Generate a busStop additional-file and scheduled bus-line vehicles for one or more PT corridors.

Usage:
    python generate_pt_lines.py --line "ew:A2B2,B2C2,C2D2,D2E2" --line "ns:C0C1,C1C2,C2C3,C3C4" \
        --out-dir pt/ --headway 300 --horizon 3600 --dwell 20 --stop-start 50 --stop-end 70

Each --line is "<line-id>:<edge1>,<edge2>,...,<edgeN>" — one busStop is placed per edge, on that
edge's driving lane. Writes <out-dir>/busstops.add.xml and <out-dir>/pt_vehicles.rou.xml.

Why explicit vehicles instead of a <flow>: SUMO's intermodal person router (duarouter routing
--persontrips demand, or the runtime intermodal router) only treats a line as "usable" for
walk-vs-ride mode choice when its stops carry an absolute `until=` arrival timetable — a bare
`duration=` dwell on a <flow>-generated stop is not a schedule. This script always emits one
concrete <vehicle> per departure with per-stop `until` times, not a <flow>, specifically to
satisfy that requirement. See the `public-transport-and-intermodal-routing` knowledge page for
the full explanation.

Assumes a sidewalk lane already exists at index _0 (e.g. from netconvert --sidewalks.guess) and
the driving lane is index _1 — adjust --driving-lane-index / --sidewalk-lane-index if the
network's lane layout differs (e.g. multi-lane edges, or sidewalks added a different way).
"""

import argparse
import os


def parse_args():
    p = argparse.ArgumentParser(description="Generate busStops + scheduled PT vehicles for one or more corridors.")
    p.add_argument(
        "--line",
        action="append",
        required=True,
        dest="lines",
        help='One PT line as "<line-id>:<edge1>,<edge2>,...". Can be repeated for multiple lines.',
    )
    p.add_argument("--out-dir", default=".", help="Directory to write busstops.add.xml and pt_vehicles.rou.xml into")
    p.add_argument("--headway", type=float, default=300.0, help="Seconds between departures on each line (default: 300)")
    p.add_argument("--horizon", type=float, default=3600.0, help="Simulated seconds to schedule departures over (default: 3600)")
    p.add_argument("--dwell", type=float, default=20.0, help="Seconds each bus dwells at a stop (default: 20)")
    p.add_argument("--stop-start", type=float, default=50.0, help="Stop's startPos on its lane, in meters (default: 50)")
    p.add_argument("--stop-end", type=float, default=70.0, help="Stop's endPos on its lane, in meters (default: 70)")
    p.add_argument("--inter-stop-time", type=float, default=38.0, help="Assumed travel time (s) between consecutive stops, for building the `until` schedule (default: 38)")
    p.add_argument("--driving-lane-index", type=int, default=1, help="Lane index for the driving lane a busStop sits on (default: 1)")
    p.add_argument("--sidewalk-lane-index", type=int, default=0, help="Lane index for the sidewalk a busStop's <access> connects to (default: 0)")
    p.add_argument("--person-capacity", type=int, default=40, help="personCapacity for the bus vType (default: 40)")
    p.add_argument("--vehicle-length", type=float, default=12.0, help="Bus vType length in meters (default: 12)")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    lines = []
    for spec in args.lines:
        line_id, _, edge_str = spec.partition(":")
        edges = edge_str.split(",")
        lines.append((line_id, edges))

    stop_mid = (args.stop_start + args.stop_end) / 2.0

    busstops_path = os.path.join(args.out_dir, "busstops.add.xml")
    with open(busstops_path, "w") as f:
        f.write("<additional>\n")
        for line_id, edges in lines:
            for i, edge in enumerate(edges, 1):
                sid = f"{line_id}_{i}"
                driving_lane = f"{edge}_{args.driving_lane_index}"
                sidewalk_lane = f"{edge}_{args.sidewalk_lane_index}"
                f.write(
                    f'    <busStop id="{sid}" lane="{driving_lane}" startPos="{args.stop_start}" '
                    f'endPos="{args.stop_end}" lines="{line_id}" friendlyPos="true">\n'
                )
                f.write(f'        <access lane="{sidewalk_lane}" pos="{stop_mid}"/>\n')
                f.write("    </busStop>\n")
        f.write("</additional>\n")

    vehicles_path = os.path.join(args.out_dir, "pt_vehicles.rou.xml")
    with open(vehicles_path, "w") as f:
        f.write("<routes>\n")
        f.write(
            f'    <vType id="bus" vClass="bus" length="{args.vehicle_length}" '
            f'personCapacity="{args.person_capacity}" color="1,0.5,0"/>\n\n'
        )
        for line_id, edges in lines:
            depart = 0.0
            idx = 0
            while depart < args.horizon:
                vid = f"bus_{line_id}_{idx}"
                f.write(f'    <vehicle id="{vid}" type="bus" line="{line_id}" depart="{depart:g}" departPos="free">\n')
                f.write(f'        <route edges="{" ".join(edges)}"/>\n')
                for i in range(1, len(edges) + 1):
                    sid = f"{line_id}_{i}"
                    until = depart + (i - 1) * args.inter_stop_time + args.dwell
                    f.write(f'        <stop busStop="{sid}" duration="{args.dwell:g}" until="{until:g}"/>\n')
                f.write("    </vehicle>\n")
                depart += args.headway
                idx += 1
            f.write("\n")
        f.write("</routes>\n")

    print(f"Wrote {busstops_path} and {vehicles_path}")
    for line_id, edges in lines:
        n_departures = int(args.horizon // args.headway) + 1
        print(f"  line {line_id}: {len(edges)} stops, ~{n_departures} scheduled buses over {args.horizon:g}s")


if __name__ == "__main__":
    main()
