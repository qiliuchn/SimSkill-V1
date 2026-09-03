#!/usr/bin/env python3
"""Run ONE experimental cell (variant x treatment x regime x seed) under TraCI
and produce every measurement the RTOR/LPI study needs.

Instrumentation
---------------
1. ON-RED vs ON-GREEN right-turn volume.  For every right-turning vehicle the
   signal character of ITS OWN right-turn link index is read at the simulation
   step in which the vehicle's front first appears on the right turn's internal
   `via` lane (= it has crossed the stop line).  'r'/'s' -> ON-RED, 'g'/'G' ->
   ON-GREEN, 'y' -> ON-YELLOW.  The stop-line speed is recorded at the same
   instant.
2. An INDEPENDENT cross-check: an `instantInductionLoop` 2 m upstream of every
   stop line logs each passage with a timestamp; those timestamps are later
   classified by an ANALYTIC reconstruction of the signal program (phase
   durations only - no TraCI involved).  The analytic reconstruction is itself
   validated here by comparing it against the TraCI-observed state at every
   single step (`analytic_state_mismatches` must be 0).
3. Segment control delay (HCM convention, see the project's
   hcm-control-delay-vs-sumo-delay-metrics page): entry at 250 m upstream of
   the stop line, exit 100 m past the junction on the receiving edge; the
   free-flow datum is MEASURED per movement (supplied via --freeflow).
4. Pedestrian crossing volume and crossing wait time per crossing.
5. Pedestrian-vehicle conflict exposure, filtered to (right-turn movement x its
   own foe crossings) pairs only.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci                                     # noqa: E402
import traci.constants as tc                     # noqa: E402
import xml.etree.ElementTree as ET               # noqa: E402

from linkmap import LinkMap                      # noqa: E402

VEH_SUB = [tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_LANE_ID, tc.VAR_LANEPOSITION]
PER_SUB = [tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_ROAD_ID]

REF_UPSTREAM = 250.0     # m upstream of stop line  -> control-delay entry
REF_DOWNSTREAM = 100.0   # m past junction on receiving edge -> exit

CONF_DIST = 8.0          # m: proximity gate for a ped-vehicle encounter
CONF_TTC = 2.0           # s: d / v_veh threshold defining a *conflict*
CONF_VMIN = 1.0          # m/s: vehicle must actually be moving


def parse_program(tll_path, tls_id="C"):
    root = ET.parse(tll_path).getroot()
    tl = [t for t in root.findall("tlLogic") if t.get("id") == tls_id][0]
    ph = [(float(p.get("duration")), p.get("state"), p.get("name")) for p in tl.findall("phase")]
    C = sum(d for d, _, _ in ph)
    return ph, C, tl.get("programID")


def analytic_state(ph, C, t):
    x = t % C
    for d, s, _ in ph:
        if x < d - 1e-9:
            return s
        x -= d
    return ph[-1][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--program", required=True)
    ap.add_argument("--detectors", required=True)
    ap.add_argument("--program-id", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--demand-end", type=float, default=3600)
    ap.add_argument("--end", type=float, default=4800)
    ap.add_argument("--warmup", type=float, default=300)
    ap.add_argument("--step-length", type=float, default=0.5)
    ap.add_argument("--freeflow", default=None, help="json: movement -> free-flow segment time")
    ap.add_argument("--keep-raw", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    pfx = os.path.join(a.outdir, a.tag)
    lm = LinkMap(a.net)
    ph, C, _ = parse_program(a.program)

    right_li = {x: lm.right(x) for x in "NESW"}
    right_via = {x: lm.veh[right_li[x]]["via"] for x in "NESW"}       # internal lane id
    via_to_appr = {v: k for k, v in right_via.items()}
    # all internal via lanes, per (approach, movement)
    via_of = {}
    for (appr, d), li in lm.mv.items():
        via_of[(appr, d)] = lm.veh[li]["via"]
    xing_edge = {li: lm.xing[li]["edge"] for li in lm.xing}
    # right-turn movement -> foe crossing link indices
    foe_x = {x: lm.foe_crossings_of_right(x) for x in "NESW"}

    freeflow = {}
    if a.freeflow and os.path.exists(a.freeflow):
        freeflow = json.load(open(a.freeflow))

    ssm_file = pfx + "_ssm.xml"
    cmd = [
        "sumo", "-n", a.net, "-r", a.routes,
        "-a", f"{a.program},{a.detectors}",
        "--pedestrian.model", "striping",
        "--step-length", str(a.step_length),
        "--begin", "0", "--end", str(a.end),
        "--time-to-teleport", "-1",
        "--no-step-log", "--no-warnings",
        "--seed", str(a.seed),
        "--tripinfo-output", pfx + "_tripinfo.xml",
        "--summary-output", pfx + "_summary.xml",
        "--summary-output.period", "60",
        "--collision-output", pfx + "_collisions.xml",
        "--device.ssm.file", ssm_file,
        "--duration-log.statistics",
    ]
    traci.start(cmd, label=a.tag)
    conn = traci.getConnection(a.tag)
    conn.trafficlight.setProgram("C", a.program_id)

    lane_len = {}
    for x in "NESW":
        lane_len[x] = conn.lane.getLength(f"in_{x}_1")
    out_len = {x: conn.lane.getLength(f"out_{x}_1") for x in "NESW"}

    # ---------------- state ----------------
    subs, prev_lane = set(), {}
    psubs = set()
    seg_enter, seg_done = {}, []          # vid -> t;   list of (mov, delay, t)
    turn_events = []                      # right-turn stop-line crossings
    all_stopline = []                      # every movement's stop-line crossing
    xing_entries = {li: 0 for li in lm.xing}
    xing_waits = {li: [] for li in lm.xing}
    pend_wait = {}
    ped_prev_edge = {}
    appr_minspeed = {}      # vid -> min speed observed in the last 15 m of the approach
    conflicts = {}                        # (vid,pid) -> dict
    conflict_log = []
    mismatches = 0
    steps = 0
    state_hist = []                       # (t, state) at 1 s resolution

    def movement_of(vid):
        # vehicle ids are "f_<approach><mov>.<n>"
        try:
            base = vid.split(".")[0]          # f_Nr
            return base[2], base[3]           # approach, movement
        except Exception:
            return None, None

    t = 0.0
    while t < a.end:
        conn.simulationStep()
        t = conn.simulation.getTime()
        steps += 1
        state = conn.trafficlight.getRedYellowGreenState("C")
        ast = analytic_state(ph, C, t - a.step_length)
        if ast != state:
            mismatches += 1
        if abs(t - round(t)) < 1e-6:
            state_hist.append((round(t, 1), state))

        for vid in conn.simulation.getDepartedIDList():
            conn.vehicle.subscribe(vid, VEH_SUB)
            subs.add(vid)
        for pid in conn.simulation.getDepartedPersonIDList():
            conn.person.subscribe(pid, PER_SUB)
            psubs.add(pid)

        vres = conn.vehicle.getAllSubscriptionResults()
        pres = conn.person.getAllSubscriptionResults()

        # ---- vehicles ----
        turning_now = {x: [] for x in "NESW"}    # approach -> [(vid,pos,speed)]
        for vid, d in vres.items():
            lane = d[tc.VAR_LANE_ID]
            lp = d[tc.VAR_LANEPOSITION]
            sp = d[tc.VAR_SPEED]
            pos = d[tc.VAR_POSITION]
            appr, mov = movement_of(vid)
            pl = prev_lane.get(vid)
            prev_lane[vid] = lane

            # control-delay segment entry
            if vid not in seg_enter and lane.startswith("in_") and appr:
                if lp >= lane_len[appr] - REF_UPSTREAM:
                    seg_enter[vid] = t
            # control-delay segment exit
            if vid in seg_enter and lane.startswith("out_") and lp >= REF_DOWNSTREAM:
                t_in = seg_enter.pop(vid)
                key = f"{appr}{mov}"
                ff = freeflow.get(key)
                seg_done.append((key, round(t - t_in, 2), ff, round(t_in, 2), round(t, 2)))

            # minimum speed in the final 15 m of the approach (stop detection)
            if appr and lane.startswith(f"in_{appr}") and lp >= lane_len[appr] - 15.0:
                appr_minspeed[vid] = min(appr_minspeed.get(vid, 99.0), sp)

            # stop-line crossing = first appearance on the movement's via lane
            if appr and mov and pl is not None and lane != pl:
                vkey = via_of.get((appr, mov))
                if vkey and lane == vkey and pl.startswith("in_"):
                    li = lm.mv[(appr, mov)]
                    ch = state[li]
                    ms = appr_minspeed.get(vid, -1.0)
                    all_stopline.append({"t": round(t, 2), "appr": appr, "mov": mov,
                                         "char": ch, "speed": round(sp, 3),
                                         "minspeed15": round(ms, 3), "veh": vid})
                    if mov == "r":
                        turn_events.append({"t": round(t, 2), "appr": appr, "veh": vid,
                                            "char": ch, "speed": round(sp, 3),
                                            "minspeed15": round(ms, 3)})

            # candidate right-turners near/at the conflict area
            if mov == "r" and appr:
                if lane == right_via[appr]:
                    # PAST the stop line: physically inside the junction, so a
                    # close encounter here is a genuine ENCROACHMENT
                    turning_now[appr].append((vid, pos, sp, state[right_li[appr]], True))
                elif lane.startswith(f"in_{appr}") and lp >= lane_len[appr] - 10.0:
                    # still upstream of the line: APPROACH exposure only
                    turning_now[appr].append((vid, pos, sp, state[right_li[appr]], False))

        for vid in conn.simulation.getArrivedIDList():
            subs.discard(vid)
            prev_lane.pop(vid, None)
            seg_enter.pop(vid, None)

        # ---- pedestrians ----
        peds_on_xing = {li: [] for li in lm.xing}
        for pid, d in pres.items():
            edge = d[tc.VAR_ROAD_ID]
            sp = d[tc.VAR_SPEED]
            pos = d[tc.VAR_POSITION]
            pe = ped_prev_edge.get(pid)
            ped_prev_edge[pid] = edge
            on_xing = edge in xing_edge.values()
            # waiting accrues only OFF the crossing (i.e. held at the kerb)
            if sp < 0.1 and not on_xing:
                pend_wait[pid] = pend_wait.get(pid, 0.0) + a.step_length
            for li, ce in xing_edge.items():
                if edge == ce:
                    peds_on_xing[li].append((pid, pos, sp))
                    if pe != ce:
                        xing_entries[li] += 1
                        xing_waits[li].append(round(pend_wait.pop(pid, 0.0), 2))
        for pid in conn.simulation.getArrivedPersonIDList():
            psubs.discard(pid)
            pend_wait.pop(pid, None)
            ped_prev_edge.pop(pid, None)

        # ---- ped-vehicle conflict exposure, right-turn movements only ----
        if t >= a.warmup:
            for appr in "NESW":
                if not turning_now[appr]:
                    continue
                for li in foe_x[appr]:
                    for (pid, ppos, psp) in peds_on_xing[li]:
                        for (vid, vpos, vsp, vch, past_line) in turning_now[appr]:
                            dx = vpos[0] - ppos[0]
                            dy = vpos[1] - ppos[1]
                            dist = (dx * dx + dy * dy) ** 0.5
                            if dist > CONF_DIST:
                                continue
                            k = (vid, pid, li)
                            ttc = dist / max(vsp, 0.05)
                            e = conflicts.get(k)
                            if e is None:
                                e = {"veh": vid, "ped": pid, "xing": li, "appr": appr,
                                     "t0": round(t, 2), "min_dist": dist, "min_ttc": ttc,
                                     "ticks": 0, "on_red": vch in "rs",
                                     "char_at_min": vch, "max_vspeed": vsp,
                                     "min_vspeed": vsp,
                                     "past_line": past_line,
                                     "encroach_ttc": ttc if past_line else 1e9,
                                     "encroach_dist": dist if past_line else 1e9}
                                conflicts[k] = e
                            e["ticks"] += 1
                            e["max_vspeed"] = max(e["max_vspeed"], vsp)
                            e["min_vspeed"] = min(e["min_vspeed"], vsp)
                            if dist < e["min_dist"]:
                                e["min_dist"] = dist
                                e["char_at_min"] = vch
                                e["past_line"] = past_line
                            if past_line:
                                e["encroach_dist"] = min(e["encroach_dist"], dist)
                                if vsp >= CONF_VMIN:
                                    e["encroach_ttc"] = min(e["encroach_ttc"], ttc)
                            if vsp >= CONF_VMIN and ttc < e["min_ttc"]:
                                e["min_ttc"] = ttc
                            e["t1"] = round(t, 2)

        if conn.simulation.getMinExpectedNumber() <= 0 and t > a.demand_end:
            break

    teleports = conn.simulation.getStartingTeleportNumber()
    conn.close()

    # ---------------- post-processing ----------------
    for e in conflicts.values():
        e["min_dist"] = round(e["min_dist"], 3)
        e["min_ttc"] = round(e["min_ttc"], 3)
        e["max_vspeed"] = round(e["max_vspeed"], 3)
        e["min_vspeed"] = round(e["min_vspeed"], 3)
        e["encroach_ttc"] = round(e["encroach_ttc"], 3)
        e["encroach_dist"] = round(e["encroach_dist"], 3)
    conflict_log = list(conflicts.values())

    res = {
        "tag": a.tag, "seed": a.seed, "net": a.net, "program": a.program,
        "program_id": a.program_id, "cycle": C, "steps": steps,
        "analytic_state_mismatches": mismatches,
        "teleports": teleports,
        "warmup": a.warmup, "demand_end": a.demand_end, "end": a.end,
        "turn_events": turn_events,
        "stopline_events": all_stopline,
        "segment": seg_done,
        "xing_entries": {str(k): v for k, v in xing_entries.items()},
        "xing_waits": {str(k): v for k, v in xing_waits.items()},
        "conflicts": conflict_log,
        "right_link_index": {k: v for k, v in right_li.items()},
        "foe_crossings": {k: v for k, v in foe_x.items()},
        "state_hist_sample": state_hist[:200],
    }
    with open(pfx + "_traci.json", "w") as f:
        json.dump(res, f)
    print(f"[{a.tag}] steps={steps} mismatch={mismatches} teleports={teleports} "
          f"turns={len(turn_events)} conflicts={len(conflict_log)}")


if __name__ == "__main__":
    main()
