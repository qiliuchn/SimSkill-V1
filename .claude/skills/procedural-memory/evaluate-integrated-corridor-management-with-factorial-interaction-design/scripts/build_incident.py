#!/usr/bin/env python3
"""Build the incident rerouter additional-file: closingLaneReroute blocking
`--lanes-blocked` of the 3 EB lanes on the incident edge (fwy_eb_9, x=4000-4500,
between interchange 2 and interchange 3) for [begin, begin+duration]. A real
physical lane closure (vClass disallow), not merely a rerouting hint -- see
simulate-incident-rerouting."""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--begin", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--lanes-blocked", type=int, default=2, choices=[1, 2])
    ap.add_argument("--incident-edge", default="fwy_eb_9")
    args = ap.parse_args()

    end = args.begin + args.duration
    lane_lines = "\n".join(
        f'        <closingLaneReroute id="{args.incident_edge}_{i}" disallow="all"/>'
        for i in range(args.lanes_blocked)
    )
    xml = f"""<additional>
    <rerouter id="incident_rerouter" edges="{args.incident_edge}">
        <interval begin="{args.begin}" end="{end}">
{lane_lines}
        </interval>
    </rerouter>
</additional>
"""
    with open(args.out, "w") as f:
        f.write(xml)
    print("wrote", args.out, f"blocking {args.lanes_blocked} lane(s) of {args.incident_edge} "
          f"[{args.begin},{end}]")


if __name__ == "__main__":
    main()
