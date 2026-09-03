#!/usr/bin/env python3
"""EMPIRICAL DISCOVERY of what SUMO's 's' signal state actually does.

SUMO documents 's' as: "green right-turn arrow requires stopping - vehicles may
pass the junction if no vehicle uses a higher priorised foe stream. They always
stop before passing. This is only generated for junction type
traffic_light_right_on_red."

Three claims are tested behaviourally against 'r' and 'g' on the SAME network,
SAME demand, SAME phase boundaries - only the character at the right-turn link
indices differs:

  C1  under 'r' the on-red right-turn volume is exactly zero; under 's' and 'g'
      it is not.
  C2  under 's' vehicles come to a stop / near-stop at the line; under 'g' they
      roll through.  Measured as the minimum speed in the last 15 m of the
      approach and the speed at the instant the front crosses the stop line.
  C3  under 's' the vehicle yields BOTH to conflicting vehicle traffic and to
      pedestrians in the crossing.  Tested by a 2x2 factorial on the presence of
      conflicting vehicle traffic and pedestrians: if 's' yields to each, the
      served on-red right-turn volume must fall when each is switched on.

Also checks that netconvert/sumo emit no warning mentioning the state and that
the character survives into the loaded program byte-identically.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci                              # noqa: E402
import traci.constants as tc              # noqa: E402
import numpy as np                        # noqa: E402

from linkmap import LinkMap, PAIRS        # noqa: E402
import gen_scenario                       # noqa: E402
from gen_programs import build_phases, CYCLE_PLAN   # noqa: E402
from run_cell import analytic_state                # noqa: E402

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs", "sprobe")
NET = os.path.join(BASE, "outputs", "net", "A_excl.net.xml")
STEP = 0.1
DEMAND_END = 900.0     # short, to keep the oversaturated backlog small
SIM_END = 1200.0
WARM = 300.0
# SSM is not needed for this probe and is expensive - use a bare vType
PROBE_VTYPE = """    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6"
           decel="4.5" sigma="0.5" tau="1.0" maxSpeed="16.0"
           speedFactor="1.0" speedDev="0" carFollowModel="Krauss"/>
    <vType id="ped" vClass="pedestrian" speedFactor="1.0" speedDev="0"/>
