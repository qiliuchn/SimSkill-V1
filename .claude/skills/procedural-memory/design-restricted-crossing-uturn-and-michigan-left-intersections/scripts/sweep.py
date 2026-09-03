#!/usr/bin/env python3
"""Run the whole experiment grid in parallel."""
import itertools
import json
import os
import sys
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run as R  # noqa: E402

VARIANTS = ["conv", "rcut", "mut"]
SEEDS = [1, 2, 3, 4, 5]
DS = [100, 200, 400, 800]
QS = [1200, 2400, 3600]
MS = [0.10, 0.20, 0.30, 0.40, 0.50]


def base_cells():
    cells = set()
    for q, m in itertools.product(QS, MS):        # spacing fixed, demand grid
        cells.add((400, q, m))
    for d, q in itertools.product(DS, QS):        # minor share fixed, spacing x demand
        cells.add((d, q, 0.30))
    for d, m in itertools.product(DS, MS):        # demand fixed, spacing x minor share
        cells.add((d, 2400, m))
    return sorted(cells)


def jobs():
    J = []
    for (d, q, m) in base_cells():
        for v, s in itertools.product(VARIANTS, SEEDS):
            J.append(dict(variant=v, D=d, Q=q, m=m, seed=s, tag="base", ttt=300))
    # SSM conflict measurement (heavier output -> fewer cells / seeds)
    for (d, q, m) in [(400, 2400, 0.30), (400, 3600, 0.30)]:
        for v, s in itertools.product(VARIANTS, [1, 2, 3]):
            J.append(dict(variant=v, D=d, Q=q, m=m, seed=s, tag="ssm", ttt=300, ssm=True))
    # teleport-artifact sensitivity
    for ttt in (120, -1):
        for (d, q, m) in [(400, 3600, 0.30), (100, 3600, 0.50)]:
            for v, s in itertools.product(VARIANTS, [1, 2, 3]):
                J.append(dict(variant=v, D=d, Q=q, m=m, seed=s,
                              tag=f"ttt{ttt}", ttt=ttt))
    return J


def one(kw):
    try:
        return R.run_cell(**kw)
    except Exception:  # noqa: BLE001
        return "FAIL " + json.dumps(kw) + "\n" + traceback.format_exc()


if __name__ == "__main__":
    J = jobs()
    # pre-build nets/routes/plans serially so parallel workers never race
    for kw in J:
        R.ensure_plan(kw["variant"], kw["D"], kw["Q"], kw["m"])
    print(f"{len(J)} runs; nets+routes+plans ready", flush=True)
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 8) as p:
        for i, r in enumerate(p.imap_unordered(one, J)):
            if str(r).startswith("FAIL"):
                print(r, flush=True)
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(J)}", flush=True)
    print("done")
