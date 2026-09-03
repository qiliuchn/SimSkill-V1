"""
Standalone CLI for one-off vehicle control: starts (or attaches to) a SUMO
simulation, steps forward, applies a state change to a single vehicle, then
optionally holds for a few more steps to observe the effect. Useful for
quick testing without writing a step-loop script by hand; for anything
ongoing (a control policy, an RL environment), import vehicle_control
directly instead (see SKILL.md).

Usage:
    # Set speed
    python control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --speed 5

    # Force a lane change
    python control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --lane-index 1 --lane-change-duration 5

    # Stop at an edge/position
    python control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --stop-edge E1 --stop-pos 50 --stop-duration 30

    # Reroute to a new destination
    python control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --target-edge E9

    # Apply a named speed-mode preset (e.g. for controlled-vehicle experiments)
    python control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --speed-mode-preset run_red_light --speed 10

    # Attach to an already-running SUMO started with --remote-port
    python control_vehicle.py --port 8813 --vehicle-id veh0 --speed 0

    # Preview the parsed action without connecting to anything
    python control_vehicle.py --vehicle-id veh0 --speed 5 --dry-run
"""

import argparse
import os
import sys

from vehicle_control import set_vehicle_state, stop_vehicle, SPEED_MODE_PRESETS, LANE_CHANGE_MODE_PRESETS


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
    p = argparse.ArgumentParser(description="Apply a state change to a single vehicle in a SUMO/TraCI simulation.")

    conn = p.add_mutually_exclusive_group()
    conn.add_argument("--config", help="Path to a .sumocfg to start a new simulation")
    conn.add_argument("--port", type=int, help="Attach to an already-running SUMO on this TraCI port")

    p.add_argument("--gui", action="store_true", help="Use sumo-gui instead of headless sumo (only with --config)")
    p.add_argument("--libsumo", action="store_true", help="Use libsumo instead of traci (only with --config, headless-only)")

    p.add_argument("--vehicle-id", required=True, help="Id of the vehicle to control")
    p.add_argument("--step-to", type=float, default=None, help="Advance to this simulation time before applying the change (default: one step)")
    p.add_argument("--hold-steps", type=int, default=1, help="Steps to continue after applying the change, to observe the effect (default: 1)")

    # State-change options (mirrors vehicle_control.set_vehicle_state)
    p.add_argument("--speed", type=float, help="m/s; -1 releases speed control back to normal car-following")
    p.add_argument("--max-speed", type=float, help="New speed ceiling, m/s")
    p.add_argument("--lane-index", type=int, help="Force a lane change to this lane index")
    p.add_argument("--lane-change-duration", type=float, default=5.0, help="Seconds to hold the forced lane (default: 5)")
    p.add_argument("--route-edges", help="Comma-separated full replacement route (first edge must be vehicle's current edge)")
    p.add_argument("--route-id", help="Assign a pre-existing route by id")
    p.add_argument("--target-edge", help="Change only the destination; route is rebuilt")
    p.add_argument("--color", help="r,g,b,a each 0-255, e.g. 255,0,0,255")
    p.add_argument("--speed-mode", type=int, help="Raw speed-mode bitset")
    p.add_argument("--speed-mode-preset", choices=list(SPEED_MODE_PRESETS), help="Named speed-mode preset")
    p.add_argument("--lane-change-mode", type=int, help="Raw lane-change-mode bitset")
    p.add_argument("--lane-change-mode-preset", choices=list(LANE_CHANGE_MODE_PRESETS), help="Named lane-change-mode preset")
    p.add_argument("--resume", action="store_true", help="Resume the vehicle from a stop")

    p.add_argument("--stop-edge", help="Schedule a stop: edge id")
    p.add_argument("--stop-pos", type=float, help="Schedule a stop: position along the edge (m)")
    p.add_argument("--stop-duration", type=float, default=30.0, help="Schedule a stop: duration (s), default 30")
    p.add_argument("--stop-lane-index", type=int, default=0, help="Schedule a stop: lane index, default 0")
    p.add_argument("--stop-flags", type=int, default=0, help="Schedule a stop: flags bitset, default 0 (plain roadside stop)")

    p.add_argument("--dry-run", action="store_true", help="Print the parsed action without connecting to a simulation")
    return p.parse_args()


