---
name: implement-transit-signal-priority
description: Use this skill when the user wants to implement Transit Signal Priority (TSP) in SUMO — a TraCI controller that grants an approaching bus (or other priority vClass) green extension or early green (red truncation) at a fixed-time signal, with or without conditions limiting the impact on cross-street traffic. Covers detecting an approaching bus via getNextTLS, deriving its target phase from link indices, perturbing only the current phase's duration (never jumping phase index), the mandatory offset-recovery mechanism, and comparing unconditional/aggressive priority against conditional priority bounded by minimum-green and a per-cycle grant limit. Trigger on mentions of transit signal priority, TSP, bus priority, signal preemption, green extension, or red truncation.
---

# Implement Transit Signal Priority

Grants a priority vehicle class (typically buses) favorable treatment at a fixed-time signal — **green extension** (holding an active green a bit longer so an approaching bus clears) or **early green via red truncation** (shortening a conflicting green so the bus's phase arrives sooner) — via a TraCI controller layered on top of SUMO's native static `tlLogic` program. This is SimSkill's transit-priority counterpart to its other TraCI signal controllers (`implement-maxpressure-traci-controller`, `implement-glosa-speed-advisory-controller`): same `getControlledLinks`/phase-introspection discipline, but reacting to one specific vClass rather than aggregate queue pressure.

## Detecting an approaching bus and its target phase

```python
nxt = traci.vehicle.getNextTLS(bus_id)   # [(tlsID, linkIdx, dist, state), ...]
tls_id, link_idx, dist, _ = nxt[0]       # nearest upcoming signal
```

The bus's `link_idx` within that signal's RYG state string tells you exactly which phase serves its movement — find it by scanning the signal's green phases for the one whose state character at `link_idx` is `G`/`g`. This is the same link-index-driven approach `implement-maxpressure-traci-controller` uses for movement-to-phase mapping, just keyed off one specific vehicle's link rather than aggregate detector counts. Filter to the priority class with `traci.vehicle.getVehicleClass(vid) == "bus"` (or whatever vClass the scenario uses) so only intended vehicles request priority.

## Perturbing the signal: current-phase-duration only

**Never jump phase index with `setPhase`.** Only call `traci.trafficlight.setPhaseDuration(tls, remaining)` on the *current* phase — lengthening it for green extension, or shortening it toward a floor for early green/red truncation. SUMO's own static program then handles all phase sequencing, yellow, and clearance intervals untouched; a priority grant is a bounded perturbation of one phase's length, not a rewrite of the signal's logic. `setPhaseDuration` sets the phase's *remaining* duration under TraCI semantics — exactly what both directions need:

- **Green extension** (bus arrives late in its own green): if the phase is about to end and the bus can't clear in the time left, extend the remaining duration up to a capped max-green.
- **Early green / red truncation** (bus arrives on red): once the current conflicting green has met its minimum-green requirement, and only if truncating it would bring the bus's phase next in sequence, cut its remaining duration toward zero.

## The offset-recovery requirement

**A single truncation or extension permanently shifts the signal's cycle offset relative to its background fixed-time schedule if left uncorrected** — every later bus then benefits (or suffers) from that shift regardless of its own request, making priority-grant attribution meaningless and contaminating a baseline-vs-priority comparison. Track per-signal "debt" (seconds the signal is currently ahead of or behind its native schedule: extension adds debt, truncation and recovery both pay it down) and repay it by flexing *only the cross-street green*, never the bus's own phase, once a cross phase is active and no bus is currently being served. This keeps every grant a bounded, transient, individually-attributable perturbation.

## Unconditional vs. conditional priority

Compare (at minimum) three configurations on identical demand and seed:

1. **Baseline** — no intervention; the native program runs untouched.
2. **Aggressive/unconditional** — priority granted on every approach with no per-cycle limit and a near-zero cross minimum-green. Maximizes bus benefit but tends to badly starve cross-street traffic.
3. **Conditional TSP** — priority bounded by a real minimum-green for the cross street and a per-cycle grant limit (e.g. at most 1 grant per signal per cycle), so cross traffic is guaranteed some share of green even under frequent bus arrivals.

`scripts/tsp_controller.py` implements all three modes in one script sharing an identical stepping loop, so the only difference between runs is the signal intervention itself:

```bash
python scripts/tsp_controller.py --mode baseline    --net net.xml --cars cars.rou.xml --buses buses.rou.xml --add stops.add.xml --tsp-signals B1,C1,D1 --cycle-length 60 --outdir runs/baseline
python scripts/tsp_controller.py --mode aggressive  --net net.xml --cars cars.rou.xml --buses buses.rou.xml --add stops.add.xml --tsp-signals B1,C1,D1 --cycle-length 60 --outdir runs/aggressive
python scripts/tsp_controller.py --mode conditional --net net.xml --cars cars.rou.xml --buses buses.rou.xml --add stops.add.xml --tsp-signals B1,C1,D1 --cycle-length 60 --outdir runs/conditional --grant-limit 1 --min-green 10 --trace
```

Compare bus mean travel time / signal delay and arterial vs. cross-street car delay from each run's `tripinfo.xml`, plus the grant counts from `grants_log.json`.

## Verifying grants actually changed signal timing (don't just trust the log)

Run with `--trace` to also dump `phase_trace.json` (realized vs. nominal duration for every phase instance), and cross-reference specific `grants_log.json` events against it: a logged truncation at time *t* should correspond to a phase in `phase_trace.json` ending near *t* with a realized duration well below nominal (and vice versa for extensions). This is the difference between "the controller logged an intent" and "the controller actually changed what SUMO simulated."

## What the aggressive-vs-conditional comparison tends to show

Measured on a 3-signal fixed-time arterial (89 buses over an hour, 40s headway, mixed arterial/cross car demand): aggressive priority cut bus travel time 45% and even improved arterial car delay, but increased cross-street delay roughly 14x. Conditional TSP (min-green 10s, 1 grant/signal/cycle) captured much of the bus benefit (travel time -15%, signal delay -36%) and still improved arterial flow, while limiting the cross-street cost to a much smaller, proportionate increase. The general lesson: unconditional priority is not "free" bus benefit — it typically buys a small additional bus improvement at a wildly disproportionate cross-street cost; a bounded conditional scheme is usually the actual best-balance choice, not a compromise that sacrifices most of the bus benefit.

## Gotchas

- **Never use `setPhase`/jump the phase index** — perturb only the current phase's remaining duration via `setPhaseDuration`, or the native program's sequencing/yellow/clearance logic can be broken.
- **Offset recovery is not optional** — without it, priority grants become unattributable and contaminate later measurements (see above).
- **When counting "blocked by the per-cycle limit," dedupe per phase-instance, not per simulation step** — a naive per-step increment while a blocking condition persists (e.g. across an entire multi-second green-extension window) inflates this diagnostic count relative to the true number of blocked *opportunities*. `scripts/tsp_controller.py` dedupes both truncation- and extension-blocks per phase-instance; if extending or modifying this controller, preserve that dedup on both code paths (a real, previously-shipped bug here inflated only the extension-block count until it was fixed).
- **A per-cycle grant limit only produces a meaningful tradeoff comparison if it actually binds** — at a low enough bus frequency relative to the limit, conditional and aggressive priority converge to similar behavior and the comparison stops being informative; check the bus headway is short enough relative to the cycle length that the limit is genuinely reached.

## Related

- `implement-maxpressure-traci-controller`, `implement-glosa-speed-advisory-controller` — the other TraCI closed-loop signal/vehicle controllers this one shares its phase-introspection and `getNextTLS` patterns with.
- `simulate-multimodal-transit` — for building the scheduled bus line (`busStop`, `line` attribute) this skill's priority logic serves.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for bus-vs-car, arterial-vs-cross-street delay comparisons.
- [[transit-signal-priority]] — the underlying SUMO/TraCI mechanics (setPhaseDuration semantics, offset recovery, the grant-counting gotcha) and the verified aggressive-vs-conditional tradeoff finding.
- `design-bus-stop-placement-type-and-spacing` — imports this skill's controller unchanged to test how stop placement interacts with TSP; finds a near-side stop can cancel most of the priority benefit and flip TSP's net corridor effect from a gain to a loss.
