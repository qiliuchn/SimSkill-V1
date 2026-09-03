---
summary: A fixed-seed SUMO optimum is an estimate on one sample, and the error is large enough to reverse a conclusion — a single-seed GA's plan looked 10.0% better than a zero-search analytic baseline in-sample and was 1.8% worse on 40 held-out seeds, with a negative seed-overfitting gap in 3 of 3 repeats and a 7.48% swing in true plan quality depending only on which seed was frozen; also establishes the resolvable-difference threshold (nothing below ~10.9% is detectable at n=1), that CRN buys only 1.38x near the optimum and nothing for dissimilar plans, that replications during search are a net loss while held-out validation after it is essential, and that a GP surrogate with an analytic (Webster) trend reached a better plan in one third of the runs than a GA.
keywords:
  - simulation-based-optimization
  - seed-overfitting
  - held-out-validation
  - resolvable-difference
  - noise-floor
  - common-random-numbers
  - sample-average-approximation
  - bayesian-optimization
  - gaussian-process
  - kriging
  - metamodel
  - expected-improvement
  - computational-budget
  - budget-efficiency
  - analytic-trend-function
created: 2026-08-11T23:15:00
last_updated: 2026-09-01T10:21:28
sources:
  - "[[episodic-memory/2026-08-11_21-20-19/summary.md]]"
related_pages:
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[webster-method]]"
  - "[[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[transit-network-design-and-frequency-setting]]"
related_skills:
  - optimize-under-simulation-noise-with-a-fixed-budget
  - optimize-signal-plan-with-simulation-in-the-loop-ga
  - quantify-sumo-run-to-run-variability
  - screen-and-decompose-sumo-parameter-sensitivity
  - design-transit-service-plan-under-a-bus-hour-budget
related_skills_for_graph_view:
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[optimize-signal-plan-with-simulation-in-the-loop-ga]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
---

# Simulation-Based Optimization Under Noise and Seed Overfitting

When a SUMO run is the objective function, the objective is a random variable. Optimizing it
at one frozen seed makes the search well-posed and the reported result an estimate on a single
sample — and the resulting bias is not small. Measured on a 5-signal arterial (11 decision
variables, 77% of measured capacity, CV ≈ 4.25% near the optimum), four optimizers under an
identical hard budget of 300 SUMO evaluations, validated on 40 seeds never used in any search.

## The headline: a fixed-seed optimum can reverse out-of-sample

| method | in-sample | held-out (40 unseen seeds) | seed-overfitting gap |
|---|---|---|---|
| GA, single frozen seed (300×1) | 61,769 | 65,247.7 ± 763.5 | **−5.33%** |
| GA, sample-average (60 designs × 5 reps, CRN) | 65,704 | 68,189.4 ± 822.8 | −3.65% |
| GP surrogate, constant trend | 57,530 | 63,003.7 ± 589.4 | **−8.69%** |
| GP surrogate, **Webster analytic trend** | 56,180 | **58,668.9 ± 648.4** | −4.24% |
| analytic baseline, **0 simulation runs** | 68,605 | 64,072.2 ± 653.3 | **+7.07%** |

`gap = (in-sample at its own search seed) − (held-out mean)`.

**The single-seed GA's advantage does not shrink — it reverses.** In-sample its plan looked
**10.0% better** than a zero-search `tlsCycleAdaptation`+`tlsCoordinator` baseline; out-of-sample
it is **1.8% worse**. Three hundred simulation runs bought negative value against a plan costing
zero.

**The zero-search baseline is the control that proves this is selection bias.** It did no
seed-specific search, and its gap is *positive* (+7.07%) — so the search seed was simply a hard
seed for that plan, and there is no global "easy seed" effect that could explain why every
searcher's gap is negative. Without carrying a zero-search arm through to held-out evaluation,
selection bias and a seed offset are indistinguishable.

**Replicated across frozen seeds**, the gap was negative in **3/3** (−5.33%, −6.26%, −3.06%),
the GA beat the zero-run baseline in only **1/3**, and **which seed you happen to freeze moved
true plan quality by 7.48%** — larger than the difference between most of the optimizers.

## The resolvable-difference threshold

Convert the noise floor into the minimum difference two plans must show to be distinguishable:

```
resolvable(n) = 1.96 * sqrt(2) * sigma / sqrt(n)            # independent seeds
              = 1.96 * sqrt(2*(1-rho)) * sigma / sqrt(n)    # CRN-paired
```

| n | independent | CRN-paired |
|---|---|---|
| **1** | **8,656 (10.85%)** | **7,374 (9.25%)** |
| 3 | 4,998 (6.27%) | 4,257 (5.34%) |
| 5 | 3,871 (4.85%) | 3,298 (4.13%) |
| 10 | 2,737 (3.43%) | 2,332 (2.92%) |

**Nine of the ten pairwise differences between the final plans fall below the n=1 threshold** —
including the winning margin. They are real when measured with 40 replications and *undetectable
by the single-seed protocol that produced them*.

Pool sigma over **near-optimal** plans, not over everything: including a degenerate plan inflated
sigma 1.9× (3,123 → 5,898) and the threshold to 20.5%. Optimizers compare candidates near the
optimum, so that is the relevant variance regime — and the smaller threshold is the conservative
choice, since it makes a margin *harder* to dismiss as noise.

## What common random numbers actually buy

