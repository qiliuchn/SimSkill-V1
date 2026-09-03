---
summary: SUMO road gradient is set via node/edge z-coordinates, preserved by netconvert by default (only --flatten strips it), and derived from compiled-net lane-shape z-data at runtime; verified to drive ICE emissions and EV battery energy monotonically with grade, with EV net energy going genuinely negative on a downhill grade due to regenerative braking recovering more than it consumed — a qualitative effect ICE vehicles cannot produce.
keywords:
  - road-gradient
  - elevation
  - slope
  - netconvert-z-coordinate
  - regenerative-braking
  - grade-emissions
created: 2026-07-25T23:00:00
last_updated: 2026-08-07T03:22:15
sources:
  - "[[episodic-memory/2026-07-25_22-39-09/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_22-39-09/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Networks/PlainXML.html
related_pages:
  - "[[vehicle-emissions-modeling]]"
  - "[[electric-vehicle-battery-and-charging]]"
  - "[[roundabout-modeling-and-comparison]]"
  - "[[abstract-network-generation]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[battery-electric-bus-energy-and-charger-sizing]]"
  - "[[horizontal-curvature-and-curve-speed-in-sumo]]"
  - "[[grade-aware-heavy-vehicle-physics-and-climbing-lane-warrants]]"
related_skills:
  - model-road-gradient-effects-on-energy
  - simulate-fleet-emissions
  - simulate-ev-charging
  - model-vclass-lane-permissions
  - measure-heavy-vehicle-passenger-car-equivalent
  - design-signal-change-and-clearance-intervals
  - model-horizontal-curvature-and-evaluate-design-consistency
  - model-grade-aware-heavy-vehicle-performance-and-climbing-lanes
related_skills_for_graph_view:
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[simulate-fleet-emissions]]"
  - "[[simulate-ev-charging]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[model-horizontal-curvature-and-evaluate-design-consistency]]"
  - "[[model-grade-aware-heavy-vehicle-performance-and-climbing-lanes]]"
---

# Road Gradient and Energy Consumption

SUMO represents longitudinal road gradient (elevation/slope) via `z`-coordinates on plain-XML `<node>` elements, and — unlike every other geometric dimension covered elsewhere in memory ([[abstract-network-generation]]'s flat grids/spiders, [[roundabout-modeling-and-comparison]]'s ring geometry) — grade directly feeds two behavioral models: [[vehicle-emissions-modeling]]'s HBEFA3 emission classes and [[electric-vehicle-battery-and-charging]]'s battery/regenerative-braking model. **Verified elsewhere ([[heavy-vehicle-passenger-car-equivalent-in-sumo]]): grade does NOT feed SUMO's car-following/longitudinal-dynamics models** — `traci.vehicle.getSlope()` correctly reports grade to a vehicle, but acceleration/speed behavior under all 11 of SUMO's built-in car-following models was measured to be essentially unaffected by it. Grade changes energy/emissions outcomes, not capacity or traffic-flow dynamics, in SUMO's default models — the same structural gap [[horizontal-curvature-and-curve-speed-in-sumo]] documents for curve radius, which likewise reaches no built-in speed-choice model.

## Authoring grade

```xml
<node id="A" x="0.0"   y="0.0" z="0.0"/>
<node id="B" x="400.0" y="0.0" z="16.0"/>   <!-- +4% grade: dz/dx = 16/400 = 0.04 -->
```

A constant-grade corridor sets each downstream node's `z` proportional to its `x`-distance from the start. For an isolated, controlled comparison of grade's effect, build variants identical in plan (`x`/`y`) that differ only in `z`.

## netconvert preserves elevation by default

**No special flag is needed to preserve `z` through compilation** — `netconvert` keeps node/edge elevation by default. `--flatten` is the flag that *strips* elevation (useful only when it should be discarded); `--osm.elevation` is specific to OpenStreetMap import and irrelevant to plain-XML authoring. The compiled `.net.xml` has no dedicated slope attribute — elevation lives in each lane's `shape` attribute as `x,y,z` coordinate triples, and SUMO derives grade from consecutive shape points at simulation runtime, not from any precomputed field in the network file.

## Verify realized slope from the compiled net

Read grade back from the compiled network rather than assuming the source `.nod.xml` propagated correctly: parse a lane's `shape` string, take the first and last `(x,y,z)` points, and compute `grade% = 100 * dz / horizontal_distance`. A shape point given with only 2 coordinates (no `z`) means flat (`z=0`) at that point, not a parsing failure — handle this explicitly when computing grade from real compiled-net data. This verify-from-the-compiled-net discipline mirrors [[roundabout-modeling-and-comparison]]'s lesson for right-of-way: never trust the source geometry's intent without confirming it survived compilation.

## The qualitative ICE-vs-EV difference downhill

Both ICE emissions and EV energy consumption scale monotonically with grade — more uphill, less downhill, relative to flat. But downhill grade affects the two vehicle types qualitatively differently: **an EV's net battery energy can go genuinely negative on a sufficiently steep, sufficiently long downhill grade**, because regenerative braking recovers more energy than the vehicle consumed traversing the segment — the battery ends the trip fuller than it started. An ICE vehicle has no equivalent recovery mechanism; its downhill consumption is merely *lower* than flat or uphill, never negative. This distinction should be verified with real numbers (`totalEnergyConsumed` vs. `totalEnergyRegenerated` from the battery output, not assumed) — whether net energy actually crosses zero depends on the specific grade, speed, and vehicle's `recuperationEfficiency`, not something to take for granted just because regenerative braking is enabled.

## Measured finding

On a 1.6km corridor at ±4% grade, identical mixed ICE+EV demand: per-vehicle ICE CO2 scaled from 174g (downhill) to 296g (flat) to 455g (uphill) — roughly 2.6x from downhill to uphill, with fuel consumption tracking the same pattern. EV energy consumption followed the same monotonic ordering, but EV *net* battery energy diverged qualitatively: genuinely negative downhill (-121.7 Wh — the vehicle recovered 271.9 Wh against 150.2 Wh consumed), positive at 156.0 Wh flat, and 446.4 Wh uphill. Battery bookkeeping (initial minus final capacity vs. consumed minus regenerated) was internally consistent to well within 1 Wh, confirming the negative net figure was a genuine energy-balance result, not a measurement artifact.

## Gotcha

A blanket battery-device-probability setting (e.g. `device.battery.probability=1.0`) attaches a default-parameterized battery device to *every* vehicle, including non-EV ones — any per-vehicle-class comparison must filter explicitly by vType/id prefix, or scope the battery device configuration to the EV vType only, to avoid conflating ICE and EV results.

See the `model-road-gradient-effects-on-energy` skill for the full build/verify/compare workflow and bundled scripts.
