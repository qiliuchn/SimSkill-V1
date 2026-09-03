---
name: quantify-sumo-run-to-run-variability
description: Use this skill when the user wants to determine how much run-to-run noise SUMO's stochastic mechanisms (randomTrips demand seed, sumo simulation seed, driver-behavior dispersion) inject into a metric, wants to know how many replications are needed to detect a given effect size, or wants to design a statistically defensible A/B comparison (with Common Random Numbers or independent seeds) instead of trusting a single run per variant. Covers separating variance sources via controlled replication families, empirical warm-up/initialization-bias detection (MSER-5, Welch's method), required-replication-count calculation, and CRN-vs-independent-seed variance-reduction analysis. Trigger on mentions of run-to-run variability, replication count, statistical significance of a SUMO comparison, common random numbers, warm-up period, initialization bias, or "is this difference real or just noise."
---

# Quantify SUMO Run-to-Run Variability

Determines how much of a SUMO scenario's outcome variance comes from each of its distinct stochastic sources, and uses that to design statistically defensible comparisons — as opposed to every prior comparison-style episode in memory, which drew conclusions from a single run or a handful of paired seeds without ever establishing whether the observed difference exceeded run-to-run noise. This is the first skill in memory to treat SUMO's own randomness as the object of study rather than incidental noise to be shared away with a common seed.

## Separating the three distinct randomness sources

Don't assume "the seed" is one thing — SUMO scenarios built from `randomTrips.py` demand have (at least) three independent sources:

1. **Demand-generation seed** (`randomTrips.py --seed`) — changes which specific OD pairs/routes get sampled.
2. **Simulation seed** (`sumo --seed`) — drives departure-time jitter, lane-change decisions, junction gap-acceptance, and (if enabled) driver behavioral noise.
3. **Driver-behavior dispersion** (vType `sigma`, `speedDev`) — a *magnitude* knob, not a seed, but interacts with the simulation seed to determine how much realized driving actually varies.

Design controlled replication *families* to isolate each: fixed routes + varying sim seed; varying demand seed + fixed sim seed; both varying; and optionally a driver-dispersion-on vs. off comparison. Run at least 30 replications per family per condition.

**Verified counter-intuitive finding: the simulation seed can have *exactly zero* effect.** With vType `sigma=0` and `speedDev=0` and a fixed route file, 30+ distinct `sumo --seed` values produced floating-point-identical mean trip duration in one verified test — every source of simulation-side randomness in that scenario flowed entirely through driver dispersion, which was turned off. This does **not** generalize to scenarios using the rerouting device, sublane/lane-change-sigma, random depart-offset, or `vTypeDistribution` — those reintroduce simulation-seed sensitivity through different mechanisms. Always test this directly for a given scenario rather than assuming either "the seed matters" or "the seed doesn't matter."

**The demand-generation seed typically dominates.** In one verified test, `randomTrips`'s own seed contributed 3-5x the variance of the simulation seed at every demand level, and variance additivity (`Var(both) ≈ Var(demand-only) + Var(sim-only)`) held reasonably well under moderate demand but **failed** near and above capacity (observed total variance 140-190% of the additive prediction) — an expected consequence of nonlinear, threshold-triggered dynamics (e.g. gridlock) near saturation, not a bug in the variance calculation. Report whether additivity holds rather than assuming it.

## Coefficient of variation is not monotone in demand — it can peak at capacity

**Verified finding**: CV of mean trip duration was small under both light load and clear oversaturation, but spiked sharply right at the capacity knee (one verified case: 1.0% → 52.0% → 9.9% across undersaturated/near-critical/oversaturated levels). The mechanism is **bimodality**, not smoothly increasing noise: near capacity, a given replication either happens to gridlock or happens not to, and the two outcomes are wildly different, so the mean ± standard deviation is a poor summary of the actual distribution there. Throughput/completed-trip-count CV, by contrast, tends to increase monotonically with demand and stays much smaller — report multiple metrics' CV separately rather than assuming they track together, and consider reporting the fraction of replications that gridlock as a more honest statistic than a mean at the knee.

