---
summary: A Monte Carlo simulated-day framework (lognormal demand variation plus stochastic incidents, ~300 paired day-draws under Common Random Numbers) measured travel-time reliability in SUMO as a first-class outcome — the originally-hypothesized mean-vs-Planning-Time-Index crossover was honestly debunked as statistically spurious, but a different, real ranking reversal was found (strict on-time-reliability thresholds structurally penalize rerouting solutions), a Buffer Index paradox was demonstrated in point estimates just short of full statistical confidence, and a variance decomposition found that estimating reliability via seed replication alone (rather than genuine day-to-day variation) can be nearly 100% simulator artifact and mis-rank which treatment is actually most reliable.
keywords:
  - travel-time-reliability
  - buffer-index
  - planning-time-index
  - misery-index
  - on-time-reliability
  - recurrent-non-recurrent-congestion
created: 2026-08-01T05:00:00
last_updated: 2026-08-01T05:00:00
sources:
  - "[[episodic-memory/2026-08-01_10-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_10-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[incident-rerouting-and-closures]]"
related_skills:
  - measure-travel-time-reliability-with-simulated-days
  - quantify-sumo-run-to-run-variability
  - simulate-incident-rerouting
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[measure-travel-time-reliability-with-simulated-days]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[simulate-incident-rerouting]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# Travel-Time Reliability Metrics in SUMO

Every prior comparison episode in this memory ranked traffic-treatment alternatives by a central-tendency metric (mean delay, mean travel time, throughput). This page documents the first treatment of travel-time **variability itself** as a first-class performance measure — using standard transportation-reliability metrics (Travel Time Index, Planning Time Index, Buffer Index, Misery Index, on-time reliability) computed from a Monte Carlo "simulated day" framework in SUMO, distinct from [[sumo-stochastic-variability-and-replication-design]]'s treatment of variance as nuisance noise to be controlled away via replication.

## Verified finding: a hypothesized ranking crossover, honestly debunked as spurious

The original hypothesis — that ranking two corridor treatments by mean travel time versus by Planning Time Index (95th percentile / free-flow) would flip as incident probability rose — was tested directly and found **not statistically real**: the crossover's estimated location shrank rather than stabilized as the number of simulated day-draws increased from 150 to 300, the classic signature of a spurious effect driven by limited sample size rather than a genuine phenomenon. This is reported as an honest negative result, not smoothed over.

## Verified finding: a genuinely different ranking reversal exists, driven by threshold structure

While the originally-hypothesized crossover was debunked, a real, statistically solid ranking reversal was found elsewhere in the reliability-metrics suite: a **strict on-time-reliability threshold** (share of trips within 10% of free-flow time) ranked two treatments in the *opposite* direction from every other metric tested (mean, median, 80th/95th percentile, TTI, PTI, Buffer Index, Misery Index, and even a looser 25%-threshold version of the same on-time concept). The mechanism: a rerouting-based treatment's alternative path had a free-flow travel time itself already exceeding the strict threshold, so *any* vehicle using that path could never register as "on time" under that specific metric — regardless of how much actual delay it avoided by rerouting. **On-time-reliability thresholds are not interchangeable — the specific threshold chosen can structurally favor or penalize a rerouting-based solution independent of its actual delay-reduction performance.**

## Verified finding: the Buffer Index paradox, honestly reported at its actual confidence level

The Buffer Index (`(95th percentile - mean)/mean`) was demonstrated, in point estimates, to move **opposite to both of its own components** — worsening even while both the mean and the 95th percentile individually improved — because the ratio's denominator (the mean) shrank proportionally faster than its numerator (the tail gap) under one tested treatment. This is a genuine metric trap: reporting only the Buffer Index, without its components, can make an unambiguous improvement look like a reliability regression. The joint statistical test for this paradox (P(mean improves AND 95th percentile improves AND Buffer Index worsens)) reached 88.4% confidence — **explicitly reported as falling just short of a conventional 95% significance threshold**, an honest near-miss rather than an inflated claim, with the underlying probability shown to be growing (not stable) as sample size increased, suggesting it might reach significance with more day-draws but had not yet done so in this study.

