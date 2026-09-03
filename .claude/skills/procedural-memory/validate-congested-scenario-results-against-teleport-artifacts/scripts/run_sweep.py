#!/usr/bin/env python3
"""
Teleport sweep driver.

Matrix: demand level x --time-to-teleport x seed, with Common Random Numbers:
for a given seed, EVERY ttt arm uses the byte-identical route file and the
identical sumo --seed, so --time-to-teleport is the only thing that varies.

Also drives the keep-clear ON/OFF network arms over the same route files.
"""
import argparse
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_cell import run  # noqa

WORK = None


def job(spec):
    level, netlab, netfile, roufile, ttt, seed, end, outdir = spec
    try:
        r = run(netfile, roufile, ttt, seed, outdir, end, keep_raw=True)
    except Exception as e:  # noqa
        r = {"error": repr(e)}
    r["level"] = level
    r["netarm"] = netlab
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--end", type=float, default=10800)
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()

    W = args.work
    LEVELS = {          # label: (general trips, loop trips)
        "LOW":  (400, 40),
        "OS-A": (1750, 262),
        "OS-B": (3000, 500),
    }
    TTTS = ["-1", "30", "60", "120", "300", "600", "900"]
    NETS = {"kc_on": os.path.join(W, "grid.net.xml"),
            "kc_off": os.path.join(W, "grid_kcoff.net.xml")}
    seeds = list(range(1, args.seeds + 1))

    specs = []
    for level, seed in itertools.product(LEVELS, seeds):
        rou = os.path.join(W, "demand_%s_s%d.rou.xml" % (level, seed))
        # teleport sweep -> keep-clear-ON network only
        for ttt in TTTS:
            od = os.path.join(W, "runs", "sweep", "%s_kc_on_ttt%s_s%d" % (level, ttt, seed))
            specs.append((level, "kc_on", NETS["kc_on"], rou, ttt, seed, args.end, od))
        # keep-clear arm: OFF network at the two anchor ttt values
        for ttt in ["-1", "300"]:
            od = os.path.join(W, "runs", "kc", "%s_kc_off_ttt%s_s%d" % (level, ttt, seed))
            specs.append((level, "kc_off", NETS["kc_off"], rou, ttt, seed, args.end, od))

    print("%d cells" % len(specs))
    res = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for i, r in enumerate(ex.map(job, specs)):
            res.append(r)
            if (i + 1) % 10 == 0:
                print("  %d/%d done" % (i + 1, len(specs)), flush=True)
    with open(args.out, "w") as fh:
        json.dump(res, fh, indent=1)
    nerr = sum(1 for r in res if "error" in r)
    print("wrote %s  (%d errors)" % (args.out, nerr))
    for r in res:
        if "error" in r:
            print(r)


if __name__ == "__main__":
    sys.exit(main())
