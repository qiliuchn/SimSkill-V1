#!/usr/bin/env python3
"""
Scenario generator for the BEB electrification study.

Produces, for a given experimental cell:
  * additional file : bus stops (+ pedestrian access), terminal charging berths,
                      depot charger  -- charger COUNT is realised as physically
                      separate chargingStation berths (SUMO's chargingStation
                      `power` is per-vehicle, NOT a shared station budget, and
                      `totalPower` segfaults with 2 simultaneous vehicles in 1.27.1)
  * bus route file  : N buses x C round-trip cycles (multi-cycle vehicle block)
  * car route file  : background traffic (CRN: identical for all cells at a seed)
  * person file     : boarding/alighting demand (CRN: identical for all cells at a seed)
"""
import os, math, random, json
import xml.etree.ElementTree as ET

import build_net as BN

# ---------------------------------------------------------------- service design
# Timetable is built so that (a) each vehicle block is a 5.5 h multi-cycle block and
# (b) nominal single-charger berth utilisation is 270/480 = 0.56 -- i.e. a MEAN-based
# charger sizing says one charger per terminal is enough.  H4 tests whether that holds.
T0       = 1800.0    # first westbound-terminal departure
HEADWAY  = 480.0     # 8 min
RUN_EB   = 1560.0    # 26 min scheduled eastbound (uphill) running time
RUN_WB   = 1260.0    # 21 min scheduled westbound (downhill) running time
LAYOVER  = 270.0     # 4.5 min scheduled terminal layover, each end
CYCLE_T  = RUN_EB + LAYOVER + RUN_WB + LAYOVER      # 3360 s = 56 min
NBUS     = 7         # CYCLE_T / HEADWAY = 7  (odd -> berth assignment rotates over cycles)
NCYC     = 6         # round trips per block -> 5.6 h block, ~125 km
SIM_END  = 26000.0

DOOR_DWELL   = 5.0   # s fixed door/dead time per en-route stop
MIN_LAYOVER  = 60.0  # s minimum terminal dwell even when late

BERTH_START, BERTH_END = 300.0, 318.0
CS_START, CS_END       = 296.0, 320.0
DEPOT_START, DEPOT_END = 240.0, 318.0
DEPOT_CS_START, DEPOT_CS_END = 236.0, 320.0

# ---------------------------------------------------------------- helpers
def stop_defs():
    """Return list of (stop_id, edge, pos, direction, x) for the 12 en-route stops
    in each direction, in travel order."""
    out = []
    for k, x in enumerate(BN.STOP_X):
        e, p = BN.edge_for_x(x, "EB")
        out.append((f"bs_EB_{k:02d}", e, p, "EB", x))
    for k, x in enumerate(reversed(BN.STOP_X)):
        e, p = BN.edge_for_x(x, "WB")
        out.append((f"bs_WB_{k:02d}", e, p, "WB", x))
    return out


def write_additional(path, n_term_chargers, term_power_w, depot_power_w,
                     served_stop_stride=1, cs_efficiency=0.95):
    S = stop_defs()
    L = ['<additional>']
    for sid, e, p, d, x in S:
        L.append(f'  <busStop id="{sid}" lane="{e}_1" startPos="{p:.1f}" endPos="{p + BN.STOP_LEN:.1f}" '
                 f'friendlyPos="true" lines="BEB" personCapacity="200">')
        L.append(f'    <access lane="{e}_0" pos="{p + BN.STOP_LEN / 2:.1f}" friendlyPos="true"/>')
        L.append('  </busStop>')
    # terminal layover berths (always 2 physical berths at each terminal)
    for term, edge, nl in (("TW", "TW_IN", 3), ("TE", "TE_IN", 2)):
        for b in (0, 1):
            L.append(f'  <busStop id="bs_{term}_b{b}" lane="{edge}_{b}" '
                     f'startPos="{BERTH_START}" endPos="{BERTH_END}" friendlyPos="true"/>')
            if b < n_term_chargers:
                L.append(f'  <chargingStation id="cs_{term}_{b}" lane="{edge}_{b}" '
                         f'startPos="{CS_START}" endPos="{CS_END}" power="{term_power_w}" '
                         f'efficiency="{cs_efficiency}" chargeDelay="0" chargeInTransit="false"/>')
    # depot berth (west terminal, third lane) + low-power depot charger
    L.append(f'  <busStop id="bs_TW_depot" lane="TW_IN_2" startPos="{DEPOT_START}" '
             f'endPos="{DEPOT_END}" friendlyPos="true"/>')
    L.append(f'  <chargingStation id="cs_depot" lane="TW_IN_2" startPos="{DEPOT_CS_START}" '
             f'endPos="{DEPOT_CS_END}" power="{depot_power_w}" efficiency="{cs_efficiency}" '
             f'chargeDelay="0" chargeInTransit="false"/>')
    L.append('</additional>')
    open(path, "w").write("\n".join(L))
    return S


