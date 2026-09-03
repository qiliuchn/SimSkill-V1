---
summary: SUMO adds sidewalks and marked pedestrian crossings via netconvert's --sidewalks.guess/--crossings.guess/--walkingareas, extending tlLogic state strings with crossing links whose signal-permitted movements can be phased exclusively (a scramble phase) or concurrently with vehicle traffic, trading pedestrian-vehicle conflict exposure against delay for both modes.
keywords:
  - pedestrian-crossing
  - crosswalk
  - sidewalk
  - walkingarea
  - pedestrian-scramble
  - tlLogic
  - conflict-exposure
created: 2026-07-24T14:45:00
last_updated: 2026-08-05T16:00:00
sources:
  - "[[episodic-memory/2026-07-24_14-07-49/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_14-07-49/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Networks/PlainXML.html#pedestrian_crossings
  - https://sumo.dlr.de/docs/Simulation/Pedestrians.html
related_pages:
  - "[[surrogate-safety-measures]]"
  - "[[random-trips]]"
  - "[[sumo-output-files]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
  - "[[right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[motorist-yielding-calibration-and-midblock-crossing-treatment-selection]]"
related_skills:
  - build-pedestrian-crossings-and-phasing
  - create-single-intersection
  - simulate-multimodal-transit
  - analyze-intersection-safety-with-ssm
  - characterize-pedestrian-flow-and-striping-model-artifacts
  - calibrate-motorist-yielding-and-select-midblock-crossing-treatment
related_skills_for_graph_view:
  - "[[build-pedestrian-crossings-and-phasing]]"
  - "[[create-single-intersection]]"
  - "[[simulate-multimodal-transit]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
  - "[[calibrate-motorist-yielding-and-select-midblock-crossing-treatment]]"
---

# Pedestrian Crossings and Signal Phasing

SUMO models pedestrian crossings as real network infrastructure — not just a mode-choice abstraction — via `netconvert --sidewalks.guess --crossings.guess --walkingareas`, which adds marked crosswalks and corner walking areas to a compiled network and extends the intersection's traffic-light logic with dedicated signal states for each crossing. This page covers that infrastructure and the resulting phasing design space (exclusive vs. concurrent pedestrian phases); contrast with [[public-transport-and-intermodal-routing]], where walking is only a leg of an intermodal trip with no crossing-specific infrastructure or signal interaction.

## Crossing and walkingarea network elements

A crossing appears in the compiled net as its own edge:

```xml
<edge id=":center_c0" function="crossing" crossingEdges="out_N in_N">
```

`crossingEdges` names the real vehicle edges the crosswalk physically spans — this is the direct, programmatic way to find which vehicle movements conflict with a given crossing (any `<connection>` whose `from` or `to` edge is in this set), without hand-mapping geometry or compass directions. Walking areas (`function="walkingarea"`) are the corner/sidewalk-junction polygons pedestrians traverse between a sidewalk and a crossing; they don't carry `crossingEdges` and aren't signal-controlled.

## tlLogic link indexing for crossings

Each crossing gets its own signal link, assigned a `linkIndex` in the *same* numbering space as ordinary vehicle movements, via a `<connection>` from the crossing's approaching internal walkingarea to the crossing edge itself:

```xml
<connection from=":center_w1" to=":center_c0" fromLane="0" toLane="0" tl="center" linkIndex="20" dir="s" state="M"/>
```

A `<tlLogic>` phase's `state` string therefore has one character per link index — vehicle links first, crossing links appended — and its total length equals the vehicle-link count plus the crossing-link count. Always re-derive this mapping from the specific compiled net being used (by counting `<connection tl="...">` entries and matching `linkIndex` values), never hardcode it: netconvert's link assignment isn't guaranteed stable across different intersections or even different recompiles of "the same" geometry.

## Exclusive (scramble) vs. concurrent phasing

Two structurally different ways to serve a crossing signal-wise:

- **Exclusive / scramble / "Barnes dance"**: a dedicated phase where every crossing link is green (`state` char in `gG`) while every vehicle link is red. No vehicle movement can be in conflict with a pedestrian during this phase by construction.
- **Concurrent / permissive**: crossings are green in parallel with a compatible vehicle phase (typically the through movement on the same approach), while permitted turning movements (right/left turns that must yield to pedestrians) remain live — a real, if legally-yielding, conflict exposure.

`netconvert --tls.scramble.time <n>` is documented to inject an exclusive phase automatically, but **this has been observed not to take effect on at least one SUMO build** (verified by diffing the compiled `tlLogic` against the same command without the flag — byte-identical output). Don't trust the flag without checking the compiled net's phases actually differ from the non-scramble baseline; build the phase explicitly as an additional-file `<tlLogic>` if it doesn't, using a **distinct `programID`** from the network's own program (an additional-file program can't reuse the net's `programID` — SUMO raises "Another logic with id ... exists") and activating it via `traci.trafficlight.setProgram(tls_id, programID)` after simulation start.

## Measuring pedestrian-vehicle conflict exposure

SUMO's SSM device (see [[surrogate-safety-measures]]) only computes vehicle-vehicle conflict measures — it has no pedestrian-aware mode. Conflict exposure between a pedestrian and a vehicle has to be measured directly via TraCI: per simulation step, for each crossing, check whether (a) the crossing's own signal link is walk, (b) a pedestrian physically occupies the crossing edge (`traci.edge.getLastStepPersonIDs`), and (c) a conflicting vehicle movement (per the crossing's `crossingEdges`) is simultaneously signal-permitted and has a vehicle on its internal via-lane. Cross-check the resulting signal-aware count against a signal-agnostic physical-co-occupancy count (same test, ignoring signal state) as a sanity denominator — an exclusive-scramble scheme's signal-aware count should be near zero while its signal-agnostic count may still be nonzero (peds and vehicles physically adjacent but never both signal-permitted at once), confirming the gating logic is doing real work rather than being vacuously always-zero.

## The delay-vs-conflict-exposure tradeoff

Measured on a 4-way intersection with a fixed 90s cycle, 200 vehicles + 334 pedestrians, identical demand across both phasing schemes: the exclusive scramble phase eliminated signal-aware conflict exposure entirely (0 conflict ticks vs. a concurrent scheme's real, substantial count — cross-validated against a signal-agnostic physical-occupancy count that also stayed near zero for the scramble, ruling out a vacuous always-zero result), but cost **both** modes delay relative to concurrent phasing — pedestrians mean waiting time roughly doubled, and vehicle mean waiting time also rose substantially — because the exclusive phase spends real cycle time on an all-red vehicle interval that every movement must wait through. Concurrent/permissive phasing was faster for both pedestrians and vehicles but sustained genuine, nonzero conflict exposure from permitted turning movements. This is a real, two-sided tradeoff, not a case where one scheme dominates: an exclusive phase is not a free pedestrian-delay win, and concurrent phasing is not a free efficiency win once conflict exposure is counted as a cost.

See the `build-pedestrian-crossings-and-phasing` skill for the full build/verify/measure workflow and bundled scripts.
