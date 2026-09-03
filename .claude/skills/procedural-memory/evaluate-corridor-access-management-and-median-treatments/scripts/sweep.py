#!/usr/bin/env python3
"""Phase 1 (serial): build demand + per-variant routes for every (density,
seed, consolidate) cell -- avoids a parallel race on the shared canonical
trips.xml. Phase 2 (parallel, ProcessPool): run the sumo simulations."""
import itertools
import multiprocessing as mp
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
import run_sim as rs  # noqa: E402

DENSITIES = [5, 15, 30, 45]
SEEDS = [1, 2, 3, 4, 5]
VARIANTS = ["undivided", "twltl", "raised"]
REMEDY = [("twltl", 45, 9), ("undivided", 45, 9)]


def phase1():
    cells = set()
    for d in DENSITIES:
        for s in SEEDS:
            cells.add((d, s, 1))
    for v, d, c in REMEDY:
        for s in SEEDS:
            cells.add((d, s, c))
    for d, s, c in sorted(cells):
        variants = VARIANTS if c == 1 else [v for v, dd, cc in REMEDY if dd == d and cc == c]
        for v in variants:
            try:
                rs.ensure_route(v, d, s, c)
            except Exception as e:
                print("PHASE1 FAIL", v, d, s, c, e)
    print("phase1 done")


def _run_one(args):
    v, d, s, c = args
    try:
        ok, outdir, log = rs.run(v, d, s, c)
        if not ok:
            return (v, d, s, c, False, log[-1500:])
        return (v, d, s, c, True, "")
    except Exception:
        return (v, d, s, c, False, traceback.format_exc()[-1500:])


def phase2(nproc=6):
    cells = []
    for d in DENSITIES:
        for s in SEEDS:
            for v in VARIANTS:
                cells.append((v, d, s, 1))
    for v, d, c in REMEDY:
        for s in SEEDS:
            cells.append((v, d, s, c))
    print(f"phase2: {len(cells)} cells, {nproc} workers")
    with mp.Pool(nproc) as pool:
        for i, res in enumerate(pool.imap_unordered(_run_one, cells)):
            v, d, s, c, ok, log = res
            status = "OK" if ok else "FAIL"
            print(f"[{i+1}/{len(cells)}] {status} variant={v} density={d} seed={s} consolidate={c}")
            if not ok:
                print("   ", log)


if __name__ == "__main__":
    phase1()
    phase2(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
