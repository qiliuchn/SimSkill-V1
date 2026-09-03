---
name: measure-travel-time-reliability-with-simulated-days
description: Use this skill when the user wants to measure travel-time RELIABILITY (the distribution and tail of travel time, not just its mean) in SUMO — Travel Time Index, Planning Time Index, Buffer Index, Misery Index, on-time reliability — rather than treating run-to-run variability purely as noise to control away. Covers a Monte Carlo "simulated day" generator (day-to-day demand variation plus stochastic incidents), computing the full reliability-metrics suite at both vehicle and day level, decomposing variance into seed/demand/incident contributions via dedicated control blocks, bootstrap confidence intervals for percentile-based metrics, and comparing treatments by reliability ranking vs. mean-based ranking. Trigger on mentions of travel-time reliability, Buffer Index, Planning Time Index, Misery Index, on-time reliability, recurrent vs. non-recurrent congestion, or "does this treatment help the average trip or the worst trip."
related_skills:
  - simulate-incident-rerouting
  - sweep-rerouting-device-market-penetration
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[simulate-incident-rerouting]]"
  - "[[sweep-rerouting-device-market-penetration]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[travel-time-reliability-metrics-in-sumo]]"
---

# Measure Travel-Time Reliability with Simulated Days

Measures travel-time reliability — the distribution and tail behavior of travel time — as a first-class performance measure in SUMO, distinct from `quantify-sumo-run-to-run-variability`'s treatment of variance as nuisance noise to be controlled away via replication. This skill treats variability itself as the outcome of interest, using standard transportation-reliability metrics that were previously absent from this project.

## The simulated-day framework

Generate a population of "day draws," each specifying: (1) a day-to-day demand multiplier (e.g. lognormal, representing recurrent demand fluctuation — verify the realized distribution matches the target via a KS test, don't just assume the draw code is correct); (2) a stochastic incident event with randomized timing, location, severity, and duration (Bernoulli-triggered, implemented via `simulate-incident-rerouting`'s `closingLaneReroute` mechanics); (3) a simulation seed. Run every compared scenario (treatment) over the **identical set of day draws** — Common Random Numbers — so every comparison is paired. **Verify CRN exactness explicitly**: on days with no incident, different treatments that don't structurally differ in that scenario should produce bit-identical per-vehicle outcomes; confirm this directly rather than assuming the day-draw pipeline correctly reuses the same draws across scenarios.

## The reliability-metrics suite, and the vehicle-vs-day level distinction

Compute, from corridor travel times: free-flow reference, mean, median, 80th/95th percentile, **Travel Time Index** (mean/free-flow), **Planning Time Index** (95th percentile/free-flow), **Buffer Index** (`(95th - mean)/mean`), **Misery Index** (mean of the worst 5% of trips), and **on-time reliability** (share of trips under a threshold multiple of free-flow or median time, e.g. 1.10x and 1.25x).

**Report every metric at both the vehicle level (pooled across all days) and the day level (computed from the distribution of daily means/percentiles), and state explicitly which level each number is defined on — they are not interchangeable and can differ substantially.** Verified case: the same underlying data gave a Planning Time Index of 4.83 at the vehicle level versus 3.68 at the day level, a 31% difference, because vehicle-level pooling lets a single very-bad incident day's tail dominate the percentile calculation in a way day-level averaging smooths out.

## Bootstrap, not t-tests, for percentile-based metrics

A t-test's validity depends on approximately normal sampling distributions; percentile-based metrics (95th percentile, PTI, Buffer Index, Misery Index) generally don't have that property, especially with a moderate number of day-draws. **Use bootstrap confidence intervals** (resample days — the actual independent experimental unit — with replacement, recompute the metric, repeat many times) for any percentile-based statistic, and use paired bootstrap differences (apply the same resampled day list to every compared scenario) for CRN-paired comparisons.

## Variance decomposition: isolate seed noise from real variability

