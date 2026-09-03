#!/usr/bin/env python3
"""
Build the detector additional-file for one ICM run: mainline E1 stations
(AID + v/c), east-end throughput E1, ramp E2 queue detectors, and VSL
control-zone E2 stations. All output file paths are absolute and unique to
--run-dir, per the "each run needs its own output path" gotcha.
"""
import argparse
import os

# mainline stations every 500 m from x=1000 (ic1) to x=7000 (ic4): segments 3..14
MAINLINE_SEGS = list(range(3, 15))
# VSL control zone: segments feeding the incident (7,8 = x=3000-4000, upstream of incident at seg 9)
VSL_SEGS = [7, 8]
# ramps at interchanges 1..4
RAMPS = [1, 2, 3, 4]
METERED_ON_EB = {2, 3}


def ramp_lane_ids(kind, j):
    """Return the lane id(s) making up this ramp movement's edge(s)."""
    if kind == "on_eb" and j in METERED_ON_EB:
        return [f"on_eb_{j}a_0", f"on_eb_{j}b_0"]
    return [f"{kind}_{j}_0"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rd = os.path.abspath(args.run_dir)
    os.makedirs(rd, exist_ok=True)

    lines = ["<additional>"]
    # mainline E1 stations, all 3 lanes, pos=5 (near start of each 500 m segment)
    for i in MAINLINE_SEGS:
        for lane in range(3):
            lines.append(
                f'    <inductionLoop id="e1_m{i}_{lane}" lane="fwy_eb_{i}_{lane}" pos="5" '
                f'period="30" file="{rd}/e1_mainline.xml"/>'
            )
    # east-end throughput E1 (x=8000, discharge measurement / v-over-c)
    for lane in range(3):
        lines.append(
            f'    <inductionLoop id="e1_east_{lane}" lane="fwy_eb_16_{lane}" pos="400" '
            f'period="30" file="{rd}/e1_east.xml"/>'
        )
    # ramp E2 queue detectors (full-length, for spillback / queue-length audit).
    # Metered on-ramps are split into two edges (storage "a" + release "b");
    # one E2 per sub-edge so the storage segment's queue is visible on its own.
    for j in RAMPS:
        for kind in ("off_eb", "on_eb", "off_wb", "on_wb"):
            for lane_id in ramp_lane_ids(kind, j):
                det_id = f"e2_{lane_id[:-2]}"  # strip trailing _0
                lines.append(
                    f'    <laneAreaDetector id="{det_id}" lane="{lane_id}" pos="0" length="-1" '
                    f'period="30" file="{rd}/e2_ramps.xml" friendlyPos="true"/>'
                )
    # VSL control-zone E2 (upstream of incident, all 3 lanes, per segment)
    for i in VSL_SEGS:
        for lane in range(3):
            lines.append(
                f'    <laneAreaDetector id="e2_vsl_{i}_{lane}" lane="fwy_eb_{i}_{lane}" pos="0" '
                f'length="-1" period="15" file="{rd}/e2_vsl.xml" friendlyPos="true"/>'
            )
    # queue-end / near-incident safety-proxy zone (segment just upstream of incident, seg 8)
    for lane in range(3):
        lines.append(
            f'    <laneAreaDetector id="e2_safety_{lane}" lane="fwy_eb_8_{lane}" pos="0" '
            f'length="-1" period="15" file="{rd}/e2_safety.xml" friendlyPos="true"/>'
        )
    lines.append("</additional>")

    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
