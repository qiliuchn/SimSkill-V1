---
summary: SUMO's measured stop/go boundary at signal yellow onset follows a clean closed form (min(v²/2a, v*yellow)) implying zero perception-reaction time, and a genuine dilemma zone (crashes forced) does not emerge from SUMO's default driving model — non-compliance must be deliberately injected to study it; measured lost time diverges from the assumed yellow+all-red intergreen in a fleet-composition-dependent direction (shifting Webster's optimal cycle length by up to 22%); all-red's safety benefit has a narrow effective range tied to specific intersection geometry rather than improving smoothly with length; heavy vehicles shift the effective stopping boundary substantially while grade — despite a large analytic prediction — barely moves SUMO's measured boundary at all (a genuine SUMO modeling gap); capacity-optimal and safety-optimal intervals differ in most tested cells; and a CRN-paired statistical test reversed an unpaired comparison's headline conclusion about a dilemma-zone detector placement.
keywords:
  - dilemma-zone
  - clearance-interval
  - yellow-interval
  - all-red
  - red-light-running
  - ITE-yellow-formula
  - lost-time
  - signal-safety
created: 2026-08-02T23:30:00
last_updated: 2026-08-04T20:00:00
sources:
  - "[[episodic-memory/2026-08-02_23-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_23-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[webster-method]]"
  - "[[surrogate-safety-measures]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[railroad-preemption-of-nearby-signalized-intersections]]"
related_skills:
  - design-signal-change-and-clearance-intervals
  - create-single-intersection
  - control-signals-with-actuated-tls
  - measure-saturation-flow-and-validate-webster-method
  - analyze-intersection-safety-with-ssm
related_skills_for_graph_view:
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[create-single-intersection]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[analyze-intersection-safety-with-ssm]]"
---

# Signal Clearance Intervals: Dilemma Zone and Safety-Capacity Tradeoff

Signal change and clearance intervals (yellow and all-red timing) are treated as a
hardcoded constant in nearly every other signal-control skill in this project's
memory. This page treats them as a first-class safety-and-capacity design object,
testing whether SUMO's own vehicle dynamics reproduce the classical
traffic-engineering "dilemma zone" and quantifying the tradeoffs involved in
choosing interval length.

## Verified finding: SUMO's stop/go boundary is a clean closed form implying zero perception-reaction time

Measuring SUMO's own stop/go decision boundary at yellow onset via single-vehicle
bisection probes across a speed range found it follows the closed form
`min(v²/2a, v*yellow)` — essentially a deceleration-limited stopping distance
capped by how far a vehicle can travel during the yellow interval itself — fitting
measured data to within about a meter. **This formula implies zero
perception-reaction time**: SUMO's deterministic car-following/junction models
react to a signal-state change essentially instantaneously, unlike the standard
ITE reference formula, which includes a real perception-reaction delay term. The
consequence is a substantially smaller effective stopping boundary than the ITE
formula predicts at the same speed and yellow duration (in one tested case, roughly
half the ITE-predicted distance at highway speed) — a naive comparison between
SUMO-measured and ITE-theoretical boundaries, without accounting for this, will
systematically conclude SUMO's simulated drivers are far more conservative /
capable than the reference formula assumes.

## Verified finding: a genuine dilemma zone does not emerge from SUMO's default driving model

