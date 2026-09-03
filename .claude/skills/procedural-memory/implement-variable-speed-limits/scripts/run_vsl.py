"""
Run a freeway bottleneck scenario, with or without a closed-loop Variable Speed
Limit (VSL) controller, via TraCI.

mode=baseline : no intervention. Native speed limits run untouched.
mode=<other>  : closed-loop VSL, driven by a named profile (see --profile-json).
                A set of E2 detectors just upstream of the bottleneck is read
                live every step; their occupancy is averaged and smoothed over
                a control interval. When smoothed occupancy crosses escalation
                thresholds, the posted max speed on a named upstream control
                zone (a list of edges) is stepped down through the profile's
                speed ladder to meter inflow; it is relaxed as occupancy falls.
                A hysteresis band (separate up/down thresholds per level) plus
                a minimum dwell time between changes prevent oscillation.

All modes should share an identical network, route file, and --seed so the
ONLY difference between runs is the VSL speed changes -- diff the actual sumo
command lines/config before trusting a baseline-vs-VSL comparison.

Profile JSON shape (see implement-variable-speed-limits SKILL.md for a worked
example):
    {
      "speeds_ms": [33.33, 27.78, 22.22, 16.67],
      "kmh":       [120, 100, 80, 60],
      "up":        [12.0, 20.0, 30.0],
      "down":      [7.0, 14.0, 22.0]
    }
`up[i]`/`down[i]` are the occupancy-percent thresholds for escalating from
level i to i+1 / de-escalating from level i+1 to i.

Usage:
    python run_vsl.py --mode vsl \
        --net freeway.net.xml --routes freeway.rou.xml --add detectors_vsl.add.xml \
        --control-zone-edges e1,e2,e3,e4 --control-detectors e2_s08_e4_l0,e2_s08_e4_l1,e2_s08_e4_l2 \
        --profile-json vsl_profile.json --control-interval 30 --min-dwell 60 \
        --outdir outputs/vsl --end 4500 --seed 42
"""

import argparse
import csv
import json
import os
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Run a freeway scenario with an optional closed-loop VSL controller.")
    p.add_argument("--mode", required=True, help='"baseline" for no intervention, or any other label naming a VSL configuration')
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--add", required=True, help="Additional-file(s) with the E2/E1 detector definitions for this run")
    p.add_argument("--outdir", required=True)
    p.add_argument("--control-zone-edges", default=None, help="Comma-separated upstream edges whose lanes get the VSL speed applied (required unless --mode baseline)")
    p.add_argument("--control-detectors", default=None, help="Comma-separated E2 detector ids just upstream of the bottleneck, read for the control decision (required unless --mode baseline)")
    p.add_argument("--profile-json", default=None, help="Path to a JSON file with speeds_ms/kmh/up/down arrays (required unless --mode baseline)")
    p.add_argument("--control-interval", type=float, default=30.0, help="Seconds between control decisions")
    p.add_argument("--min-dwell", type=float, default=60.0, help="Minimum seconds between speed-limit changes (hysteresis)")
    p.add_argument("--decel-mod", type=float, default=-3.0, help="m/s^2 threshold for a 'moderate' hard-braking event")
    p.add_argument("--decel-sev", type=float, default=-4.0, help="m/s^2 threshold for a 'severe' hard-braking event")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--end", type=float, default=4500)
    p.add_argument("--step-length", type=float, default=1.0)
    p.add_argument("--time-to-teleport", type=int, default=600)
    return p.parse_args()


def build_cmd(args):
    os.makedirs(args.outdir, exist_ok=True)
    return [
        "sumo", "-n", args.net, "-r", args.routes, "-a", args.add,
        "--tripinfo-output", os.path.join(args.outdir, "tripinfo.xml"),
        "--summary-output", os.path.join(args.outdir, "summary.xml"),
        "--fcd-output", os.path.join(args.outdir, "fcd.xml"),
        "--fcd-output.acceleration", "--device.fcd.period", "5",
        "--device.emissions.probability", "1.0",
        "--seed", str(args.seed), "--step-length", str(args.step_length),
        "--time-to-teleport", str(args.time_to_teleport),
        "--no-step-log", "true", "--duration-log.statistics", "true",
        "--end", str(args.end),
    ]


