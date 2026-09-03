#!/usr/bin/env python3
"""Shared runtime instrumentation for the rail-preemption corridor.

Everything here is read from the COMPILED corridor.net.xml, never assumed.
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET_DIR = os.path.join(ROOT, "outputs", "network")
NET_FILE = os.path.join(NET_DIR, "corridor.net.xml")

# ---- geometry, from outputs/network/net_verification.json (compiled net) ----
JX_LO, JX_HI = 591.50, 608.50      # junction X footprint along the road (x)
                                   # = 17.0 m, the MUTCD minimum track
                                   #   clearance distance (compiled net)
MUTCD_MARGIN = 1.83                # 6 ft beyond the outermost rail
ENV_LO, ENV_HI = JX_LO - MUTCD_MARGIN, JX_HI + MUTCD_MARGIN
STOPBAR_X = 647.80                 # x of the J stop bar on lane X_J_0
CLEAR_STORAGE = STOPBAR_X - ENV_HI  # 37.47 m of MUTCD clear storage distance
MIN_OVERLAP = 0.5                  # m; a vehicle must be genuinely inside

# ---- SUMO rail-crossing constants measured in instrument.py -----------------
RAILCROSSING_TIMEGAP = 15.0        # s: X goes to "rr" this long before the
                                   #    train reaches the crossing (SUMO default)

# ---- signal ----------------------------------------------------------------
LINK = {"SB": 0, "WB": 1, "NB": 2, "EB": 3}   # linkIndex at J, from net.xml
NLINKS = 4
PH_EW_G, PH_EW_Y, PH_AR1, PH_NS_G, PH_NS_Y, PH_AR2 = range(6)
YELLOW_MIN = 3.0                   # s, matches the authored tlLogic
ALLRED_MIN = 2.0                   # s, matches the authored tlLogic
# concurrent pedestrian interval on each green phase (ITE): WALK + FDW.
# FDW = crossing width / 1.2 m/s; the crossed roadway is 2 x 3.2 m = 6.4 m.
PED_WALK = 7.0
PED_FDW = math.ceil(6.4 / 1.2)     # 6 s
PED_MIN_TOTAL = PED_WALK + PED_FDW  # 13 s -- may be truncated TO this, not below


def state(spec, base="r"):
    s = [base] * NLINKS
    for k, ch in spec.items():
        s[LINK[k]] = ch
    return "".join(s)


TRACK_CLEAR_STATE = state({"EB": "G"})              # discharges the approach
DWELL_STATE = state({"NB": "G", "SB": "G"})         # limited service, no feed


def vehicle_x_extent(traci, vid):
    """[x_rear, x_front] of a vehicle's body from its polled front-bumper
    position.  SUMO's angle is degrees clockwise from north, so the heading
    unit vector is (sin a, cos a)."""
    x, _y = traci.vehicle.getPosition(vid)
    a = math.radians(traci.vehicle.getAngle(vid))
    L = traci.vehicle.getLength(vid)
    xr = x - L * math.sin(a)
    return (min(x, xr), max(x, xr))


def occupancy(traci, lo=JX_LO, hi=JX_HI, min_overlap=MIN_OVERLAP):
    """Road vehicles whose PHYSICAL EXTENT genuinely overlaps the crossing
    footprint right now.  Returns [(vid, overlap_m, speed)].  This is a direct
    geometric measurement from polled positions -- not a queue-length proxy."""
    out = []
    for vid in traci.vehicle.getIDList():
        if traci.vehicle.getVehicleClass(vid) == "rail":
            continue
        a, b = vehicle_x_extent(traci, vid)
        ov = min(b, hi) - max(a, lo)
        if ov > min_overlap:
            out.append((vid, round(ov, 2), round(traci.vehicle.getSpeed(vid), 2)))
    return out


def nearest_train(traci):
    """(id, distance_to_crossing_m, speed) for the nearest approaching train,
    or None.  This is the fallback observation channel -- it works whether or
    not the crossing is exposed as a TraCI traffic light."""
    best = None
    for vid in traci.vehicle.getIDList():
        if traci.vehicle.getVehicleClass(vid) != "rail":
            continue
        e = traci.vehicle.getRoadID(vid)
        if e == "RS_X":
            d = traci.lane.getLength("RS_X_0") - traci.vehicle.getLanePosition(vid)
        elif e == "RN_X":
            d = traci.lane.getLength("RN_X_0") - traci.vehicle.getLanePosition(vid)
        elif e.startswith(":X"):
            d = 0.0
        else:
            continue
        if best is None or d < best[1]:
            best = (vid, d, traci.vehicle.getSpeed(vid))
    return best


def gate_is_down(traci):
    """True while road traffic is barred at the crossing.  Uses the crossing's
    own TraCI traffic-light state (verified available: 'X' appears in
    traci.trafficlight.getIDList() with a 2-link 'GG'/'yy'/'rr'/'uu' program)."""
    return traci.trafficlight.getRedYellowGreenState("X") == "r" * 2


def eb_queue(traci):
    """Standing EB vehicles on the approach that lies across the tracks."""
    return traci.edge.getLastStepHaltingNumber("X_J")
