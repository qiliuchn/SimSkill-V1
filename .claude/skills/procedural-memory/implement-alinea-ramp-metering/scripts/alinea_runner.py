#!/usr/bin/env python3
"""
Run one freeway on-ramp simulation with SUMO via TraCI, either unmetered or
with ALINEA feedback ramp metering.

Two modes:
  --mode unmetered : ramp signal held permanently GREEN (meter disabled) ->
                     all ramp vehicles enter freely.
  --mode metered   : ALINEA feedback ramp metering.

ALINEA (Papageorgiou et al.):
    r(k) = r(k-1) + K * (o_target - o_measured)
  every control interval, where o_measured is the occupancy [%] measured by
  the mainline detector(s) just DOWNSTREAM of the merge, o_target is the
  critical-occupancy setpoint, and K is the feedback gain (veh/h per % occ).
  r is clamped to [r_min, r_max] (veh/h).

Rate -> signal realization (one-car-per-green cycle):
  A metering cycle of length C = 3600 / r seconds is imposed on the ramp
  traffic light. Each cycle shows GREEN for `green_time` s (long enough to
  release ~one vehicle) then RED for the remainder, so the ramp discharges
  approximately r vehicles/hour. If C <= green_time the signal is held green
  (rate at or above saturation). This is the reusable core: any metering
  algorithm that outputs a target rate can plug into this same rate->signal
  realization rather than reinventing it.

Give each run's E1 detector additional-file a DEDICATED, absolute output
path, and never re-invoke sumo against that same path afterward for a
sanity check -- doing so silently overwrites the real detector output with
whatever the sanity run produced (verified the hard way: a stray
`sumo --end 1` check clobbered a full ~4600s detector file down to a single
1-second stub). Do any ad-hoc validation against a throwaway scratch path
instead, before or separate from the real run.

Writes tripinfo, per-step summary, the E1 detector file (via the additional
file), and a metering-log CSV (control-interval rate/occupancy trace).

Usage:
    python alinea_runner.py --net net.net.xml --routes demand.rou.xml \
        --additional detectors.add.xml --mode unmetered \
        --tripinfo runs/unmetered/tripinfo.xml --summary runs/unmetered/summary.xml \
        --metering-log runs/unmetered/metering_log.csv

    python alinea_runner.py --net net.net.xml --routes demand.rou.xml \
        --additional detectors.add.xml --mode metered \
        --tripinfo runs/metered/tripinfo.xml --summary runs/metered/summary.xml \
        --metering-log runs/metered/metering_log.csv \
        --K 70 --o-target 12 --r-min 400 --r-max 1800 --control-interval 60 --green-time 2
"""
import argparse
import csv
import os
import sys

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


def find_sumo():
    import shutil
    b = shutil.which("sumo")
    if b:
        return b
    return os.path.join(SUMO_HOME, "bin", "sumo")


def main():
    p = argparse.ArgumentParser(description="Run an unmetered or ALINEA-metered freeway on-ramp scenario via TraCI.")
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--additional", required=True, help="Additional file with E1 detectors (dedicated output path)")
    p.add_argument("--mode", choices=["unmetered", "metered"], required=True)
    p.add_argument("--tripinfo", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--metering-log", required=True)
    p.add_argument("--tls-id", default="n_meter", help="Ramp meter traffic-light id")
    p.add_argument("--down-detectors", default="e1_down_0,e1_down_1", help="Comma-separated downstream detector ids ALINEA reads")
    p.add_argument("--K", type=float, default=70.0, help="feedback gain veh/h per % occ")
    p.add_argument("--o-target", type=float, default=20.0, help="critical occupancy setpoint %% (calibrate per network, don't assume a textbook value)")
    p.add_argument("--r-min", type=float, default=400.0, help="min metering rate veh/h")
    p.add_argument("--r-max", type=float, default=1800.0, help="max metering rate veh/h")
    p.add_argument("--control-interval", type=float, default=60.0, help="ALINEA update interval s")
    p.add_argument("--green-time", type=float, default=2.0, help="green per metering cycle s")
    p.add_argument("--max-time", type=float, default=6000.0, help="hard cap on sim seconds")
    args = p.parse_args()

    down_dets = args.down_detectors.split(",")

    sumo = find_sumo()
    cmd = [
        sumo,
        "-n", args.net,
        "-r", args.routes,
        "-a", args.additional,
        "--tripinfo-output", args.tripinfo,
        "--summary-output", args.summary,
        "--step-length", "1",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",  # disable teleporting so gridlock/queuing is real, not hidden
        "--duration-log.disable", "true",
        "--no-warnings", "true",
    ]
    traci.start(cmd)

    tls = args.tls_id
    # single controlled link on the meter -> state strings have length 1
    n_links = len(traci.trafficlight.getRedYellowGreenState(tls))

    def set_state(chars):
        traci.trafficlight.setRedYellowGreenState(tls, chars * n_links)

    r = args.r_max  # start at max release
    ci = args.control_interval
    occ_accum = 0.0
    occ_count = 0
    cycle_start = 0.0
    log_rows = []

    if args.mode == "unmetered":
        set_state("G")

    t = 0.0
    while traci.simulation.getMinExpectedNumber() > 0 and t < args.max_time:
        traci.simulationStep()
        t = traci.simulation.getTime()

        if args.mode == "metered":
            occ = sum(traci.inductionloop.getLastStepOccupancy(d) for d in down_dets) / len(down_dets)
            occ_accum += occ
            occ_count += 1

            if occ_count >= ci:
                o_measured = occ_accum / occ_count
                r = r + args.K * (args.o_target - o_measured)
                r = max(args.r_min, min(args.r_max, r))
                log_rows.append([round(t, 1), round(o_measured, 2), round(r, 1)])
                occ_accum = 0.0
                occ_count = 0
                cycle_start = t  # realign cycle to fresh rate

            C = 3600.0 / r
            if C <= args.green_time:
                set_state("G")
            else:
                phase_t = t - cycle_start
                if phase_t >= C:
                    cycle_start = t
                    phase_t = 0.0
                set_state("G" if phase_t < args.green_time else "r")

    traci.close()

    with open(args.metering_log, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "occ_measured_pct", "rate_vehph"])
        w.writerows(log_rows)

    print(f"[{args.mode}] finished at t={t:.0f}s; metering updates logged: {len(log_rows)}")


if __name__ == "__main__":
    main()
