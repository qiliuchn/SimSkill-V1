---
name: implement-maxpressure-traci-controller
description: Use this skill when the user wants a CUSTOM traffic-signal control algorithm applied live during a SUMO simulation via TraCI — as opposed to a static offline plan, SUMO's own native actuated/delay_based logic, or a library-wrapped RL agent. Covers the max-pressure algorithm specifically (a well-defined, classical adaptive signal-control rule) and the general closed-loop TraCI control-loop pattern it's built on: mapping tlLogic phases to their controlled lane movements via getControlledLinks, enforcing minimum green time, and inserting correct yellow/clearance transitions before any phase switch. Trigger on mentions of max-pressure control, custom/hand-written adaptive signal control, writing your own TraCI signal controller, or phase-to-movement mapping for traffic lights.
---

# Implement a Max-Pressure TraCI Controller

Implements a genuinely **custom, closed-loop** traffic-signal control algorithm driven live through TraCI — a fundamentally different implementation path from every other signal-control skill in memory: `optimize-signals-by-tlscycleadaptation`/`optimize-signals-by-tlscoordinator` compute a static plan once offline, `control-signals-with-actuated-tls` uses SUMO's own built-in detector-reactive logic, and `optimize-signals-by-qlearning` wraps an RL agent via the `sumo-rl` library. This skill is for when the task genuinely calls for writing your own control law in Python and applying it step-by-step — max-pressure specifically, or any other hand-written control algorithm following the same pattern.

## The general pattern (reusable beyond max-pressure)

Any custom signal-control algorithm applied live via TraCI needs the same three pieces, regardless of what decision rule actually picks the next phase:

1. **Phase-to-movement mapping** — derive which lane-to-lane movements each green phase serves from `traci.trafficlight.getControlledLinks(tls_id)` (index-aligned with the `tlLogic`'s RYG state string: character `i` of a phase's `state` corresponds to `links[i]`, each a `(incoming_lane, outgoing_lane, via_lane)` tuple). **Never hand-guess this mapping per network** — it must be derived programmatically so the same controller code works on any signalized junction's actual phase layout.
2. **Minimum green enforcement** — track a per-junction "green since" timestamp and refuse to switch away from the current green phase until `min_green` seconds have elapsed, regardless of what the decision rule wants.
3. **Correct yellow AND all-red clearance transition** — never jump directly from one green phase to another, and never jump directly from yellow to the next green either. Locate the clearance yellow phase that already exists in the network's own `tlLogic` program (the phase immediately following the current green that turns its green characters to `y`), hold it for its programmed duration, **then locate and hold any all-red phase that follows the yellow before switching to the target green** — do not assume the yellow alone is sufficient clearance. Suppress SUMO's own phase auto-advance (e.g. `setPhaseDuration` to a large "hold" value) so external timing fully controls transitions instead of fighting SUMO's own phase clock. **A fixed-duration (timed) all-red is itself not always sufficient**: on a program with a permissive left turn, a vehicle already committed to the internal junction from standstill can need several seconds to clear a long internal path — longer than a short programmed all-red. Verify clearance by checking that the junction's internal lanes are actually **physically empty** (via `traci.lane.getLastStepVehicleNumber` on the relevant internal lane IDs), not by trusting a fixed timer, whenever the program includes permissive turns with `cont="true"` internal-junction links.

