---
summary: OD matrix estimation (ODME) adjusts a seed matrix so assigned link flows reproduce observed counts, formulated as a bi-level objective over count fit and seed deviation; verified on a controlled SUMO experiment where the counts left 69 of 132 OD degrees of freedom structurally undetermined, so a perfect count fit removed 100% of the observable seed error and 0% of the invisible part, and six matrices differing by half of all trips all passed GEH<5 on 100% of counted links in microsimulation.
keywords:
  - ODME
  - OD-matrix-estimation
  - assignment-proportion-matrix
  - underdetermination
  - equifinality
  - seed-matrix
  - bi-level-optimization
  - SPSA
created: 2026-08-04T08:00:00
last_updated: 2026-08-17T18:10:00
sources:
  - "[[episodic-memory/2026-08-04_08-00-00/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-08-04_08-00-00/outputs/results/RESULTS.md]]"
related_pages:
  - "[[sensor-location-design-for-od-estimation]]"
  - "[[od2trips]]"
  - "[[duarouter]]"
  - "[[geh-statistic]]"
  - "[[routesampler]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[sumo-output-files]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[four-step-model-feedback-loop-convergence]]"
  - "[[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]]"
related_skills:
  - estimate-od-matrix-with-odme
  - design-count-station-locations-for-od-estimation
  - convert-od-matrix-to-trips
  - calibrate-demand-with-routesampler
  - reconstruct-demand-with-dfrouter
  - assign-traffic-with-marouter
related_skills_for_graph_view:
  - "[[estimate-od-matrix-with-odme]]"
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[reconstruct-demand-with-dfrouter]]"
  - "[[assign-traffic-with-marouter]]"
---

# OD Matrix Estimation and Underdetermination

**OD matrix estimation (ODME)** adjusts a prior ("seed") origin-destination matrix so that the link flows it produces under an assignment model reproduce observed traffic counts. It is the zone-level inverse demand problem, and it closes a gap the two neighbouring SUMO approaches explicitly leave open: [[routesampler]] scales routes from a candidate pool with no zone structure at all, and [[dfrouter-detector-based-demand-reconstruction]] states outright that its output is not a true OD matrix.

The findings below come from a controlled synthetic experiment: a 5x5 SUMO grid (250 m spacing, 2 lanes, 150 m attach edges) with 12 TAZs at external gates, 132 OD pairs, 80 internal links available for counting, and a gravity-type ground-truth matrix of 3000 veh/h that the estimator never saw.

## The bi-level formulation

Minimise, subject to `x >= 0`:

```
F(x) = w_c * SUM_l [ (v_l(x) - c_l)^2 / max(c_l,1) ]   +   w_s * SUM_k [ (x_k - s_k)^2 / max(s_k,1) ]
```

The upper level chooses the matrix `x`; the lower level `v(x)` is the assignment. The chi-square/Poisson-style denominators (the GLS/ME2 convention) make both terms dimensionless so the ratio `w_s/w_c` is interpretable.

## The assignment-proportion matrix P

`P[l,k]` = fraction of OD pair `k`'s vehicles traversing counted link `l`, so `v = P x`. It can be extracted directly from SUMO: [[od2trips]] writes `fromTaz`/`toTaz` on every trip, [[duarouter]] preserves those attributes onto the routed `<vehicle>`, so routing one large uniform reference demand and tabulating per-pair edge-usage frequencies yields the whole matrix from a single router run.

Because `duarouter` routes on **free-flow** edge weights, its route-choice distribution is independent of the demand level. `P` is therefore a demand-independent linear operator and the ODME upper level is exactly linear — verified: `P @ x_truth` reproduced the ground-truth route file's own link counts at GEH max 1.41. Deriving `P` from congested or iterated weights instead ([[marouter-macroscopic-assignment]], `duaIterate`) makes it demand-dependent, requiring an outer loop that re-derives `P` at the current solution.

`duarouter --weights.random-factor` must exceed 1. At 1.0 the router is deterministic, each OD pair uses a single route, and `P` becomes binary — a legitimate all-or-nothing assignment but a far more degenerate system. A factor of 1.4 produced a mean of 5.5 distinct routes per OD pair.

