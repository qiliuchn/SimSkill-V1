---
summary: Max-pressure signal control driven only by a random sample of connected vehicles beats a coordinated fixed-time plan from about 10% market penetration and reaches the perfect-information ceiling at about 50%, but never beats a well-tuned fully-detected actuated controller on network-wide mean delay because that ceiling itself does not; control quality collapses far faster than estimation accuracy below 5% penetration, driven by Binomial(N,p) sampling variance and by the 1/p discreteness of count-based estimates.
keywords:
  - connected-vehicles
  - market-penetration
  - detector-free-signal-control
  - probe-vehicle-data
  - max-pressure
  - phase-starvation
  - break-even-penetration
created: 2026-08-05T06:00:00
last_updated: 2026-08-05T06:30:00
sources:
  - "[[episodic-memory/2026-08-05_06-00-00/attempts/attempt-1/action-agent-output.json]]"
related_pages:
  - "[[max-pressure-signal-control]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[actuated-traffic-signals]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[information-penetration-and-congestible-routing]]"
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
  - "[[webster-method]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[network-link-criticality-and-proxy-validation]]"
related_skills:
  - implement-detector-free-cv-adaptive-signal-control
  - implement-maxpressure-traci-controller
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - control-signals-with-actuated-tls
  - design-arterial-signal-progression-and-verify-bandwidth
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[implement-detector-free-cv-adaptive-signal-control]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Connected-Vehicle Penetration and Detector-Free Signal Control

If a signal controller can see only the subset of vehicles that are connected, how many need to
be connected before it can replace loop detectors? The findings below come from a verified
312-run study on a 4-intersection arterial at v/c ≈ 0.88, comparing a coordinated fixed-time
plan, a tuned fully-detected actuated controller, perfect-information max-pressure, and
CV-driven max-pressure with two estimators across penetrations of 2–100 %, 10 seeds each
(see `implement-detector-free-cv-adaptive-signal-control`).

## The break-even penetration depends entirely on which benchmark and which metric

**Against a coordinated fixed-time Webster plan, the break-even is about 10 %** — and it is the
same for a naive and a sophisticated estimator. At 5 % the CV controller is statistically
indistinguishable from the fixed plan; at 10 % it is significantly better (−48 ± 6 s mean
delay); at 2 % it is dramatically worse (+91 ± 30 s). On side-street delay alone the break-even
arrives one step earlier, at 5 %.

**Against a well-tuned fully-detected actuated controller there is no break-even on
network-wide mean delay at any penetration, and the reason is the control law rather than the
sensing.** Perfect-information max-pressure — the information upper bound, with true per-lane
queues from `getLastStepHaltingNumber` — was itself statistically tied with actuated
(+0.6 ± 4.1 s, not significant). A CV controller cannot beat a benchmark that its own
information ceiling does not beat. **Always establish the perfect-information ceiling before
interpreting a penetration sweep**; without it, "CV control never beat actuated" would be
misread as a sensing limitation.

**Max-pressure is a redistribution, not a uniform improvement, so a single network-wide number
hides the whole effect.** Against actuated, perfect-information max-pressure was 37.8 ± 4.2 s
*worse* on the arterial and 24.1 ± 6.2 s *better* on the side street, with a 144 s reduction in
95th-percentile side-street delay and a 37 % reduction in maximum cross-street queue. Where
max-pressure genuinely dominates, CV-driven control does reach a break-even against actuated:
**20 % penetration for mean side-street delay and 10 % for 95th-percentile side-street delay.**
Report arterial and cross-street cohorts separately or the result is uninterpretable.

**The perfect-information ceiling is reached at about 50 % penetration.** The position-based
estimator at p = 50 % was within its confidence interval of the perfect-information controller
on every cohort. Half the fleet buys everything that knowing every vehicle would buy, for this
controller on this corridor. Between 10 % and 50 % the residual loss is 5–26 s of mean delay;
below 10 % it is 26–165 s and rising steeply.

## Control degrades much faster than estimation, and the cliff is at ~5 %

Between 5 % and 2 % penetration, queue-estimate RMSE rose by a factor of 1.4 while the delay
penalty over the actuated benchmark rose by a factor of 2.3. Control falls off a cliff earlier
than estimation accuracy, for two specific small-sample reasons — "less data is worse" is not
the mechanism:

**1. Binomial sampling variance overwhelms the signal.** With `K ~ Binomial(N, p)` observed
vehicles in a queue of `N`, the `k/p` estimate is unbiased with coefficient of variation
`√((1−p)/(Np))`. For a typical approach queue of 14.5 vehicles that is 0.53 at p = 10 %, 0.82 at
p = 5 % and **1.82 at p = 2 %** — the standard deviation exceeds the quantity being estimated.
A max-pressure controller takes an argmax over several such estimates, so once noise exceeds
signal the argmax is nearly uniformly random. **A randomly-ordered signal is worse than a fixed
plan**, because it randomises phase order without randomising demand.

