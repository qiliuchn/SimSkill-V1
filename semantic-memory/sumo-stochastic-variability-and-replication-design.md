---
summary: SUMO's run-to-run variability, decomposed by source (demand-generation seed, simulation seed, driver-behavior dispersion) via 786 controlled replications on a signalized grid, is non-monotone in demand — coefficient of variation of mean trip duration peaks sharply at the capacity knee due to bimodal gridlock/non-gridlock outcomes — and Common Random Numbers reduces variance for well-correlated metrics but can increase it for weakly-correlated ones; a single/few-seed A/B comparison protocol was found sound below roughly 60% of capacity, marginal up to 80%, and unsafe at 85%+ of capacity, where it reproduces the correct-sign result of a well-replicated study only a fifth to a half of the time.
keywords:
  - stochastic-variability
  - replication-design
  - common-random-numbers
  - warm-up-period
  - variance-decomposition
  - statistical-significance
created: 2026-07-31T13:20:00
last_updated: 2026-08-11T23:15:00
sources:
  - "[[episodic-memory/2026-08-11_21-20-19/summary.md]]"
  - "[[episodic-memory/2026-07-31_12-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_12-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[simulation-based-optimization-under-noise-and-seed-overfitting]]"
  - "[[sumo-output-files]]"
  - "[[curbside-delivery-blocking-externality]]"
  - "[[travel-time-reliability-metrics-in-sumo]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
  - "[[stochastic-freeway-capacity-and-breakdown-probability]]"
  - "[[state-serialization-and-rolling-horizon-traffic-forecasting]]"
  - "[[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]"
related_skills:
  - optimize-under-simulation-noise-with-a-fixed-budget
  - quantify-sumo-run-to-run-variability
  - generate-random-trips
  - analyze-simulation-outputs
  - model-curbside-delivery-and-lane-blocking-externality
  - measure-travel-time-reliability-with-simulated-days
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - characterize-pedestrian-flow-and-striping-model-artifacts
  - estimate-stochastic-freeway-capacity-and-breakdown-probability
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
  - screen-and-decompose-sumo-parameter-sensitivity
related_skills_for_graph_view:
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[generate-random-trips]]"
  - "[[analyze-simulation-outputs]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[measure-travel-time-reliability-with-simulated-days]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
  - "[[estimate-stochastic-freeway-capacity-and-breakdown-probability]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
---

# SUMO Stochastic Variability and Replication Design

Every SUMO scenario built from randomized demand carries at least three distinct, independently-controllable sources of run-to-run variability: the demand-generation seed, the simulation seed, and driver-behavior dispersion parameters. This page documents the first attempt in this memory to actually quantify how much noise these sources inject and use that to evaluate whether this project's existing habit of comparing scenarios via a single run or a handful of paired seeds has been statistically defensible. See `quantify-sumo-run-to-run-variability` for the full replication methodology.

## Verified finding: variability is not monotone in demand — it peaks at the capacity knee

Measured on a 4x4 signalized grid at three calibrated loading levels (undersaturated, near-critical, oversaturated), the coefficient of variation of mean trip duration across 30+ replications was small under light load, **spiked sharply right at the capacity knee**, and fell again under clear oversaturation (one verified case: 1.0% → 52.0% → 9.9%). The mechanism is **bimodality, not smoothly rising noise**: near capacity, a given replication either happens to tip into gridlock or happens not to, and the two outcomes differ enormously — a mean ± standard deviation summary is actively misleading in this regime. Throughput/completed-trip CV, in contrast, rose roughly monotonically with demand and stayed much smaller throughout. **This means the demand level at which most "interesting" traffic phenomena live (near saturation) is exactly the regime where a single-run conclusion is least trustworthy.**

## Verified finding: demand seed usually dominates simulation seed, sometimes completely

The `randomTrips` demand-generation seed contributed 3-5x the variance of the `sumo` simulation seed at every demand level tested. In one scenario configuration (driver-behavior dispersion parameters `sigma`/`speedDev` set to zero, fixed route file), the simulation seed had **exactly zero measurable effect** — 30+ distinct seed values produced floating-point-identical outcomes, because every source of simulation-side stochasticity in that configuration flowed through driver dispersion, which was disabled. This is scenario-specific, not universal: the rerouting device, lane-change/sublane noise, random depart offsets, or a `vTypeDistribution` would each reintroduce simulation-seed sensitivity through a different mechanism. Variance additivity (`Var(both varying) ≈ Var(demand-only) + Var(sim-only)`) held reasonably well under moderate demand but broke down (observed total 140-190% of the additive prediction) near and above capacity — consistent with genuinely nonlinear, threshold-triggered dynamics (gridlock) rather than a calculation error.

