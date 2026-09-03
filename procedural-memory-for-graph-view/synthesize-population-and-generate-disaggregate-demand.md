---
name: synthesize-population-and-generate-disaggregate-demand
description: Use this skill when SUMO demand must be built from INDIVIDUAL HOUSEHOLDS AND PERSONS rather than zone-level flows — a PUMS-style seed microdata sample fitted to zonal control totals by IPF/IPU, integerized into whole households, then given attribute-conditioned tour-based activity schedules whose mode availability is constrained by household car ownership. This is the ActivitySim/PopulationSim front end that every aggregate demand skill (od2trips, activitygen, four-step, routeSampler) structurally cannot express, and it is the ONLY way to get distributional/equity answers right — a zone-average estimate assigns car trips to carless households and can invert the sign of a travel-burden gap. Covers IPF convergence, the Truncate-Replicate-Sample trap when expansion weights fall below 1, controlled rounding, the five-check validation battery (fitted margins, held-out margin, joint preservation, negative control, across-seed stability), household vehicle-competition rules, carrying person attributes through duarouter via `<param>`, and building a genuinely matched aggregate control to measure aggregation bias. Trigger on population synthesis, synthetic population, PopulationSim/ActivitySim, PUMS or seed microdata, iterative proportional fitting, IPU, expansion weights, integerization, agent-based or disaggregate demand, household car ownership constraints, per-person or household-level travel outcomes, transport equity by income or vehicle ownership, ecological fallacy, or aggregation bias.
related_skills:
  - build-four-step-model-with-feedback-loop
  - generate-activity-based-demand
  - evaluate-multimodal-accessibility-and-equity
  - convert-od-matrix-to-trips
  - simulate-multimodal-transit
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[build-four-step-model-with-feedback-loop]]"
  - "[[generate-activity-based-demand]]"
  - "[[evaluate-multimodal-accessibility-and-equity]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[simulate-multimodal-transit]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[population-synthesis-and-aggregation-bias]]"
  - "[[accessibility-measurement-and-transport-equity]]"
  - "[[geh-statistic]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[four-step-model-feedback-loop-convergence]]"
---

# Synthesize a Population and Generate Disaggregate Demand

Builds SUMO demand from the bottom up — seed microdata + zonal controls → IPF → whole
households → activity tours → `<person>`/`<trip>` demand — and, critically, measures it
against a **matched aggregate control** so you can say what the households actually
bought you.

Every other demand skill in memory works with aggregates: `convert-od-matrix-to-trips`
(zone flows), `generate-activity-based-demand` (activitygen's scalar `inhabitants` /
`carRate`), `build-four-step-model-with-feedback-loop` (productions/attractions),
`calibrate-demand-with-routesampler` (counts). None of them can represent a *household*,
so none can answer "who bears this delay?" except by zone averaging — which is the
ecological fallacy, and it is measurably wrong (see below).

Note the two different uses of IPF. Here it reweights a *microdata sample* to univariate
zone margins. In `build-four-step-model-with-feedback-loop` the same algorithm (Furness)
balances a *2-D OD matrix* to row/column totals. Same loop, different object; both should
converge on **achieved margin error**, not on multiplier change — see
[[four-step-model-feedback-loop-convergence]].

## Pipeline

```
step 1  netgenerate + netconvert sidewalks --------> net.net.xml     create-grid-network
step 2  TAZ + land-use edge roles -----------------> taz.add.xml     convert-od-matrix-to-trips
step 3  bus lines with absolute until= ------------> pt.rou.xml      simulate-multimodal-transit
step 4  seed microdata + zonal marginals ----------> seed[], ctrl[]  (author or import)
step 5  popsynth.ipf_weights ----------------------> w[] fractional
step 6  popsynth.milp_integerize ------------------> whole households
step 7  VALIDATION BATTERY (A1-A5) ----------------> accept / reject   <-- do not skip
step 8  activity tours + vehicle competition ------> person/trip demand
step 9  aggregate own demand to OD, od2trips ------> MATCHED control   convert-od-matrix-to-trips
step 10 duarouter + sumo, N CRN seeds x arms ------> outputs         quantify-sumo-run-to-run-variability
step 11 segment outcomes by household attribute ---> the actual answer
```