**2. Discreteness: the estimator's quantum can exceed the queue itself.** A count-scaled
estimate lives on the lattice `{0, 1/p, 2/p, …}`. At p = 2 % the quantum is 50 vehicles, larger
than any queue in the network — measured over ~41 000 decision epochs the naive estimate took
only **6 distinct values** and was exactly zero 77.5 % of the time. The pressure comparison is
then decided by *which* approach happens to contain a probe at all, not by how long its queue
is. This is a collapse of the estimator's **resolution**, discontinuous in p, and it is what
makes the degradation a cliff rather than a slope. The distinct-value count and the
fraction-exactly-zero make it visible in a way RMSE does not.

## Phase starvation follows the Binomial law exactly

The probability that an approach with a genuinely non-empty queue of `N` vehicles is observed
with **zero** connected vehicles is `(1−p)^N`, and this holds essentially exactly in
simulation — for the naive estimator over queues of N = 1–8, absolute error is below 0.02 in
32 of 40 measured cells across p ∈ {2, 5, 10, 20, 50} %, with the worst-case cell still within
0.04. Match quality is best at small N and low p and degrades somewhat at larger N, where the
residual excess is the positive correlation between connectivity states within a platoon
(vehicles arrive in platoons, so successive vehicles' connectivity draws are not perfectly
independent even though the per-vehicle draw is).

Measured blindness on a cross-street approach and its consequence:

| penetration | non-empty approach seen with 0 CVs | worst gap between cross-street services |
| --- | --- | --- |
| 2 % | 62 % | 430 s (up to 608 s) |
| 5 % | 39 % | 298 s |
| 10 % | 23 % | 226 s |
| 20 % | 11 % | 189 s |
| 50 % | 2.6 % | 187 s |
| fixed-time reference | — | 67 s |
| perfect-information max-pressure | — | 93 s |

At 2 % penetration a cross street can wait over ten minutes for green, and 95th-percentile
side-street delay reaches 868 s against 427 s under actuated control. **A blind approach is not
a noisy approach — it is an approach the controller believes is empty**, which is why
starvation, not estimation error, is the dominant low-penetration failure mode.

Note also that at low penetration much of the user cost migrates out of the usual delay metric:
mean SUMO `departDelay` (queue-at-origin, *not* included in `timeLoss`) was 0.8 s at p ≥ 10 %
but 34.9 s with a maximum of 775 s at p = 2 %.

## Estimator choice: a crossover, and a bias floor penetration cannot fix

Two estimators, measured on matched traffic (one open-loop run, both estimators at every
penetration evaluated against the same ground-truth states):

- **Count scaling**, `q̂ = (observed stopped CVs)/p`. Close to unbiased at every penetration for
  the two arterial movement groups (|bias| mostly ≤ 0.55 veh), **exact** at p = 100 % — a useful
  end-to-end validation — but the bias is **movement-group-dependent, not uniformly small**: the
  busier cross-street group reaches |bias| up to ~0.99 veh at low penetration. Its dominant
  problem is variance and discreteness at low p, not bias.
- **Last-stopped-probe / shockwave** (Comert–Cetin spirit): from the upstream-most stopped
  probe at distance `d` behind the stop bar, `q̂ = d/spacing + 1 + (1−p)/p`, where `(1−p)/p` is
  the mean Geometric count of unobserved vehicles behind the last probe. Position, not count,
  carries the information — one probe deep in a queue reveals the whole queue behind it.

**The crossover penetration is movement-group-dependent, not a single number.** Measured
per-movement RMSE crossover (naive vs. shockwave) on the busiest arterial through movement sits
as low as p = 2–5 %; on the cross-street movement it sits around p = 10–20 %; on the lighter
arterial left-turn movement it is later still, around p = 20–50 %. **The position-based
estimator carries a structural bias floor that more probes cannot remove** — on the arterial
through movement its bias runs from about −0.4 veh at p = 2 % up to +5.4 veh at p = 100 %,
crossing from negative to positive as penetration rises, because converting a distance to a
vehicle count at a fixed jam spacing over-counts whenever the standing queue contains larger
gaps, and that over-count grows as more (and therefore more representative) probes are
available to trigger it. This is the same class of finding as the GPS ping-period bias floor in
[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]: a sampling-*mechanism* bias, not
sampling noise. **Practical takeaway: don't quote a single crossover penetration for a corridor
— measure it per movement, since a busy through movement and a lighter turn movement can favor
opposite estimators at the same nominal CV penetration.**

