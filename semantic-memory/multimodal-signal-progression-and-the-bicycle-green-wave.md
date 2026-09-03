---
summary: SUMO's default lane model makes a dedicated bike lane measure as WORSE for cyclists than mixed traffic (86.2 vs 49.6 s/km delay) purely because it cannot represent in-lane overtaking of a single-file bike lane — a measurement artifact, not a real finding, that is resolved by enabling the sublane model (delay drops 57% to 36.8 s/km); separately, a bicycle green wave realizes only 39.9% of its analytic bandwidth versus 101.7% for cars, is statistically indistinguishable from just running the car-tuned wave (p=0.059), and pooling both directions of a one-way-tuned plan can hide a net bicycle-delay increase even when the designed direction genuinely improves; cycle length is roughly 6x more effective than offset tuning for bicycles, and platoon coherence survives only about 2-3 signals (per-intersection survival factor 0.714 for bicycles vs 0.871 for cars).
keywords:
  - multimodal-signal-progression
  - bicycle-green-wave
  - dedicated-bike-lane
  - sublane-model
  - bandwidth-realization
  - platoon-coherence
  - design-speed-tolerance
created: 2026-08-06T02:00:00
last_updated: 2026-08-07T05:39:34
sources:
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/artifact_check.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/v6_notmodeled.json]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/bandwidth_verification.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/bandwidth_paired.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/oneway_agg.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/design_speed_tolerance.json]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/platoon_survival.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/cycle_agg.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/pareto.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/asym_agg.csv]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/v5_rightturn.json]]"
  - "[[episodic-memory/2026-08-06_02-00-00/outputs/data/v1_freespeed.json]]"
related_pages:
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[dedicated-bicycle-lanes-and-mode-share]]"
  - "[[sublane-model-and-lane-filtering]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[protected-bicycle-intersection-design-and-right-hook-mechanics]]"
related_skills:
  - design-multimodal-signal-progression-for-bicycles-and-cars
  - design-arterial-signal-progression-and-verify-bandwidth
  - model-dedicated-bicycle-lane-infrastructure
  - model-vclass-lane-permissions
  - quantify-sumo-run-to-run-variability
  - evaluate-protected-bicycle-intersection-design
related_skills_for_graph_view:
  - "[[design-multimodal-signal-progression-for-bicycles-and-cars]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[model-dedicated-bicycle-lane-infrastructure]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[evaluate-protected-bicycle-intersection-design]]"
---

# Multimodal Signal Progression and the Bicycle Green Wave

Every prior arterial-progression finding in memory treats coordination as
a single-mode (car) design problem. This page treats progression speed as
a genuine multimodal conflict — cyclists at roughly 4 m/s and cars at
roughly 12 m/s cannot both ride the same band — and finds that a bicycle
green wave is far less deliverable than the car case would suggest, with
one especially consequential measurement trap along the way.

## The critical measurement trap: a dedicated bike lane can look worse than mixed traffic

Identical demand, identical route lengths, only the lane model toggled
(`--lateral-resolution`):

| geometry | lane model | bicycle delay | car delay |
|---|---|---|---|
| dedicated lane | default | **86.2 s/km** | 44.7 s/km |
| dedicated lane | sublane | **36.8 s/km** | 45.0 s/km |
| mixed traffic | default | 49.6 s/km | 91.2 s/km |
| mixed traffic | sublane | 37.4 s/km | 50.1 s/km |

Under SUMO's **default** lane model, giving bicycles their own dedicated
lane makes their delay nearly double relative to mixed traffic — a
nonsensical result. Enabling the **sublane** model cuts dedicated-lane
bicycle delay by 57% (86.2 → 36.8 s/km) and restores the expected
ordering, while car delay in the same geometry barely changes (44.7 →
45.0 s/km), confirming the effect is entirely internal to the bike lane.
Root cause, cross-verified from lane-change event data: under the default
model in a single-file dedicated lane, bicycles show **0 overtaking
events out of 1326+ opportunities**; sublane produces genuine overtaking
(134/1485 events, 5337 side-by-side pairs). **Any SUMO bicycle-lane study
at non-trivial volume run under the default lane model risks getting the
bicycle-side conclusion qualitatively backwards.** Always enable sublane
for a dedicated single bike lane and verify overtaking is actually
occurring before trusting a delay comparison.

## What SUMO does and does not model for bicycles

Verified before any analysis: realised speed follows `min(desiredMaxSpeed,
edgeSpeed) × speedFactor`, capped by `maxSpeed`; bicycle default
`desiredMaxSpeed` ≈ 5.56 m/s; `speedFactor="1.0"` is **not** deterministic
— the default `speedDev=0.1` still applies even with car-following
`sigma=0`. Bicycles stayed on a dedicated lane 100.000% of FCD samples;
in mixed traffic they used the rightmost lane 82.6% of the time. Red
compliance was verified perfect (0 entries during red out of thousands
checked) once junction entry was detected from FCD lane identity rather
than an x-position threshold (a queued vehicle's front legitimately rests
at the stop line, which a naive threshold check flags as a violation).
Right-turning vehicles genuinely yield to bicycles at junctions; isolating
the *attributable* delay cost of this interaction requires a
difference-in-differences design against a matched control cohort (e.g.
left-turners), because naively removing bicycles from demand also removes
system-wide volume and overstates the effect. **SUMO does not model at
all**: riding two abreast, a bike box / advanced stop line (the closest
representable analogue, a leading bicycle green interval, only reproduces
departure order, not storage geometry), or — without the sublane model —
overtaking within a single dedicated bike lane.