## Underdetermination is structural, not a tuning problem

**`rank(P) = 63` for 132 OD unknowns and 80 counted links** — so 69 of 132 degrees of freedom were invisible to the counts even with *every* internal link in the network counted. This is the number to compute and report first; it is available before any optimisation runs.

Worse, the rank **saturates**. At 20 and 40 counted links `rank(P)` equalled the link count exactly — every link added an independent constraint. At 80 links it was only 63: **the last 17 links carried no information the other 63 had not already provided**, because flow conservation on a grid makes their counts linearly dependent on the rest. There is a hard ceiling on what buying more detectors can achieve, and it is reached well before "count every link".

The consequence is exact. For an unregularised least-squares ODME the estimate error decomposes as `x_est - x_truth = (I - P⁺P)(s - x_truth)`: the counts remove **100%** of the seed error lying in the row space of `P` and **0%** of the error in its null space. Verified numerically with exact, noise-free counts:

| quantity | value |
|---|---|
| seed OD error before ODME | 75.5% |
| seed error, row-space component | 168.91 |
| seed error, null-space component | 101.87 (51.6% of the seed error norm) |
| estimate error, row-space component | **0.00** (100% removed) |
| estimate error, null-space component | **101.87** (100% retained) |
| count fit | RMSN 0.000000% |
| OD cell error after a mathematically perfect fit | **39.0%** |
| cells driven negative (why `x >= 0` is needed) | 5 |

A mathematically perfect count fit halved the OD error and then stopped dead: **every unit of the remaining 39.0% error lies in the subspace the counts cannot see**, and no amount of additional fitting can touch it. This is the demand-level analogue of the behavioural-parameter equifinality recorded in [[car-following-parameter-calibration-and-identifiability]].

## Equifinality, demonstrated in microsimulation

The set of matrices reproducing the counts is a polytope `{x + N y : x + N y >= 0}` where `N` spans the null space of `P`. Solving an LP with a random objective lands on a *vertex* — a maximally different flow-equivalent matrix. (A single random null-space step hits the non-negativity boundary almost immediately and badly understates the non-uniqueness: it moved only 4-7% of demand, where the LP vertices moved ~50%.)

Six such matrices, each put through the **full microsimulation** (reference solution: `noise50.od` seed at `w_s`=0.1, 32.1% OD error):

| matrix | total demand | assigned RMSN | simulated RMSN | simulated GEH<5 | % demand moved vs ODME soln | OD error vs truth |
|---|---|---|---|---|---|---|
| ODME solution | 2973 | 3.32% | 6.36% | **100%** | 0% | 32.1% |
| alt1 | 3067 | 3.32% | 6.84% | **100%** | 51.9% | 137.6% |
| alt2 | 3159 | 3.32% | 6.07% | **100%** | 54.4% | 137.9% |
| alt3 | 2780 | 3.32% | 6.46% | **100%** | 50.8% | 120.1% |
| alt4 | 2970 | 3.32% | 7.00% | **100%** | 49.1% | 134.7% |
| alt5 | 3272 | 3.32% | 6.80% | **100%** | 56.7% | 141.2% |
| alt6 | 3277 | 3.32% | 7.08% | **100%** | 53.7% | 136.9% |

**Seven matrices that differ from one another by roughly half of all trips — 110-117 of the 132 cells off by more than 50% — and whose true OD error spans 32% to 141%, all pass GEH<5 on 100% of counted links in real microsimulation, with a maximum per-link GEH of 2.76.** Count fit cannot distinguish between them. This is not a linear-algebra artefact: it survives contact with actual traffic dynamics.

A related warning: the *uncalibrated* `noise50.od` seed matrix, **75.5% wrong** in OD terms, already passed GEH<5 on **88.8%** of links (count RMSN 38.5%) — above the conventional 85% acceptance bar — before any ODME ran at all.

## The weighting is the answer, not a nuisance parameter

Count fit improves monotonically as `w_s -> 0`. **OD recovery is U-shaped.** (5 independent seed replicates, 100% link coverage, mean seed OD error 72.7%.)

