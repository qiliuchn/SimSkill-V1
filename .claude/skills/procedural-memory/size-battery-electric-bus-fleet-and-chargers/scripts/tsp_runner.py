#!/usr/bin/env python3
"""
TraCI runner with an optional conditional Transit-Signal-Priority controller.

Controller design is imported unchanged in spirit from the `implement-transit-signal-priority`
skill:
  * detect an approaching bus with getNextTLS
  * derive its target phase from the link index in the RYG state string
  * perturb ONLY the current phase's remaining duration (never setPhase)
  * bounded by a cross-street minimum green and a per-cycle grant limit
  * mandatory offset recovery: debt accrued by extension/truncation is repaid on the
    cross-street phase only, so every grant stays a transient, attributable perturbation
`--mode off` runs the identical stepping loop with no intervention, so the only
difference between arms is the signal perturbation itself.
"""
import os, sys, json, time, argparse, collections

SUMO_HOME = os.environ.get("SUMO_HOME",
                           "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traci                                             # noqa: E402
import runner as RN                                      # noqa: E402
import scenario as SC                                    # noqa: E402


TSP_SIGNALS = ["J1", "J2", "J3", "J4", "J5", "J6"]
MIN_GREEN_CROSS = 12.0
GRANT_LIMIT_PER_CYCLE = 1
DETECT_DIST = 140.0
MAX_EXTEND = 10.0
MAX_TRUNCATE = 10.0


def run_tsp(outdir, mode="conditional", **kw):
    cfg, cmd = RN.build_cell(outdir, **kw)
    cmd = list(cmd) + ["--error-log", os.path.join(outdir, "sumo_stderr.txt")]
    open(os.path.join(outdir, "sumo_stderr.txt"), "w").write("")
    t_wall = time.time()
    traci.start(cmd)
    tls_meta = {}
    for t in TSP_SIGNALS:
        logic = traci.trafficlight.getAllProgramLogics(t)[0]
        phases = [(p.state, p.duration) for p in logic.phases]
        links = traci.trafficlight.getControlledLinks(t)
        tls_meta[t] = dict(phases=phases, nphase=len(phases), debt=0.0,
                           grants_this_cycle=0, last_phase=-1, cycle_id=0,
                           grant_instance=None, bus_near=False)
    grants = []
    phase_trace = []
    prev_phase = {t: (-1, 0.0) for t in TSP_SIGNALS}
    active_buses = set()
    step = 0
    end = cfg["sim_end"]
    while traci.simulation.getTime() < end:
        traci.simulationStep()
        now = traci.simulation.getTime()
        active_buses.update(v for v in traci.simulation.getDepartedIDList() if v.startswith("bus_"))
        active_buses.difference_update(traci.simulation.getArrivedIDList())
        # phase-instance bookkeeping
        for t in TSP_SIGNALS:
            ph = traci.trafficlight.getPhase(t)
            if ph != prev_phase[t][0]:
                if prev_phase[t][0] >= 0:
                    phase_trace.append(dict(tls=t, phase=prev_phase[t][0],
                                            start=prev_phase[t][1], end=now,
                                            realised=now - prev_phase[t][1],
                                            nominal=tls_meta[t]["phases"][prev_phase[t][0]][1]))
                prev_phase[t] = (ph, now)
                if ph == 0:
                    tls_meta[t]["grants_this_cycle"] = 0
                    tls_meta[t]["cycle_id"] += 1
        if mode == "off":
            step += 1
            continue
        # ---- priority requests
        for t in TSP_SIGNALS:
            tls_meta[t]["bus_near"] = False
        for vid in sorted(active_buses):
            nxt = traci.vehicle.getNextTLS(vid)
            if not nxt:
                continue
            tls_id, link_idx, dist, state = nxt[0]
            if tls_id not in tls_meta or dist > DETECT_DIST:
                continue
            m = tls_meta[tls_id]
            m["bus_near"] = True
            if m["grants_this_cycle"] >= GRANT_LIMIT_PER_CYCLE:
                continue
            cur = traci.trafficlight.getPhase(tls_id)
            cur_state = m["phases"][cur][0]
            remaining = traci.trafficlight.getNextSwitch(tls_id) - now
            spd = max(traci.vehicle.getSpeed(vid), 3.0)
            eta = dist / spd
            served_now = cur_state[link_idx] in "Gg"
            if served_now and eta > remaining and eta - remaining <= MAX_EXTEND:
                ext = min(MAX_EXTEND, eta - remaining + 1.0)
                traci.trafficlight.setPhaseDuration(tls_id, remaining + ext)
                m["debt"] += ext
                m["grants_this_cycle"] += 1
                m["grant_instance"] = (cur, prev_phase[tls_id][1])
                grants.append(dict(t=now, tls=tls_id, veh=vid, kind="extend",
                                   sec=round(ext, 1), phase=cur, dist=round(dist, 1)))
            elif (not served_now) and cur_state[link_idx] == "r":
                # truncate the CURRENT cross-street green if it has had its minimum
                elapsed = now - prev_phase[tls_id][1]
                is_cross_green = ("G" in cur_state or "g" in cur_state) and "y" not in cur_state
                nxt_phase = (cur + 1) % m["nphase"]
                brings_bus_next = m["phases"][(cur + 2) % m["nphase"]][0][link_idx] in "Gg"
                if is_cross_green and elapsed >= MIN_GREEN_CROSS and brings_bus_next and remaining > 1.0:
                    cut = min(MAX_TRUNCATE, remaining - 1.0)
                    if cut > 0.5:
                        traci.trafficlight.setPhaseDuration(tls_id, remaining - cut)
                        m["debt"] -= cut
                        m["grants_this_cycle"] += 1
                        m["grant_instance"] = (cur, prev_phase[tls_id][1])
                        grants.append(dict(t=now, tls=tls_id, veh=vid, kind="truncate",
                                           sec=round(cut, 1), phase=cur, dist=round(dist, 1)))
        # ---- offset recovery: repay debt on the cross-street green only, with no bus served
        for t in TSP_SIGNALS:
            m = tls_meta[t]
            if abs(m["debt"]) < 0.5:
                continue
            cur = traci.trafficlight.getPhase(t)
            st = m["phases"][cur][0]
            if cur != 2:                       # phase 2 == cross-street green (built by build_net)
                continue
            if m["bus_near"]:
                continue                       # do not fight a live priority request
            if m["grant_instance"] == (cur, prev_phase[t][1]):
                continue                       # never undo the grant inside its own phase instance
            remaining = traci.trafficlight.getNextSwitch(t) - now
            if m["debt"] > 0 and remaining > MIN_GREEN_CROSS + 1:
                pay = min(m["debt"], 2.0, remaining - MIN_GREEN_CROSS)
                traci.trafficlight.setPhaseDuration(t, remaining - pay)
                m["debt"] -= pay
            elif m["debt"] < 0:
                pay = min(-m["debt"], 2.0)
                traci.trafficlight.setPhaseDuration(t, remaining + pay)
                m["debt"] += pay
        step += 1
    traci.close()
    json.dump(grants, open(os.path.join(outdir, "grants_log.json"), "w"))
    json.dump(phase_trace[-4000:], open(os.path.join(outdir, "phase_trace.json"), "w"))
    json.dump({t: {"debt": tls_meta[t]["debt"]} for t in TSP_SIGNALS},
              open(os.path.join(outdir, "tsp_debt.json"), "w"))
    return dict(rc=0, grants=len(grants), mode=mode, wall_s=round(time.time()-t_wall,1), outdir=outdir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--mode", default="conditional")
    ap.add_argument("--kw", default="{}")
    a = ap.parse_args()
    print(json.dumps(run_tsp(a.outdir, a.mode, **json.loads(a.kw))))
