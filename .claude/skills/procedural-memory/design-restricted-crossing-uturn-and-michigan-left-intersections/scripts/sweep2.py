#!/usr/bin/env python3
"""
Supplementary HIGH-DEMAND sweep.  The main grid (Q<=3600) leaves the corridor
undersaturated, where none of the designs can win much; the interesting regime for
"does driving farther get you there sooner?" is at/above capacity, so extend Q.
"""
import itertools
import json
import os
import sys
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R  # noqa: E402

VARIANTS = ["conv", "rcut", "mut"]
SEEDS = [1, 2, 3, 4, 5]
QS = [4800]
MS = [0.10, 0.30, 0.50]
DS = [100, 200, 400, 800]


def cells():
    c = set()
    for q, m in itertools.product(QS, MS):
        c.add((400, q, m))
    for d in DS:
        c.add((d, 4800, 0.30))
    return sorted(c)


def one(kw):
    try:
        return R.run_cell(**kw)
    except Exception:  # noqa: BLE001
        return "FAIL " + json.dumps(kw) + "\n" + traceback.format_exc()


if __name__ == "__main__":
    J = [dict(variant=v, D=d, Q=q, m=m, seed=s, tag="base", ttt=300)
         for (d, q, m) in cells() for v, s in itertools.product(VARIANTS, SEEDS)]
    for kw in J:
        R.ensure_plan(kw["variant"], kw["D"], kw["Q"], kw["m"])
    print(f"{len(J)} runs ready", flush=True)
    with Pool(8) as p:
        for i, r in enumerate(p.imap_unordered(one, J)):
            if str(r).startswith("FAIL"):
                print(r, flush=True)
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(J)}", flush=True)
    print("done")
