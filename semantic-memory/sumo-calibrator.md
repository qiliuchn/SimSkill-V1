---
summary: SUMO's <calibrator> additional-file element enforces a target flow and speed at a specific edge live, every simulated second, by inserting or removing vehicles — distinct from offline demand calibration — and can dissolve a downstream jam's upstream impact via jamThreshold, verified via its own calstats output and GEH to converge within GEH<1 in both under- and over-supply cases while remaining bounded by real physical bottleneck capacity.
keywords:
  - calibrator
  - jamThreshold
  - live-flow-enforcement
  - calstats
  - in-simulation-calibration
created: 2026-07-25T15:30:00
last_updated: 2026-08-06T21:24:14
sources:
  - "[[episodic-memory/2026-07-25_15-06-30/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_15-06-30/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Calibrator.html
related_pages:
  - "[[geh-statistic]]"
  - "[[routesampler]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[sumo-output-files]]"
  - "[[multi-resolution-modeling-buffer-sizing-and-boundary-handoff]]"
related_skills:
  - calibrate-flow-with-in-simulation-calibrator
  - calibrate-demand-with-routesampler
  - implement-alinea-ramp-metering
  - extract-subnetwork-scenario-with-boundary-demand
related_skills_for_graph_view:
  - "[[calibrate-flow-with-in-simulation-calibrator]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
---

# SUMO Calibrator

SUMO's `<calibrator>` additional-file element enforces a target flow rate and/or speed at a specific edge **live, every simulated second**, by inserting vehicles to make up a shortfall or removing them to shed a surplus — a fundamentally different mechanism from offline demand calibration ([[routesampler]] scales a pre-existing route pool to match target counts *before* the simulation runs). The calibrator acts continuously against whatever the underlying route file's demand actually produces, regardless of whether that demand under- or over-supplies the target.

## Schema

```xml
<calibrator id="cal_E2" edge="E2" pos="250" output="calstats.xml" period="60" jamThreshold="0.5">
    <flow begin="0" end="600" route="corridor" type="car" vehsPerHour="1200.0" speed="25.0"/>
    <flow begin="600" end="1200" route="corridor" type="car" vehsPerHour="2000.0" speed="25.0"/>
</calibrator>
```

Each `<flow>` child specifies one target interval (`vehsPerHour`, `speed`) and which `route`/`type` to insert when supplementing flow. `output` writes the calibrator's own `calstats` file — per interval, `flow`/`aspiredFlow`, `speed`/`aspiredSpeed`, and `inserted`/`removed`/`cleared`/`nVehContrib` counts — the authoritative source for verifying enforcement, not something to re-derive from a separate detector when it's already provided directly.

## jamThreshold: jam-clearing

`jamThreshold` (an occupancy fraction, e.g. `0.5`) enables an additional behavior: when downstream occupancy at the calibrated edge exceeds this threshold, the calibrator removes vehicles to relieve the backup, on top of its normal target-flow insert/remove logic. Leaving it unset (or 0) disables jam-clearing entirely. Verifying jam-clearing's specific contribution requires comparing an otherwise-identical jamThreshold-on vs. jamThreshold-off run pair — a single run alone can't isolate the effect.

## The vType/route loading-order gotcha

**A calibrator's `<flow type="...">` cannot reference a vType or route defined only in a route (`-r`) file** — SUMO's file-loading order places additional files ahead of route files, so any vType/route a calibrator's flows need must live in an additional file that loads before the calibrator's own file (or the same one), and be listed accordingly in `--additional-files`.

## Physical bottleneck limits

**A calibrator cannot push more flow past its edge than a genuine downstream physical bottleneck's real capacity allows.** During active downstream congestion, realized flow at the calibrated point can fall short of target no matter how aggressively the calibrator inserts — this is correct, expected behavior (the calibrator enforces flow at its own point, not network-wide throughput past every downstream constraint), not a malfunction. When a target goes unmet, check for an active downstream capacity constraint before attributing the shortfall to the calibrator itself.

## Verified findings

On a 5-edge corridor with a mid-corridor calibrator (three target intervals: 1200/2000/1600 veh/h): against a deliberately under-supplying baseline (800 veh/h), the calibrator drove realized flow to GEH 0.45-0.70 of target (uncalibrated baseline GEH 14.8-32.3) via insertion (74/201/133 vehicles per interval). Against a deliberately over-supplying baseline (2800 veh/h), it drove flow to GEH 0.00-0.05 via removal (248/134/201 vehicles per interval). Under a genuine induced downstream jam, `jamThreshold=0.5` raised upstream mean speed roughly 5x and upstream flow 69% versus an identical run with jam-clearing disabled — but the calibrator's own target flow went unmet specifically during the active jam window (GEH 12.88, failing the <5 threshold) because the downstream bottleneck physically capped throughput, exactly the expected physical-limits behavior described above, not a calibrator defect.

See the `calibrate-flow-with-in-simulation-calibrator` skill for the full build/run/verify workflow, a worked template, and the bundled verification script.
