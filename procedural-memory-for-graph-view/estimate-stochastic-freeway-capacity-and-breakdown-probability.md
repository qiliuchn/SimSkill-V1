---
name: estimate-stochastic-freeway-capacity-and-breakdown-probability
description: Use this skill when the user wants freeway/merge-bottleneck CAPACITY treated as a random variable rather than a fixed number — estimating a breakdown-probability-vs-flow curve, fitting a capacity distribution (Kaplan-Meier / Weibull / log-normal) to censored SUMO detector data, computing a reliability-based design flow (e.g. the flow sustainable at 5%/10% breakdown probability), or checking whether a deterministic "capacity" figure from a queue-discharge probe is actually a low percentile of the true capacity distribution rather than its mean. Also covers a critical SUMO gotcha: default collision detection produces a massive false-positive rate at a merge whenever actionStepLength exceeds vType tau, which will corrupt any breakdown-detection pipeline that filters on collision events unless corrected. Trigger on mentions of stochastic capacity, capacity breakdown, breakdown probability, Kaplan-Meier, censored capacity data, reliability-based design, or capacity drop distribution.
---

# Estimate Stochastic Freeway Capacity and Breakdown Probability

**Every deterministic "capacity" figure elsewhere in memory for a
comparable bottleneck is a low percentile of a real, non-degenerate
capacity distribution — not its mean.** Verified on 1503 seeded day-run
simulations of a single-merge freeway bottleneck (198 uncensored + 1267
censored breakdown observations from 200 replicated demand-ramp days).

## SUMO's capacity variability is real, not degenerate — but only after correcting for counting noise

Fitting a Weibull distribution by maximum likelihood to the censored
capacity sample (Kaplan-Meier product-limit classification: an
"uncensored" observation is the pre-breakdown flow immediately preceding
a detected breakdown; a "censored" observation is any interval that
carried a flow without breaking down) gave shape k=13.51, scale=3992
veh/h, mean 3842 veh/h, **coefficient of variation 9.04%** — squarely
inside the field-observed 5–12% band (Brilon/Elefteriadou), and never
below it across any of 47 well-identified breakdown-definition cells
tested. **SUMO does reproduce real stochastic-capacity behavior**, this is
not an artifact of insufficient stochasticity. Removing Poisson
arrival-counting noise via a quadrature (additive-variance) correction —
an informal but reasonable approximation, not an exact deconvolution —
drops the estimate to 7.30%, still inside the field band. A log-normal
fit was marginally preferred by AIC (3333.3 vs 3337.3) — report both, the
difference is not decisive.

## Reliability-based design statement

The flow rate sustainable at a stated breakdown probability, not the mean
capacity, is the design-relevant quantity:

- **5% breakdown probability: 3204 veh/h** (1602 veh/h/lane), bootstrap
  CI [3156, 3259] (400-resample, day-level cluster bootstrap)
- **10% breakdown probability: 3380 veh/h** (1690 veh/h/lane), CI [3335,
  3433]
- The fitted Weibull **mean** (3842 veh/h) itself carries a **44.9%**
  breakdown probability — using a mean or a typical single-run "capacity"
  as a design flow is not a conservative choice; it is close to a coin
  flip.

## A deterministic queue-discharge "capacity" probe measures roughly the 3–5th percentile, not the mean — checked from both directions

Re-running memory's own existing deterministic capacity methods
(permanently-queued discharge probe; flat-oversaturation probe) on this
exact bottleneck gave 3077 veh/h and 3197 veh/h respectively. Evaluated
against the fitted stochastic distribution's own CDF, these land at the
**2.9th and 4.8th percentile** — not anywhere near the mean. Checked from
the other direction for consistency: the stochastic experiment's own
measured post-breakdown queue-discharge flow (3073.9 veh/h, averaged
across all 198 breakdown events) matches the standalone queue-release
probe to **0.094%** — the two methods are measuring the *same* quantity
(low-percentile discharge rate), just by different routes. **A
deterministic queue-discharge "capacity" figure is a legitimate,
reproducible measurement of a specific low-percentile discharge rate — it
is not comparable to HCM's capacity (which is closer to a central
tendency) or to a stochastic mean, and any existing skill or page
reporting a single "capacity" number for a bottleneck should be read as
reporting this percentile, not the distribution's center.**

## A critical, high-impact gotcha: SUMO's default collision output is dominated by false positives at a merge

