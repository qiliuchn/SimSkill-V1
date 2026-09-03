---
summary: SUMO's unsignalized junction-control types (right_before_left, priority/TWSC, allway_stop/AWSC) each have a distinct delay-crossover demand level beyond which a signal becomes warranted, verified via a demand sweep; a naive loaded-vs-arrived throughput comparison and a naive SSM type=111 "collision" count can both mislead, since vehicles can be blocked from ever being inserted at high demand (undercounting failure by 10x+ if only inserted-vs-arrived is compared) and opposing left-turn movements on collinear internal-lane geometry can produce a spurious zero-TTC "collision" flag that, if not excluded, can completely invert the genuine safety comparison.
keywords:
  - unsignalized-intersection
  - two-way-stop-control
  - all-way-stop-control
  - right_before_left
  - signal-warrant
created: 2026-07-29T10:35:00
last_updated: 2026-08-05T22:30:00
sources:
  - "[[episodic-memory/2026-07-29_09-44-55/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_09-44-55/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_09-44-55/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[roundabout-modeling-and-comparison]]"
  - "[[surrogate-safety-measures]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[diverging-diamond-interchange-unopposed-lefts]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[autonomous-intersection-management-safety-and-performance-envelope]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[demand-arrival-process-and-unsignalized-capacity]]"
  - "[[intersection-sight-distance-and-sumo-visibility-parameter]]"
related_skills:
  - compare-unsignalized-intersection-control-types
  - create-roundabout-network
  - analyze-intersection-safety-with-ssm
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - measure-roundabout-capacity-and-implement-metering
  - implement-reservation-based-autonomous-intersection-management
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
  - model-intersection-sight-distance-restriction-at-a-twsc-junction
related_skills_for_graph_view:
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[create-roundabout-network]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
  - "[[model-intersection-sight-distance-restriction-at-a-twsc-junction]]"
---

# Unsignalized vs. Signalized Intersection Control

SUMO's unsignalized junction-control types — `right_before_left` (uncontrolled, yield-to-the-right), `priority` (two-way stop control, TWSC, where a designated major road has right-of-way over minor approaches), and `allway_stop` (all-way stop control, AWSC, where every approach must stop) — are first-class netconvert junction types, entirely distinct from any `tlLogic`, completing the classic HCM intersection-control hierarchy (TWSC → AWSC → signal → roundabout; see [[roundabout-modeling-and-comparison]] for the roundabout end of that hierarchy).

## Each mode has a distinct delay-crossover demand level

At low demand, every unsignalized mode achieves lower delay than a comparable signal, since there's no fixed red time wasted when there's little cross-traffic to conflict with. As demand rises, each mode saturates at a different point:

- **`right_before_left`** crosses over to favor a signal earliest — uncontrolled yield-to-right behavior deadlocks relatively quickly under moderate load.
- **TWSC (`priority`)** holds out longer than uncontrolled, since the major road's uninterrupted flow delays only the minor movements.
- **AWSC (`allway_stop`)** can remain the lowest-delay mode across a very wide demand range, never crossing over to favor a signal within a tested range up to a high demand level, in a verified study.

Verify a TWSC variant's actual right-of-way from the compiled network directly — don't assume setting edge priority produced the intended yield behavior. Read the `<request response=".." foes=".."/>` bitstrings and connection `state` characters: minor-road connections should carry `m` (yield), major-road through/right connections should carry `M` with an all-zero response bitstring (yielding to nothing), and minor-road connections' response bits should point exactly at the opposing major-road movements.

## Genuine throughput measurement requires `loaded`, not just `inserted` and `arrived`

**A naive "incomplete = inserted − arrived" metric can undercount true failed demand by 10x or more at high congestion**, because it misses vehicles that were generated but never even inserted into the network at all — SUMO blocks insertion at a jammed source edge, visible as `loaded > inserted` in `summary.xml`'s per-step data. Verified: a control mode that appeared to have "0 teleports, 0 incomplete" at high demand was actually refusing to insert roughly 10% of its demand at the source, not genuinely serving it — a completely different finding from what the naive metric suggested. Always compute `never_inserted = loaded − inserted` and use `incomplete_true = loaded − arrived` as the genuine failed-demand figure.

## A collinear opposing-left-turn SSM artifact can invert a naive safety comparison

**SUMO's SSM device can flag a spurious `type="111"` ("collision") encounter between two opposing left-turning vehicles occupying the same collinear internal-lane crossing geometry, with `minTTC`/`PET` values of exactly 0.00 or `NA` — a degenerate computation artifact, not a genuine near-miss.** Verified directly across a real 32-run comparison: literally every single `type=111` flag in every run traced to this exact artifact (opposing E-left/W-left or N-left/S-left pairs), and a naive analysis that counted every `type=111` flag as a "severe conflict" produced a completely inverted, non-genuine safety narrative — attributing the highest severe-conflict rate to the wrong control mode entirely. Once correctly excluded and the genuine safety signal rebuilt from crossing-type encounters (SSM types 10-17) with a finite, positive TTC below a real severity threshold, attributed by actual movement pair, the corrected picture was substantially different from the naive first pass.

**Practical discipline**: always classify every flagged SSM conflict by the actual vehicle-movement pair that triggered it before building any causal safety narrative — an encounter-type code count alone, without movement-pair attribution and a sanity check on whether the TTC/PET values are physically meaningful (nonzero, finite), can silently be built entirely on a geometry artifact.

See the `compare-unsignalized-intersection-control-types` skill for the full network-construction, verification, and corrected-analysis workflow.
