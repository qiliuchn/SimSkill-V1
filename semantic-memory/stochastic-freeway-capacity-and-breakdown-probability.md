---
summary: SUMO's freeway-merge capacity is genuinely stochastic, not degenerate — a Weibull fit to 198 uncensored/1267 censored breakdown observations gives coefficient of variation 9.04% (7.30% after removing Poisson counting noise), squarely inside the field-observed 5-12% band — and a deterministic queue-discharge "capacity" probe (the method every other capacity skill in memory uses) measures only the 2.9th-4.8th percentile of that distribution, not its mean, cross-confirmed from both directions; the reliability-based design flow is 3204 veh/h at 5% breakdown probability and 3380 veh/h at 10%, while a critical SUMO gotcha (actionStepLength exceeding vType tau) makes 99.86% of default collision-output flags at a merge false positives.
keywords:
  - stochastic-capacity
  - breakdown-probability
  - kaplan-meier
  - censored-data
  - capacity-drop
  - reliability-based-design
  - weibull-distribution
  - collision-output-false-positives
created: 2026-08-06T00:30:00
last_updated: 2026-08-06T00:30:00
sources:
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/breakdown_observations_base.csv]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/km_main.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/deterministic_vs_stochastic_vs_hcm.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/collision_mechanism.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/capacity_drop_summary.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/capacity_drop_correlations.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/definition_sweep_headline.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/sensitivity_arms.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/mechanism_headways_paired.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/control_arms.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/vsl_activation_timing.json]]"
  - "[[episodic-memory/2026-08-06_00-30-00/outputs/analysis/dt_convergence.json]]"
related_pages:
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[sumo-time-discretization]]"
related_skills:
  - estimate-stochastic-freeway-capacity-and-breakdown-probability
  - quantify-sumo-run-to-run-variability
  - choose-time-discretization-and-integration-method
  - model-freeway-weaving-segment
  - compare-zipper-vs-default-merge-at-lane-drop
related_skills_for_graph_view:
  - "[[estimate-stochastic-freeway-capacity-and-breakdown-probability]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[choose-time-discretization-and-integration-method]]"
  - "[[model-freeway-weaving-segment]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
---

# Stochastic Freeway Capacity and Breakdown Probability

Every capacity figure elsewhere in memory for a freeway bottleneck is a
single deterministic number from a queue-discharge probe. This page
treats capacity as what it actually is — a random variable — via
censored-data survival analysis on 1503 seeded day-run simulations of a
single-merge freeway bottleneck (198 uncensored + 1267 censored breakdown
observations from 200 replicated demand-ramp days), and finds that the
deterministic figures elsewhere in memory are measuring a specific,
reproducible low percentile of that distribution, not its center.

## SUMO's capacity variability is real, not degenerate

Fitting a Weibull distribution by maximum likelihood to the censored
capacity sample (Kaplan-Meier product-limit classification: "uncensored"
= the pre-breakdown flow immediately preceding a detected breakdown;
"censored" = an interval that carried a flow without breaking down) gave
shape k=13.51, scale=3992 veh/h, mean 3842 veh/h, **coefficient of
variation 9.04%** — squarely inside the field-observed 5–12% band, and
never below it across any of 47 well-identified breakdown-definition
cells tested. **SUMO reproduces real stochastic-capacity behavior**; this
is not an artifact of insufficient stochasticity. Removing Poisson
arrival-counting noise (an informal quadrature correction, not an exact
deconvolution) drops the estimate to 7.30%, still inside the field band.
A log-normal fit was marginally preferred by AIC (3333.3 vs 3337.3) —
report both; the difference is not decisive.

## Reliability-based design statement

- **5% breakdown probability: 3204 veh/h** (1602 veh/h/lane), bootstrap
  CI [3156, 3259] (400-resample, day-level cluster bootstrap)
- **10% breakdown probability: 3380 veh/h** (1690 veh/h/lane), CI [3335,
  3433]
- The fitted Weibull **mean** (3842 veh/h) carries a **44.9%** breakdown
  probability — using a mean, or a single typical run's discharge, as a
  design flow is close to a coin flip, not a conservative choice.

