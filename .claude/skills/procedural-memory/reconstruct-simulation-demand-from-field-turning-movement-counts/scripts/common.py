#!/usr/bin/env python3
"""Shared paths, constants and SUMO output parsers for the field-count-to-demand study."""
import os
import sys
import subprocess
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
os.environ["SUMO_HOME"] = SUMO_HOME
if os.path.join(SUMO_HOME, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))

SUMO_BIN_DIR = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN_DIR, "sumo")
NETCONVERT = os.path.join(SUMO_BIN_DIR, "netconvert")

HERE = os.path.dirname(os.path.abspath(__file__))
ATTEMPT = os.path.abspath(os.path.join(HERE, ".."))
EPISODE = os.path.abspath(os.path.join(ATTEMPT, "..", ".."))
WORK = os.path.join(ATTEMPT, "work")
OUT = os.path.join(EPISODE, "outputs")
SCEN = os.path.join(WORK, "scenario")
RUNS = os.path.join(WORK, "runs")
for d in (WORK, OUT, SCEN, RUNS):
    os.makedirs(d, exist_ok=True)

NET = os.path.join(SCEN, "corridor.net.xml")
ADD_DET = os.path.join(SCEN, "detectors.add.xml")

# ------------------------------------------------------------------ geometry
X = dict(WF=-2080.0, bWF_J1=-80.0, J1=0.0, bMB_J1=80.0, MB=200.0,
         bMB_J2=320.0, J2=400.0, bJ3_J2=480.0, bJ2_J3=720.0,
         J3=800.0, bEF_J3=880.0, EF=2880.0)
SIDE_Y = 250.0
DWY = (200.0, -150.0)

JUNCTIONS = ["J1", "J2", "J3"]
APPROACHES = ["EB", "WB", "NB", "SB"]     # NB = from the south leg, SB = from the north leg
MOVEMENTS = ["L", "T", "R"]

# arterial approach (bay) edge feeding each junction, per direction
EB_BAY = {"J1": "eb_WF_J1_bay", "J2": "eb_MB_J2_bay", "J3": "eb_J2_J3_bay"}
WB_BAY = {"J3": "wb_EF_J3_bay", "J2": "wb_J3_J2_bay", "J1": "wb_MB_J1_bay"}
EB_FEED = {"J1": "eb_WF_J1_feed", "J2": "eb_MB_J2_feed", "J3": "eb_J2_J3_feed"}
WB_FEED = {"J3": "wb_EF_J3_feed", "J2": "wb_J3_J2_feed", "J1": "wb_MB_J1_feed"}
SB_IN = {j: "sN%s_in" % j[-1] for j in JUNCTIONS}     # north leg -> junction (southbound)
NB_IN = {j: "sS%s_in" % j[-1] for j in JUNCTIONS}     # south leg -> junction (northbound)
SB_OUT = {j: "sS%s_out" % j[-1] for j in JUNCTIONS}
NB_OUT = {j: "sN%s_out" % j[-1] for j in JUNCTIONS}

APPROACH_EDGE = {}
for _j in JUNCTIONS:
    APPROACH_EDGE[(_j, "EB")] = EB_BAY[_j]
    APPROACH_EDGE[(_j, "WB")] = WB_BAY[_j]
    APPROACH_EDGE[(_j, "SB")] = SB_IN[_j]
    APPROACH_EDGE[(_j, "NB")] = NB_IN[_j]

# ------------------------------------------------------------------- signals
CYCLE = 90
PH_ART_G = 41          # arterial through+right green
PH_ART_Y = 3
PH_ART_AR = 2
PH_LEFT_G = 12         # arterial protected left
PH_LEFT_Y = 3
PH_LEFT_AR = 2
PH_SIDE_G = 22         # side street (all movements)
PH_SIDE_Y = 3
PH_SIDE_AR = 2
DESIGN_SPEED = 13.89
OFFSETS = {"J1": 0, "J2": 29, "J3": 58}   # EB progression at 400 m / 13.89 m/s

# ------------------------------------------------------------------ analysis
BIN = 900                       # 15-minute count bin (s)
N_BINS = 16                     # 4 hours of demand
DEMAND_END = BIN * N_BINS       # 14400 s
SIM_END = 25200                 # drain tail
STEP = 0.5

# nominal saturation-flow assumption used ONLY for scenario design; every reported
# v/c uses the MEASURED value from measure_saturation.py
S_DESIGN = 1850.0


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("command failed: %s\nSTDOUT:\n%s\nSTDERR:\n%s"
                           % (" ".join(cmd), p.stdout[-4000:], p.stderr[-4000:]))
    return p


# ------------------------------------------------------------------ parsers
def parse_tripinfo(path):
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            out.append(dict(id=el.get("id"), depart=float(el.get("depart")),
                            arrival=float(el.get("arrival")),
                            duration=float(el.get("duration")),
                            routeLength=float(el.get("routeLength")),
                            waitingTime=float(el.get("waitingTime")),
                            timeLoss=float(el.get("timeLoss")),
                            departDelay=float(el.get("departDelay"))))
            el.clear()
    return out


def parse_summary(path):
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            rows.append({k: el.get(k) for k in
                         ("time", "loaded", "inserted", "running", "waiting",
                          "ended", "teleports", "collisions", "meanSpeed")})
            el.clear()
    return rows


def parse_e1(path):
    """{detID: [(begin, end, nVehContrib, flow, occupancy)]}"""
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            out.setdefault(el.get("id"), []).append(
                (float(el.get("begin")), float(el.get("end")),
                 int(el.get("nVehContrib")), float(el.get("flow")),
                 float(el.get("occupancy"))))
            el.clear()
    return out


def parse_instant(path):
    """[(detID, time, state, vehID)] from an instantInductionLoop output file."""
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut":
            out.append((el.get("id"), float(el.get("time")),
                        el.get("state"), el.get("vehID")))
            el.clear()
    return out


def parse_e2(path):
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            out.setdefault(el.get("id"), []).append(dict(
                begin=float(el.get("begin")), end=float(el.get("end")),
                maxJamVeh=int(el.get("maxJamLengthInVehicles")),
                maxJamM=float(el.get("maxJamLengthInMeters")),
                nVehSeen=int(el.get("nVehSeen"))))
            el.clear()
    return out


def bin_index(t):
    return int(t // BIN)


def geh(m, c):
    if m == 0 and c == 0:
        return 0.0
    return ((m - c) ** 2 / ((m + c) / 2.0)) ** 0.5
