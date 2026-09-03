"""Correct LIVE (per-simulation-step) vehicle-entry counting for E1 induction
loops via TraCI.

GOTCHA THIS FIXES (found and verified while building the sub-goal-2 DoS
validator): `traci.inductionloop.getLastStepVehicleNumber(det_id)` returns how
many vehicles are PRESENT on the loop's small detection zone during the last
step -- NOT "how many newly crossed it this step". A vehicle that is queued
and creeping, or fully stopped, close to the loop's exact position can remain
"present" for many consecutive 1 s steps, and naively summing
`getLastStepVehicleNumber` across steps over-counts that single vehicle once
per step it lingers -- verified directly: this produced physically-impossible
apparent flow rates up to ~3800 veh/h/lane on a 2-lane approach whose true
demand was ~500 veh/h. The fix (what SUMO's own periodic XML `nVehEntered`
aggregate does internally) is to track vehicle-ID SET membership and count
only NEW arrivals (IDs not present in the previous step), i.e. edge-detect
entry events rather than summing presence.

This is exactly what the real adaptive controller (sub-goal 1) must also do
for a live, step-by-step volume/DoS estimate -- so this utility is shared
between the sub-goal-2 validator and the real controller, not a one-off
validation-script fix.
"""
import sys
import os

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


class E1EntryCounter(object):
    """Tracks TRUE vehicle-entry events (not presence-steps) for a set of E1
    induction loop ids. Call step() once per simulationStep(); read/reset the
    per-loop cumulative entry count with pop(det_id) or peek(det_id)."""

    def __init__(self, det_ids):
        self.det_ids = list(det_ids)
        self._prev_present = {d: frozenset() for d in self.det_ids}
        self._count = {d: 0 for d in self.det_ids}

    def step(self):
        for d in self.det_ids:
            cur = frozenset(traci.inductionloop.getLastStepVehicleIDs(d))
            new = cur - self._prev_present[d]
            if new:
                self._count[d] += len(new)
            self._prev_present[d] = cur

    def peek(self, det_id):
        return self._count[det_id]

    def pop(self, det_id):
        v = self._count[det_id]
        self._count[det_id] = 0
        return v

    def pop_many(self, det_ids):
        return sum(self.pop(d) for d in det_ids)
