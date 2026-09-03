"""
Reusable helpers for changing the state of a single vehicle in a running
TraCI connection: speed, lane, route/destination, stops, color, and the
safety-check overrides (speed mode / lane change mode) that research code
commonly needs for controlled-vehicle experiments.

Import into a step loop, same as the sibling get-vehicles-state skill's
vehicle_state.py — this module doesn't connect to SUMO itself, it just
issues commands given an already-connected `traci` (or `libsumo`) module.

Usage inside a step loop:

    import traci
    from vehicle_control import set_vehicle_state, stop_vehicle, SPEED_MODE_PRESETS

    traci.start(["sumo", "-c", "config.sumocfg"])
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        # Multiple changes in one call
        set_vehicle_state(traci, "veh0", speed=10.0, color=(255, 0, 0, 255))

        # Force a lane change for 5 seconds
        set_vehicle_state(traci, "veh0", lane_index=1, lane_change_duration=5.0)

        # Stop a vehicle at a specific edge/position for 30s
        stop_vehicle(traci, "veh0", edge_id="in_N", pos=50.0, duration=30.0)

        # Let a controlled vehicle run a red light (research/testing only)
        traci.vehicle.setSpeedMode("veh0", SPEED_MODE_PRESETS["run_red_light"])

    traci.close()
"""

from typing import Optional


# Named speed-mode bitsets (see TraCI/Change_Vehicle_State.html#speed_mode_0xb3).
# Each bit enables a safety check when set to 1; clearing it disables that check.
SPEED_MODE_PRESETS = {
    "default": 31,                       # all checks on (SUMO's own default)
    "legacy": 0,                         # all safety checks off, but still obeys signals/row implicitly via other logic
    "aggressive_no_safety": 96,          # ignore right-of-way within intersections + ignore speed limit
    "ignore_row_within_intersection": 55,  # disregard right-of-way for vehicles already inside the intersection
    "run_red_light": 7,                  # allows running a red light (still needs setSpeed/slowDown to actually do it)
    "run_red_light_ignore_occupied": 39, # as above, even if the intersection already has traffic in it
}

# Default lane-change-mode presets (see .../lane_change_mode_0xb6).
LANE_CHANGE_MODE_PRESETS = {
    "default": 1621,               # autonomous changes allowed unless conflicting with a TraCI request
    "collision_avoidance_only": 256,   # no autonomous changing, but safety checks still apply
    "collision_and_gap_safety_only": 512,  # as above, plus safety-gap enforcement
    "no_safety_checks": 0,         # disable all autonomous changing AND safety checks — use with caution
}


def set_vehicle_state(
    traci_module,
    veh_id: str,
    speed: Optional[float] = None,
    max_speed: Optional[float] = None,
    lane_index: Optional[int] = None,
    lane_change_duration: float = 5.0,
    route_edges: Optional[list] = None,
    route_id: Optional[str] = None,
    target_edge: Optional[str] = None,
    color: Optional[tuple] = None,
    speed_mode: Optional[int] = None,
    lane_change_mode: Optional[int] = None,
    resume: bool = False,
) -> dict:
    """
    Apply any combination of the given state changes to a single vehicle.
    Only arguments that are not None (or resume=True) are applied; omit
    whatever shouldn't change. Returns a dict summarizing what was applied.

    - speed: m/s; -1 releases speed control back to normal car-following
    - max_speed: m/s, changes the vehicle's speed ceiling (vType-level otherwise)
    - lane_index: forces a lane change, held for lane_change_duration seconds
    - route_edges: full replacement route as a list of edge ids (first edge
      must be the one the vehicle is currently on)
    - route_id: assign a pre-existing route by id (must start at the vehicle's
      current edge)
    - target_edge: change only the destination; route is rebuilt to reach it
    - color: (r, g, b, a), each 0-255
    - speed_mode / lane_change_mode: raw bitset ints — see SPEED_MODE_PRESETS /
      LANE_CHANGE_MODE_PRESETS for common values, or the TraCI docs for custom ones
    - resume: True to resume from a stop
    """
    v = traci_module.vehicle
    applied = {}

    if speed is not None:
        v.setSpeed(veh_id, speed)
        applied["speed"] = speed
    if max_speed is not None:
        v.setMaxSpeed(veh_id, max_speed)
        applied["max_speed"] = max_speed
    if lane_index is not None:
        v.changeLane(veh_id, lane_index, lane_change_duration)
        applied["lane_index"] = lane_index
    if route_edges is not None:
        v.setRoute(veh_id, route_edges)
        applied["route_edges"] = route_edges
    if route_id is not None:
        v.setRouteID(veh_id, route_id)
        applied["route_id"] = route_id
    if target_edge is not None:
        v.changeTarget(veh_id, target_edge)
        applied["target_edge"] = target_edge
    if color is not None:
        v.setColor(veh_id, color)
        applied["color"] = color
    if speed_mode is not None:
        v.setSpeedMode(veh_id, speed_mode)
        applied["speed_mode"] = speed_mode
    if lane_change_mode is not None:
        v.setLaneChangeMode(veh_id, lane_change_mode)
        applied["lane_change_mode"] = lane_change_mode
    if resume:
        v.resume(veh_id)
        applied["resumed"] = True

    return applied


def stop_vehicle(
    traci_module,
    veh_id: str,
    edge_id: str,
    pos: float,
    duration: float = 2**31 - 1,
    lane_index: int = 0,
    flags: int = 0,
    start_pos: float = -1,
    until: float = -1,
) -> None:
    """
    Schedule a stop for a vehicle at a specific edge/position. Re-issuing a
    stop at the same edge/position changes its duration; setting duration=0
    cancels an existing stop at that location.

    flags is a bitset: 1=parking, 2=triggered, 4=containerTriggered,
    8=busStop (edge_id becomes the busStop id), 16=containerStop,
    32=chargingStation, 64=parkingArea. Leave at 0 for a plain roadside stop.
    """
    traci_module.vehicle.setStop(
        veh_id, edge_id, pos=pos, laneIndex=lane_index, duration=duration,
        flags=flags, startPos=start_pos, until=until,
    )


def resume_vehicle(traci_module, veh_id: str) -> None:
    """Resume a vehicle from a stop."""
    traci_module.vehicle.resume(veh_id)


def force_lane_change(traci_module, veh_id: str, lane_index: int, duration: float = 1000.0) -> None:
    """Force a vehicle onto a specific lane index for the given duration (s)."""
    traci_module.vehicle.changeLane(veh_id, lane_index, duration)


def reroute_to_edge(traci_module, veh_id: str, edge_id: str) -> None:
    """Change only the vehicle's destination; route is rebuilt automatically."""
    traci_module.vehicle.changeTarget(veh_id, edge_id)


def release_speed_control(traci_module, veh_id: str) -> None:
    """Undo a prior setSpeed override, returning the vehicle to normal car-following behavior."""
    traci_module.vehicle.setSpeed(veh_id, -1)