Measured in control terms, the better estimator **closes about 24–39 % of the delay gap in the
5–20 % penetration band**, but closes **nothing at 2 %** (a better formula applied to an empty
observation is still an empty observation) and nothing at 50 %+ (its bias floor has overtaken
the count estimator's shrinking variance).

## Bound the failure; do not imagine the data

Two mitigations for low-penetration starvation behave in opposite directions, so they must be
ablated separately:

- **A per-phase max-out / force-off timer works.** It reduced delay by 26.5 s at p = 2 %
  (significant) and flattened the worst phase-service gap to a constant ~150–166 s at *every*
  penetration. It is, however, significantly *harmful* once information is adequate
  (+9.2 s at p = 10 %) — a fixed max-out then overrides correct decisions.
- **Imputing unobserved approaches from an exponentially-smoothed memory actively hurts exactly
  where it is meant to help**: added on top of the force-off timer it cost **+66.6 s at
  p = 2 %**. With most non-empty approaches invisible, carrying a stale non-zero estimate
  forward makes the controller sticky precisely where it is least informed. It pays off only at
  high penetration (significant gains from ~20 % upward).

The transferable principle: **bound the failure, don't imagine the data.** A max-out timer
costs nothing when information is good and rescues the tail when it is not; imputation helps
only once you already have enough data.

## Decision agreement is a poor proxy for outcome

Agreement between a CV controller and the perfect-information controller on identical traffic
states rose smoothly with penetration (29 % at p = 2 %, 61 % at 10 %, 78 % at 50 %, and exactly
100.00 % for the count estimator at p = 100 %). But **agreement did not rank the controllers the
way delay did**: the position-based estimator had *lower* agreement than the count estimator
above 20 % penetration while performing equally or better, and the best high-penetration variant
had the lowest agreement of all. Greedy instantaneous max-pressure is not the optimum, so
disagreeing with it is not the same as being wrong. Use agreement as a diagnostic of the
information channel, never as a performance surrogate.

## Verifying that a CV controller is genuinely blind to non-CV state

Accidental ground-truth leakage is the easiest way to produce a good-looking result, so
isolation must be demonstrated rather than asserted. The structural measure that makes this
cheap is to **subscribe only connected vehicles** to TraCI variables — a non-connected
vehicle's state is then never retrieved at all, so it cannot be read. Beyond that, four
empirical checks, all of which held in the verified study:

1. A runtime guard around every ground-truth getter recorded **zero** violations across 276 CV
   runs (internal `:`-lane reads, used by the all-red clearance interlock, were exempted and
   counted rather than allowed silently).
2. At p = 0 the controller collapsed to its documented fixed-time fallback: **100 %** of served
   greens followed the program's cyclic order, against 58–62 % for the same controller at
   p = 10 %.
3. Replaying recorded ground-truth states through the whole pipeline with 20 non-connected
   vehicles added, or with every non-connected vehicle deleted, left both the observation and
   the decision bit-identical in **191/191** states.
4. **Positive controls are mandatory** — the mirrored CV-side perturbation (adding 20
   *connected* vehicles) changed the observation 191/191 times and the decision 34.6 % of the
   time. Without the mirror, an isolation test cannot distinguish "isolated" from "inert".

A fifth check is worth running for its own sake: at p = 100 % the count estimator must
reproduce `getLastStepHaltingNumber` exactly (verified bias 0.000, RMSE 0.000) and must agree
with the perfect-information controller on every decision epoch (verified 1.0000 ± 0.0000).
That single result validates the entire observation → estimation → decision chain.

## Scope

The break-even penetrations above are corridor-specific: one 4-intersection arterial at
400 m spacing, protected arterial lefts, v/c ≈ 0.88 at the critical intersection, a homogeneous
fleet, and connected vehicles assumed to report position and speed with no error and no latency.
The transferable content is the mechanisms — Binomial blindness, the `1/p` discreteness cliff,
the estimator crossover and its bias floor, the force-off-vs-imputation asymmetry, and the
requirement to establish a perfect-information ceiling before reading any penetration sweep.

**Known limitation — undisclosed survivorship censoring at the worst-starvation cells.** The
runs were launched with a fixed `--end` and no `--tripinfo-output.write-unfinished`, so any
vehicle still in the network at the simulation horizon is silently dropped from `tripinfo`
rather than counted with a penalty. This does not affect most cells (all 6,873 vehicles
complete for the fixed-time and actuated benchmarks, and for most CV cells), but it bites hard
in exactly the regime this page is about: at p = 2 % under the naive estimator, completion fell
as low as 4,498 of 6,873 vehicles (65 %) in the worst seed, with several other p = 2 % seeds
also short. The reported delay statistics at p = 2 % are therefore a **survivor-biased
subsample of the worst-congested cells** — vehicles that never escaped gridlock within the
horizon are excluded rather than charged a large delay, so the true severity of the p = 2 %
starvation regime is understated by the headline numbers on this page. Re-running those cells
with unfinished trips counted (and a stated penalty, e.g. horizon-censored delay as used
elsewhere in this project, see [[network-link-criticality-and-proxy-validation]]) would be
needed before citing an exact p = 2 % delay figure in a downstream decision; the qualitative
conclusion — that p = 2 % is a severe starvation regime — is unaffected and would only get
stronger, not weaker, under a corrected accounting.
