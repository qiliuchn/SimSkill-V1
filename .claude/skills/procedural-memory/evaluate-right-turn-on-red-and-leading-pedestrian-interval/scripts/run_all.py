#!/usr/bin/env python3
"""Batch-run the full experiment.

Cells
-----
geometry A (exclusive right-turn lane) : 2x2 factorial {NTOR,RTOR} x {noLPI,LPI}
geometry B (shared through+right lane) : {NTOR,RTOR} x {noLPI}   (6 cells)

Regimes
-------
operational : moderate demand, delay / conflict / pedestrian measurement
capacity    : right-turn movement deliberately oversaturated (1200 veh/h per
              approach) so the SERVED right-turn volume equals the movement
              capacity

10 seeds per cell per regime = 120 runs.
"""
import itertools
import os
import subprocess
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")
RUNS = os.path.join(OUT, "runs")

CELLS = [
    ("A_excl", "NTOR_noLPI"),
    ("A_excl", "RTOR_noLPI"),
    ("A_excl", "NTOR_LPI"),
    ("A_excl", "RTOR_LPI"),
    ("B_shared", "NTOR_noLPI"),
    ("B_shared", "RTOR_noLPI"),
]
SEEDS = list(range(1, 11))
REGIMES = {
    "operational": {"demand_end": 3600, "end": 5400},
    "capacity":    {"demand_end": 3600, "end": 4200},
}
PED_PER_FLOW = 66.667    # 12 flows -> 800 ped/h total -> ~200 ped/h per crossing (measured)
WARMUP = 600


def job(args):
    variant, cell, regime, seed = args
    tag = f"{variant}__{cell}__{regime}__s{seed}"
    outdir = os.path.join(RUNS, regime, f"{variant}__{cell}")
    if os.path.exists(os.path.join(outdir, tag + "_traci.json")):
        return tag, True, "(already done, skipped)"
    cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
           "--net", os.path.join(OUT, "net", f"{variant}.net.xml"),
           "--routes", os.path.join(OUT, "demand", f"{regime}.rou.xml"),
           "--program", os.path.join(OUT, "programs", f"{variant}.{cell}.tll.xml"),
           "--program-id", cell,
           "--detectors", os.path.join(OUT, "demand", f"det_{variant}_{regime}_{cell}_s{seed}.add.xml"),
           "--outdir", outdir, "--tag", tag, "--seed", str(seed),
           "--demand-end", str(REGIMES[regime]["demand_end"]),
           "--end", str(REGIMES[regime]["end"]),
           "--warmup", str(WARMUP),
           "--freeflow", os.path.join(OUT, "freeflow", f"freeflow_{variant}.json")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    ok = r.returncode == 0
    return tag, ok, (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "") + \
        ("" if ok else " ERR:" + r.stderr[-600:])


if __name__ == "__main__":
    import json
    sys.path.insert(0, HERE)
    import gen_scenario
    from linkmap import LinkMap

    os.makedirs(os.path.join(OUT, "demand"), exist_ok=True)
    os.makedirs(RUNS, exist_ok=True)

    # split the free-flow datum per variant so run_cell gets a flat dict
    ff = json.load(open(os.path.join(OUT, "freeflow", "freeflow.json")))
    for v, d in ff.items():
        with open(os.path.join(OUT, "freeflow", f"freeflow_{v}.json"), "w") as f:
            json.dump(d, f, indent=2)

    for regime, cfg in REGIMES.items():
        gen_scenario.gen_routes(os.path.join(OUT, "demand", f"{regime}.rou.xml"),
                                regime, PED_PER_FLOW, cfg["demand_end"], cfg["demand_end"])

    # detector file is per-run so the instant-loop output files do not collide
    jobs = []
    for (variant, cell), regime, seed in itertools.product(CELLS, REGIMES, SEEDS):
        tag = f"{variant}__{cell}__{regime}__s{seed}"
        outdir = os.path.join(RUNS, regime, f"{variant}__{cell}")
        os.makedirs(outdir, exist_ok=True)
        detp = os.path.join(OUT, "demand", f"det_{variant}_{regime}_{cell}_s{seed}.add.xml")
        lmv = LinkMap(os.path.join(OUT, "net", f"{variant}.net.xml"))
        rvia = {x: lmv.veh[lmv.right(x)]["via"] for x in "NESW"}
        gen_scenario.gen_detectors(detp, variant, 100, os.path.join(outdir, tag),
                                   right_via=rvia)
        jobs.append((variant, cell, regime, seed))

    print(f"{len(jobs)} runs")
    nproc = int(os.environ.get("NPROC", "8"))
    with Pool(nproc) as p:
        for i, (tag, ok, msg) in enumerate(p.imap_unordered(job, jobs, chunksize=1), 1):
            print(f"[{i}/{len(jobs)}] {'OK ' if ok else 'FAIL'} {tag}  {msg}", flush=True)