# ---------------------------------------------------------------- vehicle types
def beb_vtype(cap_kwh, init_frac, aux_w, recup, mass_kg, max_power_w=240000):
    return f"""  <vType id="beb" vClass="bus" length="12.0" width="2.55" minGap="2.5"
         accel="1.0" decel="2.5" emergencyDecel="4.0" maxSpeed="16.7" sigma="0.3"
         mass="{mass_kg:.0f}" emissionClass="Energy/unknown"
         personCapacity="70" boardingDuration="2.0" speedDev="0.05">
    <param key="has.battery.device" value="true"/>
    <param key="device.battery.capacity" value="{cap_kwh * 1000.0:.0f}"/>
    <param key="device.battery.chargeLevel" value="{cap_kwh * 1000.0 * init_frac:.0f}"/>
    <param key="maximumPower" value="{max_power_w}"/>
    <param key="frontSurfaceArea" value="8.0"/>
    <param key="airDragCoefficient" value="0.60"/>
    <param key="rollDragCoefficient" value="0.008"/>
    <param key="radialDragCoefficient" value="0.5"/>
    <param key="rotatingMass" value="1000"/>
    <param key="constantPowerIntake" value="{aux_w}"/>
    <param key="propulsionEfficiency" value="0.90"/>
    <param key="recuperationEfficiency" value="{recup}"/>
    <param key="stoppingThreshold" value="0.1"/>
  </vType>"""


CAR_VTYPE = """  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"
         decel="4.5" sigma="0.5" maxSpeed="16.7" speedDev="0.10" tau="1.2"/>"""


# ---------------------------------------------------------------- bus blocks
def _berth(n_arr, n_chargers, policy):
    """Berth (0 or 1) for the n-th pull-in at a terminal.

    n_chargers == 2 : both berths are electrified -> alternate, no contention.
    n_chargers == 1 and policy == "skip"  : still alternate berths, but only berth 0
        is electrified -> every second pull-in gets NO charge (session truncation).
    n_chargers == 1 and policy == "queue" : every bus is sent to the single electrified
        berth -> physical queueing behind an occupied charger (departure delay).
    n_chargers == 0 : depot-only; berths are plain layover berths.
    """
    if n_chargers >= 2:
        return n_arr % 2
    if n_chargers == 1:
        return 0 if policy == "queue" else n_arr % 2
    return n_arr % 2


def bus_route_edges():
    eb = ["TW_OUT"] + [f"EB_{i}" for i in range(7)] + ["TE_IN"]
    wb = ["TE_OUT"] + [f"WB_{i}" for i in range(6, -1, -1)] + ["TW_IN"]
    return eb, wb


def write_buses(path, cap_kwh, init_frac, aux_w, recup, mass_kg,
                n_term_chargers, stop_stride=1, midday_depot=None,
                nbus=NBUS, ncyc=NCYC, max_power_w=240000, charger_policy="skip"):
    """midday_depot: None, or dict(plan={bus_id: cycle}, duration=s) -> the listed buses
    take a depot layover (berth bs_TW_depot, low-power charger) instead of the normal
    terminal berth at the end of the given round-trip, staying `duration` seconds.
    Every stop after that point keeps its original `until`, so the bus simply runs
    `duration` seconds behind for the rest of its block -> an explicit service gap."""
    S = stop_defs()
    eb_stops = [s for s in S if s[3] == "EB"][::stop_stride]
    wb_stops = [s for s in S if s[3] == "WB"][::stop_stride]
    eb_edges, wb_edges = bus_route_edges()
    L = ['<routes>', beb_vtype(cap_kwh, init_frac, aux_w, recup, mass_kg, max_power_w)]
    sched = {}
    for b in range(nbus):
        t_start = T0 + b * HEADWAY
        edges, stops = [], []
        for c in range(ncyc):
            edges += eb_edges + wb_edges
            for sid, e, p, d, x in eb_stops:
                stops.append(f'    <stop busStop="{sid}" duration="{DOOR_DWELL:.0f}"/>')
            # east terminal layover.  Berth index follows the GLOBAL ARRIVAL ORDER
            # (n = b + c*nbus) so that consecutive pull-ins alternate berths.
            n_arr = b + c * nbus
            berth = _berth(n_arr, n_term_chargers, charger_policy)
            dep_e = t_start + c * CYCLE_T + RUN_EB + LAYOVER
            stops.append(f'    <stop busStop="bs_TE_b{berth}" duration="{MIN_LAYOVER:.0f}" '
                         f'until="{dep_e:.0f}"/>')
            sched[(b, c, "E")] = dep_e
            for sid, e, p, d, x in wb_stops:
                stops.append(f'    <stop busStop="{sid}" duration="{DOOR_DWELL:.0f}"/>')
            # west terminal layover (start of the next cycle)
            dep_w = t_start + (c + 1) * CYCLE_T
            use_depot = (midday_depot is not None
                         and midday_depot["plan"].get(str(b), midday_depot["plan"].get(b)) == c)
            if use_depot:
                dur = midday_depot["duration"]
                stops.append(f'    <stop busStop="bs_TW_depot" duration="{dur:.0f}" '
                             f'until="{dep_w + dur:.0f}"/>')
                sched[(b, c, "W")] = dep_w + dur
            else:
                berth = _berth(b + (c + 1) * nbus, n_term_chargers, charger_policy)
                stops.append(f'    <stop busStop="bs_TW_b{berth}" duration="{MIN_LAYOVER:.0f}" '
                             f'until="{dep_w:.0f}"/>')
                sched[(b, c, "W")] = dep_w
        L.append(f'  <vehicle id="bus_{b}" type="beb" line="BEB" depart="{t_start:.0f}" '
                 f'departLane="0" departPos="0" departSpeed="0">')
        L.append(f'    <route edges="{" ".join(edges)}"/>')
        L += stops
        L.append('  </vehicle>')
    L.append('</routes>')
    open(path, "w").write("\n".join(L))
    return {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in sched.items()}


