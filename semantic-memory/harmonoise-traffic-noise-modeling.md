---
summary: SUMO's Harmonoise model computes per-vehicle, per-edge traffic noise in dB(A), collectible via edgeData type="harmonoise" or TraCI's getNoiseEmission, but decibels must be time-averaged on an acoustic-intensity basis (10^(L/10) mean, then 10*log10 back) never arithmetically; verified findings show noise rises ~3 dB per volume doubling (logarithmic, not linear) and a small heavy-vehicle fraction disproportionately raises the corridor level.
keywords:
  - harmonoise
  - traffic-noise
  - dB(A)
  - noise-emission
  - intensity-averaging
  - edgeData-harmonoise
created: 2026-07-28T09:45:00
last_updated: 2026-07-28T09:45:00
sources:
  - "[[episodic-memory/2026-07-28_09-22-24/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_09-22-24/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Noise_Emissions_Calculation.html
related_pages:
  - "[[vehicle-emissions-modeling]]"
  - "[[sumo-output-files]]"
  - "[[spatial-congestion-heatmap-with-plot-net-dump]]"
related_skills:
  - analyze-traffic-noise-with-harmonoise
  - simulate-fleet-emissions
  - visualize-network-congestion-heatmap
related_skills_for_graph_view:
  - "[[analyze-traffic-noise-with-harmonoise]]"
  - "[[simulate-fleet-emissions]]"
  - "[[visualize-network-congestion-heatmap]]"
---

# Harmonoise Traffic Noise Modeling

SUMO's Harmonoise model computes traffic noise emission in dB(A) per vehicle, aggregable per edge — a logarithmic, energy-based metric fundamentally distinct from SUMO's additive pollutant-emission totals covered in [[vehicle-emissions-modeling]] (CO2/NOx/PMx sum linearly across vehicles; noise does not).

## Collection: edgeData directly supports it

`edgeData type="harmonoise"` is a real, directly-supported SUMO meandata output type (verified against an actual installed SUMO 1.27.1), producing a genuinely energy-averaged per-edge `noise` attribute with no custom code required:

```xml
<edgeData id="noise" type="harmonoise" file="meandata_noise.xml" freq="3600"/>
```

A TraCI cross-check (`traci.edge.getNoiseEmission(edge_id)`, sampled every step) is also available and was verified to agree with the meandata output within ≤0.4 dB across every edge/scenario combination in a real test — either method works; using both gives an independent cross-check.

## The critical rule: decibels never average arithmetically

**Time-averaging dB(A) samples requires converting to linear acoustic intensity first.** The correct procedure: `I = 10^(L/10)` for each sample, arithmetic-average the intensities, then `Leq = 10*log10(mean(I))` to convert back. A naive arithmetic mean of the dB values themselves is always wrong and always understates the true energy-averaged level (a direct consequence of Jensen's inequality applied to the concave `log` transform).

**Verified magnitude of the error**: on a real corridor, the gap between correct energy-averaged levels and a naive arithmetic mean of the same samples was 1.4–3.0 dB corridor-wide, reaching 5.8 dB on the single worst edge during bursty vehicle occupancy — not a rounding-level nuance, but a large enough error to materially mis-state acoustic exposure. Anyone hand-rolling a noise time-series average (rather than using SUMO's own `edgeData type="harmonoise"` meandata, which already averages correctly) must implement the intensity-based conversion explicitly.

## Verified finding: noise scales logarithmically with volume, ~3 dB per doubling

Measured on a real 2 km, 2-lane, 50 km/h arterial under a car-only volume sweep: 300→600 veh/h produced +3.01 dB, 600→1200 veh/h produced +3.02 dB, and the full 4x range produced +6.03 dB — matching the theoretical `10*log10(volume_ratio)` law (3.01 dB and 6.02 dB respectively) almost exactly. **Traffic noise is fundamentally sub-linear/logarithmic in volume: doubling the traffic does not double the noise level**, a common source of intuition failure when reasoning about noise-mitigation measures aimed at reducing volume.

## Verified finding: a small heavy-vehicle fraction produces a disproportionate noise penalty

At an identical total volume (600 veh/h), replacing 10% of the fleet (by vehicle count) with heavy-duty vehicles raised the corridor's energy-averaged noise level by +3.39 dB relative to the all-car case — and that mixed scenario was even slightly louder than an all-car scenario with **double** the total volume. A small truck-fraction increase can outweigh a much larger increase in car volume alone, a directly relevant finding for freight-routing or truck-curfew noise-mitigation analysis.

See the `analyze-traffic-noise-with-harmonoise` skill for the full collection, demand-design, and heatmap-rendering workflow.
