---
summary: The TraCI vehicle-state-changing command family covers setting speed, forcing lane changes, rerouting, scheduling stops, and overriding safety-check behavior (speed mode, lane change mode) for a single vehicle during a running simulation.
keywords:
  - change-vehicle-state
  - set-speed
  - set-stop
  - speed-mode
  - lane-change-mode
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T17:56:30
sources:
  - "[[raw-materials/Change Vehicle State.md]]"
  - https://sumo.dlr.de/docs/TraCI/Change_Vehicle_State.html
related_pages:
  - "[[traci]]"
  - "[[sumo-rl-environment]]"
  - "[[glosa-eco-driving]]"
related_skills:
  - set-vehicle-state
  - get-vehicles-state
  - implement-glosa-speed-advisory-controller
related_skills_for_graph_view:
  - "[[set-vehicle-state]]"
  - "[[get-vehicles-state]]"
  - "[[implement-glosa-speed-advisory-controller]]"
---

# Change Vehicle State

This is the [[traci]] command family for writing a single vehicle's state during a running simulation — the counterpart to vehicle value retrieval. All commands operate on a `vehID` that must already be present in the simulation (departed and not yet arrived).

## Motion control

- `setSpeed(vehID, speed)`: m/s; `-1` releases speed control back to normal car-following behavior. Setting an exact numeric speed (including 0) forces that speed under whatever safety checks are active — it is not the same as scheduling a stop.
- `slowDown(vehID, speed, duration)`: smooth deceleration to a target speed over a duration, rather than an instant change.
- `setMaxSpeed(vehID, speed)`: changes the vehicle's speed ceiling (otherwise inherited from its vehicle type).
- `setAcceleration(vehID, accel, duration)`: force a specific acceleration for a duration.

## Lane and route control

- `changeLane(vehID, laneIndex, duration)`: force a lane change onto an absolute lane index (on the vehicle's current edge) held for `duration` seconds.
- `changeTarget(vehID, edgeID)`: change only the destination edge; the route to reach it is rebuilt automatically. Requires the vehicle to be outside an intersection and the new route to still include its current edge.
- `setRoute(vehID, edgeList)`: replace the full route with an explicit edge list (first edge must be the vehicle's current one).
- `setRouteID(vehID, routeID)`: assign a pre-existing route by id (same current-edge constraint).

## Stops

- `setStop(vehID, edgeID, pos, laneIndex, duration, flags, startPos, until)`: schedule a stop at a specific edge/position. Re-issuing a stop at the same edge/position changes its duration; `duration=0` cancels it. `flags` is a bitset: 1=parking, 2=triggered, 4=containerTriggered, 8=busStop (edgeID becomes the stop id), 16=containerStop, 32=chargingStation, 64=parkingArea — 0 is a plain roadside stop.
- `resume(vehID)`: resume from a stop.

Note the distinction from motion control: `isStopped()` (value retrieval) reflects this kind of scheduled/voluntary stop, not a vehicle merely halted in traffic — `getWaitingTime()` explicitly excludes voluntary stopping, so the two states are complementary rather than overlapping.

## Safety-check overrides

- `setSpeedMode(vehID, bitset)`: enables/disables individual speed-related safety checks (each bit toggles one check — e.g. running a red light, ignoring right-of-way, exceeding the speed limit). SUMO's own default enables all checks.
- `setLaneChangeMode(vehID, bitset)`: controls whether/how the vehicle changes lanes autonomously versus only under explicit TraCI commands, and whether autonomous changes still respect collision/gap safety.

These overrides exist for controlled/CAV research scenarios — deliberately disabling safety checks can cause collisions in the simulation and shouldn't be applied broadly or by default. A well-designed closed-loop speed-advisory controller (e.g. GLOSA, see [[glosa-eco-driving]]) typically does NOT need to disable any check: leaving the default speed mode (all checks on) still lets `setSpeed` raise or lower the *target* speed freely, while real safety constraints (safe following, red-light braking) continue to cap the *realized* speed — verify this is sufficient before reaching for an override.

## Other state

- `setColor(vehID, (r, g, b, a))`: visual only, useful for highlighting specific vehicles in `sumo-gui`.
- `setType(vehID, typeID)`, `setSpeedFactor(vehID, factor)`: reassign vehicle type / adjust individual speed variability.

Every setter here requires the vehicle to have already departed; calling one on an id not yet in the simulation (or already arrived) raises an error rather than queuing the change for later.
