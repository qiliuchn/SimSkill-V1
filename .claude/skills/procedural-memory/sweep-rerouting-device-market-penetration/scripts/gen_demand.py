#!/usr/bin/env python3
"""Generate the route file for one (seed, penetration) cell of the market-penetration sweep.

Design decisions that matter for the experiment:

* Departure times are IDENTICAL across every seed and every cell.  The demand
  realization is therefore not a variance source at all; the replication
  variance comes from SUMO's own stochasticity (sigma, speedDev, lane change,
  gap acceptance -- driven by `sumo --seed`) plus which vehicles happen to be
  equipped.  This is Common Random Numbers taken as far as it can go.

* Equipping is NESTED in penetration: for a given seed each vehicle i gets a
  fixed uniform draw u_i, and is equipped iff u_i < p.  Raising p therefore
  strictly ADDS equipped vehicles rather than resampling the whole set, which
  removes a large chunk of the noise from the penetration curve.

* Equipping is expressed as a vType (`equipped` / `unequipped`) carrying
  <param key="has.rerouting.device"/>, NOT as --device.rerouting.probability.
  Both mechanisms produce the same market penetration, but the vType version
  is *auditable*: the vType lands in tripinfo, so the equipped/unequipped
  partition of the results can be checked against raw output rather than
  asserted.  (validate_device_assignment.py checks that the two mechanisms
  agree and that the vType really controls device ownership.)

* EVERY vehicle -- equipped or not -- starts on the main route.  Absent the
  incident that is the genuinely best static route, so unequipped drivers are
  not being handicapped with a bad plan; they simply cannot react.
"""
import argparse
import random

MAIN_ROUTE = "OA AC CB BD"

VTYPE_BLOCK = """    <vType id="unequipped" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5"
           length="5.0" minGap="2.5" maxSpeed="45" speedDev="0.1" color="0.85,0.25,0.20">
        <param key="has.rerouting.device" value="false"/>
    </vType>
    <vType id="equipped" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5"
           length="5.0" minGap="2.5" maxSpeed="45" speedDev="0.1" color="0.15,0.60,0.35">
        <param key="has.rerouting.device" value="true"/>
    </vType>
"""


def depart_times(n_veh, horizon, jitter_seed=20260731):
    """Deterministic departure schedule shared by every cell (headway + fixed jitter)."""
    rng = random.Random(jitter_seed)
    h = horizon / float(n_veh)
    ts = [min(horizon - 0.1, max(0.0, (i + 0.5) * h + rng.uniform(-0.45 * h, 0.45 * h)))
          for i in range(n_veh)]
    ts.sort()
    return ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--penetration", type=float, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--veh-per-hour", type=float, default=2500.0)
    ap.add_argument("--horizon", type=float, default=3600.0)
    ap.add_argument("--route", default=MAIN_ROUTE)
    a = ap.parse_args()

    n = int(round(a.veh_per_hour * a.horizon / 3600.0))
    ts = depart_times(n, a.horizon)

    # nested equipping draws, fixed per (seed, vehicle index)
    rng = random.Random(1000000 + a.seed)
    u = [rng.random() for _ in range(n)]

    with open(a.out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write(VTYPE_BLOCK)
        f.write('    <route id="main" edges="%s"/>\n' % a.route)
        for i, t in enumerate(ts):
            vt = "equipped" if u[i] < a.penetration else "unequipped"
            f.write('    <vehicle id="v%04d" type="%s" route="main" depart="%.2f" '
                    'departLane="best" departSpeed="max"/>\n' % (i, vt, t))
        f.write('</routes>\n')

    n_eq = sum(1 for x in u if x < a.penetration)
    print("wrote %s : %d vehicles, %d equipped (%.3f)" % (a.out, n, n_eq, n_eq / float(n)))


if __name__ == "__main__":
    main()
