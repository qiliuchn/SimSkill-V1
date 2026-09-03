#!/usr/bin/env python3
"""Generate route files with EXPLICIT per-vehicle departure times.

Common Random Numbers: a route file is produced once per (demand level, seed)
and reused byte-identically by every detector/fault variant, so arrival streams
are exactly paired across the whole sweep.  Departures are Poisson (exponential
headways) drawn from a python RNG seeded by `seed`, NOT by SUMO's own RNG, so
they cannot be perturbed by anything happening inside the simulation.
"""
import os
import random
import sys

# base ("med") movement demand, veh/h per approach
BASE = {
    # approach: (through, right, left)
    "WC": (550, 80, 110),   # major, 60 km/h
    "EC": (550, 80, 110),
    "NC": (240, 60, 70),    # minor, 40 km/h
    "SC": (240, 60, 70),
}
DEST = {
    "WC": {"t": "CE", "r": "CS", "l": "CN"},
    "EC": {"t": "CW", "r": "CN", "l": "CS"},
    "SC": {"t": "CN", "r": "CE", "l": "CW"},
    "NC": {"t": "CS", "r": "CW", "l": "CE"},
}
LEVELS = {"low": 0.70, "med": 1.00, "high": 1.35}


def make(level, seed, horizon, out):
    scale = LEVELS[level]
    rng = random.Random(seed * 7919 + 13)
    vehs = []
    for ap, (thr, rgt, lft) in BASE.items():
        for mv, q in (("t", thr), ("r", rgt), ("l", lft)):
            rate = q * scale / 3600.0
            if rate <= 0:
                continue
            t = 0.0
            while True:
                t += rng.expovariate(rate)
                if t >= horizon:
                    break
                vehs.append((t, ap, mv))
    vehs.sort()
    with open(out, "w") as f:
        f.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xsi:noNamespaceSchemaLocation='
                '"http://sumo.dlr.de/xsd/routes_file.xsd">\n')
        f.write('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" '
                'length="5.0" minGap="2.5" maxSpeed="20.0" '
                'carFollowModel="Krauss" tau="1.0"/>\n')
        for ap, m in DEST.items():
            for mv, dst in m.items():
                f.write(f'    <route id="r_{ap}_{mv}" edges="{ap} {dst}"/>\n')
        for i, (t, ap, mv) in enumerate(vehs):
            f.write(f'    <vehicle id="v{i}" type="car" route="r_{ap}_{mv}" '
                    f'depart="{t:.2f}" departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')
    return len(vehs)


if __name__ == "__main__":
    outdir, horizon = sys.argv[1], float(sys.argv[2])
    os.makedirs(outdir, exist_ok=True)
    for lvl in LEVELS:
        for sd in range(1, 6):
            n = make(lvl, sd, horizon, os.path.join(outdir, f"{lvl}_s{sd}.rou.xml"))
            print(f"{lvl} seed{sd}: {n} vehicles")
