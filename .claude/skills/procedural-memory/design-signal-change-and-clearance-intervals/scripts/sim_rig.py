"""Simulation rig: signal-plan authoring, demand, and the TraCI yellow-onset decision log.

Everything that touches SUMO for the main study goes through `run_cell()`.
"""
import csv
import json
import os
import shutil
import xml.etree.ElementTree as ET

from common import SUMO, add_tools_to_path, last_summary_value

add_tools_to_path()
import traci  # noqa: E402
import traci.constants as tc  # noqa: E402

GROUPS = {"NS": ("N", "S"), "EW": ("E", "W")}

# ---------------------------------------------------------------- signal plan


def tls_states(meta, cycle, yellow, allred, greens=None):
    """Build the six-phase state strings from the COMPILED net's link map.

    Phase order (verified downstream against the program SUMO actually loads):
      0 NS green | 1 NS yellow | 2 all-red | 3 EW green | 4 EW yellow | 5 all-red
    Cycle length is held CONSTANT while yellow/all-red are swept, so the green
    time lost to a longer intergreen is charged honestly against capacity.
    """
    n = meta["n_tls_links"]
    by_arm = meta["links_by_arm"]
    idx = {g: sorted(sum([by_arm[a] for a in arms], [])) for g, arms in GROUPS.items()}
    total_inter = 2 * (yellow + allred)
    if greens is None:
        g = (cycle - total_inter) / 2.0
        greens = (g, g)
    assert greens[0] > 0 and greens[1] > 0, "intergreen exceeds cycle"

    def mk(green_group, ch):
        s = ["r"] * n
        for li in idx[green_group]:
            s[li] = ch
        return "".join(s)

    allr = "r" * n
    phases = [
        dict(dur=greens[0], state=mk("NS", "G"), name="NS_green"),
        dict(dur=yellow, state=mk("NS", "y"), name="NS_yellow"),
        dict(dur=allred, state=allr, name="allred_1"),
        dict(dur=greens[1], state=mk("EW", "G"), name="EW_green"),
        dict(dur=yellow, state=mk("EW", "y"), name="EW_yellow"),
        dict(dur=allred, state=allr, name="allred_2"),
    ]
    return [p for p in phases if p["dur"] > 0], idx


def tls_xml(meta, cycle, yellow, allred, tls_type="static", minDur=None, maxDur=None,
            greens=None, params=None):
    phases, idx = tls_states(meta, cycle, yellow, allred, greens)
    out = ['  <tlLogic id="C" type="%s" programID="custom" offset="0">' % tls_type]
    for p in phases:
        extra = ""
        if tls_type in ("actuated", "delay_based") and p["name"].endswith("green"):
            extra = ' minDur="%.2f" maxDur="%.2f"' % (
                minDur if minDur is not None else 5.0,
                maxDur if maxDur is not None else p["dur"] * 1.6)
        out.append('    <phase duration="%.2f" state="%s" name="%s"%s/>'
                   % (p["dur"], p["state"], p["name"], extra))
    for k, v in (params or {}).items():
        out.append('    <param key="%s" value="%s"/>' % (k, v))
    out.append("  </tlLogic>")
    return "\n".join(out), phases, idx


# ---------------------------------------------------------------- vehicle types

CAR = dict(id="car", vClass="passenger", length="5.0", minGap="2.5", accel="2.6",
           decel="4.5", emergencyDecel="9.0", sigma="0.5", speedDev="0.10", tau="1.0",
           carFollowModel="Krauss", maxSpeed="40.0", color="1,1,0")
TRUCK = dict(id="truck", vClass="truck", length="12.0", minGap="2.5", accel="1.3",
             decel="3.5", emergencyDecel="5.0", sigma="0.5", speedDev="0.05", tau="1.4",
             carFollowModel="Krauss", maxSpeed="25.0", color="0.6,0.6,1")

SSM_PARAMS = {
    "has.ssm.device": "true",
    "device.ssm.measures": "TTC DRAC PET BR MDRAC",
    "device.ssm.thresholds": "3.0 3.0 3.0 0.0 3.4",
    "device.ssm.range": "60.0",
    "device.ssm.extratime": "6.0",
    "device.ssm.mdrac.prt": "1.0",
    "device.ssm.trajectories": "false",
}


