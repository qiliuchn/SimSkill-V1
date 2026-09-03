---
summary: SUMO is a kinematic-wave (LWR) simulator operationally — shock speeds on a physical lane blockage are predicted to within a few percent by Rankine-Hugoniot applied to each car-following model's own measured fundamental diagram — but which fundamental diagram a link has is almost entirely a property of the car-following model, not physics; the textbook w=(length+minGap)/tau and q_max formulas turned out to be identities of one specific model at zero driver imperfection, failing by up to 74% for others, and models matched to ~1% on both free-flow speed and capacity still diverged 26-31% in wave speed and jam density, spreading a downstream incident-spillback-time prediction by over 20%.
keywords:
  - kinematic-wave-theory
  - fundamental-diagram
  - lwr-theory
  - shockwave-speed
  - rankine-hugoniot
  - capacity-drop
  - moving-bottleneck
  - car-following-model-comparison
created: 2026-08-02T13:30:00
last_updated: 2026-08-02T13:30:00
sources:
  - "[[episodic-memory/2026-08-02_13-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_13-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[phantom-traffic-jams-and-single-av-stabilization]]"
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
related_skills:
  - validate-kinematic-wave-theory-across-car-following-models
  - build-macroscopic-fundamental-diagram
  - demonstrate-and-stabilize-phantom-traffic-jams
  - visualize-trajectories-and-timeseries
related_skills_for_graph_view:
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
  - "[[visualize-trajectories-and-timeseries]]"
---

# Kinematic Wave Theory Validity Across Car-Following Models

Kinematic wave (LWR) theory predicts traffic flow behaves as a conservation law over a
fundamental diagram (flow-density-speed relation), with shock/wave speeds given by
Rankine-Hugoniot. This page concerns whether SUMO's microsimulation actually behaves
this way at the link scale, and — the more consequential finding — how much of any
answer is a property of the chosen car-following model rather than of physics itself.

## Verified finding: shock speeds obey Rankine-Hugoniot strikingly well, even though models disagree sharply on wave speed

On a temporary full-lane blockage (a physical, conservation-law-obeying two-state
shock), every tested car-following model's measured wave-front speed matched the
Rankine-Hugoniot prediction computed from that *same* model's own measured
fundamental diagram to within roughly 1-12%, at very high fit quality (R² ≥ 0.996) —
despite the models' own predicted wave speeds differing from each other by up to 50%.
**This is the strongest evidence that SUMO genuinely implements the underlying
conservation law**, since agreement holds per-model against each model's own FD,
not against one shared reference.

## Verified finding: the textbook parameter-to-wave-speed and parameter-to-capacity formulas are model-specific, not general SUMO identities

The commonly-cited closed-form relations `w = (length+minGap)/tau` and
`q_max = v_f/(v_f*tau+length+minGap)` were tested by directly sweeping tau, minGap,
length, and driver-imperfection parameters and comparing against each model's fitted
FD. **These formulas turned out to be exact identities of one specific car-following
model (Krauss) at its deterministic (zero driver-imperfection) setting, not general
SUMO relations**: at zero imperfection, Krauss reproduced both formulas to within a
fraction of a percent; introducing SUMO's typical nonzero default driver-imperfection
level cost a consistent ~12% of both predicted wave speed and capacity (a clean,
roughly linear degradation as the imperfection parameter increased). Two other tested
models (IDM, EIDM) failed the wave-speed formula by as much as ~75%, because their
wave speed barely responds to the tau parameter at all. **Only the jam-density
relation, `k_j = 1/(length+minGap)`, held robustly across every tested model** — this
is the one safe generalization; the wave-speed and capacity formulas should be
verified per model before being relied on, not assumed to transfer from whichever
model a practitioner happens to be most familiar with.

## Verified finding: not every fast or slow wave is a genuine kinematic-wave violation — check the state and the transition first

Testing wave speeds on a signalized link (rather than a physical blockage) found real
disagreement with Rankine-Hugoniot for some models, but investigation traced this to
two specific, checkable mechanisms rather than a breakdown of the underlying
conservation law:

- **A model whose stopping behavior is anticipatory rather than purely reactive can
  produce a stopping wave that travels faster than its own jam-density physics would
  predict**, because it isn't tracking a genuine density-front shock at all — in one
  tested case a model brought nearly every approaching vehicle to a full stop well
  before a simple reactive car-following rule would require, more than doubling the
  effective stopping-wave speed versus its own Rankine-Hugoniot prediction, while
  still producing the physically correct total queue length. The queue itself was
  right; the *process* by which it formed was not a shock.
- **A short, repeated signal-red queue may never actually reach the model's own jam
  density**, in which case a release-wave-speed comparison against the jam-to-capacity
  Rankine-Hugoniot prediction is comparing against the wrong reference state — one
  tested model's signal queue reached only about half its own jam density (with fewer
  than half the queued vehicles reaching a genuine full stop), making its release wave
  roughly twice as fast as the (inapplicable) jam-based prediction, while that same
  model's *incident* queue (which does reach near-jam density) showed good
  Rankine-Hugoniot agreement.

