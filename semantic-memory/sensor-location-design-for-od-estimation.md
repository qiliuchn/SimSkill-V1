---
summary: Making count-station location the decision variable for OD estimation, measured on a controlled SUMO experiment with a hidden true matrix — count fit ranks sensor designs almost not at all (Spearman +0.120 against true OD recovery on the instrumented links, negative at small budgets, with 47 of 47 designs passing GEH<5 on 100% of them), no deployable placement criterion beat plain volume-greedy by a resolvable margin at any budget while the two criteria the literature most recommends (Yang & Zhou covering rules, pure rank growth) sat at the no-sensor error out to 16% instrumentation, marginal sensor value is neither diminishing nor monotone (32-43% of single-sensor additions increased OD error and the oracle's best design used 64 of 98 links), the counter-per-ID-reader exchange rate is 0 below a ~48-unit budget and ~6.3 above it, and OD-recovery accuracy predicts link-flow error strongly (+0.895) but carries no usable information about network delay.
keywords:
  - sensor-location-problem
  - count-station-placement
  - detector-siting-for-demand-estimation
  - OD-observability
  - D-optimal-design
  - experimental-design-over-a-network
  - AVI-ANPR-plate-matching
  - subpath-flow-observation
  - sensor-portfolio-exchange-rate
  - count-fit-vs-od-recovery
  - resolvable-difference
created: 2026-08-17T16:35:53
last_updated: 2026-08-17T16:35:53
sources:
  - "[[episodic-memory/2026-08-17_16-35-53/summary.md]]"
  - "[[episodic-memory/2026-08-17_16-35-53/outputs/results/]]"
related_pages:
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[geh-statistic]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]]"
related_skills:
  - design-count-station-locations-for-od-estimation
  - estimate-od-matrix-with-odme
  - solve-budget-constrained-network-design-problem
  - optimize-under-simulation-noise-with-a-fixed-budget
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
related_skills_for_graph_view:
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[estimate-od-matrix-with-odme]]"
  - "[[solve-budget-constrained-network-design-problem]]"
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
---

# Sensor Location Design for OD Estimation

[[od-matrix-estimation-and-underdetermination]] establishes that link counts generally
fail to identify an OD matrix, and its null-space diagnostic can say *how badly*. The
obvious follow-on question — can you choose the counted links so that they do identify
it? — is the classical Sensor Location Problem, and this page records what happened when
it was measured rather than assumed, on a synthetic SUMO network where the true matrix
was withheld from every estimator and used only for scoring. The procedural counterpart
is `design-count-station-locations-for-od-estimation`.

The short answer is that most of the expected effects did not appear, and the reasons
they didn't are more useful than the effects would have been.

## The testbed, and the barrier that makes it meaningful

A 6×6 grid (250 m spacing, 2 lanes, 30 signalised junctions) plus an asymmetric supply
overlay — a 3-lane/70 km/h arterial and three one-way 80 km/h bypasses — so the network
is not reflection-symmetric and route choice is genuinely contested (3.51 distinct routes
per OD pair, max 14). 14 TAZs (11 boundary gates + 3 CBD zones) give 182 directional OD
pairs; 123 internal directional links, 25 permanently held out, 98 selectable. The true
matrix is a gravity model with CBD zones attracting 6–8× a boundary zone plus four
boosted long-haul pairs, totalling 2600 veh/h.

**A placement study is worthless if a "deployable" strategy can see the answer, and the
leak paths are subtle.** The barrier that worked was structural rather than careful: one
module holds the truth and exposes exactly three doors — the data-generating process
(estimators see only *instrumented rows* of noisy link flows), the scorer (called only
after an estimate exists), and the oracle's objective. The module containing the
deployable strategies does not import it, so `grep` is a proof rather than a promise.
Two further leak paths worth naming: the assignment-proportion matrix `P` must be built
from a **uniform reference demand** so it depends on neither truth nor seed *values*, and
any strategy ranking links by *measured* volume is **weakly non-deployable** — it
presupposes the full count set the design is supposed to buy.

## Full observability is usually unachievable, which reframes the question

182 OD cells, 123 candidate links, and rank(P) saturating at **94** — so identification
needs 182 independent rows that the network cannot physically supply. **Full OD
observability is unachievable at any budget on this network**, and that is the normal
case, not a pathology of this example. Every design is therefore a choice of *which
identifiable subspace to buy*, never a step toward identification.

Rank grows exactly 1 per link up to 80 links, so counting equations is easy and
misleading; conditioning is the part that bites, with σ_max/σ_min,nonzero = **6093** on
the row space. A nominally full-rank design at that condition number is identified in
name only. `P` itself was verified before anything downstream: `P·x_true` against the
realised assignment over three router seeds gave %RMSN 5.35 / 4.91 / 6.02 with max GEH
2.27 on all 123 links, against an irreducible assignment noise of 7.69% RMSN.

