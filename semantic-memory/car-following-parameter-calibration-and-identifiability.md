---
summary: A verified Morris-screen -> GA-calibrate -> validate pipeline for SUMO's Krauss and IDM car-following parameters against field fundamental-diagram targets found defaults carry a consistent +20-33% fast bias on backward wave speed but are broadly defensible otherwise, and — the more consequential result — that a macroscopically-calibrated model is not uniquely identified, with statistically-tied parameter vectors differing 2.8-3x in microscopic headway variability and known-answer recovery getting FD features right to <8.5% error while individual parameters remain off by up to 45%.
keywords:
  - car-following-calibration, vType-calibration, Morris-screening, Sobol, global-sensitivity-analysis, equifinality, identifiability, GEH-acceptance-criteria, Krauss, IDM
created: 2026-08-03T18:20:00
last_updated: 2026-08-06T08:00:00
sources:
  - "[[episodic-memory/2026-08-03_17-00-00/outputs/SENSITIVITY_TABLE.md]]"
  - "[[episodic-memory/2026-08-03_17-00-00/outputs/CALIBRATION_SCORECARDS.md]]"
  - "[[episodic-memory/2026-08-03_17-00-00/outputs/CALIBRATION_PROTOCOL.md]]"
  - "[[episodic-memory/2026-08-03_17-00-00/outputs/FINDINGS.md]]"
related_pages:
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[geh-statistic]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[weather-friction-effects-on-capacity-and-safety]]"
  - "[[lane-change-model-calibration-and-identifiability-at-a-diverge]]"
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
  - "[[webster-method]]"
  - "[[sumo-time-discretization]]"
  - "[[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]"
related_skills:
  - calibrate-car-following-parameters-against-field-targets
  - build-macroscopic-fundamental-diagram
  - validate-kinematic-wave-theory-across-car-following-models
  - optimize-signal-plan-with-simulation-in-the-loop-ga
  - choose-time-discretization-and-integration-method
  - screen-and-decompose-sumo-parameter-sensitivity
related_skills_for_graph_view:
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
  - "[[optimize-signal-plan-with-simulation-in-the-loop-ga]]"
  - "[[choose-time-discretization-and-integration-method]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
---

# Car-Following Parameter Calibration and Identifiability

[[kinematic-wave-theory-validity-across-car-following-models]] established that a link's
fundamental diagram (FD) is almost entirely a property of which car-following model is
chosen. This page distills what happened when SUMO's car-following *parameters* — not
just the model choice — were treated as the object of study: screened for influence,
calibrated against explicit field targets, and validated for whether the result is
unique. Full protocol and reusable machinery: `calibrate-car-following-parameters-against-field-targets`.

## Are SUMO's defaults defensible?

Measured against an explicit target vector (v_free 110 km/h, capacity 2200 veh/h/ln,
critical density 25 veh/km/ln, jam density 130 veh/km/ln, backward wave speed 17.5 km/h),
SUMO's default passenger-car vType is close on free-flow speed, capacity, and jam density
(RMSN 15.2% Krauss / 11.9% IDM), but carries one dominant, consistent bias: **backward
wave speed runs +32.6% (Krauss) / +19.9% (IDM) too fast**. Calibration cuts RMSN to 4.8%
(Krauss) / 3.0% (IDM) — but not uniformly: for Krauss, closing the wave-speed gap
*degraded* two features (v_free, k_jam) the default already matched, an honest
gap-closed of -230% and -847% on those two features respectively. IDM's uncalibrated
default already passes the RMSN<15% practitioner threshold outright.

## Which parameters actually matter (Morris elementary-effects screening)

Screening (p=4, Δ=2/3, r≈10 trajectories) per FD feature, not just the aggregate
objective, found:

- **`tau` dominates capacity, critical density, and wave speed** for both models by a
  wide margin — confirms textbook expectation.
- **`minGap` + `length` dominate jam density** for both models — consistent with the
  closed-form `k_jam = 1/(length+minGap)`.
