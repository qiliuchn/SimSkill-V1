---
name: implement-variable-speed-limits
description: Use this skill when the user wants to implement Variable Speed Limits (VSL) / speed harmonization on a SUMO freeway to manage a recurring bottleneck — a closed-loop TraCI controller that lowers posted upstream speed limits when downstream E2 detector occupancy indicates congestion, and restores them as it clears. Covers building a genuine fixed capacity-drop bottleneck (lane drop), E2 lane-area detector instrumentation, the VSL control loop with hysteresis, comparing against a no-control baseline (throughput, speed, time loss, hard-braking, HBEFA3 emissions), and building a time-space speed-contour heatmap to visualize the congestion shockwave. Trigger on mentions of variable speed limit, VSL, speed harmonization, freeway bottleneck control, E2 detector, or speed contour.
related_skills:
  - implement-alinea-ramp-metering
  - simulate-incident-rerouting
  - visualize-trajectories-and-timeseries
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[implement-alinea-ramp-metering]]"
  - "[[simulate-incident-rerouting]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[variable-speed-limits-and-e2-detectors]]"
---

# Implement Variable Speed Limits

Manages a recurring freeway bottleneck by lowering posted speed limits upstream when a downstream E2 detector signals congestion, then restoring them as it clears — a closed-loop TraCI controller in the same family as `implement-alinea-ramp-metering` (downstream-detector-driven feedback) but acting on mainline speed limits rather than an on-ramp's release rate. **Verify whether VSL actually helps before assuming it will**: its classic benefit (recovering lost bottleneck capacity by smoothing inflow) only materializes if the bottleneck has a genuine capacity drop under congestion — SUMO's default lane-drop merge model doesn't necessarily reproduce this, and VSL can end up only subtracting flow with no capacity to recover.

## Building a genuine capacity-drop bottleneck

A lane drop (e.g. 3→2 lanes) is the simplest bottleneck: in the plain-XML `.edg.xml`/compiled `.net.xml`, the dropped lane simply has no outgoing `<connection>` past the drop point. Verify the drop is real by grepping the compiled net for the approach edge's connections — the rightmost lane should have no `to=` entry beyond the merge point. Generate demand with a pronounced peak clearly exceeding the bottleneck's per-lane discharge capacity (time-varying `<flow>` insertion rates work well) so congestion reliably forms and later dissipates within the simulated window.

**Check whether the bottleneck actually exhibits a capacity drop before expecting VSL to show a throughput benefit.** Compute the discharge rate per lane at the bottleneck (from E1 induction loops at the exit) during the congested window in an uncontrolled baseline — if it's still near free-flow per-lane capacity even while a queue is present upstream, there's no "lost capacity" for VSL to recover, and a VSL controller can only reduce flow, not restore it. This is a real, previously-observed behavior of SUMO's default merge model, not a hypothetical — check it directly for the specific network rather than assuming VSL will help.

## Instrumenting with E2 lane-area detectors

An E2 (`laneAreaDetector`) reports mean speed, occupancy, and jam length aggregated over a lane segment and a time interval — richer per-segment data than an E1 point detector:

```xml
<laneAreaDetector id="e2_s08_e4_l0" lane="e4_0" pos="0.0" length="500.0" period="30" file="det_e2.xml" friendlyPos="true"/>
```

`scripts/gen_e2_stations.py` automates placing a station (one detector per lane) every `--station-spacing` meters along a given corridor edge order, splitting edges longer than ~1.4x the spacing into multiple stations, and writes `stations.json` mapping each station to its cumulative distance along the corridor — the data a time-space plot's y-axis needs. It also places E1 induction loops at a discharge edge for throughput counting, and writes one additional-file per run label so concurrent runs' detector output never collides.

## The VSL control loop

`scripts/run_vsl.py` reads a set of E2 detectors just upstream of the bottleneck every step, averages their occupancy, and smooths it over a control interval (e.g. 30s). On each control decision:

- **Escalate** (lower the posted speed a level) when smoothed occupancy exceeds that level's `up` threshold.
- **De-escalate** (raise it back) when smoothed occupancy falls below the level's `down` threshold.
- **Hysteresis**: separate up/down thresholds per level (not one shared threshold) plus a minimum dwell time between changes — both together prevent oscillation every control interval.

The controller applies the level's speed to every lane of a named upstream control zone via `traci.lane.setMaxSpeed(f"{edge}_{lane_index}", speed_ms)`. Define the speed ladder and thresholds as a JSON profile:

```json
{"speeds_ms": [33.33, 27.78, 22.22, 16.67], "kmh": [120, 100, 80, 60], "up": [12.0, 20.0, 30.0], "down": [7.0, 14.0, 22.0]}
```

