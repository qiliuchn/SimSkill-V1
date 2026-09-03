#!/usr/bin/env python3
"""
Max-pressure baseline with the program's ALL-RED clearance interval honoured.

The shared skill `implement-maxpressure-traci-controller` inserts the departing
green's clearance YELLOW before switching, but then jumps straight to the next
green -- it skips the ALL-RED phase that follows the yellow in the program.  On
this study's network (a 2-phase program with PERMISSIVE lefts, "GGGgrrrr...")
that is not merely conservative-vs-aggressive, it is unsafe: a permissive left
turner that has entered the junction and is waiting for a gap at the internal
junction is still inside when the conflicting green starts, and SUMO's junction
collision detector fires.  Reproduced deterministically as

    Warning: Vehicle 'v000280'; junction collision with vehicle 'v000282',
    lane=':center_3_0', gap=-1.00, time=519.40, stage=move.

A baseline that crashes is not a baseline, so this study runs max-pressure with
the clearance restored.  Only the switching state machine is changed; the
pressure rule itself is the skill's, unmodified.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "..", ".."))
sys.path.append(os.path.join(_ROOT, ".claude", "skills", "procedural-memory",
                             "implement-maxpressure-traci-controller", "scripts"))

import traci  # noqa: E402
from maxpressure_controller import JunctionController, HOLD  # noqa: E402


def _is_all_red(state):
    s = state.lower()
    return "g" not in s and "y" not in s


class JunctionControllerAllRed(JunctionController):

    def __init__(self, tls_id, min_green, decision_interval, max_allred=12.0):
        JunctionController.__init__(self, tls_id, min_green, decision_interval)
        self.allred_until = 0.0
        self.allred_deadline = 0.0
        self.max_allred = max_allred
        self.cur_yellow = None
        # every internal lane of this junction, for the OCCUPANCY-based
        # clearance below (the second lane of a `cont` chain is not a `via`
        # lane of any controlled link, so getControlledLinks alone is not
        # enough -- take every lane whose id starts with ':<junction>_')
        pref = ":%s_" % tls_id
        self.int_lanes = [l for l in traci.lane.getIDList() if l.startswith(pref)]

    def _following_all_red(self, yi):
        """The all-red phase the program itself places after yellow `yi`."""
        for step in range(1, self.n + 1):
            j = (yi + step) % self.n
            st = self.phases[j].state
            if _is_all_red(st):
                return j
            return None      # anything else immediately after the yellow: none
        return None

    def step(self, now):
        if len(self.green_phases) < 2:
            return

        if self.mode == "ALLRED":
            # A TIMED clearance is not a clearance.  The programmed 2 s all-red
            # cannot discharge a PERMISSIVE left turner that is trapped at the
            # internal junction waiting for a gap: it starts from standstill and
            # needs ~4 s to clear ~20 m of internal path, so the conflicting
            # green opens on top of it (observed once in 25 runs, d=1200:
            # ':center_15_0', t=243.2).  Hold the all-red until the junction is
            # physically EMPTY -- the same "check occupancy, not a timer" rule
            # the AIM interlock needs.  Bounded by max_allred so a permanently
            # blocked junction cannot freeze the signal.
            if now >= self.allred_until:
                occ = sum(traci.lane.getLastStepVehicleNumber(l)
                          for l in self.int_lanes)
                if occ > 0 and now < self.allred_deadline:
                    return
                traci.trafficlight.setPhase(self.tls, self.target_green)
                traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                self.cur_green = self.target_green
                self.mode = "GREEN"
                self.green_since = now
            return

        if self.mode == "YELLOW":
            if now >= self.yellow_until:
                ar = (self._following_all_red(self.cur_yellow)
                      if self.cur_yellow is not None else None)
                if ar is None:
                    traci.trafficlight.setPhase(self.tls, self.target_green)
                    traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self.cur_green = self.target_green
                    self.mode = "GREEN"
                    self.green_since = now
                else:
                    traci.trafficlight.setPhase(self.tls, ar)
                    traci.trafficlight.setPhaseDuration(self.tls, HOLD)
                    self.mode = "ALLRED"
                    self.allred_until = now + self.phases[ar].duration
                    self.allred_deadline = now + self.max_allred
            return

        prev_green = self.cur_green
        JunctionController.step(self, now)
        if self.mode == "YELLOW":
            self.cur_yellow = self.clearance[prev_green]
