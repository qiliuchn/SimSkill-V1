"""
Standalone CLI for one-off vehicle-state inspection: starts (or attaches
to) a SUMO simulation, steps forward, and prints vehicle states matching
the given filters. Useful for quick debugging without writing a step-loop
script by hand; for anything ongoing (an RL environment, a control loop),
import vehicle_state.get_vehicles_state directly instead (see SKILL.md).

Usage:
    # Start a new simulation from a config, step to t=300, show all vehicles
    python query_vehicles.py --config sim.sumocfg --step-to 300

    # Only vehicles stopped on a specific lane
    python query_vehicles.py --config sim.sumocfg --step-to 300 --lane-id in_N_0 --stopped

    # Only moving vehicles above 5 m/s
    python query_vehicles.py --config sim.sumocfg --step-to 300 --min-speed 5 --moving

    # Specific vehicle ids
    python query_vehicles.py --config sim.sumocfg --step-to 300 --vehicle-ids veh0,veh3,veh7

    # Attach to an already-running SUMO started with --remote-port
    python query_vehicles.py --port 8813 --step-to 300

    # Keep printing a snapshot every N steps until the simulation ends
    python query_vehicles.py --config sim.sumocfg --watch --interval 50

    # JSON output instead of a table (for piping into other tools)
    python query_vehicles.py --config sim.sumocfg --step-to 300 --format json
"""

import argparse
import json
import os
import sys

from vehicle_state import get_vehicles_state


def _ensure_traci_on_path():
    if "SUMO_HOME" not in os.environ:
        sys.exit(
            "SUMO_HOME is not set. Set it to your SUMO install directory, "
            "e.g. export SUMO_HOME=/usr/share/sumo"
        )
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    if tools not in sys.path:
        sys.path.append(tools)


def parse_args():
    p = argparse.ArgumentParser(description="Query filtered vehicle state from a SUMO/TraCI simulation.")

    conn = p.add_mutually_exclusive_group(required=True)
    conn.add_argument("--config", help="Path to a .sumocfg to start a new simulation")
    conn.add_argument("--port", type=int, help="Attach to an already-running SUMO on this TraCI port")

    p.add_argument("--gui", action="store_true", help="Use sumo-gui instead of headless sumo (only with --config)")
    p.add_argument("--libsumo", action="store_true", help="Use libsumo instead of traci (only with --config, headless-only)")

    p.add_argument("--step-to", type=float, default=None, help="Advance to this simulation time before querying (default: one step)")
    p.add_argument("--watch", action="store_true", help="Keep stepping and printing a snapshot every --interval steps")
    p.add_argument("--interval", type=int, default=10, help="Steps between snapshots when --watch is set (default: 10)")
    p.add_argument("--max-steps", type=int, default=None, help="Stop after this many steps regardless of vehicles remaining")

    # Filters
    p.add_argument("--vehicle-ids", help="Comma-separated list of vehicle ids to restrict to")
    p.add_argument("--lane-id", help="Exact lane id")
    p.add_argument("--lane-ids", help="Comma-separated list of lane ids")
    p.add_argument("--edge-id", help="Exact edge id")
    p.add_argument("--edge-ids", help="Comma-separated list of edge ids")
    stop_group = p.add_mutually_exclusive_group()
    stop_group.add_argument("--stopped", action="store_true", help="Only stopped vehicles")
    stop_group.add_argument("--moving", action="store_true", help="Only moving (not stopped) vehicles")
    p.add_argument("--vtype", help="Exact vehicle type id")
    p.add_argument("--min-speed", type=float, help="Minimum speed, m/s")
    p.add_argument("--max-speed", type=float, help="Maximum speed, m/s")
    p.add_argument("--route-id", help="Exact route id")

    p.add_argument("--format", choices=["table", "json"], default="table", help="Output format (default: table)")
    return p.parse_args()


def connect(args):
    _ensure_traci_on_path()
    if args.libsumo:
        if args.gui:
            sys.exit("libsumo has no GUI support; drop --gui or drop --libsumo.")
        import libsumo as traci
    else:
        import traci

    if args.config:
        binary = "sumo-gui" if args.gui else "sumo"
        traci.start([binary, "-c", args.config])
    else:
        traci.init(port=args.port)

    return traci


def build_filters(args):
    filters = {}
    if args.vehicle_ids:
        filters["ids"] = args.vehicle_ids.split(",")
    if args.lane_id:
        filters["lane_id"] = args.lane_id
    if args.lane_ids:
        filters["lane_ids"] = args.lane_ids.split(",")
    if args.edge_id:
        filters["edge_id"] = args.edge_id
    if args.edge_ids:
        filters["edge_ids"] = args.edge_ids.split(",")
    if args.stopped:
        filters["stopped"] = True
    if args.moving:
        filters["stopped"] = False
    if args.vtype:
        filters["vtype"] = args.vtype
    if args.min_speed is not None:
        filters["min_speed"] = args.min_speed
    if args.max_speed is not None:
        filters["max_speed"] = args.max_speed
    if args.route_id:
        filters["route_id"] = args.route_id
    return filters


def print_states(states, fmt, sim_time):
    if fmt == "json":
        print(json.dumps({"time": sim_time, "vehicles": states}, indent=2))
        return

    print(f"\n--- t={sim_time} | {len(states)} vehicle(s) ---")
    if not states:
        return
    header = f"{'id':<10}{'edge':<12}{'lane':<14}{'speed':>8}{'stopped':>9}{'waiting':>9}"
    print(header)
    print("-" * len(header))
    for s in states:
        print(
            f"{s['id']:<10}{s['edge_id']:<12}{s['lane_id']:<14}"
            f"{s['speed']:>8.2f}{str(s['is_stopped']):>9}{s['waiting_time']:>9.1f}"
        )


def main():
    args = parse_args()
    traci = connect(args)
    filters = build_filters(args)

    try:
        step = 0
        target = args.step_to if args.step_to is not None else 0

        while True:
            traci.simulationStep()
            step += 1

            reached_target = args.step_to is None or traci.simulation.getTime() >= target
            should_print = args.watch and step % args.interval == 0
            should_stop = args.max_steps is not None and step >= args.max_steps
            no_vehicles_left = traci.simulation.getMinExpectedNumber() <= 0

            if not args.watch and reached_target:
                states = get_vehicles_state(traci, **filters)
                print_states(states, args.format, traci.simulation.getTime())
                break

            if args.watch and should_print:
                states = get_vehicles_state(traci, **filters)
                print_states(states, args.format, traci.simulation.getTime())

            if should_stop or no_vehicles_left:
                break
    finally:
        traci.close()


if __name__ == "__main__":
    main()
