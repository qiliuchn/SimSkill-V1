#!/usr/bin/env python3
"""Run ONE simulation cell and emit fully instrumented metrics.

A "cell" = (controller variant, demand level, seed).  The variant fixes the
signal program (Webster fixed-time OR actuated), the detector setback, the
max-gap, and any injected detector fault.

Every cell gets its OWN working directory so its additional file and every
output path are private -- parallel cells can never overwrite each other
(per `quantify-sumo-run-to-run-variability`).

INSTRUMENTATION (this is the part the critic checks against raw data)
--------------------------------------------------------------------
The runner polls the traffic light every step.  At the instant a green phase
ends it records, from live simulation state:

  * elapsed green, and the termination cause
        maxout : elapsed >= maxDur - 0.5
        minout : elapsed <= minDur + 0.5   (a special case of gap-out)
        gapout : anything in between
  * BLIND-ZONE state  -> failure mechanism "detector too FAR".
        vehicles physically between the detector and the stop line at the
        moment green ends.  These are invisible to the controller, so a
        green terminated while any of them is still slow/queued is a green
        cut with the queue still discharging.
        -> blind_veh, blind_slow_veh, cut_with_blind_queue
  * IMMINENT-ARRIVAL state -> failure mechanism "detector too CLOSE".
        `imminent`        : vehicles on the controlled lanes that would reach
                            the stop line within LOOKAHEAD s at their current
                            speed (floored at 30% of free-flow so a
                            just-launched vehicle still counts).  Independent
                            of detector position -> comparable across cells.
        `unseen_imminent` : the subset of those that have NOT yet reached the
                            detector, i.e. that the controller cannot know
                            about.  This is the setback-dependent form of "the
                            platoon isn't seen in time" and is the primary
                            mechanism-1 measure; f_premature_gapout counts
                            gap-outs with >=1 such vehicle.

Everything is written to metrics.json + a phase-by-phase trace CSV.
"""
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import traci                                                   # noqa: E402
import xml.etree.ElementTree as ET                             # noqa: E402
from tls_common import (ALL_DET_LANES, APPROACH_LEN, GREEN_ORDER, GREEN_PHASES,
                        LANE_SPEED, LANE2PHASE, build_program, detector_defs)

STUCK_LOOP_POS = 100.0  # position on the isolated DUMMY_0 lane of the loop used
                        # to model a permanently-calling (stuck-ON) detector
LOOKAHEAD = 5.0        # s, horizon for "imminent arrival"
SLOW = 2.0             # m/s, below this a vehicle counts as queued
WARMUP = 600.0
DEMAND_END = 3000.0
SIM_END = 3900.0
TTT_OVERRIDE = None    # set by teleport_check.py to sweep --time-to-teleport


# --------------------------------------------------------------------------
def build_additional(wd, cfg):
    """Write the additional file: inductionLoops + the tlLogic that uses them.

    cfg keys: mode ('webster'|'actuated'), setback, max_gap, min_dur, max_dur,
              green (webster displayed greens), fault, det_overrides
    """
    lines = ['<additional>']
    binding = {}
    if cfg["mode"] == "webster":
        lines.append(build_program(cfg["green"], tls_type="static",
                                   program_id="web"))
    else:
        # --- detector geometry, per lane (allows per-lane overrides) ---
        setbacks = {ln: cfg["setback"] for ln in ALL_DET_LANES}
        setbacks.update(cfg.get("det_overrides", {}))
        dead = set(cfg.get("dead_lanes", []))          # stuck-OFF detectors
        stuck_on = set(cfg.get("stuck_on_lanes", []))  # stuck-ON detectors
        for ln in ALL_DET_LANES:
            if ln in dead:
                # STUCK-OFF fault: the loop is declared dead.  Verified in
                # verify_binding.py to make SUMO emit "actuated phase N has no
                # controlling detector" and collapse that phase to minDur.
                binding[ln] = "NO_DETECTOR"
                continue
            did = f"det_{ln}"
            if ln in stuck_on:
                # STUCK-ON fault, modelled PHYSICALLY rather than emulated:
                # the lane is bound to a loop sitting on the isolated DUMMY
                # edge, on which run_cell parks a vehicle for the whole
                # simulation.  A parked vehicle straddling an E1 loop keeps
                # time-since-detection pinned at 0 s, i.e. a permanent call.
                # (SUMO accepts ONLY E1 <inductionLoop> as a custom actuated
                # detector -- an E2 <laneAreaDetector> is a hard error, tested.)
                lines.append(f'    <inductionLoop id="{did}" lane="DUMMY_0" '
                             f'pos="{STUCK_LOOP_POS:.2f}" period="100000" '
                             f'file="NUL"/>')
            else:
                pos = min(APPROACH_LEN - setbacks[ln], APPROACH_LEN - 0.2)
                pos = max(pos, 1.0)
                lines.append(f'    <inductionLoop id="{did}" lane="{ln}" '
                             f'pos="{pos:.2f}" period="100000" file="NUL"/>')
            binding[ln] = did
        params = {"max-gap": f'{cfg["max_gap"]}',
                  "detector-gap": "2.0",
                  "passing-time": "2.0",
                  "show-detectors": "false"}
        if cfg.get("auto_detectors"):
            # SUMO's DEFAULT behaviour: declare no bindings at all and let the
            # actuated logic auto-generate its own loops at detector-gap x speed.
            lines = ['<additional>']
            binding = {}
        else:
            params.update({ln: binding[ln] for ln in ALL_DET_LANES})
        lines.append(build_program(cfg["green"], min_durs=cfg["min_dur"],
                                   max_durs=cfg["max_dur"], tls_type="actuated",
                                   params=params, program_id="act"))
    lines.append('</additional>')
    p = os.path.join(wd, "cell.add.xml")
    open(p, "w").write("\n".join(lines) + "\n")
    return p, binding


