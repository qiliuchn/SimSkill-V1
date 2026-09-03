---
summary: How to measure place-based accessibility (cumulative-opportunity and gravity) from SUMO simulation output, and the verified ways the measure misleads — free-flow skims, threshold saturation, dropped unroutable pairs, boundary truncation and MAUP — plus why aggregate benefit-cost analysis is structurally blind to who gains, and why the ecological fallacy of zone-average demographics is an order of magnitude larger than MAUP (a 1.783x travel-burden gap read as 1.006x, sign inverting on the best aggregate run).
keywords:
  - accessibility
  - equity
  - gravity-model
  - skim-matrix
  - gini-palma
  - distributional-appraisal
  - ecological-fallacy
  - value-of-time-monetisation
created: 2026-08-05T04:00:00
last_updated: 2026-08-11T18:20:00
sources:
  - "[[episodic-memory/2026-08-05_04-00-00/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-08-05_04-00-00/outputs/results_table.csv]]"
  - "[[episodic-memory/2026-08-05_04-00-00/outputs/pitfalls.csv]]"
  - https://sumo.dlr.de/docs/duarouter.html
  - https://sumo.dlr.de/docs/Simulation/Intermodal_Routing.html
  - https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[gtfs-import-and-pt-representation-semantics]]"
  - "[[transport-economic-appraisal-from-microsimulation]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[sumo-output-files]]"
  - "[[duarouter]]"
  - "[[od2trips]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[population-synthesis-and-aggregation-bias]]"
related_skills:
  - evaluate-multimodal-accessibility-and-equity
  - simulate-multimodal-transit
  - compute-dynamic-user-equilibrium
  - appraise-project-alternatives-with-benefit-cost-analysis
  - convert-od-matrix-to-trips
  - analyze-simulation-outputs
  - synthesize-population-and-generate-disaggregate-demand
related_skills_for_graph_view:
  - "[[evaluate-multimodal-accessibility-and-equity]]"
  - "[[simulate-multimodal-transit]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[appraise-project-alternatives-with-benefit-cost-analysis]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[analyze-simulation-outputs]]"
  - "[[synthesize-population-and-generate-disaggregate-demand]]"
---

# Accessibility Measurement and Transport Equity

Accessibility answers *how many opportunities a person can reach*, not *how fast
vehicles move*. Everything downstream — isochrone maps, transport-poverty screening,
distributional appraisal — rests on one object: the zone-to-zone impedance skim
`T_ij` per mode. The measures themselves are trivial arithmetic; **every real
difficulty is in the skim and in the choices that surround it**, and each of those
choices has been observed to change the *ranking of zones*, not just the level.

## The two measures

**Cumulative opportunity** `A_i(t*) = sum_j O_j * 1[T_ij <= t*]` — transparent, but
its entire content is the threshold. **Gravity** `A_i = sum_j O_j * exp(-beta T_ij)`
— smooth, but its entire content is `beta`.

`beta` should be **calibrated**, not assumed: solve by bisection for the value at
which the model's mean trip time reproduces the mean trip time actually observed in
the simulation,

```
Tbar(beta) = sum_ij W_ij(beta) T_ij / sum_ij W_ij(beta),  W_ij(beta) = P_i s_i O_j e^{-beta T_ij}
```

with `s_i` the mode-relevant population share. Model and observation must share the
same support (interzonal, finite-impedance pairs) or the fit is meaningless.

## Verified: the free-flow skim is not a conservative approximation

Measured on a 25-zone, 3 km-radius monocentric SUMO city at DUE equilibrium
(5,988 peak-hour vehicles, three seeds):

| population-weighted measure | congested skim | free-flow skim | overstatement |
| --- | --- | --- | --- |
| jobs within 5 min by car | 2,210 | 17,303 | **+683%** |
| jobs within 10 min | 23,557 | 54,177 | **+130%** |
| jobs within 15 min | 61,131 | 70,297 | +15.0% |
| gravity index (beta fixed) | 41,501 | 48,823 | +17.6% |

The **ordering** changes too: Spearman congested-vs-free-flow is 0.928 at
`t* = 10 min` and 0.786 at `t* = 15 min`, with INNER_6 moving 3rd -> 9th and
INNER_1 5th -> 2nd. And the free-flow skim **cannot be calibrated at all**: the
observed mean interzonal car trip was 654.7 s while the free-flow gravity model's
mean at `beta = 0` — its maximum — is 475.1 s, so no non-negative decay reproduces
the observed trip-length distribution.

There is a second, opposite-signed error that is easy to miss: **a free-flow skim
cannot see capacity**. Adding a lane changes a free-flow shortest path only through
whatever speed-limit change came with it. So a free-flow appraisal *overstates the
level* of accessibility while *understating the gain* from a pure capacity project.
Verified for a corridor widening: the free-flow skim predicted +2,623 jobs within
5 min against +305 realised (88% erosion), but at `t* = 15 min` and for the gravity
index the **congested** gain was the larger of the two. The sign of the erosion is
threshold-dependent; a single number for it is not a result.

