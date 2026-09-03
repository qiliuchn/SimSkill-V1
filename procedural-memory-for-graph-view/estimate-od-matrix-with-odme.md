---
name: estimate-od-matrix-with-odme
description: Use this skill when the user wants to estimate or adjust an origin-destination matrix from observed link/detector counts (OD matrix estimation, ODME, matrix adjustment, matrix estimation from counts, demand calibration against traffic counts at the zone level). Covers building an explicit assignment-proportion matrix from duarouter/od2trips output, the bi-level count-fit-plus-seed-deviation objective, a bound-constrained generalised least-squares solver and a derivative-free SPSA alternative with simulation in the loop, and — critically — separating count-fit validation (GEH, %RMSN) from OD-recovery validation, plus a null-space/equifinality diagnostic that says whether the estimated matrix is actually identified by the counts or merely inherited from the seed. Trigger on ODME, OD matrix estimation, matrix adjustment/correction from counts, "calibrate my OD matrix to detector counts", or questions about whether a count-calibrated matrix can be trusted.
related_skills:
  - design-count-station-locations-for-od-estimation
  - convert-od-matrix-to-trips
  - convert-trips-to-routes
  - assign-traffic-with-marouter
  - calibrate-demand-with-routesampler
  - reconstruct-demand-with-dfrouter
  - analyze-simulation-outputs
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[design-count-station-locations-for-od-estimation]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[assign-traffic-with-marouter]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[reconstruct-demand-with-dfrouter]]"
  - "[[analyze-simulation-outputs]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[sensor-location-design-for-od-estimation]]"
  - "[[geh-statistic]]"
---

# Estimate an OD Matrix from Link Counts (ODME)

Adjusts a seed OD matrix so that assigned/simulated link flows reproduce observed counts. This is the true *inverse* demand problem at the zone level, and it is genuinely distinct from the two nearest SimSkill skills:

- `calibrate-demand-with-routesampler` selects and scales routes from a candidate **route pool**; there is no zone structure and no OD matrix in or out.
- `reconstruct-demand-with-dfrouter` reconstructs flows from detectors on a highway; its own knowledge page records that its output is **not** a true OD matrix.

ODME starts from a zone-level matrix and returns a zone-level matrix. **The central thing to know before running it is that it is almost always underdetermined**, and the whole workflow below is built around measuring how underdetermined *your* case is rather than hoping it isn't.

## The problem, stated

Minimise, subject to `x >= 0`:

```
F(x) = w_c * SUM_l [ (v_l(x) - c_l)^2 / max(c_l,1) ]      <- count fit
     + w_s * SUM_k [ (x_k    - s_k)^2 / max(s_k,1) ]      <- deviation from seed
```

`x` is the OD vector, `s` the seed, `c` the observed counts on the counted links, and `v(x)` the assigned link flow — the *lower level*. The `1/max(.,1)` denominators are the chi-square/Poisson weighting standard in the GLS/ME2 family and make the two terms dimensionless so `w_s/w_c` is meaningful.

`w_s/w_c` is not a nuisance parameter — **it is the single most consequential choice in the whole pipeline** (see the weighting section below).

## Pipeline

```bash
S=.claude/skills/procedural-memory/estimate-od-matrix-with-odme/scripts

# 1. assignment-proportion matrix P:  v = P x
python $S/build_assignment_matrix.py --net net.xml --taz districts.taz.xml \
    --seed-matrix seed.od --out P.npz --trips-per-pair 1000 --random-factor 1.4

# 2. estimate (sweep the weight -- always look at the sweep, never one value)
python $S/run_odme.py --p P.npz --counts observed_edgedata.xml --seed-matrix seed.od \
    --out estimated.od --w-seed 0.1 --w-seed-sweep 1e-4,0.01,0.1,1,10 --report odme.json

# 3. is the answer identified, or inherited from the seed?
python $S/check_equifinality.py --p P.npz --matrix estimated.od --n-alt 6 \
    --net net.xml --taz districts.taz.xml --add detectors.add.xml \
    --observed observed_edgedata.xml --begin 25200 --end 39600

# 4. close the loop through a real microsimulation, with a FRESH seed
python $S/validate_odme.py --net net.xml --taz districts.taz.xml --matrix estimated.od \
    --p P.npz --observed observed_edgedata.xml --add detectors.add.xml \
    --begin 25200 --end 39600 --sim-seed 9001 --report validation.json
```

