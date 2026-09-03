---
name: get-vehicles-state
description: Use this skill when the user wants to read the current state of vehicles in a running SUMO/TraCI simulation — positions, speeds, which lane/edge they're on, whether they're stopped, waiting time — optionally filtered by lane, edge, stopped status, vehicle id, type, speed range, or route. This is the read side of TraCI (as opposed to run-simulation's general step-loop/control focus). Trigger on mentions of vehicle state, queue length, stopped vehicles, vehicles on a lane/edge, traci.vehicle queries, or building a state representation for signal-control/RL work.
---

# Get Vehicles' State

Reads and filters vehicle state from a running TraCI connection — the query side of the `run-simulation` skill's step loop. Two ways to use it:

1. **Import `vehicle_state.get_vehicles_state()`** into a step loop (RL environment, control algorithm, logger) — this is the normal case, since vehicle state is almost always read every simulation step, not once.
2. **Run `scripts/query_vehicles.py`** standalone for quick one-off inspection or debugging, without writing a loop by hand.

## Using it inside a step loop (the common case)

```python
import traci
from vehicle_state import get_vehicles_state, get_queue_length

traci.start(["sumo", "-c", "config.sumocfg"])
while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()

    # All vehicles currently stopped on a specific lane (e.g. a signal approach)
    queued = get_vehicles_state(traci, lane_id="in_N_0", stopped=True)

    # All vehicles moving faster than 10 m/s anywhere in the network
    fast = get_vehicles_state(traci, min_speed=10.0)

    # A specific set of vehicles, e.g. for per-agent RL observations
    tracked = get_vehicles_state(traci, ids=["veh0", "veh3", "veh7"])

    # Queue length proxy (vehicle count under a speed threshold) for signal-timing state
    n_queued = get_queue_length(traci, lane_id="in_N_0")

traci.close()
```

Works with both `traci` and `libsumo` — pass whichever module is already connected as the first argument; the helpers only call methods on it, they don't import or connect it themselves.

## Filter reference (`get_vehicles_state`)

All filters are AND-combined; omit any that shouldn't apply.

| Filter | Meaning |
| --- | --- |
| `ids` | restrict to this specific collection of vehicle ids (silently skips any not currently in the network) |
| `lane_id` | exact lane id (e.g. `"in_N_0"`) |
| `lane_ids` | any lane id in this collection |
| `edge_id` | exact edge id (e.g. `"in_N"`) |
| `edge_ids` | any edge id in this collection |
| `stopped` | `True` for only stopped vehicles, `False` for only moving ones |
| `vtype` | exact vehicle type id |
| `min_speed` / `max_speed` | inclusive speed bounds, m/s |
| `route_id` | exact route id |

Each result is a dict with: `id`, `type`, `edge_id`, `lane_id`, `lane_index`, `lane_position`, `position` (x, y), `speed`, `acceleration`, `angle`, `route_id`, `is_stopped`, `waiting_time`, `accumulated_waiting_time`, `distance`, `next_tls` (upcoming traffic lights on the route: `[(tlsID, tlsIndex, distance, state), ...]`).

`get_queue_length(traci, lane_id, speed_threshold=0.1)` is a convenience wrapper — counts vehicles on a lane below the speed threshold, a common queue-length proxy for signal-timing state representations (RL observations, actuated control logic, etc.).

## Standalone CLI (`query_vehicles.py`)

For quick inspection without writing a script:

```bash
# Start a new simulation from a config, step to t=300, show all vehicles
python scripts/query_vehicles.py --config sim.sumocfg --step-to 300

# Only vehicles stopped on a specific lane
python scripts/query_vehicles.py --config sim.sumocfg --step-to 300 --lane-id in_N_0 --stopped

# Only moving vehicles above 5 m/s
python scripts/query_vehicles.py --config sim.sumocfg --step-to 300 --min-speed 5 --moving

# Specific vehicle ids
python scripts/query_vehicles.py --config sim.sumocfg --step-to 300 --vehicle-ids veh0,veh3,veh7

# Attach to an already-running SUMO started with --remote-port
python scripts/query_vehicles.py --port 8813 --step-to 300

# Repeated snapshots every 50 steps until the simulation ends
python scripts/query_vehicles.py --config sim.sumocfg --watch --interval 50

# JSON output for piping into other tools
python scripts/query_vehicles.py --config sim.sumocfg --step-to 300 --format json
```

CLI filter flags mirror the Python filters above (`--lane-id`, `--lane-ids`, `--edge-id`, `--edge-ids`, `--stopped`/`--moving`, `--vtype`, `--min-speed`, `--max-speed`, `--route-id`, `--vehicle-ids`). Connection can either start a new sim from `--config` (optionally `--gui`/`--libsumo`, following the same conventions as `run-simulation`) or attach to one already running via `--port`.

## Gotchas

- **A vehicle only exists between departure and arrival.** Both the module and CLI silently skip ids that aren't currently in `getIDList()` rather than raising — expected if you're tracking a fixed set of ids across steps and some haven't departed yet or have already arrived.
- **`waiting_time` vs `accumulated_waiting_time`**: `waiting_time` is consecutive standing time and, per the TraCI spec, explicitly *excludes* voluntary/scheduled stopping — so it's really measuring involuntary halting (traffic, red lights), not parking. `accumulated_waiting_time` sums standing time over a configurable trailing window (`--waiting-time-memory` in `sumo`, default 100s) and survives brief movement. For queue/delay metrics, `accumulated_waiting_time` is usually the more meaningful one.
- **`is_stopped` means a scheduled/intentional stop** (parking, a bus/container stop, a triggered stop from a `<stop>` in the route) — it's a different signal from `waiting_time`, which is about involuntary halting. A vehicle halted at a red light is *not* `is_stopped=True`, it's just moving at ~0 speed. Use `max_speed` (e.g. `max_speed=0.1`) rather than `stopped=True` to detect queued/halted-in-traffic vehicles; `get_queue_length` already does this correctly.
- **Filtering happens in Python after `getIDList()`**, not via a single lower-level TraCI call — fine for typical network sizes, but for very large networks queried every step, consider narrowing with `ids`/`lane_id`/`edge_id` rather than pulling and filtering every vehicle in the simulation each time.
- **This skill only reads state.** For writing/controlling vehicles (`setSpeed`, `changeLane`, etc.) or traffic lights, see `run-simulation`'s TraCI API cheat-sheet.
