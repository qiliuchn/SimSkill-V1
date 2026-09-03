---
name: calibrate-car-following-parameters-against-field-targets
description: Use this skill when the user wants to treat SUMO's car-following/vType parameters as things to be CALIBRATED against empirical field values (free-flow speed, capacity, critical density, jam density, backward wave speed, saturation headway) rather than accepted as defaults - including global sensitivity screening (Morris elementary effects / Sobol) to find which parameters actually matter, simulation-in-the-loop optimisation (GA vs Nelder-Mead/SPSA) against a weighted RMSN/GEH objective, and validation of the result (identifiability/equifinality, regime and facility transferability, GEH<5 / RMSN<15% acceptance criteria, known-answer recovery). Covers a fast controlled-density FD probe usable as an optimiser inner loop, a parameter-to-FD-feature influence map for Krauss and IDM, and the finding that macro-only calibration is under-determined. Trigger on mentions of calibrating car-following parameters, vType calibration, driver behaviour calibration, parameter sensitivity/screening, Morris/Sobol on SUMO, equifinality, identifiability, or "are SUMO's default driver parameters defensible".
---

# Calibrate Car-Following Parameters Against Field Targets

Treats the vType car-following parameter vector as the **object of study** rather than
a given. Every other skill in this memory picks a car-following model and accepts its
defaults; [[kinematic-wave-theory-validity-across-car-following-models]] established
that the fundamental diagram is almost entirely a property of that choice, which makes
"are the defaults defensible?" the natural next question. This skill answers it with a
screen -> calibrate -> validate pipeline, and — the more consequential result —
establishes that a **macroscopically-calibrated car-following model is not uniquely
identified**.

## The instrument problem: you need an FD measurement cheap enough to be an inner loop

A calibration run needs hundreds to thousands of FD evaluations. Neither an open-road
demand sweep (`build-macroscopic-fundamental-diagram`) nor a full corridor is fast
enough. Use a **controlled-density closed ring** as the optimiser's inner loop and keep
the open road as a *validation* facility only. On a ring, density is exact
(`k = 1000*N/(L*n_lanes)`), no insertion or bottleneck artifact can contaminate it, and
a 15-cell sweep spanning free flow to jam costs a few seconds.

**Use a TWO-LANE ring, not the single-lane ring of
`validate-kinematic-wave-theory-across-car-following-models`, whenever the desired-speed
distribution is part of the calibration.** With `speedDev > 0` on a single lane there is
no overtaking, so the measured "free-flow speed" collapses toward the *slowest* desired
speed in the sample — a moving-bottleneck artifact, not the fleet mean that an empirical
FFS target refers to. Verified: with `speedDev=0` a ring reaches 99.0% of the posted
limit at every low-density cell and at every node count from 8 to 128 (so this is *not*
a ring-geometry artifact); with `speedDev=0.2` the same cells read 82-98% of the fleet
mean desired speed, monotonically worse as density rises. Two lanes restore overtaking
and also narrow the ring→freeway transfer gap.

**Derive the features robustly, not from a single cell.** Free-flow speed from a
through-origin OLS over the *three* lowest-density cells (a single low-density cell is a
small-sample draw from the speedFactor distribution and is noisy by several km/h);
capacity and critical density from a **parabola through the peak cell and its two
neighbours**, so `k_crit` is not quantised to the density grid; jam density and wave
speed from an OLS on the congested branch (report its R² — it should be ≈1.0).

## Screen before you optimise, and screen every FD feature separately

Run Morris elementary-effects screening (p=4 levels, Δ=2/3, r≈10 trajectories,
(k+1)·r simulations) **before** any optimisation, computing μ*/σ not just for the
aggregate objective but for **each FD feature normalised by its own target**. The
aggregate ranking alone will mislead you into fixing a parameter that is the sole
control of one target.

