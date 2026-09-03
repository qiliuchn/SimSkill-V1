"""
Transit Signal Priority (TSP) controller for a signalized arterial in SUMO, via TraCI.

One script, three modes (identical demand + stepping loop; only the signal
intervention differs), so a baseline-vs-aggressive-vs-conditional comparison is
apples-to-apples:

  --mode baseline     : no intervention. The native fixed-time (static tlLogic)
                        program runs untouched. This IS the fixed-time baseline.
  --mode aggressive   : unconditional priority. Whenever a bus is within the
                        detection range and its movement is not green, the cross
                        (conflicting) green is truncated to a hard floor and the
                        arterial (bus) green is extended for as long as the bus is
                        approaching, up to a large cap. No per-cycle grant limit,
                        near-zero cross min-green -> maximises bus priority (and,
                        typically, badly starves cross-street traffic).
  --mode conditional  : conditional TSP.
                        * GREEN EXTENSION only when the bus arrives LATE in an
                          active green serving its movement (bus phase currently
                          green, about to end, bus still approaching) -> hold green
                          just long enough for the bus to clear, capped by max-green.
                        * EARLY GREEN (red truncation) only when the bus arrives on
                          RED: shorten the current conflicting green (once it has met
                          min-green) so the native cycle marches to the bus phase
                          sooner. Cross street always keeps >= min_green.
                        * PER-CYCLE GRANT LIMIT: at most `grant_limit` priority
                          episodes per signal per cycle, so cross traffic is not
                          starved.

Mechanism (deliberately minimal, so control returns cleanly to the fixed-time
program): the controller NEVER jumps phase index with setPhase. It only calls
setPhaseDuration on the CURRENT phase -- LENGTHENING it (green extension) or
SHORTENING it to a floor (early green / red truncation). SUMO's own static
program then handles all phase sequencing, yellows and clearance intervals. A
grant is thus a bounded perturbation of one phase's length, after which the
native cycle continues untouched. setPhaseDuration(tls, t) sets the REMAINING
duration of the CURRENT phase (TraCI semantics) -- exactly what green-extension
and early-green both need.

Bus detection uses traci.vehicle.getNextTLS(busID) -> [(tlsID, linkIdx, dist,
state), ...]; the nearest entry gives the signal the bus is approaching, the
bus's own link index within that signal's RYG state string, and the distance.
vClass is read via traci.vehicle.getVehicleClass so only buses (or whichever
--priority-vclass is given) request priority.

OFFSET RECOVERY (required, not optional): without it, a single truncation or
extension permanently shifts the signal's cycle offset relative to its native
fixed-time schedule, making all LATER grants unattributable to a specific bus
(every subsequent bus benefits from the earlier shift, not its own request).
This controller tracks per-signal "debt" (seconds the signal is ahead of/behind
its background schedule) and pays it back by flexing ONLY the cross-street
green, never the bus's own phase -- so each grant is a bounded, transient
perturbation and the fixed-time progression seen by un-granted buses is
preserved.

Usage:
  python tsp_controller.py --mode conditional \
      --net corridor.net.xml --cars cars.rou.xml --buses buses.rou.xml \
      --add busstops.add.xml --tsp-signals B1,C1,D1 --cycle-length 60 \
      --outdir runs/conditional --seed 42
"""
import argparse
import json
import os
import sys


def is_green_state(state):
    return ("G" in state or "g" in state) and "y" not in state


