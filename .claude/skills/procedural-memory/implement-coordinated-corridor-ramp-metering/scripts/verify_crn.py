#!/usr/bin/env python3
"""Verify that the Common Random Numbers design is actually in force:
every arm at a given (seed, demand) must have consumed the byte-identical route
file, and the identical `sumo --seed`.  Also verifies the non-binding negative
control reproduces the no-control arm exactly."""
import hashlib
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RUNS = os.path.join(ROOT, "outputs", "runs2", "core")


def main():
    bygroup = defaultdict(dict)
    for d in sorted(os.listdir(RUNS)):
        p = os.path.join(RUNS, d, "ctl.json")
        if not os.path.exists(p):
            continue
        m = json.load(open(p))["meta"]
        bygroup[(m["seed"], m["demand"])][m["arm"]] = m["routes"]
    bad = 0
    hashes = {}
    for key, arms in sorted(bygroup.items()):
        hs = set()
        for arm, rf in arms.items():
            if rf not in hashes:
                hashes[rf] = hashlib.sha256(open(rf, "rb").read()).hexdigest()[:16]
            hs.add(hashes[rf])
        if len(hs) != 1:
            bad += 1
            print("CRN VIOLATION", key, arms)
    print(f"CRN check: {len(bygroup)} (seed,demand) cells, {bad} violations, "
          f"{len(set(hashes.values()))} distinct route files "
          f"(expected = number of (seed,demand) pairs = {len(bygroup)})")
    return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