| `w_s` | count RMSN | GEH<5 | OD RMSN | total demand err | null err retained |
|---|---|---|---|---|---|
| 1e-4 | 0.09% | 100% | **70.8%** | -0.53% | 99% |
| 0.001 | 0.50% | 100% | 56.2% | -0.63% | 82% |
| 0.01 | 1.37% | 100% | 39.0% | -0.63% | 68% |
| **0.1** | 3.21% | 100% | **36.4%** | -0.50% | 68% |
| 1 | 9.94% | 100% | 47.4% | +2.81% | 77% |
| 10 | 21.98% | 98.0% | 64.7% | +11.37% | 93% |
| 100 | 28.18% | 93.5% | 71.6% | +15.94% | 99% |

At `w_s = 1e-4` the count fit is essentially perfect and the matrix barely improves on the seed at all (70.8% vs 72.7%); with a *good* seed it ends up outright worse. The optimum sits where the count-fit residual is comparable to the **observation noise floor** — measured here at 6.7-7.0% RMSN by re-running the same ground-truth matrix under two further simulation seeds. Any fit meaningfully tighter than the floor is fitting noise.

The damage is worst when the seed is *good*: a seed at 30.5% OD error came out of a near-unregularised ODME at 62.8%, and a 24.7% seed at 63.1%, with even the observable row-space error made 94% and 202% *worse* respectively — pure overfitting to count noise. Practical rule: tune `w_s` so the achieved count RMSN lands near the noise floor, not far below it.

**That rule is a scenario-dependent heuristic, not a law — it failed on a second network.** On the 6×6 grid of [[sensor-location-design-for-od-estimation]] the count noise floor was 14.14% and the truth-optimal weight was 0.03, giving a count RMSN of **5.9% — a factor of 2.4 *below* the floor**. Applying the noise-floor rule there selects `w_s` = 1, which is **17 OD points worse** (64.34% vs 47.56%). The U-shape itself replicated (63.82 / 49.38 / **47.56** / 47.93 / 52.87 / 64.34 / 78.36 across `w_s` 0.001→3), so the mechanism holds; only the location of the optimum relative to the floor does not. Sweep the weight and report the sweep, as this page's own advice says — and where OD recovery is unobservable, treat the noise-floor point as one candidate rather than the answer. In a study where `w_s` must not confound a comparison (e.g. ranking sensor designs), fix it at one value for every arm and demonstrate the ranking is invariant to it at a low and a high value instead of tuning per arm.

## Seed quality dominates coverage

| seed family | seed OD error | ODME OD error at `w_s`=0.1 |
|---|---|---|
| uniform 1.25x scaling | 30.5% | **15.4%** |
| 20% lognormal noise | 24.7% | 18.2% |
| structural bias (destinations rotated, row marginals preserved) | 48.1% | 31.1% |
| 50% lognormal noise | 72.7% | 36.4% |
| flat/uninformative | 69.7% | 42.7% |
| 100% lognormal noise | 268.1% | 68.4% |

Coverage helps, but far less than seed quality. At the tuned weight, going from a 20-link screenline to all 80 links improved OD error from 58.4% to 36.4% (25% coverage 55.3%, 50% coverage 47.3%) — while at fixed full coverage, swapping a 25%-noise seed for a 100%-noise seed moved it from 18.2% to 68.4%. Two screenlines and a scattered 25% sample use the same 20 links and end up equivalent (58.4% vs 55.3%), though the screenlines are slightly more informative per link in row-space terms (75.7% vs 68.0% of row-space error removed). With exact, noise-free counts at full coverage the residual OD error was still 20.4-34.6% — the pure underdetermination floor, with observation noise removed entirely.

## Congestion, measurement windows, and the closed loop

Feeding the estimate back through od2trips → duarouter → sumo with a fresh seed passed at every demand level: RMSN 7.6%/4.5%/3.4% and **GEH<5 on 100% of links** at 1x, 3x and 5x demand.

The interesting behaviour is in the measurement window:

