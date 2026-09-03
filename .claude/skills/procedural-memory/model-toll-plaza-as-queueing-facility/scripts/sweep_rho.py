#!/usr/bin/env python3
"""
STEP 3 + STEP 4 - utilisation sweep of the 6-booth all-manual plaza, with replications,
run twice: once with the booth chosen at random on generation (a Bernoulli split of the
Poisson stream = c independent M/M/1 queues) and once with the TraCI join-the-shortest-queue
assigner (which should behave like a single M/M/c queue).
"""
import itertools
import json
import multiprocessing as mp
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plaza_lib as P
import metrics as M

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(EP, "attempts", "attempt-1", "runs", "sweep")
NET = os.path.join(EP, "outputs", "network", "plaza_c6.net.xml")

C = 6
SERVICE_MEAN = 8.0
HORIZON = 5400.0          # arrivals generated over 0..5400 s
WARM = 900.0              # discard arrivals before 900 s (queueing transient)
W1 = 5400.0
SEEDS = [101, 202, 303, 404, 505]
RHOS = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.875, 0.95]


def launch(args):
    tag, rate, seed, controller, dpos = args
    d = os.path.join(RUNS, tag)
    hz = 14400.0 if tag == "ff" else HORIZON
    cmd = [sys.executable, os.path.join(HERE, "run_plaza.py"),
           "--run-dir", d, "--net", NET, "--booths", str(C),
           "--rate", "%.3f" % rate, "--horizon", str(hz), "--end-pad", "2400",
           "--seed", str(seed), "--service-dist", "exp",
           "--service-mean", str(SERVICE_MEAN), "--controller", controller,
           "--decision-pos", str(dpos)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return tag, r.returncode, r.stderr[-1500:]


def main():
    os.makedirs(RUNS, exist_ok=True)
    cap = json.load(open(os.path.join(EP, "outputs", "step2_mechanism_verification.json")))
    exp8 = [x for x in cap if x["variant"] == "exp8"][0]
    Seff = exp8["mean_departure_headway_s"]                 # effective service time incl. floor
    mu_eff = 1.0 / Seff
    plaza_cap = C * 3600.0 / Seff
    print("effective service time S' = %.3f s -> plaza capacity %.1f veh/h "
          "(textbook 3600/E[S]*c = %.1f veh/h)" % (Seff, plaza_cap, C * 3600 / SERVICE_MEAN))

    jobs = []
    # free-flow calibration run (near-empty)
    jobs.append(("ff", 60.0, 999, "none", 600.0))   # ~10 veh/h/booth: genuinely interaction-free
    for rho, seed in itertools.product(RHOS, SEEDS):
        jobs.append(("rnd_r%03d_s%d" % (round(rho * 100), seed), rho * plaza_cap, seed, "none", 600.0))
        jobs.append(("sq_r%03d_s%d" % (round(rho * 100), seed), rho * plaza_cap, seed, "shortest", 600.0))
        # late-decision arm: booth chosen 1150 m along the 1196 m approach, i.e. with almost
        # no commitment lag -> isolates how much of the residual gap to M/G/c is decision lag
        jobs.append(("sql_r%03d_s%d" % (round(rho * 100), seed), rho * plaza_cap, seed, "shortest", 1150.0))

    with mp.Pool(8) as pool:
        for tag, rc, err in pool.imap_unordered(launch, jobs):
            if rc:
                print("FAIL", tag, err)
    print("runs done")

    tff = M.calibrate_tff(os.path.join(RUNS, "ff"), C)
    tff_bin = M.calibrate_tff_bin(os.path.join(RUNS, "ff"), C)
    print("free-flow entry->service-start T_ff per booth (s):",
          {k: round(v, 2) for k, v in tff.items()})
    json.dump(tff, open(os.path.join(EP, "outputs", "free_flow_tff.json"), "w"), indent=1)

    rows = []
    for arm, pre in (("random", "rnd"), ("shortest_queue", "sq"), ("shortest_queue_late", "sql")):
        for rho in RHOS:
            for seed in SEEDS:
                d = os.path.join(RUNS, "%s_r%03d_s%d" % (pre, round(rho * 100), seed))
                m = M.run_metrics(d, C, tff, WARM, W1, HORIZON, tff_bin=tff_bin)
                if m is None:
                    print("no metrics", d)
                    continue
                m.update(arm=arm, rho_nominal=rho, seed=seed, run_dir=d)
                rows.append(m)
    json.dump(dict(Seff=Seff, mu_eff=mu_eff, plaza_cap_vph=plaza_cap, tff=tff, tff_bin=tff_bin,
                   service_mean=SERVICE_MEAN, warm=WARM, w1=W1, seeds=SEEDS, rhos=RHOS,
                   rows=rows),
              open(os.path.join(EP, "outputs", "step3_sweep_raw.json"), "w"), indent=1)
    print("wrote", os.path.join(EP, "outputs", "step3_sweep_raw.json"), len(rows), "rows")


if __name__ == "__main__":
    main()
