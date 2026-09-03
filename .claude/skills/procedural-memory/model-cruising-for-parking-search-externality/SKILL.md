---
name: model-cruising-for-parking-search-externality
description: Use this skill when the user wants to model parking as a SOURCE of traffic congestion in SUMO — cruising for parking, the search-time cost of finding a space, its delay externality on other traffic, and whether price, added supply, or driver information is the effective remedy — rather than parking as a routing mechanism (see model-parking-with-rerouting for the base parkingArea/rerouter mechanics this skill extends). Covers building a mixed curb/garage downtown parking supply, phase-decomposing a parker's trip into approach/search/parked/walk with VMT/VHT attribution, fitting the search-time-vs-occupancy divergence curve, measuring the search externality via a controlled-removal experiment, testing whether driver information can backfire near saturation, comparing curb pricing against added supply on door-to-door generalized cost and equity, and isolating the parking maneuver's own lane-blocking cost from the search cost. Trigger on mentions of cruising for parking, parking search externality, curb pricing, parking occupancy and congestion, or "how much traffic does parking cause."
---

# Model Cruising for Parking and Its Search Externality

Treats parking not as a routing destination (that's `model-parking-with-rerouting`'s scope — the
`parkingArea`/`rerouter` mechanism with full occupancy visibility) but as a **traffic-generating
process**: the search phase before a driver finds a space, the delay it imposes on other traffic,
and the door-to-door cost tradeoff between price, supply, and information as remedies. Builds a
downtown grid with mixed curb (on-street) and garage (off-street) parking supply, endogenous
person walk legs from the parked location, and value-of-time-driven driver behavior.

## Building the scenario

Base network: any grid/downtown-style network (`create-grid-network`) with sidewalks
(`--sidewalks.guess --crossings.guess --walkingareas`, see `simulate-multimodal-transit` for the
pedestrian-network mechanics). **`--crossings.guess.speed-threshold` defaults to 13.89 m/s and the
comparison is strict** — a network built at exactly that speed silently produces zero crossings;
set the arm's speed limit clearly above or below the threshold, or pass an explicit
`--crossings.guess.speed-threshold`, and verify crossing count is nonzero before proceeding.

**Curb supply**: many small `parkingArea` elements on block-face lanes (`roadsideCapacity` ~4-8
each), matching the granularity of real on-street parking rather than one large lot per street.
**Garage supply**: `roadsideCapacity` is bounded by the host lane's length — for a large
off-street lot, use explicit `<space x="..." y="..."/>` children instead, which decouples capacity
from any lane-length constraint.

Demand needs three classes sharing the network: PARKERS (drive to a search zone, park, then the
driver — spawned as a TraCI person — walks to a final destination and dwells before returning),
THROUGH traffic (measured separately throughout, never confounded with parker delay), and
optionally a warm-start turnover stock (already-parked vehicles departing) so occupancy reaches
steady state without a long empty-network ramp-up. Give parkers an explicit lognormal
value-of-time and a walking speed so door-to-door generalized cost
(`in-vehicle time * VOT + walk time * VOT_walk + fee`) is computable per driver, not just in
aggregate.

**Spawn the walking person at the lot the vehicle ACTUALLY reached, not the one its route
originally named.** A rerouted or self-selecting vehicle can end up in a different lot than its
initial assignment; walk time must be measured from the real parking location.

**Critical calibration gotcha: sweep demand against CURB capacity, not total (curb + garage)
capacity.** Normalizing demand against total supply produces a degenerate sweep where curb
occupancy pins near saturation at every demand level while total occupancy never rises much —
because garages absorb the marginal demand and curb never clears. The parking-search phenomenon
this skill studies lives specifically in curb occupancy; calibrate and report against it directly.

## Phase decomposition

