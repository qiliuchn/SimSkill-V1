#!/usr/bin/env python3
"""
Scenario generation for the curbside-freight double-parking externality study.

Emits, for one experimental cell + seed, into a dedicated run directory:
  routes.rou.xml   vTypes, routes, car/cross-traffic flows, delivery flow + stop
  extra.add.xml    parkingArea (variant B only) + E1/E2 detectors + edge/laneData

Each run gets its OWN additional file inside its OWN directory on purpose:
SUMO resolves an edgeData/laneData `file` path relative to the ADDITIONAL
FILE's directory, not the working directory, so per-run additional files are
what keeps parallel replications from silently overwriting each other's output
(see the analyze-simulation-outputs / quantify-sumo-run-to-run-variability
gotcha).
"""
import os

# ---------------------------------------------------------------- timeline ---
DEMAND_BEGIN = 0        # cars start
DEMAND_END = 4800       # cars stop being generated
VAN_BEGIN = 300         # vans start a bit early so the curb cycle is running
VAN_END = 4200          # ... by the time the measurement window opens
WARMUP = 600            # measurement window = [WARMUP, MEAS_END)
MEAS_END = 4200         # 3600 s = exactly one hour of measured departures
SIM_END = 7200          # long tail so every inserted vehicle finishes

CROSS_VEH_PER_HOUR = 200

# curb-stop geometry (variant A: on the right TRAVEL lane ECURB_0)
STOP_START = 55.0
STOP_END = 95.0

# ------------------------------------------------------------- experiment ---
# delivery cells: (label, stops_per_hour, dwell_seconds)
#   D0    zero-delivery NEGATIVE CONTROL
#   D10   low intensity
#   D30   high intensity            -> 30 x 100 s = 3000 s/h curb occupancy
#   D6L   few long stops            ->  6 x 500 s = 3000 s/h curb occupancy
# D30 vs D6L is the EQUAL-CURB-OCCUPANCY contrast (frequency vs. dwell length).
DELIVERY_CELLS = {
    "D0":  (0,  0),
    "D10": (10, 100),
    "D30": (30, 100),
    "D6L": (6,  500),
}
# Background car volume (veh/h on the 2-lane main street). Six levels, chosen
# after probing: the signal alone gives ~2400 veh/h capacity (g/C = 0.667,
# 1800 veh/h/lane saturation), but during a curb blockage the curb zone drops
# to ONE lane, so the blocked-state capacity is ~1900-2000 veh/h. 600-1500 is
# comfortably undersaturated, 1800 is at the blocked-state knee, 2100-2400 is
# past it. Extra resolution around the knee is where the interesting
# nonlinearity lives.
VOLUMES = [600, 1200, 1500, 1800, 2100, 2400]
VARIANTS = ["A", "B"]
SEEDS = list(range(1, 21))   # 20 replications per cell, CRN across variants

VTYPES = """\
    <!-- Car: standard urban passenger car. sigma>0 and speedDev>0 are kept
         deliberately non-zero so the simulation seed genuinely propagates to
         outcomes (the variability skill warns that with sigma=0/speedDev=0 the
         sumo seed can have exactly zero effect). -->
    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"
           decel="4.5" sigma="0.5" tau="1.0" maxSpeed="16.7" speedDev="0.1"
           color="0.7,0.7,0.7"/>
    <!-- Delivery van: longer and markedly slower-accelerating than a car,
         which is what makes its pull-out merge cost something. -->
    <vType id="delivery" vClass="delivery" length="8.0" minGap="3.0" accel="1.0"
           decel="3.5" sigma="0.5" tau="1.2" maxSpeed="13.89" speedDev="0.05"
           guiShape="delivery" color="1,0.5,0"/>
"""