Run dedicated control blocks to decompose total travel-time variance into components: a **seed-only block** (demand pinned at its mean, incidents disabled, only the simulation seed varies — establishes the pure simulator-artifact noise floor), a **demand-only block** (demand varies, incidents disabled), and the **full block** (everything varies). The additive decomposition `Var(full) = Var(seed) + (Var(demand-only) - Var(seed)) + (Var(full) - Var(demand-only))` isolates seed, demand, and incident contributions.

**Verified, important finding: a naive seed-only control block at a single pinned demand level underestimates the true seed-noise contribution.** Because seed-driven variance itself changes with demand level (per `quantify-sumo-run-to-run-variability`'s finding that CV of a metric can peak sharply at a congestion knee), pinning demand at its *mean* value for the seed-only block can miss the higher seed variance that occurs at other, non-mean demand levels the full block actually visits. **Use a stratified seed-replicate block instead**: draw seed replications across several demand-percentile strata (not just the mean), matching the actual demand distribution the full study samples from. Verified case: the naive pinned-demand estimate understated the true seed-variance contribution by 37%.

**Verified, methodologically important finding for evaluating this project's own past practice: the common convention of estimating reliability via seed replication alone (fixing demand, re-seeding) — rather than genuine day-to-day variation — can badly misrepresent reliability.** Verified case: seed-only replication reproduced a day-level coefficient of variation that was essentially 100% simulator artifact (no real-world counterpart), captured only about 13% of the true excess Planning Time Index above free-flow, and mis-ranked which treatment was actually most reliable. **Seed replication measures simulator noise, not real-world reliability — the two are not interchangeable, and a study that only varies seed while holding demand fixed is not measuring reliability at all.**

## Distinguishing a real ranking reversal from a spurious one

When comparing treatments across a swept parameter (e.g. incident probability), a claimed "crossover" where two treatments' ranking flips should be tested for whether it's statistically real, not just visually apparent in a plotted curve. **Verified diagnostic: compute the bootstrap confidence interval on the ranking gap at the apparent crossover point, and separately check whether the estimated crossover location is stable or shrinks/shifts as sample size (number of day-draws) increases.** A crossover whose estimated location shrinks toward zero (or otherwise moves unstably) as more data is added is the classic signature of a spurious effect from limited sample size, not a genuine phenomenon — report this honestly as a debunked hypothesis rather than as a confirmed finding, even if the original motivation for testing it was compelling.

**Don't stop at debunking the originally-hypothesized effect — check the full metric suite for a genuinely different reversal.** Verified case: while the hypothesized mean-vs-PTI crossover turned out to be spurious, a real, statistically solid ranking reversal existed elsewhere in the metric suite — a strict on-time-reliability threshold (10% above free-flow) ranked two treatments oppositely from every other metric, because that specific threshold structurally penalizes any solution that reroutes traffic onto a measurably longer alternative path (the detour's own free-flow time already exceeded the threshold, so rerouted trips could never register as "on-time" regardless of how much congestion they avoided). Different reliability metrics can genuinely disagree about which treatment is better — report this as a real finding about metric choice, not noise to be averaged away.

## The Buffer Index can move opposite to both of its own components

**Verified finding (a genuine metric trap, worth checking for explicitly): the Buffer Index, being a ratio (`(p95-mean)/mean`), can worsen even while both the mean AND the 95th percentile individually improve.** This happens when a treatment reduces typical-day congestion (the mean) by more, proportionally, than it reduces the worst-day tail (the 95th percentile) — the ratio's denominator shrinks faster than its numerator, so the ratio itself rises even though both raw components fell. **Never report the Buffer Index without also reporting its two components separately** — a Buffer Index improvement/worsening in isolation can misrepresent what actually happened to both typical and worst-case travel time. If testing for this paradox specifically, use a bootstrap joint-probability test (P(mean improves AND p95 improves AND BI worsens)) rather than checking each condition separately, and report the actual confidence level achieved honestly — a joint probability just short of a conventional significance threshold (e.g. 88% rather than 95%) is a real, worth-reporting near-miss, not something to round up to "confirmed."