- **`speedFactor` does NOT dominate free-flow speed for Krauss** — `decel` and
  `apparentDecel` outrank it, because the measured free-flow branch still contains
  car-following inside speed-heterogeneity platoons and Krauss's safe-gap term depends
  on those parameters. For IDM (no dawdling), `speedFactor` is cleanly the top control.
  **Lesson: don't let a low aggregate μ* license fixing a parameter that is the only
  clean, monotone control of a target you care about.**
- **`apparentDecel` is nearly as influential as `decel`** for Krauss, despite being a
  parameter practitioners almost never calibrate.
- **`emergencyDecel` is inert** (μ* ~300x below the next parameter) in an incident-free
  regime — safe to fix without screening cost.
- **`sigma` is genuinely inert for IDM** (μ* exactly 0.0000) — it's a Krauss-family
  dawdling parameter and wastes a search dimension in an IDM parameter space.

This page's Morris sampler was later reused directly (not reimplemented) for lane-changing-parameter screening, and again for a cross-subsystem study spanning car-following, lane-changing, signal timing, and demand ([[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]) — which is also where an actual Sobol/variance-based follow-up was finally implemented; "Sobol" appeared only as an aspirational keyword tag on this page until then.

## The central negative result: macro-only calibration is under-determined

Collecting every optimizer-evaluated parameter vector within `best + 2*SD_seed` of the
best objective (the "statistically tied" band, defined from the *measured* seed-noise
floor, not an arbitrary tolerance) found 144 (Krauss) / 119 (IDM) macroscopically-tied
vectors that differ **measurably** in microscopic behavior — time-headway CV spanning a
2.8-3x range, oscillation amplitude spanning 0.87-1.52 — while scoring within noise of
each other on the macro objective. Adding a single microscopic target (median headway)
to the objective shrinks the tied set by 20% (Krauss) / 40% (IDM), but doesn't eliminate
it. **Known-answer recovery against a synthetic ground truth confirms this is intrinsic,
not a real-data artifact**: FD features are recovered to under 8.5% error, but individual
parameters remain off by up to 45% (e.g. Krauss `sigma` -75.6%, IDM `delta` -45.0%) —
the objective can converge to near zero while the underlying parameter vector is
genuinely wrong. A macroscopic-only calibration objective cannot pin down a unique
car-following parameter vector; microscopic field data (headway or oscillation
statistics) is required to narrow it further.

## Acceptance criteria are necessary, not sufficient

Among top-ranked candidates passing both GEH<5 and RMSN<15%, 26% (Krauss) / 55% (IDM)
contained at least one physically implausible parameter value (e.g. IDM `tau`=0.679s
with RMSN 4.2%, GEH 3.13). Passing standard practitioner acceptance criteria does not
imply a physically defensible parameter set — a plausibility screen (e.g. `tau` in
0.7-1.6s, `decel` in 2.5-5.0 m/s²) must be applied alongside GEH/RMSN, see
[[geh-statistic]].

## Transferability is a property of the model, not the calibration procedure

Calibrating on the uncongested+capacity branch only (holding jam density and wave speed
out of the training objective) left wave speed 19.9% (Krauss) / 25.8% (IDM) off when
later checked against the congested branch — matching free-flow speed and capacity does
not pin down queueing behavior. Separately, a freeway-calibrated Krauss vector
transferred to a held-out signalized approach's saturation headway within ~1% of the
1.90s target; the equivalently-calibrated IDM vector transferred *worse* than IDM's own
uncalibrated default. **A calibrated car-following model should not be assumed to
transfer to a facility type it wasn't calibrated against — verify per model, not just
per parameter set.**

## Optimizing under simulation noise

The calibration objective's own seed-to-seed noise is non-trivial (CV 6.6-9.7% for
Krauss, 7.0% default but 49.2% at the IDM-calibrated point) and a single-seed optimizer
score is an optimistic order statistic: re-evaluating the GA's reported best with 8 seeds
found the true objective was +9% worse for Krauss and +165% worse for IDM — the IDM
search was pulled into a high-variance region of parameter space by the optimizer
chasing noise, not a genuinely better fit. Common Random Numbers reduced variance for
Krauss's evaluation (VRF 0.99, i.e. no benefit — correlation ρ=0.036) but helped IDM
(VRF 2.58, ρ=0.482): CRN's benefit is metric- and model-dependent, consistent with
[[sumo-stochastic-variability-and-replication-design]].