Verified parameter→feature map (μ*, normalised responses; see
`scripts/` outputs and the episode's `SENSITIVITY_TABLE.md`):

- **`tau` dominates capacity, critical density and wave speed** for both Krauss and IDM
  — by a wide margin (μ* on wave speed ~1.3 for Krauss, ~0.7 for IDM, 2-4x the next
  parameter). This confirms the textbook expectation.
- **`minGap` + `length` dominate jam density**, ranked 1st and 2nd for both models,
  consistent with `k_j = 1/(length+minGap)` being the one robust closed-form relation.
- **`speedFactor` does NOT dominate free-flow speed for Krauss** — `decel` and
  `apparentDecel` rank above it. This is *not* a bug: the measured free-flow branch of a
  stream with heterogeneous desired speeds still contains car-following inside
  speed-heterogeneity platoons, and the Krauss safe-gap term depends on
  decel/apparentDecel. For IDM (deterministic, no dawdling) `speedFactor` is cleanly 1st.
  **Take the aggregate μ* ranking as advice, not as a licence to fix a parameter that is
  the only monotone, non-cancelling control of a target you care about** — keep such a
  parameter free even when its objective-level μ* is small (`speedFactor`'s μ* on the
  objective was only 9% of `tau`'s, yet it is the only clean FFS knob).
- **`apparentDecel` is nearly as influential as `decel`** for Krauss across every
  feature, despite being a parameter practitioners almost never calibrate.
- **`emergencyDecel` is inert** (μ* ≈ 0.001 on every feature, ~300x below the next
  parameter) in an incident-free regime — fix it.

## Two gotchas that silently invalidate a screening or an optimisation

**IDM's `delta` is honoured ONLY as a vType attribute.** Written as
`<param key="delta" value="..."/>` it is **silently ignored** — no warning, no error,
and `delta=1` vs `delta=8` produce byte-identical output. Verified directly: as an
attribute the same two values give 20.81 vs 27.09 m/s at a fixed near-capacity density
(a 30% flow difference); as `<param>` children both give exactly the default's
26.0032 m/s. A first screening run of `delta` measured a no-op and had to be discarded.
This is the concrete instance of the general warning in
`validate-kinematic-wave-theory-across-car-following-models` — **always verify a
parameter override changed behaviour, not merely that it produced no error.** A cheap,
decisive check is to run the two extremes of the parameter's range and confirm the
outputs differ.

**`sigma` is genuinely inert for SUMO's IDM** (μ* exactly 0.0000 on every feature, with
`sigma` correctly rendered as an attribute) — it is a Krauss-family dawdling parameter.
Including it in an IDM parameter space wastes a search dimension. Distinguish this real
inertness from the `delta` rendering bug by checking *how* the parameter was written.

**`departSpeed` above what a vehicle's `speedFactor` permits makes SUMO permanently
REWRITE that vehicle's speedFactor**, rather than clamping the speed:
`Warning: Choosing new speed factor 1.20 for vehicle 'v0' to match departure speed
40.00 (max 31.62)`. A lone vehicle then cruises at 20% above the limit for the whole
run, inflating measured free-flow speed and capacity. **`--no-warnings true` hides
this.** Any routine that computes an equilibrium `departSpeed` (as ring loading must,
since `departSpeed="max"` silently under-fills a dense ring) must hard-cap it below
`laneSpeed * (speedFactor_mean - 3*speedDev)` **and** grep stderr for
`Choosing new speed factor`, treating a hit as a failed evaluation.

## Optimiser choice, and what the comparison actually shows

Compare at least two strategies on an identical objective, CRN seed and budget
accounting. A generational GA (elitism, tournament selection, BLX-α crossover) is
**population-parallel**, which matters more than per-evaluation efficiency: it saturates
all cores. Multistart Nelder-Mead is serial per restart, so parallelise it *across*
restarts — and take the restart spread as a free by-product: it is exactly the candidate
pool the equifinality test needs. Seed one restart at the SUMO defaults so the optimiser
is never worse-informed than the uncalibrated model it must beat.

Log best-so-far and generation-mean every generation and verify from the raw CSV/JSON
that best-so-far is non-increasing (elitism), per
`optimize-signal-plan-with-simulation-in-the-loop-ga`.

## The central negative result: macro-only calibration is under-determined

Define the "statistically indistinguishable" band from the **measured seed-to-seed
noise floor** of the objective (not an arbitrary tolerance), then collect every
candidate the optimisers evaluated inside `best + 2*SD`, and select maximally-separated
representatives in normalised parameter space. Re-evaluate each with ≥8 CRN seeds to
confirm the tie, then measure each one's **microscopic** signature at a fixed
near-capacity density: time-headway distribution (median, CV), speed-oscillation
amplitude, per-vehicle speed SD, and the transient from a one-shot brake pulse.

Verified: multiple parameter vectors that are statistically tied on the macroscopic
objective differ **measurably** in microscopic behaviour. **Report the equifinality
explicitly, and test the remedy**: add a microscopic target (an observed headway
distribution statistic) to the objective and re-measure how many of the tied candidates
still qualify. The shrinkage of the feasible set is the quantitative argument for
collecting microscopic field data, not just counts and speeds.

## Validation that actually tests something

- **Regime transfer**: calibrate on the uncongested+capacity features only
  (`v_free`, `q_max`, `k_crit`), then *validate* on the congested-branch features
  (`k_jam`, `w`) which were never in the training objective. On a ring this split is
  clean because density is controlled; on an open road it is confounded by insertion.
- **Facility transfer**: hold out an entirely different facility — a signalised
  approach's saturation headway, measured with
  `measure-saturation-flow-and-validate-webster-method`'s rear-bumper
  (`state="leave"`) instant-loop methodology — and check whether freeway-calibrated
  parameters reproduce it. Do **not** put it in the objective.
- **Acceptance criteria vs physical plausibility**: score candidates on the
  practitioner criteria (GEH < 5, RMSN < 15%, visual FD overlay — see [[geh-statistic]])
  **and** on whether their parameter values are physically defensible
  (e.g. tau in 0.7-1.6 s, decel in 2.5-5.0 m/s²). Count how many passing candidates are
  physically implausible: a nonzero count is a demonstration that these criteria are
  necessary but not sufficient, and that a parameter-plausibility screen must be applied
  alongside them.
- **Known-answer recovery**: run the whole pipeline against a *synthetic* ground truth
  (FD features generated by a known held-out parameter vector) to separate "the method
  works" from "reality is harder than the model". Report recovery error in normalised
  unit-cube distance per parameter, not only in the objective — the objective can go to
  ~0 while individual parameters are badly recovered, which is itself the equifinality
  result restated.

## Reporting discipline

Every reported number carries: ≥8 CRN seeds with 95% CIs, teleport and collision counts
(check **collisions**, not just teleports — an aggressive parameter draw can produce
genuine collisions), the count of failed/unusable density cells, and the congested-branch
fit R². A candidate whose evaluation failed must be charged a large penalty rather than
silently dropped, or the optimiser will learn to exploit the failure mode.

## Gotchas

- **A single-lane ring cannot measure a fleet free-flow speed when `speedDev > 0`** —
  use two lanes; verify with `speedDev=0` that the ring reaches the posted limit.
- **`<param key="delta">` is silently ignored for IDM** — use the vType attribute, and
  verify any parameter override by running its two range extremes.
- **`sigma` is inert for IDM** but not for Krauss — don't carry it in an IDM search space.
- **`emergencyDecel` is inert in an incident-free regime** — fix it after screening.
- **`departSpeed` above the permitted maximum permanently rewrites `speedFactor`**, and
  `--no-warnings` hides the warning — hard-cap departSpeed and grep stderr.
- **Never point a network *builder* at the same filename the calibration instrument
  reads.** Verified failure in this episode: a `build_ring()` helper wrote a 1-lane ring
  to the path that had been repointed to the 2-lane instrument, silently replacing it
  *while an optimisation was running*; every subsequent evaluation returned the failure
  penalty and the Nelder-Mead arm reported "no improvement over the start point" instead
  of erroring. Re-run the net verification and re-probe a known parameter vector for a
  known feature vector before trusting any long optimisation's output.
- **An open-road freeway cannot show a congested branch once demand exceeds the
  *insertion* capacity** — the queue forms at the network boundary, not at the
  bottleneck. Diagnose with the `loaded - inserted` count from `<summary>`; a sweep whose
  high-demand points show flow *falling* while speed stays free-flow is insertion-limited,
  not congested. Get the congested branch from a controlled-density ring or a genuinely
  weaker downstream bottleneck.
- **Screening the aggregate objective alone can fix a parameter you need** — screen every
  target feature separately and exempt sole-control parameters.

## Related

- `build-macroscopic-fundamental-diagram` — the open-road E1 station FD measurement used
  here as the *validation* facility (and whose insertion limit this skill documents).
- `validate-kinematic-wave-theory-across-car-following-models` — the closed-ring FD
  instrument and the parameter→FD-feature formulas this skill calibrates against; this
  skill upgrades that ring to two lanes for heterogeneous desired speeds.
- `measure-saturation-flow-and-validate-webster-method` — the held-out signalised-approach
  saturation-headway measurement used for facility transferability.
- `optimize-signal-plan-with-simulation-in-the-loop-ga` — the simulation-in-the-loop GA
  machinery (genome encoding, elitism, convergence logging, budget benchmarking) reused
  here for a parameter vector instead of a signal plan.
- `quantify-sumo-run-to-run-variability` / [[sumo-stochastic-variability-and-replication-design]]
  — the CRN replication design and required-replication-count method used to define the
  equifinality band.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport/collision
  accounting discipline applied to every sweep cell here.
- [[geh-statistic]] — the GEH acceptance criterion used in the scorecards.
- [[car-following-parameter-calibration-and-identifiability]] — the verified sensitivity,
  calibration, equifinality, transferability and known-answer-recovery findings.