## Bandwidth realization is asymmetric between a fast and a slow mode

Cars realized **101.7%** of their analytic progression band (measured
zero-stop fraction relative to band-over-cycle ratio); bicycles realized
only **39.9%** of theirs, in the identical study at the same demand and
geometry. A bicycle-tuned progression's benefit to bicycles was **not
statistically distinguishable from simply running the car-tuned
progression instead** (p=0.059, CRN-paired), while tuning for bicycles
cost cars their entire measured benefit (their realized band dropped from
101.7% to 0%). A slower, more speed-dispersed mode does not benefit
proportionally from a band sized the same way as a fast, tightly
distributed mode's band.

## Pooling both directions can hide a real net loss

A one-way-tuned progression (offsets computed for the eastbound direction
only) improved eastbound bicycle delay by 6.81 s/km, but worsened
westbound bicycle delay by 13.67 s/km — a net **+3.26 s/km increase in
pooled bicycle delay**. Bicycles were worse off, averaged across both
directions, than with no coordination at all, despite the plan
delivering a real, statistically significant eastbound improvement.
Always report both directions separately before pooling.

## The design-speed tolerance window scales as 1/v²

The exact interval-algebra bound on how far a chosen design speed can
deviate from the calibrated stream speed while still delivering useful
bandwidth, `|1/v_d − 1/v| ≤ g_T / ((n−1)·L)`, is a pure geometric
identity independent of mode. Evaluated at this study's geometry:
bicycles' usable window was **[3.60, 4.30] m/s (±9.0% relative)**; cars'
was **[9.68, 17.40] m/s (±31.0% relative)** — roughly 11× wider in
absolute speed terms, but only about 3.4× wider relative to the base
speed. State which tolerance ratio is meant; they give substantially
different pictures. Measured consequence: mistuning a bicycle
progression's design speed by +13% relative to the calibrated stream
speed degraded 5-intersection platoon survival to 0.0746 — **worse than
running no coordination at all (0.0882)**. Always calibrate design speed
from measured *stream* speed (paced by the slowest riders), not an
individual free-flow speed or a plausible nominal value.

## Platoon coherence survives roughly 2-3 signals, not the whole corridor

Measured per-intersection survival factor (fraction of a platoon that has
not yet had a full stop, matched wave conditions at a realistic
speed-dispersion level): **cars 0.871**, **bicycles 0.714**. Compounding
across a corridor: over 5 intersections cars retained about half the
platoon coherent (0.520) while bicycles retained only about a fifth
(0.204) under their own matched wave — and only 0.048 by the fifth
intersection under no coordination at all. A bicycle green wave is a
real, worthwhile intervention for the first 2-3 signals and delivers
rapidly diminishing value beyond that.

## Cycle length is a far stronger lever than offset tuning for a slow mode

At fixed cycle length, the best offset choice improved bicycle delay by
only 1.67 s/km over no coordination. Shortening the cycle alone (at
matched arterial green ratio) improved bicycle delay by 10.10 s/km —
roughly 6× the best offset effect — at no cost to the cross street at
this study's demand level. Across an 80-plan Pareto search over both
delay dimensions, **every non-dominated plan was a shorter-cycle plan;
not one baseline-cycle offset plan (one-way-tuned, two-way MAXBAND, or
directionally asymmetric) reached the frontier**. For two-way bicycle
progression, hitting the resonant cycle length `C = 2L / (n · v_bike)`
(predicted and confirmed at 102/68/51 s for this geometry) can make even
a zero-offset plan bandwidth-optimal. Sweep cycle length before spending
effort on offset optimization when bicycles are a design priority.

## Directional-asymmetric offsets split the benefit — but only cars take their share

A directionally-asymmetric plan delivered the intended trade for cars
(favored-direction delay improved 14.4–14.6 s/km, checked in both
assignment directions) but bicycles captured only a small fraction of
their favored-direction share (1.2 and 0.5 s/km respectively). This is a
real tool for balancing car-direction priorities, not a reliable way to
deliver comparable bicycle benefit even when explicitly designed to.

## Gotchas

- Enable the sublane model for any dedicated single bike lane carrying
  non-trivial volume, and verify overtaking from lane-change event data
  before trusting a delay comparison.
- Set `speedDev` explicitly for bicycles — `speedFactor="1.0"` does not
  eliminate speed dispersion.
- Detect junction/red-light entry from FCD lane identity, not an
  x-position threshold.
- Report each direction of a one-way-tuned progression separately before
  pooling.
- Calibrate design speed from measured stream speed, not a nominal or
  individual free-flow value.
- Sweep cycle length before offsets when optimizing for a slow, dispersed
  mode.

See `design-multimodal-signal-progression-for-bicycles-and-cars` for the
full build/verification/optimization workflow, and
[[arterial-signal-progression-resonance-bandwidth-and-delay]] for the
single-mode offset-algebra and resonance methodology this page extends
to a second, slower mode.