def _vt_block(d, prob=None, ssm=True):
    a = " ".join('%s="%s"' % (k, v) for k, v in d.items())
    if prob is not None:
        a += ' probability="%.6f"' % prob
    lines = ["    <vType %s>" % a]
    if ssm:
        for k, v in SSM_PARAMS.items():
            lines.append('      <param key="%s" value="%s"/>' % (k, v))
    lines.append("    </vType>")
    return "\n".join(lines)


def vtype_xml(truck_share=0.0, jm=None, ssm=True, car_over=None, truck_over=None,
              noncomp_share=0.0, noncomp_jm=None):
    """Fleet = {car, truck} x {compliant, non-compliant}, as a vTypeDistribution.

    Non-compliance is modelled ONLY through vType junction-model parameters
    (`jmDriveAfterRedTime` / `jmDriveAfterYellowTime`), applied to a SHARE of the fleet --
    never by overriding SUMO's decision logic from TraCI.
    """
    jm = jm or {}
    noncomp_jm = noncomp_jm or {}
    car = dict(CAR)
    car.update(car_over or {})
    truck = dict(TRUCK)
    truck.update(truck_over or {})
    for d in (car, truck):
        d.update({k: str(v) for k, v in jm.items()})

    members = []
    ts, ns = truck_share, noncomp_share
    for is_truck in (False, True):
        base = dict(truck if is_truck else car)
        pveh = ts if is_truck else (1.0 - ts)
        if pveh <= 0:
            continue
        for nc in (False, True):
            p = pveh * (ns if nc else 1.0 - ns)
            if p <= 0:
                continue
            d = dict(base)
            d["id"] = ("truck" if is_truck else "car") + ("_nc" if nc else "")
            if nc:
                d.update({k: str(v) for k, v in noncomp_jm.items()})
                d["color"] = "1,0,0"
            members.append((d, p))
    if len(members) == 1:
        return _vt_block(members[0][0], None, ssm), members[0][0]["id"]
    body = "\n".join(_vt_block(d, p, ssm) for d, p in members)
    return '  <vTypeDistribution id="fleet">\n%s\n  </vTypeDistribution>' % body, "fleet"


def routes_xml(veh_per_hour_per_approach, end, truck_share=0.0, jm=None, ssm=True,
               car_over=None, truck_over=None, approaches=("N", "E", "S", "W"),
               per_approach=None, noncomp_share=0.0, noncomp_jm=None):
    opp = {"N": "S", "S": "N", "E": "W", "W": "E"}
    vt, tid = vtype_xml(truck_share, jm, ssm, car_over, truck_over, noncomp_share, noncomp_jm)
    lines = ["<routes>", vt]
    for a in approaches:
        lines.append('  <route id="r_%s" edges="in_%s out_%s"/>' % (a, a, opp[a]))
    for a in approaches:
        vph = (per_approach or {}).get(a, veh_per_hour_per_approach)
        prob = vph / 3600.0
        lines.append('  <flow id="f_%s" type="%s" route="r_%s" begin="0" end="%.1f" '
                     'probability="%.6f" departSpeed="max" departLane="random" '
                     'departPos="base"/>' % (a, tid, a, end, min(prob, 0.999)))
    lines.append("</routes>")
    return "\n".join(lines)


def detectors_xml(meta, lanes):
    """Instant induction loops on the stop line (rear-bumper crossings) for headway/lost time."""
    out = []
    for a in ("N", "E", "S", "W"):
        for i in range(lanes):
            lid = "in_%s_%d" % (a, i)
            out.append('  <instantInductionLoop id="il_%s" lane="%s" pos="-0.20" '
                       'friendlyPos="true" file="instant.xml"/>' % (lid, lid))
    return "\n".join(out)


# ---------------------------------------------------------------- run one cell

