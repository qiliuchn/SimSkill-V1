---
name: design-count-station-locations-for-od-estimation
description: Use this skill when WHICH LINKS TO INSTRUMENT is the decision — count-station / sensor / detector location design for OD matrix estimation, choosing where to put traffic counters or AVI/ANPR/Bluetooth ID readers, deciding how many stations a survey needs, or judging whether an existing count programme can identify the demand at all. Covers the observability/rank accounting that says how underdetermined the problem is at each budget, a library of placement strategies (volume-greedy, Yang & Zhou covering / max-min flow fraction / link independence, greedy rank growth, Bayesian D-optimal and E-optimal, a random null distribution, and a non-deployable truth-using oracle bound), scoring every design on BOTH count fit and true OD recovery with a measured noise floor and a resolvable-difference test, ID-matching subpath readers as a second sensor type plus the measured counter-per-reader exchange rate, and robustness of a design to measurement error, a structurally wrong seed and a demand shift. Trigger on sensor location problem, count station placement, detector siting or detector layout for demand estimation, observability of an OD matrix, D-optimal or information-maximizing experimental design over a network, "where should I put my counters", "how many count stations do I need", "is my count programme enough to estimate demand", AVI/ANPR/plate-matching/Bluetooth reader placement, or sensor budget and sensor portfolio questions. Reach for this rather than `estimate-od-matrix-with-odme` whenever the observation set is a choice rather than an input — that skill estimates from counts you already have and can only diagnose that they underdetermine the matrix; this one chooses the links.
---

# Design Count-Station Locations for OD Estimation

Every other demand-calibration skill here takes the observation set as given.
`estimate-od-matrix-with-odme` estimates from whatever counts exist and its null-space
diagnostic can *tell you* the counts don't identify the matrix; nothing could *choose
links so that they do*. This skill closes that loop: the sensor set becomes the decision
variable, and the results below are measured on a controlled SUMO experiment with a
hidden true matrix rather than taken from the sensor-location literature.

The headline is uncomfortable and you should lead with it rather than bury it: **the
criterion practitioners optimise (count fit) barely ranks designs the way the goal (OD
recovery) does, and no deployable "smart" placement criterion beat plain volume-greedy
by a statistically resolvable margin at any budget.** Two of the criteria the literature
most recommends — Yang & Zhou's covering rules and pure link-independence/rank growth —
were *catastrophically worse* than the practitioner default at small budgets. Design
your study so it can detect that outcome, because it is the likely one.

## Why the naive study design produces a wrong answer

Three traps, each of which silently inverts a conclusion:

1. **Scoring a design on the links it selected.** This is the default thing to do and it
   is worse than useless. Count fit on instrumented links is the objective the estimator
   just minimised, on a link set the design itself chose. Measured rank correlation with
   true OD error: **+0.120 on average, and negative at small budgets.** Picking the
   design with the best instrumented %RMSN at 8 stations selected a design with 104.6%
   OD error when 69.6% was available. Score on a **fixed** link set (all candidates, or
   a properly sized held-out set) — that restores the correlation to **+0.890**.
2. **Believing GEH.** At 8, 24 and 48 stations, **47 of 47 designs passed GEH<5 on 100%
   of their instrumented links** while their true OD errors spanned 69.6%–105%. GEH has
   *zero* discriminating power in this setting — see [[geh-statistic]] on its tolerance
   widening at low volumes. Report %RMSN, not GEH pass rates.
3. **Declaring a winner on an unreplicated margin.** Count realisations are noisy; the
   noise floor was 14.14% ± 2.25% RMSN. With CRN across 6 realisations the minimum
   resolvable difference in OD error was 0.63 points at N=2 and 1.72 at N=24. The
   nominally best deployable strategy led by 0.77 ± 1.22 at N=8 and 0.46 ± 0.89 at N=24
   — **tied, not winning.** Use `score_designs.paired_crn_test` and say "tied" when it
   says tied.

## Pipeline

