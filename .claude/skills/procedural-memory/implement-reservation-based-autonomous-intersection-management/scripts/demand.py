#!/usr/bin/env python3
"""
Deterministic demand generator for the AIM study.

Every vehicle is written out explicitly (id / depart / route / departLane) from a
seeded numpy RNG, so that a given (demand-level, seed) produces a BYTE-IDENTICAL
vehicle population regardless of which controller will later be run on it.
That is the Common-Random-Numbers (CRN) basis for the whole study
(see `quantify-sumo-run-to-run-variability`).

Each vehicle also carries a fixed uniform draw u ~ U(0,1) written into its id-independent
`cav_u` list, so CAV/HDV assignment at penetration p (`u < p`) is NESTED across
penetration levels: a vehicle that is a CAV at p=0.25 is still a CAV at p=0.50.
"""
import argparse
import json
import os

import numpy as np

ARMS = ["N", "E", "S", "W"]
# right / through / left target arm for each approach (right-hand traffic)
TURN_TARGET = {
    "N": {"r": "W", "s": "S", "l": "E"},
    "E": {"r": "N", "s": "W", "l": "S"},
    "S": {"r": "E", "s": "N", "l": "W"},
    "W": {"r": "S", "s": "E", "l": "N"},
}
# lane forced by the compiled net's connections: right -> lane 0, left -> lane 1,
# through -> either lane
TURN_LANE = {"r": 0, "l": 1}

VTYPE_TPL = """    <vType id="{vid}" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"
           decel="4.5" emergencyDecel="9.0" sigma="0.5" tau="1.0" maxSpeed="16.0"
           speedFactor="normc(1.00,0.10,0.85,1.15)" carFollowModel="Krauss"
           latAlignment="center"{extra}
"""
# the template used to end in a hard "/>" AFTER {extra}, so the SSM variant
# closed as "</vType/>" and every SSM run died with
#   Error: unterminated end tag 'vType'
# -> {extra} now carries the whole closing form, self-closing or not.
PLAIN_EXTRA = "/>"
SSM_EXTRA = """>
        <param key="has.ssm.device" value="true"/>
        <param key="device.ssm.measures" value="TTC DRAC PET BR MDRAC"/>
        <param key="device.ssm.thresholds" value="3.0 3.0 2.0 0.0 3.4"/>
        <param key="device.ssm.range" value="60.0"/>
        <param key="device.ssm.extratime" value="5.0"/>
        <param key="device.ssm.trajectories" value="false"/>
    </vType>"""


def gen(demand_per_approach, seed, t_end=1800.0,
        split=(0.15, 0.70, 0.15), approach_weights=None):
    """Return a list of vehicle dicts, sorted by depart time."""
    rng = np.random.default_rng(seed)
    pr, ps, pl = split
    vehs = []
    if approach_weights is None:
        approach_weights = {a: 1.0 for a in ARMS}

    for arm in ARMS:
        q = demand_per_approach * approach_weights[arm]      # veh/h on this approach
        if q <= 0:
            continue
        lam = q / 3600.0
        # Poisson process via exponential gaps
        t = 0.0
        while True:
            t += rng.exponential(1.0 / lam)
            if t >= t_end:
                break
            u_turn = rng.random()
            if u_turn < pr:
                mv = "r"
            elif u_turn < pr + ps:
                mv = "s"
            else:
                mv = "l"
            if mv == "s":
                lane = int(rng.integers(0, 2))
            else:
                lane = TURN_LANE[mv]
            vehs.append({
                "depart": round(t, 2),
                "arm": arm,
                "mv": mv,
                "to": TURN_TARGET[arm][mv],
                "lane": lane,
                "u": float(rng.random()),
            })
    vehs.sort(key=lambda v: (v["depart"], v["arm"]))
    for i, v in enumerate(vehs):
        v["id"] = "v%06d" % i
    return vehs


def write(vehs, path, ssm=False):
    extra = SSM_EXTRA if ssm else PLAIN_EXTRA
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write(VTYPE_TPL.format(vid="hdv", extra=extra))
        f.write(VTYPE_TPL.format(vid="cav", extra=extra))
        seen = set()
        for v in vehs:
            rid = "r_%s_%s" % (v["arm"], v["to"])
            if rid not in seen:
                f.write('    <route id="%s" edges="in_%s out_%s"/>\n' % (rid, v["arm"], v["to"]))
                seen.add(rid)
        for v in vehs:
            f.write('    <vehicle id="%s" type="hdv" route="r_%s_%s" depart="%.2f" '
                    'departLane="%d" departSpeed="max" arrivalSpeed="current"/>\n'
                    % (v["id"], v["arm"], v["to"], v["depart"], v["lane"]))
        f.write("</routes>\n")


def write_meta(vehs, path):
    meta = {v["id"]: {"arm": v["arm"], "mv": v["mv"], "to": "out_" + v["to"],
                      "u": v["u"], "depart": v["depart"]}
            for v in vehs}
    with open(path, "w") as f:
        json.dump(meta, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", type=float, required=True, help="veh/h per approach")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--t-end", type=float, default=1800.0)
    ap.add_argument("--split", default="0.15,0.70,0.15")
    ap.add_argument("--weights", default="", help="e.g. N=1.6,S=1.6,E=0.4,W=0.4")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ssm", action="store_true")
    a = ap.parse_args()

    split = tuple(float(x) for x in a.split.split(","))
    w = None
    if a.weights:
        w = {arm: 1.0 for arm in ARMS}
        for kv in a.weights.split(","):
            k, v = kv.split("=")
            w[k] = float(v)
    vehs = gen(a.demand, a.seed, a.t_end, split, w)
    write(vehs, a.out, ssm=a.ssm)
    write_meta(vehs, os.path.splitext(a.out)[0] + ".meta.json")
    print("%s: %d vehicles" % (a.out, len(vehs)))


if __name__ == "__main__":
    main()