def write_inputs(rundir, meta, cfg):
    os.makedirs(rundir, exist_ok=True)
    tls, phases, idx = tls_xml(meta, cfg["cycle"], cfg["yellow"], cfg["allred"],
                               cfg.get("tls_type", "static"), cfg.get("minDur"),
                               cfg.get("maxDur"), cfg.get("greens"), cfg.get("tls_params"))
    add = ["<additional>", tls]
    if cfg.get("detectors", True):
        add.append(detectors_xml(meta, meta["lanes"]))
    add.append("</additional>")
    add_p = os.path.join(rundir, "extra.add.xml")
    open(add_p, "w").write("\n".join(add) + "\n")

    rou_p = os.path.join(rundir, "demand.rou.xml")
    open(rou_p, "w").write(routes_xml(cfg["vph"], cfg["demand_end"], cfg.get("truck_share", 0.0),
                                      cfg.get("jm"), cfg.get("ssm", True),
                                      cfg.get("car_over"), cfg.get("truck_over"),
                                      per_approach=cfg.get("per_approach"),
                                      noncomp_share=cfg.get("noncomp_share", 0.0),
                                      noncomp_jm=cfg.get("noncomp_jm")) + "\n")
    json.dump(dict(phases=phases, group_links=idx), open(os.path.join(rundir, "plan.json"), "w"),
              indent=2)
    return add_p, rou_p, phases, idx


def sumo_cmd(rundir, meta, cfg, add_p, rou_p):
    cmd = [SUMO, "-n", meta["net"], "-r", rou_p, "-a", add_p,
           "--step-length", str(cfg.get("step_length", 0.1)),
           "--begin", "0", "--end", str(cfg["sim_end"]),
           "--seed", str(cfg["seed"]),
           "--time-to-teleport", str(cfg.get("ttt", 300)),
           "--collision.action", "warn",
           "--collision.check-junctions", "true",
           "--collision-output", os.path.join(rundir, "collisions.xml"),
           "--tripinfo-output", os.path.join(rundir, "tripinfo.xml"),
           "--summary-output", os.path.join(rundir, "summary.xml"),
           "--summary-output.period", "1",
           "--tripinfo-output.write-unfinished", "true",
           "--statistic-output", os.path.join(rundir, "stats.xml"),
           "--duration-log.statistics", "true",
           # Integration method is pinned for EVERY arm. SUMO silently switches to ballistic
           # when actionStepLength > step-length ("Setting it now to avoid collisions"), which
           # would otherwise confound the ITE (actionStepLength=1.0) arm against the DEF arm.
           "--step-method.ballistic", str(cfg.get("ballistic", True)).lower(),
           "--no-step-log", "true", "--no-warnings", "false",
           "--error-log", os.path.join(rundir, "sumo.err"),
           "--waiting-time-memory", "10000"]
    if cfg.get("ssm", True):
        cmd += ["--device.ssm.file", os.path.join(rundir, "ssm.xml")]
    if cfg.get("extra_args"):
        cmd += list(cfg["extra_args"])
    return cmd


HARD_BRAKE = 3.0  # m/s^2, "hard braking" threshold (naturalistic-driving convention)
SEVERE_BRAKE = 4.5


