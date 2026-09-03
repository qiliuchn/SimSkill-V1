---
name: implement-glosa-speed-advisory-controller
description: Use this skill when the user wants a GLOSA (Green Light Optimal Speed Advisory) or general eco-driving speed-advisory controller in SUMO — a closed-loop TraCI controller that advises/commands individual vehicles' speed based on upcoming traffic-signal timing, to reduce stops and smooth traffic, as opposed to controlling the signals themselves. Covers deriving upcoming green windows from getNextTLS/getAllProgramLogics/getNextSwitch, the catch-green-or-glide decision rule, and applying advisory speed safely via setSpeed under SUMO's default speed mode. Trigger on mentions of GLOSA, green light optimal speed advisory, eco-driving, speed advisory, or "smooth vehicle speed approaching a signal."
---

# Implement a GLOSA Speed-Advisory Controller

Implements a genuinely custom, closed-loop TraCI controller that advises **vehicles'** speed (not signals') based on live upcoming traffic-light timing — the vehicle-side counterpart to `implement-maxpressure-traci-controller`'s signal-side closed-loop pattern. Where max-pressure reads queues and commands a signal, GLOSA reads a signal's phase program and commands a vehicle's speed so it either catches a green light or glides smoothly to a stop rather than braking hard.

## The reusable pattern

Three pieces, all handled generically in `scripts/glosa_controller.py` (works on any signalized network via TraCI introspection, not hardcoded per corridor):