```bash
python scripts/gen_e2_stations.py --net freeway.net.xml --edge-order e0,e1,e2,e3,e4,e5 \
    --station-spacing 500 --discharge-edge e5 --out-dir detectors \
    --run-labels baseline,vsl --output-dir-template "outputs/{label}"

python scripts/run_vsl.py --mode baseline --net freeway.net.xml --routes freeway.rou.xml \
    --add detectors/detectors_baseline.add.xml --outdir outputs/baseline

python scripts/run_vsl.py --mode vsl --net freeway.net.xml --routes freeway.rou.xml \
    --add detectors/detectors_vsl.add.xml --control-zone-edges e1,e2,e3,e4 \
    --control-detectors e2_s08_e4_l0,e2_s08_e4_l1,e2_s08_e4_l2 \
    --profile-json vsl_profile.json --outdir outputs/vsl
```

Both runs use identical network, routes, and `--seed` — the only difference is the VSL intervention itself.

## Comparing runs, and a tripinfo gotcha

Compare bottleneck discharge rate (from E1 loops), network mean speed, hard-braking event counts (logged live by `run_vsl.py` from `traci.vehicle.getAcceleration`), and HBEFA3 emissions sums (from tripinfo) between runs.

**`tripinfo`'s `timeLoss` is confounded when the posted speed limit varies over the route** — it's computed relative to the vehicle's *legally-observed* speed limit at each point, so a VSL run's lowered limits make `timeLoss` look artificially better even when the vehicle's actual total time in the network got worse. **Use `duration` (mean trip duration) or total vehicle-time-in-network as the unconfounded traveler-cost metric**, not raw `timeLoss`, whenever comparing runs with different posted speed limits.

## Building the time-space speed-contour heatmap

`scripts/plot_speed_contour.py` reads `stations.json` and each run's `det_e2.xml`, averages mean speed across all lanes at each station per interval, and plots distance (y) vs. simulation time (x) with speed as color — side by side for multiple runs:

```bash
python scripts/plot_speed_contour.py --stations detectors/stations.json \
    --run baseline=outputs/baseline/det_e2.xml --run vsl=outputs/vsl/det_e2.xml \
    --bottleneck-dist 4500 --out plots/speed_contour.png
```

A backward-tilting red (low-speed) band is the visual signature of an upstream-propagating shockwave; comparing the tilt/extent between a baseline and a controlled run shows directly whether the control scheme suppressed, delayed, or barely affected the wave — a genuinely different kind of evidence than a summary table of aggregate numbers.

## What the VSL comparison can show (a real negative result, not just a win)

Measured on a 3-lane freeway with a 3→2 lane-drop bottleneck under peaked demand: VSL did **not** improve bottleneck throughput or network mean speed — it reduced both (discharge -9%, mean speed -12% under an aggressive profile), while mean trip duration rose 22%. Root cause: the bottleneck's uncontrolled discharge rate was already near free-flow per-lane capacity even while queued, so there was no capacity drop for VSL to recover, and metering upstream inflow only subtracted flow. VSL's genuine benefit was elsewhere: severe hard-braking events fell ~69%, and HBEFA3 CO2/fuel emissions fell ~4%, PMx ~10% — real flow-smoothing, safety, and emissions gains, just not the throughput/speed-recovery result VSL is often deployed for. **Don't assume a throughput win — measure it, and report flow-smoothing/safety/emissions benefits on their own terms if that's what the data actually shows.**

## Gotchas

- **Verify the bottleneck has a real capacity drop before expecting VSL to help throughput** — check per-lane discharge rate during congestion in an uncontrolled baseline first.
- **`tripinfo`'s `timeLoss` is confounded by a time-varying posted speed limit** — use `duration`/total vehicle-time instead when comparing VSL against baseline.
- **Hysteresis needs both a dead-band (separate up/down thresholds) and a minimum dwell time** — either alone can still allow rapid oscillation under noisy detector readings.
- **A detector id embeds its station index for the contour plot to key on** (`e2_s{station:02d}_{edge}_l{lane}`) — if hand-authoring detectors instead of using `gen_e2_stations.py`, keep this convention or adapt the contour script's parsing.

## Related

- `implement-alinea-ramp-metering` — the other downstream-detector-driven closed-loop freeway controller; VSL manages mainline speed, ALINEA meters on-ramp release rate.
- `simulate-incident-rerouting` — lane-closure mechanics relevant to constructing a fixed bottleneck (though VSL's bottleneck is permanent, not a temporary incident).
- `visualize-trajectories-and-timeseries` — general FCD-based trajectory/time-space plotting; this skill's E2-detector-based speed contour is a bottleneck-focused specialization.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for freeway/E2/HBEFA3 output.
- [[variable-speed-limits-and-e2-detectors]] — the underlying SUMO concepts (E2 detector schema, the timeLoss-confounding gotcha, and the verified flow-smoothing-without-throughput-gain finding).