## Count fit does not rank sensor designs — and scoring on the selected links inverts it

This is the central finding. Spearman rank correlation against true OD error, across 47
designs per budget:

| scored on | mean Spearman | at N=2 | at N=48 |
|---|---|---|---|
| the **instrumented** links (what practitioners report) | **+0.120** | **−0.126** | +0.358 |
| a 25-link **held-out** set | +0.369 | +0.246 | +0.459 |
| **all 123** candidate links (a fixed reference set) | **+0.890** | +0.667 | +0.937 |

The mechanism is a tautology: count fit on instrumented links is the objective the
estimator just minimised, evaluated on a link set the design itself chose. Consequences,
quantified:

- **At 8, 24 and 48 stations, 47 of 47 designs passed GEH<5 on 100% of their instrumented
  links** while their true OD errors spanned 69.6%–105%. GEH has *zero* discriminating
  power here — a sharper instance of the low-volume leniency recorded in
  [[geh-statistic]].
- Selecting the design with the best instrumented %RMSN at 8 stations picks one with
  **104.6%** OD error when **69.6%** was available; at 24 stations, 99.5% instead of 60.3%.
- In the SPSA spot check the *worse* design achieved the *better* objective value
  (F = 9.95 vs 27.21) while being 40 OD points worse, under all three solvers.

The practical rule: **never score a sensor design on the links it selected. Score on a
fixed link set, and report %RMSN rather than GEH pass rates.**

## The literature's preferred criteria lost; the practitioner default was unbeatable

OD cell %RMSN by strategy and budget (98 selectable links; seed alone = 105.0):

| strategy | N=2 | N=8 | N=16 | N=24 | N=48 | N=98 |
|---|---|---|---|---|---|---|
| volume-greedy (practitioner) | 103.5 | 70.3 | 64.6 | 60.8 | 51.3 | 50.0 |
| Yang & Zhou covering rules | 104.9 | 102.9 | 101.1 | 63.6 | 56.4 | 50.0 |
| greedy rank growth | 104.9 | 102.5 | 100.5 | 65.4 | 56.0 | 50.0 |
| D-optimal, χ²-weighted | 104.7 | 73.2 | 72.8 | 68.4 | 55.4 | 50.0 |
| **D-optimal, homoscedastic** | **75.7** | **69.6** | 65.1 | **60.3** | 53.7 | 50.0 |
| *oracle (non-deployable)* | *71.2* | *61.6* | *54.6* | *51.0* | *48.4* | *50.0* |
| random, median of 40 draws | 104.6 | 102.9 | 100.9 | 97.3 | 62.9 | 50.0 |
| random, best of 40 draws | 76.5 | 71.7 | 67.5 | 65.0 | 55.4 | 50.0 |

- **No deployable strategy beat volume-greedy by a resolvable margin at any budget.** The
  count noise floor was 14.14% ± 2.25% RMSN; with common random numbers across 6 count
  realisations the minimum resolvable difference in OD error was 0.63 points at N=2 and
  1.72 at N=24. The nominally best strategy led by **0.77 ± 1.22** at N=8 and
  **0.46 ± 0.89** at N=24 — tied. Without the resolvable-difference discipline from
  `optimize-under-simulation-noise-with-a-fixed-budget` this study would have reported a
  winner that wasn't one.
- **What *is* resolvable is that the classical rules and pure rank growth are far worse
  than the practitioner default below ~25% instrumentation** — they sit at the no-sensor
  error out to N=16 while volume-greedy is already at 64.6%. Mechanism: the covering and
  independence rules spend early stations on many cheap low-flow pairs, buying independent
  *equations* that carry almost no demand information.
- **The χ² weighting inverts D-optimality.** The ODME objective weights count residuals by
  1/max(c,1), so a *low*-volume link is the statistically more informative observation.
  Greedy D-optimality on the estimator's own information matrix therefore picks low-flow
  links first and lands at 104.7% at N=2; dropping the weighting makes the identical
  algorithm pick high-volume links and reach 75.7%. **A criterion can be internally
  consistent with the estimator and still wrong for the goal** — so run both weightings,
  since running only the variance-consistent one yields the false conclusion that
  D-optimality fails.
- The single most valuable station was the CBD-inbound access link, taking OD error from
  105.0% to **77.0%** alone. Volume-greedy ranked it 4th; the covering and rank-growth
  rules never chose it in their first 8.
- **A well-placed few beat a badly-placed many by up to 12×**: 2 homoscedastic-D-optimal
  stations matched 24 covering-rule or rank-growth stations; 8 matched 48 random (median);
  24 oracle stations matched all 98 random. Against volume-greedy the crossover is only
  1.0–2.0×, consistent with a tie.