| pair | rho | variance-reduction factor |
|---|---|---|
| near-optimal pair | **+0.279** | **1.38× analytic / 1.75× empirical — helped** |
| moderately different | +0.182 | 1.22× / 1.06× — marginal |
| dissimilar plans | **−0.013** | **0.99× / 0.69× — no help, empirically hurt** |

CRN helps exactly where an optimizer works — comparing similar candidates — but only ~28% fewer
replications, far below the 1.9–3.3× that [[sumo-stochastic-variability-and-replication-design]]
records for well-correlated metrics, and nothing at all for dissimilar plans. That page's "CRN is
not free money" finding reproduces here on a different metric. Measure rho before budgeting
around it.

### The benefit is contingent on the vehicle population staying fixed

Every rho above was measured over *signal plans*, where all designs simulate an identical set of
vehicles and only the timing differs. That is a favourable special case. When the design variable
changes the vehicle population itself, CRN can go **negative** — a transit frequency-allocation
study measured rho across six design pairs at **+0.138, −0.028, −0.078, −0.271, −0.299, −0.450,
four of six negative**, because changing a line's bus count changes the number and identity of
bus vehicles, so SUMO consumes its `--seed` stream in a different order and the numbers are no
longer *common* between designs. Pairing on seed then *increases* the variance of the difference
rather than reducing it, and the CRN-paired column of the resolvable-difference table becomes
optimistic. Ask whether the design change adds, removes or renames vehicles before pairing. See
[[transit-network-design-and-frequency-setting]].

## Replications during search are a net loss; validation after it is essential

These are not in tension. At CV ≈ 4%, the sample-average-approximation GA (60 designs × 5
replications) finished **worst of all four arms** — 6.4% behind the zero-run baseline — because
5× replication bought only 1.38× variance reduction while costing 5× the exploration. **Buy
designs, not replications.**

The remedy for noise is not averaging during the search but **re-scoring the final incumbent on
≥30 held-out seeds**, which costs ~10% of a 300-run budget and is the difference between a
10%-better claim and a 1.8%-worse reality.

This has a direct bearing on every calibration result in this memory: an optimum reported at one
seed carries a systematic optimistic bias of roughly 3–9% of the objective, in addition to any
identifiability problem (cf. [[car-following-parameter-calibration-and-identifiability]] and
[[od-matrix-estimation-and-underdetermination]], which concern *which* parameters, not *how
optimistic* the fit).

## Budget efficiency: a GP with an analytic trend beats a GA

Held-out incumbent vs runs consumed; target = within 2% of the best plan anyone found (59,612):

| runs | GA single | GA SAA | GP const | **GP Webster** |
|---|---|---|---|---|
| 80 | 72,488 | 89,198 | **61,196** | 66,119 |
| **100** | 65,827 | 89,198 | 61,196 | **59,030 ← enters band** |
| 300 | 65,608 | 68,431 | 62,684 (**degraded**) | **58,443** |

- The analytic-trend GP is the **only** arm to reach the 2% band, at **100 runs**; neither GA
  reaches it in 300. At 100 runs it already beats the GA's 300-run answer by 10.1% — ≥3× fewer
  runs for a strictly better plan — and never degrades.
- **The constant-trend GP makes overfitting visible in the curve itself**: it bottoms at run 80,
  then gets *worse out-of-sample* while its in-sample curve keeps improving. Plotting the
  in-sample and held-out curves together turns seed overfitting into something you can see.
- **An analytic mean function is worth more than a faster start.** In a controlled comparison
  (both GP arms share a byte-identical Sobol initial design, so the trend is the only
  difference), the constant trend descends faster at run 80; the Webster trend overtakes
  decisively at run 100 and holds. It buys a better, drift-free final answer.
- Encode periodic variables periodically — signal offsets are periodic in the cycle rather than
  monotone ([[arterial-signal-progression-resonance-bandwidth-and-delay]]), so the GP takes
  `cos/sin(2*pi*offset/cycle)`.

## Check a variable is resolvable before optimizing it

Varying only the 5 offset variables gave a total spread of **2,717 (4.58%)** — *below* the
7,374 a single-seed comparison can resolve. A single-seed search structurally cannot tune them
on this testbed, and the GP discovered this independently by pinning its offset length-scale to
the upper bound in both runs. Optimizing a dimension whose entire effect is smaller than the
noise floor is wasted budget, and the search will still return a confident-looking answer for it.

## Practical notes

- **`sigma=0` / `speedDev=0` makes the SUMO seed have exactly zero effect** — the variability
  under study vanishes. Give the vType real dispersion before measuring run-to-run noise.
- **Capacity is the peak of the served-flow-vs-demand sweep**, not the flow at the heaviest
  demand tried (here served flow peaked at scale 1.50 and *fell* at 1.80). Site the operating
  point deliberately and state where it sits: single-seed protocols are sound below ~60% of
  capacity, marginal to 80%, unsafe at 85%+.
- **Enforce the budget, don't just report it** — a counter that raises before dispatching a run,
  with a per-evaluation CSV log, is auditable; a reported total is not.
- **Keep seed books provably disjoint** across search, noise floor, held-out validation and any
  re-scoring sweep, and audit them from the logs rather than from a comment.
- **One algorithmic draw is not an algorithm comparison.** With one run per arm, "method A beats
  method B" is an n=1 claim even when the *plan* comparison rests on 40 replications. Replicating
  the search across frozen seeds is what turns an anecdote into a result.