```bash
# 0. Scenario with a HIDDEN truth. Route overlap is essential — multiple viable paths
#    per OD pair. Put the truth behind one module (see "The truth barrier") and site the
#    demand level by MEASUREMENT (see "Site the demand level deliberately").

# 1. Build P with the ODME skill's own builder, then VERIFY it before trusting anything
python3 ../estimate-od-matrix-with-odme/scripts/build_assignment_matrix.py ...
python3 -c "import observability as ob; print(ob.verify_P(P, x_true, realised_counts))"
python3 -c "import observability as ob; print(ob.observability_report(P, selectable))"

# 2. Noise floor FIRST — before any strategy is compared
python3 -c "import score_designs as sd; print(sd.count_noise_floor(true_assigned))"

# 3. Placement orders (nested: design at budget N = first N entries)
#    volume, volume_meas, yang_zhou, observability, d_optimal, d_optimal_unw,
#    max_min_eig, random x40 draws, plus the non-deployable oracle
# 4. Greedy-vs-near-exact: enumerate_small_budget(n=2) + local_search from TWO starts
# 5. Factorial: strategy x budget x count realisation (x w_seed), scored on BOTH criteria
# 6. Readers: verify_matching -> build_Psub -> equal-cost portfolios -> exchange rate
# 7. Robustness: measurement noise, detector bias, structurally wrong seed, demand shift
# 8. Downstream: push the best and worst estimated matrices through microsimulation
```

`scripts/` holds the reusable parts: `placement_lib.py` (strategies + the fast ODME
solver), `score_designs.py` (truth-side scoring, the oracle, greedy-vs-exact,
resolvable-difference and correlation significance), `observability.py` (P verification
and rank accounting), `subpath_readers.py` (the ID-matching pipeline).

## The truth barrier

A placement study is worthless if a "deployable" strategy can see the answer, and it is
very easy to leak the truth accidentally — through a "measured volume" ranking, through
`P`, through a seed built from the truth. Make the barrier **structural and auditable**,
not a matter of care:

- One module, and only one, opens the truth. It exposes exactly three doors:
  `observed_counts()` (the data-generating process — estimators see only *instrumented
  rows* of noisy link flows), `score()` (called after an estimate exists), and the
  oracle's objective.
- The module containing the deployable strategies **must not import it**. Then
  `grep -rn truth /path/to/strategies.py` is a proof, not a promise. `placement_lib.py`
  is written to satisfy this; keep it that way.
- Build `P` from a **uniform reference demand**, not from the seed or the truth, so it
  depends on neither's values. The ODME skill's `build_assignment_matrix.py` already
  does this — it uses `--seed-matrix` only to enumerate OD pairs.
- Any strategy that needs measured volumes is **weakly non-deployable** (it presupposes
  the full count set the design is meant to buy). Keep it as a sensitivity arm and label
  it in every table — including the column headings.

## Site the demand level deliberately

Measure the gridlock knee before choosing the demand total; do not guess it. At 4200
veh/h the reference network gridlocked (224 teleports, 870 s TimeLoss/veh, 12.7 s wall
per run — which would have made the simulation-in-the-loop arm cost hours). Subsampling
the same route file gave a scale curve; 2600 veh/h gave 0 teleports and 1.8 s per run.

Where you sit on that curve is not a detail — it *drives* the downstream result below,
because delay is strongly convex in loading near the knee. Say where you sat and why.

## What the strategies actually do (measured, OD cell %RMSN)

| strategy | N=2 | N=8 | N=16 | N=24 | N=48 | N=98 (all) |
|---|---|---|---|---|---|---|
| volume-greedy (practitioner) | 103.5 | 70.3 | 64.6 | 60.8 | 51.3 | 50.0 |
| yang_zhou (classical rules) | 104.9 | 102.9 | 101.1 | 63.6 | 56.4 | 50.0 |
| observability (rank growth) | 104.9 | 102.5 | 100.5 | 65.4 | 56.0 | 50.0 |
| d_optimal (χ²-weighted) | 104.7 | 73.2 | 72.8 | 68.4 | 55.4 | 50.0 |
| **d_optimal_unw (homoscedastic)** | **75.7** | **69.6** | 65.1 | **60.3** | 53.7 | 50.0 |
| *oracle (non-deployable)* | *71.2* | *61.6* | *54.6* | *51.0* | *48.4* | *50.0* |
| random, median of 40 draws | 104.6 | 102.9 | 100.9 | 97.3 | 62.9 | 50.0 |
| random, best of 40 draws | 76.5 | 71.7 | 67.5 | 65.0 | 55.4 | 50.0 |
| no sensors (seed only) | 105.0 | — | — | — | — | — |

