---
summary: In a SUMO downtown grid with mixed curb/garage parking, mean search time diverges super-linearly (steeper than the classical 1/(1-occupancy) form) as curb occupancy rises, with the empirical knee landing near the canonical 85% occupancy rule; cruisers' delay externality on other traffic crosses from smaller-than-private-cost to more than 3x it at a specific occupancy threshold rather than gradually; naive driver information about free spaces helps at moderate penetration but inverts (causes net harm) near full penetration due to herding, a coordination failure fixable by reservation rather than an information failure; performance-pricing the curb cuts cruising VMT at zero capital cost but is regressive and loses to an equal-cost supply increment on door-to-door generalized cost; the parking maneuver itself (not just search) is a separate, substantial lane-blocking externality that scales with block-face congestion rather than curb share; and curb occupancy can fall while conditions worsen past collapse, making it an unreliable saturation alarm.
keywords:
  - cruising-for-parking
  - parking-search
  - curb-pricing
  - parking-externality
  - parking-maneuver
  - value-of-time
  - congestible-good
  - generalized-cost
created: 2026-08-03T11:30:00
last_updated: 2026-08-03T11:30:00
sources:
  - "[[episodic-memory/2026-08-03_11-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-03_11-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[parking-areas-and-rerouters]]"
  - "[[curbside-delivery-blocking-externality]]"
  - "[[information-penetration-and-congestible-routing]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
related_skills:
  - model-cruising-for-parking-search-externality
  - model-parking-with-rerouting
  - model-curbside-delivery-and-lane-blocking-externality
  - model-cordon-tolling-with-generalized-cost-surcharge
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
related_skills_for_graph_view:
  - "[[model-cruising-for-parking-search-externality]]"
  - "[[model-parking-with-rerouting]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
---

# Cruising for Parking: Search Externality and Remedies

Treats parking as a **source** of traffic (the cruising/search phase before a space is found) on a
downtown SUMO grid with mixed curb (on-street) and garage (off-street) supply, phase-decomposed
per-driver trips (approach/search/parked/walk), value-of-time-driven behavior, and CRN-replicated,
confidence-interval-reported hypothesis tests. See `model-cruising-for-parking-search-externality`
for the full construction and measurement methodology.

## Verified finding: search time diverges faster than the classical 1/(1-occupancy) form, and the empirical knee lands near the canonical 85% rule

Fitting mean search time against curb occupancy, a divergent form (`a/(1-rho) + b`) dramatically
outperformed a linear model (R² 0.877 vs 0.516, ΔAIC ≈ 88 in a verified study), and a free-exponent
fit found the divergence **steeper than the classical exponent of 1** (fitted γ ≈ 1.59, 95% CI
excluding 1) — the canonical queueing-theory form is directionally right but should not be assumed
to be the correctly-scaled one without fitting it. The empirical "knee" (where search time first
doubles its low-occupancy baseline) landed close to the widely-cited 85% occupancy rule of thumb in
this network, but this depends on block size, lot granularity, and turnover rate — treat the 85%
figure as a target to verify per-scenario, not a universal constant. Cruising's share of total
network VMT/VHT reproduced the commonly-cited "~30% of downtown traffic is cruising" claim **only
near curb saturation** — at moderate occupancy, cruising's VMT share was well below 10%, meaning the
30% figure is a saturated-network number, not a general baseline.

## Verified finding: the cruising externality crosses a private-vs-social-cost threshold at a specific occupancy, not gradually

A controlled-removal experiment (replacing a CRN-matched cohort of parkers with equivalent through
trips of identical origin/departure time, isolating the search behavior specifically) found the
ratio of externality (delay imposed on other traffic) to private cost (the cohort's own foregone
search delay) crossed from **below 1** (search delay privately dominates) to **above 3** (the
externality more than triples the private cost) at a specific, identifiable occupancy threshold in
the mid-70s percent — not a smooth, gradually-rising ratio. Below the threshold, a policy aimed at
reducing cruisers' own search time is roughly aligned with reducing the social cost; above it, the
social cost of cruising is dominated by its effect on everyone else, not the cruiser's own
experience — a materially different policy target.

## Verified finding: driver information about free spaces can invert into net harm near full penetration — a coordination failure, not an information failure

Sweeping driver-information penetration from none to full with a naive "route to the nearest
reported-free space" controller found real benefit at moderate penetration and a measurable
**inversion (net harm) near full penetration**, with cruising's share of network VMT actually
*rising* at 100% informed drivers relative to a lower penetration level. The mechanism is herding:
informed drivers converge on the same reported-free lot faster than the lot's capacity can absorb
them, reproducing the congestible-good/herding signature already verified in
[[information-penetration-and-congestible-routing]] for real-time routing information, now shown to
transfer to the parking-guidance domain specifically. **Adding a reservation layer (never
dispatching two drivers to the same space) restored the benefit at full penetration where naive
guidance inverted** — proving the failure mode is a coordination problem (multiple drivers racing
for one space), not an information-processing problem. This is a load-bearing distinction for policy:
publishing occupancy data alone is not sufficient at high penetration; a booking/reservation
mechanism is needed to realize the benefit.