Inputs come from `convert-od-matrix-to-trips` (TAZ file + O-format matrix) and `run-simulation`/`analyze-simulation-outputs` (edgeData/E1 counts).

## Building P — the assignment-proportion matrix

`P[l,k]` is the fraction of OD pair `k`'s vehicles that traverse counted link `l`. `build_assignment_matrix.py` estimates it by Monte Carlo: route a uniform reference demand (equal trips on every OD pair) through `od2trips` + `duarouter`, then tabulate per-pair edge-usage frequencies. This works because **`od2trips` writes `fromTaz`/`toTaz` on every trip and `duarouter` preserves those attributes onto the routed `<vehicle>`** — verified — so one router run yields the whole matrix.

Two properties to be deliberate about:

- **`--random-factor` must be > 1.** At 1.0 `duarouter` is deterministic and each OD pair gets exactly one route, making `P` binary and the system far more degenerate than it needs to be. 1.4 gave a mean of 5.5 distinct routes per OD pair on a 5x5 grid.
- **With free-flow `duarouter` weights, route choice does not depend on the demand level**, so `P` is a demand-independent linear operator and the upper level is exactly linear. Verified: `P @ x_truth` matched the ground-truth route file's own link counts at GEH max 1.41 / RMSN 4.6% (the residual is Monte-Carlo noise in P plus realisation noise in the run). If you instead derive `P` from congested or iterated weights (`duaIterate`, `marouter` with capacity restraint — see `assign-traffic-with-marouter`), `P` becomes demand-dependent and must be re-derived at the current solution in an outer loop.

`build_assignment_matrix.py` prints `rank(P)` and the null-space dimension. **Read that line before anything else.** On the 5x5 grid with 12 TAZs, 80 counted links and 132 OD pairs, rank(P) was 63 — so 69 of 132 degrees of freedom were invisible to the counts even with *every* internal link counted.

## The two algorithms

All four runs below optimise the identical objective (`w_s` = 0.1, seed at 75.5% OD error):

| optimiser | wall time | lower-level evals | F | simulated count RMSN | sim GEH<5 | OD error |
|---|---|---|---|---|---|---|
| `--method lsq` | 0.02 s | 1 solve | **52.2** | 7.22% | 100% | **32.1%** |
| `--method spsa`, 1500 iters | 0.1 s | 3000 | 57.2 | 7.19% | 100% | 31.9% |
| `--method spsa`, 300 iters | 0.03 s | 600 | 113.3 | 10.11% | 100% | 47.5% |
| SPSA with **sumo in the loop**, 300 iters | **1017 s** | 600 microsimulations | 194.1 | 10.94% | 100% | 50.8% |

**SPSA converges to the exact solver's answer, but needs ~3000 lower-level evaluations to do what one linear solve does instantly**; at a matched 600-evaluation budget it is well short. Simulation in the loop costs another ~30 000x in wall time and lands slightly *worse* than the matched-budget linear run, because simulation noise and od2trips' integer-vehicle quantisation make the objective stochastic. Use LSQ whenever the lower level can be linearised; reach for SPSA only when it genuinely cannot (route choice that responds to the demand being estimated, in-simulation control logic, non-differentiable lower level).

Note that all four solutions — spanning 32% to 51% OD error — passed GEH<5 on 100% of counted links in microsimulation.

**SPSA gain tuning is the failure mode that will cost you an afternoon.** The raw SPSA gradient estimate is `(fp-fm)/(2*ck)`; with `ck ~ 0.1` and an objective in the thousands it is O(1e3), which sends `theta` straight to its clip and the candidate matrix to ~20x the seed. In a simulation-in-the-loop run every subsequent evaluation then gridlocks and takes minutes instead of seconds — the first attempt here hung on iteration 0 for six minutes. `odme_spsa` fixes this by RMS-normalising `ghat` before applying the step and clipping the per-component step to 0.05; keep both.

## Validate on two axes and never conflate them

1. **Count fit** — per-link GEH and %RMSN against the observed counts, plus the share of links with GEH < 5 (see [[geh-statistic]]). This is what ODME optimises, so it is **not evidence the matrix is right.**
2. **OD recovery** — cell-level RMSN/MAE/correlation, total-demand error, and row/column marginal error against a ground truth the estimator never saw. Only computable in a synthetic experiment; in a real study it is *unobservable*, which is exactly the problem.

Establish the **observation noise floor** first: run the ground-truth demand two or three more times with different seeds and compare the count vectors. Here that floor was 6.7-7.0% RMSN (two extra ground-truth runs at different seeds). Any count fit meaningfully tighter than the floor is fitting simulation noise, and doing so actively damages the matrix.

