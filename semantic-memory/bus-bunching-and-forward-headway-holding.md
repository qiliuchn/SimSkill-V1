---
summary: Bus bunching in SUMO emerges from a real, verifiable feedback loop — dwell time scales with boarding load (near-perfectly linear given a fixed boardingDuration), so a delayed bus meets a larger crowd, dwells longer, falls further behind, and its follower catches up, producing a rising headway coefficient of variation and buses pairing up; a forward-headway-only TraCI holding controller (holds early buses, never late ones) measurably suppresses this — verified 22% CV reduction, pairing eliminated entirely, 34% lower mean passenger wait — at a real, quantified dwell-time cost, with one residual large gap persisting as an inherent limitation of forward-only holding; a binding personCapacity, however, truncates the whole feedback loop (dwell-on-crowd slope +1.005 -> -0.033 s/pax), making a crowded line's headways look 35% MORE regular while passenger time rises 80%, and flipping holding control's passenger benefit to a cost.
keywords:
  - bus-bunching
  - headway-instability
  - holding-control
  - transit-operations
  - headway-coefficient-of-variation
  - capacity-truncation
  - personCapacity
created: 2026-07-30T09:00:00
last_updated: 2026-08-11T19:05:00
sources:
  - "[[episodic-memory/2026-07-29_16-08-17/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_16-08-17/outputs/findings.md]]"
  - "[[episodic-memory/2026-07-29_16-08-17/attempts/attempt-1/critic-agent-feedback.json]]"
  - "[[episodic-memory/2026-08-11_18-30-39/summary.md]]"
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[phantom-traffic-jams-and-single-av-stabilization]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
related_skills:
  - demonstrate-and-control-bus-bunching
  - simulate-multimodal-transit
  - simulate-taxi-and-drt-dispatch
  - design-bus-stop-placement-type-and-spacing
  - model-capacity-constrained-transit-passenger-loading
related_skills_for_graph_view:
  - "[[demonstrate-and-control-bus-bunching]]"
  - "[[simulate-multimodal-transit]]"
  - "[[simulate-taxi-and-drt-dispatch]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[model-capacity-constrained-transit-passenger-loading]]"
---

# Bus Bunching and Forward-Headway Holding

Bus bunching — the tendency of buses on a route to pair up rather than maintain even spacing — is a genuine, reproducible emergent instability in SUMO, driven by a real feedback loop rather than an artifact of the simulation.

## The feedback mechanism: dwell time scales with boarding load

With a realistic per-passenger `boardingDuration` on the bus vType, dwell time at a stop is proportional to the number of passengers boarding. A bus that falls even slightly behind schedule arrives at each subsequent stop to find a larger accumulated crowd (more time has passed since the last bus served that stop), so it dwells longer, falling further behind — while the following bus, encountering a thinned-out crowd, catches up. Verified directly: dwell time vs. passengers boarded+alighted showed a near-perfectly linear correlation (Pearson r ≈ 1.000, consistent with the fixed `boardingDuration` per passenger), confirming this is the actual causal mechanism, not merely an associated symptom.

## The bunching signature

A genuinely bunching system shows two distinct, independently verifiable signatures from raw `--stop-output` data:

1. **Rising headway coefficient of variation (CV)** across successive laps at a reference stop — headway variability grows over time from an initially even start, rather than remaining stable.
2. **Bus pairing**: headways bifurcate into a near-zero cluster (buses running nearly back-to-back) and a large-gap cluster (the space vacated by the paired buses), rather than clustering around a single even value.

Verified on a real 6-bus loop scenario: pooled headway CV of 1.14, with roughly 18% of headways falling into the paired near-zero cluster (as low as 8 seconds apart) alongside gaps as large as 489 seconds.

## Forward-headway-only holding control

A standard mitigation: at each stop, compute a bus's headway to the preceding bus. If it's below a target even value, the bus is running early — hold it (extend its dwell) until the target headway is restored. **Critically, never hold a bus that is on-time or late** — holding an already-late bus would only worsen the instability it's meant to fix.

Verified effect on a real 6-bus loop scenario: pooled headway CV fell by 22% (1.142 → 0.889), bus pairing was **eliminated entirely** (17.6% → 0%), and mean passenger wait time fell by 34% (190.1s → 126.2s). This came at a real, quantified cost: mean dwell time rose 36% (26.8s → 36.4s), the direct cost of holding buses at stops. **One residual large gap persisted even under control** — because the controller structurally cannot speed up a late bus, forward-only holding cannot fully close a gap once one has opened; this is an inherent, disclosed limitation of the approach rather than an implementation defect.

## A binding vehicle capacity truncates the loop — and inverts both results above

Everything above assumes the bus can always absorb the crowd it meets. That assumption is doing more work than it appears: it is exactly what makes dwell an unbounded amplifier. Once `personCapacity` genuinely binds, a bus arriving full boards nobody, so the dwell-vs-load slope collapses (measured in [[transit-capacity-passenger-loading-and-pass-up-dynamics]]):

| arm | dwell-on-crowd slope (s/pax) | r |
|---|---|---|
| non-binding | +1.005 | +0.483 |
| non-binding, crowds 10–20 | **+1.995** (= the configured `boardingDuration`) | +0.827 |
| binding | **−0.033** | −0.056 |
| binding, bus arrives full | **−0.190** | −0.463 |

Two consequences reverse the operational reading of this page:

1. **A crowded line's headways look *better*, not worse.** From an identical dispatch perturbation, headway CV amplifies ×2.25 along a 10-stop corridor when capacity is non-binding but only ×1.20 when it binds (pooled 0.338 vs 0.219, and **zero** paired buses under binding capacity) — while total passenger time is +80.5% and p90 wait quintuples. The pairing signature described above can be *absent precisely because service is failing*. Check whether capacity binds before reading a low CV as good service.
2. **Holding control's passenger benefit flips sign.** The 34%-lower-wait result above holds only when capacity does not bind. Under a binding capacity holding keeps its regularity gain (CV −48.4%) but wait rises +3.7%, pass-ups +4.3%, and total passenger time +3.8% (paired 95% CIs exclude 0) — the held bus arrives at the next stop to a crowd it cannot take, converting headway variance into refused boardings.

Note that *mean* dwell barely differs (16.55 vs 19.00 s in the loaded window); it is the variance-generating **slope** that is truncated, not dwell overall.

## Methodology discipline: confirm the phenomenon before building the fix

Genuine bunching should be verified in an uncontrolled baseline *before* building and evaluating a holding controller — assuming the phenomenon will appear with arbitrary parameters risks reporting "a control for something we never actually observed." If bunching doesn't emerge with an initial parameter choice, adjust demand rate, boarding duration, or fleet size until it genuinely does, and confirm via the CV-growth and pairing signatures directly from raw data before proceeding.

See the `demonstrate-and-control-bus-bunching` skill for the full network-construction, baseline-verification, and holding-controller workflow. The same dwell-scales-with-boarding-load mechanism was independently reproduced (R² = 0.986) in [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]'s endogenous-dwell corridor, where it also drives a per-stop dwell-growth progression along an uncontrolled corridor (bus time-space diagram) — the same underlying feedback documented here, observed without a holding controller in the loop.