| demand | teleports | mean speed | peak-window flow deficit | assignment vs simulation, whole run | assignment vs simulation, demand hour |
|---|---|---|---|---|---|
| 3000 veh | 0 | 11.44 m/s | -1.6% | RMSN 0.00% | RMSN 2.2%, GEH<5 100% |
| 9000 veh | 45 | 7.93 m/s | -21.4% | RMSN 0.00% | RMSN 40.5%, GEH<5 **66.2%** |
| 15000 veh | 155 | 6.60 m/s | -47.4% | RMSN 0.00% | RMSN 107.2%, GEH<5 **11.2%** |

**Over a whole run, simulated link counts equal route-implied counts exactly — verified byte-identical vectors at all three demand levels.** Congestion redistributes flow in *time*, not in space, and with fixed (free-flow) route choice every vehicle still traverses every edge of its route eventually. So a free-flow assignment matrix is a perfectly adequate lower level for whole-run counts even in heavy congestion.

Restricted to the demand hour — the realistic field-count window — the picture inverts: queued flow spills past the end of the window and the free-flow assignment over-predicts what a detector actually records by 21% at 3x and 47% at 5x demand. **If counts come from a fixed field window on a congested network, a free-flow `P` is systematically biased and the ODME will under-estimate demand**; a congested or iterated assignment is required.

Two related output gotchas: read counts with edgeData `entered`, not `left` — teleports ([[teleport-artifacts-and-gridlock-resolution-validity]]) remove vehicles mid-edge, leaving `left` 26 vehicles short of `entered` network-wide at 3x demand and 72 short at 5x while `entered` stayed exactly consistent with the routes driven. And SUMO resolves the `file=` attribute inside an additional file relative to *that file's own directory*, not the process cwd, so detector output silently lands beside the `.add.xml` ([[sumo-output-files]]).

## Optimisers: least squares vs SPSA

With a linear lower level the whole problem is a bound-constrained linear least-squares problem solvable exactly by `scipy.optimize.lsq_linear`. The derivative-free alternative is SPSA over log-multipliers `x = s·exp(theta)`, which needs only an objective oracle and therefore also works with a full microsimulation as the lower level. All four runs below optimise the identical objective (`w_s` = 0.1, `noise50.od` seed at 75.5% OD error):

| optimiser | wall time | lower-level evaluations | objective F | count RMSN (simulated) | GEH<5 (simulated) | OD error |
|---|---|---|---|---|---|---|
| LSQ, assignment matrix | 0.02 s | 1 solve | **52.2** | 7.22% | 100% | **32.1%** |
| SPSA, linear, 1500 iters | 0.1 s | 3000 | 57.2 | 7.19% | 100% | 31.9% |
| SPSA, linear, 300 iters | 0.03 s | 600 | 113.3 | 10.11% | 100% | 47.5% |
| SPSA, **simulation in loop**, 300 iters | **1017 s** | 600 microsimulations | 194.1 | 10.94% | 100% | 50.8% |

Three things follow:

1. **SPSA does converge to the exact solver's answer** — given ~3000 lower-level evaluations it matches LSQ's objective and OD error almost exactly. It is a correct optimiser, just a hugely more expensive one.
2. **At a matched budget it does not.** 600 evaluations gets F = 113 against LSQ's 52.2, and an OD error of 47.5% against 32.1%.
3. **Simulation in the loop costs a further factor of ~30 000 in wall time and gives a slightly worse answer than the matched-budget linear run** (F = 194 vs 113), because microsimulation noise and od2trips' integer-vehicle quantisation make the objective stochastic. Putting the simulator in the loop only pays when the lower level genuinely cannot be linearised — demand-responsive route choice, in-simulation control logic, non-differentiable objectives.

And once more, the theme of this page: **all four solutions, spanning 32% to 51% OD error, passed GEH<5 on 100% of counted links in microsimulation** (max per-link GEH 2.26 to 3.20).

SPSA's practical failure mode is gain scaling. The raw gradient estimate `(fp-fm)/(2·ck)` is O(1e3) when `ck ~ 0.1` and the objective is in the thousands, which pins `theta` at its clip and inflates the candidate matrix to ~20x the seed — after which every simulation-in-the-loop evaluation gridlocks and takes minutes instead of seconds (the first attempt here sat on iteration 0 for six minutes before being killed). RMS-normalising the gradient before stepping, plus a per-component step clip of 0.05, is what makes it usable at all.