## Verified finding: seed replication alone can badly misrepresent reliability

A variance decomposition (using dedicated seed-only, demand-only, and full control blocks) found that pure simulator seed noise contributed under 1.4% of total travel-time variance in every tested scenario — day-to-day demand variation and incidents together dominate. **Critically, a naive seed-only control block pinned at a single (mean) demand level understated the true seed-noise contribution by 37%**, because seed-driven variance itself changes with demand level (peaking near a congestion knee, consistent with [[sumo-stochastic-variability-and-replication-design]]'s finding). A **stratified** seed-replicate block, sampling seed replications across the actual demand distribution rather than one fixed level, is the correct noise-floor estimator.

More importantly: **the common practice of estimating reliability via seed replication alone (fixed demand, varying only the random seed) — rather than genuine day-to-day demand and incident variation — was found to badly misrepresent reliability.** In a verified test, seed-only replication reproduced a day-level coefficient of variation that was essentially 100% simulator artifact (no real-world counterpart at all), captured only about 13% of the true excess Planning Time Index above free-flow, and mis-ranked which treatment was actually most reliable. **Seed replication measures simulator noise, not real-world travel-time reliability — a study using only seed variation to estimate reliability is not measuring the thing it claims to measure.**

## Verified finding: treatments differ in how they address recurrent vs. non-recurrent congestion

Splitting results by incident-day vs. no-incident-day found a capacity-widening treatment improved both roughly proportionally, an information/rerouting treatment was similarly proportional (removing roughly half of both incident- and demand-attributable variance), while an incident-specific treatment (a shoulder lane that only functionally adds capacity during a lane-closure incident) removed the large majority of incident-attributable variance while barely affecting demand-attributable variance — exactly as its design mechanism would predict, and confirmed directly rather than assumed.

## Verified finding: analysis-horizon censoring is a second door into the same survivorship-bias problem

Beyond the teleport-based survivorship censoring documented in [[teleport-artifacts-and-gridlock-resolution-validity]], a reliability study faces a second censoring risk: a conventional shorter analysis horizon (e.g. "peak period plus 20 minutes," rather than running until every vehicle finishes) can silently exclude still-in-progress trips from percentile/tail calculations. Verified case: such a shorter horizon would have silently dropped a meaningful fraction of trips, under-reported the 95th percentile substantially, and — because the censoring was scenario-asymmetric (worse for the more congested scenario) — understated a genuine treatment's measured tail-reliability benefit by roughly half. **Always run to full trip completion, or explicitly account for still-in-progress trips, when computing reliability tail metrics** — they exist specifically to capture worst-case outcomes, which are exactly the trips most likely to be truncated by a short analysis window.

## Practical takeaways

- Report reliability metrics at both the vehicle level (pooled) and day level (distribution of daily statistics) explicitly — they can differ substantially (verified case: 31% apart on the same underlying data).
- Never use a t-test on a percentile-based metric — use bootstrap confidence intervals, resampling days (the true independent unit).
- Use a stratified seed-only control block across demand levels, not a single pinned-demand level, to estimate the true simulator noise floor.
- Never estimate real-world reliability from seed replication alone — genuine day-to-day demand and incident variation must be modeled explicitly.
- Test any apparent metric-ranking crossover for statistical stability across sample sizes before reporting it as real.
- Never report the Buffer Index without its mean and 95th-percentile components — it can move opposite to both.
- Check analysis-horizon censoring in addition to teleport-based censoring — both are survivorship-bias risks that can specifically corrupt the tail metrics reliability studies exist to measure.

See the `measure-travel-time-reliability-with-simulated-days` skill for the full simulated-day generator, metrics-suite, and variance-decomposition methodology.
