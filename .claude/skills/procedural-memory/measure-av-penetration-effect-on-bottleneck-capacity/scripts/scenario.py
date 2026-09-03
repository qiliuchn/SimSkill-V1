#!/usr/bin/env python3
"""
Shared scenario definition for the CAV-penetration / bottleneck-capacity study.

Defines:
  * the vType fleet (HUMAN, HUMAN_SIGMA0, HUMAN_FAST, ACC, CACC, CACC_TIGHT)
  * the detector / edgeData instrumentation
  * the demand ramp profile
  * the route-file generator (per-vehicle explicit type assignment, CRN-nested)

Design notes
------------
* ALL vTypes share length / minGap / accel / decel / emergencyDecel / speedFactor /
  lane-change model.  The ONLY things that differ are `carFollowModel`, `sigma`
  and `tau`.  That is what makes HUMAN_FAST a genuine mechanism control.
* ACC and CACC are given the SAME desired time gap (tau = 0.9 s) so that
  "ACC vs CACC" is a pure model-structure contrast, and HUMAN_FAST (tau = 0.9 s,
  sigma = 0) is the matched Krauss control for BOTH of them.
* CACC_TIGHT (tau = 0.6 s) is measured homogeneously only, to show what a
  genuinely tighter cooperative gap buys on top of the model structure.
"""

import os
import math
import numpy as np

FREEFLOW = 33.33          # m/s (120 km/h) on every edge
SIM_END = 2700            # s
STEP_LENGTH = 0.1         # s  -- required for ACC/CACC stability (SUMO docs)
DET_PERIOD = 60           # s  aggregation for E1 / E2 / edgeData

# ---------------------------------------------------------------- vTypes ----
# tau of the "fast" family.  HUMAN_FAST.tau == ACC.tau == CACC.tau by construction.
TAU_HUMAN = 1.3
TAU_FAST = 0.9
TAU_CACC_TIGHT = 0.6

_COMMON = dict(
    vClass="passenger", length="5.0", minGap="2.5",
    accel="2.6", decel="4.5", emergencyDecel="9.0",
    maxSpeed="40.0", speedFactor="normc(1.0,0.10,0.85,1.15)",
    laneChangeModel="LC2013", carFollowModel="Krauss",
)

# ACC gains: SUMO defaults, written out explicitly so the parameterisation is documented.
_ACC_GAINS = dict(
    speedControlGain="-0.4",
    gapClosingControlGainSpeed="0.8", gapClosingControlGainSpace="0.04",
    gapControlGainSpeed="0.07", gapControlGainSpace="0.23",
    collisionAvoidanceGainSpeed="0.23", collisionAvoidanceGainSpace="0.8",
)
# CACC cooperative gains: SUMO defaults, written out explicitly.
_CACC_GAINS = dict(
    speedControlGainCACC="-0.4",
    gapClosingControlGainGap="0.005", gapClosingControlGainGapDot="0.05",
    gapControlGainGap="0.45", gapControlGainGapDot="0.0125",
    collisionAvoidanceGainGap="0.45", collisionAvoidanceGainGapDot="0.05",
    speedControlMinGap="1.66",
)

VTYPES = {}


def _mk(name, color, **over):
    d = dict(_COMMON)
    d.update(over)
    d["id"] = name
    d["color"] = color
    VTYPES[name] = d


# (i) human reference
_mk("HUMAN",        "1,1,0",   carFollowModel="Krauss", sigma="0.5", tau=str(TAU_HUMAN))
# decomposition control: removes driver imperfection ONLY (tau unchanged)
_mk("HUMAN_SIGMA0", "1,0.6,0", carFollowModel="Krauss", sigma="0.0", tau=str(TAU_HUMAN))
# (iv) NEGATIVE / MECHANISM CONTROL: still Krauss, sigma=0, tau == ACC tau
_mk("HUMAN_FAST",   "1,0,1",   carFollowModel="Krauss", sigma="0.0", tau=str(TAU_FAST))
# (ii) ACC
_mk("ACC",          "0,0.7,1", carFollowModel="ACC", sigma="0.0", tau=str(TAU_FAST), **_ACC_GAINS)
# (iii) CACC, same desired time gap as ACC -> pure model-structure contrast
_mk("CACC",         "0,1,0.3", carFollowModel="CACC", sigma="0.0", tau=str(TAU_FAST), **_CACC_GAINS)
# CACC with a genuinely tighter cooperative gap (homogeneous baseline only)
_mk("CACC_TIGHT",   "0,0.5,0", carFollowModel="CACC", sigma="0.0", tau=str(TAU_CACC_TIGHT), **_CACC_GAINS)

