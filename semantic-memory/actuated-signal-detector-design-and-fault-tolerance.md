---
summary: Custom detector binding to a SUMO actuated tlLogic uses the syntax <param key="<laneID>" value="<detID>"/> (keyed by lane ID, not a prefixed form), verified via a manipulation-plus-negative-control protocol; detector-too-close (premature gap-out) and detector-too-far (blind-zone green-cuts) failure modes are wildly asymmetric in cost (roughly 100x), SUMO's default detector-gap placement was not beaten by hand-tuning at any tested demand level (an honest null result), a stuck-off detector fault looks artificially harmless under naive tripinfo-based delay due to survivorship censoring of never-inserted vehicles (correcting inverts the conclusion by roughly 10x), a stuck-on fault shows no partial gradation because SUMO ORs across a phase's controlling detectors, and setting maxDur to the Webster green split lets a stuck-on fault degrade gracefully to the fixed-time baseline at a real, demand-dependent healthy-state cost.
keywords:
  - actuated-signal-detector
  - detector-placement
  - detector-binding
  - detector-fault
  - gap-out
  - blind-zone
created: 2026-08-01T07:30:00
last_updated: 2026-08-01T07:30:00
sources:
  - "[[episodic-memory/2026-08-01_12-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_12-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[actuated-traffic-signals]]"
  - "[[webster-method]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
related_skills:
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - control-signals-with-actuated-tls
  - validate-congested-scenario-results-against-teleport-artifacts
  - measure-roundabout-capacity-and-implement-metering
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - design-signal-change-and-clearance-intervals
related_skills_for_graph_view:
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[design-signal-change-and-clearance-intervals]]"
---

# Actuated Signal Detector Design and Fault Tolerance

Every actuated-signal-control episode in this memory previously assumed perfect, always-working detection — [[actuated-traffic-signals]] documents SUMO's parameter surface but never varies detector placement or studies detector failure. This page documents the first treatment of detection itself — placement, gap tolerance, and fault modes — as a design variable, using the `design-actuated-signal-detector-placement-and-fault-tolerance` skill's methodology.

## The custom detector-binding syntax, rigorously verified

Binding a custom (non-auto-generated) detector to a SUMO actuated `tlLogic` uses `<param key="<laneID>" value="<detID>"/>` — the parameter key is the **lane ID itself**, not a prefixed form like `detector:<laneID>`. A special value `NO_DETECTOR` disables actuation-driven extension for that lane. Only E1 (`inductionLoop`) detectors are accepted; an E2 `laneAreaDetector` produces a hard error.

**This syntax was proven, not assumed**, via a manipulation-plus-negative-control protocol: comparing phase-transition traces (hashed for exact match/no-match) across variants that (a) moved a bound detector to an implausible position — the trace changed, confirming the binding is real; (b) set `NO_DETECTOR` — the phase pinned exactly at `minDur` with a SUMO warning; (c) referenced a nonexistent detector ID — SUMO raised a hard error; and critically (d) added an unrecognized `<param>` key as a negative control — the trace was **byte-identical** to baseline, confirming SUMO silently ignores keys it doesn't recognize. This last point matters generally: this memory has prior direct experience with a plausible-sounding SUMO config flag (`--tls.default-type` on an already-compiled network) silently failing to take effect — the same skepticism, and the same kind of behavioral-proof protocol, should be applied to any newly-discovered or assumed SUMO configuration mechanism before trusting it.

## Verified finding: the two detector-placement failure modes are wildly asymmetric

A detector placed **too close** to the stop line causes premature gap-out (the max-gap timer expires just before an approaching vehicle would have been detected) — a real but small cost, typically a few seconds per affected vehicle. A detector placed **too far** from the stop line creates a "blind zone": vehicles between the detector and the stop line, potentially already queued, are entirely invisible to the controller, which cuts the green phase while a real queue is still discharging. **This failure mode's cost was measured at roughly two orders of magnitude larger** than the too-close failure — up to hundreds of seconds per vehicle, with genuine capacity collapse at severe setbacks — and was confirmed causally (not just correlationally): raising the minimum green duration at a problematic setback directly and dramatically reduced both the blind-zone-cut frequency and the resulting delay.

## Verified, honest null result: SUMO's default detector placement is hard to beat

A dedicated hand-tuning sweep across detector setback and gap-tolerance parameters, at multiple approach speeds and demand levels, found **no statistically significant improvement over SUMO's own default detector-placement formula at any tested demand level**. The apparent "optimum" was a broad, flat plateau rather than a sharp point — a genuine null result, reported honestly rather than spun into a false positive by picking whichever cell happened to score marginally best.

## Verified finding: naive fault analysis is corrupted by survivorship censoring

A stuck-off detector fault (an approach's detector never calls, starving it of green time) appeared, under naive `tripinfo`-based mean delay, to be *less* harmful than the healthy baseline at high demand — because roughly half of scheduled vehicles never got inserted into the gridlocked network at all, and their catastrophic non-experience never entered the average (the same survivorship-censoring mechanism documented in [[teleport-artifacts-and-gridlock-resolution-validity]], here entering through insertion backlog rather than teleporting). Correcting with a **censoring-robust delay metric** — charging every scheduled vehicle, including those never inserted, an appropriate penalty — inverted the conclusion by roughly 10x, correctly revealing the fault as severely harmful. **Any fault-injection or gridlock-adjacent study must account for this censoring mechanism, or naive delay metrics will systematically understate the worst faults' true severity.**

## Verified finding: a stuck-on fault has no partial gradation

A stuck-on detector fault (permanently signaling a vehicle present) on only one of two lanes of a movement produced results statistically and even numerically indistinguishable from the same fault on both lanes — because SUMO's actuated logic extends a phase if **any** of its controlling detectors is calling, a logical OR across detectors rather than an average or majority vote. **One stuck-on detector is as bad as every detector on that movement failing simultaneously** — there is no partial-credit degradation to expect from a partial detector fault of this type.

## Verified fail-safe recommendation

Setting the actuated controller's `maxDur` parameter to the network's own Webster-computed green split (rather than a generic large value) allowed a stuck-on fault to degrade gracefully — under the fault, the controller's behavior became statistically indistinguishable from the fixed-time Webster baseline, since the phase simply always ran to its (now sensibly-bounded) maximum. This came at a real, demand-dependent healthy-state cost: harmful at light demand (where a generic large `maxDur` rarely binds anyway, so the tighter cap only costs unnecessary green truncation) but beneficial at high demand (where the tighter cap also helps prevent one phase from monopolizing the cycle under heavy but healthy load).

## Practical takeaways

- Never trust a newly-discovered or assumed SUMO configuration syntax without a behavioral proof (manipulation-changes-outcome plus negative-control-doesn't) — SUMO silently ignores unrecognized configuration in multiple documented cases across this memory.
- A detector placed too far from the stop line is a far more severe failure mode than one placed too close — verify placement conservatively toward "close enough to see the queue," not just "far enough to catch approaching platoons."
- Don't assume hand-tuning beats a sensible SUMO default without checking — report a genuine null result when it occurs.
- Always compute a censoring-robust delay metric (accounting for never-inserted vehicles) for any fault-injection or severe-congestion study — naive completed-trip-only averages can make the worst failures look artificially mild.
- Model a stuck-on sensor fault physically (a genuinely-triggering detector) rather than as a software override, and expect no partial-credit gradation from a partial multi-lane fault, since SUMO's actuated extension logic is an OR across controlling detectors.

See the `design-actuated-signal-detector-placement-and-fault-tolerance` skill for the full binding-syntax verification protocol, dual failure-mechanism instrumentation, and fault-modeling methodology.
