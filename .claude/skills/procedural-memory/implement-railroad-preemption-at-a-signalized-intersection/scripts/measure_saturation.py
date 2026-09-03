#!/usr/bin/env python3
"""
Measure the two quantities the ITE closed-form queue-clearance-time estimate
needs, from raw SUMO output rather than assuming textbook values:

  h  = saturation discharge headway at the J stop bar on the EB approach
  l1 = startup lost time

Method (same as measure-saturation-flow-and-validate-webster-method): run the
corridor with NO trains, capture exact stop-bar crossing times with an
<instantInductionLoop>, split them by EW-green onset, and for each queue
discharge compute headway_i = t_i - t_{i-1}.  h is the mean headway from the
5th vehicle onward; l1 = sum_{i<=4} (headway_i - h).
"""
import json
import os
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

import build_scenario as B
import common as C

OUT = os.path.join(C.ROOT, "outputs", "saturation")
os.makedirs(OUT, exist_ok=True)
CYCLE = 90.0
GREEN_EW_START = 0.0     # phase 0 begins at t=0 with offset 0


def main():
    rou = os.path.join(OUT, "sat.rou.xml")
    B.write_routes(rou, 900, 300, 400, 10 ** 6, 3600)   # headway huge -> no trains
    add = os.path.join(OUT, "sat.add.xml")
    det = os.path.abspath(os.path.join(OUT, "instant.out.xml"))
    open(add, "w").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
        f'    <instantInductionLoop id="sb" lane="X_J_0" pos="38.0" file="{det}"/>\n'
        "</additional>\n")
    cmd = ["sumo", "-n", C.NET_FILE, "-r", rou, "-a", add, "--begin", "0",
           "--end", "3600", "--step-length", "0.1", "--seed", "42",
           "--no-step-log", "true", "--time-to-teleport", "-1"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)

    passes = sorted(float(e.get("time")) for e in ET.parse(det).getroot()
                    if e.get("state") == "enter")
    # group into cycles: EW green is [k*90, k*90+40)
    disch = {}
    for t in passes:
        k = int(t // CYCLE)
        off = t - k * CYCLE
        if off < 45.0:                    # within EW green + yellow
            disch.setdefault(k, []).append(t)
    # Headway PROFILE by queue position.  Positions beyond the standing queue
    # are free arrivals, not saturated discharge, so h is taken over the
    # saturated band only (positions 5..13, identified from the profile:
    # variance jumps by an order of magnitude from position 14 on).
    bypos, first_gap = {}, []
    used = 0
    for k, ts in sorted(disch.items()):
        if k < 3 or len(ts) < 8:
            continue
        used += 1
        first_gap.append(ts[0] - k * CYCLE)      # green onset -> 1st crossing
        for i in range(1, len(ts)):
            bypos.setdefault(i, []).append(ts[i] - ts[i - 1])
    profile = {i: round(st.mean(v), 3) for i, v in sorted(bypos.items())}
    profile_sd = {i: round(st.pstdev(v), 3) for i, v in sorted(bypos.items())}
    headways = [x for i in range(5, 14) for x in bypos.get(i, [])]
    h = st.mean(headways)
    first4 = {i: bypos[i] for i in (1, 2, 3, 4) if i in bypos}
    # startup lost time: the extra time the first few vehicles take beyond h,
    # counting the first vehicle's own delay from green onset (it must also
    # travel the 38 m from the stop bar... no: the detector IS at the stop bar,
    # so this is purely reaction+acceleration of the queue head).
    l1 = max(0.0, st.mean(first_gap) - h) + \
        sum(max(0.0, st.mean(v) - h) for v in first4.values())
    res = {"n_passages": len(passes), "n_cycles_used": used,
           "saturation_headway_s": round(h, 3),
           "saturation_headway_sd_s": round(st.pstdev(headways), 3),
           "n_headway_samples": len(headways),
           "headway_profile_mean_by_position": profile,
           "headway_profile_sd_by_position": profile_sd,
           "saturated_band_positions": "5-13",
           "mean_green_onset_to_first_crossing_s": round(st.mean(first_gap), 3),
           "startup_lost_time_s": round(l1, 3),
           "implied_saturation_flow_vph": round(3600.0 / h, 1),
           "detector_file": det}
    with open(os.path.join(OUT, "saturation.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