HUMAN_TYPE = "HUMAN"
SWEEP_ARMS = ["ACC", "CACC", "HUMAN_FAST"]      # AV types mixed into HUMAN traffic
HOMOGENEOUS = ["HUMAN", "HUMAN_SIGMA0", "HUMAN_FAST", "ACC", "CACC", "CACC_TIGHT"]


def vtype_xml(indent="    "):
    out = []
    for name in ["HUMAN", "HUMAN_SIGMA0", "HUMAN_FAST", "ACC", "CACC", "CACC_TIGHT"]:
        d = VTYPES[name]
        attrs = " ".join('%s="%s"' % (k, v) for k, v in d.items() if k != "id" and k != "color")
        out.append('%s<vType id="%s" color="%s" %s/>' % (indent, d["id"], d["color"], attrs))
    return "\n".join(out)


# ------------------------------------------------------------ demand ramp ----
# One fixed demand profile used for EVERY cell (baselines, sweep, arrangement).
# The ramp lets each fleet reveal its own breakdown point (=> pre-breakdown peak
# flow / capacity drop) without having to pick a fleet-specific demand level.
RAMP = dict(warm_q=3600.0, warm_end=240.0,
            ramp_end=1800.0, hi_q=10000.0, sim_end=SIM_END)


def demand_rate(t):
    """total demand across the 3 upstream lanes, veh/h, at time t."""
    if t < RAMP["warm_end"]:
        return RAMP["warm_q"]
    if t < RAMP["ramp_end"]:
        f = (t - RAMP["warm_end"]) / (RAMP["ramp_end"] - RAMP["warm_end"])
        return RAMP["warm_q"] + f * (RAMP["hi_q"] - RAMP["warm_q"])
    return RAMP["hi_q"]


def departure_times(demand_seed):
    """Non-homogeneous Poisson arrivals following the ramp.  Depends ONLY on the
    demand seed => identical vehicle stream across every penetration level (CRN)."""
    rng = np.random.default_rng(1000 + demand_seed)
    t, out = 0.0, []
    qmax = RAMP["hi_q"]
    while t < SIM_END:
        t += rng.exponential(3600.0 / qmax)       # thinning at the max rate
        if t >= SIM_END:
            break
        if rng.random() < demand_rate(t) / qmax:
            out.append(t)
    return np.array(out)


def type_uniforms(demand_seed, n):
    """One U(0,1) per vehicle, drawn from the DEMAND seed only.  Assigning
    'AV if u_i < p' makes the AV set at p=0.2 a strict subset of the set at
    p=0.4 -> maximal Common-Random-Numbers coupling across the sweep."""
    rng = np.random.default_rng(7000 + demand_seed)
    return rng.random(n)


def assign_types(demand_seed, av_type, p, arrangement="random", block=24):
    """Return a list of type names, one per vehicle, in departure order."""
    dts = departure_times(demand_seed)
    n = len(dts)
    if arrangement == "random":
        u = type_uniforms(demand_seed, n)
        types = [av_type if ui < p else HUMAN_TYPE for ui in u]
    elif arrangement == "platoon":
        # identical AV COUNT, but AVs depart in consecutive blocks.
        n_av = int(round(p * n))
        types = [HUMAN_TYPE] * n
        # lay down alternating blocks sized so that the realised share == p
        blk_av = block
        blk_hv = max(1, int(round(block * (1 - p) / p))) if p > 0 else n
        i, placed = 0, 0
        while i < n and placed < n_av:
            for k in range(min(blk_av, n_av - placed)):
                if i + k < n:
                    types[i + k] = av_type
            placed += min(blk_av, n_av - placed)
            i += blk_av + blk_hv
        # if we ran off the end before placing them all, top up from the front gaps
        j = 0
        while placed < n_av and j < n:
            if types[j] == HUMAN_TYPE:
                types[j] = av_type
                placed += 1
            j += 1
    else:
        raise ValueError(arrangement)
    return dts, types


ROUTE_EDGES = "E_src E_app E_bn E_dis"