## Five verified SUMO gotchas found along the way

1. **`departSpeed` above what a vehicle's `speedFactor` permits makes SUMO permanently
   rewrite that vehicle's speedFactor** rather than clamping speed (a logged
   `Choosing new speed factor ...` warning) — `--no-warnings` hides it, and it silently
   inflates measured free-flow speed/capacity for the rest of the run.
2. **IDM's `delta` is silently ignored when written as `<param key="delta">`** — only the
   vType *attribute* form is honored. `delta=1` vs `delta=8` as `<param>` gave
   byte-identical output (26.0032 m/s); as attributes, 20.81 vs 27.09 m/s (30% flow
   difference). Always verify a parameter override changed behavior by running the two
   extremes of its range.
3. **`sigma` is genuinely inert for SUMO's IDM** (distinct from gotcha 2 — correctly
   rendered as an attribute, just has no effect; it's Krauss-only).
4. **A single-lane ring cannot measure fleet free-flow speed when `speedDev>0`** — with
   no overtaking, the stream collapses toward the slowest desired speed in the sample.
   Verified not a geometry artifact (a `speedDev=0` ring reaches 99.0% of the limit at
   every node count 8-128); a two-lane ring is required for heterogeneous desired speeds.
5. **An open-road freeway cannot show a congested branch once demand exceeds insertion
   capacity** — the queue forms at the network boundary, not the bottleneck, so measured
   station flow *falls* while speed stays free-flow. Diagnose via `loaded - inserted`
   from `<summary>`; get the congested branch from a controlled-density ring instead.

## Caveat on prior SimSkill findings

Several previously-recorded findings rest on SUMO's uncalibrated default car-following
parameters: [[av-penetration-and-carfollowing-model-mechanism]] (AV vs human gap-matched
comparison), [[heavy-vehicle-passenger-car-equivalent-in-sumo]] (PCE measured against a
default-calibrated passenger car), [[weather-friction-effects-on-capacity-and-safety]]
(percentage capacity drops measured against a dry baseline that itself carries the
+20-33% wave-speed bias documented here), and [[webster-method]] (saturation flow
measured from default discharge headway). The general rule from this page: **direction
and mechanism findings are robust to default-parameter bias, but reported magnitudes are
not** — re-check magnitude-sensitive conclusions against a calibrated fleet before citing
exact percentages from those pages. The saturation-flow finding in [[webster-method]] is
partly corroborated here (freeway-calibrated Krauss reproduced the held-out saturation
headway target within ~1%).

## Calibrated parameter sets are not intrinsically dt-specific, but a stored optimum can be

A 2026-08-04 time-discretization audit ([[sumo-time-discretization]]) re-evaluated this
page's stored calibrated Krauss and IDM parameter sets — produced at `--step-length 0.5`
with `--step-method.ballistic` (the actual condition this episode's pipeline runs at,
not `dt=1.0s` Euler) — across a `step-length x integration-method` grid. **The stored
Krauss set transfers cleanly** (weighted RMSN 0.051-0.071 against its five FD targets
everywhere on the grid, comfortably under the 15% acceptance threshold). **The stored
IDM set does not**: RMSN rises from 0.044 at its own calibration condition to 0.171 at
`dt=1.0s` ballistic, with capacity falling 15% short of target and backward wave speed
33% short, leaving only 2 of 5 features in tolerance. A **freshly re-calibrated** set
(either model, either direction) transfers far better than the stored IDM optimum does —
only 1.16-1.39x RMSN degradation — which is best explained by this page's own
equifinality finding: the objective surface is flat enough that an optimizer can land on
a point whose *flatness* is itself convention-specific, even though the broader
acceptable region is not. **Practical rule: a calibrated vType is under-specified without
its `(step-length, integration method, actionStepLength)` triple, and should be re-scored
before reuse at a different one** — the stored IDM parameter set above should be treated
as calibrated specifically at `dt=0.5s`, ballistic, and not assumed to hold at `dt=1.0s`.
