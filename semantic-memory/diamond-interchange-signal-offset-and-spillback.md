---
summary: In a grade-separated diamond interchange with two closely-spaced signalized ramp terminals, the offset between the two signals directly governs whether the short internal arterial link between them spills back and blocks the upstream terminal; verified that a poorly-coordinated offset (half a cycle off) roughly doubled near-full-jam frequency on the internal link versus a well-coordinated offset, costing measurable throughput and a ~28% increase in mean delay on identical demand, and that reconciling a metric's aggregation definition (e.g. per-lane vs worst-of-both-lanes) consistently across every reporting document is essential to avoid an apparent (though not actual) correctness inconsistency.
keywords:
  - diamond-interchange
  - grade-separation
  - internal-link-spillback
  - signal-offset
  - ramp-terminal
created: 2026-07-29T15:45:00
last_updated: 2026-07-29T15:45:00
sources:
  - "[[episodic-memory/2026-07-29_15-03-02/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_15-03-02/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-29_15-03-02/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[roundabout-modeling-and-comparison]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[diverging-diamond-interchange-unopposed-lefts]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - build-diamond-interchange-with-signal-offset-spillback
  - optimize-signals-by-tlscoordinator
  - compare-unsignalized-intersection-control-types
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
---

# Diamond Interchange Signal Offset and Spillback

A grade-separated diamond interchange — a freeway passing under or over an arterial, with off- and on-ramps terminating at two closely-spaced signalized intersections on the arterial — presents a coordination problem distinct from ordinary arterial green-wave signal timing (see `optimize-signals-by-tlscoordinator`): the internal arterial link between the two ramp terminals is typically very short, with limited vehicle storage, so the *offset* between the two signals directly determines whether that link fills and spills back into the upstream terminal.

## Grade separation must be verified from the compiled network

Building a genuine grade-separated interchange requires distinct `z`-coordinates on the freeway vs. arterial nodes/edges, **and** ensuring no shared node exists at their crossing point. Verification should happen at the compiled network's connection level — confirm zero `<connection>` elements directly link any freeway-mainline edge to any arterial edge; all freeway↔arterial interaction must route through a ramp edge at one of the two terminal junctions.

## Verified finding: offset directly governs internal-link spillback

On a real diamond interchange with a ~100m internal link, a well-coordinated signal offset (tuned so the internal-link platoon discharges downstream before it can fill the link's storage) kept mean internal-link occupancy around 30%, with near-full-jam conditions occurring roughly a quarter of the time. A poorly-coordinated offset (roughly half a cycle off from optimal) raised mean occupancy to over 40%, with near-full-jam conditions occurring nearly half the time — a substantially more frequent, genuine spillback condition reaching back toward the upstream terminal. This translated into a real cost: dozens of fewer vehicles served, some vehicles never even inserted due to upstream congestion, and roughly a 28% increase in mean intersection delay — all attributable purely to the offset, with demand, seed, and cycle length held identical between scenarios.

## A metric's aggregation definition must be reconciled across every reporting document

**When a metric like "spillback fraction" can be validly computed multiple ways (e.g. sampling one representative lane vs. taking the worst of both lanes at each timestep), citing different numbers for the identically-named metric in different deliverables — even if each individual number is a correct computation of *something* — reads as an inconsistency and undermines confidence in the whole analysis.** Verified as a real, avoidable defect in one study: a narrative and a shipped comparison table disagreed on the "same" spillback-fraction value because they used different aggregation methods without either document disclosing which. The fix is to pick one authoritative definition (for a two-lane link's spillback specifically, "worst of both lanes per timestep" is the more physically meaningful choice, since a queue filling *either* lane is sufficient to block the junction), label it unambiguously, and cite the identical number everywhere it appears — relegating any alternative computation to an explicitly-labeled reconciliation note rather than presenting it as a second competing answer.

See the `build-diamond-interchange-with-signal-offset-spillback` skill for the full network-construction, offset-scenario, and instrumentation workflow.
