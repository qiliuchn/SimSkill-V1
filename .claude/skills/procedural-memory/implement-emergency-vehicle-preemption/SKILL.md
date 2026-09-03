---
name: implement-emergency-vehicle-preemption
description: Use this skill when the user wants FULL emergency-vehicle signal preemption in SUMO — a TraCI controller that forces an immediate phase change (with a genuine all-red clearance interval) to serve an approaching emergency vehicle, holds the grant until the vehicle physically clears the junction, then recovers to normal operation — as opposed to transit-signal-priority (implement-transit-signal-priority), which only extends or truncates the CURRENT phase's duration and never jumps phase index. Also covers SUMO's device.bluelight rescue-lane mechanism, where surrounding traffic yields laterally and forms a corridor for the emergency vehicle, and a three-configuration design (baseline / bluelight-only / bluelight+preemption) for cleanly isolating the two effects. Trigger on mentions of emergency vehicle preemption, EVP, signal preemption, device.bluelight, rescue lane, or Rettungsgasse.
---

# Implement Emergency-Vehicle Preemption

Full emergency-vehicle signal preemption forces an immediate, safety-correct phase change to serve an approaching emergency vehicle — categorically different from `implement-transit-signal-priority`'s bounded courtesy priority, which only perturbs the currently-active phase's duration and never strands a conflicting movement mid-green.

## Full preemption vs. transit signal priority

| | Transit Signal Priority | Full Preemption |
|---|---|---|
| Mechanism | Extends/truncates the *current* phase's duration | Forces an immediate transition to the target movement, regardless of current phase |
| Safety | Native program handles all sequencing/yellow/clearance | Controller must manufacture its own yellow→all-red clearance before granting green |
| Grant duration | Bounded by minimum green / per-cycle limits | Held until the vehicle physically clears the junction |
| Recovery | Automatic offset-recovery within the native cycle | Explicit `setProgram` back to the native plan |

## Per-signal preemption FSM

```
NORMAL -> YELLOW -> ALLRED -> EVGREEN -> RECOVER -> NORMAL
```

Implement with `traci.trafficlight.setRedYellowGreenState` overrides (not phase-duration adjustment) so every clearance state string is directly loggable and auditable:

1. **NORMAL**: watch for an approaching emergency vehicle within a detection range via `traci.vehicle.getNextTLS`. **If the vehicle's target movement is already green** (conflicts already red), skip clearance entirely and go straight to EVGREEN — don't blindly insert a clearance interval every time.
2. **YELLOW**: any movement currently green that conflicts with the target movement gets `y`; everything else (including the target movement itself) is held `r`.
3. **ALLRED**: after the yellow duration, force every link to `r` — a genuine all-red clearance interval, held for a fixed safety duration.
4. **EVGREEN**: grant the target movement `G`/`g`, hold **until the vehicle is verified to have physically cleared the junction** — check via `tls_id not in [e[0] for e in traci.vehicle.getNextTLS(vehicle_id)]`, not a fixed timer.
5. **RECOVER**: `traci.trafficlight.setProgram(tls, native_program_id)` to resume normal operation.

See `scripts/preemption_controller.py` for the full working implementation, including the yellow-transition logic that only clears movements that are actually green and conflict with the target.

## `device.bluelight`: the rescue-lane mechanism

Equip the emergency vehicle's vType with `<param key="has.bluelight.device" value="true"/>` and enable the sublane model (`--lateral-resolution`) so surrounding vehicles can physically shift laterally to form a rescue lane. Control the effect's range with `--device.bluelight.reactiondist`.

## Isolating bluelight's effect from preemption's effect: a three-configuration design

Run identical background demand and seed across three configurations, varying only the emergency vehicle's equipment and whether the preemption controller is active:
- **(a) baseline**: plain emergency vType, no bluelight, no preemption — the vehicle obeys signals normally.
- **(b) bluelight-only**: bluelight-equipped vType, but signals run their native program — isolates the rescue-lane effect alone.
- **(c) bluelight + preemption**: both mechanisms active — isolates preemption's additional effect on top of (b).

This cleanly decomposes the emergency vehicle's total benefit into a rescue-lane component (b vs. a) and a signal-control component (c vs. b), rather than conflating the two.

## Verifying the all-red clearance genuinely occurred

Don't just assert clearance happened — log every FSM transition (timestamp, event, the actual state string) to a JSON file and read it back: a genuine all-red interval should show zero `G`/`g` characters in the logged state string, held for the intended duration, between the pre-existing state and the eventual EV-green state (except at intersections where the target movement was already green, where clearance is correctly skipped).

## Verifying the rescue-lane effect from FCD

Compare the lateral gap and speed of the vehicle immediately ahead of the emergency vehicle across configurations, computed from FCD output (`--fcd-output.attributes id,x,y,speed,lane,type` with `--lateral-resolution` enabled) — a genuine rescue-lane effect shows a substantially larger lateral offset from the emergency vehicle's path and a speed reduction (pulling aside) specifically in the bluelight-equipped configurations, not present in the baseline.

## Verified findings

On a real 4-signal arterial: preemption reduced emergency-vehicle corridor travel time (144s baseline → 104s bluelight-only → 96s bluelight+preemption) and eliminated its final stop, decomposing to roughly 40 seconds of rescue-lane benefit and a further ~8 seconds plus one fewer stop from preemption specifically. Every preemption event showed a genuine all-red clearance in the raw log except where correctly skipped for an already-green target movement. This came at a real, bounded cross-street cost (~183 additional vehicle-seconds of waiting, ~232 of time loss across the conflicting approaches) for the emergency vehicle's benefit — a legitimate, quantifiable tradeoff, not a free lunch.

## Gotchas

- **Don't reuse TSP's perturb-current-phase logic for full preemption** — it cannot safely handle forcing a phase change from an arbitrary current state; you need genuine forced-state overrides with manufactured clearance.
- **Skip clearance when the target movement is already green** — don't insert an unnecessary all-red interval every time; check the current state first.
- **Hold the EV-green grant based on verified vehicle position, not a fixed timer** — a fixed timer risks releasing the grant before the vehicle has actually cleared, or holding it needlessly long.
- **Log every FSM transition with its actual state string** — this is the only way to verify clearance genuinely occurred rather than asserting it.
- **Isolate bluelight from preemption via a three-configuration design** — conflating both mechanisms in a single before/after comparison obscures which effect is actually responsible for the benefit.

## Related

- `implement-transit-signal-priority` — the bounded, current-phase-only courtesy priority mechanism this skill's full preemption is explicitly contrasted with.
- `control-signals-with-actuated-tls` — general tlLogic authoring and phase/clearance conventions background.
- `analyze-simulation-outputs` — general tripinfo/edgeData comparison methodology used for the cross-street cost measurement.
- [[emergency-vehicle-preemption-and-bluelight]] — the underlying device.bluelight mechanics and the verified travel-time/clearance/cost findings.
