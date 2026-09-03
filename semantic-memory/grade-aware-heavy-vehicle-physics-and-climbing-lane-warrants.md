---
summary: SUMO's road car-following models are completely grade-blind (0.0% speed deviation across Krauss/IDM/EIDM/ACC/CACC/W99 at grades up to 6%, since grade feeds only emission/energy bookkeeping), repairable only via a custom TraCI controller applying a physics-derived setMaxSpeed ceiling (validated to 0.00-0.67% error against an independent RK4 integration, safe by construction since it never overrides car-following); using this repair, grade-blindness was found to flip climbing-lane engineering decisions by roughly 29x in benefit magnitude, the AASHTO speed-reduction warrant triggers far more permissively than the actual delay-benefit knee under realized traffic, general-purpose added lanes are used mainly by passing cars rather than trucks, restricting the lane to trucks has a genuine truck-share-dependent crossover, and the uphill capacity-loss mechanism does not have a symmetric downhill counterpart.
keywords:
  - grade-aware-vehicle-dynamics
  - climbing-lane
  - truck-crawl-speed
  - AASHTO-truck-performance-curve
  - heavy-vehicle-factor
  - weight-to-power-ratio
  - grade-blindness
created: 2026-08-07T03:22:15
last_updated: 2026-08-07T03:22:15
sources:
  - "[[episodic-memory/2026-08-07_03-18-19/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_03-18-19/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[rail-simulation-and-railsignal]]"
related_skills:
  - model-grade-aware-heavy-vehicle-performance-and-climbing-lanes
  - measure-heavy-vehicle-passenger-car-equivalent
  - model-road-gradient-effects-on-energy
  - evaluate-two-lane-highway-with-hcm-and-passing-lanes
  - model-vclass-lane-permissions
  - set-vehicle-state
related_skills_for_graph_view:
  - "[[model-grade-aware-heavy-vehicle-performance-and-climbing-lanes]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[evaluate-two-lane-highway-with-hcm-and-passing-lanes]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[set-vehicle-state]]"
---

# Grade-Aware Heavy-Vehicle Physics and Climbing-Lane Warrants

`[[heavy-vehicle-passenger-car-equivalent-in-sumo]]` documented that SUMO's default car-following models are grade-insensitive; this page holds the follow-up: a re-confirmation showing the null result is total (not partial), the construction and validation of a repair, and what that repair reveals about climbing-lane design once trucks can actually lose speed on a grade. See `model-grade-aware-heavy-vehicle-performance-and-climbing-lanes` for the full methodology.

## The gap is total, and only one native lever touches it

Full speed-distance profiles across six car-following models (Krauss, IDM, EIDM, ACC, CACC, W99) at four grades (0/2/4/6%) showed **exactly 0.0% deviation at every checkpoint for every model** — not a partial effect masked by noise, a complete absence of grade response in every stock road car-following model tested. Native vType/device levers that might plausibly reach longitudinal behavior were tested and found not to: vehicle `mass` (a 10x change produced an identical trajectory), `emissionClass`, and battery-device power/drag parameters all feed only energy/emission bookkeeping, confirmed by producing zero trajectory change. The one native lever that genuinely responded: `carFollowModel="Rail"` with a `trainType`, which collapsed max speed toward zero as grade increased — a real rail-adhesion effect, but disqualified for highway climbing-lane use by its single-track topology and lack of lane-changing (see `[[rail-simulation-and-railsignal]]`).

## The repair: a physics-derived speed ceiling, validated independently

Three candidate mechanisms were tested. Repurposing the Rail car-following model stalled completely above a modest grade with realistic freight parameters and requires incompatible dedicated track. Static per-edge speed authoring produced an unrealistic abrupt speed drop rather than a gradual decay curve, and cannot differentiate trucks by individual weight-to-power ratio. The mechanism that worked: a per-step TraCI controller computing attainable acceleration from tractive effort, grade resistance, rolling resistance, and aerodynamic drag, applied via `setMaxSpeed()` **only** — never overriding actual speed — so SUMO's own car-following model remains solely responsible for collision-avoidance safety while the controller merely caps what's physically achievable.

Validated against a genuinely independent RK4/bisection integration of the same equations of motion (confirmed to share no code with the controller implementation): **0.00–0.67% relative error at every grade ≥2%** across three tested weight-to-power ratios. Reproduced the qualitative AASHTO truck-performance-curve shape — crawl speed approached gradually (within 5% of the analytic terminal value after 1–4 km) rather than instantaneously, monotonically decreasing with grade and with weight-to-power ratio. Proven not to compromise safety: zero collisions/teleports on a mixed-traffic test, and the physics ceiling was confirmed to stay non-binding (at or above actual speed) in essentially every simulation step of a truck genuinely constrained by a slower lead vehicle — the controller caps capability, not behavior. The real, disclosed cost: roughly 10–45x wall-clock slowdown versus a grade-blind run, driven by tens of thousands of TraCI calls per simulation.

## What became measurable once grade reached the vehicles

**Grade-blindness doesn't just under-predict a magnitude — it can flip the engineering decision.** At a severe grade/length combination, grade-aware simulation found a climbing lane's car-delay benefit roughly an order of magnitude larger than the largest effect the grade-blind model could produce anywhere in the same sweep. A naive "is there a statistically significant benefit" test can pass under both models (any added lane relieves some baseline friction regardless of grade) — the test that actually matters for a warrant decision is the *magnitude*, and only the grade-aware model shows the magnitude a real economic warrant would act on.

**The AASHTO 15 km/h (10 mph) speed-reduction criterion and the delay-based economic warrant are not interchangeable, and can disagree substantially under realized (congested) conditions.** In one verified sweep, the speed-reduction criterion was exceeded in *every* tested grade/length combination — including the mildest — while a statistically distinguishable delay benefit only appeared at the longer/steeper combinations and required a high enough truck share. The speed-reduction criterion, measured under real mixed traffic rather than clean free-flow conditions, is a substantially more permissive (liberal) trigger than the economic knee; treating it as a stand-in for "the lane will pay off" risks recommending lanes that don't clear a delay-based benefit test.

**An unrestricted (general-purpose) added lane over a grade functions mainly as a car-passing lane, not a truck lane.** Trucks are power-limited on a grade, not congestion-limited, so they have little independent incentive to change into an added lane; measured truck use of a GP climbing lane ran from near-zero up to the low teens percent across tested conditions, while passing cars used it substantially (roughly half of car traffic in some cells) specifically to get around slow trucks stuck in the base lanes. A lane restricted to trucks/slow vehicles forces ~100% truck usage by construction — the two variants are not interchangeable in practice, and which one is preferable has a genuine truck-share-dependent crossover: restriction measurably hurts overall car delay at low truck share (dedicating capacity to a small minority) and measurably helps at high truck share.

**The uphill capacity-loss mechanism does not automatically have a symmetric downhill counterpart.** On the same facility, grade-aware behavior produced a genuine, statistically significant served-flow (capacity) loss uphill relative to grade-blind, while the corresponding downhill direction showed no significant served-flow change at any tested combination — even though grade-aware trucks were somewhat slower than grade-blind trucks in *both* directions (roughly 3x larger speed reduction uphill than downhill in one measured comparison). Downhill effects are better characterized by speed-differential/variance mechanisms than by a capacity mechanism, and even that should be verified per-direction rather than assumed — a genuine variance increase was found in one tested downhill condition but not in the single tested uphill condition, so "opposite direction" should not be read as "mirror-image effect on every metric."
