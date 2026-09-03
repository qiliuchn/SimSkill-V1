#!/usr/bin/env python3
"""Shared definitions of the intersection's signal structure and detector map.

Link index map (verified from the built net via sumolib, see build_network.py):
    0 NC_0->CW_0 (minor N right)     6 SC_0->CE_0 (minor S right)
    1 NC_0->CS_0 (minor N through)   7 SC_0->CN_0 (minor S through)
    2 NC_1->CE_1 (minor N LEFT)      8 SC_1->CW_1 (minor S LEFT)
    3 EC_0->CN_0 (major E right)     9 WC_0->CS_0 (major W right)
    4 EC_0->CW_0 (major E through)  10 WC_0->CE_0 (major W through)
    5 EC_1->CS_1 (major E LEFT)     11 WC_1->CN_1 (major W LEFT)

Program: 4 green phases (all movements fully protected), each followed by
3 s yellow + 1 s all-red  ->  total lost time L = 4 x 4 s = 16 s.
"""

NLINKS = 12
YELLOW = 3
ALLRED = 1

# green-phase index in the 12-phase program -> descriptor
GREEN_PHASES = {
    0: dict(name="A_major_thru", lanes=["EC_0", "WC_0"], links=[3, 4, 9, 10],
            road="major", mvt="thru"),
    3: dict(name="B_major_left", lanes=["EC_1", "WC_1"], links=[5, 11],
            road="major", mvt="left"),
    6: dict(name="C_minor_thru", lanes=["NC_0", "SC_0"], links=[0, 1, 6, 7],
            road="minor", mvt="thru"),
    9: dict(name="D_minor_left", lanes=["NC_1", "SC_1"], links=[2, 8],
            road="minor", mvt="left"),
}
GREEN_ORDER = [0, 3, 6, 9]

# every incoming lane -> the green phase it is served by
LANE2PHASE = {ln: p for p, d in GREEN_PHASES.items() for ln in d["lanes"]}
ALL_DET_LANES = [ln for p in GREEN_ORDER for ln in GREEN_PHASES[p]["lanes"]]

MAJOR_SPEED = 60 / 3.6
MINOR_SPEED = 40 / 3.6
LANE_SPEED = {ln: (MAJOR_SPEED if GREEN_PHASES[LANE2PHASE[ln]]["road"] == "major"
                   else MINOR_SPEED) for ln in ALL_DET_LANES}
APPROACH_LEN = 389.60   # actual lane length from the built net (400 m nominal
                        # minus the junction radius); verified with sumolib.


def _state(greens, char="G"):
    s = ["r"] * NLINKS
    for i in greens:
        s[i] = char
    return "".join(s)


def build_program(green_durs, min_durs=None, max_durs=None, tls_type="static",
                  params=None, program_id="0", tls_id="C"):
    """Return the <tlLogic> XML string.

    green_durs / min_durs / max_durs : dict green-phase-index -> seconds
    params : dict of <param key=..  value=..> children (actuated params +
             custom-detector bindings)
    """
    lines = [f'    <tlLogic id="{tls_id}" type="{tls_type}" '
             f'programID="{program_id}" offset="0">']
    for k, v in (params or {}).items():
        lines.append(f'        <param key="{k}" value="{v}"/>')
    for gp in GREEN_ORDER:
        links = GREEN_PHASES[gp]["links"]
        d = green_durs[gp]
        attrs = f'duration="{d:.0f}" state="{_state(links)}"'
        if tls_type in ("actuated", "delay_based"):
            mn = (min_durs or {}).get(gp, 5)
            mx = (max_durs or {}).get(gp, 50)
            attrs += f' minDur="{mn:.0f}" maxDur="{mx:.0f}"'
        lines.append(f'        <phase {attrs} name="{GREEN_PHASES[gp]["name"]}"/>')
        lines.append(f'        <phase duration="{YELLOW}" '
                     f'state="{_state(links, "y")}"/>')
        lines.append(f'        <phase duration="{ALLRED}" state="{_state([])}"/>')
    lines.append('    </tlLogic>')
    return "\n".join(lines)


def detector_defs(setback_m, lane_subset=None, det_len=None, prefix="det"):
    """<inductionLoop> definitions placed `setback_m` upstream of the stop line.

    pos is measured from the START of the lane, so pos = laneLength - setback.
    Returns (xml_string, {laneID: detID}).
    """
    lanes = lane_subset if lane_subset is not None else ALL_DET_LANES
    xml, mapping = [], {}
    for ln in lanes:
        did = f"{prefix}_{ln}"
        pos = APPROACH_LEN - setback_m
        # -0.1 keeps a 0 m setback detector fully inside the lane
        pos = min(pos, APPROACH_LEN - 0.2)
        xml.append(f'    <inductionLoop id="{did}" lane="{ln}" pos="{pos:.2f}" '
                   f'period="100000" file="NUL"/>')
        mapping[ln] = did
    return "\n".join(xml), mapping