## Verified: thresholds saturate, and saturation is invisible

On a compact study area the car cumulative measure runs out of information. At
`t* = 30` and `t* = 45 min` all 25 zones tied at the full 71,400 jobs and Spearman
was undefined — the conventional 15/30/45 grid produced a constant. Informative
thresholds there were 5-15 min, where the ranking is *not* robust: car
rho(10,15) = 0.906 but rho(15,20) = 0.770, and transit rho(10,15) = **0.394**.

The gravity index is markedly more rank-stable: halving or doubling the calibrated
`beta` gave Spearman 1.000 / 0.999 (car) and 0.986 / 0.964 (transit), with 4-5 of the
top 5 zones unchanged. But cumulative-at-30-min and gravity agreed only at
rho = 0.661 for transit — the two measures are not interchangeable.

Always report a **saturation flag** (`max_i A_i == min_i A_i`) beside every
cumulative number.

## Skims are not travel times until you check them

Two independent validations against raw simulation output, both of which found real
bias:

- **Car.** A `duarouter --weight-files <edgeData> --weight-attribute traveltime
  --write-costs` skim, with the skim's own route re-injected as probe vehicles into
  the simulation: mean signed error **+4.8% to +6.0%** (the skim is biased *low*),
  median |error| 4.9-5.9%, p90 10.9-15.3%, worst 27.2%, 78-83% of pairs within 10%.
  Interval-mean edge travel times cannot resolve *when within the peak* a trip
  departs, nor turn-specific junction delay.
- **Transit.** `duarouter`'s a-priori intermodal plan cost under-predicts the realised
  `<personinfo>` door-to-door duration by **28-45%**, with only 7-17% of pairs within
  10%. The plan assumes the published timetable is met; under congestion buses run
  late and riders miss connections. A transit skim must therefore be taken from
  **realised** `<personinfo>` durations, averaged over departure offsets covering one
  headway, not from the router's cost. See [[public-transport-and-intermodal-routing]].

`<personinfo>` reconciles exactly as
`duration = sum(walk) + sum(access) + sum(ride.waitingTime) + sum(ride.duration)`,
because `ride@depart` is the boarding time and `ride@duration` therefore *excludes*
the wait ([[sumo-output-files]]).

## Unroutable pairs carry the finding

`duarouter` with `modes="public"` **never reports failure** — with no usable line it
returns a walk-only plan, which then looks like a finite (if enormous) transit time.
Verified: 743 of 2,400 intermodal probes (31.0%) came back walk-only. Defining the
transit skim only over plans containing at least one `<ride>` leg exposed that **155
of 600 zone pairs (25.8%) had no transit option at all**, concentrated exactly in the
peripheral zones the study was about (one zone had 12 of its 24 destinations
unreachable). Dropping those cells instead of treating them as infinite impedance
deletes the deficit being measured.

## Where transit time actually goes

Decomposing realised door-to-door transit time by leg, for the four poor peripheral
zones versus the core and inner ring (base case):

| component | peripheral | core+inner | share of the peripheral *excess* |
| --- | --- | --- | --- |
| access walk | 1,205 s (32.3%) | 546 s (20.3%) | **+660 s (63%)** |
| initial wait | 717 s (19.2%) | 436 s (16.3%) | +281 s (27%) |
| in-vehicle | 438 s (11.7%) | 331 s (12.3%) | +107 s (10%) |
| transfer (walk+wait) | 529 s (14.2%) | 393 s (14.6%) | +136 s (13%) |
| egress walk | 838 s (22.5%) | 979 s (36.5%) | -141 s (-14%) |
| **total** | **3,728 s** | **2,685 s** | 1,043 s |

Out-of-vehicle time is **88%** of door-to-door time for every group. The common claim
that *transfer and wait* drive the peripheral deficit is only half right: in-vehicle
time is indeed almost irrelevant (10% of the excess), but the dominant term is
**access walking — i.e. stop coverage**, not headway. A frequency-only intervention
attacks the second-largest term. Halving headways *and* adding a peripheral feeder cut
the peripheral total to 2,748 s (-26%), with wait -62% and access walk -29%.

## Equity metrics and their sensitivity

Population-weighted Lorenz over zones sorted by accessibility; Gini as `1 - 2*area`;
Palma as top-10%/bottom-40% population shares of accessibility, interpolated *within*
zones at the percentile boundaries (25 zones are far too coarse to snap to zone
edges); carless gap as car-owner mean `A_car` versus carless mean `A_pt`.

Verified base: Gini 0.164 for the mode-weighted person index, but **0.072 for car
alone and 0.334 for transit alone**. Car accessibility is close to equally
distributed; transit accessibility is not. Reporting a single-mode Gini is therefore a
choice of answer. Carless accessibility was **4.12x lower** than car-owner
accessibility.

