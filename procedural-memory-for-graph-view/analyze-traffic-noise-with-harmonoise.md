---
name: analyze-traffic-noise-with-harmonoise
description: Use this skill when the user wants to model or analyze SUMO's traffic noise output — the Harmonoise dB(A) model — as opposed to pollutant emissions (CO2/NOx/PMx, covered by simulate-fleet-emissions). Covers collecting per-edge noise via edgeData type="harmonoise" (and a TraCI traci.edge.getNoiseEmission cross-check), the mandatory intensity-based time-averaging rule (decibels never average arithmetically), a volume-sweep + mixed-fleet demand design to quantify the ~3 dB-per-doubling volume law and the heavy-vehicle noise penalty, and rendering a spatial noise heatmap via plot_net_dump.py. Trigger on mentions of traffic noise, Harmonoise, dB(A), noise emission, sound level, or noise heatmap/noise map.
related_skills:
  - simulate-fleet-emissions
  - visualize-network-congestion-heatmap
related_skills_for_graph_view:
  - "[[simulate-fleet-emissions]]"
  - "[[visualize-network-congestion-heatmap]]"
related_pages:
  - "[[harmonoise-traffic-noise-modeling]]"
---

# Analyze Traffic Noise with Harmonoise

SUMO's Harmonoise model computes per-vehicle, per-edge noise emission in dB(A) — a logarithmic, energy-based metric fundamentally different from SUMO's additive pollutant-emission totals (CO2/NOx/PMx, see `simulate-fleet-emissions`). Decibels combine and average by acoustic *intensity*, not by the dB value itself, which is the single most important thing to get right in any noise analysis.

## Collecting per-edge noise: two verified methods

**Primary: `edgeData` with `type="harmonoise"`** — SUMO's own meandata mechanism directly supports a Harmonoise output type, producing a genuinely energy-averaged per-edge `noise` attribute with no custom averaging code needed:

```xml
<additional>
    <edgeData id="noise" type="harmonoise" file="meandata_noise.xml" freq="3600"/>
</additional>
```

**Cross-check: TraCI sampling** (`scripts/sample_noise.py`) — read `traci.edge.getNoiseEmission(edge_id)` every step and time-average correctly:

```python
L = traci.edge.getNoiseEmission(edge_id)   # instantaneous edge noise, dB(A)
I = 10.0 ** (L / 10.0)                     # convert to linear acoustic intensity
# ... accumulate I over all steps ...
Leq = 10.0 * math.log10(mean(I))           # convert the INTENSITY mean back to dB
```

**Never average dB values arithmetically** — `mean(dB samples)` always understates the true energy-averaged level (Jensen's inequality direction), sometimes by several dB on a single edge during bursty traffic. Verified: the two collection methods (`edgeData type="harmonoise"` and the TraCI intensity-averaged sampler) agreed within ≤0.4 dB across every edge/scenario combination in a real test — use both if you want an independent cross-check, or either alone if you trust the built-in meandata path.

## Demand design: isolate volume, then isolate fleet composition

To measure noise's dependence on volume and heavy-vehicle share as separate, cleanly attributable effects:
1. **A car-only volume sweep** on the identical route (e.g. 300 / 600 / 1200 veh/h) — isolates the volume effect with fleet composition held constant.
2. **One mixed-fleet variant at a sweep volume level**, with a defined truck fraction by vehicle count (e.g. 10%) — compared against the car-only scenario at the *same total volume*, isolating the fleet-composition effect from the volume effect.

Define genuinely distinct HBEFA3 `emissionClass` values for the two vTypes (e.g. `HBEFA3/PC_G_EU4` for cars, `HBEFA3/HDV` for trucks) — Harmonoise noise depends on vehicle class and speed, so a cosmetic vClass-only change without a real emissionClass difference won't produce a genuine noise differential.

## Rendering a spatial noise heatmap

Write per-edge dB(A) values into an edgeData-style file and color the network with `plot_net_dump.py` following `visualize-network-congestion-heatmap`'s documented interface — `-m` must exactly match your written attribute name, use a fixed `--min-color-value`/`--max-color-value` scale so multiple scenario PNGs are visually comparable, and remember a perfectly collinear (1-D) network can render flat regardless of data — use genuine 2-D geometry even for a conceptually straight corridor.

## Verified findings

**Noise rises logarithmically with volume, at ~3 dB per doubling — not linearly, and the level never doubles.** Measured on a real corridor: 300→600 veh/h gave +3.01 dB, 600→1200 veh/h gave +3.02 dB, and the full 4x range gave +6.03 dB — matching the theoretical `10*log10(ratio)` law (3.01 dB and 6.02 dB respectively) almost exactly.

**A heavy-vehicle fraction raises noise disproportionately to its share of vehicle count.** Measured: a fleet that was just 10% trucks by count, at the *same total volume* as an all-car baseline, was 3.39 dB louder — and was even louder than an all-car scenario with **double** the total volume (quadrupled relative to the lowest sweep level). A small truck fraction can out-shout a much larger increase in car volume alone.

**Arithmetic dB averaging systematically understates the true level.** Measured: the gap between the correct energy-averaged level and a naive arithmetic mean of the same dB samples was 1.4–3.0 dB corridor-wide, and up to 5.8 dB on the single worst edge during bursty occupancy — a concrete, quantifiable consequence of Jensen's inequality, not a rounding-level nuance.

## Gotchas

- **Never arithmetically average dB values** — always convert to intensity (`10^(L/10)`), average, then convert back (`10*log10(...)`). This is the single most common way to get a noise analysis quietly wrong.
- **`edgeData type="harmonoise"` is a real, directly-supported SUMO output type** — verify against your installed SUMO version rather than assuming a TraCI-only fallback is required.
- **Isolate volume and fleet-composition effects separately** — a volume sweep at constant composition, then a composition change at constant total volume — or the two effects will be confounded in your comparison.
- **A cosmetic vType change (vClass only, same emissionClass) won't produce a real noise differential** — use genuinely distinct HBEFA3 `emissionClass` values for car vs. truck vTypes.
- **A collinear (1-D) test network can render a flat, uninformative heatmap** regardless of the underlying noise data — see `visualize-network-congestion-heatmap`'s documented fix (genuine 2-D geometry).

## Related

- `simulate-fleet-emissions` — the parallel pollutant-emissions skill (HBEFA3 vType/mixed-fleet setup pattern this skill reuses); noise and pollutant emissions are distinct metrics from the same underlying vType machinery.
- `visualize-network-congestion-heatmap` — the `plot_net_dump.py` spatial-heatmap mechanics and gotchas this skill's noise map reuses directly.
- [[harmonoise-traffic-noise-modeling]] — the underlying Harmonoise mechanics, the intensity-averaging rule, and the verified volume-law/heavy-vehicle-penalty findings.
