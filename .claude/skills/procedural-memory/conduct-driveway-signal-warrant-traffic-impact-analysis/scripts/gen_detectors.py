#!/usr/bin/env python3
"""
Detector instrumentation for the driveway TIA.

  E1 <inductionLoop>      stop-bar counts, aggregated over exact CLOCK HOURS
                          (period=3600, begin=0 <=> 07:00).  This is the ONLY
                          volume source the MUTCD warrant engine is allowed to
                          use -- see the demand-vs-served-volume test.
  E2 <laneAreaDetector>   per-60 s maxJamLengthInMeters per lane group, for the
                          95th-percentile queue and the bay/throat spillover check.
  E3 <entryExitDetector>  one per turning movement: entry cross-section 250 m
                          upstream of the stop bar, exit 100 m past the junction.
                          meanTravelTime over that fixed segment minus a MEASURED
                          free-flow datum = HCM-style control delay.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SCEN, write

DET = os.path.join(SCEN, "detectors")
os.makedirs(DET, exist_ok=True)

ENTRY_POS_MAJ = 150.0   # on the 300 m feed -> 150 + 100 m bay = 250 m upstream of stop bar
EXIT_POS = 100.0        # 100 m past the junction on the departure edge
E1_POS = -2.0           # 2 m upstream of the lane end = stop bar
E2_PERIOD = 60
E1_PERIOD = 3600
E3_PERIOD = 3600

# approach -> (entry edge, lanes)
# NOTE: a <detEntry> at pos="0" NEVER registers -- a vehicle must physically
# cross the position, and vehicles are inserted at or beyond the lane start, so
# an entry cross-section at 0.0 silently produces zero samples for that whole
# movement (verified: e3_DWR/e3_SBL had vehicleSum=0 in every interval of every
# run until this was moved off 0.0).  It ALSO must sit beyond the insertion
# position: with the default departPos="base" a vehicle's front bumper starts at
# `length` m (5.0 m here), so an entry at pos <= 5.0 is likewise never crossed.
# 15.0 m is used, making the driveway/minor approach segment 235 m.
ENTRY_POS_MINOR = 15.0
APPROACH_ENTRY = {
    "EB": ("maj_W_feed", 2, ENTRY_POS_MAJ),
    "WB": ("maj_E_feed", 2, ENTRY_POS_MAJ),
    "DW": ("drw_N_in", None, ENTRY_POS_MINOR),   # lane count filled per variant
    "MN": ("min_S_in", 1, ENTRY_POS_MINOR),
}
# movement -> (approach, exit edge, exit lanes)
MOVEMENTS = {
    "EBT": ("EB", "maj_out_E", 2),
    "EBR": ("EB", "min_S_out", 1),
    "EBL": ("EB", "drw_N_out", 1),
    "WBT": ("WB", "maj_out_W", 2),
    "WBR": ("WB", "drw_N_out", 1),
    "WBL": ("WB", "min_S_out", 1),
    "DWL": ("DW", "maj_out_E", 2),
    "DWR": ("DW", "maj_out_W", 2),
    "SBL": ("MN", "maj_out_W", 2),
    "SBR": ("MN", "maj_out_E", 2),
}
# stop-bar E1 groups: approach -> list of (edge, lane index)
def e1_lanes(driveway_lanes):
    return {
        "EB": [("maj_W_bay", i) for i in range(3)],
        "WB": [("maj_E_bay", i) for i in range(3)],
        "DW": [("drw_N_in", i) for i in range(driveway_lanes)],
        "MN": [("min_S_in", 0)],
    }


def e2_groups(driveway_lanes):
    """laneAreaDetector chains: id -> list of lane ids (must be consecutive)."""
    g = {
        "q_EBL_bay": ["maj_W_bay_2"],                       # the 100 m left-turn bay
        "q_EBT":     ["maj_W_feed_0", "maj_W_bay_0"],       # EB through/right lane group
        "q_WBL_bay": ["maj_E_bay_2"],
        "q_WBT":     ["maj_E_feed_0", "maj_E_bay_0"],
        "q_MIN":     ["min_S_in_0"],
    }
    if driveway_lanes == 1:
        g["q_DW"] = ["drw_N_in_0"]
    else:
        g["q_DW"] = ["drw_N_in_0"]        # right-turn lane
        g["q_DW_L"] = ["drw_N_in_1"]      # left/through lane
    return g


def build(variant, driveway_lanes, outdir_token):
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<additional xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
    # ---------------- E1 stop-bar loops, per clock hour
    for appr, lanes in e1_lanes(driveway_lanes).items():
        for edge, li in lanes:
            did = f"e1_{appr}_{edge}_{li}"
            x.append(f'  <inductionLoop id="{did}" lane="{edge}_{li}" pos="{E1_POS}" '
                     f'period="{E1_PERIOD}" file="{outdir_token}e1_stopbar.xml"/>')
    # ---------------- E2 queue detectors
    for gid, lanes in e2_groups(driveway_lanes).items():
        if len(lanes) == 1:
            x.append(f'  <laneAreaDetector id="{gid}" lane="{lanes[0]}" pos="0" '
                     f'endPos="-0.1" period="{E2_PERIOD}" file="{outdir_token}e2_queue.xml"/>')
        else:
            x.append(f'  <laneAreaDetector id="{gid}" lanes="{" ".join(lanes)}" pos="0" '
                     f'endPos="-0.1" period="{E2_PERIOD}" file="{outdir_token}e2_queue.xml"/>')
    # ---------------- E3 per-movement travel-time detectors
    for mv, (appr, exit_edge, exit_lanes) in MOVEMENTS.items():
        edge, nl, pos = APPROACH_ENTRY[appr]
        nl = driveway_lanes if appr == "DW" else nl
        x.append(f'  <entryExitDetector id="e3_{mv}" period="{E3_PERIOD}" openEntry="true" '
                 f'timeThreshold="1.0" speedThreshold="1.39" '
                 f'file="{outdir_token}e3_movement.xml">')
        for i in range(nl):
            x.append(f'    <detEntry lane="{edge}_{i}" pos="{pos}"/>')
        for i in range(exit_lanes):
            x.append(f'    <detExit lane="{exit_edge}_{i}" pos="{EXIT_POS}"/>')
        x.append("  </entryExitDetector>")
    x.append("</additional>")
    p = os.path.join(DET, f"det_{variant}.add.xml")
    write(p, "\n".join(x) + "\n")
    print(f"[detectors] {variant:10s} -> {os.path.basename(p)} "
          f"(driveway lanes={driveway_lanes})")
    return p


def main():
    # detector `file` paths resolve relative to the ADDITIONAL FILE's directory,
    # so every run gets its own output dir passed as a relative token at run time.
    # We instead emit one add-file per variant with a placeholder that run_scenarios
    # rewrites into the per-run directory.
    build("std", 1, "@OUTDIR@/")
    build("rt", 2, "@OUTDIR@/")
    build("riro", 1, "@OUTDIR@/")


if __name__ == "__main__":
    main()
