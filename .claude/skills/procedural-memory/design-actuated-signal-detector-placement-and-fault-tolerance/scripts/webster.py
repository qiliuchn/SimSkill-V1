#!/usr/bin/env python3
"""Webster fixed-time plan from the MEASURED saturation flows."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tls_common import GREEN_ORDER, GREEN_PHASES
from make_demand import BASE, LEVELS

LOST_PER_PHASE = 4.0          # 3 s yellow + 1 s all-red, all treated as lost
TOTAL_LOST = LOST_PER_PHASE * len(GREEN_ORDER)     # L = 16 s
MIN_GREEN = 7.0
MAX_CYCLE = 120.0

# critical-lane demand per green phase at scale 1.0 (veh/h on the critical lane)
CRIT_Q = {
    0: BASE["WC"][0] + BASE["WC"][1],   # major through + right share lane _0
    3: BASE["WC"][2],                   # major left, lane _1
    6: BASE["NC"][0] + BASE["NC"][1],   # minor through + right
    9: BASE["NC"][2],                   # minor left
}


def load_satflow(path):
    raw = json.load(open(path))
    s = {}
    for gp in GREEN_ORDER:
        lanes = GREEN_PHASES[gp]["lanes"]
        vals = [raw[l]["sat_flow"] for l in lanes if raw[l]["sat_flow"]]
        s[gp] = sum(vals) / len(vals)
    return s


def plan(level, satflow):
    scale = LEVELS[level]
    y = {gp: CRIT_Q[gp] * scale / satflow[gp] for gp in GREEN_ORDER}
    Y = sum(y.values())
    capped = False
    if Y >= 0.95:
        C = MAX_CYCLE
        capped = True
    else:
        C = (1.5 * TOTAL_LOST + 5.0) / (1.0 - Y)
        if C > MAX_CYCLE:
            C, capped = MAX_CYCLE, True
        C = max(C, TOTAL_LOST + MIN_GREEN * len(GREEN_ORDER))
    Gtot = C - TOTAL_LOST
    g = {gp: Gtot * y[gp] / Y for gp in GREEN_ORDER}
    # enforce minimum green, redistribute the remainder proportionally
    for _ in range(6):
        short = [gp for gp in GREEN_ORDER if g[gp] < MIN_GREEN]
        if not short:
            break
        for gp in short:
            g[gp] = MIN_GREEN
        rest = [gp for gp in GREEN_ORDER if gp not in short]
        avail = Gtot - MIN_GREEN * len(short)
        ysum = sum(y[gp] for gp in rest)
        for gp in rest:
            g[gp] = avail * y[gp] / ysum
    g = {gp: max(MIN_GREEN, round(g[gp])) for gp in GREEN_ORDER}
    cycle = sum(g.values()) + TOTAL_LOST
    return dict(level=level, scale=scale, y={str(k): round(v, 4) for k, v in y.items()},
                Y=round(Y, 4), cycle_raw=round(C, 1), cycle=cycle,
                capped=capped, green={str(k): g[k] for k in GREEN_ORDER},
                deg_sat={str(gp): round(CRIT_Q[gp] * scale / satflow[gp] * cycle / g[gp], 3)
                         for gp in GREEN_ORDER})


def all_plans(satflow_json):
    s = load_satflow(satflow_json)
    return {lvl: plan(lvl, s) for lvl in LEVELS}, s


if __name__ == "__main__":
    plans, s = all_plans(sys.argv[1])
    print("measured saturation flow per phase (veh/h/lane):")
    for gp in GREEN_ORDER:
        print(f"  {GREEN_PHASES[gp]['name']:14s} {s[gp]:7.1f}")
    for lvl, p in plans.items():
        print(f"\n{lvl}: Y={p['Y']}  C_webster={p['cycle_raw']}s "
              f"-> C={p['cycle']}s (capped={p['capped']})")
        for gp in GREEN_ORDER:
            print(f"   {GREEN_PHASES[gp]['name']:14s} G={p['green'][str(gp)]:3.0f}s "
                  f"x_deg_sat={p['deg_sat'][str(gp)]}")
    json.dump(plans, open(sys.argv[2], "w"), indent=2)