"""


def write_prog(lm, red_char, path, prog_id):
    """Same 100 s program as the main experiment, but the character used for a
    red right-turn link is `red_char` ('r', 's' or 'g')."""
    phases = build_phases(lm, rtor=False, lpi=False)
    out = []
    for dur, s, lab in phases:
        s = list(s)
        for a in "NESW":
            if s[lm.right(a)] == "r":
                s[lm.right(a)] = red_char
        out.append((dur, "".join(s), lab))
    lines = ['<additional>',
             f'    <tlLogic id="C" type="static" programID="{prog_id}" offset="0">']
    for d, s, lab in out:
        lines.append(f'        <phase duration="{d}" state="{s}" name="{lab}"/>')
    lines += ['    </tlLogic>', '</additional>']
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return out


def write_routes(path, conflicting, peds):
    """Right turns saturated (1200 veh/h/approach).  `conflicting` toggles the
    through movements that a right-turn-on-red must merge into / yield to;
    `peds` toggles pedestrian demand."""
    out = ['<routes>', PROBE_VTYPE]
    for a, mv in gen_scenario.MOVES.items():
        for m in ("r", "s", "l"):
            out.append(f'    <route id="rt_{a}{m}" edges="in_{a} out_{mv[m]}"/>')
    for a in "NESW":
        out.append(f'    <flow id="f_{a}r" type="car" route="rt_{a}r" begin="0" end="{DEMAND_END:.0f}" '
                   f'vehsPerHour="1200" departLane="best" departSpeed="max"/>')
        if conflicting:
            out.append(f'    <flow id="f_{a}s" type="car" route="rt_{a}s" begin="0" end="{DEMAND_END:.0f}" '
                       f'vehsPerHour="900" departLane="best" departSpeed="max"/>')
    if peds:
        for a in "NESW":
            for b in "NESW":
                if a == b:
                    continue
                out.append(f'    <personFlow id="p_{a}{b}" type="ped" begin="0" end="{DEMAND_END:.0f}" '
                           f'perHour="66.667" departPos="250">')
                out.append(f'        <walk from="in_{a}" to="out_{b}" arrivalPos="50"/>')
                out.append('    </personFlow>')
    out.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def run(lm, red_char, conflicting, peds, tag):
    prog = os.path.join(OUT, f"prog_{red_char}.tll.xml")
    written = write_prog(lm, red_char, prog, f"probe_{red_char}")
    rou = os.path.join(OUT, f"rou_c{int(conflicting)}_p{int(peds)}.rou.xml")
    write_routes(rou, conflicting, peds)

    right_li = {x: lm.right(x) for x in "NESW"}
    right_via = {x: lm.veh[right_li[x]]["via"] for x in "NESW"}
    xing_edge = {li: lm.xing[li]["edge"] for li in lm.xing}
    foe_x = {x: lm.foe_crossings_of_right(x) for x in "NESW"}

    cmd = ["sumo", "-n", NET, "-r", rou, "-a", prog,
           "--pedestrian.model", "striping", "--step-length", str(STEP),
           "--begin", "0", "--end", f"{SIM_END:.0f}", "--no-step-log",
           "--time-to-teleport", "-1", "--seed", "11",
           "--message-log", os.path.join(OUT, f"{tag}_msg.log"),
           "--error-log", os.path.join(OUT, f"{tag}_err.log")]
    traci.start(cmd, label=tag)
    conn = traci.getConnection(tag)
    conn.trafficlight.setProgram("C", f"probe_{red_char}")
    loaded = conn.trafficlight.getAllProgramLogics("C")
    loaded_states = None
    for lg in loaded:
        if lg.programID == f"probe_{red_char}":
            loaded_states = [(p.duration, p.state) for p in lg.phases]

    Cyc = sum(d for d, _ in loaded_states)
    plan = [(d, lab) for (d, _), (_, _, lab) in zip(loaded_states, written)]

    def phase_label(tt):
        x = tt % Cyc
        for d, lab in plan:
            if x < d - 1e-9:
                return lab
            x -= d
        return plan[-1][1]

    lane_len = {x: conn.lane.getLength(f"in_{x}_1") for x in "NESW"}
    prev_lane, minsp, events = {}, {}, []
    yield_stop_for_ped = 0
    ped_present_ticks = 0
    t = 0.0
    while t < SIM_END:
        conn.simulationStep()
        t = conn.simulation.getTime()
        state = conn.trafficlight.getRedYellowGreenState("C")
        for vid in conn.simulation.getDepartedIDList():
            if vid.split(".")[0][3] != "r":     # only right-turners are measured
                continue
            conn.vehicle.subscribe(vid, [tc.VAR_LANE_ID, tc.VAR_LANEPOSITION,
                                         tc.VAR_SPEED, tc.VAR_POSITION])
        peds_on = {li: conn.edge.getLastStepPersonIDs(xing_edge[li]) for li in xing_edge}
        for vid, d in conn.vehicle.getAllSubscriptionResults().items():
            lane, lp, sp = d[tc.VAR_LANE_ID], d[tc.VAR_LANEPOSITION], d[tc.VAR_SPEED]
            base = vid.split(".")[0]
            appr, mov = base[2], base[3]
            pl = prev_lane.get(vid)
            prev_lane[vid] = lane
            if mov != "r":
                continue
            if lane.startswith(f"in_{appr}") and lp >= lane_len[appr] - 15.0:
                minsp[vid] = min(minsp.get(vid, 99.0), sp)
                ch = state[right_li[appr]]
                if ch in "rs" and any(peds_on[li] for li in foe_x[appr]):
                    ped_present_ticks += 1
                    if sp < 0.3:
                        yield_stop_for_ped += 1
            if pl is not None and lane != pl and lane == right_via[appr] and pl.startswith("in_"):
                events.append({"t": round(t, 2), "appr": appr,
                               "phase": phase_label(t),
                               "char": state[right_li[appr]],
                               "speed": round(sp, 3),
                               "minspeed15": round(minsp.get(vid, -1.0), 3)})
        if t > DEMAND_END and conn.simulation.getMinExpectedNumber() <= 0:
            break
    conn.close()

    warm = [e for e in events if WARM <= e["t"] <= DEMAND_END]
    dur_h = (DEMAND_END - WARM) / 3600.0
    def own_green(e):
        pair = "NS" if e["appr"] in "NS" else "EW"
        return e["phase"] == f"{pair}_thru"

    def own_yellow(e):
        pair = "NS" if e["appr"] in "NS" else "EW"
        return e["phase"] == f"{pair}_thru_yellow"

    by = {}
    for cls in ("on_red", "on_green", "on_yellow"):
        if cls == "on_green":
            sel = [e for e in warm if own_green(e)]
        elif cls == "on_yellow":
            sel = [e for e in warm if own_yellow(e)]
        else:
            sel = [e for e in warm if not own_green(e) and not own_yellow(e)]
        sp = np.array([e["speed"] for e in sel]) if sel else np.array([])
        ms = np.array([e["minspeed15"] for e in sel if e["minspeed15"] >= 0]) if sel else np.array([])
        by[cls] = {
            "n": len(sel),
            "veh_per_h": round(len(sel) / dur_h, 1),
            "stopline_speed_mean": round(float(sp.mean()), 3) if len(sp) else None,
            "stopline_speed_p50": round(float(np.median(sp)), 3) if len(sp) else None,
            "stopline_speed_p95": round(float(np.percentile(sp, 95)), 3) if len(sp) else None,
            "min_approach_speed_mean": round(float(ms.mean()), 3) if len(ms) else None,
            "min_approach_speed_p50": round(float(np.median(ms)), 3) if len(ms) else None,
            "frac_full_stop_lt0.3ms": round(float((ms < 0.3).mean()), 4) if len(ms) else None,
            "frac_near_stop_lt1.0ms": round(float((ms < 1.0).mean()), 4) if len(ms) else None,
        }
    return {"red_char": red_char, "conflicting": conflicting, "peds": peds,
            "by_class": by,
            "total_rt_vph": round(len(warm) / dur_h, 1),
            "ped_yield_stop_ticks": yield_stop_for_ped,
            "ped_present_ticks": ped_present_ticks,
            "loaded_program_matches_written": (
                [s for _, s in loaded_states] == [s for _, s, _ in written]),
            "loaded_states": [s for _, s in loaded_states],
            "written_states": [s for _, s, _ in written]}


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    lm = LinkMap(NET)
    results = []
    only = os.environ.get("PROBE_CHARS", "rsg")
    for red_char in [ch for ch in ("r", "s", "g") if ch in only]:
        for conflicting in (False, True):
            for peds in (False, True):
                tag = f"probe_{red_char}_c{int(conflicting)}_p{int(peds)}"
                r = run(lm, red_char, conflicting, peds, tag)
                r["tag"] = tag
                # scan sumo's own message/error logs for anything about the state
                warn = []
                for suffix in ("_msg.log", "_err.log"):
                    p = os.path.join(OUT, tag + suffix)
                    if os.path.exists(p):
                        for line in open(p):
                            if re.search(r"(Warning|Error)", line):
                                warn.append(line.strip())
                r["warnings"] = warn[:50]
                r["n_warnings"] = len(warn)
                results.append(r)
                b = r["by_class"]
                print(f"{tag}: on_red={b['on_red']['veh_per_h']} veh/h "
                      f"(stopline v={b['on_red']['stopline_speed_mean']}, "
                      f"minv={b['on_red']['min_approach_speed_mean']}, "
                      f"stop_frac={b['on_red']['frac_full_stop_lt0.3ms']}) | "
                      f"on_green={b['on_green']['veh_per_h']} veh/h "
                      f"(minv={b['on_green']['min_approach_speed_mean']}) | "
                      f"warnings={r['n_warnings']} progmatch={r['loaded_program_matches_written']}")
    outp = os.path.join(OUT, os.environ.get("PROBE_OUT", "s_state_probe.json"))
    with open(outp, "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", outp)
