---
summary: The macroscopic fundamental diagram (flow-density-speed) can be empirically constructed in SUMO from E1 induction-loop detector data across a steady-state demand sweep on a bottlenecked freeway, requiring a genuine downstream lane-drop to reveal the congested branch; verified to show the classic free-flow branch, a capacity/critical-density point, a capacity-drop congested branch, and both bounded below the theoretical single-lane bottleneck capacity.
keywords:
  - macroscopic-fundamental-diagram
  - flow-density-speed
  - E1-detector
  - induction-loop
  - capacity-drop
  - critical-density
created: 2026-07-26T09:10:00
last_updated: 2026-07-26T09:10:00
sources:
  - "[[episodic-memory/2026-07-26_08-50-17/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-26_08-50-17/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Output/Induction_Loops_Detectors_(E1).html
related_pages:
  - "[[ramp-metering-with-alinea]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[sumo-output-files]]"
  - "[[sumo-plotting-tools]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[weather-friction-effects-on-capacity-and-safety]]"
  - "[[phantom-traffic-jams-and-single-av-stabilization]]"
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[mfd-based-perimeter-gating]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
related_skills:
  - build-macroscopic-fundamental-diagram
  - implement-alinea-ramp-metering
  - implement-variable-speed-limits
  - analyze-simulation-outputs
  - implement-mfd-based-perimeter-gating
  - measure-heavy-vehicle-passenger-car-equivalent
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - validate-kinematic-wave-theory-across-car-following-models
  - characterize-pedestrian-flow-and-striping-model-artifacts
related_skills_for_graph_view:
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-variable-speed-limits]]"
  - "[[analyze-simulation-outputs]]"
  - "[[implement-mfd-based-perimeter-gating]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
---

# Macroscopic Fundamental Diagram

The macroscopic fundamental diagram (MFD) — the relationship between traffic flow, density, and speed at a point or section of road — is the central relationship of traffic-flow theory, and can be empirically constructed in SUMO from E1 induction-loop detector data across a steady-state demand sweep. This page treats E1 detectors as a standalone measurement instrument in their own right; every other use of E1 loops in memory ([[ramp-metering-with-alinea]], [[variable-speed-limits-and-e2-detectors]]) embeds them inside a live feedback controller instead.

## A bottleneck is required to observe the congested branch

An unconstrained corridor with no downstream bottleneck only ever traces the free-flow branch of the diagram — flow rises with demand up to whatever throughput the network can actually carry, with no mechanism to produce a queue at a specific upstream measurement point. A genuine fixed-capacity bottleneck (e.g. a lane drop) downstream of the measurement station is what makes the congested branch observable: once demand exceeds the bottleneck's reduced throughput, a queue forms and backs up over the upstream station, producing the high-density, low-speed points that define the congested branch. The measurement station must sit **upstream** of the bottleneck, not at or past it.

## Deriving flow, density, and speed from E1 output

Per-interval E1 attributes: `nVehContrib` (vehicle count), `flow` (already veh/h-normalized), `occupancy` (% time occupied), `harmonicMeanSpeed` (the correct space-mean-speed average — use harmonic, not arithmetic, mean), `length` (mean vehicle length that interval).

- **Flow**: `q_i = nVehContrib_i / duration * 3600` per lane, summed across the station's lanes.
- **Space-mean speed**: harmonic mean, `v_i = n_i / sum(n_i/speed_i)` per lane, combined as `v_space = n_total / sum_over_lanes(n_i/v_i)`.
- **Density**: two independent estimators worth cross-checking — `k_qv = q/v_space` (the fundamental relation `q=k·v`) and `k_occ = 10 * occupancy% / mean_vehicle_length` from the occupancy attribute directly. These agree closely in free flow and can diverge more (10%+ or more) under congestion; report both rather than trusting one.

Compute density **per lane before summing** rather than from station-aggregate flow/speed — this correctly handles uneven lane loading, which differs sharply between free flow (vehicles favor one lane) and congestion (vehicles spread across all lanes).

## The demand sweep and steady-state discipline

Run identical network/detector setup at a series of demand levels spanning well below to well above the expected bottleneck capacity, each run long enough that a genuine steady state is reached before the measurement window begins — discard an initial warmup period rather than averaging from `t=0`. Classify each run's regime (free-flow vs. congested) from its *measured* space-mean speed against a threshold, not from the demand level alone, since the actual breakpoint (capacity) is exactly what the sweep is measuring.

## Sanity-checking capacity against theory

The theoretical maximum single-lane capacity, `v_free / (v_free·tau + length + minGap) * 3600` (vehicles/hour, from the car-following model's saturated headway), bounds both the measured pre-breakdown capacity and the congested discharge flow (scaled by the number of downstream bottleneck lanes). Either figure exceeding this bound is a red flag that the measurement station isn't genuinely bottleneck-limited by the intended lane drop.

## Jam density: measured vs. extrapolated

A two-point linear extrapolation of the congested branch to `q=0` (via the backward-wave slope between the capacity point and the mean congested point) is unreliable when the congested branch is a tight cluster rather than a real spread toward standstill — extrapolating far beyond the observed data range typically overshoots the physical jam-density limit. Report a physically-grounded standstill estimate (`1000/(vehicle_length+minGap)` per lane, times the jamming lane count) alongside any extrapolated figure, explicitly labeling the latter as unreliable rather than presenting it as a confident measurement.

## Measured finding

On a 3-lane freeway with a 3→1 lane drop, a 17-point demand sweep from 600 to 7000 veh/h: the free-flow branch tracked flow=demand up to a capacity of 2500 veh/h at ~21 veh/km critical density and ~117 km/h free-flow speed. Beyond capacity, the congested branch showed speed collapsing to ~10 km/h with discharge flow settling at a reduced ~1938 veh/h — a ~22% capacity drop between the pre-breakdown peak and the queued-discharge flow, the well-documented capacity-drop phenomenon in real-world traffic-flow data. Both figures fell safely below the theoretical single-lane capacity bound, and the congested-branch runs showed zero teleports/collisions — confirming genuine physical queueing, not a simulation artifact, produced the congested branch.

See the `build-macroscopic-fundamental-diagram` skill for the full bottleneck/detector build workflow and bundled sweep-analysis script. This page's MFD is a point/corridor-level flow-density-speed relationship, purely descriptive; [[mfd-based-perimeter-gating]] instead measures a network-region's accumulation-production MFD and uses it as an *active control variable* to throttle perimeter inflow.
