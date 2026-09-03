"""
Emergency-vehicle full signal PREEMPTION controller for a signalized arterial in
SUMO, via TraCI. One script, three configs on identical demand + seed:

  --config a : baseline. EV uses a plain emergency vType (NO device.bluelight),
               no preemption. EV obeys signals, no rescue lane.
  --config b : bluelight rescue-lane only. EV uses a bluelight-equipped emergency
               vType so surrounding traffic forms a rescue lane, but signals run
               their native program (NO preemption) and the EV still stops at red.
  --config c : bluelight + full signal preemption (this controller active).

FULL PREEMPTION vs. Transit Signal Priority (the existing skill):
TSP (implement-transit-signal-priority) only *perturbs the CURRENT phase's
duration* (extend an active green / truncate a conflicting green) and NEVER jumps
phase index, letting the native program handle all sequencing/yellow/clearance.
Full preemption is categorically different: when the EV approaches, it FORCES a
transition to the EV's movement regardless of the current phase, and it must
first drive conflicting movements to red through a genuine YELLOW -> ALL-RED
clearance interval (a safety requirement TSP never needs because TSP never
strands a movement mid-green). It then HOLDS the EV green until the EV physically
clears the junction (verified by TraCI position, not a timer), then RECOVERS to
the native program. Implemented here with setRedYellowGreenState overrides so the
exact clearance state strings are logged and auditable.

Per-signal FSM:  NORMAL -> YELLOW -> ALLRED -> EVGREEN -> RECOVER -> NORMAL
"""
import argparse
import json
import os
import sys


def is_green_state(state):
    return ("G" in state or "g" in state) and "y" not in state


class SignalPreemptor:
    """Per-signal preemption FSM. Overrides state directly for auditable clearance."""

    def __init__(self, traci, tls, params, log):
        self.traci = traci
        self.tls = tls
        self.p = params
        self.log = log
        logic = traci.trafficlight.getAllProgramLogics(tls)[0]
        self.phases = logic.phases
        self.green_phases = [i for i, ph in enumerate(self.phases) if is_green_state(ph.state)]
        self.nlinks = len(traci.trafficlight.getRedYellowGreenState(tls))
        self.state = "NORMAL"
        self.target_state = None   # EV-green phase state string
        self.timer_end = 0.0
        self.ev_id = None
        self.preempt_count = 0

    def _ev_green_state_for(self, link_idx):
        """The native conflict-free green phase whose char at link_idx is G/g."""
        for gi in self.green_phases:
            st = self.phases[gi].state
            if link_idx < len(st) and st[link_idx] in ("G", "g"):
                return st, gi
        return None, None

    def _yellow_from(self, cur, target):
        out = []
        for i in range(len(cur)):
            c = cur[i]
            t = target[i] if i < len(target) else "r"
            if c in ("G", "g") and t == "r":
                out.append("y")   # movement losing its green -> yellow
            elif c == "y":
                out.append("y")   # already clearing
            else:
                out.append("r")   # EV movement + everything else held red for now
        return "".join(out)

    def _ev_cleared(self, now):
        """EV has physically passed this junction (TraCI position, not a timer)."""
        tr = self.traci
        if self.ev_id not in tr.vehicle.getIDList():
            return True
        upcoming = [e[0] for e in tr.vehicle.getNextTLS(self.ev_id)]
        return self.tls not in upcoming

    def step(self, now, request, enabled):
        tr = self.traci
        if not enabled:
            return

        # ---- NORMAL: watch for an approaching EV within detection range ----
        if self.state == "NORMAL":
            if request is None:
                return
            ev_id, link_idx, dist, _spd = request
            target_state, target_gi = self._ev_green_state_for(link_idx)
            if target_state is None:
                return
            self.ev_id = ev_id
            self.target_state = target_state
            self.preempt_count += 1
            cur = tr.trafficlight.getRedYellowGreenState(self.tls)
            # If the EV movement is ALREADY green (conflicts already red), no
            # clearance is physically needed: hold it. Otherwise run YELLOW->ALLRED.
            if cur == target_state:
                tr.trafficlight.setRedYellowGreenState(self.tls, target_state)
                self.state = "EVGREEN"
                self.log.append({"t": now, "tls": self.tls, "event": "PREEMPT_START_ALREADY_GREEN",
                                 "ev": ev_id, "dist": round(dist, 1), "link_idx": link_idx,
                                 "state": target_state, "native_green_phase": target_gi})
                return
            yellow = self._yellow_from(cur, target_state)
            tr.trafficlight.setRedYellowGreenState(self.tls, yellow)
            self.timer_end = now + self.p["yellow_dur"]
            self.state = "YELLOW"
            self.log.append({"t": now, "tls": self.tls, "event": "PREEMPT_START",
                             "ev": ev_id, "dist": round(dist, 1), "link_idx": link_idx,
                             "prev_state": cur, "state": yellow,
                             "target_ev_green": target_state, "native_green_phase": target_gi,
                             "note": "conflicting greens -> yellow"})
            return

        # ---- YELLOW: hold, then go ALL-RED ----
        if self.state == "YELLOW":
            if now >= self.timer_end:
                allred = "r" * self.nlinks
                tr.trafficlight.setRedYellowGreenState(self.tls, allred)
                self.timer_end = now + self.p["allred_dur"]
                self.state = "ALLRED"
                self.log.append({"t": now, "tls": self.tls, "event": "CLEARANCE_ALLRED",
                                 "ev": self.ev_id, "state": allred,
                                 "hold_s": self.p["allred_dur"],
                                 "note": "genuine all-red clearance before EV green"})
            else:
                tr.trafficlight.setRedYellowGreenState(
                    self.tls, tr.trafficlight.getRedYellowGreenState(self.tls))
            return

        # ---- ALLRED: hold clearance, then grant EV GREEN ----
        if self.state == "ALLRED":
            if now >= self.timer_end:
                tr.trafficlight.setRedYellowGreenState(self.tls, self.target_state)
                self.state = "EVGREEN"
                self.log.append({"t": now, "tls": self.tls, "event": "EV_GREEN",
                                 "ev": self.ev_id, "state": self.target_state,
                                 "note": "EV movement granted green, conflicts red"})
            return

        # ---- EVGREEN: hold until EV physically clears the junction ----
        if self.state == "EVGREEN":
            tr.trafficlight.setRedYellowGreenState(self.tls, self.target_state)
            if self._ev_cleared(now):
                self.state = "RECOVER"
                self.log.append({"t": now, "tls": self.tls, "event": "EV_CLEARED",
                                 "ev": self.ev_id, "state": self.target_state,
                                 "note": "EV past stop line (TraCI getNextTLS), begin recovery"})
            return

        # ---- RECOVER: return to native program ----
        if self.state == "RECOVER":
            tr.trafficlight.setProgram(self.tls, "0")
            self.log.append({"t": now, "tls": self.tls, "event": "RECOVERY_DONE",
                             "ev": self.ev_id,
                             "state": tr.trafficlight.getRedYellowGreenState(self.tls),
                             "note": "native fixed-time program resumed"})
            self.state = "NORMAL"
            self.ev_id = None
            self.target_state = None
            return


