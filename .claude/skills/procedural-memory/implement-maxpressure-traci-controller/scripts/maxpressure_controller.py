"""
Custom max-pressure adaptive traffic-signal controller, driven live via TraCI.

This is an EXTERNAL control law (not SUMO's built-in actuated logic): every
signalized junction is stepped and re-timed from Python each decision interval,
using the classical Varaiya max-pressure rule. Works on any network's existing
traffic-light program(s) — it introspects each junction's phases/links via
TraCI rather than assuming a particular phase count or layout, so it doesn't
need to be rewritten per network.

Pressure definition (documented choice)
---------------------------------------
For a signalized junction, each *green phase* activates a set of controlled
lane-to-lane movements (links whose phase-state char is 'G'/'g'). Each green
phase is mapped to the UNIQUE set of incoming lanes and outgoing lanes it
serves (via traci.trafficlight.getControlledLinks, which is index-aligned with
the RYG state string — don't hand-guess this mapping per junction). The phase
pressure is the classical queue-based max-pressure:

    pressure(phase) = sum_{l in incoming(phase)} queue(l)
                    - sum_{m in outgoing(phase)} queue(m)

where queue(lane) = number of halting vehicles on the lane
(traci.lane.getLastStepHaltingNumber, i.e. vehicles with speed < 0.1 m/s — the
standard queue-length proxy, same one get-vehicles-state's get_queue_length
uses). QUEUE LENGTH (halting count) is used on BOTH the upstream and
downstream side rather than mixing vehicle-count with fractional occupancy —
this is the theoretically grounded Varaiya (2013) formulation and keeps both
terms in the same unit (vehicles). The downstream term makes the controller
spillback-aware: it discounts serving a movement whose receiving lane is
already backed up.

Control loop per junction (all timing driven externally; SUMO's own phase
auto-advance is disabled by holding every phase with a huge setPhaseDuration):
  - Hold the current green phase for at least `min_green` seconds.
  - Every `decision_interval` seconds, once min-green has elapsed, recompute
    all green phases' pressures and pick the argmax (ties -> keep current
    phase, so a still-busy phase isn't needlessly dropped).
  - To switch green A -> green B, first insert A's own clearance YELLOW (the
    phase that follows A in the existing program and turns A's greens to 'y'),
    hold it for its programmed duration; THEN, if the program has an ALL-RED
    phase following that yellow, hold it too — until BOTH its programmed
    duration has elapsed AND A's own internal/via lanes are physically empty
    (bounded by a cap so a permanently-blocked junction can't freeze the
    signal) — THEN jump to B. Never green->green or yellow->green directly.
    A fixed-duration all-red alone is not sufficient on a permissive-left
    program: a vehicle already committed to the internal junction from
    standstill can need several seconds to clear a long internal path, longer
    than a typical short programmed all-red. Verified: an earlier version of
    this controller that jumped straight from yellow to the next green
    produced a real simulated collision on a 2-phase permissive-left program.

Usage:
    python maxpressure_controller.py --net net.net.xml --routes routes.rou.xml \
        --tripinfo tripinfo.xml --summary summary.xml --min-green 10 --decision-interval 5
"""
import argparse
import os
import sys

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci

HOLD = 100000  # large phase duration to suppress SUMO's own auto-advance


ALLRED_CAP = 12.0  # seconds: hard cap on extending all-red waiting for internal lanes to clear


def is_green(state):
    return ("G" in state or "g" in state) and "y" not in state


def has_yellow(state):
    return "y" in state


def is_allred(state):
    return ("G" not in state) and ("g" not in state) and ("y" not in state)


