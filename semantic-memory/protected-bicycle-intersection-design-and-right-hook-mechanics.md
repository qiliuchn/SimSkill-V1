---
summary: SUMO's junction logic genuinely gives a through bicycle priority over an adjacent right-turning car (verified behaviorally, not from the misleadingly-asymmetric raw foes bitstring), but corner radius alone never slows a turning vehicle — only explicit --junctions.limit-turn-speed does, and only at genuinely tight radii; in a 5-variant intersection-design comparison, a timing-only Leading Bicycle Interval measured the lowest conflict rate of every variant at every tested volume, a protected-intersection proxy (setback + tight radius combined in one junction) showed no measured safety benefit over paint and revealed a critical construction gotcha — combining two geometric levers in a single junction produced genuine simulated collisions that neither lever alone produced — and an exclusive bicycle phase reduced but never eliminated conflicts at an always-positive, non-breakeven person-delay cost.
keywords:
  - protected-intersection
  - right-hook-conflict
  - bicycle-signal-phase
  - leading-bicycle-interval
  - cycle-track
  - corner-radius
  - bicycle-vehicle-conflict
created: 2026-08-07T05:39:34
last_updated: 2026-08-07T05:39:34
sources:
  - "[[episodic-memory/2026-08-07_05-35-47/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_05-35-47/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[horizontal-curvature-and-curve-speed-in-sumo]]"
  - "[[multimodal-signal-progression-and-the-bicycle-green-wave]]"
  - "[[right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[surrogate-safety-measures]]"
  - "[[dedicated-bicycle-lanes-and-mode-share]]"
  - "[[left-turn-treatment-tradeoffs]]"
related_skills:
  - evaluate-protected-bicycle-intersection-design
  - model-dedicated-bicycle-lane-infrastructure
  - build-pedestrian-crossings-and-phasing
  - evaluate-right-turn-on-red-and-leading-pedestrian-interval
  - analyze-intersection-safety-with-ssm
  - compare-left-turn-signal-treatments
related_skills_for_graph_view:
  - "[[evaluate-protected-bicycle-intersection-design]]"
  - "[[model-dedicated-bicycle-lane-infrastructure]]"
  - "[[build-pedestrian-crossings-and-phasing]]"
  - "[[evaluate-right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[compare-left-turn-signal-treatments]]"
---

# Protected Bicycle Intersection Design and Right-Hook Mechanics

The signalized junction — specifically the right-hook conflict between a right-turning car and an adjacent through bicycle — is where bicycle crashes concentrate in practice, but nothing in memory had built or measured it before this page. See `evaluate-protected-bicycle-intersection-design` for the full methodology; this page holds the mechanism-verification findings and the design-comparison results from a 5-variant study (mixing zone, conventional bike lane, protected intersection, protected + exclusive bicycle phase, timing-only Leading Bicycle Interval).

## The right-hook yield mechanism is native and verified — but only behaviorally

SUMO's compiled-net junction foe/response bitstring can look asymmetric across geometrically identical corners of the same junction — reading it naively suggests the yield mechanism is unreliable or inconsistent. A direct behavioral test refutes that: at light, non-saturating demand (so free-flow gaps exist to observe selective yielding rather than general queueing), right-turn via-lane speed collapsed uniformly at every corner when a bicycle was present (roughly halved from free-flow), while bicycle speed was unaffected — confirming SUMO's junction logic genuinely gives the through bicycle priority, consistently, with zero collisions in the clean test. **The raw bitstring is not a safe way to answer "does this mechanism work" — only a paired baseline-vs-interaction behavioral measurement should be trusted.** The SSM device does record these encounters when filtered by vClass pair, though it double-logs every conflict from both participants and total conflict counts in a busy scenario can be dominated by non-target vClass pairs — filter explicitly.

## Corner geometry alone does not slow a turn — the flag is required, and it may not activate

Node `radius` by itself has no independent effect on measured right-turn speed — in a verified factorial across four radii, the tightest radius tested actually produced the *highest* unconstrained speed of any tested value. This replicates `[[horizontal-curvature-and-curve-speed-in-sumo]]`'s finding that SUMO's speed-choice machinery doesn't read geometry, now confirmed at junctions specifically, not just on curved edges. `--junctions.limit-turn-speed` does produce a real, substantial speed reduction (verified ~20%) — but **only at genuinely tight radii**; it was a complete no-op at moderate radii in the tested range, consistent with that page's angle/deadband finding. Any "protected intersection" design whose safety case depends on geometry physically slowing the turn must verify both that the flag is set *and* that it actually activates at the chosen radius.