`scripts/maxpressure_controller.py` implements all three pieces generically (works on any network's junctions via introspection, not hardcoded per topology) plus the max-pressure decision rule on top — reuse its `JunctionController` class structure for a different custom algorithm by swapping out `_pressure()` for a different scoring function, rather than rebuilding the phase-mapping/min-green/yellow-transition machinery from scratch.

## Max-pressure specifically

See [[max-pressure-signal-control]] for the algorithm's background and its `pressure(phase) = queue(incoming) - queue(outgoing)` formula. Key implementation choices, documented so they can be revisited rather than silently assumed:

- **Queue length (halting vehicle count via `traci.lane.getLastStepHaltingNumber`), not raw vehicle count, on both sides of the subtraction** — keeps units consistent and matches the classical Varaiya formulation. The downstream (outgoing) term is what makes the controller spillback-aware: it discounts serving a movement whose receiving lane is already backed up.
- **`decision_interval`** (default 5 s) — how often pressures are recomputed and a switch decision is (re-)made, independent of `min_green`.
- **Ties keep the current phase** — a still-busy phase isn't needlessly dropped for an equally-pressured alternative; only strictly higher pressure triggers a switch.

## Usage

```bash
python scripts/maxpressure_controller.py \
    --net net.net.xml --routes routes.rou.xml \
    --tripinfo tripinfo.xml --summary summary.xml \
    --min-green 10 --decision-interval 5
```

Runs the full simulation itself (starts `traci`, steps until `traci.simulation.getMinExpectedNumber() == 0`, writes `tripinfo`/`summary` via the normal SUMO output flags) — there's no separate command-line run needed for this scenario; the controller *is* the run.

## Evaluating against baselines

To fairly compare a custom controller against a fixed-time plan and/or SUMO's native actuated control (see `control-signals-with-actuated-tls`), keep the network topology and demand **identical** across all three runs — only the signal-control mechanism should differ:
1. One `.net.xml` with the default static `tlLogic` — used both for the fixed-time baseline (plain `run-simulation` command-line run) and for this skill's controller (which overrides the same static program's phase timing externally).
2. A second `.net.xml` differing only in `--tls.default-type actuated` (or `delay_based`) for the native-actuated baseline.
3. One fixed, pre-routed demand file reused unchanged across all three runs.

Then compare with `analyze-simulation-outputs` (or a custom comparison script following `control-signals-with-actuated-tls`'s `scripts/compare_tls_controllers.py` pattern for a controller × demand-level grid).

## What to expect

A correctly-implemented max-pressure controller reliably beats a static fixed-time plan by a wide margin (mirroring the general actuated-vs-fixed-time finding in [[actuated-traffic-signals]]), but **does not automatically beat SUMO's native actuated/delay_based control** — in one verified comparison, max-pressure lost to native actuated at moderate demand, with the gap narrowing (not necessarily closing) as demand rose toward saturation. This is consistent with max-pressure's classical strength being an *oversaturation* property: its queue-based, spillback-aware pressure rule is designed to prevent gridlock and maximize throughput specifically when a network is under heavy, imbalanced load, not necessarily to minimize average delay at moderate load where a well-tuned detector-reactive controller can do just as well or better. Don't treat "max-pressure lost to actuated at this demand level" as an implementation bug — verify the phase-mapping/min-green/yellow-transition logic first, and if those are genuinely correct, report the result honestly as a condition-dependent finding.

## Gotchas

- **A phase-switching implementation that inserts the clearance yellow but skips a following all-red phase can produce genuine simulated collisions, not just aggressive-but-safe timing** — verified directly: an otherwise-correct max-pressure controller that jumped straight from yellow to the next green produced a real junction collision on a 2-phase permissive-left program. Always check whether the network's own `tlLogic` program has an all-red phase after the yellow, and if so, hold it too.
- **A short, fixed-duration all-red is not automatically sufficient on a permissive-left program** — a vehicle already committed to the internal junction from standstill can need several seconds to clear a long internal path, longer than a typical 1-2s programmed all-red. Verify the internal lanes are physically empty before switching to the next green rather than trusting the programmed duration; this is the same "clear on occupancy, not on a timer" lesson `implement-reservation-based-autonomous-intersection-management` independently re-derived for a completely different (signal-free, reservation-based) controller architecture.

## Related

- `create-grid-network`, `generate-random-trips`, `convert-trips-to-routes` — build the shared network/demand.
- `get-vehicles-state` — the general read-side TraCI helpers (`get_queue_length` uses the same halting-vehicle-count definition as this skill's pressure calculation).
- `control-signals-with-actuated-tls` — the native-actuated baseline to compare against, and the source of the "actuated beats fixed-time, benefit narrows with load" finding this skill's results should be read alongside.
- `run-simulation` — general command-line-vs-TraCI background; this skill's controller *is* a TraCI step-loop, following that skill's "Option 2" pattern.
- [[max-pressure-signal-control]] — the algorithm's theoretical background and the verified beats-fixed-time/loses-to-actuated-at-moderate-load finding.
- `implement-mfd-based-perimeter-gating` — reuses this skill's phase-to-movement mapping (`getControlledLinks`) and yellow-transition discipline, applied to network-level green-time throttling at a region's perimeter rather than per-junction phase selection.
- `implement-reservation-based-autonomous-intersection-management` — a genuinely different, signal-free control paradigm at the same junction-control layer; found and fixed a real collision defect in this skill's own controller (missing all-red clearance) while building a baseline comparison, and independently arrived at the same "clear on occupancy, not on a timer" principle from its own reservation-scheduling bug.