def detector_positions(cfg):
    """Stop-line setback actually applied to each lane [m]."""
    if cfg["mode"] == "webster":
        return {}
    if cfg.get("auto_detectors"):
        # SUMO places an auto-generated loop detector-gap seconds of travel time
        # upstream of the stop line -> 2.0 s x 16.667 = 33.3 m on the major,
        # 2.0 s x 11.111 = 22.2 m on the minor.
        return {ln: 2.0 * LANE_SPEED[ln] for ln in ALL_DET_LANES}
    sb = {ln: cfg["setback"] for ln in ALL_DET_LANES}
    sb.update(cfg.get("det_overrides", {}))
    # A faulted lane has NO usable detector on it at all, so the controller is
    # blind to the WHOLE lane -> setback = full lane length (det_pos = 0).
    for ln in list(cfg.get("stuck_on_lanes", [])) + list(cfg.get("dead_lanes", [])):
        sb[ln] = APPROACH_LEN
    return sb


# --------------------------------------------------------------------------
def run(wd, net, rou, cfg, seed, keep_raw=False):
    os.makedirs(wd, exist_ok=True)
    addf, binding = build_additional(wd, cfg)
    prog = "web" if cfg["mode"] == "webster" else "act"
    setb = detector_positions(cfg)

    cmd = ["sumo", "-n", os.path.abspath(net), "-r", os.path.abspath(rou),
           "-a", os.path.abspath(addf),
           "--tripinfo-output", os.path.join(wd, "tripinfo.xml"),
           "--summary-output", os.path.join(wd, "summary.xml"),
           "--statistic-output", os.path.join(wd, "stats.xml"),
           "--begin", "0", "--end", str(SIM_END), "--step-length", "1",
           "--time-to-teleport",
           str(TTT_OVERRIDE if TTT_OVERRIDE is not None else 180),
           "--no-step-log", "true", "--no-warnings", "false",
           "--seed", str(seed), "--duration-log.statistics", "true",
           "--waiting-time-memory", "10000"]
    traci.start(cmd, label=wd)
    c = traci.getConnection(wd)

    c.trafficlight.setProgram("C", prog)
    active = c.trafficlight.getProgram("C")
    assert active == prog, f"program not active: {active}"
    lane_len = {ln: c.lane.getLength(ln) for ln in ALL_DET_LANES}
    det_pos = {ln: lane_len[ln] - setb.get(ln, 0.0) for ln in ALL_DET_LANES}

    # ---- park a vehicle on the stuck-ON loop, if this cell has that fault ----
    stuck_lanes = list(cfg.get("stuck_on_lanes", []))
    n_dummy = 0
    if stuck_lanes:
        c.route.add("dummyroute", ["DUMMY"])
        c.vehicle.add("STUCKON", "dummyroute", typeID="car",
                      departPos=str(STUCK_LOOP_POS + 2.0), departSpeed="0",
                      departLane="0")
        c.vehicle.setStop("STUCKON", "DUMMY", pos=STUCK_LOOP_POS + 2.0,
                          laneIndex=0, duration=10 ** 6)
        n_dummy = 1
    stuck_check = []      # time-since-detection samples on the stuck-ON loop

    # ---- state ----
    ev = []                       # per-green-phase-end event records
    cur = c.trafficlight.getPhase("C")
    gstart = 0.0
    t = 0.0
    teleports = 0
    while t < SIM_END:
        c.simulationStep()
        t = c.simulation.getTime()
        teleports += c.simulation.getStartingTeleportNumber()
        if stuck_lanes and t > 60 and int(t) % 60 == 0:
            stuck_check.append(
                c.inductionloop.getTimeSinceDetection("det_" + stuck_lanes[0]))
        ph = c.trafficlight.getPhase("C")
        if ph != cur:
            if cur in GREEN_PHASES:
                ev.append(sample_green_end(c, cur, t, gstart, cfg, det_pos,
                                           lane_len, t >= WARMUP))
            gstart = t
            cur = ph
        if t > DEMAND_END and c.simulation.getMinExpectedNumber() <= n_dummy:
            break
    c.close()

    # ---- write raw phase trace ----
    tr = os.path.join(wd, "phase_trace.csv")
    with open(tr, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ev[0].keys()) if ev else ["t"])
        w.writeheader()
        w.writerows(ev)

    m = aggregate(wd, ev, cfg, rou)
    m.update(dict(teleports=teleports, seed=seed, binding=binding,
                  setback_applied={k: round(v, 2) for k, v in setb.items()},
                  det_pos={k: round(v, 2) for k, v in det_pos.items()}))
    if stuck_check:
        # health check on the stuck-ON fault model: if the parked vehicle really
        # holds the loop, time-since-detection must be 0 s at every sample.
        m["stuckon_max_time_since_detection"] = max(stuck_check)
        m["stuckon_n_samples"] = len(stuck_check)
    json.dump(m, open(os.path.join(wd, "metrics.json"), "w"), indent=2)
    if not keep_raw:
        # bulk per-vehicle traces are dropped; the phase trace (the file the
        # instrumentation claims rest on) and cell.add.xml are always kept
        for f in ("summary.xml", "tripinfo.xml", "stats.xml"):
            p = os.path.join(wd, f)
            if os.path.exists(p):
                os.remove(p)
    return m


