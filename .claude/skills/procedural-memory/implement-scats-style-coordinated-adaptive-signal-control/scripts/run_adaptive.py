#!/usr/bin/env python3
"""Run the full adaptive controller (sub-goal 1) on the network under a given
demand regime/seed, writing tripinfo/summary plus the controller's own
cycle_log / dos_log / cycle_target_log for downstream analysis (common-cycle
verification, sub-goal 3/4/5/6 reuse)."""
import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "demand"))

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ.setdefault("SUMO_HOME", SUMO_HOME)
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402
from adaptive_system import SystemController  # noqa: E402
from demand_gen import write_demand, END  # noqa: E402
import build_rerouter  # noqa: E402

SUMO_BIN = os.path.join(os.path.dirname(os.path.dirname(SUMO_HOME.rstrip("/"))), "bin", "sumo")
NET = os.path.join(ROOT, "net", "arterial_static.net.xml")
DET = os.path.join(ROOT, "det", "detectors.add.xml")


def run(seed, regime, outdir, C0=90.0, min_green=8.0, end=END, fault=None,
        oversat_scale=1.0, update_interval_cycles=1):
    os.makedirs(outdir, exist_ok=True)
    trips_path = os.path.join(outdir, "trips.rou.xml")
    write_demand(trips_path, seed, regime)
    if oversat_scale != 1.0:
        _scale_trips(trips_path, oversat_scale)
    adds = [DET]
    if regime == "unpred":
        adds.append(build_rerouter.build(outdir))
    tripinfo = os.path.join(outdir, "tripinfo.xml")
    summary = os.path.join(outdir, "summary.xml")
    cmd = [SUMO_BIN, "-n", NET, "-r", trips_path, "-a", ",".join(adds),
           "--device.rerouting.probability", "1", "--device.rerouting.period", "20",
           "--no-step-log", "true", "--time-to-teleport", "300",
           "--ignore-route-errors", "true", "--end", str(int(end)),
           "--tripinfo-output", tripinfo, "--summary-output", summary,
           "--duration-log.statistics", "true", "--seed", str(seed)]
    traci.start(cmd)
    ctrl = SystemController(C0=C0, min_green=min_green, update_interval_cycles=update_interval_cycles)
    try:
        t = 0.0
        # step through the full demand horizon, THEN drain remaining vehicles
        # (matching command-line SUMO's own "run until empty" default) so
        # every comparison arm is scored on the SAME completed-trip population
        while t < end or traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            t = traci.simulation.getTime()
            if fault:
                fault(t, ctrl)
            ctrl.step(t)
            if t > end + 1800:   # safety cap: never drain forever
                break
    finally:
        traci.close()

    with open(os.path.join(outdir, "cycle_log.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["junction", "cyc_idx", "t_start", "t_end", "realized_C", "art_main", "art_left", "cross"])
        for j, plant in ctrl.plants.items():
            for k, (gs, ge, plan, C) in enumerate(plant.cycle_log):
                w.writerow([j, k, gs, ge, C, plan["ART_MAIN"], plan["ART_LEFT"], plan["CROSS"]])
    with open(os.path.join(outdir, "dos_log.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "junction", "stage", "dos_hat"])
        w.writerows(ctrl.dos_log)
    with open(os.path.join(outdir, "cycle_target_log.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "C_target", "critical_dos"])
        w.writerows(ctrl.cycle_target_log)
    with open(os.path.join(outdir, "audit_calls.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["call", "count"])
        for k, v in sorted(ctrl.audit_calls.items()):
            w.writerow([k, v])
    return dict(tripinfo=tripinfo, summary=summary, outdir=outdir, ctrl=ctrl)


def _scale_trips(path, scale):
    """Used only by the sub-goal-6 oversaturation stress test: multiply
    departure DENSITY by duplicating/dropping trips is complex; instead we
    just re-run write_demand with inflated internal rates via monkeypatch --
    see failure/oversaturation_run.py for the real mechanism. Kept as a no-op
    placeholder here to keep run() 's signature stable."""
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--regime", default="unpred", choices=["pred", "unpred"])
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    res = run(a.seed, a.regime, a.outdir)
    print("done:", res["outdir"])