def run_cell(rundir, meta, cfg):
    """Run one simulation cell and build the per-vehicle yellow-onset decision log."""
    add_p, rou_p, phases, idx = write_inputs(rundir, meta, cfg)
    cmd = sumo_cmd(rundir, meta, cfg, add_p, rou_p)
    dt = float(cfg.get("step_length", 0.1))
    warmup = float(cfg.get("warmup", 240.0))
    lanes = meta["lanes"]

    # lane -> controlled link index, and lane -> length, from the compiled net
    link_of_lane = {}
    for li_s, d in meta["links"].items():
        link_of_lane["%s_%d" % (d["from_edge"], d["from_lane"])] = int(li_s)
    lane_len = {k: v for k, v in meta["approach_lane_length"].items()}
    approach_lanes = sorted(link_of_lane.keys())

    # internal (junction) lanes, grouped by the movement's approach arm -> for jPET
    internal_group = {}
    for li_s, d in meta["links"].items():
        via = d["via"]
        arm = d["from_edge"].split("_")[1]
        grp = "NS" if arm in ("N", "S") else "EW"
        if via:
            internal_group[via] = grp

    traci.start(cmd, label=os.path.basename(rundir))
    c = traci.getConnection(os.path.basename(rundir))
    # activate the hand-authored plan before the first step
    c.trafficlight.setProgram("C", "custom")
    c.trafficlight.setPhase("C", 0)
    assert c.trafficlight.getProgram("C") == "custom"
    for ln in approach_lanes:
        c.lane.subscribe(ln, [tc.LAST_STEP_VEHICLE_ID_LIST])
    for ln in internal_group:
        c.lane.subscribe(ln, [tc.LAST_STEP_VEHICLE_ID_LIST])
    junc = {}   # vehID -> [group, t_in, t_last_seen, lane]
    junc_done = []
    resp_window = float(cfg.get("resp_window", 6.0))

    records = []
    tracking = {}
    prev_state = None
    phase_trace = []
    tls_prog_dump = None
    green_end_events = []
    t = 0.0
    end = float(cfg["sim_end"])
    try:
        if tls_prog_dump is None:
            logics = c.trafficlight.getAllProgramLogics("C")
            tls_prog_dump = [dict(programID=l.programID, type=l.type,
                                  phases=[dict(duration=p.duration, state=p.state,
                                               minDur=p.minDur, maxDur=p.maxDur,
                                               name=p.name) for p in l.phases])
                             for l in logics]
        while t < end:
            c.simulationStep()
            t = c.simulation.getTime()
            state = c.trafficlight.getRedYellowGreenState("C")
            ph = c.trafficlight.getPhase("C")
            if not phase_trace or phase_trace[-1][1] != ph:
                phase_trace.append((round(t, 2), ph, state))

            lsub = c.lane.getAllSubscriptionResults()

            # ---- junction occupancy -> right-angle exposure (jPET) ----
            seen_now = set()
            for iln, grp in internal_group.items():
                for vid in lsub.get(iln, {}).get(tc.LAST_STEP_VEHICLE_ID_LIST, ()):
                    seen_now.add(vid)
                    if vid in junc:
                        junc[vid][2] = t
                    else:
                        junc[vid] = [grp, t, t, iln]
            for vid in [v for v in junc if v not in seen_now]:
                grp, tin, tlast, iln = junc.pop(vid)
                if tin >= warmup:
                    junc_done.append((grp, tin, tlast, vid))

            if prev_state is not None:
                for ln, li in link_of_lane.items():
                    was_g = prev_state[li] in "gG"
                    now_y = state[li] in "yY"
                    if was_g and now_y and t >= warmup:
                        green_end_events.append((round(t, 2), ln))
                        vids = lsub.get(ln, {}).get(tc.LAST_STEP_VEHICLE_ID_LIST, ())
                        for vid in vids:
                            if vid in tracking:
                                continue
                            try:
                                pos = c.vehicle.getLanePosition(vid)
                                sp = c.vehicle.getSpeed(vid)
                                vt = c.vehicle.getTypeID(vid)
                            except traci.TraCIException:
                                continue
                            d0 = lane_len[ln] - pos
                            if d0 < -1:
                                continue
                            tracking[vid] = dict(
                                veh=vid, vtype=vt, lane=ln, link=li, t_onset=round(t, 2),
                                dist0=round(d0, 3), speed0=round(sp, 4),
                                ttsl=round(d0 / sp, 3) if sp > 0.05 else None,
                                vprev=sp, maxdecel=0.0, maxdecel_resp=0.0, minspeed=sp, stopped=0,
                                stop_dist=None, t_stop=None, cross_t=None,
                                cross_state=None, resolved=None, n_step=0)
                            c.vehicle.subscribe(vid, [tc.VAR_SPEED, tc.VAR_ROAD_ID,
                                                      tc.VAR_LANEPOSITION])

            if tracking:
                vsub = c.vehicle.getAllSubscriptionResults()
                alive = set(vsub.keys())
                for vid, r in list(tracking.items()):
                    li = r["link"]
                    if vid not in alive:
                        # left the network entirely between observations
                        r["resolved"] = r["resolved"] or "GONE"
                        records.append(finish(r))
                        del tracking[vid]
                        continue
                    s = vsub[vid]
                    sp = s[tc.VAR_SPEED]
                    road = s[tc.VAR_ROAD_ID]
                    dec = (r["vprev"] - sp) / dt
                    if dec > r["maxdecel"]:
                        r["maxdecel"] = dec
                    # the RESPONSE-window peak deceleration: only braking attributable to the
                    # yellow itself, not to joining a queue 20 s later on the same red.
                    if (t - r["t_onset"]) <= resp_window and dec > r["maxdecel_resp"]:
                        r["maxdecel_resp"] = dec
                    r["minspeed"] = min(r["minspeed"], sp)
                    r["vprev"] = sp
                    r["n_step"] += 1
                    approach_edge = r["lane"].rsplit("_", 1)[0]
                    if road != approach_edge:
                        r["cross_t"] = round(t, 2)
                        r["cross_state"] = state[li]
                        ch = state[li]
                        if ch in "gG":
                            r["resolved"] = "CROSS_GREEN"
                        elif ch in "yY":
                            r["resolved"] = "CLEAR_YELLOW"
                        else:
                            r["resolved"] = "RED_ENTRY"
                        r["red_elapsed"] = round(t - r["t_onset"] - cfg["yellow"], 2)
                        try:
                            c.vehicle.unsubscribe(vid)
                        except traci.TraCIException:
                            pass
                        records.append(finish(r))
                        del tracking[vid]
                        continue
                    if sp < 0.1 and not r["stopped"]:
                        r["stopped"] = 1
                        r["stop_dist"] = round(lane_len[r["lane"]] - s[tc.VAR_LANEPOSITION], 3)
                        r["t_stop"] = round(t, 2)
                    if state[li] in "gG" and r["t_onset"] < t:
                        # the movement got green again: this vehicle did not go on yellow
                        r["resolved"] = "STOPPED" if r["stopped"] else "SLOWED_NO_STOP"
                        try:
                            c.vehicle.unsubscribe(vid)
                        except traci.TraCIException:
                            pass
                        records.append(finish(r))
                        del tracking[vid]
            prev_state = state
    finally:
        for vid, r in tracking.items():
            r["resolved"] = r["resolved"] or "UNRESOLVED_AT_END"
            records.append(finish(r))
        try:
            c.close()
        except Exception:
            pass

    # ---- right-angle exposure: junction-level PET between conflicting streams ----
    junc_done.sort(key=lambda x: x[1])
    jpets = []
    overlaps = 0
    for i, (g1, tin1, tout1, v1) in enumerate(junc_done):
        for j in range(i + 1, len(junc_done)):
            g2, tin2, tout2, v2 = junc_done[j]
            if tin2 - tout1 > 12.0:
                break
            if g1 == g2:
                continue
            gap = tin2 - tout1     # >0: sequential; <=0: both inside the junction together
            if gap <= 0:
                overlaps += 1
            if gap < 12.0:
                jpets.append(round(gap, 3))
    json.dump(dict(jpet=jpets, n_overlap=overlaps, n_junction_passages=len(junc_done)),
              open(os.path.join(rundir, "jpet.json"), "w"))

    log_p = os.path.join(rundir, "decision_log.csv")
    cols = ["veh", "vtype", "lane", "link", "t_onset", "dist0", "speed0", "ttsl",
            "maxdecel", "maxdecel_resp", "minspeed", "stopped", "stop_dist", "t_stop",
            "cross_t", "cross_state", "red_elapsed", "resolved", "outcome", "n_step"]
    with open(log_p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)
    json.dump(dict(phase_trace=phase_trace[:400], n_phase_changes=len(phase_trace),
                   loaded_program=tls_prog_dump, n_green_end_events=len(green_end_events),
                   authored_phases=phases, group_links=idx),
              open(os.path.join(rundir, "tls_verify.json"), "w"), indent=2)
    return log_p, records


