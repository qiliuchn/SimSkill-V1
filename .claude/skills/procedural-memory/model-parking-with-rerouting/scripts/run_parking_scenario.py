"""
Run a SUMO parking scenario via TraCI, recording per-parkingArea occupancy over time,
per-vehicle parking-search time, actual-vs-assigned lot, and failed-to-park/teleport events.

Usage:
    python run_parking_scenario.py --net grid.net.xml --routes routes.rou.xml \
        --additional parking.add.xml --lots PA0,PA1,PA2,PA3,PA4,PA5 --out-dir outputs/disabled \
        --tripinfo-output outputs/disabled/tripinfo.xml --summary-output outputs/disabled/summary.xml

    # Same demand, rerouting enabled: add the rerouter file and the rerouting device
    python run_parking_scenario.py --net grid.net.xml --routes routes.rou.xml \
        --additional parking.add.xml,rerouter.add.xml --lots PA0,PA1,PA2,PA3,PA4,PA5 \
        --out-dir outputs/enabled --device-rerouting-probability 1 \
        --tripinfo-output outputs/enabled/tripinfo.xml --summary-output outputs/enabled/summary.xml

Why TraCI instead of a CLI flag: as of SUMO 1.27.x there is no `--parking-output`-style CLI
option or parkingArea `output` attribute that emits an occupancy-over-time file directly —
verified via `sumo --help` before writing this script, rather than assumed. `parkingarea.get*`
TraCI calls are the actual mechanism for observing occupancy live, so this script drives the
simulation step-by-step to sample it, while still letting SUMO write the normal tripinfo/summary/
stop-output files for the standard travel-time-style metrics.

`--time-to-teleport` matters here beyond its usual meaning: with parking rerouting disabled (or
if every alternative is also full), a vehicle stuck waiting for space at a full lot will
eventually be teleported by SUMO's normal stuck-vehicle handling — this is what turns unresolved
lot over-subscription into a concrete, countable "failed to park" event rather than an indefinite
wait. Set it low enough (e.g. 120s) that the scenario's timeframe can actually produce these
events if over-subscription isn't resolved.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Run a SUMO parking scenario via TraCI, tracking occupancy and parking outcomes.")
    p.add_argument("--net", required=True, help="Input .net.xml")
    p.add_argument("--routes", required=True, help="Input .rou.xml with parking stops (<stop parkingArea=... duration=... parking=\"true\"/>)")
    p.add_argument("--additional", required=True, help="Comma-separated additional file(s) — at least the parkingArea file; include the rerouter file too when rerouting should be enabled")
    p.add_argument("--lots", required=True, help="Comma-separated parkingArea ids to track occupancy for")
    p.add_argument("--out-dir", required=True, help="Directory for traci_metrics.json (created if missing)")
    p.add_argument("--tripinfo-output", required=True)
    p.add_argument("--summary-output", required=True)
    p.add_argument("--stop-output", help="Optional --stop-output file")
    p.add_argument("--time-to-teleport", type=float, default=120.0, help="Seconds before SUMO teleports a stuck vehicle (default: 120)")
    p.add_argument("--device-rerouting-probability", type=float, help="Set to 1 to equip every vehicle with the rerouting device (needed for parkingAreaReroute to take effect)")
    p.add_argument("--end", type=float, default=3600.0, help="Max simulation time (default: 3600)")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        sys.exit("SUMO_HOME is not set.")
    sys.path.append(os.path.join(sumo_home, "tools"))
    import traci

    lots = args.lots.split(",")

    rt = ET.parse(args.routes).getroot()
    assigned = {}
    for v in rt.findall("vehicle"):
        s = v.find("stop")
        if s is not None and s.get("parkingArea"):
            assigned[v.get("id")] = s.get("parkingArea")

    import shutil
    sumo_bin = shutil.which("sumo")
    if not sumo_bin:
        candidate = os.path.join(sumo_home, "bin", "sumo")
        sumo_bin = candidate if os.path.isfile(candidate) else "sumo"

    cmd = [
        sumo_bin,
        "-n", args.net,
        "-r", args.routes,
        "-a", args.additional,
        "--tripinfo-output", args.tripinfo_output,
        "--summary-output", args.summary_output,
        "--time-to-teleport", str(args.time_to_teleport),
        "--no-step-log", "true",
        "--end", str(args.end),
    ]
    if args.stop_output:
        cmd += ["--stop-output", args.stop_output, "--stop-output.write-unfinished"]
    if args.device_rerouting_probability is not None:
        cmd += ["--device.rerouting.probability", str(args.device_rerouting_probability)]

    traci.start(cmd)

    occ = {p: [] for p in lots}
    times = []
    arrive_t, park_t, actual_lot = {}, {}, {}
    teleport_ids = set()

    step = 0
    while traci.simulation.getMinExpectedNumber() > 0 and step < args.end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        times.append(t)
        for p in lots:
            occ[p].append(traci.parkingarea.getVehicleCount(p))

        for vid in traci.simulation.getStartingTeleportIDList():
            teleport_ids.add(vid)

        for vid in traci.vehicle.getIDList():
            if vid not in park_t:
                if vid not in arrive_t:
                    stops = traci.vehicle.getStops(vid, 1)
                    if stops:
                        edge = stops[0].lane.rsplit("_", 1)[0]
                        if traci.vehicle.getRoadID(vid) == edge:
                            arrive_t[vid] = t
                if traci.vehicle.isStoppedParking(vid):
                    park_t[vid] = t
                    for p in lots:
                        if vid in traci.parkingarea.getVehicleIDs(p):
                            actual_lot[vid] = p
                            break
        step += 1

    traci.close()

    parked = set(park_t.keys())
    all_veh = set(assigned.keys())
    failed = sorted(all_veh - parked)
    search_times = {vid: park_t[vid] - arrive_t[vid] for vid in parked if vid in arrive_t}
    peak_occ = {p: (max(occ[p]) if occ[p] else 0) for p in lots}

    result = {
        "n_vehicles": len(all_veh),
        "n_parked": len(parked),
        "n_failed_to_park": len(failed),
        "failed_ids": failed,
        "n_teleports": len(teleport_ids),
        "teleport_ids": sorted(teleport_ids),
        "mean_search_time": (sum(search_times.values()) / len(search_times)) if search_times else None,
        "search_times": search_times,
        "assigned": assigned,
        "actual_lot": actual_lot,
        "peak_occ": peak_occ,
        "times": times,
        "occ": occ,
    }
    out_path = os.path.join(args.out_dir, "traci_metrics.json")
    with open(out_path, "w") as f:
        json.dump(result, f)

    print(f"parked={len(parked)} failed={len(failed)} teleports={len(teleport_ids)} "
          f"mean_search={result['mean_search_time']}")
    print("peak occupancy:", peak_occ)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
