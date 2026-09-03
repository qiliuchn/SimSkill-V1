"""Shared configuration for the freeway AID (automatic incident detection) experiment."""
import os

# Override with AID_BASE to run this pipeline in a fresh working directory.
BASE = os.environ.get(
    "AID_BASE",
    "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-04_06-00-00")
SCRIPTS = os.path.join(BASE, "attempts", "attempt-1", "scripts")
OUT = os.path.join(BASE, "outputs")
NET_DIR = os.path.join(OUT, "network")
DEMAND_DIR = os.path.join(OUT, "demand")
DET_DIR = os.path.join(OUT, "detectors")
RUNS_DIR = os.path.join(OUT, "runs")
RESULTS_DIR = os.path.join(OUT, "results")
PLOTS_DIR = os.path.join(OUT, "plots")

SUMO_TOOLS = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo/tools"
SUMO_BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin/sumo"
NETCONVERT = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin/netconvert"

# ---------------- geometry ----------------
SEG_LEN = 250.0            # length of each mainline edge (m) -> finest detector station spacing
N_SEG = 24                 # 24 * 250 m = 6000 m of instrumented mainline
MAINLINE_LEN = SEG_LEN * N_SEG
SRC_LEN = 1000.0           # upstream insertion/warm-up edge
SNK_LEN = 1000.0           # downstream exit edge
RAMP_LEN = 300.0
N_LANES = 3
FREE_SPEED = 33.33         # m/s (120 km/h)
RAMP_SPEED = 22.22

# on-ramp merges at x = 750 m (junction J3); aux (acceleration) lane runs 750 -> 1000 m,
# so a 4->3 lane drop -- the RECURRENT bottleneck -- sits at x = 1000 m.
RAMP_MERGE_SEG = 3         # edge m03 carries N_LANES+1 lanes
INCIDENT_X_MIN = 1500.0    # incidents are drawn well downstream of the recurrent bottleneck
INCIDENT_X_MAX = 5750.0

# ---------------- detectors ----------------
DET_PERIOD = 30.0          # aggregation interval (s)
# station k sits at the START (pos = 5 m) of edge m{k}: x = 250*k, k = 0..23
STATION_X = [SEG_LEN * k for k in range(N_SEG)]

FIRST_STATION = 4   # x = 1000 m: first station downstream of the on-ramp merge + aux-lane drop,
                    # so every spacing subset starts at the same clean point


def stations_for_spacing(spacing_m):
    """Subset of station indices realising a given uniform station spacing."""
    step = int(round(spacing_m / SEG_LEN))
    return list(range(FIRST_STATION, N_SEG, step))

# ---------------- simulation ----------------
SIM_END = 3600
WARMUP = 600               # excluded from scoring
INCIDENT_T_MIN = 1200
INCIDENT_T_MAX = 2700
INCIDENT_DUR_MIN = 300
INCIDENT_DUR_MAX = 900

# Measured (not assumed) bottleneck capacity of the downstream 3->2 lane drop: ~4500 veh/h
# (see outputs/results/capacity_sweep.txt). Demand levels are expressed as % of that.
BOTTLENECK_CAPACITY = 4500.0
# demand levels: (mainline veh/h, ramp veh/h)
DEMAND_LEVELS = {
    "low":      (3200, 450),   # total 3650 =  81% of capacity -- free flow everywhere
    "moderate": (3650, 500),   # total 4150 =  92% of capacity -- near capacity, no recurrent queue
    "high":     (4250, 620),   # total 4870 = 108% of capacity -- recurrent queue grows upstream
}

N_SEEDS = 40