Testing explicitly whether a measurable red-light-running rate (the practical
signature of a real dilemma zone's crash risk) emerges from SUMO's default,
compliance-assuming driving behavior found **exactly zero** red-light-running
events across tens of thousands of yellow-onset decisions when non-compliance
parameters were left at default/absent settings. **SUMO's deterministic, rule-
following driving model does not spontaneously generate the non-compliant behavior
that creates a real-world dilemma zone.** To study dilemma-zone phenomena at all,
non-compliance must be deliberately injected via SUMO's junction-model parameter
family (e.g. parameters controlling how long after a red/yellow onset a vehicle
will still proceed) — a study that assumes SUMO's default behavior will naturally
exhibit dilemma-zone crash risk is making an assumption that does not hold.

## Verified finding: safety-optimal yellow length is a tradeoff between crash types, not a single-metric optimum

Sweeping yellow length while measuring both right-angle conflict exposure
(post-encroachment time at conflict points) and rear-end conflict indicators
(hard-braking event rate) found the two move in **opposite directions** as yellow
lengthens: right-angle exposure genuinely improves, while rear-end conflict
indicators significantly worsen. **The safety-optimal yellow interval is therefore
not simply "as long as possible" — it is a genuine tradeoff between two distinct
crash mechanisms that must be weighed against each other explicitly**, not a
single metric with an interior optimum that a naive one-dimensional sweep would
reveal.

## Verified finding: all-red's safety benefit has a narrow effective range tied to geometry

Sweeping all-red duration and measuring the marginal right-angle-conflict benefit
of each additional second found a statistically significant benefit only at one
specific, identifiable geometry (a wide, high-speed crossing) for the first added
second, with essentially every other tested combination of geometry and additional
all-red duration showing no significant safety benefit while still incurring a
real, statistically significant delay cost. **All-red is not a "more is always
safer" dial** — it has a narrow window of genuine effectiveness that depends on
intersection width and approach speed, and should be sized to that specific
geometry rather than applied as a uniform default across an entire network.

## Verified finding: measured lost time diverges from assumed intergreen in a fleet-dependent direction, with real Webster-cycle consequences

Comparing measured startup-plus-clearance lost time (from stop-line discharge
data) against the commonly-assumed intergreen (yellow + all-red) used as a
lost-time proxy in Webster-style cycle-length calculations found a real,
consistent gap for an all-passenger-car fleet — **and found the gap's sign flips**
once a substantial heavy-vehicle share is introduced into the fleet. Feeding the
measured (not assumed) lost time back into the Webster formula shifted the
computed optimal cycle length by up to roughly a fifth in the tested range, though
at a comparatively small delay cost. **The direction of a Webster-cycle-length
error from using assumed rather than measured lost time depends on fleet
composition, not just a fixed correction offset.**

## Verified finding: heavy vehicles shift the boundary substantially; grade — despite theory — barely does, a genuine SUMO modeling gap

Testing truck share and approach grade as separate factors found genuinely
asymmetric results. **Heavy-vehicle share produced a large, statistically robust
shift** in measured stopping/time-loss behavior, closely matching physical
expectation, including collapsing the measured stop/go boundary to near-zero width
at a sufficiently high truck share (meaning nearly every position becomes a "must
stop" outcome). **Grade, despite the analytic ITE formula predicting a
substantial required-stopping-distance shift over the tested grade range, produced
almost no corresponding change in SUMO's own measured stop/go boundary.** This is
reported as a genuine gap between real-world stopping-distance physics and SUMO's
braking/junction model, not a modeling choice that happens to look different — a
study relying on SUMO's default longitudinal dynamics to represent grade's effect
on signal timing should not expect simulated results to match real-world
downgrade-braking physics.

## Verified finding: capacity-optimal and safety-optimal intervals genuinely differ

Locating both the delay-minimizing and the safety-maximizing interval choice on
the same swept parameter space found they differ in the large majority of tested
configurations, with the safety-optimal choice costing a real and sometimes
substantial delay penalty (ranging from a few percent to nearly half, depending on
configuration, in the tested cases) relative to the capacity-optimal choice. This
confirms the interval-design decision is a genuine, unavoidable tradeoff rather
than a case where a single objectively "correct" value exists independent of
which goal is prioritized.

## Methodological finding: a paired statistical test reversed an unpaired comparison's conclusion

Comparing a dilemma-zone-oriented detector placement against alternative
placements under Common Random Numbers found that an initial **unpaired**
per-configuration confidence-interval comparison suggested the dilemma-zone
placement significantly reduced red-light-running relative to a conventional
placement. **The methodologically correct paired test on the same seed-matched
data found no significant difference between those two specific configurations** —
the placement was only significantly better than a poorly-chosen alternative
placement, and its one genuinely strong, statistically significant effect was on
a metric (extreme, physically implausible emergency braking at red) that was
separately flagged as a likely SUMO modeling artifact rather than a real safety
signal. **Whenever comparing CRN-replicated arms that share seeds, use a paired
test on the seed-matched differences — an unpaired comparison of each arm's own
confidence interval can produce a materially different, and potentially reversed,
conclusion.**

## Practical takeaways

- Compute both the stopping-distance and clearing-distance dilemma-zone boundaries
  and check whether they actually imply a true dilemma zone (`x_c > x_s`) before
  assuming a given yellow/speed combination produces one.
- Do not assume SUMO's default driving model will exhibit red-light-running or
  dilemma-zone risk — it must be deliberately modeled via junction-model
  non-compliance parameters, each verified with a negative control.
- Report yellow-length safety effects on right-angle and rear-end conflicts
  separately — the safety-optimal choice is a tradeoff between them, not a single
  interior optimum.
- Size all-red duration to the specific intersection's width and speed rather than
  applying a uniform value — its safety benefit does not scale smoothly with
  length.
- Measure lost time directly rather than assuming it equals the programmed
  intergreen, and re-check the correction's sign whenever fleet composition
  changes materially.
- Treat a SUMO result that contradicts strong physical theory (like grade's
  near-absence of effect on stopping distance here) as a candidate modeling gap
  to report explicitly, not as evidence against the theory.
- Always use a paired test, never an unpaired per-arm comparison, when analyzing
  CRN-replicated arms that share seeds.

See `design-signal-change-and-clearance-intervals` for the full analytic-reference,
decision-log, non-compliance-injection, and hypothesis-testing methodology.