## Scripts

`scripts/popsynth.py` — the reusable synthesizer, deliberately generic (seed sample is a
list of dicts; you supply a category-index array per control):

- `ipf_weights(cat_index, targets, controls, n_total)` → `(w, history)`, where `history`
  is the max **relative margin error** per iteration, so callers can assert on
  convergence rather than assume it.
- `milp_integerize(w, ...)` — **controlled rounding**; the one to use. Each household is
  bounded to `floor(w)` or `floor(w)+1` and the up/down choices are constrained so every
  fitted category hits its total exactly. `jitter` perturbs the objective so different
  seeds pick different equally-good roundings, which is what makes the across-seed
  stability check (A5) meaningful.
- `trs_integerize(w, rng)` — Truncate-Replicate-Sample, provided mainly as the
  documented-bad baseline (see the trap below).
- `fit_metrics(observed, target)` → TAE / SAE / SRMSE / chi2; `cramers_v(table)` and
  `table_srmse()` for the joint-preservation checks.

A complete worked implementation — network, transit, input authoring, synthesis,
activity converter, three aggregate controls, 20 replications, comparison and plots — is
in `episodic-memory/2026-08-11_16-40-44/attempts/attempt-1/scripts/`.

## TRS silently destroys the IPF fit when weights fall below 1

This is the trap that costs the most time, because nothing errors — you just get a
population that no longer matches its controls.

Truncate-Replicate-Sample floors each weight, replicates, then draws the residual by
fractional part. When most expansion weights are **near or below 1**, the floor step
yields zero for nearly everyone and TRS degenerates into plain multinomial sampling —
re-injecting exactly the sampling noise IPF had just removed. Verified: identical IPF
weights integerized by TRS gave max SAE **0.1206** / SRMSE 0.1663 on the *fitted*
margins, versus **0.0000 / 0.0000** for controlled rounding.

The weight regime is set by `n_zone_households / n_seed_households`. With 250 seed
households and 2550 zone households the mean weight is ~1.1 — right in the danger zone.
Either use controlled rounding (preferred), or size the seed so weights are comfortably
above ~5.

Do **not** reach for a general L1 MILP instead. An unrestricted `min sum|n_h - w_h|`
meets the margins exactly but is massively degenerate: it is free to pile population onto
whichever seed rows satisfy the constraints cheapest. Measured, it made both the held-out
margin (SRMSE 0.398 vs TRS's 0.307) and the joint structure (Z11 r = 0.362 against a true
0.649) *worse* than the bad baseline it was meant to replace. Bounding each household to
its own two neighbouring integers is what fixes it.

## The validation battery — five checks, and one of them is a trap

Run all five *before* generating any demand. A synthesizer that hits its margins can
still have destroyed the joint structure that is the entire reason for synthesizing.

| check | what it tests | usable threshold |
|---|---|---|
| **A1** fitted margins | did the fit + integerization hold? | SAE ≤ 0.02, SRMSE ≤ 0.05 |
| **A2** held-out margin | does it generalize past what it was fitted to? | SRMSE ≤ 0.25 |
| **A3** joint income x vehicles | is the correlation the seed carried preserved? | compare to noise floor, not a fixed bar |
| **A4/A5** across-seed stability | how much population varies seed to seed | CV ≤ 0.10 controls / ≤ 0.25 free cells |
| **NC** negative control | independent marginal sampling, must fail | should lose the joint entirely |

Three things this battery taught:

