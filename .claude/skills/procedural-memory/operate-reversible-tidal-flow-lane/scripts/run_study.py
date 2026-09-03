#!/usr/bin/env python3
"""Parts 3 and 4: control-policy comparison and the directional-split sweep.

  --mode day    full simulated day with an AM (eastbound) and a PM (westbound)
                peak; policies A / B / C, 5 seeds each
  --mode sweep  fixed total demand, directional split swept 50/50 -> 85/15,
                policies A / B / C, 5 seeds per cell

Policy A  static 3+3, never reversed
Policy B  fixed time-of-day schedule, changeover requested ahead of each peak
Policy C  demand-responsive: E2 directional occupancy, two-sided hysteresis,
          minimum dwell time

Writes outputs/analysis/<mode>_runs.json
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NETDIR, DEMDIR, RUNDIR, ANADIR, SCRIPTS, PEAK_TOTAL,
                    OFFPEAK_TOTAL, ensure_dirs)
from metrics import run_metrics

NET = os.path.join(NETDIR, "encB_open.net.xml")
SEEDS = [301, 302, 303, 304, 305]

# ----- full-day scenario --------------------------------------------------
DAY_PERIODS = [
    (0, 1800, OFFPEAK_TOTAL, 0.50),          # early off-peak
    (1800, 5400, PEAK_TOTAL, 0.75),          # AM peak, eastbound dominant
    (5400, 7200, 2800.0, 0.50),              # midday
    (7200, 10800, PEAK_TOTAL, 0.25),         # PM peak, westbound dominant
    (10800, 12600, OFFPEAK_TOTAL, 0.50),     # evening off-peak
]
DAY_END = 14400.0
DAY_SCHEDULE_B = "1500:4+2,5400:3+3,6900:2+4,10800:3+3"

# ----- split-sweep scenario ----------------------------------------------
SWEEP_SPLITS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
SWEEP_PERIODS_T = [(0, 900, OFFPEAK_TOTAL, 0.50), (900, 4500, PEAK_TOTAL, None),
                   (4500, 5400, OFFPEAK_TOTAL, 0.50)]
SWEEP_END = 7200.0
SWEEP_SCHEDULE_B = "600:4+2,4500:3+3"


def demand_file(tag, periods, seed, cross_end):
    rou = os.path.join(DEMDIR, tag + ".rou.xml")
    if os.path.exists(rou):
        return rou
    cmd = [sys.executable, os.path.join(SCRIPTS, "gen_demand.py"),
           "--out", rou, "--seed", str(seed), "--cross", "400",
           "--cross-end", str(int(cross_end))]
    for b, e, tot, sh in periods:
        cmd += ["--period", f"{int(b)},{int(e)},{tot},{sh}"]
    subprocess.run(cmd, check=True, capture_output=True)
    return rou


def run_one(job):
    mode, policy, seed, split = job
    if mode == "day":
        tag = f"day_s{seed}"
        rou = demand_file(tag, DAY_PERIODS, seed, 12600)
        end, sched = DAY_END, DAY_SCHEDULE_B
    else:
        tag = f"sw_p{int(split*100)}_s{seed}"
        periods = [(b, e, tot, split if sh is None else sh)
                   for b, e, tot, sh in SWEEP_PERIODS_T]
        rou = demand_file(tag, periods, seed, 5400)
        end, sched = SWEEP_END, SWEEP_SCHEDULE_B

    outdir = os.path.join(RUNDIR, f"{mode}_{policy}_{tag}")
    cmd = [sys.executable, os.path.join(SCRIPTS, "reversible_controller.py"),
           "--net", NET, "--routes", rou, "--outdir", outdir,
           "--policy", policy, "--start-config", "3+3",
           "--dead-time", "60", "--seed", str(seed), "--end", str(end)]
    if policy == "B":
        cmd += ["--schedule", sched]
    if policy == "C":
        # calibrated against the measured E2 occupancy range of this corridor
        # (see analysis/policyC_threshold_calibration.json)
        cmd += ["--occ-hi", "20", "--delta-on", "12", "--occ-lo", "12",
                "--delta-off", "5", "--confirm", "300", "--min-dwell", "900"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return dict(mode=mode, policy=policy, seed=seed, split=split,
                    error=r.stderr[-800:])
    m = run_metrics(outdir, rou, NET, end)
    cho = json.load(open(os.path.join(outdir, "changeover_log.json")))
    hs = json.load(open(os.path.join(outdir, "headon_scan.json")))
    return dict(
        mode=mode, policy=policy, seed=seed, split=split, outdir=outdir,
        person_hours_delay_corridor=m["corridor"]["person_hours_delay"],
        veh_hours_delay_corridor=m["corridor"]["veh_hours_delay"],
        person_hours_delay_network=m["network"]["person_hours_delay"],
        ph_delay_EB=m["groups"].get("EB", {}).get("person_hours_delay", 0.0),
        ph_delay_WB=m["groups"].get("WB", {}).get("person_hours_delay", 0.0),
        demand_EB=m["groups"].get("EB", {}).get("n", 0),
        demand_WB=m["groups"].get("WB", {}).get("n", 0),
        arrived_corridor=m["corridor"]["arrived"],
        unfinished_corridor=m["corridor"]["unfinished"],
        never_inserted_corridor=m["corridor"]["never_inserted"],
        teleports=m["teleports"],
        n_changeovers=cho["n_changeovers"],
        changeovers=[dict(t_request=c["t_request"], t_grant=c["t_grant"],
                          clearance_s=c["clearance_s"], phys=c["phys"],
                          loser=c["loser"], gainer=c["gainer"],
                          occ_at_grant=c["occupancy_at_grant_total"])
                     for c in cho["changeovers"]],
        headon_steps=hs["steps_with_opposing_cooccupancy"],
        headon_overlap_samples=hs["total_overlapping_pair_samples"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["day", "sweep"])
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    ensure_dirs()

    if a.mode == "day":
        jobs = [("day", p, s, None) for p in ("A", "B", "C") for s in SEEDS]
    else:
        jobs = [("sweep", p, s, sp) for sp in SWEEP_SPLITS
                for p in ("A", "B", "C") for s in SEEDS]
    print(f"{len(jobs)} runs")
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(run_one, jobs))
    bad = [r for r in rows if "error" in r]
    for b in bad:
        print("FAILED", b)
    out = os.path.join(ANADIR, f"{a.mode}_runs.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print("wrote", out, f"({len(rows)-len(bad)} ok, {len(bad)} failed)")


if __name__ == "__main__":
    main()
