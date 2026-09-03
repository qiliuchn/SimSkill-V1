#!/usr/bin/env python3
"""SUB-GOAL 2 -- the chosen grade-aware heavy-vehicle performance model.

Mechanism (candidate #1 of three enumerated -- see module docstring in
run_single.py / the action-agent report for the enumeration and why the
other two were rejected): a per-step TraCI controller that maintains, for
each truck, a physically-attainable "ceiling speed" v_attain integrated from
a constant-power tractive-effort equation of motion:

    F_trac(v)  = min(P * eta / max(v, v_floor), F_trac_cap)
    F_grade(v) = m * g * sin(atan(grade_frac))          (grade_frac = tan(slope_deg))
    F_roll     = m * g * Cr
    F_aero(v)  = 0.5 * rho * Cd * A * v^2
    a(v)       = (F_trac - F_grade - F_roll - F_aero) / m

v_attain is integrated forward each step with the ACTUAL (possibly
traffic-suppressed) speed as a floor: v_base = min(v_attain_prev, v_actual).
This makes the model behave correctly in three regimes:
  - free flow on a grade: v_attain converges to the grade's power-limited
    terminal (crawl) speed, exactly the AASHTO truck-performance-curve
    quantity;
  - free flow on flat/downhill: v_attain converges to a power-limited
    terminal speed that can sit below the desired/legal speed for an
    underpowered truck (also physically correct), capped by v_governor so a
    truck never uses gravity to exceed its own desired cruise speed;
  - congested / following a slower lead vehicle: v_base tracks the
    (suppressed) actual speed, so v_attain is never allowed to run away to a
    stale high ceiling -- when the truck is released from the queue it
    re-accelerates under the SAME power-limited dynamics from where it
    actually is, not from an artificial full-speed ceiling.

v_attain is applied ONLY as a ceiling via traci.vehicle.setMaxSpeed(). The
underlying car-following model (whatever it is -- Krauss/IDM/etc.) still
owns all safety-relevant behavior (safe gap, emergency braking, response to
a lead vehicle); this controller never calls setSpeed/setAcceleration, so it
cannot disable car-following safety by construction. This directly answers
the sub-goal-2 requirement to prove the mechanism doesn't disable safety and
is non-binding under traffic constraint.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import G, RHO_AIR, DEFAULT_MASS_KG, DEFAULT_CR, DEFAULT_CD, DEFAULT_A, DEFAULT_ETA, V_FLOOR

try:
    import traci
    import traci.constants as tc
except Exception:
    traci = None
    tc = None

MAX_ACCEL_CAP = 2.2   # m/s^2, sanity cap on power-limited accel (~engine/traction realism)


def accel_from_grade_percent(v, grade_percent, **kwargs):
    """Convenience wrapper taking grade as a PERCENT (dz/dx*100), the
    quantity used everywhere else in this study (network authoring,
    reporting). Internally converts percent -> the angle used in the force
    balance. Kept as a separate thin wrapper so callers never have to reason
    about the percent-vs-degrees mismatch between network authoring and
    traci.vehicle.getSlope() (which returns DEGREES, verified empirically --
    see units_test in the action-agent transcript / probe1)."""
    grade_frac = grade_percent / 100.0
    theta = math.atan(grade_frac)
    mass_kg = kwargs.pop("mass_kg", DEFAULT_MASS_KG)
    power_w = kwargs.pop("power_w", None)
    eta = kwargs.pop("eta", DEFAULT_ETA)
    cr = kwargs.pop("cr", DEFAULT_CR)
    cd = kwargs.pop("cd", DEFAULT_CD)
    area = kwargs.pop("area", DEFAULT_A)
    rho = kwargs.pop("rho", RHO_AIR)
    g = kwargs.pop("g", G)
    v_floor = kwargs.pop("v_floor", V_FLOOR)
    f_trac_cap = kwargs.pop("f_trac_cap", None)
    if power_w is None:
        power_w = mass_kg / 120.0 * 1000.0
    f_grade = mass_kg * g * math.sin(theta)
    f_roll = mass_kg * g * cr * math.cos(theta)
    f_aero = 0.5 * rho * cd * area * v * v
    v_eff = max(v, v_floor)
    f_trac = power_w * eta / v_eff
    if f_trac_cap is None:
        f_trac_cap = 0.6 * mass_kg * g * 0.5
    f_trac = min(f_trac, f_trac_cap)
    f_net = f_trac - f_grade - f_roll - f_aero
    a = f_net / mass_kg
    return max(-6.0, min(MAX_ACCEL_CAP, a))


class GradeAwareController:
    """Per-step TraCI controller applied AFTER traci.simulationStep(). Tracks
    v_attain per registered truck and applies it as a setMaxSpeed ceiling.
    Uses subscriptions (VAR_SPEED, VAR_SLOPE) + getAllSubscriptionResults for
    a single bulk call per step rather than per-vehicle round trips.
    """

    def __init__(self, weight_to_power_kg_per_kw=120.0, mass_kg=DEFAULT_MASS_KG,
                 governor_speed=None, eta=DEFAULT_ETA, cr=DEFAULT_CR, cd=DEFAULT_CD,
                 area=DEFAULT_A, truck_prefix="hv_"):
        self.ratio = weight_to_power_kg_per_kw
        self.mass_kg = mass_kg
        self.power_w = mass_kg / weight_to_power_kg_per_kw * 1000.0
        self.governor_speed = governor_speed  # m/s cap representing desired-speed compliance; None = uncapped
        self.eta = eta
        self.cr = cr
        self.cd = cd
        self.area = area
        self.truck_prefix = truck_prefix
        self.v_attain = {}
        self.known = set()
        self.call_count = 0
        self.n_steps = 0

    def _maybe_subscribe(self, vid):
        if vid in self.known:
            return
        traci.vehicle.subscribe(vid, [tc.VAR_SPEED, tc.VAR_SLOPE])
        self.call_count += 1
        self.known.add(vid)
        self.v_attain[vid] = max(0.0, traci.vehicle.getSpeed(vid))
        self.call_count += 1

    def step(self, dt=1.0):
        """Call once per simulation step, AFTER traci.simulationStep()."""
        self.n_steps += 1
        ids = traci.vehicle.getIDList()
        self.call_count += 1
        trucks = [v for v in ids if v.startswith(self.truck_prefix)]
        for vid in trucks:
            self._maybe_subscribe(vid)
        results = traci.vehicle.getAllSubscriptionResults()
        self.call_count += 1
        for vid in trucks:
            r = results.get(vid)
            if r is None:
                continue
            v_actual = r.get(tc.VAR_SPEED, self.v_attain.get(vid, 0.0))
            slope_deg = r.get(tc.VAR_SLOPE, 0.0)
            grade_pct = 100.0 * math.tan(math.radians(slope_deg))
            v_prev = self.v_attain.get(vid, v_actual)
            v_base = min(v_prev, v_actual) if v_actual >= 0 else v_prev
            a = accel_from_grade_percent(v_base, grade_pct, mass_kg=self.mass_kg,
                                          power_w=self.power_w, eta=self.eta, cr=self.cr,
                                          cd=self.cd, area=self.area)
            v_new = v_base + a * dt
            if v_new < 0.0:
                v_new = 0.0
            if self.governor_speed is not None:
                v_new = min(v_new, self.governor_speed)
            self.v_attain[vid] = v_new
            traci.vehicle.setMaxSpeed(vid, max(v_new, 0.2))
            self.call_count += 1
        # drop stale entries for vehicles that left
        gone = self.known - set(ids)
        for vid in gone:
            self.known.discard(vid)
            self.v_attain.pop(vid, None)

    def stats(self):
        return {"traci_call_count": self.call_count, "n_steps": self.n_steps,
                "ratio_kg_per_kw": self.ratio, "power_w": self.power_w, "mass_kg": self.mass_kg}