**A3 needs a noise floor, not a fixed threshold.** A flat `|Δr| ≤ 0.05` bar failed in the
CBD zone (measured 0.0478 / 0.0582) — but that bar is *tighter than the sampling error of
the reference it is compared against*: bootstrapping the per-zone ground-truth joint gave
2 SE = 0.104–0.111. The fixed threshold was measuring finite-population noise, not
synthesizer error. Report both; make the noise-floor version the operative criterion.
This is the same discipline `quantify-sumo-run-to-run-variability` applies to simulation
metrics, transplanted to the synthesizer.

**A check can pass by construction and tell you nothing.** A4 measured the CV of the
zero-vehicle household count across seeds — but controlled rounding forces fitted control
totals to be exact, so its CV is identically 0. It passes trivially. The informative
stability test is on the **unconstrained** joint cells (A5), and even there restrict to
cells with ≥5 households or you are just measuring small-count noise (0.2484 vs 0.0684).

**Always run the negative control.** A population drawn by sampling each marginal
independently reproduces the margins about as well as IPF does, so without it you have no
evidence IPF did anything. It fails exactly where it should: region-wide
r(income, vehicles) **0.160 against a true 0.643** (IPF: 0.636), per-zone joint SRMSE
0.518–0.757 (IPF: 0.033–0.190), and the held-out margin 0.372 (IPF: 0.172).

## Household vehicle competition, and getting attributes through duarouter

A zero-vehicle household must produce **no** car leg — that constraint is the whole point,
and it is worth verifying on the output rather than trusting the generator.

A documented allocation rule that works: sort the household's adults by (worker first,
then earlier provisional departure), give the first `min(vehicles, n_adults)` of them
car-holder status, and let a car-holder drive with probability `P_DRIVE`. Students never
hold a car. Simple, defensible, and it produces the right monotone gradient — measured car
share by household vehicles 0 → **0.000**, 1 → 0.371, 2+ → 0.577.

Verify with two assertions on the leg table: zero-vehicle car legs == 0, and no household
ever fields more distinct drivers than it owns vehicles.

Carry `hh_id`, `income`, `hh_vehicles` as `<param>` children of each `<trip>`/`<person>`.
duarouter preserves them, which is what makes person-level segmentation possible after
the run — confirm the count survives routing (5190 vehicle trips and 4231 person plans
did here).

**duarouter emits one `<vehicle>` per car leg.** A `<person>` with two
`<personTrip modes="car public">` legs produces two `<vehicle>` elements sharing an id
plus a duplicated `<vType>`, which SUMO then rejects. Either emit car tours as plain
`<trip>` vehicles (what the worked example does — it also makes the arms symmetric with
od2trips), or give each car leg a distinct id. Relatedly, pass a shared `vtypes.add.xml`
to **duarouter only**: duarouter echoes vType definitions into the routed file, so also
passing it to `sumo` double-defines the type.

## Building an aggregate control that is not a strawman

If you are measuring aggregation bias, almost all the work is in making the aggregate arm
*good*. Three fixes turned a strawman into a real control, and the third reversed the
study's conclusion:

1. **Predict mode share from something the aggregate model actually has.** "Share of
   households with ≥1 vehicle" gave the aggregate arm a 65.2% car share against the
   disaggregate arm's 36.4%. Vehicles *per capita*, still computable from univariate
   marginals alone, plus one regional constant calibrated to the observed total, is what
   mode-choice calibration does in practice.
2. **Apply mode split at the production (home) end.** Indexing by trip *origin* puts the
   return-home leg's mode choice at the workplace zone — measured corr(aggregate, truth)
   = **−0.28** across zones. Segment OD cells by production zone.
3. **Segment by period and purpose before blaming the households.** A naive single-constant
   control over-loaded the AM peak by **+44%**, which looks like proof that disaggregate
   demand matters. Adding period-segmented (`agg2`) and period+purpose-segmented (`agg3`)
   controls showed the whole gap was a mode-choice *specification* artefact: agg3 hits
   AM-peak car trips exactly (870 vs 870) and reaches GEH<5 on **100%** of links.

Hold constant across arms what you are not testing: same network, same transit file, same
vType file, same seeds, and the **same total trip count** (14 075 in all four arms here).

