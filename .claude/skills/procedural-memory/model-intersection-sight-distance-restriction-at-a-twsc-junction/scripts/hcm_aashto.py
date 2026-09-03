#!/usr/bin/env python3
"""
Analytical references: HCM 6th Ed. Chapter 20 (TWSC gap-acceptance capacity) and
AASHTO Green Book Chapter 9 Case B intersection sight distance (ISD).

HCM TWSC potential capacity (random / exponential conflicting headways):
    c_p,x = v_c,x * exp(-v_c,x * t_c,x / 3600) / (1 - exp(-v_c,x * t_f,x / 3600))

Base critical headways / follow-up headways, two-lane major street (Exhibits
20-11 / 20-12), passenger cars:
    minor-street LEFT     t_c = 7.1  t_f = 3.5
    minor-street THROUGH  t_c = 6.5  t_f = 4.0
    minor-street RIGHT    t_c = 6.2  t_f = 3.3
The movement studied here is the minor-street THROUGH (crossing) movement, so
t_c = 6.5 s, t_f = 4.0 s, and its conflicting flow is the TOTAL two-way major
volume (the major stream carries no turning movements in this testbed, so no
impedance / no rank-3 adjustment applies: c_m = c_p).

AASHTO Green Book Case B intersection sight distance, metric form:
    ISD = 0.278 * V_major[km/h] * t_g
with gap times t_g for passenger cars on a TWO-LANE major road:
    Case B1  left turn from the minor road      t_g = 7.5 s
    Case B2  right turn from the minor road     t_g = 6.5 s
    Case B3  crossing the major road            t_g = 6.5 s
(+0.5 s for each additional major-road lane to be crossed / traversed.)
"""
import math

TC_THROUGH, TF_THROUGH = 6.5, 4.0
TC_LEFT, TF_LEFT = 7.1, 3.5
TC_RIGHT, TF_RIGHT = 6.2, 3.3

TG = {"B1_left": 7.5, "B2_right": 6.5, "B3_crossing": 6.5}


def c_potential(v_c, t_c=TC_THROUGH, t_f=TF_THROUGH):
    """HCM gap-acceptance capacity, veh/h.  v_c in veh/h."""
    if v_c <= 0:
        return 3600.0 / t_f
    q = v_c / 3600.0
    return v_c * math.exp(-q * t_c) / (1.0 - math.exp(-q * t_f))


def c_regular(v_c, t_c=TC_THROUGH, t_f=TF_THROUGH):
    """Deterministic (equidistant) conflicting stream -- the staircase."""
    if v_c <= 0:
        return 3600.0 / t_f
    h0 = 3600.0 / v_c
    if h0 < t_c:
        return 0.0
    return v_c * (math.floor((h0 - t_c) / t_f) + 1)


def fit_tc_tf(vc, cap, t_c0=6.5, t_f0=4.0):
    """Least-squares fit of (t_c, t_f) to a measured (conflicting flow, capacity)
    curve under the HCM random-arrival form.  Plain Nelder-Mead so there is no
    scipy dependency."""
    vc = list(map(float, vc))
    cap = list(map(float, cap))

    def sse(p):
        tc, tf = p
        if tc <= 0 or tf <= 0.05:
            return 1e18
        return sum((c_potential(v, tc, tf) - c) ** 2 for v, c in zip(vc, cap))

    # simple Nelder-Mead
    pts = [[t_c0, t_f0], [t_c0 + 1.0, t_f0], [t_c0, t_f0 + 0.5]]
    vals = [sse(p) for p in pts]
    for _ in range(4000):
        idx = sorted(range(3), key=lambda i: vals[i])
        pts = [pts[i] for i in idx]
        vals = [vals[i] for i in idx]
        if abs(vals[2] - vals[0]) < 1e-10:
            break
        cen = [(pts[0][j] + pts[1][j]) / 2.0 for j in range(2)]
        ref = [cen[j] + 1.0 * (cen[j] - pts[2][j]) for j in range(2)]
        fr = sse(ref)
        if fr < vals[0]:
            exp_ = [cen[j] + 2.0 * (cen[j] - pts[2][j]) for j in range(2)]
            fe = sse(exp_)
            pts[2], vals[2] = (exp_, fe) if fe < fr else (ref, fr)
        elif fr < vals[1]:
            pts[2], vals[2] = ref, fr
        else:
            con = [cen[j] + 0.5 * (pts[2][j] - cen[j]) for j in range(2)]
            fc = sse(con)
            if fc < vals[2]:
                pts[2], vals[2] = con, fc
            else:
                for i in (1, 2):
                    pts[i] = [(pts[i][j] + pts[0][j]) / 2.0 for j in range(2)]
                    vals[i] = sse(pts[i])
    i = min(range(3), key=lambda k: vals[k])
    tc, tf = pts[i]
    n = len(vc)
    rmse = math.sqrt(vals[i] / n) if n else None
    return {"t_c": tc, "t_f": tf, "sse": vals[i], "rmse_vph": rmse, "n": n}


def isd(v_kmh, case="B3_crossing", extra_lanes=0):
    """AASHTO Case B intersection sight distance, metres."""
    return 0.278 * v_kmh * (TG[case] + 0.5 * extra_lanes)


def design_speed_for_isd(leg_m, case="B3_crossing", extra_lanes=0):
    """Inverse: the highest major-road design speed for which a sight-triangle
    leg of `leg_m` metres satisfies AASHTO Case B."""
    return leg_m / (0.278 * (TG[case] + 0.5 * extra_lanes))


if __name__ == "__main__":
    import json
    tbl = {"hcm_twsc_through_tc6.5_tf4.0": {v: round(c_potential(v), 1)
                                            for v in (300, 500, 700, 800, 900, 1100, 1400)},
           "aashto_isd_m": {V: {c: round(isd(V, c), 1) for c in TG} for V in (40, 50, 70)},
           "design_speed_for_leg_kmh": {L: {c: round(design_speed_for_isd(L, c), 1) for c in TG}
                                        for L in (200, 120, 90, 60, 30, 15, 7.5, 4.5)}}
    print(json.dumps(tbl, indent=1))