**19,796 raw `--collision-output` flags occurred across the study's
merge-bottleneck runs; only 28 were genuine** once
`--collision.mingap-factor 0` was set (verified: pre-breakdown flow,
breakdown time, and insertion counts are bit-identical between the
default and corrected collision-handling settings across 8 probe days —
confirming the flag setting only affects collision *detection*
sensitivity, not simulated vehicle behavior). **Root cause, verified**:
whenever `actionStepLength` exceeds the controlling vType's `tau`
(car-following desired time headway), SUMO's default collision-warning
threshold flags normal close-following as a collision. Direct mechanism
test: across 125 days spanning 3 heterogeneity arms, **every single day
where no vehicle's `tau` fell below the run's `actionStepLength` produced
exactly zero flags**; the correlation between the vType-tau-below-share
and flag count was strongly positive (Spearman 0.62–0.92 across arms).
**Any study that filters simulation runs on "zero collisions" as a
validity gate at a merge, weaving, or other close-following-heavy
location must set `--collision.mingap-factor 0` (or otherwise verify
`actionStepLength ≤ min(tau)`) or risk discarding the large majority of
genuinely valid runs as false failures.**

## Capacity drop: report the full distribution, and correct for counting noise before testing correlations

Per-event capacity drop (pre-breakdown flow minus that event's own
subsequent discharge flow): signed mean **+446.2 veh/h (12.15%)**, median
451.2, but a wide spread (p05 −27.6, p95 876.0) with **5.56% of events
showing a negative "drop"** (discharge exceeding pre-breakdown flow) —
report the distribution, not just the mean, since a mean alone hides that
one case in eighteen is not a drop at all. **77.1% of the per-event
spread is attributable to Poisson counting noise**, not genuine
event-to-event heterogeneity in the drop mechanism — check this before
interpreting spread as physically meaningful.

Testing whether drop magnitude correlates with pre-breakdown flow
requires correcting for the fact that the pre-breakdown flow itself is
noisily measured (classical attenuation bias): the **disattenuated**
regression slope of discharge flow on pre-breakdown flow is 0.512±0.052
(z=−9.3 versus the null of no relationship, i.e. slope=1) — larger
pre-breakdown flows genuinely produce larger absolute drops, but less than
proportionally. Testing drop against recovery hysteresis is a genuine
case where controlling for a confound reverses the naive answer: the raw
correlation (r=−0.167, p=0.018) looked like a real, moderate negative
relationship, but **controlling for pre-breakdown flow via residualization
flips it to a small, non-significant positive value (r=+0.094, p=0.19)**
— the naive correlation was itself substantially an artifact of both
quantities depending on pre-breakdown flow. **Always residualize against
the shared driving variable before interpreting a correlation between two
quantities that both plausibly depend on flow level.**

## The breakdown definition moves the answer more than almost anything else in the study — sweep it explicitly

Across 47 well-identified (control-type, station, threshold, persistence,
aggregation-interval) combinations, the estimated 5%-breakdown-probability
design flow spanned **2045–3249 veh/h — a 58.9% range** — restricted to
stations measuring total (not just mainline) flow, still 2321–3249
(40.0%). **Detector station placement alone can make breakdown
unobservable**: a station just downstream of the merge (`dn2` in this
study) detected zero breakdowns in 22 of 32 tested definition cells; a
station just upstream of the merge itself (`mrg`) detected zero in only 2
of 32 — placing the detector at the actual bottleneck location, not
merely "near" it, is essential. **Aggregation interval matters
substantially too**: 1-minute aggregation inflated the fitted mean
capacity by +30.09% and the 5%-probability flow by +19.59% relative to
5-minute aggregation from the same raw data — always state the
aggregation interval alongside any stochastic-capacity figure, and prefer
count-weighted (not simple) averaging when re-aggregating finer intervals
into coarser ones (unweighted averaging of 1-minute speeds erred by up to
9.48 km/h against the native 5-minute output in this study, enough to
cross a common 80 km/h breakdown threshold).

## Driver heterogeneity has a non-monotone effect, and the obvious mechanism test failed — reported as a genuine unexplained result

Both *less* heterogeneous (0.25× the baseline speedFactor/tau/sigma
spread, p=0.0017) and *more* heterogeneous (2.0×, p=0.0041) driver
populations produced *lower* mean capacity than the baseline — a
non-monotone relationship, not the naive "more variability degrades
capacity monotonically" story. Higher heterogeneity did widen the fitted
capacity distribution itself (shape k 13.47→10.21, CV 9.07%→11.80%), which
is intuitive; the *level* effect is not. The obvious candidate mechanism —
that heterogeneity changes gap availability at the merge — was tested
directly (paired merge-lane headway comparisons across CRN days) **and
failed to reach significance at the merge lane specifically** in either
direction (n=12 CRN days). This null-mechanism-but-real-effect
combination is reported honestly rather than papered over with a
post-hoc story; the true mechanism remains unidentified.

