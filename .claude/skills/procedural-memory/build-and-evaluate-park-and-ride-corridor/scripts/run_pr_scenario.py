#!/usr/bin/env python3
"""Run a park-and-ride corridor scenario via TraCI.

Adapted from `model-parking-with-rerouting`'s run_parking_scenario.py, but
person-aware: as well as sampling parkingArea occupancy (still the only way to
observe it -- SUMO 1.27 has no --parking-output CLI flag), it tracks which
vehicles actually occupied which lot, teleports, and persons still in the
network at the end (= stranded).
"""
import argparse
import json
import os
import sys

SUMO_HOME = os.environ.get("SUMO_HOME")
if SUMO_HOME:
    sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--additional", required=True)
    p.add_argument("--lots", default="")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--end", type=float, default=14400.0)
    p.add_argument("--time-to-teleport", type=float, default=300.0)
    p.add_argument("--device-rerouting-probability", type=float, default=None)
    p.add_argument("--sample-every", type=int, default=30)
    p.add_argument("--label", default="run")
    a = p.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    j = lambda f: os.path.join(a.out_dir, f)

    # edgeData additional written here so its `file=` resolves inside out-dir
    meas = j("meas.add.xml")
    with open(meas, "w") as fh:
        fh.write('<additional>\n  <edgeData id="ed900" file="%s" begin="0" end="200000" '
                 'period="900" excludeEmpty="true"/>\n</additional>\n' % "edgedata.xml")
    # NB: `file=` in an additional resolves RELATIVE TO THAT ADDITIONAL FILE's
    # directory, not the cwd -- passing an absolute/cwd-relative path here
    # produces a doubled path and a hard "Could not build output file" error.
    add = a.additional + "," + meas

    cmd = ["sumo", "-n", a.net, "-r", a.routes, "-a", add,
           "--tripinfo-output", j("tripinfo.xml"),
           "--tripinfo-output.write-unfinished",
           "--summary-output", j("summary.xml"),
           "--stop-output", j("stopinfo.xml"),
           # without this, a P+R car still parked at simulation end writes NO
           # stopinfo row at all -- stop-output only records *ended* stops
           "--stop-output.write-unfinished",
           "--vehroute-output", j("vehroutes.xml"),
           "--pedestrian.model", "striping",
           "--time-to-teleport", str(a.time_to_teleport),
           "--duration-log.statistics",
           "--no-step-log", "true",
           "--ignore-route-errors", "true",
           "--end", str(a.end),
           "--seed", "7"]
    if a.device_rerouting_probability is not None:
        cmd += ["--device.rerouting.probability", str(a.device_rerouting_probability),
                "--device.rerouting.period", "60"]

    lots = [x for x in a.lots.split(",") if x]
    traci.start(cmd)
    occ = {l: [] for l in lots}
    times = []
    parked_in = {}          # veh id -> lot it was seen parked in
    ever_parked = set()
    teleports = 0
    step = 0
    dt = traci.simulation.getDeltaT()
    while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < a.end:
        traci.simulationStep()
        teleports += traci.simulation.getStartingTeleportNumber()
        t = traci.simulation.getTime()
        if lots and step % a.sample_every == 0:
            times.append(t)
            for l in lots:
                ids = traci.parkingarea.getVehicleIDs(l)
                occ[l].append(len(ids))
                for v in ids:
                    parked_in[v] = l
                    ever_parked.add(v)
        elif lots:
            for l in lots:
                for v in traci.parkingarea.getVehicleIDs(l):
                    parked_in[v] = l
                    ever_parked.add(v)
        step += 1
    stranded_persons = list(traci.person.getIDList())
    remaining_veh = list(traci.vehicle.getIDList())
    end_time = traci.simulation.getTime()
    traci.close()

    res = {"label": a.label, "end_time": end_time, "teleports": teleports,
           "sample_times": times, "occupancy": occ,
           "parked_in": parked_in,
           "n_ever_parked": len(ever_parked),
           "peak_occupancy": {l: (max(v) if v else 0) for l, v in occ.items()},
           "lot_counts": {l: sum(1 for x in parked_in.values() if x == l) for l in lots},
           "stranded_persons_n": len(stranded_persons),
           "stranded_persons": stranded_persons[:50],
           "remaining_vehicles_n": len(remaining_veh)}
    with open(j("traci_metrics.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items()
                      if k not in ("sample_times", "occupancy", "parked_in", "stranded_persons")},
                     indent=1))


if __name__ == "__main__":
    main()