## Verified finding: curb pricing is regressive and can lose to added supply on door-to-door cost, despite cutting cruising VMT

A feedback-based performance-pricing controller holding curb occupancy near a target cut cruising
VMT and through-traffic delay substantially at zero capital cost in a verified study — but
door-to-door **generalized cost was statistically unchanged**, because the time saved was offset by
the fee itself and, for price-sensitive drivers, a longer walk from a cheaper alternative. Pricing's
burden was **unambiguously regressive**: the lowest-value-of-time quartile was made measurably worse
off while the highest-value-of-time quartile was made slightly better off, with low-VOT drivers
disproportionately displaced to the garage. A supply increment (adding curb/garage spaces, held to
the same nominal scale as the pricing intervention but explicitly **not** cost-equalized against a
real capital-cost model) **beat every pricing arm on door-to-door generalized cost** in the same
study. Neither pricing's superiority nor supply's superiority should be assumed a priori — report
both the VMT/delay effect and the generalized-cost/equity effect, since they can point in different
directions, and flag explicitly whether a supply-vs-price comparison is genuinely cost-equalized.

## Verified finding: the parking maneuver is a separate, substantial lane-blocking externality — and it scales with block-face congestion, not curb share

Beyond search time, the physical act of maneuvering into/out of a curb space briefly blocks the
travel lane — a mechanism invisible to any analysis that models parking as instantaneous. Toggling
`--parking.maneuver` on/off (paired within seed) found this component added a substantial fraction
of total network delay (order 20-50% in a verified study, comparable in size to the search delay the
analysis already accounts for), directly confirmed via a standing-vehicle-seconds instrument (the
same lane-blocking verification protocol as [[curbside-delivery-blocking-externality]], applied to
the maneuver event). **Counter to the intuitive expectation that this externality should scale with
how much curb parking exists, the per-event maneuver cost was found to scale instead with how
congested the specific block face being blocked is** — a manoeuvre on a scarce, heavily-used curb
face costs measurably more per event than the same manoeuvre on an abundant, lightly-loaded one.
**Methodological caution**: any comparison of this effect across curb-share arms must verify
achieved occupancy is genuinely matched across arms (a pricing controller intended to hold occupancy
constant can fail to reach its target in an abundant-supply arm, since it floors at zero fee) —
otherwise curb share and occupancy are confounded and the direction of the finding cannot be
cleanly attributed to either one alone.

## Verified finding: curb occupancy is an unreliable saturation alarm — it can fall while conditions get worse

As parking demand rises past the network's sustainable capacity, curb occupancy was found to
**peak and then fall** even as never-parked counts and through-traffic delay both continued rising
sharply — because vehicles that never find a space stop contributing to the occupancy numerator
while the network's ability to deliver drivers to open spaces degrades faster than turnover frees
them. A city or operator monitoring only curb occupancy would read the falling number as easing
pressure when the opposite is true. **Never-parked count, still-searching count, and through-traffic
delay are the reliable saturation signals**, not occupancy, once a network is near or past
collapse.

## Practical takeaways

- Calibrate and report cruising demand sweeps against **curb** occupancy specifically, not
  curb+garage combined — normalizing against total supply produces a degenerate sweep where curb
  saturates immediately while total occupancy barely moves.
- Verify a performance-pricing controller actually reached its stated occupancy target in every
  arm of a multi-arm comparison before treating those arms as comparable.
- A parking-guidance/information system should include a reservation mechanism, not just publish
  occupancy data, if it will operate at high market penetration.
- Report door-to-door generalized cost and value-of-time-quartile equity outcomes alongside any
  VMT/delay effect when comparing pricing, supply, and information as remedies — a policy can win
  on one dimension and lose (or be regressive) on the other.
- Model the parking maneuver as a distinct event from search when lane-blocking delay matters,
  and verify achieved occupancy (not just curb share) when comparing across supply-mix arms.
- Monitor never-parked/still-searching counts and through-traffic delay, not occupancy, as the
  saturation alarm near or past a network's capacity limit.

See the `model-cruising-for-parking-search-externality` skill for the full scenario-construction
methodology, the divergence-fitting technique, the controlled-removal externality measurement
design, and two disclosed SUMO/TraCI gotchas (a teleporting vehicle's subscribed speed reading as
an enormous invalid value, and a silent parking-stop-loss bug in `rerouteParkingArea`) worth
carrying into any future TraCI-driven parking study.
