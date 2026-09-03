"""
Reusable helpers for reading vehicle state from a running TraCI connection
and filtering it by common screening criteria (lane, edge, stopped status,
vehicle id, type, speed range, route).

Import into a step loop (e.g. the one in the sibling run-simulation skill's
scripts/run_traci_simulation.py) rather than running standalone — this
module doesn't connect to SUMO itself, it just reads state given an
already-connected `traci` (or `libsumo`) module.

Usage inside a step loop:

    import traci
    from vehicle_state import get_vehicles_state

    traci.start(["sumo", "-c", "config.sumocfg"])
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        stopped_on_lane = get_vehicles_state(
            traci, lane_id="in_N_0", stopped=True
        )
        fast_movers = get_vehicles_state(traci, min_speed=10.0)
        one_vehicle = get_vehicles_state(traci, ids=["veh0"])

    traci.close()
"""

from collections.abc import Iterable


def get_vehicle_state(traci_module, veh_id: str) -> dict:
    """Read the common state fields for a single vehicle currently in the network."""
    v = traci_module.vehicle
    return {
        "id": veh_id,
        "type": v.getTypeID(veh_id),
        "edge_id": v.getRoadID(veh_id),
        "lane_id": v.getLaneID(veh_id),
        "lane_index": v.getLaneIndex(veh_id),
        "lane_position": v.getLanePosition(veh_id),
        "position": v.getPosition(veh_id),  # (x, y)
        "speed": v.getSpeed(veh_id),
        "acceleration": v.getAcceleration(veh_id),
        "angle": v.getAngle(veh_id),
        "route_id": v.getRouteID(veh_id),
        "is_stopped": v.isStopped(veh_id),
        "waiting_time": v.getWaitingTime(veh_id),  # consecutive standing time (s); voluntary/scheduled stopping is excluded
        "accumulated_waiting_time": v.getAccumulatedWaitingTime(veh_id),  # over a configurable memory window
        "distance": v.getDistance(veh_id),  # total distance traveled so far (m)
        "next_tls": v.getNextTLS(veh_id),  # [(tlsID, tlsIndex, distance, state), ...] upcoming signals on the route
    }


def get_vehicles_state(
    traci_module,
    ids: Iterable[str] | None = None,
    lane_id: str | None = None,
    lane_ids: Iterable[str] | None = None,
    edge_id: str | None = None,
    edge_ids: Iterable[str] | None = None,
    stopped: bool | None = None,
    vtype: str | None = None,
    min_speed: float | None = None,
    max_speed: float | None = None,
    route_id: str | None = None,
) -> list:
    """
    Return state dicts for vehicles currently in the network, filtered by
    any combination of the given criteria. All filters are AND-combined;
    omit (leave as None) any filter that shouldn't apply.

    - ids: only consider these vehicle ids (skips ones not currently in the network)
    - lane_id / lane_ids: exact lane id, or any lane id in this collection
    - edge_id / edge_ids: exact edge id, or any edge id in this collection
    - stopped: True for only stopped vehicles, False for only moving ones
    - vtype: exact vehicle type id
    - min_speed / max_speed: inclusive speed bounds, m/s
    - route_id: exact route id
    """
    v = traci_module.vehicle
    candidates = list(ids) if ids is not None else v.getIDList()

    lane_id_set = set(lane_ids) if lane_ids is not None else None
    edge_id_set = set(edge_ids) if edge_ids is not None else None

    results = []
    for vid in candidates:
        try:
            veh_lane = v.getLaneID(vid)
            veh_edge = v.getRoadID(vid)
            veh_speed = v.getSpeed(vid)
        except Exception:
            continue  # vehicle no longer in the network (departed/arrived between calls)

        if lane_id is not None and veh_lane != lane_id:
            continue
        if lane_id_set is not None and veh_lane not in lane_id_set:
            continue
        if edge_id is not None and veh_edge != edge_id:
            continue
        if edge_id_set is not None and veh_edge not in edge_id_set:
            continue
        if min_speed is not None and veh_speed < min_speed:
            continue
        if max_speed is not None and veh_speed > max_speed:
            continue
        if vtype is not None and v.getTypeID(vid) != vtype:
            continue
        if route_id is not None and v.getRouteID(vid) != route_id:
            continue
        if stopped is not None and v.isStopped(vid) != stopped:
            continue

        results.append(get_vehicle_state(traci_module, vid))

    return results


def get_queue_length(traci_module, lane_id: str, speed_threshold: float = 0.1) -> int:
    """
    Convenience helper: count vehicles on a lane with speed below
    speed_threshold (m/s) — a common queue-length proxy for signal-timing
    state representations. Not the same as traci.lane.getLastStepHaltingNumber()
    only in that it's expressed via the same filtering machinery as the
    rest of this module, for consistency.
    """
    return len(get_vehicles_state(traci_module, lane_id=lane_id, max_speed=speed_threshold))