Read this table for its *shape*, not its numbers — they are one network. Four shapes
that are likely to generalise, because each has a mechanism:

- **The covering and rank-growth criteria are terrible at small budgets.** They spend
  early stations on many cheap low-flow pairs, buying independent *equations* that carry
  almost no demand information. They only catch up past ~25% instrumentation.
- **The χ² weighting inverts D-optimality.** The ODME objective weights residuals by
  1/max(c,1), so a *low*-volume link is the statistically more informative observation.
  Greedy D-optimality on the estimator's own information matrix therefore picks low-flow
  links and lands at the no-sensor error. Dropping the weighting makes the identical
  algorithm pick high-volume links and become the best deployable arm. **Run both arms**
  — with only the variance-consistent one you conclude, wrongly, that D-optimality fails.
- **A well-placed few beat a badly-placed many, by a lot.** 2 homoscedastic-D-optimal
  stations matched **24** Yang & Zhou or rank-growth stations (12x); 8 matched 48 random
  (6x); 24 oracle stations matched all 98 random. Against volume-greedy the crossover is
  only 1.0–2.0x, consistent with the two being tied.
- **The best deployable strategy captures 79.5–86.7% of the oracle's gain** at small
  budgets and 95–97% at large ones. It beats the random null's *median* everywhere, and
  the best of 40 draws at 10 of 12 budgets — but *resolvably* at only 7 of 12, and at one
  budget the best random draw won. The honest claim is "reliably beats random placement,
  not a lucky random draw."

## Marginal gains are not diminishing and error is not monotone in N

Do not import submodularity assumptions from the network-design literature. Measured
across every strategy including the oracle: **32.0%–43.3% of single-sensor additions
INCREASED OD error**, and 22%–52% of steps were non-diminishing. The non-monotonicity
survives to the top end — **the oracle's best design was at N=64 and full instrumentation
was worse** (48.1% vs 50.0%). Mechanism: with a fixed `w_seed`, each extra count row
pulls the solution toward what the counts can see and away from seed information that was
correct in the null space. Use `score_designs.marginal_gain_diagnostics` and report it.

The knee sits at roughly **12–33% instrumentation** (N≈12–32 of 98); volume-greedy
captured 70.6% of its achievable gain with 12 of 98 stations.

Validate greedy against something: exhaustive enumeration at N=2 (4753 designs, ~1 s)
gave a true optimum that oracle-greedy recovered *exactly*, and swap local search from
two different starts converged to the same value at N=8 and N=16 — that agreement is what
licenses greedy elsewhere. Oracle-greedy was within 0.7–1.1 points of near-exact while
the best deployable strategy was 15 points away.

## Cross-check the solver, not just the design

A design sweep visits thousands of rank-deficient row subsets, so solver pathologies that
never appear in a single ODME run become routine. `scipy.optimize.lsq_linear` raised
`LinAlgError: SVD did not converge` on some two-sensor designs; `placement_lib.estimate`
uses a ridge-regularised normal-equation solve instead (~50x faster, unconditionally well
posed) and `verify_solvers` should agree with the ODME skill's reference solver to ~1e-15.

Then spot-check that the cheap linear solver is not producing your conclusion. At N=16,
GLS / SPSA-linear / SPSA-with-microsimulation-in-the-loop (200 sim runs) all preserved the
strategy ranking: 61.4 / 60.8 / 62.1 for the better design against 101.6 / 103.9 / 107.9
for the worse one. Note in passing that the *worse* design achieved the *better* objective
value (F = 9.95 vs 27.21) in every solver — another face of trap #1.

