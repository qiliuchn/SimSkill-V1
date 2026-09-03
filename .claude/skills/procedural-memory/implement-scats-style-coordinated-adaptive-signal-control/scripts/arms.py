#!/usr/bin/env python3
"""Comparison arms (sub-goal 4), all sharing controller_core.JunctionPlant and
the same network/detector/demand/incident infrastructure as the adaptive
controller, so only the SIGNAL-CONTROL MECHANISM differs between arms:

  (a) fixed_time      -- one Webster-optimized (webster_plan.py) static plan,
                          progression offsets, for the whole run.
  (b) waut             -- 3 Webster-like plans matched to the KNOWN/scheduled
                          stationary -> reversal -> post-reversal profile,
                          switched at t=1200/2100 (see
                          switch-signal-plans-by-time-of-day-with-waut) --
                          note this ToD schedule is never told about the
                          UNPRED regime's unannounced surge/incident.
  (c) actuated_uncoord -- SUMO's native per-junction gap-based actuated logic
                          (no coordination at all) -- run command-line only
                          on net/arterial_actuated.net.xml, no code here.
  (d) coord_actuated   -- fixed Webster cycle/offset/nominal-splits, but each
                          stage may GAP OUT EARLY (never run long) based on
                          stop-bar occupancy -- "actuated splits inside a
                          fixed background cycle and offset".
  (f) maxpressure      -- implement-maxpressure-traci-controller's controller,
                          applied unchanged to this network (fully generic).

(e) adaptive is controller/adaptive_system.py, run via run_adaptive.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "demand"))
SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from controller_core import JunctionPlant, is_green  # noqa: E402
from webster_plan import compute_plan, average_demand_rates, S_MEAS, ART_LEFT_FIXED  # noqa: E402

N_INT = 5
PROG_SPEED = 13.89 * 0.9   # calibrated progression speed (design-arterial-signal-progression finding)
SPACING = 400.0
GAP_OUT_S = 3.0            # actuated gap-out threshold


def progression_offsets(C):
    return [((i * SPACING) / PROG_SPEED) % C for i in range(N_INT)]


class BasePlants(object):
    def __init__(self, min_green=8.0):
        self.plants = {j: JunctionPlant(j, min_green=min_green) for j in
                       ["J%d" % i for i in range(N_INT)]}


# ---------------------------------------------------------------- (a) fixed
def make_fixed(regime, min_green=8.0):
    plan = compute_plan(regime)
    bp = BasePlants(min_green)
    offs = progression_offsets(plan["C"])
    for i, j in enumerate(bp.plants):
        pass
    for i in range(N_INT):
        j = "J%d" % i
        p = bp.plants[j]
        p.set_plan(art_main=plan["art_main"], art_left=plan["art_left"], cross=plan["cross"])
        p.start(0.0, warm_start_elapsed=offs[i])

    def step(now):
        for p in bp.plants.values():
            p.step(now)
    return bp, step, plan


# ---------------------------------------------------------------- (b) waut
WAUT_SWITCH_1, WAUT_SWITCH_2 = 1200.0, 2100.0


def _period_plan(regime, t0, t1):
    from rate_schedule import thru_rate
    import numpy as np
    ts = np.linspace(t0, t1, 40)
    eb = np.mean([thru_rate("EB", t, regime) for t in ts])
    wb = np.mean([thru_rate("WB", t, regime) for t in ts])
    from webster_plan import WebsterDesign, L1, YELLOW, ALLRED, CROSS_RATE_TOTAL
    q_art = max(eb, wb) + 70.0
    wd = WebsterDesign(s_vph=S_MEAS, l1=L1, l2=YELLOW, yellow=YELLOW, allred=ALLRED)
    crit = [q_art / 2.0, CROSS_RATE_TOTAL / 1.0]
    c_opt, Y, L = wd.c_opt(crit)
    if c_opt is None:
        c_opt = 150.0
    c_opt = max(30.0, min(150.0, c_opt))
    geff, gdisp = wd.splits(c_opt, crit, min_green=10.0)
    fixed_overhead = 3 * YELLOW
    avail = c_opt - fixed_overhead - ART_LEFT_FIXED
    ratio = gdisp[0] / (gdisp[0] + gdisp[1])
    g_art = max(10.0, avail * ratio)
    return dict(C=c_opt, art_main=g_art, art_left=ART_LEFT_FIXED, cross=avail - g_art)


def make_waut(regime, min_green=8.0):
    plan_am = _period_plan(regime, 0.0, WAUT_SWITCH_1)
    plan_mid = _period_plan(regime, WAUT_SWITCH_1, WAUT_SWITCH_2)
    plan_pm = _period_plan(regime, WAUT_SWITCH_2, 3900.0)
    bp = BasePlants(min_green)
    offs = progression_offsets(plan_am["C"])
    for i in range(N_INT):
        j = "J%d" % i
        p = bp.plants[j]
        p.set_plan(art_main=plan_am["art_main"], art_left=plan_am["art_left"], cross=plan_am["cross"])
        p.start(0.0, warm_start_elapsed=offs[i])
    state = {"switched1": False, "switched2": False}

    def step(now):
        if not state["switched1"] and now >= WAUT_SWITCH_1:
            offs2 = progression_offsets(plan_mid["C"])
            for i in range(N_INT):
                j = "J%d" % i
                bp.plants[j].set_plan(art_main=plan_mid["art_main"], art_left=plan_mid["art_left"],
                                      cross=plan_mid["cross"])
            state["switched1"] = True
        if not state["switched2"] and now >= WAUT_SWITCH_2:
            for i in range(N_INT):
                j = "J%d" % i
                bp.plants[j].set_plan(art_main=plan_pm["art_main"], art_left=plan_pm["art_left"],
                                      cross=plan_pm["cross"])
            state["switched2"] = True
        for p in bp.plants.values():
            p.step(now)
    return bp, step, dict(am=plan_am, mid=plan_mid, pm=plan_pm)


# ------------------------------------------------------- (d) coord-actuated
class GapActuatedPlant(JunctionPlant):
    """Same fixed cycle/offset/nominal-split plan as arm (a), but a stage may
    end EARLY (gap-out) if its stop-bar detectors show no vehicle for
    GAP_OUT_S seconds after min_green -- never later than the nominal
    duration. This is 'actuated splits inside a fixed background cycle and
    offset' -- the network keeps its shared cycle/offset (coordination is
    preserved) while reclaiming unused green like native actuated control."""

    def __init__(self, tls_id, min_green, stopbar_ids):
        super(GapActuatedPlant, self).__init__(tls_id, min_green=min_green)
        self.stopbar_ids = stopbar_ids   # kind -> [det ids]
        self._last_veh_t = {}

    def step(self, now):
        s = self.order[self.cur_i]
        if self.mode == "GREEN" and s.kind in self.stopbar_ids:
            occ = any(traci.lanearea.getLastStepVehicleNumber(d) > 0 for d in self.stopbar_ids[s.kind])
            if occ:
                self._last_veh_t[s.kind] = now
            last = self._last_veh_t.get(s.kind, now)
            nominal = self.plan[s.kind]
            elapsed = now - self.green_since
            if elapsed >= s.min_green and (now - last) >= GAP_OUT_S and elapsed < nominal:
                # force early end by temporarily shrinking this activation only
                self.plan[s.kind] = elapsed
                super(GapActuatedPlant, self).step(now)
                self.plan[s.kind] = nominal
                return
        super(GapActuatedPlant, self).step(now)


def make_coord_actuated(regime, min_green=8.0):
    plan = compute_plan(regime)
    plants = {}
    for i in range(N_INT):
        j = "J%d" % i
        sb = {"ART_MAIN": ["SB_%s_EB_0" % j, "SB_%s_EB_1" % j, "SB_%s_WB_0" % j, "SB_%s_WB_1" % j],
              "CROSS": ["SB_%s_SB_0" % j]}
        plants[j] = GapActuatedPlant(j, min_green, sb)
    offs = progression_offsets(plan["C"])
    for i in range(N_INT):
        j = "J%d" % i
        plants[j].set_plan(art_main=plan["art_main"], art_left=plan["art_left"], cross=plan["cross"])
        plants[j].start(0.0, warm_start_elapsed=offs[i])

    def step(now):
        for p in plants.values():
            p.step(now)
    return plants, step, plan


# --------------------------------------------------------------- (f) max-pressure
HOLD = 100000.0
ALLRED_CAP = 12.0


class MPJunctionController(object):
    """implement-maxpressure-traci-controller's JunctionController, reused
    essentially verbatim (queue-based pressure(phase)=up-down halting count,
    min-green, yellow/all-red clearance introspected from the program) --
    applied unchanged to this study's network."""

    def __init__(self, tls_id, min_green, decision_interval):
        self.tls = tls_id
        self.min_green = min_green
        self.decision_interval = decision_interval
        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
        self.phases = logic.phases
        self.n = len(self.phases)
        links = traci.trafficlight.getControlledLinks(tls_id)
        self.green_phases = [i for i, p in enumerate(self.phases) if is_green(p.state)]
        self.phase_in, self.phase_out, self.phase_via = {}, {}, {}
        for gi in self.green_phases:
            state = self.phases[gi].state
            inc, out, via = set(), set(), set()
            for idx, ch in enumerate(state):
                if ch in ("G", "g") and idx < len(links):
                    for link in links[idx]:
                        if link and link[0]:
                            inc.add(link[0])
                        if link and link[1]:
                            out.add(link[1])
                        if link and len(link) > 2 and link[2]:
                            via.add(link[2])
            self.phase_in[gi], self.phase_out[gi], self.phase_via[gi] = list(inc), list(out), list(via)
        self.clearance, self.allred = {}, {}
        for gi in self.green_phases:
            y, r = self._following_clearance(gi)
            self.clearance[gi], self.allred[gi] = y, r
        self.mode = "GREEN"
        self.cur_green = self.green_phases[0]
        self.target_green = self.cur_green
        self.vacating_green = self.cur_green
        self.green_since = 0.0
        self.yellow_until = 0.0
        self.allred_min_until = 0.0
        self.allred_cap_until = 0.0
        self.last_decision = -1e9

    def _following_clearance(self, gi):
        yellow = allred = None
        for step in range(1, self.n + 1):
            j = (gi + step) % self.n
            state = self.phases[j].state
            if yellow is None and ("y" in state):
                yellow = j
                continue
            if yellow is not None:
                if ("G" not in state) and ("g" not in state) and ("y" not in state):
                    allred = j
                break
            if j in self.green_phases:
                break
        return yellow, allred

    def start(self, now):
        traci.trafficlight.setPhase(self.tls, self.cur_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.green_since = now

    def _pressure(self, gi):
        up = sum(traci.lane.getLastStepHaltingNumber(l) for l in self.phase_in[gi])
        down = sum(traci.lane.getLastStepHaltingNumber(l) for l in self.phase_out[gi])
        return up - down

    def step(self, now):
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
                    self._commit(now)
            return
        if self.mode == "ALLRED":
            past_min = now >= self.allred_min_until
            past_cap = now >= self.allred_cap_until
            via = self.phase_via.get(self.vacating_green, [])
            clear = all(traci.lane.getLastStepVehicleNumber(l) == 0 for l in via) if via else True
            if past_cap or (past_min and clear):
                self._commit(now)
            return
        if now - self.green_since < self.min_green:
            return
        if now - self.last_decision < self.decision_interval:
            return
        self.last_decision = now
        pressures = {gi: self._pressure(gi) for gi in self.green_phases}
        best = max(pressures, key=lambda g: pressures[g])
        if best == self.cur_green or pressures[best] <= pressures[self.cur_green]:
            return
        yellow = self.clearance[self.cur_green]
        self.vacating_green = self.cur_green
        self.target_green = best
        if yellow is None:
            self._commit(now)
            return
        traci.trafficlight.setPhase(self.tls, yellow)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.mode = "YELLOW"
        self.yellow_until = now + self.phases[yellow].duration

    def _commit(self, now):
        traci.trafficlight.setPhase(self.tls, self.target_green)
        traci.trafficlight.setPhaseDuration(self.tls, HOLD)
        self.cur_green = self.target_green
        self.mode = "GREEN"
        self.green_since = now


def make_maxpressure(min_green=8.0, decision_interval=5.0):
    ctrls = {}

    def step(now):
        for c in ctrls.values():
            c.step(now)

    def start():
        for j in traci.trafficlight.getIDList():
            ctrls[j] = MPJunctionController(j, min_green, decision_interval)
            ctrls[j].start(0.0)
    return ctrls, step, start