def write_routes(path, variant, volume, cell, seed):
    stops_per_hour, dwell = DELIVERY_CELLS[cell]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>", VTYPES]
    parts.append('    <route id="main"  edges="E0 ECURB E2 E3"/>')
    parts.append('    <route id="cross" edges="CIN COUT"/>')
    parts.append(
        f'    <flow id="car" type="car" route="main" begin="{DEMAND_BEGIN}" '
        f'end="{DEMAND_END}" vehsPerHour="{volume}" departLane="free" '
        f'departSpeed="max" departPos="base"/>')
    parts.append(
        f'    <flow id="xcar" type="car" route="cross" begin="{DEMAND_BEGIN}" '
        f'end="{DEMAND_END}" vehsPerHour="{CROSS_VEH_PER_HOUR}" '
        f'departLane="free" departSpeed="max"/>')

    if stops_per_hour > 0:
        period = 3600.0 / stops_per_hour
        if variant == "A":
            # LANE-BLOCKING stop: parking="false" keeps the van physically in
            # the right TRAVEL lane, occupying it, forcing following cars to
            # merge left. parking="true" here would make the van vanish from
            # lane occupancy and invalidate the whole experiment.
            stop = (f'        <stop lane="ECURB_0" startPos="{STOP_START}" '
                    f'endPos="{STOP_END}" duration="{dwell}" parking="false"/>')
        else:
            # Dedicated loading bay: an off-line parkingArea on the
            # delivery-only bay lane. parking="true" -> van leaves the
            # carriageway entirely for the dwell.
            stop = (f'        <stop parkingArea="LB0" duration="{dwell}" '
                    f'parking="true"/>')
        # departLane="0" (the curb lane) in BOTH variants: deterministic and
        # identical across the A/B contrast, and it is how a van approaching a
        # curb stop actually travels.
        parts.append(
            f'    <flow id="van" type="delivery" route="main" '
            f'begin="{VAN_BEGIN}" end="{VAN_END}" period="{period:.4f}" '
            f'departLane="0" departSpeed="max">')
        parts.append(stop)
        parts.append("    </flow>")
    parts.append("</routes>")
    with open(path, "w") as fh:
        fh.write("\n".join(parts) + "\n")


def write_additional(path, variant):
    p = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    if variant == "B":
        p.append('    <!-- dedicated loading bay: off-line parkingArea sitting'
                 ' on the delivery-only bay lane ECURB_0 -->')
        p.append('    <parkingArea id="LB0" lane="ECURB_0" roadsideCapacity="6"'
                 ' startPos="15" endPos="135" onRoad="false"/>')
    p.append('    <!-- E1 loops 50 m DOWNSTREAM of the curb zone: throughput -->')
    p.append('    <inductionLoop id="e1_dn_0" lane="E2_0" pos="50" period="300" file="e1.xml"/>')
    p.append('    <inductionLoop id="e1_dn_1" lane="E2_1" pos="50" period="300" file="e1.xml"/>')
    p.append('    <!-- E2 lane-area detectors covering all of E0, i.e. the whole')
    p.append('         approach UPSTREAM of the curb zone: queue length.')
    p.append('         One per lane - a multi-lane E2 detector needs CONSECUTIVE')
    p.append('         lanes, it cannot span parallel lanes. -->')
    p.append('    <laneAreaDetector id="e2_up_0" lane="E0_0" pos="0" endPos="599" period="60" file="e2.xml"/>')
    p.append('    <laneAreaDetector id="e2_up_1" lane="E0_1" pos="0" endPos="599" period="60" file="e2.xml"/>')
    p.append('    <edgeData id="ed" file="edgedata.xml" period="300" excludeEmpty="false"/>')
    p.append('    <laneData id="ld_van" file="lanedata_van.xml" period="300" vTypes="delivery" excludeEmpty="false"/>')
    p.append('    <laneData id="ld_car" file="lanedata_car.xml" period="300" vTypes="car" excludeEmpty="false"/>')
    p.append("</additional>")
    with open(path, "w") as fh:
        fh.write("\n".join(p) + "\n")


def build_run_dir(run_dir, variant, volume, cell, seed):
    os.makedirs(run_dir, exist_ok=True)
    write_routes(os.path.join(run_dir, "routes.rou.xml"),
                 variant, volume, cell, seed)
    write_additional(os.path.join(run_dir, "extra.add.xml"), variant)
    return run_dir