## ID-matching readers, and why the exchange rate is not a constant

Readers observe subpath passages, so R readers give up to R(R-1) observation rows against
a counter's one. Verify the matching pipeline against route-implied subpath flows before
using it — `subpath_readers.verify_matching` compares two genuinely independent sources
(SUMO's `instantInductionLoop` `vehID` output versus the router's route file) and should
report exact agreement (reference: 969/969 ordered reader pairs, max abs difference 0).

At equal notional cost with a reader priced at 3 counters:

| budget (units) | all-counter | best mix | counter-equivalent of a reader | resolvable? |
|---|---|---|---|---|
| 6 | 71.97 | 0R+6C (no mix wins) | — | **no** (0.00 ± 0.00) |
| 12 | 65.90 | 0R+12C | — | **no** |
| 24 | 59.71 | 0R+24C | — | **no** |
| **48** | 53.30 | **7R+27C = 46.74** | **6.56 ± 2.10** | **yes** |

**The exchange rate is 0 below ~48 units and ~6.3 counters per reader at 48.** The
quadratic return needs R ≳ 6 before it overtakes the linear cost of the counters given
up, so a lone reader is just an expensive counter. Any single-number answer to "how many
loops is one reader worth" is an artefact of the budget it was measured at — report the
curve. At 48 units the mixed portfolio was unmatchable by *all 98* counters.

## Robustness is a property of the design, not a footnote

Re-score the winning and runner-up designs under perturbation. Kendall τ against the
baseline ranking, at 24 stations:

| perturbation | τ | winner | ranking usable? |
|---|---|---|---|
| measurement noise cv 0.10 | +0.905 | unchanged | yes |
| measurement noise cv 0.20 | −0.238 | flips | **no** |
| systematic under-count −5% / −10% | +1.000 | unchanged | yes, and error *improves* |
| structurally wrong seed (application only) | −0.333 | flips to rank-growth | **no** |
| structurally wrong seed (design + application) | +0.048 | flips to rank-growth | **no** |
| demand level + pattern shift | +0.619 | flips to volume | partly |

Two findings here matter more than the primary factorial:

- **Systematic detector under-count did not hurt — it helped**, preserving the ranking
  perfectly (τ = +1.000) and improving every strategy's error. The mechanism is specific
  and worth checking rather than generalising: the seed's total was 6.75% high, so a
  detector reading low pulled the estimated total the right way. **A bias in the lucky
  direction is a free correction, and it would reverse with a low seed.** Report which
  direction your seed errs before interpreting a bias result.
- **The best placement strategy depends on the seed's error *structure*, not its size.**
  With a seed whose marginals and total are right but whose destination splits are
  rotated, volume-greedy degraded from 60.8% to **94.5%** — barely better than no sensors
  — while rank-growth, the *worst* strategy at baseline, improved to **52.7%**, its best
  result anywhere. **A volume-prior design is a bet that the prior's structure is right;
  a rank-growth design is not.** This is the case for the observability criterion that
  the primary factorial appears to refute, and it is the situation in which a designed
  sensor set matters most. If your seed's structure is uncertain, prefer rank growth.

## What OD error actually costs a decision

Push the best and worst designs' estimated matrices through microsimulation. Measured
across 13 matrices at 3 seeds each (truth-run noise band: TTT 2.27%, delay 3.87%):

| relationship | Spearman (n=12) | p | 95% CI | verdict |
|---|---|---|---|---|
| OD %RMSN vs link-flow MAPE | **+0.895** | <0.001 | [+0.66, +0.97] | **solid** |
| OD %RMSN vs \|TTT error\| | −0.294 | 0.354 | [−0.74, +0.34] | **not resolvable** |
| OD %RMSN vs \|mean-delay error\| | −0.294 | 0.354 | [−0.74, +0.34] | **not resolvable** |

