---
name: optimize-under-simulation-noise-with-a-fixed-budget
description: Use this skill whenever a SUMO simulation is the objective function of a search — signal timing, ramp-metering gains, calibration parameters, fleet sizing, any black-box tuning — because SUMO's output is a random variable and a fixed-seed optimum is an estimate on one sample, not an answer. Covers measuring the noise floor BEFORE optimizing and converting it into the minimum difference resolvable at n replications, quantifying what common random numbers actually buy, enforcing a hard evaluation budget, held-out-seed validation and the seed-overfitting gap, budget-efficiency curves, and a hand-rolled Gaussian-process/expected-improvement optimizer with an analytic trend function (no scikit-learn needed). The measured headline: a single-seed GA's plan looked 10.0% better than a zero-search analytic baseline in-sample and was 1.8% WORSE out-of-sample, with a negative overfitting gap in 3 of 3 repeats. Trigger on simulation-based optimization, black-box or derivative-free optimization, Bayesian optimization, surrogate or metamodel or kriging or response surface, sample average approximation, computational or evaluation budget, replications per design point, overfitting to a seed, held-out validation, "is this improvement real", or any use of a GA/CMA-ES/particle swarm over SUMO runs.
related_skills:
  - optimize-signal-plan-with-simulation-in-the-loop-ga
  - quantify-sumo-run-to-run-variability
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - screen-and-decompose-sumo-parameter-sensitivity
related_skills_for_graph_view:
  - "[[optimize-signal-plan-with-simulation-in-the-loop-ga]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
related_pages:
  - "[[simulation-based-optimization-under-noise-and-seed-overfitting]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[webster-method]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
---

# Optimize Under Simulation Noise With a Fixed Budget

Every optimization skill in this memory used to freeze one seed and report the in-sample
optimum. That makes the search well-posed and the reported number wrong. This skill is the
protocol that fixes it, plus the measurement showing how much it matters.

**The headline, measured on a 5-signal arterial at 77% of capacity, 300 evaluations per
optimizer, 40 held-out seeds:** the single-seed GA's plan looked **10.0% better** than a
zero-search `tlsCycleAdaptation`+`tlsCoordinator` baseline in-sample, and was **1.8% worse**
out-of-sample. Three hundred simulation runs bought *negative* value against a plan costing
zero runs. Repeated on three different frozen seeds, the overfitting gap was negative **3/3**
and the GA won only **1/3** — and which seed you happen to freeze moved true plan quality by
**7.48%**, more than the difference between most optimizers.

## The protocol

```
1. Site the demand deliberately     -> know where you are on the variability curve
2. Measure the noise floor FIRST    -> resolvable difference at n = 1, 3, 5, 10
3. Check each variable is resolvable-> don't optimize below your own noise floor
4. Enforce a hard evaluation budget -> so optimizers are actually comparable
5. Always carry a zero-search baseline
6. Re-score the incumbent on >=30 HELD-OUT seeds  <- the number you report
7. Report the seed-overfitting gap
```

Steps 2 and 6 are the ones people skip, and they are the ones that changed the answer.

## Scripts

- `scripts/evalpool.py` — thread-pool SUMO evaluator plus a **hard** `Budget` counter:
  `take()` raises `BudgetExhausted` *before* dispatching a run, so the cap is enforced
  rather than merely reported. Log every evaluation to CSV with `eval_index`, `seed`,
  `objective`, `best_so_far` — a budget claim you cannot audit from a file is not a claim.
- `scripts/noise_floor.py` — evaluates fixed plans across many seeds and emits the
  resolvable-difference table and the CRN variance-reduction factor. `--from-cache`
  re-derives thresholds from stored arrays without re-simulating.
- `scripts/opt_bo.py` — a **self-contained Gaussian-process optimizer** (Matérn-5/2, grouped
  length-scales, REML hyperparameter fitting via L-BFGS-B on the profiled log-marginal
  likelihood, Cholesky solves, universal-kriging mean, EI acquisition with multi-start).
  Needs only numpy/scipy — **no scikit-learn**.

Full worked implementation (testbed, four optimizer arms, held-out validation, budget curves)
in `episodic-memory/2026-08-11_21-20-19/attempts/attempt-1/scripts/`.

## Measure the noise floor before optimizing anything

Evaluate a few fixed plans across ≥30 seeds and convert the spread into the **minimum
difference two plans must differ by to be distinguishable at n replications**:

```
resolvable(n) = 1.96 * sqrt(2) * sigma / sqrt(n)          # independent seeds
              = 1.96 * sqrt(2 * (1-rho)) * sigma / sqrt(n) # CRN-paired
```

Measured (CV ≈ 4.25% near the optimum):