def apply_vsl(traci, level, prof, control_zone_edges):
    v = prof["speeds_ms"][level]
    for e in control_zone_edges:
        n = traci.edge.getLaneNumber(e)
        for li in range(n):
            traci.lane.setMaxSpeed(f"{e}_{li}", v)


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci  # noqa: E402

    is_baseline = args.mode == "baseline"
    prof = None
    control_zone_edges = control_dets = None
    if not is_baseline:
        if not (args.control_zone_edges and args.control_detectors and args.profile_json):
            raise SystemExit("--control-zone-edges, --control-detectors, and --profile-json are required unless --mode baseline")
        prof = json.load(open(args.profile_json))
        control_zone_edges = args.control_zone_edges.split(",")
        control_dets = args.control_detectors.split(",")
    kmh = prof["kmh"] if prof else [None]

    os.makedirs(args.outdir, exist_ok=True)
    trace_path = os.path.join(args.outdir, "control_trace.csv")
    changes_path = os.path.join(args.outdir, f"speed_changes_{args.mode}.csv")

    traci.start(build_cmd(args))

    level = 0
    last_change_t = -1e9
    prev_accel = {}
    mod_events = sev_events = mod_vehsteps = sev_vehsteps = 0
    occ_samples, spd_samples = [], []

    trace_f = open(trace_path, "w", newline="")
    trace_w = csv.writer(trace_f)
    trace_w.writerow(["time", "smoothed_occ_pct", "control_meanspeed_ms", "level", "vsl_kmh"])
    chg_f = open(changes_path, "w", newline="")
    chg_w = csv.writer(chg_f)
    chg_w.writerow(["time", "old_level", "new_level", "old_kmh", "new_kmh", "smoothed_occ_pct", "control_meanspeed_ms", "reason"])

    step = 0
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
            t = traci.simulation.getTime()

            for vid in traci.vehicle.getIDList():
                a = traci.vehicle.getAcceleration(vid)
                pa = prev_accel.get(vid, 0.0)
                if a < args.decel_mod:
                    mod_vehsteps += 1
                    if pa >= args.decel_mod:
                        mod_events += 1
                if a < args.decel_sev:
                    sev_vehsteps += 1
                    if pa >= args.decel_sev:
                        sev_events += 1
                prev_accel[vid] = a
            if step % 200 == 0:
                live = set(traci.vehicle.getIDList())
                prev_accel = {k: v for k, v in prev_accel.items() if k in live}

            if not is_baseline:
                occ, spd = [], []
                for d in control_dets:
                    o = traci.lanearea.getLastStepOccupancy(d)
                    s = traci.lanearea.getLastStepMeanSpeed(d)
                    if o >= 0:
                        occ.append(o)
                    if s >= 0:
                        spd.append(s)
                if occ:
                    occ_samples.append(sum(occ) / len(occ))
                if spd:
                    spd_samples.append(sum(spd) / len(spd))

                if step % args.control_interval == 0:
                    sm_occ = sum(occ_samples) / len(occ_samples) if occ_samples else 0.0
                    sm_spd = sum(spd_samples) / len(spd_samples) if spd_samples else -1.0
                    occ_samples.clear(); spd_samples.clear()

                    new_level, reason = level, ""
                    can_change = (t - last_change_t) >= args.min_dwell
                    n_levels = len(prof["speeds_ms"])
                    if level < n_levels - 1 and sm_occ > prof["up"][level] and can_change:
                        new_level = level + 1
                        reason = f"occ>{prof['up'][level]}"
                    elif level > 0 and sm_occ < prof["down"][level - 1] and can_change:
                        new_level = level - 1
                        reason = f"occ<{prof['down'][level - 1]}"
                    if new_level != level:
                        old = level
                        level = new_level
                        last_change_t = t
                        apply_vsl(traci, level, prof, control_zone_edges)
                        chg_w.writerow([f"{t:.0f}", old, level, kmh[old], kmh[level],
                                        f"{sm_occ:.2f}", f"{sm_spd:.2f}", reason])
                        chg_f.flush()
                    trace_w.writerow([f"{t:.0f}", f"{sm_occ:.2f}", f"{sm_spd:.2f}", level, kmh[level]])
    finally:
        traci.close()
        trace_f.close()
        chg_f.close()

    with open(os.path.join(args.outdir, "live_metrics.txt"), "w") as f:
        f.write(f"mode={args.mode}\n")
        f.write(f"moderate_brake_onset_events(<{args.decel_mod})={mod_events}\n")
        f.write(f"moderate_brake_vehicle_seconds(<{args.decel_mod})={mod_vehsteps}\n")
        f.write(f"severe_brake_onset_events(<{args.decel_sev})={sev_events}\n")
        f.write(f"severe_brake_vehicle_seconds(<{args.decel_sev})={sev_vehsteps}\n")
    print(f"[{args.mode}] done. moderate-brake onset events(<{args.decel_mod})={mod_events}, "
          f"severe(<{args.decel_sev})={sev_events}")


if __name__ == "__main__":
    main()
