#!/usr/bin/env python3
"""Orchestrate the managed-lane experiment programme (phases run independently)."""
import argparse
import itertools
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEM = os.path.join(ROOT, "demand")
RUNS = os.path.join(ROOT, "runs")
NET = os.path.join(ROOT, "net")
ANA = os.path.join(ROOT, "analysis")
for d in (DEM, RUNS, ANA):
    os.makedirs(d, exist_ok=True)

BASE_SCALE = 1.35
BASE_CARPOOL = 0.15
SEEDS5 = [1001, 1002, 1003, 1004, 1005]
SEEDS3 = [1001, 1002, 1003]
NPROC = 8


def dem_stem(seed, carpool, scale, bus=25.0):
    base = os.path.join(DEM, f"d_s{seed}_c{carpool:.3f}_x{scale:.2f}")
    return base if bus == 25.0 else base + f"_b{bus:.0f}"


def gen_demand(seed, carpool, scale, bus=25.0):
    stem = dem_stem(seed, carpool, scale, bus)
    if os.path.exists(stem + ".rou.xml") and os.path.exists(stem + ".fleet.csv"):
        return stem
    subprocess.run([sys.executable, os.path.join(HERE, "gen_demand.py"),
                    "--seed", str(seed), "--carpool-share", str(carpool),
                    "--demand-scale", str(scale), "--bus-veh-per-hour", str(bus),
                    "--out-stem", stem], check=True)
    return stem


def run_one(job):
    stem = dem_stem(job["seed"], job["carpool"], job["scale"], job.get("bus", 25.0))
    outdir = os.path.join(RUNS, job["name"])
    cmd = [sys.executable, os.path.join(HERE, "run_corridor.py"),
           "--arm", job["arm"], "--net", os.path.join(NET, job["net"] + ".net.xml"),
           "--routes", stem + ".rou.xml", "--fleet", stem + ".fleet.csv",
           "--outdir", outdir, "--seed", str(job["seed"])]
    for k in ("toll", "occ_target", "alinea_k", "toll_init", "time_to_teleport"):
        if k in job:
            cmd += ["--" + k.replace("_", "-"), str(job[k])]
    if job.get("lanechange"):
        cmd += ["--lanechange-output"]
    if job.get("ssm"):
        cmd += ["--ssm", str(job["ssm"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    return {"name": job["name"], "ok": ok, "err": r.stderr[-800:] if not ok else ""}


def launch(jobs, tag):
    for j in jobs:
        gen_demand(j["seed"], j["carpool"], j["scale"], j.get("bus", 25.0))
    print(f"[{tag}] {len(jobs)} runs on {NPROC} workers ...")
    with ProcessPoolExecutor(NPROC) as ex:
        res = list(ex.map(run_one, jobs))
    bad = [r for r in res if not r["ok"]]
    print(f"[{tag}] done. failures={len(bad)}")
    for b in bad[:5]:
        print("  FAIL", b["name"], b["err"][:400])
    json.dump(jobs, open(os.path.join(ANA, f"jobs_{tag}.json"), "w"), indent=1)
    return len(bad) == 0


# --------------------------------------------------------------------------- #
def phase_toll(args):
    tolls = [0.00, 0.10, 0.25, 0.40, 0.60, 0.80, 1.10, 1.50, 2.00, 3.00, 5.00]
    jobs = []
    for toll, seed in itertools.product(tolls, SEEDS3):
        jobs.append(dict(name=f"H2_toll{toll:.2f}_s{seed}", arm="C", net="managed",
                         seed=seed, carpool=BASE_CARPOOL, scale=BASE_SCALE, toll=toll))
    return launch(jobs, "H2")


def phase_toll2(args):
    """(a) finer tolls near the price floor at base demand; (b) the whole sweep repeated at a
    LOWER demand level where the GP lanes are not themselves saturated -- the regime in which
    an interior optimum could exist at all."""
    jobs = []
    for toll, seed in itertools.product([0.02, 0.05, 0.15], SEEDS3):
        jobs.append(dict(name=f"H2_toll{toll:.2f}_s{seed}", arm="C", net="managed",
                         seed=seed, carpool=BASE_CARPOOL, scale=BASE_SCALE, toll=toll))
    for toll, seed in itertools.product([0.00, 0.10, 0.25, 0.50, 0.80, 1.20, 2.00, 3.00], SEEDS3):
        jobs.append(dict(name=f"H2lo_toll{toll:.2f}_s{seed}", arm="C", net="managed",
                         seed=seed, carpool=BASE_CARPOOL, scale=1.05, toll=toll))
    for seed in SEEDS3:
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H2lo_{arm}_s{seed}", arm=arm, net=net, seed=seed,
                             carpool=BASE_CARPOOL, scale=1.05))
    return launch(jobs, "H2b")


def phase_main(args):
    jobs = []
    for seed in SEEDS5:
        base = dict(seed=seed, carpool=BASE_CARPOOL, scale=BASE_SCALE)
        jobs.append(dict(name=f"MAIN_A_s{seed}", arm="A", net="gp4", **base))
        jobs.append(dict(name=f"MAIN_B_s{seed}", arm="B", net="managed", **base))
        # C-lo: fixed toll price-matched to arm D's realised mean toll (fair static-vs-dynamic test)
        jobs.append(dict(name=f"MAIN_Clo_s{seed}", arm="C", net="managed",
                         toll=args.c_toll, **base))
        # C-hi: the revenue-maximising fixed toll from the H2 sweep
        jobs.append(dict(name=f"MAIN_Chi_s{seed}", arm="C", net="managed",
                         toll=args.c_toll_hi, **base))
        jobs.append(dict(name=f"MAIN_D_s{seed}", arm="D", net="managed",
                         occ_target=args.occ_target, alinea_k=args.alinea_k,
                         toll_init=0.50, **base))
    return launch(jobs, "MAIN")


def phase_h1(args):
    shares = [0.025, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30]
    jobs = []
    for cp, seed in itertools.product(shares, SEEDS3):
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H1cp_{arm}_c{cp:.3f}_s{seed}", arm=arm, net=net,
                             seed=seed, carpool=cp, scale=BASE_SCALE))
    for sc, seed in itertools.product([1.10, 1.20, 1.45], SEEDS3):
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H1dm_{arm}_x{sc:.2f}_s{seed}", arm=arm, net=net,
                             seed=seed, carpool=BASE_CARPOOL, scale=sc))
    return launch(jobs, "H1")