**MAUP** is real but bounded: merging 25 zones into 13 left the population-weighted
mean identical by construction while moving Gini -3.8% and Palma -2.3%. Every
scenario comparison kept its sign; no magnitude did. **Boundary truncation** is
larger and more uneven: excluding the 8 outermost zones (6.2% of jobs) cost interior
zones 4.5-7.6% of cumulative accessibility, but ranged from 5.8% to 17.9% across
zones for transit, dropping the rank correlation to 0.753 at `t* = 20 min`.

## The ecological fallacy is a much larger error than MAUP

Every metric above attaches demographics to *zones* — a zone car-ownership rate, a zone
income index — because aggregate demand carries nothing finer. MAUP perturbs such
measures by a few percent; assigning zone-average attributes to individuals distorts them
by an order of magnitude more. Measured against person-level truth from a synthetic
population on an otherwise identical run ([[population-synthesis-and-aggregation-bias]]):

| quantity | person-level truth | zone-average estimate |
|---|---|---|
| car mode share, zero-vehicle households | 0.000 | **0.328** |
| car mode share, low income | 0.216 | 0.347 |
| travel-burden ratio, 0-veh vs 2+-veh households | **1.783x** | **1.006x** |

The burden ratio computed ecologically **on the very same simulation output** compresses a
78% gap to 1%, and on a well-specified aggregate run it comes out 0.936x — the sign
inverts. The failure is not in the accessibility or equity machinery; it is that a zone
mean is being used as if it described its residents. Carless-gap and by-income figures
built this way should be read as *lower bounds on the disparity*.

Two related cautions. An aggregate model can land closer to truth **by accident** when a
network-wide bias offsets the ecological one (here it over-estimated travel time 563 s vs
490 s, partly cancelling the under-estimate) — check the sign of both errors before
crediting an agreement. And **income-weighted monetisation destroys the signal even with
person-level data**: a 2.09x minutes-equivalent generalized-cost gap became 0.99x once
converted at an income-specific value of time, because a lower-income traveller's time is
priced lower. This is the sharpest form of the blindness described in the next section —
report minutes-equivalent alongside any monetised figure.

## Why BCA is blind to distribution — the honest version

Aggregate benefit-cost analysis sums monetised time savings over travellers, so it is
invariant to *who* receives them. That is a structural property; it does not
guarantee that BCA and an equity criterion will disagree. In the verified comparison
of a road-capacity project (A) against a transit-service project (B) of comparable
budget, they **agreed** — B won on NPV (+$17.2M vs -$98.6M, and -$22.5M for A even
after equalising the budget) *and* on every equity criterion (Palma 0.456 vs 0.526,
carless gap 2.90 vs 4.46). Reporting a manufactured disagreement would be the error;
the blindness has to be demonstrated where it lives:

- **Incidence.** A delivered 66.8% of its monetised benefit to the affluent inner ring
  and made the job core *worse off* (-28.9% of the total), 2.1x more per capita to the
  affluent than to the poor periphery. B delivered 51.1% to the four low-income zones
  while the affluent ring slightly lost. **The BCA total is identical under either
  incidence pattern.**
- **Distributional weights** `w_i = (income index)^-e` move the ratio between the two
  projects' benefits from 8.9x to 13.2x at `e = 1` (A's weighted benefit -11%, B's
  +31%) — an effect the unweighted NPV cannot express.
- **Uncounted benefit.** 45 OD pairs / 113 transit trips per peak hour gained a
  transit option that did not previously exist. There is no consumer-surplus triangle
  for a service with an infinite base impedance, so their benefit enters the BCA as
  **zero**.
- **Switching value.** A only out-benefits B if transit users' time is worth less than
  **$1.80/h** — report the switching value instead of asserting robustness.

Also verified, and easy to miss: a road project can *reduce* transit accessibility.
The corridor widening redistributed car flow onto bus routes and cut population-weighted
transit accessibility from 11,163 to 10,442 jobs (-6.5%) while raising car
accessibility 2.0%, widening the carless gap from 4.12x to 4.46x. Equity effects of
road projects are not only "no benefit to the carless"; they can be negative.

## Replication

Rebuild the **whole skim** per seed, not just the simulation — a seed-averaged weight
file hides the variance. Verified spreads over 3 common-random-number seeds: mean
per-person accessibility CV 0.13-1.06%, Gini SD 0.001-0.003. Paired differences were
sign-consistent across all seeds for every claim except one (the transit project's
effect on *car* accessibility: -248 jobs, t = -0.82, sign flipped between seeds),
which was reported as noise rather than as a finding. See
[[sumo-stochastic-variability-and-replication-design]].

One replication caveat is a validity issue rather than a noise issue: the corridor
widening re-routed flow into unsignalised peripheral junctions and produced 67
teleports on one seed against 2 in the base — an artefact that, unexamined, reads as
an equity finding about the poor periphery. Check teleport *locations*
([[teleport-artifacts-and-gridlock-resolution-validity]]) and fix the network
identically in every scenario.