## Choosing `w_s/w_c`

Count fit improves monotonically as `w_s -> 0`. **OD recovery does not** — it is U-shaped:

| `w_s` | count RMSN | GEH<5 | OD RMSN (mean seed was 72.7%) |
|---|---|---|---|
| 1e-4 | 0.09% | 100% | **70.8%** (no better than the seed) |
| 0.01 | 1.37% | 100% | 39.0% |
| **0.1** | 3.21% | 100% | **36.4%** (best) |
| 1 | 9.94% | 100% | 47.4% |
| 100 | 28.18% | 93.5% | 71.6% |

The optimum sits where the count-fit residual is comparable to the observation noise floor. Practical rule: **tune `w_s` so the achieved count RMSN lands near the noise floor, not far below it.** With a *good* seed and near-zero `w_s`, ODME actively destroys it — a seed at 30.5% OD error came out at 62.8% and a 24.7% seed at 63.1%, with even the observable (row-space) error made 94% and 202% worse by fitting count noise.

**That rule is a heuristic, and it failed on a second network — do not apply it blind.** On the 6x6 grid of `design-count-station-locations-for-od-estimation` the count noise floor was 14.14% but the truth-optimal weight was 0.03, achieving a count RMSN of **5.9%, a factor of 2.4 *below* the floor**; the noise-floor rule picks `w_s` = 1 there, which is **17 OD points worse** (64.34% vs 47.56%). The U-shape replicated (63.82 / 49.38 / **47.56** / 47.93 / 52.87 / 64.34 / 78.36 across `w_s` 0.001→3) — only the optimum's position relative to the floor did not. So: always sweep and report the sweep (this skill's step 2 already says so), and treat the noise-floor point as one candidate rather than the answer. `w_s` = 0.1 was a reasonable default on both networks.

**In a comparative study, do not tune `w_s` at all.** Tuning on truth isn't deployable and tuning per arm confounds the comparison. Fix one value for every arm and demonstrate the ranking is invariant by re-running at a low and a high value.

## Gotchas

- **The counted-link set must be given explicitly** (`--p` or `--counted-edges`). Defaulting to "every edge in the edgeData file" pulls in the TAZ attach edges, where edgeData `entered` is **0** for vehicles that *depart* on them while the route file credits them with the whole zone's demand — the comparison then looks catastrophically broken for reasons unrelated to the estimate. This bit during development.
- **Read counts with `entered`, not `left`.** Under congestion teleports remove vehicles mid-edge: at 3x demand `left` was 26 vehicles short of `entered` network-wide and 72 short at 5x (max 19 on a single edge), while `entered` stayed exactly consistent with the routes driven.
- **SUMO resolves the `file=` attribute inside an additional file relative to that additional file's own directory, not the process cwd.** Detector output silently lands next to the `.add.xml`. Copy the one master additional file into each run directory (what `odme_core.simulate` does) — that also guarantees byte-identical detector definitions across runs, the near-miss flagged in [[dfrouter-detector-based-demand-reconstruction]].
- **Zone IDs must match exactly** between the TAZ file and the matrix, or `od2trips` silently emits zero trips for that pair (see `convert-od-matrix-to-trips`).
- **Validate with a seed never used to build P, the observations, or the estimate.** Reusing one turns the closed-loop check into a tautology.
- **Measurement window matters enormously under congestion.** Over a whole run every trip is counted exactly once, so counts are invariant to congestion — verified byte-identical to route-implied counts at 1x, 3x and 5x demand. Restricted to the demand hour, queued flow spills past the window: at 3x demand the free-flow assignment over-predicted measured flow by 21% (GEH<5 fell to 66%), at 5x by 47% (GEH<5 fell to 11%). If your counts come from a fixed field window on a congested network, a free-flow `P` is systematically biased and you need a congested/iterated assignment.

## When ODME output is trustworthy

Run `check_equifinality.py` and report its number. It constructs matrices that reproduce the counts *identically* by moving to vertices of the null-space polytope. On the 5x5 grid, six such matrices each moved ~50% of all trips between OD pairs relative to the ODME solution, ranged 120-141% OD error against the truth (vs 32.1% for the ODME solution), and **every one of them passed GEH<5 on 100% of counted links in full microsimulation.** A further warning: the *uncalibrated* 50%-noise seed, 75.5% wrong in OD terms, already passed GEH<5 on 88.8% of links — above the conventional 85% bar — before ODME ran at all.