def phase_h1b(args):
    """Push the carpool-share and transit-intensity sweeps far enough to LOCATE the crossing."""
    jobs = []
    for cp, seed in itertools.product([0.40, 0.50, 0.60, 0.75], SEEDS3):
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H1cp_{arm}_c{cp:.3f}_s{seed}", arm=arm, net=net,
                             seed=seed, carpool=cp, scale=BASE_SCALE))
    for cp, seed in itertools.product([0.15, 0.30, 0.45, 0.60], SEEDS3):
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H1cp120_{arm}_c{cp:.3f}_s{seed}", arm=arm, net=net,
                             seed=seed, carpool=cp, scale=1.20))
    for bus, seed in itertools.product([50.0, 100.0, 200.0, 400.0], SEEDS3):
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"H1bus_{arm}_b{bus:.0f}_s{seed}", arm=arm, net=net,
                             seed=seed, carpool=BASE_CARPOOL, scale=BASE_SCALE, bus=bus))
    return launch(jobs, "H1b")


def phase_h3(args):
    jobs = []
    for seed in SEEDS3:
        for acc, net in (("cont", "managed"), ("gated", "managed_gated")):
            jobs.append(dict(name=f"H3_B_{acc}_s{seed}", arm="B", net=net, seed=seed,
                             carpool=BASE_CARPOOL, scale=BASE_SCALE,
                             lanechange=True, ssm=0.20))
            jobs.append(dict(name=f"H3_C_{acc}_s{seed}", arm="C", net=net, seed=seed,
                             carpool=BASE_CARPOOL, scale=BASE_SCALE, toll=args.c_toll,
                             lanechange=True, ssm=0.20))
    return launch(jobs, "H3")


def phase_h2gate(args):
    """H2 in the one regime where the managed lane CAN be over-subscribed: LIMITED ACCESS,
    where a vehicle that buys in is committed until the next egress gate."""
    jobs = []
    for toll, seed in itertools.product([0.00, 0.05, 0.15, 0.30, 0.60, 1.50], SEEDS3):
        jobs.append(dict(name=f"H2g_toll{toll:.2f}_s{seed}", arm="C", net="managed_gated",
                         seed=seed, carpool=BASE_CARPOOL, scale=BASE_SCALE, toll=toll))
    return launch(jobs, "H2g")


def phase_teleport(args):
    jobs = []
    for ttt in [-1, 120, 300, 600]:
        for arm, net in (("A", "gp4"), ("B", "managed")):
            jobs.append(dict(name=f"TP_{arm}_ttt{ttt}_s1001", arm=arm, net=net, seed=1001,
                             carpool=BASE_CARPOOL, scale=BASE_SCALE, time_to_teleport=ttt))
    return launch(jobs, "TP")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["toll", "toll2", "main", "h1", "h1b", "h2gate", "h3", "teleport"])
    ap.add_argument("--c-toll", type=float, default=0.12)
    ap.add_argument("--c-toll-hi", type=float, default=1.50)
    ap.add_argument("--occ-target", type=float, default=8.0)
    ap.add_argument("--alinea-k", type=float, default=0.10)
    a = ap.parse_args()
    ok = {"toll": phase_toll, "toll2": phase_toll2, "main": phase_main, "h1": phase_h1, "h1b": phase_h1b, "h2gate": phase_h2gate,
          "h3": phase_h3, "teleport": phase_teleport}[a.phase](a)
    sys.exit(0 if ok else 1)