def build_state_kwargs(args):
    kwargs = {}
    if args.speed is not None:
        kwargs["speed"] = args.speed
    if args.max_speed is not None:
        kwargs["max_speed"] = args.max_speed
    if args.lane_index is not None:
        kwargs["lane_index"] = args.lane_index
        kwargs["lane_change_duration"] = args.lane_change_duration
    if args.route_edges:
        kwargs["route_edges"] = args.route_edges.split(",")
    if args.route_id:
        kwargs["route_id"] = args.route_id
    if args.target_edge:
        kwargs["target_edge"] = args.target_edge
    if args.color:
        kwargs["color"] = tuple(int(c) for c in args.color.split(","))
    if args.speed_mode is not None:
        kwargs["speed_mode"] = args.speed_mode
    elif args.speed_mode_preset:
        kwargs["speed_mode"] = SPEED_MODE_PRESETS[args.speed_mode_preset]
    if args.lane_change_mode is not None:
        kwargs["lane_change_mode"] = args.lane_change_mode
    elif args.lane_change_mode_preset:
        kwargs["lane_change_mode"] = LANE_CHANGE_MODE_PRESETS[args.lane_change_mode_preset]
    if args.resume:
        kwargs["resume"] = True
    return kwargs


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


def main():
    args = parse_args()
    state_kwargs = build_state_kwargs(args)
    has_stop = args.stop_edge is not None

    if not state_kwargs and not has_stop:
        sys.exit("No state change specified. Pass at least one of --speed, --lane-index, --stop-edge, etc.")

    if args.dry_run:
        print(f"Would apply to vehicle '{args.vehicle_id}':")
        if state_kwargs:
            print(f"  set_vehicle_state kwargs: {state_kwargs}")
        if has_stop:
            print(
                f"  stop_vehicle(edge_id={args.stop_edge!r}, pos={args.stop_pos}, "
                f"duration={args.stop_duration}, lane_index={args.stop_lane_index}, flags={args.stop_flags})"
            )
        return

    if not args.config and args.port is None:
        sys.exit("Need either --config (start a new sim) or --port (attach to a running one).")

    traci = connect(args)

    try:
        target = args.step_to if args.step_to is not None else 0
        while args.step_to is None or traci.simulation.getTime() < target:
            traci.simulationStep()
            if args.step_to is None:
                break

        if args.vehicle_id not in traci.vehicle.getIDList():
            print(f"Warning: '{args.vehicle_id}' is not currently in the network (not yet departed, or already arrived).", file=sys.stderr)

        if state_kwargs:
            applied = set_vehicle_state(traci, args.vehicle_id, **state_kwargs)
            print(f"Applied: {applied}")
        if has_stop:
            stop_vehicle(
                traci, args.vehicle_id, edge_id=args.stop_edge, pos=args.stop_pos,
                duration=args.stop_duration, lane_index=args.stop_lane_index, flags=args.stop_flags,
            )
            print(f"Stop scheduled at {args.stop_edge}:{args.stop_pos} for {args.stop_duration}s")

        for _ in range(args.hold_steps):
            traci.simulationStep()

        if args.vehicle_id in traci.vehicle.getIDList():
            v = traci.vehicle
            print(
                f"After: speed={v.getSpeed(args.vehicle_id):.2f} "
                f"edge={v.getRoadID(args.vehicle_id)} lane={v.getLaneID(args.vehicle_id)}"
            )
    finally:
        traci.close()


if __name__ == "__main__":
    main()
