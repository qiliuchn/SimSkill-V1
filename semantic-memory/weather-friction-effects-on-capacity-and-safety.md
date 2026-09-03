---
summary: "Adverse weather modeled via progressive vType car-following parameters (not SUMO's native lane friction attribute, which the default Krauss model ignores entirely) reduces freeway bottleneck discharge capacity monotonically — verified 26.3% (wet) and 49.7% (snow) drops relative to dry — and degrades safety only conditionally: fully-adapted driving (larger gaps, lower speed) can make snow appear safer than dry by SSM measures, while an underadapted-driver isolation scenario (severity braking, dry-level gaps) shows a 28x conflict increase, revealing the genuine stopping-distance danger."
keywords:
  - weather-effects
  - road-friction
  - lane-friction-attribute
  - capacity-drop
  - weather-adjusted-car-following
created: 2026-07-28T16:05:00
last_updated: 2026-07-28T16:05:00
sources:
  - "[[episodic-memory/2026-07-28_15-37-07/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_15-37-07/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[surrogate-safety-measures]]"
  - "[[opposite-direction-overtaking-mechanics]]"
related_skills:
  - model-adverse-weather-effects-on-freeway-traffic
  - build-macroscopic-fundamental-diagram
  - analyze-intersection-safety-with-ssm
related_skills_for_graph_view:
  - "[[model-adverse-weather-effects-on-freeway-traffic]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[analyze-intersection-safety-with-ssm]]"
---

# Weather/Friction Effects on Capacity and Safety

Adverse weather (rain, snow/ice) can be modeled in SUMO by adjusting vehicle car-following parameters to represent progressively reduced road grip — but not, as the name might suggest, via SUMO's native per-lane `friction` attribute.

## SUMO's lane `friction` attribute is not honored by the default Krauss model

**Verified directly: SUMO's per-lane `friction` XML attribute (settable in plain-XML edge/lane definitions and compiled through correctly by netconvert) has zero effect on vehicle behavior under the default Krauss car-following model.** A test scenario with `friction=0.4` (snow-level) applied to the network, but otherwise-default (dry-level) vType car-following parameters, produced simulation output substantively byte-identical to a pure dry baseline. Conversely, a scenario with default `friction=1.0` but snow-level vType parameters produced output byte-identical to a full snow scenario using both mechanisms together. **The `friction` attribute is genuinely compiled into the network (confirmed present in the compiled `.net.xml`'s lane elements) but simply never consulted by the car-following model that determines vehicle acceleration/deceleration/gap-keeping.** Anyone modeling weather in SUMO must use vType car-following parameter adjustments — the `friction` attribute alone will not produce any behavioral effect, regardless of how physically appropriate the name sounds.

## Modeling severity progressively via vType parameters

Effective weather modeling reduces `speedFactor` (desired speed), increases `minGap` and `tau` (following gap and time headway), reduces `accel`/`decel` (acceleration and braking capability), and increases `sigma` (driver imperfection) — moving monotonically from dry through wet to snow/ice.

## Verified capacity impact

On a genuine 3-to-2 lane-drop freeway bottleneck under an oversaturating demand sweep, sustained discharge capacity (summed downstream per-lane E1 flow) fell from 4044 veh/h (dry) to 2982 veh/h (wet, a 26.3% drop) to 2034 veh/h (snow, a 49.7% drop) — capacity loss under weather is substantial and roughly doubles going from wet to snow-level severity, not merely incremental.

## Safety is conditional on behavioral adaptation, not a simple function of friction alone

**A naive comparison of SSM-measured conflict frequency and minimum time-to-collision across weather scenarios, each with fully weather-adapted driving behavior, can show a counter-intuitive result: snow appearing *safer* than dry.** This happens because the increased following gaps and reduced speeds that model appropriate weather-adapted driving genuinely reduce conflict frequency more than the reduced braking capability increases it — caution dominates when drivers actually adapt. **The genuine danger of low friction only appears when driver behavior fails to adapt to match it.** Verified via an isolation scenario using snow-level braking/deceleration capability but dry-level following gaps ("underadapted"): this produced a 28x increase in SSM-logged conflicts and a substantially lower minimum TTC relative to the fully-adapted snow scenario — directly demonstrating the real physical mechanism (longer stopping distances, under-compensated by an insufficient following gap) that a naive full-adaptation-only comparison would otherwise mask entirely. When a weather/safety comparison produces a counter-intuitive result, this kind of isolation scenario is the right way to surface the underlying conditional risk rather than discarding or reversing the counter-intuitive finding.

## Separating capacity measurement from efficiency measurement

A demand level high enough to reach a bottleneck's saturated discharge-capacity regime will strand many vehicles mid-network under degraded (wet/snow) car-following parameters, confounding travel-time/delay statistics computed only over completed vehicles. Use a sustained high-insertion-rate demand for capacity measurement, and a separate, clearly-disclosed moderate/undersaturated demand level for speed/travel-time/delay comparison.

See the `model-adverse-weather-effects-on-freeway-traffic` skill for the full network, vType, mechanism-verification, and safety-isolation workflow.