## Verified finding: a genuine warm-up/steady-state period may not exist at high demand

Two independent empirical warm-up-detection methods (MSER-5 and Welch's moving-average band) applied to the running-vehicle-count/mean-speed time series found a clean steady state — and a well-defined warm-up cutoff — only at an undersaturated demand level. At near-critical and oversaturated demand, both methods correctly flagged non-stationarity (persistent drift, or the truncation-point search pinned to its own search boundary) rather than forcing a spurious warm-up point. **A terminating, finite-demand simulation at high load may simply have no steady state to warm up into** — applying a fixed or naively-detected warm-up truncation there introduces bias rather than removing it.

## Verified finding: Common Random Numbers is not universally beneficial

Comparing a real treatment (a 20% signal cycle-length reduction) via both a paired (Common Random Numbers, same seed list in both arms) and an independent-seed design: CRN reduced the variance of the estimated treatment effect by 1.9-3.3x for metrics with strong paired correlation, but **increased** variance (variance-reduction factor 0.77x, i.e. CRN hurt) for a queue-length metric with weak correlation (ρ≈0.14) at low demand. At the near-critical demand level, the two designs even **disagreed in the sign** of the estimated treatment effect, while both were statistically non-significant — illustrating that near a system's capacity threshold, no single-comparison design (paired or independent) is reliable regardless of sophistication.

## Verified finding: guidance for this project's existing comparison protocol

Using minimum-detectable-difference and sign-reproduction-rate analysis (how often a single paired-seed comparison matches the sign of a well-replicated 40-run result): the project's habitual single/few-shared-seed comparison protocol was found:

- **Sound** below roughly 60% of capacity, for effects larger than a few percent — helped by the fact that a shared-seed protocol is, whether or not it was framed this way, an accidental Common Random Numbers design.
- **Marginal** in the 60-80%-of-capacity range, or for queue-type metrics specifically.
- **Unsafe** at 85%+ of capacity, where a single comparison reproduced the correct sign of a well-replicated result only about a fifth to a half of the time, depending on the metric.

This is not a blanket indictment or exoneration — it's a demand-level-dependent verdict, and any specific past comparison episode's reliability should be judged against where its own demand level sat relative to that scenario's own capacity, not assumed from this general pattern alone.

## Practical takeaways

- Measure network capacity as the *peak* of a flow-vs-demand sweep, not the flow at the heaviest demand tested — over-loading a signalized network causes served flow to collapse well below true capacity.
- Report CV (or better, the fraction of replications that gridlock) separately near a capacity knee — a mean ± CI is a poor, potentially misleading summary of a bimodal outcome distribution.
- Test whether warm-up truncation is even appropriate before applying it — a terminating high-demand simulation may have no steady state.
- Measure the actual paired correlation for a specific metric before assuming Common Random Numbers will help — it can hurt for weakly-correlated metrics.
- Treat any single-run or few-paired-seed comparison result near a system's capacity threshold as unreliable regardless of design, and prefer a demand level well below the knee when a small number of replications is all that's affordable.

See the `quantify-sumo-run-to-run-variability` skill for the full replication-design methodology and reusable batch-runner/analysis scripts.

## Feeding this into an optimizer: what the variability actually costs

This page measures the noise; a later study ([[simulation-based-optimization-under-noise-and-seed-overfitting]]) measured what happens when an
optimizer ignores it. Three results extend the findings above:

- **CRN's variance reduction is metric- and distance-dependent, and smaller than the headline
  figures here suggest.** On a signal-plan objective the factor was **1.38x** for near-optimal
  pairs (rho +0.279), 1.22x for moderately different plans, and **0.99x -- nothing -- for
  dissimilar plans** (rho -0.013), where it empirically hurt (0.69x). The "CRN is not free money"
  conclusion holds, with a new caveat: CRN helps precisely where an optimizer works (comparing
  similar candidates) but by far less than 2x.
- **Replicating during a search is a net loss at CV ~4%.** A sample-average-approximation GA
  (60 designs x 5 replications) finished worst of four arms because 5x replication bought only
  1.38x variance reduction at 5x the exploration cost. The remedy for optimization noise is
  **held-out validation after the search**, not averaging during it.
- **The single-seed protocol's danger has a second, sharper form.** This page establishes that a
  single-seed A/B comparison is unsafe above ~85% of capacity. Under *optimization* it is unsafe
  much earlier: at **77% of capacity** a 300-evaluation single-seed search produced a plan that
  beat a zero-run analytic baseline by 10.0% in-sample and lost to it by 1.8% out-of-sample.
  Selection over many candidates amplifies the same noise that a two-way comparison merely
  suffers from.