| n | independent | CRN-paired |
|---|---|---|
| **1** | **8,656 (10.85%)** | **7,374 (9.25%)** |
| 3 | 4,998 (6.27%) | 4,257 (5.34%) |
| 5 | 3,871 (4.85%) | 3,298 (4.13%) |
| 10 | 2,737 (3.43%) | 2,332 (2.92%) |

**Any margin below the n=1 threshold is noise.** In the study, **9 of 10** pairwise
differences between the final plans — including the winning margin — fell below it: real when
measured with 40 replications, undetectable by the single-seed protocol that produced them.

**Pool sigma over near-optimal plans, not over everything.** Including a deliberately
degenerate plan inflated sigma 1.9× (3,123 → 5,898) and the threshold to 20.5%. Optimizers
compare candidates *near the optimum*, so that is the regime whose variance matters. Note
this is the conservative direction — a smaller threshold makes it *harder* to dismiss a margin
as noise.

## What CRN actually buys — measure rho, don't assume

| pair | rho | variance-reduction factor |
|---|---|---|
| near-optimal pair | **+0.279** | **1.38× (analytic) / 1.75× (empirical) — helped** |
| moderately different | +0.182 | 1.22× / 1.06× — marginal |
| dissimilar plans | **−0.013** | **0.99× / 0.69× — did not help, empirically hurt** |

CRN helps for the similar-plan comparisons an optimizer actually makes, but only ~28% fewer
replications — far below the 1.9–3.3× recorded for well-correlated metrics in
[[sumo-stochastic-variability-and-replication-design]], and **nothing at all** for dissimilar
plans. Measure rho for *your* metric before budgeting around it.

## Replications per design point: 1. But never report the in-sample optimum.

These sound contradictory and are not. At CV ≈ 4%, spending budget on replications was a net
loss: the sample-average-approximation GA (60 designs × 5 reps with CRN) finished **worst of
all four arms**, 6.4% behind the zero-run baseline, because 5× replication bought only 1.38×
variance reduction at 5× the exploration cost. **Buy designs, not replications.**

The fix for noise is not replication during search — it is **validation after it**. Re-scoring
the final incumbent on 30 held-out seeds costs 10% of a 300-run budget and is the difference
between a 10%-better claim and a 1.8%-worse reality.

**Report the seed-overfitting gap** = (in-sample objective at its own search seed) − (held-out
mean). Measured: −5.33% (single-seed GA), −3.65% (SAA GA), −8.69% (GP, constant trend), −4.24%
(GP, analytic trend). **Every searcher was negative.**

**Include a zero-search baseline as the control.** Its gap was **+7.07%** — positive, showing
the search seed was simply a hard seed for that plan and there is no global "easy seed" effect
that could explain the searchers' uniformly negative gaps. Without that control you cannot
distinguish selection bias from a seed offset. It also *won*: the analytic baseline beat two
of four 300-run optimizers out-of-sample.

## A GP surrogate with an analytic trend beats a GA on the same budget

Held-out incumbent vs runs consumed; target = within 2% of the best plan anyone found:

| runs | GA single | GA SAA | GP const trend | **GP Webster trend** |
|---|---|---|---|---|
| 80 | 72,488 | 89,198 | **61,196** | 66,119 |
| **100** | 65,827 | 89,198 | 61,196 | **59,030 ← 2% band** |
| 300 | 65,608 | 68,431 | 62,684 (**degraded**) | **58,443** |

- The analytic-trend GP is the **only** arm to reach the 2% band, at **100 runs**; neither GA
  reaches it in 300. At 100 runs it already beats the GA's 300-run answer by **10.1%** — ≥3×
  fewer runs for a strictly better plan — and it never degrades.
- **The constant-trend GP shows seed overfitting in the curve itself**: it bottoms at run 80,
  then gets *worse out-of-sample* while its in-sample curve keeps improving. Plot both curves;
  the divergence between them is the overfitting, made visible.
- **Use an analytic prediction as the GP's mean function**, not a constant — Webster delay
  here, via a universal-kriging basis `[1, D_analytic]`. Controlled comparison (both arms share
  a byte-identical Sobol initial design, so the trend function is the *only* difference): the
  constant trend descends faster early, but the analytic trend overtakes decisively at 100 runs
  and holds. It buys a better and drift-free final answer, not a faster start.
- **Encode periodic variables periodically.** Signal offsets are periodic in the cycle, not
  monotone ([[arterial-signal-progression-resonance-bandwidth-and-delay]]), so feed the GP
  `cos/sin(2*pi*offset/cycle)` rather than raw seconds.

## Check that a variable is resolvable before optimizing it

