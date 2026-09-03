#!/usr/bin/env python3
"""
Generate ONE canonical (variant-independent) demand file per (density, seed,
consolidate) -- through trips + distributed midblock driveway trips with a
stated turn-movement split -- then route it SEPARATELY per median variant
against that variant's own compiled net (OD-fair per-variant routing, the
same discipline used in design-restricted-crossing-uturn-and-michigan-left-
intersections): raised median has no direct left connections, so duarouter
is forced to find the U-turn-crossover detour on its own, which is exactly
how the "banned lefts reappear as U-turns, not vanished trips" check works.

Total corridor demand, through/access split, and driveway-trip totals are
held FIXED across densities -- only the number of points the fixed access
demand is spread over changes (sub-goal 3's experimental control).
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

THROUGH_RATE_PER_DIR = 1000.0   # veh/h, fixed regardless of density
DWY_TOTAL_RATE = 600.0          # veh/h, combined both sides, fixed regardless of density
# stated turn-movement split of driveway demand
SPLIT = {"in_right": 0.30, "in_left": 0.20, "out_right": 0.30, "out_left": 0.20}
DEMAND_END = 3600.0
SIM_END = 5400.0
VTYPE = ('  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
         'decel="4.5" sigma="0.5" tau="1.2" maxSpeed="16.0" '
         'speedFactor="normc(1.0,0.10,0.7,1.3)">\n'
         '    <param key="has.ssm.device" value="true"/>\n'
         '    <param key="device.ssm.measures" value="TTC DRAC PET"/>\n'
         '    <param key="device.ssm.thresholds" value="3.0 3.0 2.0"/>\n'
         '    <param key="device.ssm.range" value="50.0"/>\n'
         '    <param key="device.ssm.extratime" value="5.0"/>\n'
         '  </vType>\n')


def poisson_departs(rate_veh_per_h, end_s, rng):
    """Return sorted departure times (s) for a Poisson process at rate_veh_per_h."""
    if rate_veh_per_h <= 0:
        return []
    lam = rate_veh_per_h / 3600.0
    t = 0.0
    out = []
    while True:
        t += rng.expovariate(lam)
        if t >= end_s:
            break
        out.append(round(t, 2))
    return out


def gen_trips(density_meta_path, seed, outpath):
    with open(density_meta_path) as f:
        meta = json.load(f)
    dwys = meta["driveways"]
    n_total_units = sum(d["n_merged"] for d in dwys)  # = original (pre-consolidation) driveway count
    rng = random.Random(seed)

    trips = []   # (depart, xml_line)
    vid = 0

    for t in poisson_departs(THROUGH_RATE_PER_DIR, DEMAND_END, rng):
        trips.append((t, f'  <trip id="thru_eb_{vid}" type="car" depart="{t:.2f}" '
                          f'fromJunction="W" toJunction="E"/>\n'))
        vid += 1
    for t in poisson_departs(THROUGH_RATE_PER_DIR, DEMAND_END, rng):
        trips.append((t, f'  <trip id="thru_wb_{vid}" type="car" depart="{t:.2f}" '
                          f'fromJunction="E" toJunction="W"/>\n'))
        vid += 1

    for d in dwys:
        nid, nmerged = d["nid"], d["n_merged"]
        for cat, share in SPLIT.items():
            rate_this_dwy = DWY_TOTAL_RATE * share * nmerged / n_total_units
            rate_each_submovement = rate_this_dwy / 2.0
            if cat == "in_left":
                movs = [("thru_eb", "fromJunction", "W", "to", f"IN_{nid}A"),
                        ("thru_wb", "fromJunction", "E", "to", f"IN_{nid}B")]
            elif cat == "in_right":
                movs = [("thru_wb", "fromJunction", "E", "to", f"IN_{nid}A"),
                        ("thru_eb", "fromJunction", "W", "to", f"IN_{nid}B")]
            elif cat == "out_left":
                movs = [("thru_eb", "from", f"OUT_{nid}A", "toJunction", "E"),
                        ("thru_wb", "from", f"OUT_{nid}B", "toJunction", "W")]
            else:  # out_right
                movs = [("thru_wb", "from", f"OUT_{nid}A", "toJunction", "W"),
                        ("thru_eb", "from", f"OUT_{nid}B", "toJunction", "E")]
            for tag, k1, v1, k2, v2 in movs:
                for t in poisson_departs(rate_each_submovement, DEMAND_END, rng):
                    trips.append((t, f'  <trip id="dwy_{cat}_{nid}_{vid}" type="car" depart="{t:.2f}" '
                                      f'{k1}="{v1}" {k2}="{v2}"/>\n'))
                    vid += 1

    trips.sort(key=lambda x: x[0])
    with open(outpath, "w") as f:
        f.write("<routes>\n")
        f.write(VTYPE)
        for _, line in trips:
            f.write(line)
        f.write("</routes>\n")
    return len(trips)


def route(net_path, trips_path, outpath, logpath):
    args = ["duarouter", "-n", net_path, "-r", trips_path, "-o", outpath,
            "--junction-taz", "true", "--ignore-errors", "true",
            "--no-step-log", "true", "--routing-threads", "2",
            "--seed", "1"]
    r = subprocess.run(args, capture_output=True, text=True)
    with open(logpath, "w") as f:
        f.write(" ".join(args) + "\n\n" + r.stdout + "\n" + r.stderr)
    return r.returncode, r.stdout + r.stderr


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("meta_json")
    ap.add_argument("seed", type=int)
    ap.add_argument("outdir")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    trips_path = os.path.join(a.outdir, "trips.xml")
    n = gen_trips(a.meta_json, a.seed, trips_path)
    print(f"generated {n} trips -> {trips_path}")
