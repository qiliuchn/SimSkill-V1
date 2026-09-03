"""Shared configuration for the reversible-lane (tidal-flow) corridor study.

FIXED PHYSICAL CROSS-SECTION -- 6 lanes, 3.2 m each, centred on the corridor
centre line (y = 0):

    y = +8.0   L6   permanently westbound
    y = +4.8   L5   permanently westbound
    y = +1.6   L4   REVERSIBLE   (westbound in the 3+3 base configuration)
    y = -1.6   L3   REVERSIBLE   (eastbound in the 3+3 base configuration)
    y = -4.8   L2   permanently eastbound
    y = -8.0   L1   permanently eastbound

ENCODING B (accepted).  Every directional edge of the facility declares all SIX
physical lanes, `spreadType="center"` and no explicit shape, so netconvert lays
the eastbound edge's lane i and the westbound edge's lane 5-i on EXACTLY the
same y coordinate.  Every lane is compiled OPEN so netconvert builds the
complete internal-junction connectivity for all of them; the actual lane
assignment (including the permanent 2+2 lanes) is established at t=0 and
changed during the run with traci.lane.setAllowed / setDisallowed.

    physical   EB representation      WB representation
    L1         <ebedge>_0             <wbedge>_5     (permanently EB)
    L2         <ebedge>_1             <wbedge>_4     (permanently EB)
    L3         <ebedge>_2             <wbedge>_3     (REVERSIBLE)
    L4         <ebedge>_3             <wbedge>_2     (REVERSIBLE)
    L5         <ebedge>_4             <wbedge>_1     (permanently WB)
    L6         <ebedge>_5             <wbedge>_0     (permanently WB)

lane index 0 is the rightmost lane in the direction of travel.
"""
import os

SUMO_HOME = os.environ.get(
    "SUMO_HOME",
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo",
)
TOOLS = os.path.join(SUMO_HOME, "tools")

EPISODE = os.environ.get("REVLANE_WORKDIR", os.getcwd())
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(EPISODE, "outputs")
NETDIR = os.path.join(OUT, "net")
DEMDIR = os.path.join(OUT, "demand")
RUNDIR = os.path.join(OUT, "runs")
ANADIR = os.path.join(OUT, "analysis")
PLOTDIR = os.path.join(OUT, "plots")

# --- geometry -------------------------------------------------------------
CORRIDOR_LEN = 3000.0       # m between the two signalized terminals
STUB_LEN = 400.0            # loading / unloading tails outside the terminals
LANE_WIDTH = 3.2
CORR_SPEED = 16.67          # m/s  (60 km/h)

# --- signal ---------------------------------------------------------------
CYCLE = 90
G_CORR, Y_CORR, G_CROSS, Y_CROSS = 48, 4, 34, 4   # corridor g/C = 48/90 = 0.533

# --- facility edges, in travel order, per direction -----------------------
EB_EDGES = ["apW_in", "COR_EB", "apE_out"]
WB_EDGES = ["apE_in", "COR_WB", "apW_out"]
DIR_EDGES = {"EB": EB_EDGES, "WB": WB_EDGES}
CORRIDOR_EDGE = {"EB": "COR_EB", "WB": "COR_WB"}

N_PHYS = 6
PHYS_LANES = ["L1", "L2", "L3", "L4", "L5", "L6"]
PHYS_Y = {"L1": -8.0, "L2": -4.8, "L3": -1.6, "L4": 1.6, "L5": 4.8, "L6": 8.0}


def lane_id(direction, edge, phys):
    """SUMO lane id of physical lane `phys` in `direction` on `edge`."""
    k = PHYS_LANES.index(phys)           # 0..5, south -> north
    idx = k if direction == "EB" else (N_PHYS - 1 - k)
    return f"{edge}_{idx}"


def dir_lane_ids(direction, phys):
    """All SUMO lane ids of physical lane `phys` in `direction`, whole facility."""
    return [lane_id(direction, e, phys) for e in DIR_EDGES[direction]]


# --- lane-assignment configurations --------------------------------------
PERMANENT = {"L1": "EB", "L2": "EB", "L5": "WB", "L6": "WB"}
REVERSIBLE = ["L3", "L4"]

CONFIGS = {
    "3+3": {"L3": "EB", "L4": "WB"},
    "4+2": {"L3": "EB", "L4": "EB"},
    "2+4": {"L3": "WB", "L4": "WB"},
}


def assignment(config):
    """physical lane -> owning direction, for every one of the six lanes."""
    a = dict(PERMANENT)
    a.update(CONFIGS[config])
    return a


def n_lanes(direction, config):
    return sum(1 for d in assignment(config).values() if d == direction)


OPEN_CLASSES = [
    "passenger", "bus", "coach", "truck", "trailer", "delivery", "motorcycle",
    "moped", "taxi", "emergency", "authority", "private", "army", "vip", "hov",
    "evehicle", "custom1", "custom2",
]
CLOSED_CLASSES = ["authority"]      # no demand of this vClass exists anywhere

PERSON_PER_VEH = 1.35               # uniform car occupancy for person-hours

# --- demand ---------------------------------------------------------------
PEAK_TOTAL = 4600.0                 # veh/h summed over both corridor directions
OFFPEAK_TOTAL = 2400.0
CROSS_FLOW = 400.0                  # veh/h per cross-street approach


def ensure_dirs():
    for d in (OUT, NETDIR, DEMDIR, RUNDIR, ANADIR, PLOTDIR):
        os.makedirs(d, exist_ok=True)