def write_routes(path, demand_seed, av_type, p, arrangement="random", block=24):
    dts, types = assign_types(demand_seed, av_type, p, arrangement, block)
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write('    <route id="r0" edges="%s"/>\n' % ROUTE_EDGES)
        for i, (t, ty) in enumerate(zip(dts, types)):
            f.write('    <vehicle id="v%d" type="%s" route="r0" depart="%.2f" '
                    'departLane="free" departSpeed="last"/>\n' % (i, ty, t))
        f.write('</routes>\n')
    return len(dts), sum(1 for x in types if x != HUMAN_TYPE)


def write_routes_vtypedist(path, av_type, p):
    """Alternative demand realisation using a genuine SUMO <vTypeDistribution> +
    <flow>; used as a cross-check that the explicit per-vehicle assignment above
    reproduces SUMO's own probability-weighted sampling."""
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write('    <vTypeDistribution id="mix" vTypes="%s %s" probabilities="%.4f %.4f"/>\n'
                % (HUMAN_TYPE, av_type, 1 - p, p))
        f.write('    <route id="r0" edges="%s"/>\n' % ROUTE_EDGES)
        # piecewise-constant approximation of the same ramp, 100 s steps
        t = 0.0
        i = 0
        while t < SIM_END:
            q = demand_rate(t + 50.0)
            f.write('    <flow id="f%d" type="mix" route="r0" begin="%.0f" end="%.0f" '
                    'vehsPerHour="%.1f" departLane="free" departSpeed="last"/>\n'
                    % (i, t, min(t + 100, SIM_END), q))
            t += 100.0
            i += 1
        f.write('</routes>\n')


# ------------------------------------------------------- instrumentation ----
# E1 positions on E_app (length 2496 m).  2396 m = 100 m upstream of the drop.
E_APP_LEN = 2496.0
FD_POSITIONS = [(2396.0, "x100"), (1500.0, "x1000"), (700.0, "x1800")]


def additional_xml(with_vtypes=True):
    L = []
    L.append('<?xml version="1.0" encoding="UTF-8"?>')
    L.append('<additional>')
    if with_vtypes:
        L.append(vtype_xml())
    # --- E1 array AT the bottleneck stop line (10 m downstream of the lane drop) ---
    for ln in range(2):
        L.append('    <inductionLoop id="e1_bn_%d" lane="E_bn_%d" pos="10.0" period="%d" '
                 'file="e1_bn.xml"/>' % (ln, ln, DET_PERIOD))
    # --- downstream free-flow check ---
    for ln in range(2):
        L.append('    <inductionLoop id="e1_dn_%d" lane="E_dis_%d" pos="600.0" period="%d" '
                 'file="e1_dn.xml"/>' % (ln, ln, DET_PERIOD))
    # --- entry flow (is the ENTRY the constraint?) ---
    for ln in range(3):
        L.append('    <inductionLoop id="e1_src_%d" lane="E_src_%d" pos="250.0" period="%d" '
                 'file="e1_src.xml"/>' % (ln, ln, DET_PERIOD))
    # --- upstream FD arrays ---
    for pos, tag in FD_POSITIONS:
        for ln in range(3):
            L.append('    <inductionLoop id="e1_app_%s_%d" lane="E_app_%d" pos="%.1f" period="%d" '
                     'file="e1_app.xml"/>' % (tag, ln, ln, pos, DET_PERIOD))
    # --- E2 queue detectors covering the whole 2496 m approach ---
    for ln in range(3):
        L.append('    <laneAreaDetector id="e2_app_%d" lane="E_app_%d" pos="0.0" endPos="%.1f" '
                 'period="%d" file="e2_app.xml"/>' % (ln, ln, E_APP_LEN - 1.0, DET_PERIOD))
    # --- edgeData ---
    L.append('    <edgeData id="ed" period="%d" file="edgedata.xml" excludeEmpty="false"/>' % DET_PERIOD)
    L.append('</additional>')
    return "\n".join(L) + "\n"


def sumocfg_xml(net_path, route_file, add_file, extra=""):
    return """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="%s"/>
        <route-files value="%s"/>
        <additional-files value="%s"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="%d"/>
        <step-length value="%.2f"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
        <max-depart-delay value="120"/>
        <lateral-resolution value="-1"/>
        <default.speeddev value="0"/>
        <collision.action value="warn"/>
    </processing>
    <report>
        <no-step-log value="true"/>
        <duration-log.statistics value="true"/>
        <xml-validation value="never"/>
    </report>
%s</configuration>
""" % (net_path, route_file, add_file, SIM_END, STEP_LENGTH, extra)