So: **OD-recovery accuracy strongly predicts link-flow error and carries no usable
information about network-performance error.** Do not read the negative sign — n=12
cannot separate it from zero, and `score_designs.corr_significance` exists so you check
that on your own numbers rather than bolding a point estimate. (This is the correction a
critic caught in the reference study; the same trap is waiting in any downstream
comparison over a handful of designs.)

What *is* established is the specific inversion, far outside the noise band: the design
that **won** on OD recovery (59.58% cell %RMSN) produced **+62.6%** mean-delay error with
9 teleports, while the one that **lost** (69.71%) produced **−17.7%** with 0 teleports.
A 10-point improvement in cell %RMSN bought an 80-point swing in delay error the wrong
way. Mechanism: demand sited near the gridlock knee makes delay convex in loading, so a
+3.3% demand error on the wrong corridors tips the network locally while a −2.5% error
stays under. **Sharpen `estimate-od-matrix-with-odme`'s guidance accordingly: a
count-calibrated matrix is trustworthy for link flows and not for congestion or delay
measures, however good its OD error looks.**

## `w_seed` — and a correction to the ODME skill's own rule

`estimate-od-matrix-with-odme` advises tuning `w_seed` so the achieved count RMSN lands
near the observation noise floor. **On this scenario that rule chose `w_seed` = 1, which
was 17 OD points worse than the truth-optimal 0.03** (64.34% vs 47.56%); the optimum sat
at a count RMSN of 5.9%, a factor of 2.4 *below* the 14.14% floor. The rule is a heuristic
whose validity is scenario-dependent, not a law.

For a placement study the fix is not to tune it — tuning on truth is not deployable, and
tuning per design confounds the comparison. **Fix `w_seed` at one value for every design
and demonstrate that the strategy ranking is invariant to it** by re-running the factorial
at a low and a high value (0.03 and 1.0 gave identical orderings at N=8 and N=98, with
mid-list reshuffling at intermediate budgets). Report that invariance check; without it a
reader cannot tell a placement effect from a regularisation effect.

## What to do in a real study, where there is no truth

Everything above that ranks designs needed a hidden truth, which a real study does not
have. That is not a limitation of the method — it is the finding. In a real study you
**cannot** validate a sensor design against OD recovery, and count fit will not
substitute (traps #1 and #2). What remains available, and what to report:

- `observability_report` on your candidate `P`: the number of OD cells, rank(P), the
  null-space dimension, and whether full observability is achievable **at any budget**.
  On the reference network it was not — 182 OD cells against 123 links whose rank
  saturated at 94. Say so up front; it reframes the whole procurement question.
- `rank_vs_budget` and `identifiable_share` for the design you propose — which subspace
  the budget buys, and the condition number on that subspace (nominal full rank at
  σ_max/σ_min ≈ 6000 is identified in name only).
- Volume-greedy as the design, unless your seed's *structure* is uncertain, in which case
  rank growth — that is the one situation where the observability criterion measurably
  wins, and it is not a small margin.
- Roughly 12–33% instrumentation as the knee, and the explicit warning that adding
  stations is not monotonically helpful.
- If you can afford ID readers, 6+ of them or none, priced against counters at the
  measured exchange rate for your own budget.

## Related

- `estimate-od-matrix-with-odme` — the estimator, `P` builder, solvers and metrics this
  skill composes; its `w_seed` rule is corrected above
- `solve-budget-constrained-network-design-problem` — the greedy-vs-near-exact and
  marginal-gain discipline reused here
- `optimize-under-simulation-noise-with-a-fixed-budget` — the noise floor and
  resolvable-difference test, without which this study reports a false winner
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — sensors for *state*
  estimation rather than demand; the sensor-emulation and systematic-bias patterns
- `design-actuated-signal-detector-placement-and-fault-tolerance` — detector siting for
  signal *control*, a different objective on the same physical hardware
- `convert-od-matrix-to-trips`, `create-grid-network` — the testbed inputs
- [[sensor-location-design-for-od-estimation]] — the full methodology, tables and
  negative results
- [[od-matrix-estimation-and-underdetermination]] — the null-space framing this extends
- [[geh-statistic]] — why GEH cannot rank sensor designs
