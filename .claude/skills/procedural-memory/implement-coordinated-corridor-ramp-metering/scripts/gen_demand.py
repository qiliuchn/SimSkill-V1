#!/usr/bin/env python3
"""Time-varying peak demand for the corridor, generated with COMMON RANDOM NUMBERS.

Every vehicle's depart time (Poisson/exponential headways), route and speedFactor
are drawn from a python RNG seeded ONLY by (seed), independent of the control arm.
The identical .rou.xml is therefore reused byte-for-byte by every control arm at a
given (seed, demand level) -- true CRN, per
`quantify-sumo-run-to-run-variability` / [[sumo-stochastic-variability-and-replication-design]].

Profile: build-up -> peak -> recovery.
"""
import argparse
import math
import os
import random

ROUTES = {
    # freeway demand (scaled by --demand)
    "ml_thru":  ("fwy", "ml_0 ml_1 ml_2 ml_3 ml_4 ml_5 ml_6",                     3350.0),
    "ml_off1":  ("fwy", "ml_0 ml_1 o1_off",                                        500.0),
    "ml_off2":  ("fwy", "ml_0 ml_1 ml_2 ml_3 o2_off",                              600.0),
    "r1_thru":  ("ramp", "r1_sapp r1_stor r1_mrg ml_1 ml_2 ml_3 ml_4 ml_5 ml_6",   620.0),
    "r1_off2":  ("ramp", "r1_sapp r1_stor r1_mrg ml_1 ml_2 ml_3 o2_off",           130.0),
    "r2_thru":  ("ramp", "r2_sapp r2_stor r2_mrg ml_3 ml_4 ml_5 ml_6",             590.0),
    "r2_off2":  ("ramp", "r2_sapp r2_stor r2_mrg ml_3 o2_off",                     110.0),
    "r3_thru":  ("ramp", "r3_sapp r3_stor r3_mrg ml_5 ml_6",                       700.0),
    # surface demand (NOT scaled -- so surface delay changes come purely from
    # ramp-queue spillback, not from a different surface loading)
    "s1_thru":  ("surf", "r1_sapp r1_sout",                                        500.0),
    "s2_thru":  ("surf", "r2_sapp r2_sout",                                        500.0),
    "s3_thru":  ("surf", "r3_sapp r3_sout",                                        500.0),
    "c1_thru":  ("surf", "r1_capp r1_cout",                                        300.0),
    "c2_thru":  ("surf", "r2_capp r2_cout",                                        300.0),
    "c3_thru":  ("surf", "r3_capp r3_cout",                                        300.0),
}

# (t_start, t_end, multiplier_start, multiplier_end) -- linear ramp between
PROFILE = [(0, 600, 0.55, 0.55),
           (600, 1500, 0.55, 1.00),
           (1500, 3900, 1.00, 1.00),
           (3900, 4800, 1.00, 0.50),
           (4800, 5400, 0.50, 0.45)]
T_END_DEMAND = 5400


def mult(t):
    for a, b, m0, m1 in PROFILE:
        if a <= t < b:
            return m0 + (m1 - m0) * (t - a) / (b - a)
    return 0.0


def gen(seed, demand, out, warm_surface=True):
    rng = random.Random(1000003 * seed + 7)
    vehs = []
    for rid, (cls, edges, base) in sorted(ROUTES.items()):
        scale = demand if cls in ("fwy", "ramp") else 1.0
        t = 0.0
        # thinning-free direct sampling: piecewise-linear rate, small dt integration
        # use exponential headways against the instantaneous rate
        while t < T_END_DEMAND:
            rate = base * scale * mult(t) / 3600.0      # veh/s
            if rate <= 1e-9:
                t += 1.0
                continue
            t += rng.expovariate(rate)
            if t >= T_END_DEMAND:
                break
            vehs.append((t, rid, cls, edges, rng.gauss(1.0, 0.10)))
    vehs.sort()
    lines = ['<routes>']
    lines.append('  <vType id="car" vClass="passenger" length="5.0" minGap="2.5" '
                 'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" maxSpeed="40.0" '
                 'speedFactor="1.0" speedDev="0.0" carFollowModel="Krauss" '
                 'lcStrategic="1.0" lcCooperative="1.0" lcSpeedGain="1.0" lcKeepRight="1.0"/>')
    seen = {}
    for rid, (cls, edges, base) in sorted(ROUTES.items()):
        lines.append(f'  <route id="{rid}" edges="{edges}"/>')
    for i, (t, rid, cls, edges, sf) in enumerate(vehs):
        sf = max(0.70, min(1.35, sf))
        # ramp-bound vehicles must use the terminal's LEFT lane (lane 1); surface
        # through traffic takes the least-occupied lane.
        dl = "1" if rid.startswith(("r1_", "r2_", "r3_")) else ("free" if cls == "surf" else "best")
        lines.append(f'  <vehicle id="{rid}.{i}" type="car" route="{rid}" depart="{t:.2f}" '
                     f'departLane="{dl}" departSpeed="max" speedFactor="{sf:.4f}"/>')
    lines.append('</routes>')
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").write("\n".join(lines) + "\n")
    return len(vehs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--demand", type=float, default=1.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    n = gen(a.seed, a.demand, a.out)
    print(f"{a.out}: {n} vehicles (seed={a.seed}, demand={a.demand})")