**The general lesson: before concluding kinematic wave theory has failed on a given
wave measurement, check whether the measured queue state actually matches the density
the theory's prediction assumes, and whether the transition being measured is a
genuine density-front shock or a different kind of process (e.g., anticipatory
stopping) that happens to look wave-like.**

## Verified finding: capacity drop in SUMO is largely, but not exclusively, a lane-changing phenomenon

Comparing a lane-drop bottleneck (requiring merging) against a same-lane speed-drop
bottleneck (no lane changing involved) found the classic two-capacity/capacity-drop
phenomenon present strongly (25-47%) at the merge-requiring bottleneck across every
tested model, but only weakly or negligibly present for some models (near zero) on
the lane-change-free bottleneck, while still present (~15%) for others. **Capacity
drop should not be assumed to be a pure car-following/fundamental-diagram effect** —
testing both bottleneck types separately is necessary to establish how much of an
observed capacity drop is attributable to lane-changing dynamics specifically versus
the underlying car-following model's own congested-branch behavior.

## Verified finding: Newell's moving-bottleneck theory holds on a single lane, and multi-lane discharge can instead be lane-change-limited

A slow-moving vehicle acting as a moving bottleneck was tested against Newell's
theory in two regimes. On a **single lane** (passing physically impossible), the
platoon behind the slow vehicle settled onto the fundamental-diagram point whose
chord slope equals the slow vehicle's speed, as predicted, across every tested model,
and the state-dependence prediction (a queue forms only once upstream demand exceeds
the predicted passing capacity) was confirmed at the great majority of tested
demand/speed combinations. On **two lanes** (the slow vehicle occupies one lane,
passing available in the other), the theoretical prediction that discharge capacity
collapses to exactly the single-lane capacity, independent of the slow vehicle's
speed, held for most tested models, but **failed sharply for one model whose
two-lane discharge was only about 60% of the theoretical value** — traced to that
model's vehicles not merging out of the blocked lane fast enough, meaning its
multi-lane discharge was set by SUMO's lane-change gap-acceptance logic, not by its
fundamental diagram. **A car-following model's fundamental diagram does not
automatically determine its multi-lane discharge behavior; the lane-changing model
can be the actual binding constraint**, and this should be tested explicitly rather
than assumed away.

## Verified finding: matching capacity and free-flow speed does not pin down queueing behavior

Four car-following models were explicitly tuned (via a parameter search) to match
free-flow speed and capacity to within about 1% of each other. Despite this close
match on two of the most commonly-cited calibration targets, the models still
diverged substantially in wave speed (up to 31% spread) and jam density (up to 26%
spread) — and this translated directly into a concrete downstream engineering
prediction: simulating the identical incident scenario across the four matched
models produced a spread of over 20% in both predicted spillback time to an upstream
junction and total incident clearance time, even though each model's own spillback
prediction still matched its own fundamental diagram to within about 10%.
**Calibrating a car-following model on free-flow speed and capacity alone is not
sufficient to pin down queueing/spillback predictions — jam density and wave speed
must be calibrated separately, since they are not implied by matching the other two
quantities.**

## Practical takeaways

- Use a closed ring for any fundamental-diagram measurement that needs an exact,
  controlled density rather than an open-road detector-based estimate.
- Verify a triangular-FD fit's quality (R²) per model — some car-following models
  produce a genuinely curved (non-triangular) free-flow branch, and a through-origin
  linear fit to such a model can be biased, with a fitted apex exceeding the model's
  own highest observed flow.
- Don't assume the textbook `w=(l+g)/tau`/`q_max` closed-form formulas hold for every
  car-following model — verify per model; only the jam-density relation
  (`k_j=1/(length+minGap)`) is a safe cross-model generalization.
- Before concluding a wave-speed measurement disagrees with kinematic-wave theory,
  check whether the measured state actually reaches the density the prediction
  assumes, and whether the observed transition is a genuine density-front shock.
- Test capacity drop on both a merge-requiring and a lane-change-free bottleneck
  separately — it is largely, but not exclusively, a lane-changing phenomenon.
- A car-following model's multi-lane discharge past a moving bottleneck can be
  limited by its lane-changing model rather than its fundamental diagram — test this
  explicitly.
- Matching free-flow speed and capacity across car-following models does not
  guarantee matched queueing/spillback behavior — calibrate wave speed and jam
  density as separate targets if downstream queueing predictions matter.
- Check `collisions`, not just `teleports`, at every cell of a congested-regime
  sweep — an unusually large seed-to-seed variance is an early warning sign of
  collision contamination that can silently distort a reported statistic.

See `validate-kinematic-wave-theory-across-car-following-models` for the full
ring-construction, FD-fitting, wave-measurement, and moving-bottleneck methodology,
including three reusable implementation gotchas (ring under-filling, a model-specific
ring-size-dependent free-speed artifact, and a multi-lane E1 station lane-pooling bug
that can silently halve a measured discharge flow).