1. **Find the next signal and its distance**: `traci.vehicle.getNextTLS(veh_id)` returns `[(tlsID, linkIndex, distance, currentState), ...]` for upcoming traffic lights on the vehicle's route — take the first (nearest) entry. `linkIndex` is the vehicle's own position within that TLS's RYG state string, needed for the next step.
2. **Derive when it next turns green** (`getNextTLS`/`getNextSwitch` alone don't tell you this): `traci.trafficlight.getNextSwitch(tls)` gives when the *current* phase ends; `traci.trafficlight.getAllProgramLogics(tls)[0].phases` gives every phase's `state` string and `duration`. Walk the phase list forward ~2 cycles from the current phase, reading `state[link_idx]` of each phase to build the vehicle's actual upcoming green/not-green windows for its specific movement.
3. **One decision rule for both "speed up" and "glide down"**: search the green windows in arrival order; a window `[gs, ge]` is *catchable* if some constant speed in `[v_min, v_max]` lands the vehicle inside it (i.e. the reachable-arrival interval `[now + dist/v_max, now + dist/v_min]` overlaps `[gs, ge]`). For the earliest catchable window, target the earliest arrival at or after `gs` and derive the constant speed needed — this single rule naturally produces a **higher** speed (up to the cap) when the current green is about to end and is still just catchable, and a **lower glide** speed when the light is red and only the *next* green is catchable. If nothing is catchable, fall back to a comfortable glide-to-stop: `v = sqrt(2 · a_comf · max(distance − stop_buffer, 0))`, capped by the vehicle's current speed — a smooth deceleration profile, not a hard brake.

## Applying the advice safely

```python
traci.vehicle.setSpeedMode(veh, 31)   # SUMO's default: ALL safety checks on
traci.vehicle.setSpeed(veh, target)
```

**Leave the speed mode at SUMO's default (bitset 31, every check enabled) rather than disabling anything.** With safe-following and red-light-braking checks on, the commanded speed is still capped by car-following safety and red-light compliance — the advisory can only ever lower the *realized* speed below the target, or raise the *target* up to the speed limit, never force a collision or a red-light run. Verify this is sufficient (as opposed to needing an override) before reaching for `setSpeedMode` overrides — [[change-vehicle-state]] warns overrides "shouldn't be applied broadly," and a correctly-designed GLOSA controller shouldn't need one.

**Release control** with `traci.vehicle.setSpeed(veh, -1)` once the vehicle: has no TLS ahead on its route, has a nearest TLS beyond the advisory horizon (e.g. 200-300m), or is within a small clearing distance of the stop line (e.g. 5m) — letting normal car-following resume rather than holding an advisory speed indefinitely.

## Running a baseline-vs-GLOSA comparison

```bash
# Baseline: penetration 0.0 runs the identical stepping loop with no vehicle ever equipped
python scripts/glosa_controller.py --net corridor.net.xml --routes demand.rou.xml \
    --outdir runs/baseline --penetration 0.0

# Full GLOSA
python scripts/glosa_controller.py --net corridor.net.xml --routes demand.rou.xml \
    --outdir runs/glosa --penetration 1.0

# Partial penetration
python scripts/glosa_controller.py --net corridor.net.xml --routes demand.rou.xml \
    --outdir runs/glosa50 --penetration 0.5
```

Using `--penetration 0.0` for the baseline (rather than a separate non-TraCI command-line run) keeps the *exact* same stepping loop and per-vehicle bookkeeping code path across all scenarios — the only thing that changes is which vehicles get advised. Each run writes `tripinfo.xml` (with `<emissions>` children if `--device.emissions.probability` is set, matching `simulate-fleet-emissions`'s pattern), `summary.xml`, per-edge emissions/traffic `edgeData`, per-vehicle `trajectories.csv` for any ids listed in `--track-file` (useful for the classic "speed vs. distance, GLOSA glide replacing the baseline stop-and-go sawtooth" plot), and `run_stats.json` (network-wide speed variance and hard-deceleration count — the smoothness proxies).

**Don't also load a separate vType additional-file when running these scenarios** — if the route file was produced by `duarouter`, it already embedded the full vType (with all its parameters) into the routes; loading the original vType file again raises a duplicate-vType-id error.

## What to expect — a real, non-obvious trade-off

A correctly-implemented GLOSA controller reliably cuts stops, waiting time, hard-braking events, and speed variance (verified: -22%/-16%/-14%/-24% respectively in one comparison) — exactly what GLOSA is designed for. **It does not automatically reduce emissions or travel time**, and can measurably increase both: on a corridor whose signals are *not* coordinated into a green wave, most reds simply aren't catchable at any reasonable speed, so the controller spends most of its time gliding vehicles into a sustained low-speed approach rather than speeding up to catch greens. HBEFA3's speed-emission relationship (see [[vehicle-emissions-modeling]]) means sustained low-speed cruising can emit *more* per km than the stop-start bursts it replaces, and the extra time spent gliding also adds to total time-in-network — both compounding into a net emissions/duration increase even as per-stop and per-braking-event metrics improve. See [[glosa-eco-driving]] for the full verified finding. Don't treat "GLOSA increased CO2 in this scenario" as evidence of a bug — check whether the corridor's signals are coordinated (a green wave should let speed-up-to-catch dominate over glide-to-near-stop, changing the emissions direction) before assuming something's wrong.

## Related

- `implement-maxpressure-traci-controller` — the signal-side analogue of this closed-loop pattern (read queues → command signal, vs. here: read signal → command vehicle); its `JunctionController`-style phase introspection (via `getAllProgramLogics`) is the same technique this skill's `_green_windows` uses, applied to a different purpose.
- `create-grid-network` — build an arterial corridor via an asymmetric `--grid.x-number`/`--grid.y-number` (e.g. 5x1) rather than a square grid.
- `simulate-fleet-emissions` — the emissions-device attachment pattern (`emissionClass`, `--device.emissions.probability`) this skill's demand reuses to make CO2/fuel measurable.
- `get-vehicles-state` / `set-vehicle-state` — the general TraCI read/write vehicle-state primitives (`setSpeed`, speed mode) this controller is built on.
- [[glosa-eco-driving]] — the underlying concepts (API used, decision logic, speed-mode safety reasoning) and the verified stops-vs-emissions-vs-travel-time trade-off.