So:

- **Trustworthy for policy** when the question depends only on link flows in the counted corridor and its immediate neighbourhood — flow-consistent base-year link volumes, corridor-level before/after, feeding a microsimulation whose outputs are link-based. This has since been confirmed directly: across 13 differently-estimated matrices pushed through microsimulation, OD-recovery error correlated with link-flow error at **Spearman +0.895** (p < 0.001).
- **Report as a flow-consistent adjustment only** — never as recovered demand — when the question is OD-specific: zone-to-zone travel demand, corridor-to-corridor market share, tolling or transit ridership by OD pair, anything where a specific cell or a specific pair of zones carries the answer. Quote the null-space dimension and the equifinality spread alongside the matrix.
- **Also report as a flow-consistent adjustment only when the question is a congestion or delay measure** — total travel time, mean delay, LOS, queue-based impacts. Same experiment: OD-recovery error carried **no usable information** about network delay error (−0.294, p = 0.354, CI [−0.74, +0.34] on n=12 — the sign is not established, do not read it), and the failure is not just a weak correlation. The matrix with the *best* OD recovery (59.6% cell %RMSN) gave **+62.6%** mean-delay error while the *worst* (69.7%) gave **−17.7%**, both far outside a 3.87% run-to-run band, because near a network's gridlock knee delay is convex in loading and the *sign* of a small total-demand error decides whether it tips. A well-fitting matrix is not a licence to report delay.
- The honest headline: **at the tuned weight ODME cut OD error from 72.7% to 36.4% — a real improvement — but with exact counts and a mathematically perfect fit the entire residual error lies in the subspace the counts cannot see.** Seed quality dominated count coverage in every experiment: at full coverage, swapping a 24.7%-error seed for a 268%-error seed moved the answer from 18.2% to 68.4%, while at fixed seed quality, going from 20 counted links to all 80 moved it only from 58.4% to 36.4%.

## Related

- `design-count-station-locations-for-od-estimation` — **use that skill instead when the counted-link set is a choice rather than an input.** This skill's null-space diagnostic can only *diagnose* that the counts don't identify the matrix; that one chooses the links, and reports that the problem generally cannot be designed away (182 OD cells against 123 links whose rank saturated at 94 — full observability unachievable at any budget) and that count fit on the selected links is actively misleading as a design criterion (+0.120 rank correlation with true OD recovery, negative at small budgets). It reuses this skill's `P` builder, solvers and metrics.
- `convert-od-matrix-to-trips` — the TAZ/O-format inputs this skill consumes and produces
- `convert-trips-to-routes`, `assign-traffic-with-marouter` — the two candidate lower-level assignment models
- `calibrate-demand-with-routesampler`, `reconstruct-demand-with-dfrouter` — the count-based alternatives that do *not* produce an OD matrix
- `analyze-simulation-outputs`, `validate-congested-scenario-results-against-teleport-artifacts` — count harvesting and the teleport checks used above
- [[od-matrix-estimation-and-underdetermination]] — the methodology, the verified numbers, and the trustworthiness argument
- [[sensor-location-design-for-od-estimation]] — what happens when the observation set becomes the decision variable
- [[geh-statistic]] — the count-fit acceptance convention, and why it cannot *rank* candidate matrices (47 of 47 designs passed GEH<5 on 100% of instrumented links while spanning 69.6-105% OD error)

## Gotchas specific to running many ODME solves

If you are sweeping designs, weights, or seeds rather than solving once, two things bite that a single run never shows:

- **`scipy.optimize.lsq_linear` is not robust across rank-deficient row subsets.** It raised `LinAlgError: SVD did not converge in Linear Least Squares` (in its internal `np.linalg.lstsq` warm start) on some two-count designs. A ridge-regularised normal-equation solve — the ridge `w_s*diag(1/max(s,1))` makes the matrix strictly positive definite — is unconditionally well posed and ~50x faster; keep `odme_lsq` as the cross-check reference (agreement to ~1e-15 relative L2). `design-count-station-locations-for-od-estimation`'s `placement_lib.estimate` implements this.
- **Confirm the cheap linear solver isn't producing your conclusion.** Spot-check one comparison with `odme_spsa` on both a linear lower level and a real simulation-in-the-loop lower level. In the reference check the design ranking survived all three, but note the trap it exposed: the *worse* design achieved the *better* objective value (F = 9.95 vs 27.21) in every solver while being 40 OD points worse.