## A protected-intersection proxy can hide a real construction defect — check the combined treatment for collisions, not just each factor alone

A protected intersection typically bundles two distinct mechanisms: a setback crossing (moves the conflict location) and a tight corner radius (reduces the conflict speed). Isolating them individually is straightforward and verified to work cleanly for speed (turn speed reduction is attributable entirely to radius, not setback). **Conflict rate is a different story, and combining the two levers within a single compiled junction — rather than as physically separate junction nodes — surfaced a genuine, serious construction defect**: the combined treatment's internal via-lane geometry became measurably longer and more convoluted than either factor alone, and this produced real simulated collisions (bike-bike and car-bike) that scaled with bicycle volume, while every other design variant — including *each geometric factor tested alone* — showed zero collisions. This is not a hypothetical risk to flag defensively; it was measured directly in one implementation. **Whenever two geometric treatments are combined within one junction, check the combined variant's collision count specifically and compare it against each factor tested alone** — a defect invisible in either individual treatment can appear only in combination, and it will silently contaminate every conflict-rate number computed from the combined variant if not caught.

A single-junction connection-shape override is a pragmatic proxy for a protected intersection, not a topologically faithful one — a true protected intersection has a physically separate corner-refuge node. Any conclusion drawn from the proxy (including "geometric protection measured worse than a timing-only treatment") should be scoped explicitly to that proxy's construction, not generalized to real protected intersections, until re-validated against a genuinely separate-node design.

## Design comparison: the cheap treatment won on every measured axis, in this implementation

Across a 5-variant comparison (mixing zone, conventional bike lane, protected-intersection proxy, protected + exclusive bicycle phase, and a timing-only Leading Bicycle Interval on the conventional lane) swept across bicycle volume and conflicting right-turn volume with CRN-paired replications:

- **The Leading Bicycle Interval (timing-only, no concrete) measured the lowest conflict rate of all five variants at every tested bicycle and right-turn volume**, and did so at lower person-delay than the exclusive-phase variant. The protected-intersection proxy never beat it on conflict exposure at any tested volume — though this comparison is qualified by the construction defect above, since the protected variant's conflict count may be inflated by it.
- **An exclusive bicycle signal phase reduces but does not eliminate right-hook conflicts**, and does so at an always-positive person-delay cost with **no breakeven point** in the tested range against the protected-intersection-without-exclusive-phase variant — it converts some conflict exposure into delay rather than removing it for free.
- **A mixing zone (bike lane dropped upstream of the junction, bicycles sharing the through/right lane) is unambiguously worse than a conventional dedicated-but-conflicting bike lane on both conflict count and conflict severity** — not a count-for-severity tradeoff. Bicycle delay was also several times higher in the mixing-zone design.
- **Neither the setback nor the tight-radius factor alone showed a measured conflict-rate benefit over the conventional baseline** in this implementation, and their combination was not simply additive — a genuinely surprising result, though one that must be read alongside the construction-defect caveat and the proxy's lack of topological fidelity.

## Validity envelope

What this class of study cannot represent without explicit workarounds or caveats: cyclist lateral positioning and bicycle-bicycle passing (mitigated by enabling the sublane/lateral-resolution model per `[[multimodal-signal-progression-and-the-bicycle-green-wave]]`'s gotcha, but overtaking should be independently verified from lane-change output rather than assumed to occur safely — bike-bike collisions at high volume are circumstantial evidence it isn't always resolved cleanly); informal yielding, eye contact, and cyclist non-compliance (not modeled — every simulated bicycle obeys signals and right-of-way perfectly); driver sight-line and visual-prominence effects of corner geometry (SUMO has no such visibility model); and topological fidelity of a "protected intersection" built as a same-junction shape override rather than a genuinely separate corner-refuge node (the direct cause of the collision defect above). Any conclusion drawn from this class of study should state explicitly which of these gaps it depends on not mattering.
