---
name: set-vehicle-state
description: Use this skill when the user wants to change the state of a single vehicle in a running SUMO/TraCI simulation — speed, forced lane, route/destination, a scheduled stop, color, or safety-check overrides (speed mode, lane change mode). This is the write side of TraCI (as opposed to get-vehicles-state's read/query focus). Trigger on mentions of controlling a vehicle, forcing a lane change, stopping a vehicle, rerouting a vehicle, setSpeed/setStop/changeLane/changeTarget, overriding right-of-way or red-light behavior, or CAV/controlled-vehicle experiments.
---

# Set Vehicle State

Changes the state of a single vehicle in a running TraCI connection — the write-side counterpart to `get-vehicles-state`'s reads. Two ways to use it:

1. **Import `vehicle_control.set_vehicle_state()`** (and the convenience wrappers) into a step loop — the normal case for a control policy, an RL environment's action step, or a scripted scenario.
2. **Run `scripts/control_vehicle.py`** standalone for quick one-off testing without writing a loop by hand.

## Using it inside a step loop (the common case)

```python
import traci
from vehicle_control import set_vehicle_state, stop_vehicle, resume_vehicle, SPEED_MODE_PRESETS

traci.start(["sumo", "-c", "config.sumocfg"])
while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()

    # Multiple changes in one call
    set_vehicle_state(traci, "veh0", speed=10.0, color=(255, 0, 0, 255))

    # Force a lane change, held for 5 seconds
    set_vehicle_state(traci, "veh0", lane_index=1, lane_change_duration=5.0)

    # Reroute to a new destination edge (route is rebuilt automatically)
    set_vehicle_state(traci, "veh0", target_edge="E9")

    # Schedule a stop
    stop_vehicle(traci, "veh0", edge_id="E1", pos=50.0, duration=30.0)
    # ...later...
    resume_vehicle(traci, "veh0")

    # Override safety checks for a controlled-vehicle experiment (see Gotchas)
    set_vehicle_state(traci, "veh0", speed=10.0, speed_mode=SPEED_MODE_PRESETS["run_red_light"])

traci.close()
```

Works with both `traci` and `libsumo` — pass whichever module is already connected as the first argument; the helpers only call methods on it, they don't import or connect it themselves.

## Function reference (`vehicle_control.py`)

**`set_vehicle_state(traci, veh_id, **kwargs)`** — the main entry point. Only the kwargs given are applied; everything else is left alone. Returns a dict summarizing what was applied.

| Kwarg | Effect |
| --- | --- |
| `speed` | m/s; `-1` releases speed control back to normal car-following (see `release_speed_control`) |
| `max_speed` | changes the vehicle's speed ceiling (otherwise inherited from its vType) |
| `lane_index` (+ `lane_change_duration`, default 5s) | forces a lane change, held for the given duration |
| `route_edges` | full replacement route as a list of edge ids (first edge must be the one the vehicle is currently on) |
| `route_id` | assign a pre-existing route by id (same current-edge constraint) |
| `target_edge` | change only the destination; route to it is rebuilt automatically |
| `color` | `(r, g, b, a)`, each 0-255 |
| `speed_mode` | raw bitset int overriding safety-check behavior — see Gotchas |
| `lane_change_mode` | raw bitset int overriding autonomous lane-changing behavior |
| `resume` | `True` to resume from a stop |

**Convenience wrappers**, each a thin call to one TraCI method:
- `stop_vehicle(traci, veh_id, edge_id, pos, duration=..., lane_index=0, flags=0, start_pos=-1, until=-1)` — schedule a stop; re-issuing at the same edge/position changes its duration, `duration=0` cancels it
- `resume_vehicle(traci, veh_id)`
- `force_lane_change(traci, veh_id, lane_index, duration=1000.0)`
- `reroute_to_edge(traci, veh_id, edge_id)`
- `release_speed_control(traci, veh_id)` — equivalent to `set_vehicle_state(traci, veh_id, speed=-1)`

**`SPEED_MODE_PRESETS`** and **`LANE_CHANGE_MODE_PRESETS`** — named bitsets for common cases (see table below), so callers don't need to hand-compute the raw integers.

## Standalone CLI (`control_vehicle.py`)

```bash
# Set speed
python scripts/control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --speed 5

# Force a lane change
python scripts/control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --lane-index 1 --lane-change-duration 5

# Stop at an edge/position
python scripts/control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --stop-edge E1 --stop-pos 50 --stop-duration 30

# Reroute to a new destination
python scripts/control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --target-edge E9

# Apply a named speed-mode preset
python scripts/control_vehicle.py --config sim.sumocfg --step-to 100 --vehicle-id veh0 --speed-mode-preset run_red_light --speed 10

# Attach to an already-running SUMO started with --remote-port
python scripts/control_vehicle.py --port 8813 --vehicle-id veh0 --speed 0

# Preview the parsed action without connecting to anything
python scripts/control_vehicle.py --vehicle-id veh0 --speed 5 --dry-run
```

CLI flags mirror the Python kwargs above, plus `--stop-*` flags for scheduling a stop and `--step-to`/`--hold-steps` to control when the change is applied and how long to keep stepping afterward to observe the effect (prints the vehicle's resulting speed/edge/lane at the end).

## Speed-mode / lane-change-mode presets

| Speed mode preset | Bitset | Effect |
| --- | --- | --- |
| `default` | 31 | all safety checks on (SUMO's own default) |
| `legacy` | 0 | all speed-related safety checks off |
| `aggressive_no_safety` | 96 | ignore right-of-way within intersections + ignore speed limit |
| `ignore_row_within_intersection` | 55 | disregard right-of-way for vehicles already inside an intersection |
| `run_red_light` | 7 | allows running a red light (still needs `speed`/`slowDown` to actually move through it) |
| `run_red_light_ignore_occupied` | 39 | as above, even if the intersection already has traffic in it |

| Lane-change mode preset | Bitset | Effect |
| --- | --- | --- |
| `default` | 1621 | autonomous changes allowed unless conflicting with a TraCI request |
| `collision_avoidance_only` | 256 | no autonomous changing, but safety checks still apply |
| `collision_and_gap_safety_only` | 512 | as above, plus safety-gap enforcement |
| `no_safety_checks` | 0 | disable all autonomous changing AND safety checks |

## Gotchas

- **A vehicle must have already departed to be controllable.** Most setters raise if `veh_id` isn't currently in `traci.vehicle.getIDList()` — a trip scheduled to depart later in the simulation can't be set yet. Both the module and CLI don't hide this; check membership or catch the error if applying to a vehicle whose departure time is uncertain.
- **`setRoute`/`setRouteID`/`changeTarget` require the vehicle to be outside an intersection** and the new route to still include the vehicle's current edge — changing the route mid-intersection or to a route that's already been passed will fail.
- **Speed-mode overrides are for controlled/CAV experiments, not everyday use.** Disabling safety checks (`run_red_light`, `aggressive_no_safety`, `no_safety_checks`) can cause collisions in the simulation — legitimate for testing a specific controlled vehicle's behavior against surrounding traffic, but don't apply these presets broadly or by default.
- **`speed=-1` is the "give control back" value**, not "stop" — to actually stop a vehicle, use `stop_vehicle`, not `set_vehicle_state(..., speed=0)` (setting speed to exactly 0 forces the vehicle to a halt under whatever speed mode is active, but doesn't register as a scheduled stop the way `isStopped()`/`stop_vehicle` does — see `get-vehicles-state`'s gotchas on that distinction).
- **`lane_index` is an absolute lane index on the current edge**, not relative — the target lane must physically exist on the vehicle's current edge or the change silently fails to find a valid target.
- **This skill only writes vehicle state.** For reading it back, see `get-vehicles-state`. For traffic light control, see `run-simulation`'s TraCI cheat-sheet.
