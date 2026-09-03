#!/usr/bin/env python3
"""Supplementary runs with the EXTENDED pedestrian-conflict instrument.

The main 10-seed batch records a ped-vehicle "conflict" whenever a right-turning
vehicle comes within 8 m of a pedestrian who is on one of that turn's foe
crossings, with a TTC-like value d/v < 2 s while the vehicle is moving >= 1 m/s.
That gate fires both for a vehicle that has actually entered the junction and
for one still approaching / creeping in the queue upstream of the stop line -
so under No-Turn-on-Red it reports a non-zero "on-red" count for vehicles that
never legally enter anything.

These supplementary runs (3 extra seeds per cell, operational regime only) add a
`past_line` flag and an `encroach_*` pair recorded ONLY while the vehicle is on
the right turn's internal via lane, i.e. physically inside the junction.  That
separates genuine ENCROACHMENT on a pedestrian from mere APPROACH EXPOSURE.
"""
import itertools
import os
import subprocess
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_scenario                     # noqa: E402
from linkmap import LinkMap             # noqa: E402
import run_all                          # noqa: E402

OUT = run_all.OUT
RUNS = os.path.join(OUT, "runs_encroach")
SEEDS = [101, 102, 103]


def job(args):
    variant, cell, seed = args
    tag = f"{variant}__{cell}__operational__s{seed}"
    outdir = os.path.join(RUNS, "operational", f"{variant}__{cell}")
    if os.path.exists(os.path.join(outdir, tag + "_traci.json")):
        return tag, True, "(skipped)"
    os.makedirs(outdir, exist_ok=True)
    lm = LinkMap(os.path.join(OUT, "net", f"{variant}.net.xml"))
    rvia = {x: lm.veh[lm.right(x)]["via"] for x in "NESW"}
    detp = os.path.join(outdir, f"det_{tag}.add.xml")
    gen_scenario.gen_detectors(detp, variant, 100, os.path.join(outdir, tag), right_via=rvia)
    cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
           "--net", os.path.join(OUT, "net", f"{variant}.net.xml"),
           "--routes", os.path.join(OUT, "demand", "operational.rou.xml"),
           "--program", os.path.join(OUT, "programs", f"{variant}.{cell}.tll.xml"),
           "--program-id", cell, "--detectors", detp,
           "--outdir", outdir, "--tag", tag, "--seed", str(seed),
           "--demand-end", "3600", "--end", "5400", "--warmup", "600",
           "--freeflow", os.path.join(OUT, "freeflow", f"freeflow_{variant}.json")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    return tag, r.returncode == 0, (r.stdout.strip().splitlines()[-1]
                                    if r.stdout.strip() else r.stderr[-400:])


if __name__ == "__main__":
    jobs = [(v, c, s) for (v, c) in run_all.CELLS for s in SEEDS]
    print(len(jobs), "supplementary runs")
    with Pool(int(os.environ.get("NPROC", "5"))) as p:
        for i, (tag, ok, msg) in enumerate(p.imap_unordered(job, jobs, chunksize=1), 1):
            print(f"[{i}/{len(jobs)}] {'OK ' if ok else 'FAIL'} {tag} {msg}", flush=True)