- **The best deployable strategy captured 79.5–86.7% of the oracle's gain** at small
  budgets and 95–97% at large ones. It beat the random null's *median* everywhere and the
  *best of 40 draws* at 10 of 12 budgets — but resolvably at only 7 of 12, and at one
  budget the best random draw won outright. The honest claim is that designed placement
  reliably beats random placement, not a lucky random draw.

## Marginal sensor value is neither diminishing nor monotone

Submodularity assumptions imported from the discrete network design problem (see
[[discrete-network-design-and-project-interaction]]) do not transfer. Across every
strategy including the oracle, **32.0%–43.3% of single-sensor additions *increased* OD
error**, and 22%–52% of steps were non-diminishing. The non-monotonicity survives to the
top end: **the oracle's best design used 64 of 98 links (48.1%) and full instrumentation
was worse (50.0%)** — 34 extra stations that make the answer 1.9 points worse. Mechanism:
with a fixed seed weight, each extra count row pulls the solution toward what the counts
can see and away from seed information that was correct in the null space.

The knee in marginal value sits at roughly **12–33% instrumentation**; volume-greedy
captured 70.6% of its achievable gain with 12 of 98 stations.

Greedy was validated rather than trusted: exhaustive enumeration of all 4753 two-sensor
designs gave a true optimum that oracle-greedy recovered *exactly*, and swap local search
from two different starts converged to the same value at N=8 and N=16. Oracle-greedy sat
within 0.7–1.1 points of near-exact; the best deployable strategy was 15 points away.

A solver caveat specific to design sweeps: a sweep visits thousands of rank-deficient row
subsets, so `scipy.optimize.lsq_linear` raised `LinAlgError: SVD did not converge` on some
two-sensor designs — routine here rather than an edge case. A ridge-regularised
normal-equation solve is unconditionally well posed and ~50× faster, agreeing with the
reference solver to ~1e-15 relative L2.

## ID-matching readers: the exchange rate is not a constant

A second sensor type — AVI/ANPR/Bluetooth-analogue readers observing *subpath* passages —
is realisable in SUMO with `instantInductionLoop`, which records `vehID` per passage
(the aggregating `inductionLoop` loses identity). Deduplicating `state="enter"` records to
(vehID, edge) first-crossing times and matching IDs across reader pairs gives subpath
flows, which enter the estimator as extra rows of the same linear system, tabulated from
the reference router run that produced `P`. The pipeline was verified before use:
**969/969 ordered reader pairs exact (max absolute difference 0)** against route-implied
subpath flows, plus exact single-reader link counts on 123/123 links — a comparison of two
genuinely independent sources (detector output versus route file), not a self-comparison.

At equal notional cost with a reader priced at 3 counters:

| budget (units) | all-counter | best mix | counter-equivalent of one reader | resolvable? |
|---|---|---|---|---|
| 6 | 71.97 | 0R + 6C | — | **no** (paired gain 0.00 ± 0.00) |
| 12 | 65.90 | 0R + 12C | — | **no** |
| 24 | 59.71 | 0R + 24C | — | **no** |
| **48** | 53.30 | **7R + 27C = 46.74** | **6.56 ± 2.10** | **yes** |

**The exchange rate is 0 below a ~48-unit budget and ~6.3 counters per reader at it** —
so any single-number answer to "how many loops is one reader worth" is an artefact of the
budget it was measured at. The mechanism is structural: R readers yield only R(R−1)
subpath rows, so the quadratic return does not overtake the linear cost of the counters
given up until R ≳ 6, and a lone reader is just an expensive counter. At 48 units the
mixed portfolio was unmatchable by *all 98* counters.

## Robustness: the winning criterion depends on the seed's error *structure*

Kendall τ of the strategy ranking against baseline, at 24 stations:

| perturbation | τ | winner | ranking usable? |
|---|---|---|---|
| measurement noise cv 0.10 | +0.905 | unchanged | yes |
| measurement noise cv 0.20 | −0.238 | flips | no |
| systematic under-count −5% / −10% | +1.000 | unchanged | yes, and error *improves* |
| structurally wrong seed (application only) | −0.333 | flips to rank growth | no |
| structurally wrong seed (design + application) | +0.048 | flips to rank growth | no |
| demand level + pattern shift (+18%, CBD ×0.65) | +0.619 | flips to volume | partly |

Two results here matter more than the primary factorial:

- **Systematic detector under-count did not degrade the estimate — it improved it**, with
  the ranking perfectly preserved (τ = +1.000) and every strategy's error falling
  (60.34% → 58.89% → 58.45%). The expected effect simply did not appear. The mechanism is
  specific and must not be generalised: the seed's total was **+6.75%** high, so a detector
  reading low pulled the estimated total the right way. **A bias in the lucky direction is
  a free correction**, and it would reverse with a low seed — so establish which direction
  your seed errs before interpreting any bias result. Contrast the genuinely systematic
  sensor biases in [[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]], where
  direction is a property of the sensor rather than of the prior.
- **A volume-prior sensor design is a bet that the prior's *structure* is right; a
  rank-growth design is not.** With a seed whose marginals and grand total are correct but
  whose destination splits are 55% rotated, volume-greedy degraded from 60.8% to **94.5%**
  — barely better than no sensors at all (109.3%) — while rank growth, the *worst*
  strategy at baseline, improved to **52.7%**, its best result in any scenario. This is
  the case for the observability criterion that the primary factorial appears to refute,
  and it applies exactly when a designed sensor set matters most. **If the seed's structure
  is uncertain, prefer rank growth over volume-greedy.**

## What OD error costs a decision, and what it doesn't

Estimated matrices pushed back through microsimulation (13 matrices × 3 seeds; truth-run
noise band TTT 2.27%, mean delay 3.87%):

| relationship | Spearman (n=12) | p | Fisher 95% CI | verdict |
|---|---|---|---|---|
| OD %RMSN vs top-10 link-flow MAPE | **+0.895** | <0.001 | [+0.66, +0.97] | **solid** |
| OD %RMSN vs \|TTT error\| | −0.294 | 0.354 | [−0.74, +0.34] | **not resolvable** |
| OD %RMSN vs \|mean-delay error\| | −0.294 | 0.354 | [−0.74, +0.34] | **not resolvable** |

**OD-recovery accuracy strongly predicts link-flow error and carries no usable information
about network-performance error.** The negative sign must not be read — n = 12 cannot
separate −0.294 from zero, and a design study that compares a handful of designs downstream
will always be in that regime. (The original write-up bolded the sign; the critic's
significance check retracted it. Apply the same test to any correlation over a small design
set.)

What *is* established, far outside the noise band, is the specific inversion: the design
that **won** on OD recovery (59.58% cell %RMSN) produced **+62.6%** mean-delay error with
9 teleports, while the one that **lost** (69.71%) produced **−17.7%** with 0 teleports;
another design at 61.85% gave +76.1% and 15 teleports. Mechanism: the demand was
deliberately sited just below the network's gridlock knee, where delay is strongly convex
in loading, so a +3.3% total-demand error concentrated on the wrong corridors tips the
network locally while a −2.5% error stays comfortably under. **A 10-point improvement in
cell %RMSN bought an 80-point swing in delay error in the wrong direction.**

This sharpens the trustworthiness argument in
[[od-matrix-estimation-and-underdetermination]]: a count-calibrated matrix is trustworthy
for *link flows* (+0.895 confirms it directly) and is **not** trustworthy for congestion or
delay measures, however small its OD error looks. It also means the demand level chosen for
a synthetic study is not a detail — where you sit relative to the gridlock knee drives this
result, and should be stated.

## A correction to the ODME seed-weight rule

`estimate-od-matrix-with-odme` advises tuning the seed weight so the achieved count RMSN
lands near the observation noise floor. **On this scenario that rule selected w_seed = 1,
which was 17 OD points worse than the truth-optimal 0.03** (64.34% vs 47.56%); the optimum
sat at a count RMSN of 5.9%, a factor of 2.4 *below* the 14.14% floor. The rule is a
scenario-dependent heuristic, not a law.

For a placement study the resolution is not to tune it at all — tuning on truth is not
deployable and tuning per design confounds the comparison. Fix the weight at one value for
every design and **demonstrate that the strategy ranking is invariant to it** by re-running
the factorial at a low and a high value (0.03 and 1.0 gave identical orderings at N=8 and
N=98, with mid-list reshuffling at intermediate budgets). Without that invariance check a
reader cannot distinguish a placement effect from a regularisation effect.

## What survives into a real study

Everything that ranked designs above required a hidden truth. A real study has none, and
count fit will not substitute — that is the finding, not a limitation of the method. What
remains available:

- The rank/null-space accounting on the candidate `P`, and the honest statement of whether
  full observability is achievable **at any budget**. It usually isn't, and saying so
  reframes the procurement question.
- The identifiable subspace a proposed budget buys, and its condition number.
- Volume-greedy as the default design — unless the seed's *structure* is uncertain, in
  which case rank growth, which is the one situation where the observability criterion
  measurably and substantially wins.
- Roughly 12–33% instrumentation as the knee, with the explicit warning that adding
  stations is not monotonically helpful.
- ID readers in blocks of 6 or more, or not at all, priced against counters at the exchange
  rate measured for the relevant budget.