## Ramp-share is the dominant fragility lever — far more than heterogeneity

Holding total demand fixed and varying the ramp-vs-mainline split:
breakdown occurred on only **8.3% of days (10/120) at a 10% ramp share**,
versus **100% of days at both 20% and 30% ramp share**. The 10%-ramp-share
arm's capacity distribution is honestly flagged as **statistically
unidentified** (the Kaplan-Meier survival curve never falls below 95.7%
survival, so a distribution fit would be extrapolating far past the data)
rather than reported with false precision. Comparing the two identified
arms, the 5%-probability flow fell from 3188 to 2974 veh/h moving from
20% to 30% ramp share. **Demand split at a merge is a more consequential
fragility variable than driver-population heterogeneity in this study.**

## Ramp metering and variable speed limits did not shift the breakdown-probability curve at all — the demand ramp used here cannot test true prevention

Comparing do-nothing against ALINEA (two setpoints) and VSL (reactive and
proactive), all six arms broke down on **100% of days**, with 5%-flow
estimates overlapping across arms (3171–3207 veh/h, confidence intervals
overlapping). **Neither control strategy prevented breakdown or
meaningfully shifted the capacity distribution** in this experimental
design — because demand was deliberately ramped past capacity on every
day, which tests upper-tail compression/queue-management behavior, not
breakdown *prevention*. ALINEA's real, measurable benefit showed up
elsewhere: breakdown **duration** fell 14.5–20.1%, at a cost of **+65–72%
`departDelay`** (ramp queuing) — a genuine tradeoff, not a free win.
**Reactive VSL was a structural null by construction**: it triggered
*after* breakdown had already begun on 99 of 100 days, verified directly
from activation-timing logs, so it could not have prevented what it never
saw coming. A **proactive** variant that triggered before breakdown on 88
of 100 days *still* failed to shift the distribution — ruling out
reaction-timing as the sole explanation and leaving the null as a genuine
finding about VSL's effectiveness at this bottleneck, not merely an
artifact of a badly-timed reactive trigger.

## Absolute capacity level is not converged across step length — the coefficient of variation is far more robust

CRN-paired comparisons against a dt=0.25 s reference found the fitted
mean capacity itself shifts substantially with simulation step length:
+14.76% at dt=1.0 s, +8.23% at dt=0.5 s (the step length used throughout
this study), and −4.95% moving to dt=0.1 s (all differences p<0.006).
**Absolute stochastic-capacity figures from this method should be treated
as accurate to no better than roughly 10–15% across common step-length
choices.** The **coefficient of variation**, in contrast, stayed
comparatively stable (7.43–9.60%) across the same step-length sweep —
the shape/relative-spread finding is far more robust than the absolute
level, and should be reported with that distinction made explicit.

## Gotchas

- Use `--collision.mingap-factor 0` (or verify `actionStepLength ≤
  min(tau)` across the fleet) before trusting any collision-based
  validity filter at a merge or other close-following-heavy location.
- Detector placement determines whether breakdown is observable at all —
  place the primary detection station at the actual bottleneck, not
  merely nearby.
- State the aggregation interval with any stochastic-capacity figure, and
  use count-weighted (not simple) re-aggregation across time windows.
- Always residualize a candidate correlate of capacity drop against
  pre-breakdown flow before interpreting the correlation, since both
  quantities plausibly share that dependence.
- A demand-ramp-to-guaranteed-breakdown experimental design tests
  control's effect on breakdown *severity/duration*, not *prevention* —
  use a design with demand levels that stay below capacity on some days
  if breakdown prevention itself is the question.
- State the simulation step length with any absolute stochastic-capacity
  figure; prefer the coefficient of variation as the more portable,
  step-length-robust result.

See `quantify-sumo-run-to-run-variability` for the CRN/replication design
this skill's day-level bootstrap and paired comparisons build on,
`choose-time-discretization-and-integration-method` for the step-length
discipline behind the dt-convergence caveat, and
`model-freeway-weaving-segment` / `compare-zipper-vs-default-merge-at-lane-drop`
for the deterministic queue-discharge capacity methods this skill's
percentile-mapping finding retroactively qualifies.