## Measuring capacity correctly, as a prerequisite for calibrating loading levels

**Don't measure capacity by loading the network as hard as possible.** A signalized network driven far past its actual capacity gridlocks, and *served* flow collapses well below the true peak (verified case: naive extreme loading measured an order of magnitude below actual capacity). Capacity is the **peak of the flow-vs-demand curve** — sweep demand from light to heavy and find where served flow (from `edgeData`) stops increasing and starts falling, not the flow at the highest demand tested. Cross-validate demand-side v/c (computed from planned routes) against measured (edgeData-served) v/c — they should agree closely below capacity and diverge exactly at the point flow stops tracking demand, which is itself a useful confirmation that the capacity estimate is right.

## Empirical warm-up (initialization-bias) detection

Use a real statistical method — MSER-5 (minimizes a scaled sum-of-squared-deviations statistic over candidate truncation points, White 1997) or Welch's moving-average-band method — on the running-vehicle-count or instantaneous mean-speed time series from `summary` output, not an arbitrary fixed cutoff. **A genuine steady state may not exist at every demand level** — verified case: a clean steady state (and a well-defined warm-up point) existed only at the undersaturated level; both methods correctly flagged the near-critical and oversaturated levels as non-stationary (persistent drift, or the truncation-point search pinned to its own search boundary) rather than forcing a spurious warm-up estimate. **These are terminating, transient simulations at high demand, not systems with a steady state to warm up into** — truncating an early window under the false assumption of stationarity there would introduce bias, not remove it. Quantify the actual bias of including vs. excluding any candidate warm-up window directly, rather than assuming a warm-up correction always helps.

## Required replication count

Standard formula: `n = (t_{n-1, 0.975} * s / d)^2`, where `s` is the observed sample standard deviation and `d` is the target absolute half-width (e.g. 5% of the mean). Solve iteratively (t depends on `n`) or via fixed-point iteration; watch for oscillation in a naive fixed-point loop at small `n` (e.g. bouncing between n=2 and n=7) — a degenerate case worth detecting and handling explicitly (e.g. `n<2` has no meaningful degrees of freedom) rather than trusting whichever value a fixed iteration count happens to land on. **Don't assume required n increases monotonically with demand/variance** — the CV-peaks-at-capacity finding above means the *required replication count* can also be non-monotone (verified case: fewer replications needed at the highest, most oversaturated level than at the near-critical level, because a terminating oversaturated run's relative variance was actually lower than the bimodal near-critical case's).

## Common Random Numbers vs. independent seeds

To evaluate a real treatment (e.g. a signal-timing change), run both a **paired design** (same seed list used in both the baseline and treatment arms — Common Random Numbers) and an **independent design** (separate, unrelated seed lists per arm), then compare a paired t-test against a two-sample (Welch) t-test.

- **CRN reduces variance of the estimated difference when the paired outcomes are positively correlated** — verified variance-reduction factors of 1.9-3.3x for well-correlated metrics.
- **CRN can *increase* variance of the difference estimate for a weakly-correlated metric** (verified: VRF 0.77x, i.e. CRN hurt, for a queue-length metric with correlation ≈0.14 at low demand) — don't assume CRN is free money; it depends on the actual correlation between paired-seed outcomes for that specific metric, which should be measured, not assumed.
- **Near a demand knee, CRN and independent designs can disagree in the *sign* of an estimated treatment effect**, with both non-significant — a genuine illustration of why a single comparison (paired or not) near a system's capacity threshold is unreliable regardless of design sophistication.

## Evaluating whether an existing single/few-seed comparison protocol was sound

Compute the minimum detectable difference (MDD) at `n=1` (a single comparison) against the measured standard deviation, and separately check how often a single paired-seed comparison reproduces the *sign* of a well-replicated (e.g. 40-replication) result. Verified finding in one scenario: single-seed comparisons were **sound** below roughly 60% of capacity for effects larger than a few percent (and a shared-seed protocol is, without necessarily being labeled as such, an accidental CRN design — which is part of why it worked better than an independent-seed single comparison would have), **marginal** in the 60-80%-of-capacity range or for queue-type metrics, and **unsafe** at 85%+ of capacity, where a single comparison reproduced the correctly-signed 40-replication result only about a fifth to a half of the time depending on the metric. This kind of explicit sound/marginal/unsafe demand-dependent verdict — not a blanket "always fine" or "always need more seeds" — is the right level of honesty for evaluating any specific comparison-style episode's methodology.

