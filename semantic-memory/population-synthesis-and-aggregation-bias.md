---
summary: Population synthesis (IPF + integerization) fitted to zonal controls, and a controlled measurement of what disaggregate demand actually changes in SUMO — network loading is reproduced by a properly segmented aggregate model (GEH<5 on 100% of links, residual 4-5% traceable to zone granularity), while distributional incidence categorically requires households: a zone-average estimator assigns a 32.8% car share to carless households and inverts the sign of the travel-burden gap.
keywords:
  - population-synthesis
  - iterative-proportional-fitting
  - IPF
  - IPU
  - integerization
  - controlled-rounding
  - truncate-replicate-sample
  - seed-microdata
  - PUMS
  - disaggregate-demand
  - agent-based-demand
  - aggregation-bias
  - ecological-fallacy
  - MAUP
  - transport-equity
created: 2026-08-11T18:20:00
last_updated: 2026-08-11T18:20:00
sources:
  - "[[episodic-memory/2026-08-11_16-40-44/summary.md]]"
related_pages:
  - "[[four-step-model-feedback-loop-convergence]]"
  - "[[accessibility-measurement-and-transport-equity]]"
  - "[[geh-statistic]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[activitygen]]"
  - "[[od2trips]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - synthesize-population-and-generate-disaggregate-demand
  - build-four-step-model-with-feedback-loop
  - generate-activity-based-demand
  - evaluate-multimodal-accessibility-and-equity
  - convert-od-matrix-to-trips
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[synthesize-population-and-generate-disaggregate-demand]]"
  - "[[build-four-step-model-with-feedback-loop]]"
  - "[[generate-activity-based-demand]]"
  - "[[evaluate-multimodal-accessibility-and-equity]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Population Synthesis and Aggregation Bias

Population synthesis builds a list of individual households and persons that is
statistically consistent with published zonal control totals, by reweighting a small
seed sample of real microdata (PUMS-style) rather than sampling attributes
independently. It is the front end of ActivitySim/PopulationSim/MATSim, and the thing
that makes travel demand *agent-based* rather than flow-based.

The question it raises — does representing households change the answer, or is it
expensive bookkeeping? — has a two-part answer, and both parts were measured on a
controlled SUMO experiment (9-zone 6x6 grid, 2550 households / 6537 persons, 4 arms x 5
Common-Random-Number seeds, 14 075 legs held identical across arms).

## The method

Two inputs: a **seed sample** carrying the *joint* distribution of attributes (household
size, income, vehicles, workers) but not the right totals, and **zonal marginals** giving
the right univariate totals per zone but no joint structure. IPF reweights the seed so
its weighted margins match each zone's controls, preserving the seed's joint structure as
far as the margins allow. Fractional weights are then **integerized** into whole
households, because half a household cannot travel.

This is the same algorithm as the Furness balancing in
[[four-step-model-feedback-loop-convergence]], applied to a different object — a
microdata sample rather than a 2-D OD matrix — and it should converge on the same
criterion, the achieved margin error rather than the change in multipliers.

## Integerization is where synthesizers quietly break

**Truncate-Replicate-Sample degenerates into multinomial sampling when expansion weights
fall below 1.** TRS floors each weight, replicates, then draws the residual by fractional
part; when most weights are under 1 the floor step yields zero for nearly everyone and
the whole population is drawn by sampling — re-injecting exactly the noise IPF had just
removed. Measured on identical IPF weights: TRS gave max SAE **0.1206** / SRMSE 0.1663 on
the *fitted* margins against **0.0000 / 0.0000** for controlled rounding. Nothing errors;
the fit is simply gone. The weight regime is `n_zone_households / n_seed_households`, so
a 250-household seed against 2550 zone households (mean weight ~1.1) sits squarely in the
danger zone.