## A deterministic capacity probe measures the 3rd–5th percentile, not the mean — checked from both directions

Re-running the standard deterministic capacity methods (permanently-queued
discharge probe; flat-oversaturation probe) on this exact bottleneck gave
3077 and 3197 veh/h respectively. Evaluated against the fitted stochastic
distribution's own CDF, these land at the **2.9th and 4.8th percentile**.
Checked from the other direction: the stochastic experiment's own
measured post-breakdown queue-discharge flow (3073.9 veh/h, averaged
across all 198 breakdown events) matches the standalone queue-release
probe to **0.094%** — the two methods measure the same quantity, a
low-percentile discharge rate, by different routes. **A deterministic
queue-discharge "capacity" figure is a legitimate, reproducible
low-percentile discharge rate; it is not comparable to HCM's capacity
(closer to a central tendency) or to a stochastic mean.** Any existing
skill or page reporting a single "capacity" number for a bottleneck
should be read this way.

## A critical, high-impact gotcha: SUMO's default collision output is dominated by false positives at a merge

19,796 raw `--collision-output` flags occurred across this study's
merge-bottleneck runs; only 28 were genuine once
`--collision.mingap-factor 0` was set (verified: pre-breakdown flow,
breakdown time, and insertion counts are bit-identical between the
default and corrected collision-handling settings, confirming the flag
only affects detection sensitivity, not simulated behavior). **Root
cause, verified**: whenever `actionStepLength` exceeds the controlling
vType's `tau`, SUMO's default collision-warning threshold flags normal
close-following as a collision. Direct mechanism test across 125 days
spanning 3 heterogeneity arms: **every single day where no vehicle's
`tau` fell below the run's `actionStepLength` produced exactly zero
flags** (Spearman correlation between tau-below-share and flag count:
0.62–0.92 across arms). **Set `--collision.mingap-factor 0` (or verify
`actionStepLength ≤ min(tau)`) before using "zero collisions" as a
validity gate at a merge, weaving segment, or other close-following-heavy
location**, or risk discarding the large majority of genuinely valid runs
as false failures.

## Capacity drop: report the full distribution, and correct for counting noise before testing correlations

Per-event capacity drop: signed mean **+446.2 veh/h (12.15%)**, median
451.2, wide spread (p05 −27.6, p95 876.0), with **5.56% of events showing
a negative "drop"** (discharge exceeding pre-breakdown flow). **77.1% of
the per-event spread is attributable to Poisson counting noise**, not
genuine event-to-event heterogeneity. The **disattenuated** regression
slope of discharge flow on pre-breakdown flow (correcting for
measurement error in the predictor) is 0.512±0.052 (z=−9.3 vs. the null
of slope=1) — larger pre-breakdown flows genuinely produce larger
absolute drops, but less than proportionally. Testing drop against
recovery hysteresis illustrates a genuine confound reversal: the raw
correlation (r=−0.167, p=0.018) looks like a real negative relationship,
but **controlling for pre-breakdown flow via residualization flips it to
a small, non-significant positive value (r=+0.094, p=0.19)** — the naive
correlation was substantially an artifact of both quantities depending on
flow level. Always residualize against a shared driving variable before
interpreting such a correlation.

## The breakdown definition moves the answer more than almost anything else in the study

Across 47 well-identified (control-type, station, threshold, persistence,
aggregation-interval) combinations, the 5%-breakdown-probability design
flow spanned **2045–3249 veh/h — a 58.9% range**; restricted to stations
measuring total (not just mainline) flow, still 40.0%. **Detector station
placement alone can make breakdown unobservable**: a station just
downstream of the merge detected zero breakdowns in 22 of 32 tested
cells; a station at the merge itself detected zero in only 2 of 32.
**Aggregation interval matters substantially too**: 1-minute aggregation
inflated the fitted mean capacity by +30.09% and the 5%-probability flow
by +19.59% relative to 5-minute aggregation from the same raw data —
always state aggregation interval alongside any stochastic-capacity
figure, and use count-weighted (not simple) averaging when re-aggregating
finer intervals (unweighted averaging of 1-minute speeds erred by up to
9.48 km/h in this study, enough to cross a common 80 km/h threshold).

