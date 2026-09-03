---
name: calibrate-flow-with-in-simulation-calibrator
description: Use this skill when the user wants to enforce a target traffic flow and/or speed at a specific point in a SUMO network DURING the simulation — SUMO's <calibrator> additional-file element, which live-inserts vehicles to make up a shortfall or removes them to shed a surplus, and can dissolve a downstream jam's upstream impact via jamThreshold. This is distinct from offline demand calibration (routeSampler, which scales a route pool before the run) — the calibrator acts live, every simulated second. Covers the calibrator XML schema, its required companion route/vType definitions, the vType-loading-order gotcha, insert/remove/jamThreshold semantics, and verifying enforcement via the calibrator's own calstats output plus GEH. Trigger on mentions of calibrator, in-simulation calibration, jamThreshold, or live flow enforcement.
---

# Calibrate Flow with an In-Simulation Calibrator

Enforces a target flow rate and/or speed at a specific edge, live, throughout a SUMO simulation — inserting vehicles to make up a shortfall relative to a schedule of target values, or removing them to shed a surplus, and (via `jamThreshold`) removing vehicles to dissolve a jam's impact on the calibrated point. This is fundamentally different from every other demand-calibration skill in memory: `calibrate-demand-with-routesampler` scales a *pre-existing route pool* to match target counts *before* the simulation runs; the `<calibrator>` element acts *during* the simulation, every simulated second, regardless of what the underlying route file's demand actually specifies.

## The calibrator element

```xml
<additional>
    <calibrator id="cal_E2" edge="E2" pos="250" output="calstats.xml" period="60" jamThreshold="0.5">
        <flow begin="0" end="600" route="corridor" type="car" vehsPerHour="1200.0" speed="25.0"/>
        <flow begin="600" end="1200" route="corridor" type="car" vehsPerHour="2000.0" speed="25.0"/>
        <flow begin="1200" end="1800" route="corridor" type="car" vehsPerHour="1600.0" speed="25.0"/>
    </calibrator>
</additional>
```

See `templates/calibrator_example.add.xml` for a complete, verified working example. Each `<flow>` child is a target interval: `vehsPerHour` is the target flow, `speed` the target mean speed, `route`/`type` name the route and vehicle type to insert when supplementing flow. `output` writes the calibrator's own `calstats` file — the authoritative source for realized-vs-aspired flow/speed and insert/remove/cleared counts (see Verification below), not something to re-derive from a separate detector when the calibrator's own output already provides it.

`jamThreshold` (occupancy fraction, e.g. `0.5`) enables jam-clearing: when downstream occupancy at the calibrated edge exceeds this threshold, the calibrator removes vehicles to relieve the backup, in addition to its normal insert/remove-to-target behavior. Omitting `jamThreshold` (or setting it to 0/leaving it unset) disables jam-clearing entirely — verify this distinction with an otherwise-identical run pair (one with, one without) before attributing an observed effect to jam-clearing specifically.

## The vType/route loading-order gotcha

**A calibrator's `<flow type="...">` cannot reference a vType defined only in a route (`-r`) file** — SUMO loads additional files before route files, so a vType or route the calibrator needs must be defined in an additional file that loads *before* the calibrator's own additional file (or in the same one). Define the `<vType>` and any named `<route>` the calibrator's flows reference in a separate additional file, and list it ahead of the calibrator's file in `--additional-files`.

## What the calibrator cannot do: physical bottleneck limits

**A calibrator cannot push more flow past its edge than a genuine downstream physical bottleneck allows.** If congestion downstream of the calibrated point caps real throughput, the calibrator's realized flow will fall short of its target during that window regardless of how aggressively it inserts — this is expected, correct behavior (the calibrator enforces flow at *its own edge*, not network-wide throughput), not a malfunction. Verify this distinction explicitly when jam-testing: check whether a shortfall coincides with an active downstream capacity constraint before concluding the calibrator failed.

## Verifying enforcement

Don't assume the calibrator worked because the run completed — verify from its own `calstats` output and, ideally, against an otherwise-identical uncalibrated baseline:

```bash
python scripts/verify_calibrator.py \
    --calstats out/cal_calstats.xml --baseline-e1-output out/base_e1.xml --out-csv comparison.csv
```

For each interval, this reports the calibrator's own realized-vs-aspired flow with GEH (`sqrt(2*(observed-expected)^2/(observed+expected))`, see [[geh-statistic]] — GEH<5 is the standard per-interval acceptance threshold), the insert/remove/cleared counts, and — when a baseline E1 detector output is supplied — the uncalibrated realized flow's GEH for comparison. A working calibrator should show GEH well under 5 in every interval where no physical bottleneck constrains it, against a baseline GEH that can be far higher in either direction (under-supply or over-supply).

## What a well-configured calibrator demonstrates

Measured on a 5-edge corridor with a mid-corridor calibrator (3 target intervals: 1200/2000/1600 veh/h): against a deliberately under-supplying baseline (800 veh/h), the calibrator drove realized flow to within GEH 0.45-0.70 of target (baseline GEH 14.8-32.3) by inserting vehicles (74/201/133 per interval, confirmed in `calstats`). Against a deliberately over-supplying baseline (2800 veh/h), it drove flow to within GEH 0.00-0.05 by removing vehicles (248/134/201 per interval). Under a genuine downstream jam (induced via a variable speed sign), `jamThreshold=0.5` raised upstream mean speed roughly 5x and upstream flow 69% versus an otherwise-identical run with jam-clearing disabled — but the calibrator's own target flow went unmet during the active jam window specifically because the downstream bottleneck physically capped throughput, not because the calibrator malfunctioned.

## Gotchas

- **A calibrator's `<flow>` needs its `type`/`route` defined in an additional file loaded before the calibrator's own file** — a route-file-only vType/route isn't visible to it.
- **`jamThreshold` must be explicitly set to enable jam-clearing** — verify the distinction with an otherwise-identical jamThreshold-on vs. jamThreshold-off run pair, not assumed from a single run.
- **A calibrator target unmet during an active downstream jam is not necessarily a calibrator failure** — check whether a real physical bottleneck capped throughput before concluding otherwise.
- **The calibrator's own `calstats` output is the authoritative realized-flow source** — prefer it over re-deriving flow from a separate detector when both are available.

## Related

- `calibrate-demand-with-routesampler` — SimSkill's offline demand-calibration skill; contrast its pre-run route-pool scaling against this skill's live, every-second enforcement.
- `implement-alinea-ramp-metering` — the closest existing precedent for hand-authored corridor networks and induction-loop instrumentation this skill reuses.
- [[geh-statistic]] — the GEH formula and acceptance threshold used to validate calibrator enforcement.
- [[sumo-calibrator]] — the underlying calibrator XML schema, the loading-order gotcha, and the verified enforcement/jam-resolution findings.
