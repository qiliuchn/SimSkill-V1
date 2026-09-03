"""
Run one taxi/DRT scenario under a given dispatch algorithm, via TraCI.

While SUMO writes tripinfo (persons+vehicles), stop-output, and the dispatch
log itself, this driver walks every simulation step recording, per taxi
vehicle: odometer distance split by occupancy bucket (0 => empty driving,
>=1 => occupied) and max simultaneous passengers aboard (occupancy) -- the
latter is the direct proof of whether ride-pooling actually occurred, since
a fleet can be *configured* for pooling without ever actually pooling anyone
under sparse demand. Writes a per-taxi CSV-shaped list and a JSON fleet
summary (occupancy_summary.json).

Usage:
    python run_taxi_scenario.py \
        --net net.xml --fleet taxis.rou.xml --persons persons.rou.xml \
        --algo greedyShared --label pool --outdir out/pool \
        [--dispatch-params key1:val1,key2:val2] [--taxi-vtype taxi] [--max-time 5400]
"""

import argparse
import json
import os
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Run a SUMO taxi/DRT scenario via TraCI and measure fleet occupancy/mileage.")
    p.add_argument("--net", required=True)
    p.add_argument("--fleet", required=True, help="Route file defining the taxi vehicles (vType with has.taxi.device=true)")
    p.add_argument("--persons", required=True, help="Route file with <person><ride lines=\"taxi\"/></person> reservations")
    p.add_argument("--algo", required=True, help="e.g. greedy | greedyShared | routeExtension -- see sumo --help for the full list installed")
    p.add_argument("--label", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--dispatch-params", default=None, help="Comma-separated key:value pairs passed to --device.taxi.dispatch-algorithm.params")
    p.add_argument("--taxi-vtype", default="taxi", help="vType id to treat as a taxi (must match the fleet file)")
    p.add_argument("--max-time", type=float, default=5400.0)
    return p.parse_args()


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci  # noqa: E402

    os.makedirs(args.outdir, exist_ok=True)
    cmd = ["sumo",
           "-n", args.net,
           "-r", f"{args.fleet},{args.persons}",
           "--device.taxi.dispatch-algorithm", args.algo,
           "--device.taxi.dispatch-algorithm.output", os.path.join(args.outdir, "dispatch.xml"),
           "--tripinfo-output", os.path.join(args.outdir, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished",
           "--stop-output", os.path.join(args.outdir, "stops.xml"),
           "--summary-output", os.path.join(args.outdir, "summary.xml"),
           "--no-step-log", "true",
           "--duration-log.statistics", "true",
           "--step-length", "1"]
    if args.dispatch_params:
        cmd += ["--device.taxi.dispatch-algorithm.params", args.dispatch_params]

    traci.start(cmd)

    taxi_ids = []
    prev_dist, empty_dist, occ_dist, max_occ, pooled_seconds, served_by_taxi = {}, {}, {}, {}, {}, {}

    while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < args.max_time:
        traci.simulationStep()
        for vid in traci.vehicle.getIDList():
            try:
                vtype = traci.vehicle.getTypeID(vid)
            except traci.TraCIException:
                continue
            if vtype != args.taxi_vtype:
                continue
            if vid not in prev_dist:
                prev_dist[vid] = traci.vehicle.getDistance(vid)
                empty_dist[vid] = occ_dist[vid] = 0.0
                max_occ[vid] = 0
                pooled_seconds[vid] = 0
                served_by_taxi[vid] = set()
                taxi_ids.append(vid)
            d = traci.vehicle.getDistance(vid)
            delta = max(0.0, d - prev_dist[vid])
            prev_dist[vid] = d
            occ = traci.vehicle.getPersonNumber(vid)
            if occ > 0:
                occ_dist[vid] += delta
            else:
                empty_dist[vid] += delta
            max_occ[vid] = max(max_occ[vid], occ)
            if occ >= 2:
                pooled_seconds[vid] += 1
            served_by_taxi[vid].update(traci.vehicle.getPersonIDList(vid))

    end_time = traci.simulation.getTime()
    remaining_persons = list(traci.person.getIDList())
    traci.close()

    rows = []
    tot_empty = tot_occ = 0.0
    n_pooled_taxis = 0
    for vid in taxi_ids:
        tot = empty_dist[vid] + occ_dist[vid]
        rows.append({
            "taxi": vid,
            "total_m": round(tot, 1),
            "empty_m": round(empty_dist[vid], 1),
            "occupied_m": round(occ_dist[vid], 1),
            "empty_frac": round(empty_dist[vid] / tot, 4) if tot > 0 else 0.0,
            "max_occupancy": max_occ[vid],
            "pooled_seconds": pooled_seconds[vid],
            "distinct_persons_served": len(served_by_taxi[vid]),
        })
        tot_empty += empty_dist[vid]
        tot_occ += occ_dist[vid]
        if max_occ[vid] >= 2:
            n_pooled_taxis += 1

    tot_all = tot_empty + tot_occ
    summary = {
        "label": args.label,
        "algo": args.algo,
        "dispatch_params": args.dispatch_params,
        "end_time_s": round(end_time, 1),
        "n_taxis": len(taxi_ids),
        "fleet_total_km": round(tot_all / 1000.0, 3),
        "fleet_empty_km": round(tot_empty / 1000.0, 3),
        "fleet_occupied_km": round(tot_occ / 1000.0, 3),
        "empty_mileage_frac": round(tot_empty / tot_all, 4) if tot_all > 0 else 0.0,
        "taxis_that_pooled": n_pooled_taxis,
        "max_fleet_occupancy": max(max_occ.values()) if max_occ else 0,
        "total_pooled_seconds": sum(pooled_seconds.values()),
        "persons_never_arrived": len(remaining_persons),
        "remaining_person_ids": remaining_persons,
        "per_taxi": rows,
    }
    with open(os.path.join(args.outdir, "occupancy_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("per_taxi", "remaining_person_ids")}, indent=2))


if __name__ == "__main__":
    main()