def finish(r):
    r = dict(r)
    r.pop("vprev", None)
    r["maxdecel"] = round(r["maxdecel"], 4)
    r["maxdecel_resp"] = round(r.get("maxdecel_resp", 0.0), 4)
    r["minspeed"] = round(r["minspeed"], 4)
    res = r.get("resolved")
    md = r["maxdecel_resp"]     # response-window peak deceleration drives the classification
    if res == "RED_ENTRY":
        r["outcome"] = "RED_RUN"
    elif res == "CLEAR_YELLOW":
        r["outcome"] = "CLEARED_ON_YELLOW"
    elif res == "CROSS_GREEN":
        r["outcome"] = "CROSSED_ON_GREEN"
    elif res in ("STOPPED", "SLOWED_NO_STOP"):
        if md >= SEVERE_BRAKE:
            r["outcome"] = "STOPPED_SEVERE"
        elif md >= HARD_BRAKE:
            r["outcome"] = "STOPPED_HARD"
        else:
            r["outcome"] = "STOPPED_CLEAN"
        if res == "SLOWED_NO_STOP":
            r["outcome"] += "_NOSTOP"
    else:
        r["outcome"] = res
    return r


# ---------------------------------------------------------------- post metrics

def read_metrics(rundir):
    m = {}
    # tripinfo is written with --tripinfo-output.write-unfinished, so vehicles still in the
    # network at the horizon appear with arrival="-1". Completed and still-running are counted
    # and reported SEPARATELY; the headline means are over completed trips only, and a
    # censoring-robust mean over ALL loaded vehicles is reported alongside.
    tp = os.path.join(rundir, "tripinfo.xml")
    dur = tl = wt = 0.0
    dur_all = tl_all = 0.0
    n = 0
    n_unf = 0
    trucks = 0
    trucks_nc = 0
    if os.path.exists(tp):
        try:
            for _, el in ET.iterparse(tp, events=("end",)):
                if el.tag == "tripinfo":
                    arr = float(el.get("arrival", -1))
                    d = float(el.get("duration"))
                    l = float(el.get("timeLoss"))
                    dur_all += d
                    tl_all += l
                    if arr < 0:
                        n_unf += 1
                    else:
                        n += 1
                        dur += d
                        tl += l
                        wt += float(el.get("waitingTime"))
                    vt = el.get("vType") or ""
                    if vt.startswith("truck"):
                        trucks += 1
                    if vt.endswith("_nc"):
                        trucks_nc += 1
                    el.clear()
        except ET.ParseError:
            pass
    m["completed"] = n
    m["still_running_at_end"] = n_unf
    m["mean_duration"] = dur / n if n else None
    m["mean_timeloss"] = tl / n if n else None
    m["mean_waiting"] = wt / n if n else None
    m["mean_timeloss_censoring_robust"] = tl_all / (n + n_unf) if (n + n_unf) else None
    m["realized_truck_share"] = trucks / (n + n_unf) if (n + n_unf) else None
    m["realized_noncomp_share"] = trucks_nc / (n + n_unf) if (n + n_unf) else None

    sp = os.path.join(rundir, "summary.xml")
    for a in ("teleports", "collisions", "running", "inserted", "loaded", "ended", "halting"):
        m[a if a not in ("running", "halting") else "final_" + a] = last_summary_value(sp, a)
    st = os.path.join(rundir, "stats.xml")
    if os.path.exists(st):
        try:
            root = ET.parse(st).getroot()
            v = root.find("vehicles")
            if v is not None:
                for k in ("loaded", "inserted", "running", "waiting"):
                    m["stat_" + k] = int(v.get(k, 0))
            ts = root.find("teleports")
            if ts is not None:
                m["stat_teleports_total"] = int(ts.get("total", 0))
                m["stat_teleports_jam"] = int(ts.get("jam", 0))
                m["stat_teleports_yield"] = int(ts.get("yield", 0))
                m["stat_teleports_wrongLane"] = int(ts.get("wrongLane", 0))
            sf = root.find("safety")
            if sf is not None:
                m["stat_collisions"] = int(sf.get("collisions", 0))
                m["stat_emergencyBraking"] = int(sf.get("emergencyBraking", 0))
                m["stat_emergencyStops"] = int(sf.get("emergencyStops", 0))
        except ET.ParseError:
            pass
    cp = os.path.join(rundir, "collisions.xml")
    ncol = 0
    coltypes = {}
    if os.path.exists(cp):
        try:
            for _, el in ET.iterparse(cp, events=("end",)):
                if el.tag == "collision":
                    ncol += 1
                    lane = el.get("lane") or ""
                    k = "junction" if lane.startswith(":") else "link"
                    coltypes[k] = coltypes.get(k, 0) + 1
                    el.clear()
        except ET.ParseError:
            pass
    m["collision_records"] = ncol
    m["collision_junction"] = coltypes.get("junction", 0)
    m["collision_link"] = coltypes.get("link", 0)

    # SUMO's own warning stream: the unphysical "emergency stop at the end of lane because of
    # a red traffic light" events are the signature artifact of this study and are counted
    # directly from the log rather than inferred.
    ep = os.path.join(rundir, "sumo.err")
    cnt = dict(emg_stop_red=0, emg_brake=0, teleport_warn=0, collision_warn=0,
               emg_stop_max_decel=0.0)
    if os.path.exists(ep):
        for line in open(ep, errors="ignore"):
            if "emergency stop at the end of lane" in line:
                cnt["emg_stop_red"] += 1
                if "decel=-" in line:
                    try:
                        d = abs(float(line.split("decel=")[1].split(",")[0]))
                        cnt["emg_stop_max_decel"] = max(cnt["emg_stop_max_decel"], d)
                    except (ValueError, IndexError):
                        pass
            elif "performs emergency braking" in line:
                cnt["emg_brake"] += 1
            elif "teleporting" in line:
                cnt["teleport_warn"] += 1
            elif "collision with vehicle" in line and "SSM device" not in line:
                cnt["collision_warn"] += 1
    m.update(cnt)
    return m


