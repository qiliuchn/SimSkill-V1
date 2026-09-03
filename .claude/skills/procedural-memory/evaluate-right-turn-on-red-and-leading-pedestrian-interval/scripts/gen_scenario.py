#!/usr/bin/env python3
"""Demand + detector generation for the RTOR / LPI experiment.

One demand set is shared by both geometry variants (identical routes, identical
flows); only the network geometry differs.

Two demand regimes
------------------
operational : through 240, right 170, left 80 veh/h per approach
              (right-turn share = 170/490 = 34.7 %), Poisson arrivals.
capacity    : identical through/left, right-turn demand raised to 1200 veh/h
              per approach so the right-turn movement is deeply oversaturated
              and the SERVED right-turn volume equals the movement capacity.

Pedestrians: personFlows over all 12 ordered (in_X -> out_Y) sidewalk pairs,
rate calibrated so that the MEASURED volume is ~200 ped/h per crossing.
"""
import argparse
import os

ARMS = ["N", "E", "S", "W"]
MOVES = {
    "N": {"r": "W", "s": "S", "l": "E"},
    "E": {"r": "N", "s": "W", "l": "S"},
    "S": {"r": "E", "s": "N", "l": "W"},
    "W": {"r": "S", "s": "E", "l": "N"},
}
# Right-turn demand is set from the MEASURED No-Turn-on-Red right-turn capacity
# at the chosen pedestrian volume (outputs/calibration/capacity_vs_ped.json:
# 218.1 veh/h/approach at ~200 ped/h per crossing), so the NTOR baseline sits at
# v/c = 170/218 = 0.78 - loaded enough for RTOR to matter, far enough below the
# capacity knee that a 10-seed comparison is defensible
# (see [[sumo-stochastic-variability-and-replication-design]]).
REGIMES = {
    "operational": {"s": 240.0, "l": 80.0, "r": 170.0},
    "capacity":    {"s": 240.0, "l": 80.0, "r": 1200.0},
}

VTYPE = """    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6"
           decel="4.5" sigma="0.5" tau="1.0" maxSpeed="16.0"
           speedFactor="1.0" speedDev="0" jmDriveAfterRedTime="-1"
           carFollowModel="Krauss">
        <param key="has.ssm.device" value="true"/>
        <param key="device.ssm.measures" value="TTC DRAC PET"/>
        <param key="device.ssm.thresholds" value="3.0 3.0 2.0"/>
        <param key="device.ssm.range" value="50.0"/>
        <param key="device.ssm.extratime" value="5.0"/>
        <param key="device.ssm.trajectories" value="false"/>
    </vType>
    <vType id="ped" vClass="pedestrian" speedFactor="1.0" speedDev="0"/>
"""


def gen_routes(path, regime, ped_per_flow, end, ped_end):
    d = REGIMES[regime]
    out = ['<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
           ' xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">']
    out.append(VTYPE)
    for a in ARMS:
        for m in ("r", "s", "l"):
            out.append(f'    <route id="rt_{a}{m}" edges="in_{a} out_{MOVES[a][m]}"/>')
    for a in ARMS:
        for m in ("r", "s", "l"):
            rate = d[m] / 3600.0
            out.append(f'    <flow id="f_{a}{m}" type="car" route="rt_{a}{m}" '
                       f'begin="0" end="{end}" period="exp({rate:.6f})" '
                       f'departLane="best" departSpeed="max"/>')
    # pedestrians: all 12 ordered sidewalk pairs
    for a in ARMS:
        for b in ARMS:
            if a == b:
                continue
            out.append(f'    <personFlow id="p_{a}{b}" type="ped" begin="0" end="{ped_end}" '
                       f'perHour="{ped_per_flow:.2f}" departPos="250">')
            out.append(f'        <walk from="in_{a}" to="out_{b}" arrivalPos="50"/>')
            out.append('    </personFlow>')
    out.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def gen_detectors(path, variant, e1_period, prefix_out, right_via=None):
    """Stop-line detectors.

    Two independent stop-line instruments:
      * `inst_in_<A>_<k>`  - 2 m UPSTREAM of the stop line.  Measures arrival at
        the stop line.  Good for total volume, but it CANNOT time the departure
        from the stop line, because a vehicle held at the line has already
        passed every upstream detector.
      * `instv_<A>`        - 1 m along the right turn's own INTERNAL via lane,
        i.e. immediately DOWNSTREAM of the stop line.  This is the instrument
        that times the actual stop-line crossing and is what the on-red /
        on-green classification is cross-checked against.

    Vehicle lane indices come from the compiled net (lane 0 = guessed sidewalk).
    """
    nveh = 3 if variant == "A_excl" else 2
    out = ['<additional>']
    for a in ARMS:
        for k in range(1, nveh + 1):
            lid = f"in_{a}_{k}"
            out.append(f'    <inductionLoop id="e1_{lid}" lane="{lid}" pos="-2.0" '
                       f'period="{e1_period}" file="{prefix_out}_e1.xml"/>')
            if k == 1:   # only the right-turn-carrying lane needs per-vehicle logging
                out.append(f'    <instantInductionLoop id="inst_{lid}" lane="{lid}" pos="-2.0" '
                           f'file="{prefix_out}_instant.xml"/>')
    if right_via:
        for a in ARMS:
            out.append(f'    <instantInductionLoop id="instv_{a}" lane="{right_via[a]}" '
                       f'pos="1.0" file="{prefix_out}_instantvia.xml"/>')
    out.append('</additional>')
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--regime", default="operational")
    ap.add_argument("--ped-per-flow", type=float, default=100.0)
    ap.add_argument("--end", type=float, default=3600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    gen_routes(a.out, a.regime, a.ped_per_flow, a.end, a.end)
    print("wrote", a.out)
