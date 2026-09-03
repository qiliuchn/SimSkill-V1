---
summary: Variable Speed Limits (VSL) in SUMO are implemented as a TraCI controller that lowers upstream posted speed limits when E2 lane-area detector occupancy near a bottleneck indicates congestion, but the classic throughput benefit only materializes if the bottleneck has a genuine capacity drop under congestion, which SUMO's default lane-drop merge model may not reproduce.
keywords:
  - variable-speed-limits
  - VSL
  - speed-harmonization
  - E2-detector
  - laneAreaDetector
  - speed-contour
  - capacity-drop
created: 2026-07-24T21:20:00
last_updated: 2026-08-04T21:00:00
sources:
  - "[[episodic-memory/2026-07-24_21-00-00/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_21-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Output/Lanearea_Detectors_%28E2%29.html
related_pages:
  - "[[ramp-metering-with-alinea]]"
  - "[[sumo-output-files]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[simpla-platooning]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[dynamic-hard-shoulder-running-with-traci-lane-permissions]]"
  - "[[driver-desired-speed-and-speed-enforcement-evaluation]]"
  - "[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]"
related_skills:
  - implement-variable-speed-limits
  - implement-alinea-ramp-metering
  - visualize-trajectories-and-timeseries
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[implement-variable-speed-limits]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[analyze-simulation-outputs]]"
---

# Variable Speed Limits and E2 Detectors

Variable Speed Limits (VSL) — lowering posted freeway speed limits upstream of a bottleneck when congestion is detected, then restoring them as it clears — has no built-in SUMO mechanism; it's implemented as a TraCI controller, structurally the mainline-speed analogue of [[ramp-metering-with-alinea]]'s on-ramp-release-rate control: both are downstream-detector-driven closed feedback loops, differing only in what they actuate.

## E2 lane-area detectors

`<laneAreaDetector>` ("E2") aggregates mean speed, occupancy, and jam length over a lane segment and a time interval — richer per-segment data than a point-based E1 induction loop:

```xml
<laneAreaDetector id="e2_s08_e4_l0" lane="e4_0" pos="0.0" length="500.0" period="30" file="det_e2.xml" friendlyPos="true"/>
```

Placed as a series of stations (one detector per lane) spaced along a corridor, E2 output becomes the input both to a live control loop (reading `traci.lanearea.getLastStepOccupancy`/`getLastStepMeanSpeed`) and to offline analysis — including a time-space speed field for visualizing shockwave propagation.

## The VSL control loop

Read a set of E2 detectors just upstream of the bottleneck every step, average and smooth their occupancy over a control interval (e.g. 30s), then adjust a posted-speed "level" applied to every lane in an upstream control zone via `traci.lane.setMaxSpeed`. **Hysteresis needs two components together**: a dead-band (separate escalation/de-escalation occupancy thresholds per level, not one shared threshold) and a minimum dwell time between changes — either alone can still let the controller oscillate under noisy detector readings from step to step.

## Verify the bottleneck has a genuine capacity drop before expecting a throughput benefit

VSL's classic benefit — smoothing inflow to prevent the flow breakdown that follows a bottleneck exceeding its capacity, thereby recovering throughput lost to that breakdown — depends entirely on the bottleneck actually *having* a capacity drop under congestion. **SUMO's default lane-drop merge model may not reproduce this**: measured directly on a 3→2 lane-drop bottleneck, the uncontrolled baseline's discharge rate stayed near free-flow per-lane capacity (~2216 veh/h/lane) even while a substantial queue was present upstream — there was no "lost capacity" for VSL to recover. In that situation, a VSL controller metering upstream inflow can only *subtract* flow from the bottleneck, not restore any. Always check discharge rate per lane during congestion in an uncontrolled baseline before assuming VSL will show a throughput or speed benefit for a given network.

## The tripinfo `timeLoss` confounding gotcha

**`tripinfo`'s `timeLoss` attribute is computed relative to the speed limit a vehicle was legally subject to at each point along its route** — when VSL temporarily lowers that limit, `timeLoss` shrinks accordingly even if the vehicle's actual total time in the network increased. This can make a VSL run look like it reduced delay on `timeLoss` alone while `duration` (raw trip time) or total vehicle-time-in-network tells the opposite, correct story. **Always use `duration`/total vehicle-hours as the unconfounded traveler-cost metric when comparing runs with different posted speed limits** — `timeLoss` alone is unreliable for exactly this comparison.

## Time-space speed-contour visualization

Building a station-index-to-cumulative-distance mapping when placing E2 detectors (see `implement-variable-speed-limits`'s `gen_e2_stations.py`) lets a time-space heatmap be built directly from E2 output: distance along the corridor on one axis, simulation time on the other, mean speed as color. A backward-tilting low-speed (red) band is the direct visual signature of an upstream-propagating shockwave; comparing this contour between an uncontrolled baseline and a controlled run shows whether a control scheme suppressed, delayed, or barely affected the wave — evidence a summary table of aggregate numbers alone doesn't convey.

## Measured finding: flow-smoothing without a throughput gain

On a 3-lane freeway, 3→2 lane-drop bottleneck, peaked demand clearly exceeding bottleneck capacity, identical seed across runs: an aggressive VSL profile (120→60 km/h ladder) reduced bottleneck discharge 9.3% and network mean speed 12.1%, while mean trip duration rose 22.3% — a real net cost, not a wash, consistent with the "no capacity drop to recover" root cause above. A gentler profile shrank the travel-time penalty to +5.4% but still produced no throughput gain. What VSL genuinely delivered instead: severe hard-braking events (a proxy for near-collision events) fell ~69% (aggressive) / ~20% (gentle), and HBEFA3 emissions fell ~4% (CO2/fuel) and ~10% (PMx) — real flow-smoothing, safety, and emissions benefits, distinct from the throughput/speed-recovery result VSL is often deployed to achieve. This is a genuine, verified negative result for the classically-expected benefit on this particular bottleneck model, not a failed implementation — report flow-smoothing/safety/emissions benefits on their own terms when a throughput gain doesn't materialize, rather than forcing a "VSL wins" narrative the data doesn't support.

See the `implement-variable-speed-limits` skill for the full build/control/compare/visualize workflow and bundled scripts. [[coordinated-ramp-metering-delay-transfer-and-ramp-storage]] independently reproduces this page's "verify the capacity drop before expecting a throughput benefit" finding on a different bottleneck and a different controller (coordinated ramp metering rather than VSL), and extends it into a full system-wide delay-transfer accounting.