Reconstruct each parker's trip into APPROACH (origin to search-zone entry) / SEARCH (search-zone
entry until the parking maneuver begins) / PARKED (dwell) / WALK (parkingArea to final
destination and back), with VMT and VHT attributed to each phase. A per-step TraCI subscription
(`VAR_ROAD_ID`, `VAR_SPEED`, `VAR_STOPSTATE`) is a viable substitute for full FCD if FCD's volume
(tens of GB across a large multi-seed campaign) is prohibitive — reconcile it against summed
`parkingArea` occupancy as an internal-consistency check (see Validity below) rather than assuming
correctness.

**A teleporting vehicle's subscribed `VAR_SPEED` returns `INVALID_DOUBLE_VALUE` (-2^30), not
0.** This silently corrupts any per-step speed accumulation (VMT, VHT) by roughly 1e9 per
affected step — a single teleported vehicle can inflate an aggregate by hundreds of millions of
vehicle-seconds and turn a modest externality ratio into a nonsensical one. **Clamp or filter
`VAR_SPEED` before any accumulation that uses it**, and verify the fix is applied at every call
site that reads the field, not just the one where the corruption was first noticed (a single
shared clamp point, e.g. one function all speed reads pass through, is safer than patching each
usage separately).

## The search-time-vs-occupancy divergence (H1-style analysis)

Fit both a linear model and a divergent form `a/(1-rho) + b` (and optionally a free exponent
`a/(1-rho)^gamma + b`) to mean search time against curb occupancy `rho`, comparing R² and AIC. In
a verified study, the divergent form fit dramatically better than linear (R² 0.877 vs 0.516,
ΔAIC ≈ 88), and a free-exponent fit found the divergence **steeper than the classical 1/(1-rho)**
(gamma ≈ 1.59, 95% CI excluding 1) — don't assume the canonical exponent of 1 without fitting it.
Locate the empirical "knee" (e.g. via a doubling criterion: the occupancy at which search time
first reaches 2x its low-occupancy baseline) and test it against the commonly-cited 85%-occupancy
rule of thumb rather than assuming the rule transfers — in one verified network the knee landed
almost exactly at 0.835-0.86, but this depends on block size, lot granularity, and turnover rate,
which should be stated as untested moderators unless actually swept. **Watch for a knee-detection
method that is analytically degenerate for a given functional form** (e.g. a fixed-slope
criterion that never triggers for a convex-then-flat curve) — check the criterion actually fires
before reporting a knee value from it.

Also compute cruising's share of total network VMT/VHT across the occupancy sweep, and compare
against the commonly-cited "~30% of downtown traffic is cruising for parking" claim as a
falsifiable target rather than an assumption — in a verified study this figure was only
reproduced near curb saturation (mid-30s % of VMT), with cruising's VMT share below 10% at
moderate occupancy.

## Measuring the search externality (H2-style controlled removal)

To isolate cruisers' delay effect on OTHER traffic, don't just correlate search-time with
congestion — run a controlled-removal counterfactual: replace a CRN-matched cohort of parkers with
equivalent through trips of identical origin/departure time (preserving the approach phase, only
removing the search behavior), and compute the change in delay experienced by everyone else versus
the removed cohort's own foregone search delay. Report the **external:private delay ratio**
(`Δ others' delay / cohort's own search delay`) across the occupancy sweep — this ratio need not be
constant, and in a verified study it crossed from below 1 (search delay privately exceeds its
externality) to above 3 (externality more than triples the private cost) at a specific occupancy
threshold, not gradually — report the threshold explicitly rather than only a single pooled ratio.

## Testing whether driver information can backfire (H3-style)

Sweep information penetration from none to full via `parkingAreaReroute`'s `visible` attribute
and/or a custom TraCI guidance controller (SUMO's `parkingAreaReroute` element has only
`id`/`probability`/`visible` — **per-driver partial information penetration cannot be expressed
natively** and must be built via TraCI dispatch logic). A naive "route every informed driver to
the nearest reported-free lot" controller can show a real benefit at moderate penetration and a
measurable **inversion (net harm) near full penetration**, because informed drivers herd toward
the same reported-free lot — this is the same congestible-good mechanism documented in
[[information-penetration-and-congestible-routing]], transferable to the parking domain. To
distinguish a genuine information-processing failure from a coordination failure, add a
reservation-aware guidance variant (never dispatching two drivers to the same space) as a separate
experimental arm — if reservation-aware guidance restores the benefit at full penetration where
naive guidance inverted, the failure is coordination (multiple drivers converging on one space),
not information itself. This distinction changes the policy prescription (build a
reservation/booking layer, not just publish occupancy data).