def collect_requests(traci, controlled, detection_range):
    reqs = {t: None for t in controlled}
    for vid in traci.vehicle.getIDList():
        if traci.vehicle.getVehicleClass(vid) != "emergency":
            continue
        nxt = traci.vehicle.getNextTLS(vid)
        if not nxt:
            continue
        tls_id, link_idx, dist, _state = nxt[0]
        if tls_id not in reqs or dist > detection_range:
            continue
        cur = reqs[tls_id]
        spd = traci.vehicle.getSpeed(vid)
        if cur is None or dist < cur[2]:
            reqs[tls_id] = (vid, link_idx, dist, spd)
    return reqs


def run(args):
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci  # noqa: E402

    os.makedirs(args.outdir, exist_ok=True)
    ev_file = args.ev_a if args.config == "a" else args.ev_bc
    preempt_enabled = (args.config == "c")
    signals = args.signals.split(",")
    params = {"yellow_dur": args.yellow_dur, "allred_dur": args.allred_dur}

    # Per-config edgeData additional so the three runs don't overwrite each other.
    ed_out = os.path.abspath(os.path.join(args.outdir, "edgedata.out.xml"))
    add_path = os.path.abspath(os.path.join(args.outdir, "edgedata.add.xml"))
    with open(add_path, "w") as f:
        f.write('<additional>\n  <edgeData id="ed" file="%s" begin="0" end="%d" '
                'excludeEmpty="true"/>\n</additional>\n' % (ed_out, args.end))

    cmd = ["sumo", "-n", args.net, "-r", f"{args.bg},{ev_file}", "-a", add_path,
           "--tripinfo-output", os.path.join(args.outdir, "tripinfo.xml"),
           "--summary-output", os.path.join(args.outdir, "summary.xml"),
           "--fcd-output", os.path.join(args.outdir, "fcd.xml"),
           "--fcd-output.attributes", "id,x,y,speed,lane,type",
           "--lateral-resolution", "0.64",
           "--device.bluelight.reactiondist", str(args.reactiondist),
           "--duration-log.statistics", "true", "--no-step-log", "true",
           "--time-to-teleport", "300", "--seed", str(args.seed), "-e", str(args.end)]
    # edgeData additional writes relative to CWD; redirect by running with outdir cwd-safe name
    traci.start(cmd)
    log = []
    try:
        controlled = [t for t in traci.trafficlight.getIDList() if t in signals]
        sigs = {t: SignalPreemptor(traci, t, params, log) for t in controlled}
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            now = traci.simulation.getTime()
            reqs = collect_requests(traci, controlled, args.detection_range)
            for t, sig in sigs.items():
                sig.step(now, reqs[t], preempt_enabled)
        preempts = {t: sigs[t].preempt_count for t in sigs}
    finally:
        traci.close()

    with open(os.path.join(args.outdir, "preempt_log.json"), "w") as f:
        json.dump({"config": args.config, "preempt_enabled": preempt_enabled,
                   "preempts_per_signal": preempts, "events": log}, f, indent=2)
    print(f"[config {args.config}] preempt_enabled={preempt_enabled} "
          f"preempts/signal={preempts} events={len(log)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["a", "b", "c"], required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--bg", required=True)
    ap.add_argument("--ev-a", required=True)
    ap.add_argument("--ev-bc", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--end", type=int, default=900)
    ap.add_argument("--detection-range", type=float, default=150.0)
    ap.add_argument("--yellow-dur", type=float, default=3.0)
    ap.add_argument("--allred-dur", type=float, default=2.0)
    ap.add_argument("--reactiondist", type=float, default=50.0)
    args = ap.parse_args()
    run(args)