## Validation must be reported on two separate axes

- **Count fit** — per-link GEH and %RMSN, share of links with GEH<5 ([[geh-statistic]]). This is what ODME optimises, so it is *not* evidence the matrix is right.
- **OD recovery** — cell RMSN/MAE/correlation, total-demand error, row/column marginal error. Only computable against a known truth, i.e. only in a synthetic experiment. In a real study it is unobservable — which is precisely the problem.

Row and column marginals recover far better than individual cells (row-marginal MAPE 4.9% and column-marginal MAPE 4.9% against 36.4% cell RMSN at the tuned weight), so **zone-level trip productions and attractions are much more trustworthy ODME outputs than individual OD cells.** Total demand is recovered to within 0.5% at the tuned weight.

## When ODME output is trustworthy

- **Usable for policy** when the question depends only on link flows in and around the counted corridor: flow-consistent base-year link volumes, corridor before/after comparisons, feeding a microsimulation whose outputs are link-based, and (with care) zone-level productions/attractions.
- **Report only as a flow-consistent adjustment, never as recovered demand**, when the question is OD-specific: zone-to-zone demand, corridor market share, tolling or transit ridership by OD pair — anything where a specific cell carries the answer. Always quote the null-space dimension and the equifinality spread beside the matrix.
- The honest summary from this experiment: at the tuned weight ODME cut OD error from 72.7% to 36.4% — a real, worthwhile improvement — but with exact counts and a perfect fit the entire residual error lies in the subspace the counts cannot observe. **ODME improves a matrix; it does not identify one.**

**Sharpened by direct measurement:** the "usable for link flows, not for OD cells" boundary above was later tested by pushing 13 differently-estimated matrices through microsimulation and correlating their OD error against downstream error ([[sensor-location-design-for-od-estimation]]). OD-recovery accuracy predicts **link-flow error strongly (Spearman +0.895, p < 0.001)** — direct confirmation of the first bullet — and predicts **network delay not at all** (−0.294, p = 0.354, CI [−0.74, +0.34]; the sign is not established and must not be read). The failure is not merely a weak correlation: the design with the *best* OD recovery (59.6% cell %RMSN) produced **+62.6%** mean-delay error while the *worst* (69.7%) produced **−17.7%**, both far outside a 3.87% run-to-run noise band, because near a network's gridlock knee delay is strongly convex in loading and the sign of a small total-demand error decides whether the network tips. So extend the second bullet: **also report only as a flow-consistent adjustment when the question is a congestion or delay measure** — total travel time, mean delay, level of service, queue-based impacts — not just when a specific OD cell carries the answer.

## Choosing which links to count

This page treats the counted-link set as given. When it is a *choice* — where to site count stations, how many a survey needs, whether an existing count programme can identify the demand at all — see [[sensor-location-design-for-od-estimation]] and the `design-count-station-locations-for-od-estimation` skill. Two of its results bear directly on this page's argument: the null-space problem generally **cannot** be designed away (182 OD cells against 123 links whose rank saturated at 94 — full observability unachievable at any budget), and the count-fit statistic this page already warns against is not merely weak but actively misleading as a *design* criterion, since scoring a design on the links it selected correlates with true OD recovery at +0.120 and negatively at small budgets.

See the `estimate-od-matrix-with-odme` skill for the runnable pipeline, including the `check_equifinality.py` diagnostic that should accompany every reported ODME result.

[[four-step-model-feedback-loop-convergence]] is this page's forward-problem counterpart — synthesizing an OD matrix from land use rather than inferring one from counts. The two problems' lessons only partly transfer: ODME's equifinality/non-uniqueness finding is specific to inverting sparse link counts and does not apply to the forward gravity model (a doubly-constrained gravity model has a unique IPF fixed point given its margins and impedances), but both share the discipline of measuring a noise floor before trusting a convergence or fit claim, and od2trips's fromTaz/toTaz pass-through behavior transfers directly between the two workflows.
