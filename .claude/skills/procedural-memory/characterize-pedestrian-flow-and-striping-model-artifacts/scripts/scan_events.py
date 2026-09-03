#!/usr/bin/env python3
"""Post-hoc scan of every retained sumo.log: WHERE do jam and person-collision
warnings actually happen?

This is the check that decides whether a congested-corridor measurement is usable.
The corridor's wide feed edge EA exists only to hold the unserved excess demand at
oversaturated demand levels; it is an artificial reservoir, not part of the
experiment.  If the striping model's failure modes (jam squeezing, person-person
overlap) are confined to EA and the junction walkingarea, then the measurement
section EM is clean and its flow/density/speed numbers stand -- and if they are not,
the corridor result is contaminated at its own measurement point.
"""
import argparse
import collections
import glob
import json
import os
import re

JAM_RE = re.compile(r"jammed on edge '([^']+)'")
COL_RE = re.compile(r"Collision of person '([^']+)' and person '([^']+)', lane='([^']+)'")
TEL_RE = re.compile(r"[Tt]eleport")


def scan(log):
    jam = collections.Counter()
    col = collections.Counter()
    col_pairs = set()
    tel = 0
    if not os.path.exists(log):
        return None
    for line in open(log, errors="ignore"):
        m = JAM_RE.search(line)
        if m:
            jam[m.group(1)] += 1
        m = COL_RE.search(line)
        if m:
            col[m.group(3)] += 1
            col_pairs.add((m.group(1), m.group(2)))
        if TEL_RE.search(line):
            tel += 1
    return {"jam_lines_by_edge": dict(jam), "collision_lines_by_lane": dict(col),
            "distinct_collision_pairs": len(col_pairs), "teleport_lines": tel}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args()
    out = {}
    for root in a.roots:
        exp = os.path.basename(root.rstrip("/"))
        for d in sorted(glob.glob(os.path.join(root, "*"))):
            if not os.path.isdir(d):
                continue
            s = scan(os.path.join(d, "sumo.log"))
            if s:
                out["%s/%s" % (exp, os.path.basename(d))] = s
    # roll-up: measurement-section vs reservoir/junction share
    roll = collections.defaultdict(lambda: {"jam_EM": 0, "jam_other": 0,
                                            "col_EM": 0, "col_other": 0, "n": 0})
    for k, v in out.items():
        exp = k.split("/")[0]
        r = roll[exp]
        r["n"] += 1
        for e, c in v["jam_lines_by_edge"].items():
            r["jam_EM" if e == "EM" else "jam_other"] += c
        for l, c in v["collision_lines_by_lane"].items():
            r["col_EM" if l.startswith("EM") else "col_other"] += c
    summary = {}
    for exp, r in roll.items():
        jt = r["jam_EM"] + r["jam_other"]
        ct = r["col_EM"] + r["col_other"]
        summary[exp] = dict(r,
                            jam_share_on_measurement_section=(r["jam_EM"] / jt if jt else None),
                            collision_share_on_measurement_section=(r["col_EM"] / ct if ct else None))
    json.dump({"per_run": out, "per_experiment": summary}, open(a.out_json, "w"), indent=1)
    for exp in sorted(summary):
        s = summary[exp]
        print("%-22s n=%3d  jam: EM=%7d other=%7d (%s on EM)   collisions: EM=%5d other=%5d (%s on EM)"
              % (exp, s["n"], s["jam_EM"], s["jam_other"],
                 "%.2f%%" % (100 * s["jam_share_on_measurement_section"])
                 if s["jam_share_on_measurement_section"] is not None else "n/a",
                 s["col_EM"], s["col_other"],
                 "%.2f%%" % (100 * s["collision_share_on_measurement_section"])
                 if s["collision_share_on_measurement_section"] is not None else "n/a"))


if __name__ == "__main__":
    main()
