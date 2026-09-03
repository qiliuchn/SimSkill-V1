"""Generate the peak-period demand (main OD O->D + cross-street side demand).

Writes a .trips.xml with explicit per-vehicle depart times so that every
experiment arm can share exactly the same demand realisation (Common Random
Numbers) and only differ in route choice / equipage.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK  # noqa: E402

# (begin, end, veh/h) -- triangular peak profile
MAIN_PROFILE = [
    (0, 600, 1400),
    (600, 1200, 2200),
    (1200, 2400, 2800),
    (2400, 3000, 2200),
    (3000, 3600, 1400),
]
SIDE_RATE = 200  # veh/h per side movement, constant over 0..3600

SIDE_OD = [
    ("N1_I1", "I1_S1"), ("S1_I1", "I1_N1"),
    ("N2_I2", "I2_P2"), ("P2_I2", "I2_N2"),
    ("N3_I3", "I3_P3"), ("P3_I3", "I3_N3"),
    ("N4_I4", "I4_S4"), ("S4_I4", "I4_N4"),
]

VTYPES = """<additional>
    <vType id="base" vClass="passenger" emissionClass="HBEFA3/PC_G_EU4"
           length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5"
           maxSpeed="30.0" speedDev="0.1" tau="1.0"/>
    <vType id="eco"  vClass="passenger" emissionClass="HBEFA3/PC_G_EU4"
           length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5"
           maxSpeed="30.0" speedDev="0.1" tau="1.0"/>
    <vType id="side" vClass="passenger" emissionClass="HBEFA3/PC_G_EU4"
           length="4.5" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5"
           maxSpeed="30.0" speedDev="0.1" tau="1.0"/>
</additional>
"""


def poisson_departures(rng, begin, end, rate_per_h):
    """Exponential inter-arrival departures in [begin, end)."""
    if rate_per_h <= 0:
        return []
    mean_gap = 3600.0 / rate_per_h
    t = begin
    out = []
    while True:
        t += rng.expovariate(1.0 / mean_gap)
        if t >= end:
            return out
        out.append(t)


def generate(seed):
    rng = random.Random(1000 + seed)
    trips = []
    n = 0
    for (b, e, r) in MAIN_PROFILE:
        for t in poisson_departures(rng, b, e, r):
            trips.append((t, "main.%d" % n, "O_A", "M_D", "base"))
            n += 1
    m = 0
    for (fr, to) in SIDE_OD:
        for t in poisson_departures(rng, 0, 3600, SIDE_RATE):
            trips.append((t, "side.%d" % m, fr, to, "side"))
            m += 1
    trips.sort(key=lambda x: x[0])

    vt = os.path.join(WORK, "vtypes.add.xml")
    with open(vt, "w") as f:
        f.write(VTYPES)

    path = os.path.join(WORK, "demand_s%d.trips.xml" % seed)
    with open(path, "w") as f:
        f.write('<routes>\n')
        for t, vid, fr, to, ty in trips:
            f.write('    <trip id="%s" type="%s" depart="%.2f" from="%s" to="%s" '
                    'departLane="best" departSpeed="max"/>\n' % (vid, ty, t, fr, to))
        f.write('</routes>\n')
    print("seed %d: %d main + %d side = %d trips -> %s" % (seed, n, m, len(trips), path))
    return path


if __name__ == "__main__":
    for s in (0, 1, 2):
        generate(s)