## Driver heterogeneity: a non-monotone effect with a failed mechanism test, reported honestly

Both *less* heterogeneous (0.25× baseline speedFactor/tau/sigma spread,
p=0.0017) and *more* heterogeneous (2.0×, p=0.0041) driver populations
produced *lower* mean capacity than baseline — non-monotone, not the
naive "more variability degrades capacity" story. Higher heterogeneity
did widen the fitted distribution itself (CV 9.07%→11.80%), which is
intuitive; the level effect is not. The obvious candidate mechanism
(heterogeneity changing merge-lane gap availability) was tested directly
and **failed to reach significance at the merge lane specifically** in
either direction (n=12 CRN days) — reported as a genuine, unexplained
result rather than papered over with a post-hoc story.

## Ramp share is the dominant fragility lever

Holding total demand fixed and varying ramp-vs-mainline split: breakdown
occurred on only **8.3% of days (10/120) at a 10% ramp share**, versus
**100% of days at both 20% and 30%**. The 10%-ramp-share arm's
distribution is honestly flagged as statistically unidentified (survival
never falls below 95.7%) rather than reported with false precision.
Between the two identified arms, the 5%-probability flow fell from 3188
to 2974 veh/h moving from 20% to 30% ramp share. Demand split at a merge
is a more consequential fragility variable than driver heterogeneity in
this study.

## Ramp metering and VSL did not shift the breakdown-probability curve — by construction

Comparing do-nothing against ALINEA (two setpoints) and VSL (reactive and
proactive), all six arms broke down on **100% of days**, with overlapping
5%-flow confidence intervals (3171–3207 veh/h). Neither strategy shifted
the capacity distribution — because demand was deliberately ramped past
capacity on every day, testing upper-tail compression, not breakdown
prevention. ALINEA's real benefit showed up elsewhere: breakdown
**duration** fell 14.5–20.1%, at a cost of **+65–72% `departDelay`**
(ramp queuing) — a genuine tradeoff. **Reactive VSL was a structural null
by construction**: it triggered *after* breakdown had begun on 99 of 100
days. A **proactive** variant triggering before breakdown on 88 of 100
days *still* failed to shift the distribution — ruling out reaction
timing as the sole explanation and leaving the null as a genuine finding
about VSL's effectiveness here, not merely a badly-timed-trigger artifact.

## Absolute capacity level is not converged across step length; the coefficient of variation is far more robust

CRN-paired comparisons against a dt=0.25 s reference found fitted mean
capacity shifts substantially with step length: +14.76% at dt=1.0 s,
+8.23% at dt=0.5 s (used throughout this study), −4.95% at dt=0.1 s (all
p<0.006). **Absolute stochastic-capacity figures should be treated as
accurate to no better than roughly 10–15%** across common step-length
choices. The **coefficient of variation** stayed comparatively stable
(7.43–9.60%) across the same sweep — report the CV as the more portable,
robust result, distinct from the level.

## Gotchas

- Use `--collision.mingap-factor 0` (or verify `actionStepLength ≤
  min(tau)`) before trusting a collision-based validity filter at a
  merge or close-following-heavy location.
- Detector placement determines whether breakdown is observable at all —
  place the primary station at the actual bottleneck, not merely nearby.
- State the aggregation interval with any stochastic-capacity figure; use
  count-weighted re-aggregation across time windows.
- Residualize a candidate correlate of capacity drop against
  pre-breakdown flow before interpreting the correlation.
- A demand-ramp-to-guaranteed-breakdown design tests control's effect on
  breakdown severity/duration, not prevention.
- State the simulation step length with any absolute stochastic-capacity
  figure; prefer the CV as the more portable result.

See `estimate-stochastic-freeway-capacity-and-breakdown-probability` for
the full build/measurement/estimation workflow, and
[[sumo-stochastic-variability-and-replication-design]] for the CRN and
day-level bootstrap design this page's estimation method builds on.
