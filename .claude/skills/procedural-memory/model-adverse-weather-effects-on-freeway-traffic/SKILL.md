---
name: model-adverse-weather-effects-on-freeway-traffic
description: Use this skill when the user wants to model adverse weather (wet/rain, snow/ice) effects on SUMO freeway traffic — capacity, travel time, and safety — as opposed to dry-condition scenarios covered by other skills. Covers representing weather severity via progressive vType car-following parameters (speedFactor, minGap, tau, accel, decel, sigma), the critical finding that SUMO's native lane `friction` attribute is NOT honored by the default Krauss car-following model (weather must be modeled through vType params instead), a demand design that separates saturated-capacity measurement from undersaturated efficiency measurement, the SSM device for safety quantification, and an underadapted-driver isolation technique for conditional safety findings. Trigger on mentions of weather effects, rain/wet road, snow/ice, road friction, adverse conditions, or weather-adjusted driving behavior.
---

# Model Adverse Weather Effects on Freeway Traffic

Models the effect of weather severity (dry/wet/snow) on freeway capacity, efficiency, and safety by adjusting vehicle car-following behavior — reusing `build-macroscopic-fundamental-diagram`'s verified lane-drop bottleneck and E1/E2 detector pattern, and `analyze-intersection-safety-with-ssm`'s SSM device configuration.

## Critical finding: SUMO's lane `friction` attribute is not honored by the default car-following model

**SUMO's native per-lane `friction` attribute (settable in plain-XML edge/lane definitions, compiled through by netconvert) has NO effect on vehicle behavior under the default Krauss car-following model — it is silently ignored.** Verified directly: a scenario with `friction=0.4` (snow-level) but otherwise-dry vType parameters produced output byte-identical to the pure dry baseline; a scenario with default `friction=1.0` but snow-level vType parameters produced output byte-identical to the full snow scenario. **Model weather severity through vType car-following parameters, not the lane `friction` attribute** — despite its name suggesting it should be the mechanism.

**Always genuinely test this rather than assume an answer** — run both an isolation scenario (severity-attribute-only, default behavioral params) and its complement (default attribute, severity-level behavioral params) and diff their raw output against the two pure baselines. This is a required verification step, not an optional nicety — the finding could change in a future SUMO version or with a different car-following model, and asserting the mechanism without testing it risks persisting a stale or version-specific claim as fact.

## Representing weather severity via vType parameters

Progressively adjust car-following parameters from dry to snow — verified example values:

```python
VTYPES = {
    "dry":  dict(speedFactor=1.0,  minGap=2.5, tau=1.0, accel=2.6, decel=4.5, sigma=0.5),
    "wet":  dict(speedFactor=0.85, minGap=3.5, tau=1.4, accel=2.0, decel=3.5, sigma=0.6),
    "snow": dict(speedFactor=0.65, minGap=5.0, tau=2.0, accel=1.3, decel=2.5, sigma=0.7),
}
```

Lower `speedFactor` (reduced desired speed), higher `minGap`/`tau` (larger following gaps), lower `accel`/`decel` (reduced acceleration and braking capability), higher `sigma` (more driver imperfection) — each moving monotonically more conservative from dry to snow.

## Separate capacity measurement (saturated) from efficiency measurement (undersaturated)

**A single demand level cannot cleanly answer both "what's the bottleneck's discharge capacity under each condition?" and "how does travel time/delay change for completed vehicles?"** — a heavily oversaturated demand needed to reach the capacity regime will strand many vehicles mid-network, confounding travel-time/delay statistics computed only over vehicles that happened to complete. Run two demand levels per weather scenario: a sustained high-insertion-rate sweep for the capacity measurement (sum per-lane downstream E1 flow in the saturated window), and a separate, clearly-labeled moderate/undersaturated demand level for the speed/travel-time/delay comparison. Disclose this substitution explicitly in the findings — it's legitimate methodology, not a silent inconsistency, as long as it's stated.

## Safety: a counter-intuitive result requires an isolation follow-up, not suppression

**Enabling the SSM device across weather scenarios with full behavioral adaptation can show a counter-intuitive result: snow appearing *safer* than dry, because increased following gaps and reduced speed dominate the SSM's conflict/TTC calculation.** This is a real result, not an error — caution genuinely can outweigh reduced friction's raw danger when drivers fully adapt. To isolate the danger the task actually asks about (what happens when drivers *don't* adapt), construct an additional scenario with severity-level braking/deceleration capability but dry-level following gaps ("underadapted"). Verified: this isolation scenario showed a 28x increase in SSM-logged conflicts and a much lower minimum TTC relative to the fully-adapted severity scenario — demonstrating the real physical mechanism (longer stopping distances under-compensated by following gap) that a naive full-adaptation comparison would otherwise mask. Report the counter-intuitive full-adaptation result honestly, then use the isolation scenario to surface the genuine conditional danger, rather than omitting the inconvenient result.

## Verified findings

On a genuine 3-to-2 lane-drop freeway bottleneck: discharge capacity fell from 4044 veh/h (dry) to 2982 veh/h (wet, -26.3%) to 2034 veh/h (snow, -49.7%); mean speed fell from 109.3 to 87.7 to 61.6 km/h with corresponding travel-time and delay increases, all measured at a moderate undersaturated demand level; and SSM-measured safety showed the full-adaptation-vs-underadaptation contrast described above.

## Gotchas

- **The lane `friction` attribute does nothing under the default Krauss model** — always verify this on your installed SUMO version rather than assuming it; model weather via vType parameters instead.
- **Don't use the same (saturated) demand level for both capacity and efficiency metrics** — oversaturation confounds completed-vehicle travel-time statistics; use a separate moderate-demand run for efficiency, clearly disclosed.
- **A counter-intuitive safety result (e.g. "snow is safer") isn't necessarily wrong** — it can reflect genuine behavioral adaptation. Build an underadapted-driver isolation scenario to surface the conditional danger rather than discarding the counter-intuitive finding.

## Related

- `build-macroscopic-fundamental-diagram` — the verified lane-drop bottleneck and E1/E2 detector pattern this skill's network construction reuses directly.
- `analyze-intersection-safety-with-ssm` — the SSM device configuration and TTC/conflict-count interpretation this skill's safety analysis reuses.
- [[weather-friction-effects-on-capacity-and-safety]] — the underlying friction-mechanism finding, the verified capacity-drop percentages, and the conditional-safety/underadaptation finding.