def read_ssm(rundir, warmup=240.0):
    """Parse SSM log into conflict-category counts and severity extremes."""
    p = os.path.join(rundir, "ssm.xml")
    out = dict(n_conflict=0, n_rear=0, n_cross=0, n_merge=0, n_ssm_collision=0,
               ttc_lt_15=0, ttc_lt_10=0, pet_lt_10=0, pet_lt_20=0,
               min_ttc=None, min_pet=None, max_drac=None, max_br=None,
               n_br_gt_3=0, n_br_gt_45=0, n_veh_global=0, pets=[], rear_ttcs=[])
    if not os.path.exists(p):
        return out
    REAR = {2, 3, 18}
    MERGE = {6, 7, 8, 19}
    CROSS = set(range(10, 18))
    try:
        for _, el in ET.iterparse(p, events=("end",)):
            if el.tag == "conflict":
                if float(el.get("begin", 0)) < warmup:
                    el.clear()
                    continue
                out["n_conflict"] += 1
                types = set()
                for sub in el:
                    tv = sub.get("type")
                    if tv is not None and tv != "NA":
                        try:
                            types.add(int(float(tv)))
                        except ValueError:
                            pass
                    val = sub.get("value")
                    if val in (None, "NA"):
                        continue
                    fv = float(val)
                    if sub.tag == "minTTC":
                        out["min_ttc"] = fv if out["min_ttc"] is None else min(out["min_ttc"], fv)
                        if fv < 1.5:
                            out["ttc_lt_15"] += 1
                        if fv < 1.0:
                            out["ttc_lt_10"] += 1
                    elif sub.tag == "PET":
                        out["min_pet"] = fv if out["min_pet"] is None else min(out["min_pet"], fv)
                        if fv < 1.0:
                            out["pet_lt_10"] += 1
                        if fv < 2.0:
                            out["pet_lt_20"] += 1
                    elif sub.tag == "maxDRAC":
                        out["max_drac"] = fv if out["max_drac"] is None else max(out["max_drac"], fv)
                if types & CROSS:
                    out["n_cross"] += 1
                    for sub in el:
                        if sub.tag == "PET" and sub.get("value") not in (None, "NA"):
                            out["pets"].append(float(sub.get("value")))
                elif types & MERGE:
                    out["n_merge"] += 1
                elif types & REAR or not types:
                    out["n_rear"] += 1
                    for sub in el:
                        if sub.tag == "minTTC" and sub.get("value") not in (None, "NA"):
                            out["rear_ttcs"].append(float(sub.get("value")))
                if 111 in types:
                    out["n_ssm_collision"] += 1
                el.clear()
            elif el.tag == "globalMeasures":
                out["n_veh_global"] += 1
                for sub in el:
                    if sub.tag == "maxBR" and sub.get("value") not in (None, "NA"):
                        fv = float(sub.get("value"))
                        out["max_br"] = fv if out["max_br"] is None else max(out["max_br"], fv)
                        if fv > 3.0:
                            out["n_br_gt_3"] += 1
                        if fv > 4.5:
                            out["n_br_gt_45"] += 1
                el.clear()
    except ET.ParseError:
        pass
    return out


def prune_run(rundir, keep=("decision_log.csv", "summary.xml", "tls_verify.json",
                            "plan.json", "extra.add.xml", "collisions.xml", "metrics.json",
                            "stats.xml", "sumo.err")):
    for f in os.listdir(rundir):
        if f not in keep:
            p = os.path.join(rundir, f)
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
