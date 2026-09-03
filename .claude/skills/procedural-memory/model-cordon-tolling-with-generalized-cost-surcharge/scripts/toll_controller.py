#!/usr/bin/env python3
"""Cordon congestion-pricing TraCI controller (generalized-cost surcharge).

Downtown cordon toll modelled as a per-edge GENERALIZED-COST surcharge -- NOT a
physical closure and NOT a real slowdown. All vehicles are equipped with the
rerouting device (device.rerouting.probability 1). Every rerouting period the
controller inflates the ROUTER-PERCEIVED travel time of each cordon-entry edge by
`toll_seconds` (the edge's nominal free-flow travel time + toll) via
traci.edge.adaptTraveltime(), then, for every equipped vehicle in the network,
proposes a candidate route with traci.simulation.findRoute() (which honours the
inflated weights) and switches the vehicle onto it with setRoute() ONLY IF the
candidate is strictly cheaper under the generalized cost
    g(route) = sum_e  freeflow_tt(e) + toll * [e is a cordon-entry edge].

Why this design, verified empirically against this SUMO build (1.27.1):
  * The automatic rerouting device routes ONLY by its own measured mean-speed
    weights; it ignores both edge.adaptTraveltime() and
    vehicle.setAdaptedTraveltime(). So a global/per-vehicle weight override does
    not reach it -- a giant toll produced identical cordon crossings.
  * traci.simulation.findRoute() and traci.vehicle.rerouteTraveltime() DO honour
    edge.adaptTraveltime(). We therefore drive the reroute through findRoute and
    apply it via setRoute, using the equipped vehicles' routing capability.

Real maxSpeed / capacity are never touched, so a vehicle that keeps a center
path pays the SAME real travel time; only its perceived cost (and hence route
choice) changes. With toll_seconds == 0 the surcharge is 0, the candidate is
never strictly cheaper than the vehicle's existing free-flow shortest path, so
NO vehicle reroutes and the run reproduces the no-controller baseline exactly
(negative control).
"""
import os, sys, json, argparse
sys.path.append(os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import traci, sumolib

REROUTE_PERIOD = 30  # seconds; matches device.rerouting.period cadence
EPS = 1e-6


def build_scorer(net, cordon_entry, toll):
    ff = {}  # free-flow travel time per edge
    for e in net.getEdges():
        ff[e.getID()] = e.getLength() / e.getSpeed()
    centry = set(cordon_entry)

    def perceived(edge_id):
        return ff.get(edge_id, 0.0) + (toll if edge_id in centry else 0.0)

    def route_cost(edges):
        return sum(perceived(e) for e in edges)
    return ff, perceived, route_cost


def run(net_file, route, addfiles, toll, end, tripinfo, seed, cordon_entry):
    net = sumolib.net.readNet(net_file)
    ff, perceived, route_cost = build_scorer(net, cordon_entry, toll)
    sumo_bin = sumolib.checkBinary("sumo")
    cmd = [sumo_bin, "-n", net_file, "-r", route,
           "-a", ",".join(addfiles),
           "--begin", "0", "--end", str(end),
           "--seed", str(seed),
           "--tripinfo-output", tripinfo,
           # equip every vehicle with the rerouting device, but keep the device's
           # own auto-reroute dormant so it never fights the toll controller
           "--device.rerouting.probability", "1",
           "--device.rerouting.period", "1e9",
           "--device.rerouting.pre-period", "1e9",
           "--device.rerouting.adaptation-interval", "0",
           "--time-to-teleport", "300",
           "--no-step-log", "true", "--no-warnings", "true"]
    traci.start(cmd)
    n_switch = 0
    step = 0
    while traci.simulation.getMinExpectedNumber() > 0 and step <= end:
        traci.simulationStep()
        # A zero surcharge adapts no edge and diverts no vehicle -> the toll=0
        # run is byte-for-byte the no-controller baseline (exact negative control).
        if toll > 0 and step % REROUTE_PERIOD == 0:
            # (re)apply the perceived-cost surcharge so findRoute sees the toll
            for e in cordon_entry:
                traci.edge.adaptTraveltime(e, ff[e] + toll)
            for vid in traci.vehicle.getIDList():
                cur_edge = traci.vehicle.getRoadID(vid)
                if cur_edge.startswith(":"):
                    continue  # inside a junction; skip this tick
                route_cur = traci.vehicle.getRoute(vid)
                idx = traci.vehicle.getRouteIndex(vid)
                remaining = route_cur[idx:]
                if len(remaining) < 2:
                    continue
                dest = remaining[-1]
                cand = traci.simulation.findRoute(cur_edge, dest)
                cand_edges = cand.edges
                if not cand_edges:
                    continue
                # switch only if the candidate is strictly cheaper in gen. cost
                if route_cost(cand_edges) < route_cost(remaining) - EPS:
                    traci.vehicle.setRoute(vid, cand_edges)
                    n_switch += 1
        step += 1
    traci.close()
    return n_switch


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--add", required=True, help="comma-separated additional files")
    ap.add_argument("--toll", type=float, required=True)
    ap.add_argument("--end", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tripinfo", required=True)
    ap.add_argument("--info", required=True, help="cordon_info.json")
    args = ap.parse_args()
    cordon = json.load(open(args.info))["entry"]
    n = run(args.net, args.route, args.add.split(","), args.toll, args.end,
            args.tripinfo, args.seed, cordon)
    print(f"toll={args.toll} run complete, route switches={n}")