# ---------------------------------------------------------------- background cars
CAR_PROFILE = [   # (begin, end, EB veh/h, WB veh/h)
    (0.0,      3600.0,   900, 700),
    (3600.0,  10800.0,  1750, 850),
    (10800.0, 18000.0,  1050, 950),
    (18000.0, 26000.0,   800, 700),
]
CROSS_VPH = 210      # per approach, per direction


def write_cars(path, seed):
    eb = " ".join(f"EB_{i}" for i in range(7))
    wb = " ".join(f"WB_{i}" for i in range(6, -1, -1))
    L = ['<routes>', CAR_VTYPE,
         f'  <route id="r_eb" edges="{eb}"/>',
         f'  <route id="r_wb" edges="{wb}"/>',
         '  <route id="r_eb_turnN" edges="EB_0 EB_1 EB_2 J3_N3"/>',
         '  <route id="r_wb_turnS" edges="WB_6 WB_5 J5_S5"/>']
    for i in range(1, 7):
        L.append(f'  <route id="r_ns{i}" edges="N{i}_J{i} J{i}_S{i}"/>')
        L.append(f'  <route id="r_sn{i}" edges="S{i}_J{i} J{i}_N{i}"/>')
    flows = []   # (begin, xml)
    for (b, e, veb, vwb) in CAR_PROFILE:
        for rid, vph in (("r_eb", veb), ("r_wb", vwb),
                         ("r_eb_turnN", int(veb * 0.10)), ("r_wb_turnS", int(vwb * 0.10))):
            flows.append((b, rid, b, e, vph))
    for i in range(1, 7):
        for rid in (f"r_ns{i}", f"r_sn{i}"):
            flows.append((0.0, rid, 0.0, SIM_END, CROSS_VPH))
    # SUMO ignores flows that are out of departure-time order -> sort by begin.
    flows.sort(key=lambda f: (f[0], f[1]))
    for k, (_, rid, b, e, vph) in enumerate(flows):
        L.append(f'  <flow id="f{k}" type="car" route="{rid}" begin="{b:.0f}" end="{e:.0f}" '
                 f'vehsPerHour="{vph}" departLane="best" departSpeed="max"/>')
    L.append('</routes>')
    open(path, "w").write("\n".join(L))


# ---------------------------------------------------------------- person demand
def write_persons(path, seed, n_persons=2400):
    rng = random.Random(90000 + seed)
    S = stop_defs()
    eb = [s for s in S if s[3] == "EB"]
    wb = [s for s in S if s[3] == "WB"]
    L = ['<routes>']
    recs = []
    for n in range(n_persons):
        # temporal profile: peak between 3600 and 10800 s
        u = rng.random()
        if u < 0.50:
            t = rng.uniform(3600, 10800)
        elif u < 0.75:
            t = rng.uniform(1500, 3600)
        else:
            t = rng.uniform(10800, 22000)
        # directional split: eastbound dominant in the peak
        p_eb = 0.62 if 3600 <= t < 10800 else 0.48
        chain = eb if rng.random() < p_eb else wb
        i = rng.randrange(0, len(chain) - 2)
        j = min(len(chain) - 1, i + 1 + int(rng.expovariate(1 / 3.2)))
        if j <= i:
            j = i + 1
        o_sid, o_e, o_p, o_d, o_x = chain[i]
        d_sid, d_e, d_p, d_d, d_x = chain[j]
        dep_pos = max(2.0, o_p - rng.uniform(40, 220))
        arr_pos = min(1000.0, d_p + rng.uniform(30, 180))
        recs.append((t, n, o_e, o_sid, d_sid, d_e, dep_pos, arr_pos))
    recs.sort()
    for t, n, o_e, o_sid, d_sid, d_e, dep_pos, arr_pos in recs:
        L.append(f'  <person id="pax_{n}" depart="{t:.1f}" departPos="{dep_pos:.1f}">')
        L.append(f'    <walk from="{o_e}" busStop="{o_sid}"/>')
        L.append(f'    <ride busStop="{d_sid}" lines="BEB"/>')
        L.append(f'    <walk busStop="{d_sid}" to="{d_e}"/>')
        L.append('  </person>')
    L.append('</routes>')
    open(path, "w").write("\n".join(L))
    return len(recs)