## Recurrent vs. non-recurrent decomposition

Split results into incident-days and no-incident-days to determine whether a treatment preferentially helps recurrent (day-to-day demand-driven) congestion or non-recurrent (incident-driven) congestion. A capacity treatment that widens the whole corridor typically helps both roughly proportionally; an incident-specific treatment (e.g. a shoulder lane that only functionally exists during a lane closure) can remove the large majority of incident-attributable variance while barely touching demand-attributable variance — verify this design intuition against the actual incident/no-incident split rather than assuming a treatment's mechanism from its description alone.

## Teleport and censoring validation for reliability studies specifically

Apply `validate-congested-scenario-results-against-teleport-artifacts`'s methodology, with extra care since reliability metrics are specifically designed to capture worst-case days — exactly the days most likely to gridlock or produce unfinished trips. **Explicitly report teleport counts and unfinished-trip counts per scenario; never silently drop unfinished trips from a percentile/tail calculation.** Beyond the teleport check, also test **analysis-horizon censoring**: if the simulation only runs a short time past the demand period (a common convention, e.g. "peak plus 20 minutes"), check whether trips that are still in progress at that cutoff are silently excluded from the metrics — verified case: a conventional shorter horizon would have silently dropped a meaningful fraction of trips and under-reported the 95th percentile substantially, with the censoring being scenario-asymmetric (worse for the scenario with more congestion) enough to understate a genuine treatment's measured tail benefit by roughly half. This is the same survivorship-censoring mechanism as the teleport artifact, entering through a different door (the analysis time window rather than the gridlock-resolution mechanism) — check both.

## Gotchas

- **Vehicle-level and day-level reliability metrics are not interchangeable** — always state which level a reported number is defined on.
- **Never use a t-test on a percentile-based metric** — use bootstrap confidence intervals, resampling the day (the true independent unit), not the vehicle.
- **A pinned-demand seed-only control block underestimates true seed-noise variance** if seed noise itself varies with demand level (which it typically does, peaking near a congestion knee) — use a stratified seed-replicate block across demand levels instead.
- **Seed replication is not a substitute for genuine day-to-day variability** — a reliability estimate built purely from re-seeding at fixed demand can be almost entirely simulator artifact and can mis-rank treatments.
- **A visually apparent crossover/reversal in a swept-parameter plot needs a bootstrap stability check across sample sizes** before being reported as real — an estimate that shrinks or moves as more data is added is the signature of a spurious effect.
- **The Buffer Index can move opposite to both its own components** — always report mean and 95th percentile alongside it, and use a joint bootstrap probability test if specifically checking for this paradox.
- **Different on-time-reliability thresholds can rank treatments in opposite directions** — a strict threshold structurally penalizes any solution involving a measurably longer alternative path, even if that path avoids far more delay.
- **Check analysis-horizon censoring, not just teleporting** — a conventional short post-peak analysis window can silently drop the worst-case trips reliability metrics exist to capture, asymmetrically across compared scenarios.

## Related

- `simulate-incident-rerouting` — the stochastic incident (closingLaneReroute) mechanics this skill's day generator uses.
- `sweep-rerouting-device-market-penetration` — the information-treatment mechanics (`--device.rerouting.probability`) used for one comparison arm in this skill's verified application.
- `quantify-sumo-run-to-run-variability` — the CV-peaks-at-the-knee finding this skill's stratified seed-noise-floor design directly builds on; that skill treats variance as noise to control away, this skill treats it as the outcome of interest.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport/survivorship-censoring validation methodology this skill applies, extended here to analysis-horizon censoring specifically.
- [[travel-time-reliability-metrics-in-sumo]] — the verified debunked-crossover/real-reversal finding, the near-miss Buffer Index paradox, the recurrent-vs-non-recurrent decomposition, and the seed-noise-over-reporting quantification.