## Gotchas

- **`edgeData`'s `file` output path resolves relative to the additional file's own directory, not SUMO's invoking working directory** (verified directly against the SUMO binary — see the corrected `analyze-simulation-outputs`/`sumo-output-files` entries). In a parallel batch-replication study this matters enormously: multiple workers sharing one additional file will silently overwrite each other's edgeData output unless each replication gets its own additional-file copy or an explicit per-run absolute path.
- **Don't assume "the seed matters" or "the seed doesn't matter" without testing** — both are scenario-dependent, and the specific mechanism (driver dispersion on/off, rerouting device present/absent) determines which sources of randomness actually propagate to outcomes.
- **A single mean ± CI is a poor summary near a capacity knee** where the outcome distribution is bimodal — report the gridlock/non-gridlock split, not just a mean, in that regime.
- **Required replication count is not monotone in demand level** — check it empirically per condition rather than assuming heavier demand always needs more replications.
- **CRN is not universally beneficial** — measure the actual paired correlation for the specific metric in question before assuming it reduces variance.

## Feeding the noise floor into an optimizer

This skill measures run-to-run variability; `optimize-under-simulation-noise-with-a-fixed-budget`
is what to do with the number once a *search* is involved, and the extension is not obvious:

- **Convert sigma into a resolvable-difference threshold** and check every reported margin
  against it: `resolvable(n) = 1.96*sqrt(2)*sigma/sqrt(n)` (independent) or
  `1.96*sqrt(2*(1-rho))*sigma/sqrt(n)` (CRN-paired). Measured at CV~4.25%, nothing below
  **10.85%** is detectable at n=1 — and 9 of 10 pairwise differences between a study's final
  plans fell below that.
- **Pool sigma over near-optimal candidates**, not over a range that includes a degenerate one —
  that inflated sigma 1.9x and the threshold to 20.5%. An optimizer compares candidates near the
  optimum.
- **Selection amplifies noise beyond what a two-way A/B suffers.** This skill's protocol is
  "sound below ~60% of capacity, marginal to 80%". Under optimization the failure arrives
  earlier: at **77% of capacity** a 300-evaluation single-seed search produced a plan that looked
  10.0% better than a zero-run analytic baseline in-sample and was 1.8% worse out-of-sample.
- **Replicating during a search is a net loss at this CV** (5x replication bought 1.38x variance
  reduction at 5x the exploration cost). Spend the budget on designs and validate the winner on
  >=30 held-out seeds instead.

See [[simulation-based-optimization-under-noise-and-seed-overfitting]].

## Related

- `create-grid-network` — the network-building technique used for this skill's test scenario.
- `generate-random-trips` — the demand-generation tool whose `--seed` is one of the variance sources isolated here.
- `analyze-simulation-outputs` — general tripinfo/summary/edgeData parsing conventions this skill's batch analysis follows; its `edgeData` path-resolution gotcha was corrected as part of this skill's verification work.
- [[sumo-stochastic-variability-and-replication-design]] — the verified variance-decomposition, warm-up, required-n, and CRN findings, plus the explicit sound/marginal/unsafe guidance for evaluating an existing comparison's statistical soundness.
- `measure-travel-time-reliability-with-simulated-days` — reuses this skill's CV-peaks-at-the-knee finding to justify a stratified (not single-demand-level) seed-noise-floor design, and treats variability as the outcome of interest rather than noise to control away.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — extends this skill's CRN discipline to hold across sensing configurations (not just seeds), and found a new false-failure mode specific to that use: `tripinfo`'s `devices` bookkeeping attribute legitimately differs between sensing arms and must be excluded from any byte-identity check.
