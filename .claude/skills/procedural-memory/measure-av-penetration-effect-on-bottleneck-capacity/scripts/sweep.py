#!/usr/bin/env python3
"""
Orchestrates the full experiment as a queue of independent SUMO runs.

Runs are executed by a process pool; EVERY completed run immediately appends one
row to runs_index.csv and leaves its own metrics.json on disk, so the study can
be resumed or analysed at any point without holding anything in memory.
Already-completed cells are skipped on re-invocation.
"""
import os
import sys
import csv
import json
import time
import subprocess
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs")
INDEX = os.path.join(ROOT, "runs_index.csv")
NET_DROP = os.path.join(ROOT, "net", "bneck.net.xml")
NET_NODROP = os.path.join(ROOT, "net", "nodrop.net.xml")

SEEDS = [1, 2, 3, 4, 5, 6, 7, 8]
FCD_SEEDS = [1, 2, 3]
SWEEP_P = [0.2, 0.4, 0.6, 0.8]
ARMS = ["ACC", "CACC", "HUMAN_FAST"]
P_ARRANGE = 0.5


def jobs():
    J = []

    def add(cell, seed, **kw):
        J.append(dict(cell=cell, seed=seed, rundir=os.path.join(RUNS, cell, "s%d" % seed), **kw))

    # (1) homogeneous baselines: p = 1.0 of each fleet  (p=0 HUMAN doubles as the
    #     0% penetration point of every sweep arm)
    for ty in S.HOMOGENEOUS:
        for sd in SEEDS:
            add("homo__%s" % ty, sd, av_type=ty, p=1.0)

    # (2) penetration sweep, random arrangement
    for arm in ARMS:
        for p in SWEEP_P:
            for sd in SEEDS:
                add("sweep__%s__p%02d" % (arm, round(p * 100)), sd, av_type=arm, p=p)

    # (3) arrangement effect at p = 0.5: random vs deliberately platooned
    for arm in ARMS:
        for arr in ["random", "platoon"]:
            for sd in SEEDS:
                add("arr__%s__p50__%s" % (arm, arr), sd, av_type=arm, p=P_ARRANGE,
                    arrangement=arr)

    # (4) ENTRY-CAPACITY CONTROL: identical demand on a network with NO lane drop.
    #     Proves the 3-lane entry can deliver far more than the bottleneck discharges.
    for ty in S.HOMOGENEOUS:
        for sd in [1, 2]:
            add("entryctl__%s" % ty, sd, av_type=ty, p=1.0, net=NET_NODROP)

    # (5) cross-check that explicit per-vehicle type assignment reproduces SUMO's
    #     own <vTypeDistribution> probability-weighted sampling
    for sd in SEEDS:
        add("vtdist__ACC__p40", sd, av_type="ACC", p=0.4, demand_mode="vtypedist")

    # (6) FCD runs for the DIRECTLY MEASURED leader-is-AV fraction
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        for p in [0.2, 0.4, 0.5, 0.6, 0.8]:
            for sd in FCD_SEEDS:
                add("fcd__%s__p%02d__random" % (arm, round(p * 100)), sd,
                    av_type=arm, p=p, fcd=True)
        for sd in FCD_SEEDS:
            add("fcd__%s__p50__platoon" % arm, sd, av_type=arm, p=0.5,
                arrangement="platoon", fcd=True)
    return J


def run_one(j):
    rd = j["rundir"]
    mj = os.path.join(rd, "metrics.json")
    if os.path.exists(mj):
        try:
            d = json.load(open(mj))
            if d.get("meta", {}).get("rc") == 0:
                return (j["cell"], j["seed"], "cached", 0.0)
        except Exception:
            pass
    cmd = [sys.executable, os.path.join(HERE, "run_cell.py"),
           "--rundir", rd, "--cell", j["cell"], "--seed", str(j["seed"]),
           "--av-type", j["av_type"], "--p", str(j["p"]),
           "--arrangement", j.get("arrangement", "random"),
           "--demand-mode", j.get("demand_mode", "explicit"),
           "--net", j.get("net", NET_DROP)]
    if j.get("fcd"):
        cmd.append("--fcd")
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        ok = "ok" if pr.returncode == 0 else "FAIL:" + (pr.stdout + pr.stderr)[-200:]
    except subprocess.TimeoutExpired:
        ok = "TIMEOUT"
    return (j["cell"], j["seed"], ok, time.time() - t0)


def main():
    J = jobs()
    print("total runs queued: %d" % len(J))
    os.makedirs(RUNS, exist_ok=True)
    new = not os.path.exists(INDEX)
    fh = open(INDEX, "a", newline="")
    w = csv.writer(fh)
    if new:
        w.writerow(["cell", "seed", "status", "wall_s", "finished_at"])
        fh.flush()
    done = 0
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=9) as ex:
        for cell, seed, status, wall in ex.map(run_one, J):
            done += 1
            w.writerow([cell, seed, status, "%.1f" % wall, time.strftime("%H:%M:%S")])
            fh.flush()
            if status != "cached":
                print("[%3d/%3d] %-34s s%d %-8s %5.0fs   elapsed %.0fs"
                      % (done, len(J), cell, seed, status[:8], wall, time.time() - t0),
                      flush=True)
    fh.close()
    print("ALL DONE in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
