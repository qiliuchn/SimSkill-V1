---
summary: Converting a two-way street grid to a fair (equal-total-lane-km) one-way-pair system in SUMO produces a genuine, non-monotonic demand crossover — two-way wins below ~4200-5600 veh/h, one-way wins above it (fewer conflicting movements, real signal-progression bandwidth outweighing a ~9% route-circuity penalty concentrated entirely in local-access trips), and the ranking reverses back toward two-way at very high demand (~8000 veh/h) as the narrower one-way streets begin to gridlock; a deliberately unfair naive (halved-lane) one-way conversion collapses far earlier, showing the conclusion is highly sensitive to the fairness-of-comparison control.
keywords:
  - one-way-street
  - two-way-street
  - grid-topology
  - route-circuity
  - signal-progression
  - bandwidth
created: 2026-07-31T19:25:00
last_updated: 2026-07-31T19:25:00
sources:
  - "[[episodic-memory/2026-07-31_18-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_18-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[neighborhood-traffic-calming-displacement-and-evaporation]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - compare-one-way-vs-two-way-street-grid-conversion
  - create-grid-network
  - optimize-signals-by-tlscoordinator
  - quantify-sumo-run-to-run-variability
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[compare-one-way-vs-two-way-street-grid-conversion]]"
  - "[[create-grid-network]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
---

# One-Way vs. Two-Way Grid Performance Crossover

Whether converting a two-way urban street grid to one-way pairs improves network performance depends on demand level in a way that is neither purely linear nor purely one-directional — this page documents the first street-system-topology comparison in this memory to measure exactly where and why the answer changes, and how sensitive the conclusion is to a fair-comparison control.

## Verified finding: a genuine, non-monotonic demand crossover exists

With total lane-km held exactly equal between a two-way baseline and a one-way-pair conversion (verified directly from compiled network files, not just design intent), a demand sweep found: **below roughly 4200-5600 vehicles/hour** (the exact crossover point varies slightly by metric — mean speed, mean duration, and stops/vehicle each cross at a slightly different demand level), the two-way network performed better. **Above that range**, one-way's structural advantages (fewer conflicting movements at each intersection, simpler two-phase signal timing, achievable real progression bandwidth) overtook its route-circuity penalty. **At very high demand (~8000 veh/h)**, the ranking reversed *back* toward two-way, as one-way's narrower per-street capacity began to bind and gridlock more severely than the two-way grid's more evenly-distributed capacity. The advantage of one-way conversion is therefore a genuine, bounded demand *window*, not a monotonic function of demand in either direction.

## Verified finding: the fair-comparison control determines the answer

A deliberately unfair "naive" one-way conversion (simply dropping the reverse-direction lanes, roughly halving total lane-km) collapsed into gridlock at a substantially lower demand level than the fair (equal-lane-km) conversion. **Using the naive conversion's result alone would have produced a starkly more negative — and misleading — conclusion about one-way conversion in general.** This is a strong illustration that a "one-way streets are worse/better than two-way" claim is not meaningful without specifying exactly how the lane capacity was reallocated in the conversion.

## Verified finding: the route-circuity penalty is concentrated entirely in local-access trips

Decomposing route circuity by trip type revealed a clean split: **through-trips** (traversing the grid corner-to-corner) had circuity essentially exactly **1.0** — a Manhattan-grid path length is invariant to which streets carry which direction, since an equally-long path exists in both directions somewhere in a regular alternating grid. **Local-access trips** (shorter, more localized origin-destination pairs) bore the entire circuity penalty (a real ~20% detour in one verified test), yielding an aggregate ~9% overall penalty once weighted by the actual through/local demand mix. **Reporting only an aggregate circuity number would obscure that the cost is entirely a local-access phenomenon** — a network with mostly through-traffic would see little circuity penalty from one-way conversion, while a network with mostly local-access trips would see the full penalty.

## Verified finding: signal-progression bandwidth requires reconciling network-wide and per-street pictures

A network-wide *geometric* bandwidth calculation (from signal offsets and cycle length alone) came out nearly identical between the two-way and one-way topologies — both can theoretically progress two of four directional flows independently. But the *simulated* result strongly favored one-way, because the constraint actually bites **per-street**: on a given two-way street, one direction can get a real green-wave band while the opposing direction gets essentially none, whereas every one-way street's entire signal-timing budget serves its single direction exclusively. **A network-wide aggregate bandwidth figure can mask a real, asymmetric per-street constraint** — check both levels before concluding two topologies have equivalent progression potential.

## Verified, honest correction to a textbook expectation

The commonly-assumed consequence of two-way signal coordination — that one direction gets sacrificed for the other's green wave — did **not** appear in this test. Instead, `tlsCoordinator`'s computed offsets produced a **symmetric compromise**: both directions on the two-way arterial landed at a similar, moderately-degraded stops/delay level, with the directional difference statistically indistinguishable from zero (computed as a direct paired difference, not a folded/absolute-value statistic, which would have distorted the confidence interval). The real bandwidth penalty from two-way operation was still present and substantial — it was simply distributed across both directions rather than concentrated in one.

## Verified, honestly mixed safety result

A surrogate-safety (SSM) comparison found fewer crossing/angle conflicts under one-way conversion (consistent with fewer intersection conflict points, the expected mechanism) but *more* total conflicts overall, driven by increases in rear-end and merging conflict types. **This memory does not claim one-way conversion is safer** — the mixed direction of the result is reported honestly rather than forced toward a clean "fewer conflict points means safer" narrative.

## Practical takeaways

- Never evaluate a one-way conversion (or any topology change) without an explicit, verified fair-capacity control — how the lane reallocation is done can determine the entire conclusion.
- Decompose route-circuity impact by trip type — a topology change's circuity cost is often concentrated in one trip category, not spread evenly.
- Check both network-wide aggregate and per-street/per-direction signal-progression metrics — they can tell inconsistent-looking stories that are actually both true at different levels of aggregation.
- Don't assume a textbook prediction (e.g. "two-way sacrifices one direction") without computing the actual per-direction outcome — a coordinated signal system can produce a different distribution of the same aggregate cost.
- A "fewer conflict points" topology change is not automatically safer overall — check conflict type breakdown, not just total count or crossing-conflict count alone.

See the `compare-one-way-vs-two-way-street-grid-conversion` skill for the full network-construction, circuity-decomposition, and bandwidth-reconciliation methodology, plus two disclosed SUMO implementation gotchas (`tlLogic` offset sign convention, FCD edge-filter file format).