## Price vs. supply vs. information (H4-style)

Implement a feedback-based performance-pricing controller (an ALINEA-style loop, reusing the
pattern from `model-cordon-tolling-with-generalized-cost-surcharge`/
`model-managed-lanes-with-dynamic-tolling-and-self-selection`) that adjusts curb fee to hold curb
occupancy near a target, with parkers self-selecting curb vs. garage vs. balk by comparing
fee + expected search time*VOT + walk time*VOT. **The controller can fail to reach its target when
curb supply is abundant relative to fixed total demand** — it floors at fee=0 and simply cannot
push demand up further; verify the achieved occupancy actually matches the intended target in
every arm of a multi-arm comparison (don't assume a stated target was reached), since two arms
that are supposed to be occupancy-matched but aren't will confound any comparison between them
(see the Gotchas section below).

Compare pricing, an equal-cost-labelled supply increment, and driver-information policies on
door-to-door generalized cost, explicitly noting whether the supply comparison is genuinely
cost-equalized (a free-to-traveller added-space arm is an *effect* comparison, not a
benefit-cost comparison, unless a capital-cost model is included) and reporting outcomes
**by value-of-time quartile** so a regressive result is visible rather than hidden in an aggregate
mean — in a verified study, curb pricing reduced cruising VMT and through-traffic delay at zero
capital cost, but door-to-door generalized cost was statistically unchanged (time saved was offset
by the fee and a longer walk to a cheaper alternative) and the burden was regressive (low-VOT
travelers made measurably worse off, high-VOT travelers slightly better off, with low-VOT drivers
disproportionately displaced to the garage) — while a supply increment beat every pricing arm on
generalized cost. Neither of these directions should be assumed; test both explicitly.

## The parking maneuver as a separate lane-blocking externality (H5-style)

Search delay and the delay from the parking **maneuver** itself (the vehicle physically pulling
into/out of a curb space, briefly at near-zero speed in the travel lane) are distinct mechanisms
that a model treating parking as instantaneous will miss entirely. Toggle `--parking.maneuver`
on/off (paired within seed) to isolate its contribution, and verify the lane-blocking mechanism
directly — not just infer it from aggregate delay — using the same standing-vehicle-seconds
instrument `model-curbside-delivery-and-lane-blocking-externality` establishes for
`<stop parking="false"/>`: sum time spent below a near-zero speed threshold, on the relevant lane,
by vehicles that are *not yet counted as parked*. In a verified study the maneuver added a
substantial fraction (order 20-50%) of total network delay, comparable in size to the search delay
the analysis already models — genuinely missing, not a rounding effect.

**Design a genuine multi-arm comparison of this effect against curb share carefully: match
achieved occupancy across arms, don't just set a nominal target.** If a performance-pricing
controller is used to hold occupancy comparable across curb-share arms (so the comparison isolates
curb share rather than conflating it with occupancy), verify per-arm achieved occupancy
independently — a controller can fail to reach its target in an abundant-supply arm (see the price
vs. supply section above), leaving that arm confounded on both curb share AND occupancy
simultaneously. A per-event manoeuvre cost that appears to fall with rising curb share may in
part (or wholly) be explained by falling occupancy in that same arm, since search/delay dynamics
are occupancy-driven (per the H1 analysis) — state which comparisons are genuinely
occupancy-matched and which are not, and draw the strongest conclusion only from the matched pairs.

## Failure mode under undersupply (H6-style)

As demand exceeds sustainable curb+garage capacity, track never-parked count, still-searching/
still-parked/still-walking counts at simulation end, and through-traffic delay — not occupancy —
as the saturation signal. **Curb occupancy can peak and then FALL as demand keeps rising past
collapse**, because vehicles that never find a space stop contributing to the numerator
(occupied spaces) while the network's ability to deliver drivers to open spaces degrades faster
than spaces are freed by turnover — a city monitoring only occupancy would read a falling number
as easing pressure when the opposite is true. Verify this is a genuine physical measurement of lot
occupancy (not a survivorship artifact of who counts as "never-parked" being excluded from a
different metric) before reporting it, since a declining-occupancy-under-rising-demand finding is
counter-intuitive enough to warrant that check. Confirm whether the installed SUMO version has any
anywhere-parking/frustration fallback behavior (check the binary/CLI directly, don't assume from
documentation) — its absence means the failure mode is unbounded cruising rather than driver
abandonment, changing what "collapse" looks like in the data.

## Validity checks specific to this scenario

- **Three-way occupancy consistency**: at every sampling interval, summed `parkingArea` occupancy
  should equal both the count of vehicles whose subscribed stop-state carries the parking bit and
  the phase-decomposition's own count of currently-parked vehicles. Any deviation indicates a bug
  in the phase-reconstruction logic, not a real phenomenon.
- **Placement/capacity verification from the compiled net**: read back every `parkingArea`'s lane,
  `startPos`/`endPos`, and total `roadsideCapacity` (plus `<space>` count for garages) via TraCI
  or by parsing the additional files against the compiled `.net.xml`, and confirm no lot's observed
  maximum simultaneous occupancy ever exceeds its declared capacity.
- **Teleport-by-reason logging**: if parsing SUMO's stderr/log for teleport reasons by matching a
  string like `"teleporting"`, be aware SUMO emits **two** matching lines per teleport event — a
  `"Teleporting vehicle ... (reason)"` starting line and a separate `"... ends teleporting on edge
  ..."` completion line that carries no reason keyword and will be miscounted as a distinct
  "other/unclassified" event if not filtered out. Match only the starting-line pattern, or dedupe
  by vehicle+timestamp, and cross-check the by-reason total against the deduplicated teleport-ID
  set used elsewhere in the analysis — a mismatch of roughly 2x is the signature of this bug.
- **`traci.vehicle.rerouteParkingArea` can silently strip a vehicle's parking stop** if the newly
  assigned lot is unreachable from the vehicle's current position — it does not raise an
  exception, and the vehicle's every subsequent reroute attempt then fails. Detect via
  `traci.vehicle.getStops()` (a vehicle that should have a pending parking stop but doesn't);
  repair with `traci.vehicle.changeTarget()` **followed by** `setParkingAreaStop()` in that
  order. Track and report the unrepaired residual (typically a small fraction of dispatches) as
  contributing to the never-parked count, not silently dropped from any denominator.

## Related

- `model-parking-with-rerouting` — the base `parkingArea`/`rerouter` mechanism (occupancy-aware
  redirection with full visibility) this skill extends into the pre-parking search process itself.
- `create-grid-network`, `generate-random-trips` — base network and demand generation this
  scenario is built on.
- `model-curbside-delivery-and-lane-blocking-externality` — the lane-blocking verification
  instrument (standing-vehicle-seconds, forced lane changes) transferred directly to the parking
  maneuver's own externality here.
- `model-cordon-tolling-with-generalized-cost-surcharge`, `model-managed-lanes-with-dynamic-tolling-and-self-selection`
  — the generalized-cost-surcharge and VOT-based self-selection patterns reused for curb pricing.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport-artifact methodology
  needed to distinguish genuine gridlock from simulator artifacts under undersupply.
- [[cruising-for-parking-search-externality-and-remedies]] — the knowledge page with the full
  verified findings (divergence exponent, externality regime threshold, information's inversion
  mechanism, pricing's regressive equity profile, the maneuver's separate externality, the
  failure-mode occupancy paradox) this skill's workflow is built on.
- [[information-penetration-and-congestible-routing]] — the congestible-good/herding mechanism
  independently reproduced here in the parking-information domain.
- [[parking-areas-and-rerouters]] — the underlying `parkingArea`/rerouter/TraCI reference this
  skill's scenario-construction steps build on.