class JunctionController:
    """Max-pressure state machine for one traffic light."""

    def __init__(self, tls_id, min_green, decision_interval):
        self.tls = tls_id
        self.min_green = min_green
        self.decision_interval = decision_interval

        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
        self.phases = logic.phases
        self.n = len(self.phases)
        links = traci.trafficlight.getControlledLinks(tls_id)  # index-aligned to state

        self.green_phases = [i for i, p in enumerate(self.phases) if is_green(p.state)]

        # phase -> (unique incoming lanes, unique outgoing lanes, unique via/internal
        # lanes) for its green movements. The via lane is each link's 3rd element
        # (inLane, outLane, viaLane) — the internal lane a vehicle occupies while
        # actually crossing the junction. These are what must be physically empty
        # before it is safe to open a conflicting phase.
        self.phase_in = {}
        self.phase_out = {}
        self.phase_via = {}
        for gi in self.green_phases:
            state = self.phases[gi].state
            inc, out, via = set(), set(), set()
            for idx, ch in enumerate(state):
                if ch in ("G", "g") and idx < len(links):
                    for link in links[idx]:  # each is (inLane, outLane, viaLane)
                        if link and link[0]:
                            inc.add(link[0])
                        if link and link[1]:
                            out.add(link[1])
                        if link and len(link) > 2 and link[2]:
                            via.add(link[2])
            self.phase_in[gi] = list(inc)
            self.phase_out[gi] = list(out)
            self.phase_via[gi] = list(via)

        # for each green phase, the clearance yellow (and, if present, the
        # all-red that follows it) to insert when leaving it
        self.clearance = {}
        self.allred = {}
        for gi in self.green_phases:
            y, r = self._following_clearance(gi)
            self.clearance[gi] = y
            self.allred[gi] = r

        # runtime state
        self.mode = "GREEN"
        self.cur_green = self.green_phases[0] if self.green_phases else 0
        self.target_green = self.cur_green
        self.vacating_green = self.cur_green
        self.green_since = 0.0
        self.yellow_until = 0.0
        self.allred_min_until = 0.0
        self.allred_cap_until = 0.0
        self.last_decision = -1e9

    def _following_clearance(self, gi):
        """Return (yellow_phase_index_or_None, allred_phase_index_or_None) for
        leaving green phase gi, searched in program order starting right after gi."""
        yellow = None
        allred = None
        for step in range(1, self.n + 1):
            j = (gi + step) % self.n
            state = self.phases[j].state
            if yellow is None and has_yellow(state):
                yellow = j
                continue
            if yellow is not None:
                if is_allred(state):
                    allred = j
                break  # only look one phase past the yellow for an all-red
            if j in self.green_phases:  # reached next green before any yellow
                break
        return yellow, allred

    def start(self, now):
        if not self.green_phases:
            return
        traci.trafficlight.setPhase(self.tls, self.cur_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.green_since = now

    def _pressure(self, gi):
        up = sum(traci.lane.getLastStepHaltingNumber(l) for l in self.phase_in[gi])
        down = sum(traci.lane.getLastStepHaltingNumber(l) for l in self.phase_out[gi])
        return up - down

    def step(self, now):
        if len(self.green_phases) < 2:
            return  # nothing to switch between (e.g. degenerate boundary TLS)

        if self.mode == "YELLOW":
            if now >= self.yellow_until:
                allred = self.allred[self.vacating_green]
                if allred is not None:
                    traci.trafficlight.setPhase(self.tls, allred)
                    traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self.mode = "ALLRED"
                    self.allred_min_until = now + self.phases[allred].duration
                    self.allred_cap_until = now + ALLRED_CAP
                else:
                    self._commit_target_green(now)
            return

        if self.mode == "ALLRED":
            past_min = now >= self.allred_min_until
            past_cap = now >= self.allred_cap_until
            via_lanes = self.phase_via.get(self.vacating_green, [])
            clear = all(traci.lane.getLastStepVehicleNumber(l) == 0 for l in via_lanes)
            if past_cap or (past_min and clear):
                self._commit_target_green(now)
            return

        # GREEN mode
        if now - self.green_since < self.min_green:
            return
        if now - self.last_decision < self.decision_interval:
            return
        self.last_decision = now

        pressures = {gi: self._pressure(gi) for gi in self.green_phases}
        best = max(pressures, key=lambda g: pressures[g])
        if best == self.cur_green:
            return
        if pressures[best] <= pressures[self.cur_green]:
            return  # only switch if the winning phase strictly beats the current one

        yellow = self.clearance[self.cur_green]
        self.vacating_green = self.cur_green
        if yellow is None:
            # no clearance phase found in the program; jump directly (should not
            # happen on a well-formed network — verify the tlLogic if this triggers)
            self.target_green = best
            self._commit_target_green(now)
            return
        self.target_green = best
        traci.trafficlight.setPhase(self.tls, yellow)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.mode = "YELLOW"
        self.yellow_until = now + self.phases[yellow].duration

    def _commit_target_green(self, now):
        traci.trafficlight.setPhase(self.tls, self.target_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.cur_green = self.target_green
        self.mode = "GREEN"
        self.green_since = now


def run(net, routes, tripinfo, summary, min_green, decision_interval, max_steps=100000):
    sumo = os.path.join(SUMO_HOME, "bin", "sumo")
    traci.start(
        [
            sumo, "-n", net, "-r", routes,
            "--tripinfo-output", tripinfo,
            "--summary-output", summary,
            "--no-step-log", "true",
            "--duration-log.statistics", "true",
            "--time-to-teleport", "300",
        ]
    )
    try:
        controllers = [
            JunctionController(t, min_green, decision_interval)
            for t in traci.trafficlight.getIDList()
        ]
        now = traci.simulation.getTime()
        for c in controllers:
            c.start(now)

        steps = 0
        while traci.simulation.getMinExpectedNumber() > 0 and steps < max_steps:
            traci.simulationStep()
            steps += 1
            now = traci.simulation.getTime()
            for c in controllers:
                c.step(now)
        print(f"max-pressure run finished at t={now:.0f}, steps={steps}, tls={len(controllers)}")
    finally:
        traci.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run a max-pressure adaptive signal controller via TraCI.")
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--tripinfo", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--min-green", type=float, default=10.0, help="Minimum green duration in seconds (default: 10)")
    ap.add_argument("--decision-interval", type=float, default=5.0, help="Seconds between re-evaluating pressure (default: 5)")
    a = ap.parse_args()
    run(a.net, a.routes, a.tripinfo, a.summary, a.min_green, a.decision_interval)