Vary one variable group alone, holding the rest fixed, and compare its whole range of effect to
the n=1 threshold. Measured: all 5 offset variables together spanned **2,717 (4.58%)** — well
*below* the 7,374 a single-seed comparison can resolve. A single-seed search structurally
cannot tune them on that testbed. The GP found this independently by pinning its offset
length-scale to the upper bound in **both** runs: the surrogate correctly concluded the
objective is nearly flat in those dimensions.

Optimizing a dimension whose entire effect is smaller than your noise floor is wasted budget —
and worse, the search will still return *some* offset vector and it will look meaningful.

## When BENCHMARKING rather than optimizing: sweep the candidate's own parameters first

Everything above is about handling noise correctly while searching. A different failure mode
bites when you are *ranking* an algorithm against baselines — and this skill's noise discipline
does not catch it, because the noise handling can be flawless while the answer is still an
artifact.

**Sweep the candidate controller/algorithm's own constraint parameters before you rank it.**
Measured, from `implement-predictive-rolling-horizon-signal-control`: a predictive signal
controller was benchmarked with its minimum green time hard-coded at 8 s. That pinned it to its
own constraint boundary — its optimizer returned "switch at the first legal stage" in 72–80% of
decisions, so the realised policy was a fixed-order minimum-green cycler, not an optimizer at
all. Raising the bound to 12 s moved three arms from 77.5 / 53.2 / 24.1 to **29.3 / 29.4 / 28.2**
s/veh and made a 53-second apparent gap-to-upper-bound vanish entirely. The CRN pairing,
replication count and resolvable-difference test in that study were all correct; the parameterisation
of the thing being benchmarked was not, and every headline was wrong.

Three riders:

- **Report the ranking's robustness to the knob, not the ranking at one point.** The corrected
  study's conclusion held at *every* minimum green from 8 to 20 s and at each cell's own best
  horizon — that is what made a negative result trustworthy rather than a lucky point.
- **Fixing an operating point before the sweep that would have chosen it repeats the mistake.**
  That same study fixed its horizon at 30 s before the horizon sweep ran, which later found 10 s
  better. It verified the ranking survived — the minimum you owe a reader — but did not re-optimize.
- **Watch for a knob that silently controls something else.** 50–64% of that controller's greens
  ended exactly on the minimum-green bound at *every* value tested, so the parameter was really
  setting cycle length (realised cycle 54→138 s as it went 8→20 s). Much of that "parameter sweep"
  was a cycle-length optimum, not a control-logic effect. Recover the derived quantity and say so.

## Gotchas

- **`sigma=0` / `speedDev=0` makes the SUMO seed have exactly zero effect** — the noise you set
  out to study disappears and every seed gives an identical answer. Give the vType real
  dispersion (e.g. `sigma=0.5`, `speedDev=0.10`) before claiming to measure run-to-run
  variability.
- **Site the demand deliberately and say where it sits.** Capacity is the *peak* of the
  served-flow-vs-demand sweep, not the flow at the heaviest demand tried — here served flow
  peaked at scale 1.50 and *fell* at 1.80. Per
  [[sumo-stochastic-variability-and-replication-design]], single-seed protocols are sound below
  ~60% of capacity, marginal to 80%, unsafe at 85%+.
- **Hold the demand fixed and vary only the simulation seed** if the task says "fixed demand" —
  keep `randomTrips`/`duarouter` seeds constant and change only `sumo --seed`.
- **Keep the seed books provably disjoint**: search, noise-floor, held-out, and any
  budget-curve re-scoring must not share a single seed. Write them as explicit ranges and
  audit them from the logs, not from a comment.
- **One algorithmic draw is not an algorithm comparison.** With one run per arm, a "method A
  beats method B" claim is n=1 even when the *plan* comparison rests on 40 replications. Say
  which of the two you are claiming. Replicating the search across frozen seeds is what turned
  this study's headline from anecdote into a 3/3 result.

## Related

- [[simulation-based-optimization-under-noise-and-seed-overfitting]] — the knowledge page behind this skill
- `optimize-signal-plan-with-simulation-in-the-loop-ga` — the skill this one corrects and
  succeeds; its genome encoding, clamping decoder and tlLogic writer are reused here
- `quantify-sumo-run-to-run-variability` — supplies the replication and CRN machinery this
  protocol feeds into an optimizer's design
- `optimize-signals-by-tlscycleadaptation`, `optimize-signals-by-tlscoordinator` — the
  zero-search baseline that must always be carried through to held-out comparison
- `screen-and-decompose-sumo-parameter-sensitivity` — space-filling designs for the surrogate's
  initial sample
- [[sumo-stochastic-variability-and-replication-design]], [[webster-method]],
  [[simulation-in-the-loop-ga-signal-optimization]]