## What the synthetic population actually buys — and what it doesn't

Measured on a 6x6 grid, 9 zones, 2550 households / 6537 persons, 4 arms x 5 CRN seeds:

**Network loading: no.** Against the best aggregate control, link volumes match at GEH<5
on 100% of links (r = 0.93 AM peak, 0.98 full day) and mean network speed differs by 0.2%
(p = 0.19, n.s.). A ~4–5% residual on VMT/VHT/delay survives, but it traces to *within-zone
spatial resolution* — the aggregate arm draws origins uniformly across a zone's edges,
making trips ~4% longer. That is a TAZ-granularity (MAUP) problem; finer zones would fix
it, households are not required.

**Distributional incidence: categorically yes.** No aggregate re-specification helps,
because all aggregate arms have identically zero household information:

- zone-average estimation assigns a **32.8% car share to households owning no car** (813
  car trips/day that cannot exist), and understates the 2+-vehicle group by 18 points;
- the zero-vehicle travel-burden ratio is **1.783x** in person-level truth, **1.006x**
  computed ecologically on the *same* disaggregate run's zone means, and **0.936x** on the
  best aggregate run — **the sign inverts**;
- an aggregate arm that happens to land closer to truth can do so by accident: it
  over-estimates travel time network-wide (563 s vs 490 s), partly cancelling its
  ecological under-estimate. Two errors offsetting, not a better method.

**And you can still throw it away in the last step.** In minutes-equivalent generalized
cost the zero-vehicle segment bears **2.09x** the burden of the 2+-vehicle segment
(22.24 vs 10.62). Monetised at an income-specific value of time the same costs are
**3.670 vs 3.699 EUR — 0.99x**. Income-weighted monetisation erases the entire
distributional signal even when person-level data is available. Report
minutes-equivalent alongside any monetised figure.

## Gotchas

- **`hash()` is salted per process.** Seeding an RNG with `hash(zone_name)` makes the
  synthesis silently non-reproducible across runs. Use a stable index
  (`ZONES.index(z)`) — this cost a full pipeline re-run to catch.
- **GEH is a weak test at low link volumes.** At ~40 veh/h per link the GEH<5 band is
  enormous: the `agg2` arm passed the conventional 85%-of-locations criterion (88.3%)
  while correlating with the truth at only **r = 0.23**. Report r and RMSE alongside GEH
  — see [[geh-statistic]].
- **A transit line is only usable by the intermodal router if its stops carry absolute
  `until=` times.** A clean exit proves nothing; check a nonzero ride count in the SUMO
  log (`Ride Statistics (avg of N rides) ... Bus: N`). See
  [[public-transport-and-intermodal-routing]].
- **Paired t-tests on deterministic metrics return `p = 0.0` degenerately** (identical
  values across seeds → zero variance → `t = inf`). Metrics fixed by the demand file, not
  the simulation — trip counts, peak-hour share — will do this. Don't report them as
  significant.
- **Raw SUMO output is large.** 20 runs of per-timestep `summary.xml` was 360 MB. Gzip
  outputs and read them transparently.

## Related

- [[population-synthesis-and-aggregation-bias]] — the knowledge page behind this skill
- `build-four-step-model-with-feedback-loop` — the aggregate counterpart; its
  `furness()`/IPF convergence discipline is what `ipf_weights()` follows
- `generate-activity-based-demand` — activitygen; the aggregate way to get a commute peak
- `evaluate-multimodal-accessibility-and-equity` — equity metrics; note it models
  demographics as *zone* attributes, which is exactly the ecological estimator this skill
  measures the error of
- `convert-od-matrix-to-trips`, `simulate-multimodal-transit`,
  `quantify-sumo-run-to-run-variability` — used for the control arm, transit supply, and
  replication protocol
- [[accessibility-measurement-and-transport-equity]], [[geh-statistic]],
  [[public-transport-and-intermodal-routing]], [[four-step-model-feedback-loop-convergence]]
