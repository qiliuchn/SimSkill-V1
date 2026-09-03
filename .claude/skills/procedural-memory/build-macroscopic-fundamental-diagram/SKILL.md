---
name: build-macroscopic-fundamental-diagram
description: Use this skill when the user wants to empirically construct a SUMO freeway corridor's macroscopic fundamental diagram (flow-density-speed relationship) via a demand sweep, or use E1 induction-loop detectors as a standalone measurement instrument (not embedded inside a controller). Covers building a verified fixed-capacity lane-drop bottleneck, defining E1 detectors and interpreting their output attributes, running a steady-state demand sweep from undersaturated to oversaturated, deriving flow/density/space-mean-speed from real detector data, and identifying capacity, critical density, the free-flow/congested branches, and the capacity-drop phenomenon. Trigger on mentions of fundamental diagram, flow-density-speed, MFD, E1 detector, induction loop, or capacity/critical density.
---

# Build a Macroscopic Fundamental Diagram

Empirically constructs the flow-density-speed macroscopic fundamental diagram (MFD) — the central relationship of traffic-flow theory — from a demand sweep on a SUMO freeway bottleneck, using E1 induction-loop detectors as a standalone measurement instrument. This is SimSkill's only skill treating E1 detectors as a first-class measurement tool in their own right; every other use of E1 loops in memory (`implement-alinea-ramp-metering`, `implement-variable-speed-limits`, `control-signals-with-actuated-tls`) embeds them inside a live controller.

## Building a bottleneck to reveal both branches of the diagram

An unconstrained corridor with no bottleneck only ever traces the free-flow branch — flow keeps rising with demand up to whatever the network's actual capacity is, with no way to observe congestion at a specific measurement point. **A genuine fixed-capacity bottleneck downstream of the measurement station is what makes the congested branch observable**: a lane drop (e.g. 3→1 lanes) reduces downstream throughput below what the upstream section could otherwise carry, so once demand exceeds that reduced capacity, a queue forms and backs up over the upstream detector station — exactly the mechanism that produces high-density, low-speed congested points. Verify the lane drop is real from the compiled network's connections (see `model-vclass-lane-permissions`/`implement-variable-speed-limits` for the verification pattern), and place the measurement station **upstream** of the drop, not at or past it.

## E1 detector output as a standalone measurement instrument

```xml
<inductionLoop id="mfd_l0" lane="main_0" pos="1700" period="60" file="e1_mfd.xml"/>
```

One detector per lane at the same longitudinal position forms a measurement "station." Key output attributes per `<interval>`: `nVehContrib` (vehicle count that interval), `flow` (veh/h, already normalized), `occupancy` (% of time a vehicle was over the loop), `harmonicMeanSpeed` (m/s, the correct averaging for space-mean speed), and `length` (mean vehicle length that interval). Verify the exact attribute set against real E1 output for the SUMO version in use — don't assume a fixed schema across versions.

## Deriving flow, density, and space-mean speed

Standard traffic-flow-theory quantities, computed per lane then summed/combined across the station:

- **Flow** `q_i = nVehContrib_i / duration * 3600` (veh/h), summed across lanes for the station total.
- **Space-mean speed** — use the **harmonic** mean, not arithmetic: `v_i = n_i / sum(n_i / speed_i)` per lane, combined station-wide as `v_space = n_total / sum_over_lanes(n_i / v_i)`. This correctly weights by how long each vehicle actually occupies the road, which matters especially under congestion.
- **Density** — compute **two independent estimators** and cross-check them: `k_qv = q / v_space` (the fundamental relation `q = k·v`), and `k_occ = 10 * occupancy% / mean_vehicle_length` from the E1 occupancy attribute directly. They should agree closely in free flow and can diverge more (10%+) under congestion — report both, don't rely on just one.

Compute density **per lane** before summing, not from station-aggregate flow and speed — this correctly handles uneven lane loading (free flow tends to favor one lane; congestion spreads vehicles across all lanes).

## The demand sweep

Run the identical network and detector setup at a series of steady demand levels spanning well below to well above the bottleneck's expected capacity (e.g. 15+ points from ~20% to ~2-3x the theoretical capacity), each run long enough to reach a genuine steady state before the measurement window starts (discard an initial warmup period, e.g. the first half of the run). Classify each run's regime (free vs. congested) from its measured space-mean speed against a threshold (e.g. below 60 km/h on a 120 km/h freeway = congested) — don't assume the regime from the demand level alone, since the actual breakpoint (capacity) is what the sweep is measuring.

