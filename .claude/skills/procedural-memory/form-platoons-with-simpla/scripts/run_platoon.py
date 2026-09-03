#!/usr/bin/env python3
"""TraCI runner for the simpla platooning experiment.

Usage:
    run_platoon.py <scenario> <route_file> <out_dir> --net freeway.net.xml --vtypes vtypes.add.xml \
        [--simpla simpla.cfg.xml] [--main-edge main] [--main-edge-lanes 3] [--seed N]

- Starts sumo (headless) via TraCI.
- If --simpla is given, imports simpla and calls simpla.load(cfg) AFTER the traci
  connection is up (required order), then steps the sim; simpla registers itself as
  a step listener so platoon management runs automatically each step.
- Every second we sample simpla's own API (getPlatoonLeaderIDList /
  getAveragePlatoonLength) to record how many platoons exist and their mean size --
  this is the *empirical* proof that platoons formed, independent of the config.
- Enables fcd-output, tripinfo-output and loads the detector/edgeData additional.
"""
import os
import sys
import argparse
import csv

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

STEP_LENGTH = 0.25

MEAS_ADD_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<additional>
{loops}
    <edgeData id="ed_main" file="{ed}" period="60" edges="{edge}"/>
</additional>
"""


def build_loops(edge, n_lanes, pos, e1_out):
    return "\n".join(
        f'    <inductionLoop id="e1_{i}" lane="{edge}_{i}" pos="{pos}" period="60" file="{e1_out}"/>'
        for i in range(n_lanes)
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("route_file")
    ap.add_argument("out_dir")
    ap.add_argument("--net", required=True)
    ap.add_argument("--vtypes", required=True, help="Additional-file defining the base vType(s) and any platoon-role vTypes")
    ap.add_argument("--main-edge", default="main", help="Mainline edge id to instrument with E1 loops + edgeData")
    ap.add_argument("--main-edge-lanes", type=int, default=3)
    ap.add_argument("--detector-pos", type=float, default=2900.0, help="Position along --main-edge for the E1 loops")
    ap.add_argument("--simpla", default=None)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    NET = args.net
    VTYPES = args.vtypes

    args.out_dir = os.path.abspath(args.out_dir)
    os.makedirs(args.out_dir, exist_ok=True)
    # All output paths absolute -> no --output-prefix, no re-rooting surprises.
    fcd = os.path.join(args.out_dir, "fcd.xml")
    tripinfo = os.path.join(args.out_dir, "tripinfo.xml")
    plat_log = os.path.join(args.out_dir, "platoon_timeseries.csv")
    e1_out = os.path.join(args.out_dir, "e1_out.xml")
    ed_out = os.path.join(args.out_dir, "edgedata.xml")
    meas_add = os.path.join(args.out_dir, "meas.add.xml")
    loops = build_loops(args.main_edge, args.main_edge_lanes, args.detector_pos, e1_out)
    with open(meas_add, "w") as f:
        f.write(MEAS_ADD_TEMPLATE.format(loops=loops, ed=ed_out, edge=args.main_edge))

    sumo_bin = os.path.join(SUMO_HOME, "bin", "sumo")
    cmd = [
        sumo_bin,
        "-n", NET,
        "-a", "%s,%s" % (VTYPES, meas_add),
        "-r", args.route_file,
        "--step-length", str(STEP_LENGTH),
        "--fcd-output", fcd,
        "--device.fcd.period", "1.0",       # sample FCD once per sim-second
        "--tripinfo-output", tripinfo,
        "--seed", str(args.seed),
        "--time-to-teleport", "-1",         # disable teleporting so jams are real, not hidden
        "--no-step-log", "true",
        "--collision.action", "warn",
    ]

    traci.start(cmd)

    use_simpla = args.simpla is not None
    simpla = None
    if use_simpla:
        import simpla  # noqa: E402
        simpla.load(args.simpla)

    # --- step loop, sampling platoon state every 1.0 s ---
    rows = []
    step = 0
    steps_per_sec = int(round(1.0 / STEP_LENGTH))
    max_platoons = 0
    max_mean_size = 0.0
    total_managed_samples = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step += 1
        if step % steps_per_sec == 0:
            t = traci.simulation.getTime()
            n_running = traci.vehicle.getIDCount()
            if use_simpla:
                leaders = simpla.getPlatoonLeaderIDList()
                # count *real* platoons: size >= 2 (a lone "platoon" of 1 is not one)
                sizes = []
                for lid in leaders:
                    pid = simpla.getPlatoonID(lid)
                    info = simpla.getPlatoonInfo(pid)
                    if info and "members" in info:
                        sizes.append(len(info["members"]))
                real = [s for s in sizes if s >= 2]
                n_platoons = len(real)
                mean_size = (sum(real) / len(real)) if real else 0.0
                n_in_platoon = sum(real)
                max_platoons = max(max_platoons, n_platoons)
                max_mean_size = max(max_mean_size, mean_size)
                if n_platoons:
                    total_managed_samples += 1
                rows.append((round(t, 1), n_running, n_platoons,
                             round(mean_size, 3), n_in_platoon))
            else:
                rows.append((round(t, 1), n_running, 0, 0.0, 0))
        if step > 400000:
            break

    traci.close()

    with open(plat_log, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "n_running", "n_platoons_ge2", "mean_platoon_size", "n_veh_in_platoon"])
        w.writerows(rows)

    # summary to stdout for the driver script
    n_samples_with_platoons = sum(1 for r in rows if r[2] > 0)
    peak = max((r[2] for r in rows), default=0)
    print("SCENARIO=%s simpla=%s steps=%d fcd=%s tripinfo=%s"
          % (args.scenario, use_simpla, step, fcd, tripinfo))
    print("PLATOONS peak_count=%d max_mean_size=%.2f samples_with_platoons=%d/%d"
          % (peak, max_mean_size, n_samples_with_platoons, len(rows)))


if __name__ == "__main__":
    main()
