#!/usr/bin/env python3
"""
Run one scenario through SUMO under TraCI.

TraCI is used ONLY to sample the E2 queue detectors at 1 Hz, so that a per-cycle
MINIMUM jam length (the residual / overflow queue) and an exact bin-boundary
queue can be recorded.  E2 interval output only reports maxima, and at a
signalised approach the within-cycle maximum is dominated by the cyclic queue,
which is not the quantity the residual-queue correction needs.

Everything else (tripinfo, summary, E1, instant loops, E2 intervals) is ordinary
SUMO file output.
"""
import argparse
import csv
import os
import shutil
import sys

from common import (SUMO, NET, RUNS, SIM_END, STEP, BIN, CYCLE, run)
import build_detectors


def build_cfg(run_dir, route_file, end, seed, ttt):
    add = build_detectors.write_for_run(run_dir)
    cfg = os.path.join(run_dir, "run.sumocfg")
    with open(cfg, "w") as f:
        f.write("""<configuration>
  <input>
    <net-file value="%s"/>
    <route-files value="%s"/>
    <additional-files value="detectors.add.xml"/>
  </input>
  <time>
    <begin value="0"/><end value="%d"/><step-length value="%s"/>
  </time>
  <processing>
    <time-to-teleport value="%s"/>
    <max-depart-delay value="-1"/>
  </processing>
  <report>
    <no-step-log value="true"/>
    <duration-log.statistics value="true"/>
    <xml-validation value="never"/>
  </report>
  <random_number><seed value="%d"/></random_number>
  <output>
    <tripinfo-output value="tripinfo.xml"/>
    <summary-output value="summary.xml"/>
    <summary-output.period value="60"/>
    <statistic-output value="stats.xml"/>
  </output>
</configuration>
""" % (os.path.abspath(NET), os.path.abspath(route_file), end, STEP, ttt, seed))
    return cfg


def simulate(run_dir, route_file, end=SIM_END, seed=42, ttt=-1, quiet=True):
    os.makedirs(run_dir, exist_ok=True)
    cfg = build_cfg(run_dir, route_file, end, seed, ttt)

    sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci
    import traci.constants as tc

    log = os.path.join(run_dir, "sumo.log")
    traci.start([SUMO, "-c", "run.sumocfg", "--message-log", "sumo.log",
                 "--error-log", "sumo.err"], port=None, label=run_dir,
                traceFile=None, stdout=None)
    # cwd matters for the relative file= paths -> start SUMO from run_dir
    dets = traci.lanearea.getIDList()
    for d in dets:
        traci.lanearea.subscribe(d, [tc.JAM_LENGTH_VEHICLE, tc.JAM_LENGTH_METERS,
                                    tc.LAST_STEP_VEHICLE_NUMBER])

    cyc = {d: [] for d in dets}          # per-cycle (min, max) jam veh
    cur = {d: [] for d in dets}
    curn = {d: [] for d in dets}         # per-cycle vehicle-number samples
    q_end = {}                           # (bin, det) -> jam veh at bin end
    n_end = {}                           # (bin, det) -> vehicles ON the approach
    n_cycmin = {}                        # (bin, det) -> [per-cycle minima]
    q_stats = {}                         # (bin, det) -> [sum, n, max]
    cyc_rows = []
    pending_rows = []

    t = 0.0
    while t < end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        if abs(t - round(t)) > 1e-6:      # sample on whole seconds only
            continue
        t = float(round(t))
        res = traci.lanearea.getAllSubscriptionResults()
        for d in dets:
            v = res.get(d, {}).get(tc.JAM_LENGTH_VEHICLE, 0)
            cur[d].append(v)
            curn[d].append(res.get(d, {}).get(tc.LAST_STEP_VEHICLE_NUMBER, 0))
            b = int((t - 1) // BIN)
            if 0 <= b:
                s = q_stats.setdefault((b, d), [0.0, 0, 0])
                s[0] += v; s[1] += 1; s[2] = max(s[2], v)
        if abs(t % CYCLE) < 1e-6:
            for d in dets:
                if cur[d]:
                    cyc_rows.append((t - CYCLE, d, min(cur[d]), max(cur[d])))
                    cyc[d].append((t - CYCLE, min(cur[d])))
                    n_cycmin.setdefault((int((t - CYCLE) // BIN), d), []).append(min(curn[d]))
                cur[d] = []
                curn[d] = []
        if abs(t % BIN) < 1e-6:
            b = int(t // BIN) - 1
            for d in dets:
                q_end[(b, d)] = res.get(d, {}).get(tc.JAM_LENGTH_VEHICLE, 0)
                n_end[(b, d)] = res.get(d, {}).get(tc.LAST_STEP_VEHICLE_NUMBER, 0)
            try:
                np_ = len(traci.simulation.getPendingVehicles())
            except Exception:
                np_ = -1
            pending_rows.append((t, np_, traci.simulation.getMinExpectedNumber()))
    traci.close()

    with open(os.path.join(run_dir, "queue_cycles.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cycle_start", "det", "jam_min_veh", "jam_max_veh"])
        w.writerows(cyc_rows)
    with open(os.path.join(run_dir, "queue_bins.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bin", "det", "q_end_veh", "q_mean_veh", "q_max_veh", "q_resid_veh",
                    "n_end_veh", "n_cycmin_veh"])
        # residual queue for a bin = mean of the per-cycle minima inside that bin
        resid = {}
        for (t0, d, qmin, qmax) in cyc_rows:
            b = int(t0 // BIN)
            resid.setdefault((b, d), []).append(qmin)
        for (b, d), s in sorted(q_stats.items()):
            r = resid.get((b, d), [])
            nc = n_cycmin.get((b, d), [])
            w.writerow([b, d, q_end.get((b, d), ""), "%.3f" % (s[0] / max(s[1], 1)),
                        s[2], "%.3f" % (sum(r) / len(r)) if r else "",
                        n_end.get((b, d), ""),
                        "%.3f" % (sum(nc) / len(nc)) if nc else ""])
    with open(os.path.join(run_dir, "pending.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "n_pending_insertion", "min_expected"])
        w.writerows(pending_rows)
    return run_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--end", type=int, default=SIM_END)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ttt", default="-1")
    a = ap.parse_args()
    a.route = os.path.abspath(a.route)
    d = os.path.join(RUNS, a.name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    cwd = os.getcwd()
    os.chdir(d)
    try:
        simulate(d, a.route, a.end, a.seed, a.ttt)
    finally:
        os.chdir(cwd)
    print("done", d)


if __name__ == "__main__":
    main()