**Controlled rounding is the fix; a general L1 MILP is not.** Bounding each household to
`floor(w)` or `floor(w)+1`, with the up/down choices constrained so every fitted category
hits its total exactly, meets the margins exactly and preserves the joint. An
*unrestricted* `min sum|n_h - w_h|` program also meets the margins but is massively
degenerate — free to pile population onto whichever seed rows satisfy the constraints
cheapest — and measurably made both the held-out margin (SRMSE 0.398 vs TRS's 0.307) and
the joint structure (CBD zone r = 0.362 against a true 0.649) *worse* than the bad
baseline it replaced.

## Validating a synthesizer

Matching the margins proves almost nothing — it is what the fit was told to do. Five
checks, of which two carry most of the information:

- **Fitted margins** (SAE/SRMSE ≈ 0): necessary, not sufficient.
- **A held-out marginal** never shown to the fit: tests generalization. IPF 0.172 vs the
  negative control's 0.372.
- **Joint preservation** — does the synthesized population still carry the seed's income x
  vehicle-ownership correlation? This is the entire reason for synthesizing.
- **A negative control**, drawn by sampling each marginal independently: it reproduces the
  margins about as well as IPF, so without it there is no evidence IPF did anything. It
  fails where it must — region-wide r(income, vehicles) **0.160 against a true 0.643**
  (IPF 0.636), per-zone joint SRMSE 0.518–0.757 (IPF 0.033–0.190).
- **Across-seed stability**, which is only informative on the *unconstrained* cells.

Two traps in the battery itself. A fixed joint-preservation threshold (`|Δr| ≤ 0.05`)
turned out to be **tighter than the sampling error of the reference it is compared
against** — bootstrapping the per-zone ground-truth joint gave 2 SE = 0.104–0.111, so the
threshold was measuring finite-population noise, not synthesizer error; the noise-floor
comparison must be the operative criterion, the same discipline
[[sumo-stochastic-variability-and-replication-design]] applies to simulation metrics. And
a stability check on a *fitted control* passes identically by construction, since
controlled rounding forces those totals to be exact — its CV is 0 and it carries no
information at all.

## What disaggregate demand changes: network loading, no

Against a matched aggregate control (identical network, transit, seeds, and total trip
count), a trip-based four-step model with **period- and purpose-segmented mode choice**
reproduces the disaggregate model's link volumes at GEH<5 on **100%** of links, r = 0.932
(AM peak) / 0.975 (full day), with AM-peak car trips exactly equal (870 vs 870) and mean
network speed differing 0.2% (p = 0.19, not significant).

A ~4–5% residual on VMT/VHT/delay does survive (all p<0.0001 against a seed-to-seed noise
floor of GEH 0.011), but it traces to **within-zone spatial resolution**: the aggregate arm
draws origins and destinations uniformly across a zone's edges, making trips ~4% longer.
That is a TAZ-granularity/MAUP problem — finer zones fix it, households are not required.
Activity-chaining also spreads the PM peak slightly (sd 1.310 h vs 1.349–1.352 h), an
effect the aggregate model structurally cannot produce, worth about 3%.

**The corollary matters more than the null.** A *naive* aggregate control — one regional
mode-split constant — over-loaded the AM peak by **+44%** and passed GEH<5 on only 77.5%
of links. That looks like proof that disaggregate demand matters, and it is not: adding
period segmentation and then purpose segmentation closed the entire gap. An aggregation-bias
study that runs only one aggregate arm will attribute a mode-choice *specification* error
to the absence of households. Getting the mode-split predictor right matters similarly —
it must be computable from the marginals alone (vehicles per capita, not "share of
households with a vehicle", which produced a 65.2% vs 36.4% car-share strawman) and
applied at the **production end**, since indexing by trip origin puts the return-home
leg's mode choice at the workplace zone (measured corr with truth −0.28 across zones).

## What disaggregate demand changes: distributional incidence, categorically yes

No aggregate re-specification helps here, because every aggregate arm has identically zero
household information. The zone-average ("ecological") estimator — the one
[[accessibility-measurement-and-transport-equity]] and most equity appraisal actually use
— fails in three distinct ways:

| quantity | person-level truth | zone-average estimate |
|---|---|---|
| car share, zero-vehicle households | **0.000** | **0.328** (813 impossible car trips/day) |
| car share, 2+-vehicle households | 0.577 | 0.393 |
| car share, low income | 0.216 | 0.347 |
| travel-burden ratio, 0-veh vs 2+-veh | **1.783x** | **1.006x** (0.936x on the best aggregate arm — *sign inverts*) |

A 78% burden gap is compressed to 1%, and the best-specified aggregate model reports it
backwards. Note also that an aggregate arm can land closer to truth **by accident**: it
over-estimates travel time network-wide (563 s vs 490 s), which partly cancels its
ecological under-estimate — two errors offsetting, not a better method.

The underlying travel differences are real and large: mean per-leg travel time 669.2 s in
zero-vehicle households against 375.4 s in 2+-vehicle households, with walk+wait time
620.4 s against 246.5 s.

## Monetisation can erase the signal you paid for

In minutes-equivalent generalized cost the zero-vehicle segment bears **2.09x** the burden
of the 2+-vehicle segment (22.24 vs 10.62). Monetised at an income-specific value of time,
the same costs become **3.670 vs 3.699 EUR — a ratio of 0.99x**. Because a lower-income
traveller's time is priced lower, income-weighted monetisation converts a large
distributional gap into no gap at all, *even when the person-level data is available*.
Report minutes-equivalent alongside any monetised figure; this is a sharper version of the
structural blindness [[accessibility-measurement-and-transport-equity]] describes in
benefit-cost analysis.

## Practical notes

- **GEH is a weak test at low link volumes.** At ~40 veh/h per link the GEH<5 band is
  enormous: one aggregate arm passed the conventional 85%-of-locations criterion (88.3%)
  while correlating with truth at only r = 0.23. Report r and RMSE alongside GEH — see
  [[geh-statistic]].
- **duarouter emits one `<vehicle>` per car leg**, so a `<person>` with two
  `personTrip modes="car public"` legs produces duplicate vehicle ids and a duplicated
  `vType`, which SUMO rejects. Emitting car tours as plain `<trip>` vehicles avoids it and
  keeps the arms symmetric with od2trips output.
- Person attributes carried as `<param>` survive duarouter, which is what makes
  post-run segmentation by household possible.
- A transit line is usable by the intermodal router only if its stops carry absolute
  `until=` times — verify via a nonzero ride count, not a clean exit
  ([[public-transport-and-intermodal-routing]]).
- `hash()` is salted per process in Python; seeding an RNG with `hash(zone_name)` makes a
  synthesis silently non-reproducible across runs.

## Bottom line

Synthesize a population when the question is **who**. Do not synthesize one to get link
volumes right — segment the mode-choice step and refine the zones instead. And whichever
you do, run more than one aggregate control, or you will misattribute your own
specification errors to the modeling paradigm.
