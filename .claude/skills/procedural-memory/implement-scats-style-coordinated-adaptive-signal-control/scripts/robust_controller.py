#!/usr/bin/env python3
"""Sub-goal 6: fault injection + failsafe layer on top of the sub-goal-1
adaptive controller.

FAULTS injected (software fault injection on the detector READ path -- the
controller cannot tell this apart from a genuinely broken sensor, which is
the point):
  stuck_on  -- the named advance detector is made to report a NEW vehicle
               EVERY simulation step regardless of real traffic (a classic
               inductive-loop failure mode: a loop shorted/miswired so it
               free-runs) -- this inflates its measured DoS_hat far past 1.0
               continuously.
  stuck_off -- the named advance detector NEVER reports a new vehicle,
               regardless of real traffic -- its measured DoS_hat pins at 0.

FAILSAFE (enable_failsafe=True):
  1. Detector plausibility check, every adaptation tick, per advance
     detector: flag FAULTED if its entry count this window implies a rate
     above a physically-impossible ceiling (PLAUSIBLE_MAX_VPH, well above
     this network's own measured per-lane saturation flow) -- catches
     stuck_on; OR if its count is exactly zero for STUCK_OFF_TICKS
     consecutive ticks WHILE the paired stop-bar E2 detector shows nonzero
     occupancy during that same stage's green (real vehicles are there,
     contradicting the advance detector's silence) -- catches stuck_off.
  2. FALLBACK-TO-FIXED-PLAN: a junction with ANY currently-faulted detector
     has its split/cycle contribution IGNORED for that tick -- it instead
     runs the static Webster default plan (webster_plan.compute_plan) until
     the fault clears (or for the rest of the run, in this study's
     permanent-fault scenario).
  3. Cycle-length runaway cap: c_max is a constructor parameter -- the
     "unprotected" oversaturation run uses an effectively unbounded cap
     (C_MAX_UNPROTECTED) to show what the naive DoS-tracking rule does with
     NO ceiling; the "protected" run uses this study's normal C_MAX=150.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CTRL = os.path.join(ROOT, "controller")
sys.path.insert(0, CTRL)
SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from adaptive_system import SystemController, N_INT  # noqa: E402
from webster_plan import compute_plan  # noqa: E402

PLAUSIBLE_MAX_VPH = 2200.0    # veh/h/lane ceiling -- above this network's measured
                              # ~1604 veh/h/lane saturation flow by a wide margin;
                              # no real approach can sustain more
STUCK_OFF_TICKS = 3
C_MAX_UNPROTECTED = 10000.0


class RobustSystemController(SystemController):
    def __init__(self, *a, faults=None, enable_failsafe=False, uncapped_cycle=False, **kw):
        if uncapped_cycle:
            kw["c_max"] = C_MAX_UNPROTECTED
        super(RobustSystemController, self).__init__(*a, **kw)
        self.faults = faults or {}          # det_id -> 'stuck_on'|'stuck_off'
        self.enable_failsafe = enable_failsafe
        self._fault_flag = {j: False for j in self.ids}
        self._zero_ticks = {aid: 0 for ids in self.adv_ids.values() for aid in ids}
        self.default_plan = compute_plan("unpred")
        self.fault_log = []   # (t, junction, detector, reason)

    def poll_detectors(self, now):
        for aid in self._prev_present:
            fault = self.faults.get(aid)
            if fault == "stuck_on":
                new = {"PHANTOM_%d" % int(now * 10)}
                self._entry_count[aid] += 1
                self._entry_times[aid].append(now)
                self._prev_present[aid] = frozenset(new)
                continue
            if fault == "stuck_off":
                self._audit("inductionloop.getLastStepVehicleIDs")
                traci.inductionloop.getLastStepVehicleIDs(aid)  # still "read" it, just ignore result
                self._prev_present[aid] = frozenset()
                continue
            self._audit("inductionloop.getLastStepVehicleIDs")
            cur = frozenset(traci.inductionloop.getLastStepVehicleIDs(aid))
            new = cur - self._prev_present[aid]
            if new:
                self._entry_count[aid] += len(new)
                self._entry_times[aid].append(now)
            self._prev_present[aid] = cur

    def _detect_faults(self, now):
        """Returns set of (junction, dir) pairs currently flagged faulted, and
        records why. Runs EVERY tick regardless of enable_failsafe (so the
        unprotected run's fault_log shows what a plausibility check WOULD
        have caught, for the report's 'quantify the damage' comparison)."""
        faulted = set()
        for (j, d), ids in self.adv_ids.items():
            for aid in ids:
                cnt = self._entry_count[aid]
                rate = cnt / self._window_len * 3600.0 if self._window_len > 0 else 0.0
                is_stuck_on = rate > PLAUSIBLE_MAX_VPH
                if cnt == 0:
                    self._zero_ticks[aid] += 1
                else:
                    self._zero_ticks[aid] = 0
                sb_ids = ["SB_%s_%s_0" % (j, d)]
                real_traffic = False
                try:
                    real_traffic = any(traci.lanearea.getLastStepVehicleNumber(s) > 0 for s in sb_ids)
                except Exception:
                    pass
                is_stuck_off = self._zero_ticks[aid] >= STUCK_OFF_TICKS and real_traffic
                if is_stuck_on or is_stuck_off:
                    faulted.add((j, d))
                    reason = ("stuck_on(rate=%.0f)" % rate if is_stuck_on else
                              "stuck_off(zero_ticks=%d,real_traffic=%s)" % (self._zero_ticks[aid], real_traffic))
                    self.fault_log.append((now, j, aid, reason))
        return faulted

    def _dos_hat(self, j, d, green_now, n_lanes):
        faulted = getattr(self, "_current_faulted", set())
        if self.enable_failsafe and (j, d) in faulted:
            self._audit("failsafe_safe_default_dos")
            return 0.70   # trusted safe-default DoS, not the corrupted reading
        return super(RobustSystemController, self)._dos_hat(j, d, green_now, n_lanes)

    def _adapt(self, now):
        faulted = self._detect_faults(now)
        self._current_faulted = faulted
        for j, d in faulted:
            self._fault_flag[j] = True
        super(RobustSystemController, self)._adapt(now)
        if self.enable_failsafe:
            # explicit FALLBACK-TO-FIXED-PLAN for any junction with a currently
            # faulted approach: override its split with the static default,
            # rather than trusting the (safe-defaulted, but still adaptive)
            # split the base layer computed above.
            for j in {jj for jj, dd in faulted}:
                plant = self.plants[j]
                plant.set_plan(art_main=self.default_plan["art_main"],
                               art_left=self.default_plan["art_left"],
                               cross=self.default_plan["cross"])
