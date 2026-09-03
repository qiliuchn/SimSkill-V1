"""
Run one signal-config variant of a signalized intersection with pedestrian
crossings, loading given vehicle+pedestrian route files, and measure a
pedestrian-vehicle CONFLICT-EXPOSURE proxy via TraCI.

Generalized: derives crossing-to-conflicting-vehicle-link mappings directly
from the compiled net.xml's own <edge function="crossing" crossingEdges="..."/>
and <connection tl="..." linkIndex="..."/> elements -- no hardcoded arm names
or link-index tables, so this works on any signalized intersection netconvert
produced sidewalks/crossings for for(--sidewalks.guess --crossings.guess).

Conflict-exposure proxy (per simulation step, per crossing):
  count 1 if ALL of:
    (a) the crossing's own signal link is WALK (state char in 'gG'), AND
    (b) >=1 pedestrian is physically on the crossing edge, AND
    (c) >=1 conflicting vehicle movement (a <connection> whose from/to edge is
        one of the crossing's crossingEdges) is simultaneously signal-permitted
        (state char in 'gG') AND has a vehicle physically occupying its
        internal via-lane.
  -> genuine concurrent occupancy of a pedestrian and a permitted conflicting
     vehicle at the same crosswalk. Summed over crossings and steps.

Also logs, as sanity denominators:
  ped_on_crossing_ticks    : ped physically on a crossing (any signal state)
  walk_ticks                : crossing signal is walk with >=1 ped on it
  phys_conflict_ticks       : ped on crossing AND conflicting veh physically on
                              its via-lane, IGNORING signal state (upper bound)
And, if a `--scramble-program` is given, verifies once that switching to it
genuinely produces a step where every crossing link is green while every
vehicle link is red (an exclusive/scramble phase), rather than trusting the
program's XML definition alone.

Usage:
    python measure_conflict_exposure.py \
        --net net.xml --veh-routes veh.rou.xml --ped-routes ped.rou.xml \
        --tls-id center --tripinfo out/tripinfo.xml --conflict-out out/conflict.json \
        [--additional extra.add.xml] [--program programID] [--scramble-program programID]
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--net", required=True)
    p.add_argument("--veh-routes", required=True)
    p.add_argument("--ped-routes", required=True)
    p.add_argument("--tls-id", required=True)
    p.add_argument("--additional", default=None, help="optional additional-file(s), comma-separated, e.g. an alternate tlLogic program")
    p.add_argument("--program", default=None, help="tls programID to activate at simulation start")
    p.add_argument("--scramble-program", default=None, help="programID expected to contain an exclusive-pedestrian phase; verified live if given")
    p.add_argument("--tripinfo", required=True)
    p.add_argument("--conflict-out", required=True)
    p.add_argument("--max-time", type=float, default=3000.0)
    return p.parse_args()


def derive_crossing_conflict_map(net_path, tls_id):
    """From the compiled net.xml: {crossing_link_index: {"edge": crossing_edge_id,
    "crossing_edges": [veh_edge_ids...], "conflict_links": [veh_link_indices...]}}"""
    root = ET.parse(net_path).getroot()

    crossing_edges = {}  # edge_id -> set(crossingEdges)
    for e in root.findall("edge"):
        if e.get("function") == "crossing":
            spans = set((e.get("crossingEdges") or "").split())
            crossing_edges[e.get("id")] = spans

    veh_links = {}  # linkIndex -> (from_edge, to_edge)
    crossing_link_by_edge = {}  # crossing_edge_id -> linkIndex
    for c in root.findall("connection"):
        if c.get("tl") != tls_id:
            continue
        li = int(c.get("linkIndex"))
        frm, to = c.get("from"), c.get("to")
        if to in crossing_edges:
            crossing_link_by_edge[to] = li
        elif not frm.startswith(":") and not to.startswith(":"):
            veh_links[li] = (frm, to)
        elif not frm.startswith(":"):
            veh_links.setdefault(li, (frm, to))

    result = {}
    for edge_id, spans in crossing_edges.items():
        li = crossing_link_by_edge.get(edge_id)
        if li is None:
            continue
        conflict_links = [vli for vli, (frm, to) in veh_links.items() if frm in spans or to in spans]
        result[li] = {"edge": edge_id, "crossing_edges": sorted(spans), "conflict_links": sorted(conflict_links)}
    return result, veh_links


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import traci  # noqa: E402

    crossing_map, veh_links = derive_crossing_conflict_map(args.net, args.tls_id)
    if not crossing_map:
        raise SystemExit(f"No crossing links found for tls '{args.tls_id}' in {args.net} -- check --tls-id and that the net has crossings.")

    sumo_bin = "sumo"
    cmd = [sumo_bin, "-n", args.net,
           "-r", f"{args.veh_routes},{args.ped_routes}",
           "--pedestrian.model", "striping",
           "--tripinfo-output", args.tripinfo,
           "--no-step-log", "true",
           "--duration-log.statistics", "true"]
    if args.additional:
        cmd += ["--additional-files", args.additional]
    traci.start(cmd)
    if args.program:
        traci.trafficlight.setProgram(args.tls_id, args.program)

    controlled = traci.trafficlight.getControlledLinks(args.tls_id)
    via_lane = {li: entries[0][2] for li, entries in enumerate(controlled) if entries}

    scramble_verified = None
    conflict_ticks = 0
    per_crossing = {info["edge"]: 0 for info in crossing_map.values()}
    ped_on_crossing_ticks = 0
    walk_ticks = 0
    phys_conflict_ticks = 0
    steps = 0
    n_veh_links = len(veh_links)

    while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < args.max_time:
        traci.simulationStep()
        steps += 1
        state = traci.trafficlight.getRedYellowGreenState(args.tls_id)

        if args.scramble_program and scramble_verified is None:
            cross_states = [state[ci] for ci in crossing_map]
            veh_states = [state[i] for i in veh_links]
            if all(c in "gG" for c in cross_states):
                scramble_verified = {
                    "state": state,
                    "all_crossings_green": True,
                    "all_vehicles_red": all(v == "r" for v in veh_states),
                    "num_vehicle_links_red": sum(1 for v in veh_states if v == "r"),
                    "num_vehicle_links_total": n_veh_links,
                }

        for ci, info in crossing_map.items():
            edge = info["edge"]
            peds = traci.edge.getLastStepPersonIDs(edge)
            if not peds:
                continue
            ped_on_crossing_ticks += 1
            crossing_walk = state[ci] in "gG"
            if crossing_walk:
                walk_ticks += 1
            phys_veh = green_veh_present = False
            for v in info["conflict_links"]:
                lane = via_lane.get(v)
                if lane is None:
                    continue
                if traci.lane.getLastStepVehicleNumber(lane) > 0:
                    phys_veh = True
                    if state[v] in "gG":
                        green_veh_present = True
            if phys_veh:
                phys_conflict_ticks += 1
            if crossing_walk and green_veh_present:
                conflict_ticks += 1
                per_crossing[edge] += 1

    traci.close()

    out = {
        "steps": steps,
        "conflict_exposure_ticks": conflict_ticks,
        "conflict_exposure_by_crossing": per_crossing,
        "ped_on_crossing_ticks": ped_on_crossing_ticks,
        "walk_ticks": walk_ticks,
        "phys_conflict_ticks_ignoring_signal": phys_conflict_ticks,
        "scramble_verification": scramble_verified,
        "crossing_conflict_map": crossing_map,
    }
    with open(args.conflict_out, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