class SignalTSP:
    """Per-signal TSP state machine. Perturbs only the CURRENT phase's duration."""

    def __init__(self, traci, tls, mode, cycle_length, params, log):
        self.traci = traci
        self.tls = tls
        self.mode = mode
        self.cycle_length = cycle_length
        self.p = params
        self.log = log

        logic = traci.trafficlight.getAllProgramLogics(tls)[0]
        self.phases = logic.phases
        self.n = len(self.phases)
        self.green_phases = [i for i, ph in enumerate(self.phases) if is_green_state(ph.state)]

        self.cur_phase = traci.trafficlight.getPhase(tls)
        self.phase_start = traci.simulation.getTime()
        self.nominal = {i: float(ph.duration) for i, ph in enumerate(self.phases)}

        self.cycle_idx = -1
        self.grants_this_cycle = 0
        self.total_grants = 0
        self.ext_active = False
        self.trunc_armed_phase = None
        self.ext_blocked_armed_phase = None   # dedupe blocked-by-limit counting for extensions too
        self.ext_count = 0
        self.trunc_count = 0
        self.blocked_by_limit = 0

        self.debt = 0.0
        self.bus_phase = None
        self.recovery_done_phase = None
        self.transitions = []

    def _next_green_after(self, phase_idx):
        for step in range(1, self.n + 1):
            j = (phase_idx + step) % self.n
            if j in self.green_phases:
                return j
        return None

    def _refresh_phase(self, now):
        traci = self.traci
        ph = traci.trafficlight.getPhase(self.tls)
        if ph != self.cur_phase:
            actual = now - self.phase_start
            self.debt -= (actual - self.nominal.get(self.cur_phase, actual))
            self.transitions.append({
                "end_t": now, "phase_ended": self.cur_phase,
                "realized_dur": round(actual, 1),
                "nominal_dur": self.nominal.get(self.cur_phase),
            })
            self.cur_phase = ph
            self.phase_start = now
            if ph not in self.green_phases:
                self.ext_active = False
            self.trunc_armed_phase = None
            self.ext_blocked_armed_phase = None
            self.recovery_done_phase = None

    def _recover(self, now, serving_bus):
        traci = self.traci
        if self.bus_phase is None or abs(self.debt) < 0.5:
            return
        if serving_bus:
            return
        if self.cur_phase not in self.green_phases or self.cur_phase == self.bus_phase:
            return
        if self.recovery_done_phase == self.cur_phase:
            return
        elapsed = now - self.phase_start
        base = self.nominal[self.cur_phase]
        cross_max = base + self.p["recovery_max"]
        cross_min = self.p["min_green"]
        pay = max(-(base - cross_min), min(self.debt, cross_max - base))
        new_dur = base + pay
        new_remaining = max(0.5, new_dur - elapsed)
        traci.trafficlight.setPhaseDuration(self.tls, new_remaining)
        self.recovery_done_phase = self.cur_phase

    def _refresh_cycle(self, now):
        ci = int(now // self.cycle_length)
        if ci != self.cycle_idx:
            self.cycle_idx = ci
            self.grants_this_cycle = 0

    def _can_grant(self):
        if self.mode == "aggressive":
            return True
        return self.grants_this_cycle < self.p["grant_limit"]

    def step(self, now, request):
        """request = (bus_id, link_idx, dist, bus_speed) for the nearest approaching bus, or None."""
        traci = self.traci
        self._refresh_phase(now)
        self._refresh_cycle(now)
        if self.mode == "baseline":
            return

        if request is not None:
            link_idx = request[1]
            state0 = traci.trafficlight.getRedYellowGreenState(self.tls)
            if link_idx < len(state0):
                for gi in self.green_phases:
                    if self.phases[gi].state[link_idx] in ("G", "g"):
                        self.bus_phase = gi
                        break

        self._recover(now, serving_bus=(request is not None))

        if request is None:
            return

        bus_id, link_idx, dist, bus_speed = request
        state = traci.trafficlight.getRedYellowGreenState(self.tls)
        if link_idx >= len(state):
            return
        bus_char = state[link_idx]
        elapsed = now - self.phase_start
        bus_phase = self.bus_phase
        if bus_phase is None:
            return

        # --- Case 1: bus movement is GREEN right now -> consider GREEN EXTENSION ---
        if bus_char in ("G", "g") and self.cur_phase == bus_phase:
            remaining = traci.trafficlight.getNextSwitch(self.tls) - now
            speed = max(bus_speed, 2.0)
            time_to_clear = dist / speed + self.p["clear_buffer"]

            if self.mode == "aggressive":
                ext_threshold = 1e9
                max_green = self.p["agg_max_green"]
            else:
                ext_threshold = self.p["ext_threshold"]
                max_green = self.p["max_green"]

            if remaining <= ext_threshold and time_to_clear > remaining:
                max_remaining_allowed = max_green - elapsed
                if max_remaining_allowed <= remaining:
                    return
                new_remaining = min(time_to_clear, max_remaining_allowed)
                if new_remaining <= remaining + 0.1:
                    return
                if not self.ext_active:
                    if not self._can_grant():
                        if self.ext_blocked_armed_phase != self.cur_phase:
                            self.blocked_by_limit += 1
                            self.ext_blocked_armed_phase = self.cur_phase
                        return
                    self.grants_this_cycle += 1
                    self.total_grants += 1
                    self.ext_count += 1
                    self.ext_active = True
                    self.log.append({
                        "t": now, "tls": self.tls, "bus": bus_id, "action": "green_extension",
                        "dist": round(dist, 1), "phase": self.cur_phase, "state": state,
                        "old_remaining": round(remaining, 1),
                        "new_remaining": round(new_remaining, 1),
                        "elapsed_in_phase": round(elapsed, 1),
                        "cycle_grant_no": self.grants_this_cycle,
                    })
                traci.trafficlight.setPhaseDuration(self.tls, new_remaining)
            return

        # --- Case 2: bus movement is RED -> consider EARLY GREEN (red truncation) ---
        if bus_char == "r":
            if self.cur_phase not in self.green_phases:
                return
            if self.cur_phase == bus_phase:
                return
            if self._next_green_after(self.cur_phase) != bus_phase:
                return

            min_green = self.p["agg_min_green"] if self.mode == "aggressive" else self.p["min_green"]
            if elapsed < min_green:
                return
            if self.trunc_armed_phase == self.cur_phase:
                return

            remaining = traci.trafficlight.getNextSwitch(self.tls) - now
            if remaining <= self.p["clear_buffer"]:
                return
            if not self._can_grant():
                self.blocked_by_limit += 1
                self.trunc_armed_phase = self.cur_phase
                return

            self.grants_this_cycle += 1
            self.total_grants += 1
            self.trunc_count += 1
            self.trunc_armed_phase = self.cur_phase
            self.log.append({
                "t": now, "tls": self.tls, "bus": bus_id, "action": "early_green_truncation",
                "dist": round(dist, 1), "phase": self.cur_phase, "state": state,
                "old_remaining": round(remaining, 1), "new_remaining": 0.0,
                "elapsed_in_phase": round(elapsed, 1),
                "cycle_grant_no": self.grants_this_cycle,
            })
            traci.trafficlight.setPhaseDuration(self.tls, 0.0)
            return


def collect_requests(traci, controlled, detection_range, priority_vclass):
    reqs = {t: None for t in controlled}
    for vid in traci.vehicle.getIDList():
        if traci.vehicle.getVehicleClass(vid) != priority_vclass:
            continue
        nxt = traci.vehicle.getNextTLS(vid)
        if not nxt:
            continue
        tls_id, link_idx, dist, _state = nxt[0]
        if tls_id not in reqs or dist > detection_range:
            continue
        speed = traci.vehicle.getSpeed(vid)
        cur = reqs[tls_id]
        if cur is None or dist < cur[2]:
            reqs[tls_id] = (vid, link_idx, dist, speed)
    return reqs


def run(args):
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci  # noqa: E402

    os.makedirs(args.outdir, exist_ok=True)
    tsp_signals = args.tsp_signals.split(",")
    params = {
        "min_green": args.min_green, "max_green": args.max_green,
        "ext_threshold": args.ext_threshold, "clear_buffer": args.clear_buffer,
        "grant_limit": args.grant_limit, "recovery_max": args.recovery_max,
        "agg_min_green": args.agg_min_green, "agg_max_green": args.agg_max_green,
    }

    cmd = ["sumo", "-n", args.net, "-r", f"{args.cars},{args.buses}", "-a", args.add,
           "--tripinfo-output", os.path.join(args.outdir, "tripinfo.xml"),
           "--summary-output", os.path.join(args.outdir, "summary.xml"),
           "--duration-log.statistics", "true", "--no-step-log", "true",
           "--time-to-teleport", "300", "--seed", str(args.seed), "-e", str(args.end)]
    traci.start(cmd)
    log = []
    try:
        controlled = [t for t in traci.trafficlight.getIDList() if t in tsp_signals]
        sigs = {t: SignalTSP(traci, t, args.mode, args.cycle_length, params, log) for t in controlled}
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            now = traci.simulation.getTime()
            reqs = collect_requests(traci, controlled, args.detection_range, args.priority_vclass)
            for t, sig in sigs.items():
                sig.step(now, reqs[t])
        grants = {t: sigs[t].total_grants for t in sigs}
        diag = {t: {"extensions": sigs[t].ext_count, "truncations": sigs[t].trunc_count,
                    "blocked_by_limit": sigs[t].blocked_by_limit,
                    "final_debt": round(sigs[t].debt, 2)} for t in sigs}
    finally:
        traci.close()

    with open(os.path.join(args.outdir, "grants_log.json"), "w") as f:
        json.dump({"mode": args.mode, "grants_per_signal": grants,
                   "total_grants": sum(grants.values()), "diagnostics": diag,
                   "total_blocked_by_limit": sum(d["blocked_by_limit"] for d in diag.values()),
                   "events": log}, f, indent=2)
    if args.trace:
        with open(os.path.join(args.outdir, "phase_trace.json"), "w") as f:
            json.dump({t: sigs[t].transitions for t in sigs}, f, indent=2)
    print(f"[{args.mode}] grants/signal={grants} total={sum(grants.values())} "
          f"blocked={sum(d['blocked_by_limit'] for d in diag.values())}")
    return grants


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "aggressive", "conditional"], required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--cars", required=True)
    ap.add_argument("--buses", required=True)
    ap.add_argument("--add", required=True)
    ap.add_argument("--tsp-signals", required=True, help="Comma-separated tlLogic ids to apply TSP to")
    ap.add_argument("--cycle-length", type=float, required=True, help="Fixed-time cycle length (s), for per-cycle grant accounting")
    ap.add_argument("--priority-vclass", default="bus", help="vClass that requests priority")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--end", type=int, default=3900)
    ap.add_argument("--detection-range", type=float, default=120.0)
    ap.add_argument("--min-green", type=float, default=10.0)
    ap.add_argument("--max-green", type=float, default=42.0)
    ap.add_argument("--ext-threshold", type=float, default=6.0)
    ap.add_argument("--clear-buffer", type=float, default=2.0)
    ap.add_argument("--grant-limit", type=int, default=1)
    ap.add_argument("--recovery-max", type=float, default=18.0,
                    help="Max seconds the cross green may be lengthened during offset recovery")
    ap.add_argument("--agg-min-green", type=float, default=3.0)
    ap.add_argument("--agg-max-green", type=float, default=55.0)
    ap.add_argument("--trace", action="store_true",
                    help="Also dump per-signal realized phase durations to phase_trace.json")
    args = ap.parse_args()
    run(args)
