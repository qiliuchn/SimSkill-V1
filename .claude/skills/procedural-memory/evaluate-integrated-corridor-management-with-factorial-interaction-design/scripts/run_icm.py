#!/usr/bin/env python3
"""
ICM scenario orchestrator. Runs one full corridor scenario via TraCI with any
combination of the four control modules (D=diversion advisory, M=ramp
metering, S=arterial responsive signal plan, V=VSL), a shared "response lag"
that gates all four activations, and a mainline incident (closingLaneReroute).

Everything is driven from a single explicit `activation_time = incident_begin
+ response_lag`, NOT SUMO's built-in continuous rerouting-device timers or
actuated-signal state machines, so the sub-goal-4 lag sweep is a clean,
controlled independent variable shared identically across all four modules.

Writes <run-dir>/result.json with every audited metric sub-goals 2-7 need:
group-decomposed trip stats, D/M/S/V audits, AID-adjacent detector series,
teleport/collision counts, and a queue-tail hard-braking safety proxy.
"""
import argparse
import json
import os
import random
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from demand.gen_demand import build as build_demand_xml  # noqa: E402

DECISION_EDGE = "fwy_eb_5"          # ~1000m lead before interchange-2 off-ramp diverge (fwy_eb_6->fx7),
                                     # giving equipped vehicles time to lane-change before the diverge
DETOUR_TAIL = ["fwy_eb_6", "off_eb_2", "art_eb_3", "on_eb_3a", "on_eb_3b"] + [f"fwy_eb_{i}" for i in range(11, 18)]
METER_TLS = {2: "mtr_eb_2", 3: "mtr_eb_3"}
METER_DOWNSTREAM_STATION = {2: 7, 3: 11}   # mainline segment index just downstream of each merge
METER_RAMP_LANES = {2: ["on_eb_2a_0"], 3: ["on_eb_3a_0"]}
ARTERIAL_SIGNALS = ["ax1", "ax2", "ax3", "ax4", "ax5", "ax6"]
VSL_ZONE_EDGES = ["fwy_eb_7", "fwy_eb_8"]
VSL_DETECTORS = [f"e2_vsl_{i}_{l}" for i in (7, 8) for l in range(3)]
SAFETY_LANES = [f"fwy_eb_8_{l}" for l in range(3)]

# ALINEA parameters
ALINEA_K = 60.0
ALINEA_O_TARGET = 18.0     # % occupancy setpoint (measured range for a merge-turbulence station, see SG3 audit)
ALINEA_R_MIN = 200.0       # veh/h
ALINEA_R_MAX = 1500.0      # veh/h (single-lane ramp)
ALINEA_INTERVAL = 60.0     # s

# VSL speed ladder (m/s) and hysteresis thresholds (occupancy %)
VSL_LEVELS = [29.06, 22.0, 15.0]
VSL_UP = [20.0, 32.0]
VSL_DOWN = [12.0, 22.0]
VSL_MIN_DWELL = 30.0


