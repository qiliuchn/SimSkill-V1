#!/usr/bin/env python3
"""How long does the changeover sweep actually take?

Sweeps the two things the clearance time is supposed to depend on --
reversible-lane LENGTH and the RESIDUAL QUEUE on it when the sweep starts --
with the nominal dead time set to 0 so the measured number is the raw sweep
time and nothing else.

Writes outputs/analysis/clearance_study.json + clearance_study.csv
"""
import csv
import json
import os
import statistics as st
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NETDIR, DEMDIR, RUNDIR, ANADIR, SCRIPTS, ensure_dirs

LENGTHS = [1000, 2000, 3000, 4500]
WB_LOAD = [1200, 2000, 2800, 3200]      # veh/h westbound (2-lane cap ~2059,
                                        # 3-lane cap ~3113)
SEEDS = [201, 202, 203]
FLIP_T = 1500.0
END = 2400.0


def netfile(L):
    return os.path.join(NETDIR, "encB_open.net.xml" if L == 3000
                        else f"encB_open_L{L}.net.xml")


def one(args):
    L, wb, seed = args
    tag = f"clr_L{L}_W{wb}_s{seed}"
    rou = os.path.join(DEMDIR, tag + ".rou.xml")
    total = wb + 1600            # keep a constant modest eastbound load
    share = 1600.0 / total
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "gen_demand.py"),
                    "--out", rou, "--seed", str(seed),
                    "--period", f"0,{int(END)},{total},{share:.4f}",
                    "--cross", "400", "--cross-end", str(int(END))],
                   check=True, capture_output=True)
    outdir = os.path.join(RUNDIR, tag)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "reversible_controller.py"),
                        "--net", netfile(L), "--routes", rou, "--outdir", outdir,
                        "--policy", "B", "--start-config", "3+3",
                        "--schedule", f"{int(FLIP_T)}:4+2", "--dead-time", "0",
                        "--seed", str(seed), "--end", str(END)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return dict(length=L, wb_demand=wb, seed=seed, error=r.stderr[-500:])
    cho = json.load(open(os.path.join(outdir, "changeover_log.json")))
    hs = json.load(open(os.path.join(outdir, "headon_scan.json")))
    c = cho["changeovers"][0]
    return dict(length_m=L, wb_demand_vph=wb, seed=seed,
                residual_vehicles_at_sweep_start=c["cohort_on_lane_at_sweep_start"],
                clearance_s=c["clearance_s"],
                left_by_lane_change=c["cohort_left_by_lane_change"],
                left_downstream_exit=c["cohort_left_downstream_exit"],
                occupancy_at_grant=c["occupancy_at_grant_total"],
                headon_steps=hs["steps_with_opposing_cooccupancy"])


def main():
    ensure_dirs()
    jobs = [(L, wb, s) for L in LENGTHS for wb in WB_LOAD for s in SEEDS]
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, jobs))
    rows = [r for r in rows if "error" not in r]

    cells = {}
    for r in rows:
        cells.setdefault((r["length_m"], r["wb_demand_vph"]), []).append(r)
    summary = []
    for (L, wb), rs in sorted(cells.items()):
        cl = [x["clearance_s"] for x in rs]
        res = [x["residual_vehicles_at_sweep_start"] for x in rs]
        lat = sum(x["left_by_lane_change"] for x in rs)
        dwn = sum(x["left_downstream_exit"] for x in rs)
        summary.append(dict(
            length_m=L, wb_demand_vph=wb, n_seeds=len(rs),
            mean_residual_vehicles=round(st.mean(res), 1),
            mean_clearance_s=round(st.mean(cl), 1),
            min_clearance_s=min(cl), max_clearance_s=max(cl),
            free_flow_traverse_s=round(L / 16.67, 1),
            clearance_over_freeflow=round(st.mean(cl) / (L / 16.67), 3),
            pct_left_by_lane_change=round(100.0 * lat / max(lat + dwn, 1), 1),
            all_grants_at_zero_occupancy=all(x["occupancy_at_grant"] == 0 for x in rs),
            total_headon_steps=sum(x["headon_steps"] for x in rs)))

    with open(os.path.join(ANADIR, "clearance_study.json"), "w") as f:
        json.dump(dict(runs=rows, summary=summary), f, indent=2)
    with open(os.path.join(ANADIR, "clearance_study.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    for s in summary:
        print(s)
    print("\nwrote", os.path.join(ANADIR, "clearance_study.json"))


if __name__ == "__main__":
    main()
