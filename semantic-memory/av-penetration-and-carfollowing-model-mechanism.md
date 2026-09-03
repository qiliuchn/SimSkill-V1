---
summary: A gap-matched Krauss mechanism control (isolating shorter reaction time from car-following model structure) revealed that a plain Krauss fleet at the AVs' own time gap achieves dramatically higher SUMO freeway bottleneck capacity (+34%) than SUMO's own ACC (+3.5%) or CACC (-13%, worse than human) at the identical time gap, because SUMO's CACC model was independently verified to silently fall back to a hard-coded ~1.0s headway (ignoring its own configured tau) when following a non-CACC leader; all ACC-arm results are honestly flagged as involving real vehicle collisions and should be treated as provisional.
keywords:
  - AV-market-penetration
  - carFollowModel
  - ACC
  - CACC
  - mixed-autonomy
  - bottleneck-capacity
created: 2026-07-31T16:55:00
last_updated: 2026-07-31T16:55:00
sources:
  - "[[episodic-memory/2026-07-31_16-40-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_16-40-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[phantom-traffic-jams-and-single-av-stabilization]]"
  - "[[simpla-platooning]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
related_skills:
  - measure-av-penetration-effect-on-bottleneck-capacity
  - demonstrate-and-stabilize-phantom-traffic-jams
  - form-platoons-with-simpla
  - quantify-sumo-run-to-run-variability
  - validate-kinematic-wave-theory-across-car-following-models
related_skills_for_graph_view:
  - "[[measure-av-penetration-effect-on-bottleneck-capacity]]"
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
  - "[[form-platoons-with-simpla]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
---

# AV Penetration and Car-Following Model Mechanism

Whether automated/connected vehicles increase freeway bottleneck capacity in SUMO depends on a distinction that a naive HUMAN-vs-ACC-vs-CACC comparison conflates: is any measured benefit coming from the shorter reaction time (`tau`) typically configured for automated vehicles, or from the ACC/CACC car-following model's structure itself? This page documents the first mechanism-isolated test of this question in this memory, using a **gap-matched Krauss mechanism control** — plain Krauss car-following with zero driver noise and `tau` set exactly equal to the AV fleet's own configured time gap.

## Verified finding: the mechanism control inverts the naive conclusion

At a 3-to-2 lane-drop freeway bottleneck, a plain Krauss fleet given the AVs' own time gap (`tau=0.9s`, `sigma=0`) reached **+34.4%** bottleneck discharge over an all-human baseline. SUMO's own **ACC** model at the *identical* time gap reached only **+3.5%**. SUMO's own **CACC** model at the *identical* time gap fell to **−12.7%**, actually *below* the human baseline. **A study that only ran HUMAN vs. ACC vs. CACC would have concluded "ACC gives a small gain, CACC is harmful."** The mechanism-isolated conclusion is different and more informative: the shorter headway alone is worth a large capacity gain, and SUMO's ACC/CACC model structures give back the large majority of that benefit — traced directly to excess lane-change/merge turbulence at the bottleneck (Krauss fleets achieved 102-105% of their own pure car-following capability there; ACC only ~76%; CACC only ~65%).

## Verified, decisive finding: SUMO's CACC silently ignores its own parameters behind a non-CACC leader

An isolated two-vehicle probe (a single follower behind different leader types, with speed-factor noise removed) found that SUMO's CACC model is leader-aware, but in a way not evident from configuration: **behind a non-CACC leader, two CACC vehicles configured with genuinely different time gaps (0.9s and 0.6s) converged to nearly identical gaps — both falling back to a hard-coded ~1.0-second headway that ignored their own configured `tau` entirely.** Behind their own type (CACC following CACC), each honored its own configured `tau` exactly. This means CACC can degrade to behavior *worse* than the simpler, leader-agnostic ACC model (which held its own configured `tau` regardless of leader type) in precisely the mixed-traffic conditions a market-penetration study exists to study. **Never assume a "cooperative" car-following model's advertised parameters apply uniformly across leader types — verify actual behavior behind a foreign leader via a direct probe.**

## Verified finding: the curve shape differs qualitatively by model, and isn't what folklore assumes

Fitting (not eyeballing) linear and quadratic models to capacity-vs-penetration data, with an F-test to justify any claimed curvature: the gap-matched Krauss control's curve was essentially perfectly **linear**. CACC's curve was **monotone decreasing** (more CACC penetration made things worse, consistent with its leader-awareness fallback degrading capacity whenever a CACC vehicle followed a human). ACC's curve was **non-monotone and poorly fit** by either polynomial degree — its behavior as a function of penetration was not a smooth function of market share at all. **The commonly-assumed convex "AV benefit compounds with penetration" shape was not observed in any tested arm** — always fit the actual data rather than assuming a particular curve shape.

## Verified finding: AV arrangement matters far less than expected, and leader-is-AV fraction is not p²

Comparing random AV placement against deliberately platooned/clustered placement of the identical AV count: platooning substantially raised the realized fraction of AV vehicles whose immediate leader was also an AV (from roughly 0.54 to 0.74 in one test), but changed measured bottleneck capacity by at most ~1%, mostly not statistically distinguishable from zero — a clean negative result. Separately, the realized leader-is-AV fraction at a given penetration level was measured directly (not assumed) and found to substantially exceed the naive independence assumption of `p²` — by roughly 8x at low penetration in one test — because AVs are not spatially uniform through a congested network and exhibit some genuine self-clustering from car-following dynamics alone. **Both of these are reasons to measure the leader-composition and arrangement effects directly rather than reasoning about them analytically.**

## Honest, prominently-disclosed limitation: the ACC arm involved real collisions

Every ACC-fleet simulation run in the underlying study experienced genuine vehicle-vehicle collisions (thousands total, zero for CACC and all Krauss-family configurations), even using SUMO's own documented minimum step length (0.1s) for ACC/CACC. Collision count did not correlate with the reported discharge-flow metric, so it does not mechanically inflate the ACC capacity numbers — but **all ACC-specific figures should be treated as describing a physically-invalid configuration in this SUMO version**, provisional rather than a clean measurement, while the CACC and Krauss-family results (collision-free) can be trusted at face value. This caveat belongs in any headline summary of the finding, not buried in a limitations section, given how much of the study's central claim rests on the ACC comparison.

## Practical takeaways

- Never study "does automation help traffic" by comparing human vs. automated car-following models alone — include a gap-matched, driver-noise-free Krauss control to separate the reaction-time effect from the model-structure effect.
- Verify a cooperative car-following model's actual leader-aware behavior via a direct two-vehicle probe rather than trusting its documented parameters — it may silently fall back to different behavior behind a foreign leader type.
- Check `departSpeed` settings before attributing a capacity result to an intended bottleneck — ACC/CACC insertion dynamics can make network entry the actual binding constraint.
- Fit penetration-vs-capacity curves statistically (with an F-test for curvature) rather than asserting a shape from a plot.
- Measure leader-composition/arrangement effects directly from simulation data — don't assume p² independence or that platooning must help proportionally.
- If a car-following configuration produces real collisions, disclose this in the headline of any report, not just a limitations section — it changes how much the affected results should be trusted.

See the `measure-av-penetration-effect-on-bottleneck-capacity` skill for the full mechanism-control, leader-awareness-probe, and penetration-sweep methodology.