def sample_green_end(c, gp, t, gstart, cfg, det_pos, lane_len, counted):
    """Snapshot live vehicle state at the exact instant a green phase ends."""
    d = GREEN_PHASES[gp]
    elapsed = t - gstart
    blind = blind_slow = imminent = unseen_imminent = queued_total = 0
    for ln in d["lanes"]:
        dp = det_pos[ln]
        vmax = LANE_SPEED[ln]
        for vid in c.lane.getLastStepVehicleIDs(ln):
            pos = c.vehicle.getLanePosition(vid)
            spd = c.vehicle.getSpeed(vid)
            if spd < SLOW:
                queued_total += 1
            # --- mechanism 2: blind zone between detector and stop line ---
            if pos > dp:
                blind += 1
                if spd < SLOW:
                    blind_slow += 1
            # --- mechanism 1: would have arrived imminently ---
            eff = max(spd, 0.3 * vmax)
            if (lane_len[ln] - pos) / eff <= LOOKAHEAD:
                imminent += 1
                # ...and the controller could not know about it, because the
                # vehicle has not reached the detector yet.  THIS is the
                # setback-dependent form of "the platoon isn't seen in time":
                # at a 0 m setback every imminent vehicle is unseen; moving the
                # loop upstream converts unseen arrivals into seen ones.
                if pos < dp:
                    unseen_imminent += 1
    if cfg["mode"] == "webster":
        cause = "fixed"
    else:
        mx = cfg["max_dur"][gp]
        mn = cfg["min_dur"][gp]
        if elapsed >= mx - 0.5:
            cause = "maxout"
        elif elapsed <= mn + 0.5:
            cause = "minout"
        else:
            cause = "gapout"
    return dict(t=round(t, 1), phase=gp, name=d["name"], road=d["road"],
                mvt=d["mvt"], elapsed=round(elapsed, 1), cause=cause,
                blind=blind, blind_slow=blind_slow, imminent=imminent,
                unseen_imminent=unseen_imminent, queued=queued_total,
                counted=int(counted))


# --------------------------------------------------------------------------
def veh_group_map(rou):
    """vehicle id -> (approach, movement, road, scheduled depart) from the routes."""
    g = {}
    for _, el in ET.iterparse(rou, events=("end",)):
        if el.tag == "vehicle":
            r = el.get("route")           # r_<AP>_<mv>
            _, ap, mv = r.split("_")
            g[el.get("id")] = (ap, mv, "major" if ap in ("WC", "EC") else "minor",
                               float(el.get("depart")))
        el.clear()
    return g


