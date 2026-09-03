#!/usr/bin/env python3
"""Traffic-matched estimation-layer benchmark.

In the closed-loop grid each controller creates its OWN traffic, so a queue-
estimate RMSE measured inside a p=2% run is inflated by the much longer queues
that controller causes — the estimator and the traffic are confounded.  This
harness removes the confound: one OPEN-LOOP simulation per seed under the
fully-detected actuated benchmark, and at every 5 s epoch BOTH estimators are
evaluated at EVERY penetration against the same TraCI ground truth
(getLastStepHaltingNumber) on the same traffic state.  CRN across estimator and
across p is therefore exact, not approximate.
"""
import csv
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import cvcontrol as CC
import cvlib as CV
import traci

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCEN = os.path.join(ROOT, "outputs", "scenario")
OUT = os.path.join(ROOT, "outputs")
TABLES = os.path.join(OUT, "tables")
PS = [0.02, 0.05, 0.10, 0.20, 0.50, 1.00]
GROUP = {0: "art_left", 3: "art_through", 6: "cross"}
T0, T1 = 600.0, 3600.0


def one(seed):
    net = os.path.join(SCEN, "art_actuated.net.xml")
    rou = os.path.join(SCEN, "demand.rou.xml")
    traci.start([CV.SUMO, "-n", net, "-r", rou, "--begin", "0",
                 "--end", "%.0f" % CV.SIM_END, "--seed", str(seed),
                 "--no-step-log", "true", "--time-to-teleport", "300",
                 "--no-warnings", "true", "--xml-validation", "never"],
                label="estbench%d" % seed)
    tls = sorted(traci.trafficlight.getIDList())
    mon = {t: CC.BaseJunctionController(t, 0.6, 5.0, 0.0, 15.0) for t in tls}
    assign = CC.CVAssignment(1.0, "cv|%d" % seed)     # u(vid) for every vehicle
    lanes = sorted({l for t in tls for g in mon[t].green_phases
                    for l in mon[t].phase_in[g]})
    lane_len = {l: traci.lane.getLength(l) for l in lanes}

    acc = defaultdict(lambda: dict(n=0, se=0.0, sse=0.0, nq=0, blind=0,
                                   nq5=0, blind5=0, strue=0.0, sest=0.0))
    now = 0.0
    nxt = 0.0
    while traci.simulation.getMinExpectedNumber() > 0 and now < CV.SIM_END:
        traci.simulationStep()
        now = traci.simulation.getTime()
        if now < nxt:
            continue
        nxt += 5.0
        if not (T0 <= now < T1):
            continue
        # full ground truth on the approach lanes
        state = {}
        truth = {}
        for l in lanes:
            vs = traci.lane.getLastStepVehicleIDs(l)
            state[l] = [(v, traci.vehicle.getLanePosition(v),
                         traci.vehicle.getSpeed(v)) for v in vs]
            truth[l] = traci.lane.getLastStepHaltingNumber(l)
        us = {v: assign.u(v) for l in lanes for (v, _, _) in state[l]}
        for p in PS:
            obs = {l: [r for r in state[l] if us[r[0]] < p] for l in lanes}
            for est_name, fn in (("naive", CC.est_naive),
                                 ("shockwave", CC.est_shockwave)):
                q = {l: fn(obs[l], p, lane_len[l]) for l in lanes}
                for t in tls:
                    for g in mon[t].green_phases:
                        gl = mon[t].phase_in[g]
                        tq = sum(truth[l] for l in gl)
                        eq = sum(q[l] for l in gl)
                        k = (p, est_name, GROUP.get(g, str(g)))
                        a = acc[k]
                        a["n"] += 1
                        a["se"] += eq - tq
                        a["sse"] += (eq - tq) ** 2
                        a["strue"] += tq
                        a["sest"] += eq
                        if tq >= 1:
                            a["nq"] += 1
                            nobs = sum(1 for l in gl for r in obs[l]
                                       if r[2] < CC.HALT_SPEED)
                            a["blind"] += int(nobs == 0)
                            if tq >= 5:
                                a["nq5"] += 1
                                a["blind5"] += int(nobs == 0)
    traci.close()
    return seed, {("%s|%s|%s" % k): v for k, v in acc.items()}


def main(seeds=(1, 2, 3, 4, 5)):
    with ProcessPoolExecutor(5) as ex:
        res = list(ex.map(one, seeds))
    per_seed = defaultdict(list)
    for seed, d in res:
        for k, a in d.items():
            n = max(a["n"], 1)
            per_seed[k].append(dict(
                bias=a["se"] / n, rmse=math.sqrt(a["sse"] / n),
                mean_true=a["strue"] / n, mean_est=a["sest"] / n,
                blind=a["blind"] / a["nq"] if a["nq"] else float("nan"),
                blind5=a["blind5"] / a["nq5"] if a["nq5"] else float("nan"),
                n=n, nq=a["nq"]))
    rows = []
    for k, v in sorted(per_seed.items(), key=lambda kv: (kv[0].split("|")[1],
                                                         float(kv[0].split("|")[0]),
                                                         kv[0].split("|")[2])):
        p, est, g = k.split("|")

        def mc(f):
            xs = [x[f] for x in v if x[f] == x[f]]
            m = st.mean(xs)
            hw = (2.776 * st.stdev(xs) / math.sqrt(len(xs))) if len(xs) > 1 else 0
            return m, hw
        b, bh = mc("bias")
        r, rh = mc("rmse")
        mt, _ = mc("mean_true")
        me, _ = mc("mean_est")
        bl, blh = mc("blind")
        b5, b5h = mc("blind5")
        rows.append(dict(estimator=est, p=float(p), approach=g,
                         n_seeds=len(v), n_epoch_samples=v[0]["n"],
                         mean_true_queue_veh=round(mt, 3),
                         mean_est_queue_veh=round(me, 3),
                         bias_veh=round(b, 3), bias_ci=round(bh, 3),
                         rmse_veh=round(r, 3), rmse_ci=round(rh, 3),
                         rel_rmse=round(r / mt, 3) if mt else "",
                         pct_blind_q_ge1=round(100 * bl, 2),
                         pct_blind_ci=round(100 * blh, 2),
                         pct_blind_q_ge5=round(100 * b5, 2)))
    os.makedirs(TABLES, exist_ok=True)
    p = os.path.join(TABLES, "estimation_error_matched_traffic.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", p)
    for r in rows:
        print("%-10s p=%-5.2f %-12s true=%6.2f est=%6.2f bias=%+7.2f+-%4.2f "
              "rmse=%6.2f+-%4.2f rel=%-6s blind(q>=1)=%5.2f%% blind(q>=5)=%5.2f%%"
              % (r["estimator"], r["p"], r["approach"], r["mean_true_queue_veh"],
                 r["mean_est_queue_veh"], r["bias_veh"], r["bias_ci"],
                 r["rmse_veh"], r["rmse_ci"], r["rel_rmse"],
                 r["pct_blind_q_ge1"], r["pct_blind_q_ge5"]))


if __name__ == "__main__":
    main()
