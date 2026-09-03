---
summary: SUMO's simpla plugin dynamically forms cooperative vehicle platoons, switching in-platoon vehicles to the CACC car-following model with tightened gaps; verified to genuinely reduce travel time and increase throughput at realistic (non-oversaturated) freeway demand, with platoon followers concentrating disproportionately in one lane under mixed penetration and CACC damping (not amplifying) a forced speed disturbance down the platoon chain.
keywords:
  - simpla
  - platooning
  - CACC
  - connected-automated-vehicles
  - string-stability
  - car-following-model
created: 2026-07-25T22:15:00
last_updated: 2026-07-25T22:15:00
sources:
  - "[[episodic-memory/2026-07-25_15-31-58/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_15-31-58/attempts/attempt-2/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simpla.html
related_pages:
  - "[[traci]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[sumo-output-files]]"
  - "[[phantom-traffic-jams-and-single-av-stabilization]]"
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
related_skills:
  - form-platoons-with-simpla
  - run-simulation
  - implement-alinea-ramp-metering
  - implement-variable-speed-limits
  - measure-av-penetration-effect-on-bottleneck-capacity
related_skills_for_graph_view:
  - "[[form-platoons-with-simpla]]"
  - "[[run-simulation]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-variable-speed-limits]]"
  - "[[measure-av-penetration-effect-on-bottleneck-capacity]]"
---

# simpla Platooning

`simpla` is SUMO's dedicated platooning plugin: it dynamically forms cooperative vehicle platoons at runtime and switches in-platoon vehicles to the CACC (Cooperative Adaptive Cruise Control) car-following model, tightening inter-vehicle gaps relative to ordinary ACC or human-driven car-following. This is a genuinely distinct mechanism from every other closed-loop TraCI controller in memory (GLOSA, max-pressure, TSP) — those advise or control a single vehicle or signal; `simpla` manages dynamically-forming *groups* of cooperating vehicles.

## Location and loading order

`simpla` ships under `$SUMO_HOME/tools/simpla`, not as a separate pip package — add `$SUMO_HOME/tools` to `sys.path` (the same path `traci` needs) before importing it. **It must be imported and `simpla.load(cfg)`-called after `traci.start()`**, not before; once loaded it registers itself as a step listener, so platoon management happens automatically on every `traci.simulationStep()` with no further intervention needed.

## Configuration: vType roles and join thresholds

A `vTypeMapFile` maps one base vType to four platoon-role vTypes (`orig:leader:follower:catchup:catchupFollower`); `vehicleSelectors` restricts management to vType ids matching a substring, so non-connected vehicles are left entirely alone. Follower/catchupFollower roles should use `carFollowModel="CACC"` with a short `tau` (e.g. 0.6s); leader/catchup roles use `carFollowModel="ACC"` with a longer `tau` (e.g. 1.4s) — the CACC/ACC gap difference is what any platooning benefit physically depends on.

**Join thresholds need empirical tuning for the specific road speed, not just documented defaults.** On a fast (33 m/s) multi-lane freeway, a tight `maxPlatoonHeadway` (1.5s) left roughly 99% of managed vehicles stuck in `catchup` (ACC) mode in one verified build, never actually becoming genuine CACC followers; loosening it to 2.5s let vehicles a few seconds apart join as real followers, engaging the tight-gap CACC behavior the scenario was meant to demonstrate. Verify the actual role distribution achieved, don't assume a chosen threshold value works as intended.

## Verifying genuine formation and gap-tightening

Don't trust configuration alone. `simpla` exposes a live API (`getPlatoonLeaderIDList`, `getPlatoonID`, `getPlatoonInfo`) for directly confirming platoons formed, with genuine multi-vehicle size (a "platoon" of size 1 isn't one). For gap-tightening, compute realized time-headway/space-gap between consecutive same-lane vehicles directly from FCD: genuine platooning should show sub-second headways physically impossible under the baseline's ACC-only `tau`, concentrated specifically among platoon-role vTypes (`*_follower`/`*_catchupFollower`) — not spread evenly across all vehicles, which would indicate a confound rather than real platooning.

## Demand-density discipline

A platooning throughput benefit demonstrated only under demand well above a scenario's realistic or specified range is not evidence the effect holds at realistic demand — the entire narrative can collapse to an artifact of artificial bottleneck oversaturation. Verify a claimed benefit persists (even if smaller) at genuinely in-spec, non-oversaturated demand before reporting it; if a network segment does saturate at the demand level actually specified, report that honestly with real `departDelay` figures rather than quietly inflating demand to manufacture queueing.

## Per-lane occupancy under mixed penetration

Platoon followers can concentrate disproportionately in specific lanes under partial (mixed) CAV penetration — measured in one case: at 50% penetration, platoon followers occupied the middle lane ~61% of vehicle-time versus a uniform 33% expectation, with non-connected vehicles correspondingly displaced toward another lane. At full penetration this effect washes out (every vehicle is a platoon member, so there's no differential lane preference to observe). Compute this directly from FCD (vehicle-time-weighted occupancy fraction per lane, split by role) rather than assuming uniform lane use.

## String-stability verification

String stability — whether a speed/spacing disturbance from a platoon leader damps or amplifies as it propagates to trailing followers — is not automatically guaranteed by CACC and should be measured, not assumed. If natural cruising traffic shows negligible speed variance (nothing to measure disturbance propagation against), a forced-perturbation test works: make a platoon leader brake sharply for a few seconds mid-corridor and track the speed-deviation amplitude at each successive follower. In one verified test (8-vehicle platoon, leader forced 33→18 m/s brake for 4s), the disturbance damped from a 15.33 m/s leader speed dip to 8.94 (follower 1), 2.12 (follower 2), and effectively zero by followers 3-7 — a clearly string-stable response for that CACC configuration.

## Measured findings

On a 3-lane, 3km freeway at 1800 veh/h/lane (within realistic per-lane freeway capacity), full CAV penetration vs. a matched non-platooned baseline: mean travel time -11%, timeLoss -65%, mainline throughput +4% (consistent across multiple demand seeds), mean speed +12.5%. The benefit persisted, proportionally smaller, at an undersaturated 1200 veh/h/lane (throughput +1.6%, travel time still -9%, timeLoss -73%) — confirming the benefit wasn't an artifact of demand oversaturation at the higher rate. This is a real, if modest, network-level benefit from cooperative platooning at realistic freeway demand levels, not merely a locally-tight-gap effect with no aggregate consequence.

See the `form-platoons-with-simpla` skill for the full build/verify workflow, worked config templates, and bundled scripts.