def seed_hash(seed):
    import hashlib
    return int(hashlib.sha256(f"icm-{seed}".encode()).hexdigest(), 16) % (2**31)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--tls", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--incident-begin", type=float, default=1800)
    ap.add_argument("--incident-duration", type=float, default=1800)
    ap.add_argument("--lanes-blocked", type=int, default=2)
    ap.add_argument("--no-incident", action="store_true")
    ap.add_argument("--sim-end", type=float, default=6300)
    ap.add_argument("--demand-end", type=float, default=4200)
    ap.add_argument("--D", type=int, default=0)
    ap.add_argument("--D-compliance", type=float, default=0.5)
    ap.add_argument("--M", type=int, default=0)
    ap.add_argument("--S", type=int, default=0)
    ap.add_argument("--V", type=int, default=0)
    ap.add_argument("--V-compliance", type=float, default=0.8)
    ap.add_argument("--response-lag", type=float, default=300.0)
    ap.add_argument("--fwy-eb-vph", type=float, default=3650)
    ap.add_argument("--fwy-wb-vph", type=float, default=2800)
    ap.add_argument("--art-eb-vph", type=float, default=500)
    ap.add_argument("--art-wb-vph", type=float, default=500)
    ap.add_argument("--cross-vph", type=float, default=80)
    ap.add_argument("--ramp-vph", type=float, default=90)
    ap.add_argument("--demand-scale", type=float, default=1.0)
    ap.add_argument("--gui", action="store_true")
    args = ap.parse_args()

    rd = os.path.abspath(args.run_dir)
    os.makedirs(rd, exist_ok=True)
    rng = random.Random(seed_hash(args.seed))

    # ---- build demand ----
    demand_path = os.path.join(rd, "demand.rou.xml")

    class DArgs:
        pass
    da = DArgs()
    da.begin, da.end, da.scale = 0, args.demand_end, args.demand_scale
    da.fwy_eb_vph, da.fwy_wb_vph = args.fwy_eb_vph, args.fwy_wb_vph
    da.art_eb_vph, da.art_wb_vph = args.art_eb_vph, args.art_wb_vph
    da.cross_vph, da.ramp_vph = args.cross_vph, args.ramp_vph
    with open(demand_path, "w") as f:
        f.write(build_demand_xml(da))

    # ---- build incident + detectors ----
    add_files = [args.tls]
    if not args.no_incident:
        incident_path = os.path.join(rd, "incident.add.xml")
        end = args.incident_begin + args.incident_duration
        lane_lines = "\n".join(
            f'        <closingLaneReroute id="fwy_eb_9_{i}" disallow="all"/>' for i in range(args.lanes_blocked)
        )
        with open(incident_path, "w") as f:
            f.write(f"""<additional>
    <rerouter id="incident_rerouter" edges="fwy_eb_9">
        <interval begin="{args.incident_begin}" end="{end}">
{lane_lines}
        </interval>
    </rerouter>
</additional>
""")
        add_files.append(incident_path)

    det_path = os.path.join(rd, "detectors.add.xml")
    os.system(f'{sys.executable} "{os.path.join(os.path.dirname(__file__), "build_detectors.py")}" '
              f'--run-dir "{rd}" --out "{det_path}"')
    add_files.append(det_path)

    tripinfo_path = os.path.join(rd, "tripinfo.xml")
    stats_path = os.path.join(rd, "stats.xml")

    activation_time = args.incident_begin + args.response_lag if not args.no_incident else 1e18

    cmd = ["sumo-gui" if args.gui else "sumo",
           "-n", args.net, "-r", demand_path, "-a", ",".join(add_files),
           "--begin", "0", "--end", str(args.sim_end),
           "--step-length", "1.0", "--no-step-log", "true",
           "--time-to-teleport", "300", "--seed", str(args.seed),
           "--tripinfo-output", tripinfo_path, "--tripinfo-output.write-unfinished", "true",
           "--statistic-output", stats_path,
           "--collision.action", "warn", "--collision.mingap-factor", "0"]
    traci.start(cmd)

    # ---- state ----
    diversion_decided = set()
    diverted_ids = set()
    diversion_offered = 0

    meter_state = {j: dict(rate=ALINEA_R_MAX, last_control=-1e9, green_until=0.0,
                            log=[], queue_log=[]) for j in METER_TLS}

    s_switched_at = None

    vsl_orig_speed = {}
    vsl_compliant_ids = set()
    vsl_zone_seen_ids = set()
    vsl_level_history = []
    vsl_current_level = -1
    vsl_last_switch = -1e9

    safety_events = []
    prev_speed = {}

    # origin-insertion delay (vehicles never yet inserted are invisible to
    # tripinfo/departDelay entirely -- see
    # coordinated-ramp-metering-delay-transfer-and-ramp-storage.md). Track the
    # integral of the pending-vehicle count, overall and by demand group.
    origin_delay_veh_s = 0.0
    origin_delay_by_group = {}

    def grp_of_id(vid):
        if vid.startswith("fwyT_"):
            return "fwy_through"
        if vid.startswith("artT_"):
            return "arterial_through"
        return "cross_street_local"

    if args.M:
        for j in METER_TLS:
            traci.trafficlight.setRedYellowGreenState(METER_TLS[j], "G")

    # spillback audit (claim ii/iii): the diversion off-ramp (off_eb_2) and
    # the re-entry on-ramp storage segment (on_eb_3a), tracked unconditionally
    # (not just when M is armed) so D-alone runs can also show whether the
    # off-ramp queue reaches back onto the freeway mainline.
    off_eb_2_len = traci.lane.getLength("off_eb_2_0")
    on_eb_3a_len = traci.lane.getLength("on_eb_3a_0")
    off_eb_2_jam_log = []
    on_eb_3a_jam_log = []

    t = 0.0
    while t < args.sim_end and (traci.simulation.getMinExpectedNumber() > 0 or t < args.demand_end + 60):
        traci.simulationStep()
        t = traci.simulation.getTime()
        armed = t >= activation_time

        if int(t) % 15 == 0:
            off_eb_2_jam_log.append(dict(t=t, jam_m=traci.lanearea.getJamLengthMeters("e2_off_eb_2")))
            on_eb_3a_jam_log.append(dict(t=t, jam_m=traci.lanearea.getJamLengthMeters("e2_on_eb_3a")))

        pending = traci.simulation.getPendingVehicles()
        if pending:
            origin_delay_veh_s += len(pending)
            for vid in pending:
                g = grp_of_id(vid)
                origin_delay_by_group[g] = origin_delay_by_group.get(g, 0.0) + 1.0

        # ---- D: diversion advisory ----
        if args.D and armed:
            for vid in traci.edge.getLastStepVehicleIDs(DECISION_EDGE):
                if not vid.startswith("fwyT_EB"):
                    continue
                if vid in diversion_decided:
                    continue
                diversion_decided.add(vid)
                diversion_offered += 1
                if rng.random() < args.D_compliance:
                    try:
                        traci.vehicle.setRoute(vid, [DECISION_EDGE] + DETOUR_TAIL)
                        diverted_ids.add(vid)
                    except traci.exceptions.TraCIException:
                        pass

        # ---- M: ALINEA ramp metering (interchanges 2 and 3) ----
        if args.M and armed:
            for j, tls_id in METER_TLS.items():
                st = meter_state[j]
                if t - st["last_control"] >= ALINEA_INTERVAL:
                    seg = METER_DOWNSTREAM_STATION[j]
                    occs = []
                    for lane in range(3):
                        lid = f"fwy_eb_{seg}_{lane}"
                        occs.append(traci.lane.getLastStepOccupancy(lid) * 100.0)
                    o_meas = sum(occs) / len(occs)
                    new_rate = st["rate"] + ALINEA_K * (ALINEA_O_TARGET - o_meas)
                    new_rate = max(ALINEA_R_MIN, min(ALINEA_R_MAX, new_rate))
                    st["rate"] = new_rate
                    st["last_control"] = t
                    cycle = 3600.0 / new_rate
                    green_time = min(cycle, 4.0)  # ~one car per green (4s green pulse)
                    st["cycle"] = cycle
                    st["green_time"] = green_time
                    st["log"].append(dict(t=t, rate_vph=new_rate, occ_pct=o_meas))
                # apply one-car-per-green pattern within the current cycle
                cyc = st.get("cycle", 1.0)
                gt = st.get("green_time", 1.0)
                phase_t = (t - st["last_control"]) % cyc if cyc > 0 else 0
                state = "G" if phase_t < gt else "r"
                traci.trafficlight.setRedYellowGreenState(tls_id, state)
            # ramp queue length audit (every step is cheap: 2 lanes)
            if int(t) % 30 == 0:
                for j in METER_TLS:
                    qlens = [traci.lanearea.getJamLengthMeters(f"e2_on_eb_{j}a")]
                    meter_state[j]["queue_log"].append(dict(t=t, jam_m=qlens[0]))

        # ---- S: arterial responsive diversion signal plan ----
        if args.S and armed and s_switched_at is None:
            green_before = {}
            for ax in ARTERIAL_SIGNALS:
                green_before[ax] = traci.trafficlight.getRedYellowGreenState(ax)
                traci.trafficlight.setProgram(ax, "incident")
            s_switched_at = t

        # ---- V: VSL upstream of incident ----
        if args.V:
            occs = []
            for det in VSL_DETECTORS:
                occs.append(traci.lanearea.getLastStepOccupancy(det))
            zone_occ = sum(occs) / len(occs) if occs else 0.0
            if armed:
                level = vsl_current_level
                if t - vsl_last_switch >= VSL_MIN_DWELL:
                    if level < len(VSL_LEVELS) - 1 and zone_occ > VSL_UP[level] if level >= 0 else zone_occ > VSL_UP[0]:
                        level = level + 1
                        vsl_last_switch = t
                    elif level >= 0 and zone_occ < (VSL_DOWN[level - 1] if level > 0 else -1):
                        level = level - 1
                        vsl_last_switch = t
                if level != vsl_current_level:
                    vsl_current_level = level
                    vsl_level_history.append(dict(t=t, level=level))
                if vsl_current_level >= 0:
                    posted = VSL_LEVELS[vsl_current_level]
                    for edge in VSL_ZONE_EDGES:
                        for vid in traci.edge.getLastStepVehicleIDs(edge):
                            vsl_zone_seen_ids.add(vid)
                            if vid not in vsl_orig_speed:
                                vsl_orig_speed[vid] = traci.vehicle.getMaxSpeed(vid)
                                if rng.random() < args.V_compliance:
                                    traci.vehicle.setMaxSpeed(vid, posted)
                                    vsl_compliant_ids.add(vid)
            # restore speed once vehicle leaves the VSL zone (getIDList() called
            # ONCE per step, not per vehicle -- calling it inside the loop was
            # an O(n^2)-per-step bug that made this module far slower than D/M/S)
            if vsl_orig_speed:
                still_present = set(traci.vehicle.getIDList())
                for vid in list(vsl_orig_speed.keys()):
                    if vid not in still_present:
                        vsl_orig_speed.pop(vid, None)
                        continue
                    road = traci.vehicle.getRoadID(vid)
                    if road not in VSL_ZONE_EDGES and vid in vsl_compliant_ids:
                        traci.vehicle.setMaxSpeed(vid, vsl_orig_speed[vid])
                        vsl_orig_speed.pop(vid, None)

        # ---- queue-tail safety proxy: hard-braking EVENTS (onset transitions,
        # not raw per-step samples -- a single multi-second braking maneuver
        # must count once, matching the AID skill's alarm-onset discipline)
        # near the incident's upstream queue front (segment 8, x=3500-4000) ----
        seen_this_step = set()
        for lane in SAFETY_LANES:
            for vid in traci.lane.getLastStepVehicleIDs(lane):
                seen_this_step.add(vid)
                sp = traci.vehicle.getSpeed(vid)
                acc = traci.vehicle.getAcceleration(vid)
                was_braking = prev_speed.get(("brk", vid), False)
                is_braking = acc < -4.0
                if is_braking and not was_braking:
                    safety_events.append(dict(t=t, vid=vid, accel=acc, speed=sp))
                prev_speed[("brk", vid)] = is_braking
        # drop braking-state memory for vehicles that left the zone
        for key in [k for k in prev_speed if k[0] == "brk" and k[1] not in seen_this_step]:
            del prev_speed[key]

    traci.close()

    # ---- parse tripinfo, group by id prefix ----
    def group_of(vid):
        if vid.startswith("fwyT_"):
            return "diverted" if vid in diverted_ids else "fwy_through"
        if vid.startswith("artT_"):
            return "arterial_through"
        if vid.startswith(("crs_", "crsOut_")):
            return "cross_street_local"
        if vid.startswith("rmp_"):
            return "cross_street_local"
        return "other"

    tree = ET.parse(tripinfo_path)
    root = tree.getroot()
    groups = {}
    for ti in root.findall("tripinfo"):
        vid = ti.get("id")
        g = group_of(vid)
        rec = groups.setdefault(g, dict(n=0, duration=0.0, timeLoss=0.0, waitingTime=0.0, departDelay=0.0, routeLength=0.0))
        rec["n"] += 1
        rec["duration"] += float(ti.get("duration"))
        rec["timeLoss"] += float(ti.get("timeLoss"))
        rec["waitingTime"] += float(ti.get("waitingTime"))
        rec["departDelay"] += float(ti.get("departDelay"))
        rec["routeLength"] += float(ti.get("routeLength"))
    for g, rec in groups.items():
        n = rec["n"]
        if n:
            for k in ("duration", "timeLoss", "waitingTime", "departDelay", "routeLength"):
                rec[f"mean_{k}"] = rec[k] / n

    stree = ET.parse(stats_path)
    sroot = stree.getroot()
    veh = sroot.find("vehicles").attrib if sroot.find("vehicles") is not None else {}
    tel = sroot.find("teleports").attrib if sroot.find("teleports") is not None else {}
    saf = sroot.find("safety").attrib if sroot.find("safety") is not None else {}

    # ---- M audit summary ----
    m_audit = {}
    for j, st in meter_state.items():
        rates = [x["rate_vph"] for x in st["log"]]
        occs = [x["occ_pct"] for x in st["log"]]
        jams = [x["jam_m"] for x in st["queue_log"]]
        m_audit[j] = dict(n_intervals=len(rates),
                           mean_rate_vph=sum(rates) / len(rates) if rates else None,
                           min_rate_vph=min(rates) if rates else None,
                           mean_downstream_occ_pct=sum(occs) / len(occs) if occs else None,
                           max_ramp_jam_m=max(jams) if jams else None,
                           mean_ramp_jam_m=sum(jams) / len(jams) if jams else None,
                           armed=bool(args.M))

    result = dict(
        args=vars(args),
        activation_time=activation_time,
        vehicles=veh, teleports=tel, safety=saf,
        groups=groups,
        origin_delay_veh_s=origin_delay_veh_s,
        origin_delay_by_group_veh_s=origin_delay_by_group,
        spillback_audit=dict(
            off_eb_2_lane_length_m=off_eb_2_len,
            off_eb_2_max_jam_m=max((r["jam_m"] for r in off_eb_2_jam_log), default=0.0),
            off_eb_2_max_jam_frac=(max((r["jam_m"] for r in off_eb_2_jam_log), default=0.0) / off_eb_2_len) if off_eb_2_len else None,
            off_eb_2_spillback_onto_mainline=(max((r["jam_m"] for r in off_eb_2_jam_log), default=0.0) >= 0.90 * off_eb_2_len),
            on_eb_3a_lane_length_m=on_eb_3a_len,
            on_eb_3a_max_jam_m=max((r["jam_m"] for r in on_eb_3a_jam_log), default=0.0),
            on_eb_3a_max_jam_frac=(max((r["jam_m"] for r in on_eb_3a_jam_log), default=0.0) / on_eb_3a_len) if on_eb_3a_len else None,
        ),
        D_audit=dict(configured_compliance=args.D_compliance,
                     offered=diversion_offered,
                     diverted=len(diverted_ids),
                     realized_share=(len(diverted_ids) / diversion_offered) if diversion_offered else None),
        M_audit=m_audit,
        S_audit=dict(armed=bool(args.S), switched_at=s_switched_at),
        V_audit=dict(configured_compliance=args.V_compliance,
                     zone_vehicles_seen=len(vsl_zone_seen_ids),
                     compliant_vehicles=len(vsl_compliant_ids),
                     realized_compliance=(len(vsl_compliant_ids) / len(vsl_zone_seen_ids)) if vsl_zone_seen_ids else None,
                     level_history=vsl_level_history),
        safety_proxy=dict(hard_braking_events=len(safety_events),
                          events_sample=safety_events[:50]),
    )
    with open(os.path.join(rd, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("wrote", os.path.join(rd, "result.json"))


if __name__ == "__main__":
    main()
