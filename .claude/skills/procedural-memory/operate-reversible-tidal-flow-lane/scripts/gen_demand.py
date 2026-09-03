#!/usr/bin/env python3
"""Generate an explicit-vehicle route file for the reversible-lane corridor.

Departure times are drawn here (numpy Poisson process) rather than left to
SUMO's <flow> RNG, so that every control policy compared at a given
(split, seed) sees a byte-identical demand realisation -- Common Random Numbers
at the demand level, per `quantify-sumo-run-to-run-variability`.

Usage:
  python3 gen_demand.py --out demand.rou.xml --seed 1 \
      --period 0,900,2400,0.5 --period 900,4500,4600,0.70 --period 4500,5400,2400,0.5 \
      --cross 400
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CROSS_FLOW

ROUTES = {
    "EB": "apW_in COR_EB apE_out",
    "WB": "apE_in COR_WB apW_out",
    "XW_N": "Ws_W W_Wn",
    "XW_S": "Wn_W W_Ws",
    "XE_N": "Es_E E_En",
    "XE_S": "En_E E_Es",
}

VTYPE = ('    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" '
         'accel="2.6" decel="4.5" sigma="0.5" tau="1.0" maxSpeed="20.0" '
         'speedFactor="normc(1.0,0.10,0.75,1.25)"/>\n')


def poisson_departs(rng, rate_per_h, t0, t1):
    """Exponential-headway arrival times in [t0, t1)."""
    if rate_per_h <= 0:
        return []
    out, t = [], float(t0)
    mean_gap = 3600.0 / rate_per_h
    while True:
        t += rng.exponential(mean_gap)
        if t >= t1:
            break
        out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--period", action="append", required=True,
                    help="begin,end,total_veh_per_h,eb_share")
    ap.add_argument("--cross", type=float, default=CROSS_FLOW,
                    help="veh/h per cross-street approach (constant)")
    ap.add_argument("--cross-end", type=float, default=None)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    periods = []
    for p in a.period:
        b, e, tot, sh = p.split(",")
        periods.append((float(b), float(e), float(tot), float(sh)))
    tmax = max(p[1] for p in periods)
    cross_end = a.cross_end if a.cross_end is not None else tmax

    veh = []   # (depart, id, route_key)
    for b, e, tot, sh in periods:
        for t in poisson_departs(rng, tot * sh, b, e):
            veh.append((t, "EB"))
        for t in poisson_departs(rng, tot * (1.0 - sh), b, e):
            veh.append((t, "WB"))
    for key in ("XW_N", "XW_S", "XE_N", "XE_S"):
        for t in poisson_departs(rng, a.cross, 0.0, cross_end):
            veh.append((t, key))

    veh.sort(key=lambda x: x[0])
    counters = {}
    lines = ['<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
             VTYPE.rstrip("\n")]
    for key, edges in ROUTES.items():
        lines.append(f'    <route id="r_{key}" edges="{edges}"/>')
    for t, key in veh:
        n = counters.get(key, 0)
        counters[key] = n + 1
        lines.append(f'    <vehicle id="{key}.{n}" type="car" route="r_{key}" '
                     f'depart="{t:.2f}" departLane="best" departSpeed="max"/>')
    lines.append("</routes>")
    with open(a.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {a.out}: {len(veh)} vehicles "
          + ", ".join(f"{k}={v}" for k, v in sorted(counters.items())))


if __name__ == "__main__":
    main()