def aggregate(wd, ev, cfg, rou):
    grp = veh_group_map(rou)
    rows = []
    seen = set()
    for _, el in ET.iterparse(os.path.join(wd, "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            vid = el.get("id")
            info = grp.get(vid)
            if info is not None and WARMUP <= info[3] < DEMAND_END:
                # NOTE: selection is on the SCHEDULED departure time, not the
                # realised one.  A blocked approach delays actual departure by
                # minutes; selecting on the realised time would quietly drop the
                # worst-affected vehicles from the sample.
                ap, mv, road, sched = info
                seen.add(vid)
                rows.append(dict(road=road, mvt=mv,
                                 timeLoss=float(el.get("timeLoss")),
                                 departDelay=float(el.get("departDelay")),
                                 waitingTime=float(el.get("waitingTime")),
                                 duration=float(el.get("duration")),
                                 stops=int(el.get("waitingCount"))))
        el.clear()

    # ---- censoring-robust accounting -------------------------------------
    # tripinfo only records COMPLETED trips.  When an approach is starved (e.g.
    # a stuck-off detector) hundreds of vehicles never even get inserted, and a
    # naive mean over tripinfo would make the broken controller look GOOD by
    # survivorship.  So we also build a delay measure over EVERY vehicle that
    # was SCHEDULED to depart in the window, charging an un-completed vehicle
    # its time from scheduled departure to the simulation horizon (a lower
    # bound on its true delay).
    sched = {v: info for v, info in grp.items() if WARMUP <= info[3] < DEMAND_END}
    tot, nmiss = 0.0, 0
    for vid, (ap, mv, road, dep) in sched.items():
        if vid in seen:
            continue
        nmiss += 1
        tot += SIM_END - dep
    tot += sum(r["timeLoss"] + r["departDelay"] for r in rows)

    def stat(sel):
        s = [r for r in rows if sel(r)]
        if not s:
            return dict(n=0)
        n = len(s)
        return dict(n=n,
                    delay=round(sum(r["timeLoss"] for r in s) / n, 3),
                    wait=round(sum(r["waitingTime"] for r in s) / n, 3),
                    tt=round(sum(r["duration"] for r in s) / n, 3),
                    stops=round(sum(r["stops"] for r in s) / n, 4))

    out = dict(all=stat(lambda r: True),
               major=stat(lambda r: r["road"] == "major"),
               minor=stat(lambda r: r["road"] == "minor"),
               throughput=len(rows),
               n_scheduled=len(sched),
               n_uncompleted=nmiss,
               completion_rate=round(len(rows) / max(1, len(sched)), 4),
               delay_censor_robust=round(tot / max(1, len(sched)), 3))

    # arrived/inserted from statistic-output (catches censoring)
    try:
        st = ET.parse(os.path.join(wd, "stats.xml")).getroot()
        v = st.find("vehicles")
        out["inserted"] = int(v.get("inserted"))
        out["loaded"] = int(v.get("loaded"))
        out["running_at_end"] = int(v.get("running"))
        out["waiting_at_end"] = int(v.get("waiting"))
    except Exception:
        pass

    # ---- phase-level instrumentation ----
    ph = {}
    for gp in GREEN_ORDER:
        e = [x for x in ev if x["phase"] == gp and x["counted"]]
        n = len(e)
        if n == 0:
            ph[GREEN_PHASES[gp]["name"]] = dict(n=0)
            continue
        go = [x for x in e if x["cause"] in ("gapout", "minout")]
        mo = [x for x in e if x["cause"] == "maxout"]
        ph[GREEN_PHASES[gp]["name"]] = dict(
            n=n,
            mean_green=round(sum(x["elapsed"] for x in e) / n, 2),
            f_gapout=round(len(go) / n, 4),
            f_maxout=round(len(mo) / n, 4),
            f_minout=round(len([x for x in e if x["cause"] == "minout"]) / n, 4),
            # MECHANISM 2 (detector too far): green cut while blind-zone queue present
            f_cut_with_blind_queue=round(
                sum(1 for x in go if x["blind_slow"] > 0) / n, 4),
            mean_blind_veh=round(sum(x["blind"] for x in e) / n, 3),
            mean_blind_slow=round(sum(x["blind_slow"] for x in e) / n, 3),
            # MECHANISM 1 (detector too close): premature gap-out
            f_premature_gapout=round(
                sum(1 for x in go if x["unseen_imminent"] > 0) / n, 4),
            f_premature_gapout_anyimminent=round(
                sum(1 for x in go if x["imminent"] > 0) / n, 4),
            mean_imminent=round(sum(x["imminent"] for x in e) / n, 3),
            mean_unseen_imminent=round(
                sum(x["unseen_imminent"] for x in e) / n, 3),
            mean_queued_at_end=round(sum(x["queued"] for x in e) / n, 3),
        )
    out["phases"] = ph
    out["n_green_events"] = len([x for x in ev if x["counted"]])
    return out


# --------------------------------------------------------------------------
if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1]))
    m = run(cfg["wd"], cfg["net"], cfg["rou"], cfg["cfg"], cfg["seed"],
            cfg.get("keep_raw", False))
    print(json.dumps(m["all"]))
