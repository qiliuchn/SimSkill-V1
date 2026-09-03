#!/usr/bin/env python3
"""SUB-GOAL 2 validation -- INDEPENDENT analytical integration of the truck
equation of motion, written fresh (does not import physics_model.py's
accel_from_grade_percent), used only to cross-check the TraCI controller's
realized open-road trajectory against a standalone RK4 numerical integration
of the same physical equations. Agreement here is evidence the TraCI
controller is applying the intended physics correctly (a coding-bug check),
not evidence the physics themselves are "true" -- see the report for the
separate cross-check against published AASHTO truck-performance-curve shape.
"""
import math


def rk4_truck_trajectory(v0, grade_pct, mass_kg, power_w, eta=0.85, cr=0.007,
                          cd=0.6, area=9.0, rho=1.225, g=9.81, v_floor=1.0,
                          dt=0.1, t_end=300.0, governor_speed=None):
    """Independently-typed RK4 integration of dv/dt = a(v) for a heavy vehicle
    climbing (or descending) a constant grade under constant rated power,
    rolling resistance, and quadratic aerodynamic drag. Returns a list of
    (t, distance_m, v_m_s) samples.
    """
    theta = math.atan(grade_pct / 100.0)
    f_grade = mass_kg * g * math.sin(theta)
    f_roll = mass_kg * g * cr * math.cos(theta)
    f_trac_cap = 0.6 * mass_kg * g * 0.5

    def dvdt(v):
        v_eff = max(v, v_floor)
        f_trac = min(power_w * eta / v_eff, f_trac_cap)
        f_aero = 0.5 * rho * cd * area * v * v
        a = (f_trac - f_grade - f_roll - f_aero) / mass_kg
        a = max(-6.0, min(2.2, a))
        if governor_speed is not None and v >= governor_speed and a > 0:
            a = 0.0
        return a

    t = 0.0
    v = v0
    d = 0.0
    out = [(t, d, v)]
    n = int(t_end / dt)
    for _ in range(n):
        k1 = dvdt(v)
        k2 = dvdt(v + 0.5 * dt * k1)
        k3 = dvdt(v + 0.5 * dt * k2)
        k4 = dvdt(v + dt * k3)
        a_avg = (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
        v_new = max(0.0, v + dt * a_avg)
        d += 0.5 * (v + v_new) * dt
        t += dt
        v = v_new
        out.append((round(t, 2), round(d, 3), round(v, 4)))
        if governor_speed is not None and abs(v - governor_speed) < 1e-4 and a_avg <= 0:
            pass  # allow settling at governor speed
    return out


def crawl_speed(grade_pct, mass_kg, power_w, eta=0.85, cr=0.007, cd=0.6, area=9.0,
                 rho=1.225, g=9.81, v_floor=1.0):
    """Bisection solve for the equilibrium (a=0) terminal speed -- the
    analytical crawl speed -- independent of the time-stepped integration
    above, as a second independent check."""
    theta = math.atan(grade_pct / 100.0)
    f_grade = mass_kg * g * math.sin(theta)
    f_roll = mass_kg * g * cr * math.cos(theta)
    f_trac_cap = 0.6 * mass_kg * g * 0.5

    def net(v):
        v_eff = max(v, v_floor)
        f_trac = min(power_w * eta / v_eff, f_trac_cap)
        f_aero = 0.5 * rho * cd * area * v * v
        return f_trac - f_grade - f_roll - f_aero

    lo, hi = 0.01, 60.0
    if net(hi) > 0:
        return hi  # never converges within range -> essentially uncapped by this grade
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if net(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


if __name__ == "__main__":
    mass = 36287.0
    for ratio in (90, 120, 180):
        power = mass / ratio * 1000.0
        print("--- weight/power = %d kg/kW (P=%.1f kW) ---" % (ratio, power / 1000.0))
        for grade in (0, 2, 4, 6):
            cs = crawl_speed(grade, mass, power)
            print("  grade=%d%%  analytical crawl speed = %.2f m/s = %.1f km/h = %.1f mph" %
                  (grade, cs, cs * 3.6, cs * 2.23694))