```bash
python scripts/build_fundamental_diagram.py \
    --runs-dir outputs --rates 600,1200,1500,1800,2000,2200,2500,2600,2700,2800,2900,3000,3500,4000,5000,6000,7000 \
    --run-dir-template "q{rate}" --e1-filename e1_mfd.xml \
    --warmup 1800 --end 3600 --free-speed-threshold-kmh 60 \
    --single-lane-speed-ms 33.33 --veh-length-m 5.0 --min-gap-m 2.5 --tau-s 1.0 --n-downstream-lanes 1 \
    --out-csv mfd_points.csv --out-json fd_summary.json --plots-dir plots/
```

Produces the three classic FD plots (flow-vs-density, speed-vs-density, flow-vs-speed) plus a summary of capacity, critical density, free-flow speed, congested discharge flow, and jam-density estimates.

## Sanity-checking measured capacity against theory

Compute the theoretical maximum single-lane capacity from the vType's car-following parameters: `v_free / (v_free * tau + length + minGap) * 3600` (vehicles/hour for one lane at free-flow speed, saturated headway). **Both the measured pre-breakdown capacity and the congested discharge flow should fall below this bound**, scaled by the number of downstream bottleneck lanes — if either exceeds it, that's a red flag that the measurement station isn't actually downstream-bottleneck-limited, or something else is wrong with the setup.

## Jam density: measured vs. theoretical, and why extrapolation is unreliable

A two-point linear extrapolation of the congested branch to `q=0` (using the backward-wave slope between the capacity point and the mean congested point) is **ill-conditioned when the congested branch is a tight cluster rather than a real spread toward standstill** — a shallow, noisy queue-discharge condition doesn't actually sample near jam density, so extrapolating far beyond the observed range overshoots the physical limit. Report a physically-grounded standstill estimate instead (`1000 / (vehicle_length + minGap)` per lane, times the number of lanes actually jamming) alongside the extrapolated figure explicitly labeled as unreliable — don't present an extrapolated jam density as a confident measurement.

## What a clean fundamental diagram looks like

Measured on a 3-lane freeway with a 3→1 lane drop, 17-point demand sweep 600-7000 veh/h: a free-flow branch where flow tracked demand 1:1 up to a capacity of 2500 veh/h at ~21 veh/km critical density and ~117 km/h free-flow speed, followed by a congested branch (once demand exceeded capacity) where speed collapsed to ~10 km/h and discharge flow settled at a reduced ~1938 veh/h — a ~22% capacity drop between pre-breakdown flow and queued discharge, the well-documented capacity-drop phenomenon. Both figures fell safely below the theoretical single-lane bound, and the congested-branch runs showed zero teleports/collisions, confirming genuine physical queueing rather than a simulation artifact.

## Gotchas

- **A congested branch requires a genuine downstream bottleneck** — an unconstrained network only ever traces the free-flow branch regardless of how high demand goes.
- **Use harmonic mean speed, not arithmetic mean**, for space-mean speed — E1's `harmonicMeanSpeed` attribute is already the correct one to use.
- **Compute density per lane before summing**, not from station-aggregate flow/speed, to correctly handle uneven lane loading between free-flow and congested regimes.
- **Don't extrapolate jam density from a tight congested cluster** — report the physically-grounded standstill estimate and flag any extrapolation as unreliable.
- **Verify congestion is physical, not a teleport artifact** — check for zero teleports/collisions in oversaturated runs before trusting the congested branch's data.

## Related

- `implement-alinea-ramp-metering`, `implement-variable-speed-limits` — SimSkill's other freeway-scenario skills; the bottleneck-verification and E1-detector-authoring patterns this skill builds on.
- `analyze-simulation-outputs`, `visualize-trajectories-and-timeseries` — general analysis/plotting skills this one specializes for the multi-run demand-sweep case.
- [[macroscopic-fundamental-diagram]] — the underlying traffic-flow-theory concepts (flow/density/speed relations, capacity drop, jam density) and the verified sweep findings.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — reuses this skill's E1-loop flow/density/space-mean-speed measurement methodology, extended to quantify the specific bias of reading raw spot speed instead of the harmonic (space-mean) speed this skill establishes as correct.
- `validate-kinematic-wave-theory-across-car-following-models` — upgrades this skill's open-road E1-occupancy density estimate to an exact, controlled closed-ring density measurement for link-scale fundamental-diagram fitting across multiple car-following models, and found the ~22% capacity drop this skill documents is largely, but not exclusively, a lane-changing/merge phenomenon.
- `characterize-pedestrian-flow-and-striping-model-artifacts` — adapts this skill's demand-sweep/flow-density-speed methodology to pedestrians via FCD person records (no induction-loop equivalent exists for persons), and found the pedestrian analog's apparent below-benchmark capacity is a lateral stripe-quantization artifact, not a core dynamics flaw.
