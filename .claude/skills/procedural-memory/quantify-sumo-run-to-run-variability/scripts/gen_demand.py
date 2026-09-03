#!/usr/bin/env python3
"""Generate randomTrips demand for the 4x4 signalized grid at a given
insertion rate and demand seed, producing a validated .rou.xml.

Usage:
  python3 gen_demand.py --rate 2400 --seed 1000 --out-dir /path/to/dir --tag L090
"""
import argparse
import os
import subprocess
import sys

SUMO_HOME = os.environ["SUMO_HOME"]
RANDOMTRIPS = os.path.join(SUMO_HOME, "tools", "randomTrips.py")
HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "grid4x4.net.xml")

# Demand window. Vehicles are inserted uniformly over [0, DEMAND_END].
DEMAND_END = 3600


def gen(rate, seed, out_dir, tag, net=NET, demand_end=DEMAND_END, quiet=True):
    os.makedirs(out_dir, exist_ok=True)
    trips = os.path.join(out_dir, "trips_%s_s%d.trips.xml" % (tag, seed))
    routes = os.path.join(out_dir, "routes_%s_s%d.rou.xml" % (tag, seed))
    cmd = [
        sys.executable, RANDOMTRIPS,
        "-n", net,
        "-o", trips,
        "-r", routes,
        "-b", "0", "-e", str(demand_end),
        "--insertion-rate", str(rate),
        # Strongly prefer trips that enter and leave via the boundary stubs, so
        # that interior-edge v/c is well defined (through traffic, not trips
        # that materialise mid-block).
        "--fringe-factor", "1000",
        "--min-distance", "300",
        "--seed", str(seed),
        "--validate",
        "--trip-attributes", 'departLane="best" departSpeed="max"',
    ]
    env = dict(os.environ)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=out_dir)
    if p.returncode != 0:
        sys.stderr.write(p.stdout + "\n" + p.stderr + "\n")
        raise RuntimeError("randomTrips failed (rate=%s seed=%s)" % (rate, seed))
    if not quiet:
        sys.stderr.write(p.stderr)
    return routes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    print(gen(a.rate, a.seed, a.out_dir, a.tag))
