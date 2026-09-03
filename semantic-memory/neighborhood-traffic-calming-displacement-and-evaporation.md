---
summary: In a permeable residential grid enclosed by a parallel-capacity arterial ring, every traffic-calming intervention tested (speed limits, modal filters, diagonal diverters, one-way loop cells) displaces rather than evaporates cut-through traffic under fixed demand, with 2-8x amplification onto the boundary arterial; an elastic-demand test flips the system-efficiency conclusion at a plausible demand elasticity but never flips the boundary-burden conclusion; a modal filter can be a free lunch that makes displaced through-traffic faster (a Braess-flavored effect) while a vClass-based filter's access cost is selective (zero for exempted vehicles) unlike a speed limit's universal cost; and in every variant the largest time penalty falls on residents' own trips, never the targeted through traffic.
keywords:
  - cut-through-traffic
  - rat-running
  - modal-filter
  - diagonal-diverter
  - traffic-calming
  - low-traffic-neighborhood
  - traffic-displacement
  - traffic-evaporation
created: 2026-08-02T11:30:00
last_updated: 2026-08-02T11:30:00
sources:
  - "[[episodic-memory/2026-08-02_11-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_11-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[one-way-vs-two-way-grid-performance-crossover]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[braess-paradox-in-sumo]]"
related_skills:
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - compute-dynamic-user-equilibrium
  - compare-one-way-vs-two-way-street-grid-conversion
  - model-vclass-lane-permissions
  - model-cordon-tolling-with-generalized-cost-surcharge
related_skills_for_graph_view:
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[compare-one-way-vs-two-way-street-grid-conversion]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
---

# Neighborhood Traffic Calming: Displacement and Evaporation

Traffic-calming interventions in a residential grid (modal filters, diagonal
diverters, speed limits, one-way conversions) are usually justified by their effect on
the interior streets they target. This page concerns what happens to the removed
traffic — whether it genuinely disappears ("evaporation") or simply relocates
("displacement") — measured in SUMO on a permeable interior grid enclosed by a
parallel-capacity signalized arterial ring, the canonical rat-running geometry.

## Verified finding: under fixed demand, it is displacement with amplification, not evaporation

A fixed OD matrix cannot show evaporation by construction (there is no mechanism for a
trip to stop existing), so a fixed-demand model can only honestly answer *where*
traffic goes, not *whether* some of it disappears. Measured directly across five
traffic-calming variants (speed limit, modal filter, diagonal diverters, one-way loop
cells, and a combination), every vehicle-kilometre of interior-traffic reduction
reappeared as **2.0-8.0 vehicle-kilometres on the boundary arterial** — an
*amplification*, not a 1-for-1 relocation, because the boundary detour route is longer
than the interior shortcut it replaces. Total network vehicle-km rose 2-6% in every
variant tested. All demand was served in every variant and every replication — the
"neighborhood's gain" in every case was a transfer to the boundary, and a lossy one,
not a system-wide reduction in vehicle travel.

## Verified finding: elastic demand resolves the efficiency question but not the equity question

Re-running the best-performing filter variant with an elastic-demand model (a
generalized-cost feedback loop suppressing or mode-shifting trips whose equilibrium
cost rises past a threshold, swept across a range of demand elasticities) found that
**different conclusions flip at different elasticities, and one conclusion never
flips at all**: "this intervention raises total system travel time" and "this
intervention adds delay to the boundary arterial" each flipped sign at real,
empirically-plausible elasticity values, but "this intervention puts more
vehicle-kilometres onto the boundary arterial" **never flipped**, even at a high
tested elasticity with roughly a quarter of all trips suppressed — the boundary still
carried measurably more vehicle-km than the untreated baseline. **Evaporation, where
it occurs, settles the pure system-efficiency argument; it does not settle the
interior-versus-boundary equity argument.** Any evaluation of a traffic-calming scheme
that relies on an elastic-demand argument to dismiss boundary-road impact should check
whether the specific outcome measure in question is actually one of the ones that
flips.

## Verified finding: a modal filter can be a free lunch that makes the displaced traffic faster — a Braess-flavored effect

A well-placed modal filter (a vClass-restricted plug excluding ordinary cars from a
short interior link, verified to genuinely exclude passenger-class vehicles from the
compiled network while preserving full connectivity for every other address) reduced
cut-through traffic by roughly a fifth in one tested case while simultaneously
*reducing* total system vehicle-hours traveled, and — the more surprising result — the
through traffic that was displaced onto the boundary route ended up traveling
**faster** than it had via the interior shortcut. The interior shortcut had been
individually rational for each driver to choose but collectively worse than the
boundary route once the whole equilibrium is accounted for — a Braess-paradox-flavored
inefficiency (see [[braess-paradox-in-sumo]]): removing a link made the vehicles that
had been using it better off, not worse. This is not guaranteed to hold for every
filter placement or demand level, but demonstrates that "removing a shortcut hurts the
people who used it" is not a safe default assumption.

## Verified finding: the burden of every intervention falls on residents, not the targeted through-traffic

Broken out by OD class (through/rat-run traffic being targeted, versus residents'
own inbound/outbound/local trips), **the largest time penalty from every single tested
intervention landed on residents' own trips** (ranging roughly +8% to +47% across
variants), never on the through-traffic class the intervention was designed to deter —
under the modal filter, the targeted through-traffic class actually gained travel
time. **Reporting only a network-wide or neighborhood-wide average hides this
distributional result entirely.** Every intervention also raised a volume-concentration
statistic (e.g. a Gini coefficient) across interior streets, even when it reduced
total interior exposure — a scheme that improves the average can still make specific
streets (those flanking a modal filter, the surviving direction of a one-way pair, the
outer ring of a diverter layout) measurably worse than under the untreated baseline.

## Verified finding: a vClass filter's access cost is selective; a speed limit's is not

Measuring shortest-path response time from an external point to every interior
address for both an exempted vehicle class (e.g. emergency) and an ordinary passenger
car found a structural difference between intervention types: a vClass-based modal
filter cost the exempted class **exactly zero** additional time (its route is
unaffected, since it is permitted through the filter) while still imposing a real
detour cost on ordinary cars — but a speed-limit intervention, having no selectivity
mechanism, imposed the same relative time cost on every vehicle class traversing the
affected streets, exempted class included. **A traffic-calming toolkit's access-cost
tradeoff depends on the specific mechanism, not just its overall traffic-reduction
effectiveness** — a scheme's efficacy and its emergency-access cost should be evaluated
as two separate dimensions, since they don't move together across intervention types.

## Methodological finding: DUE cost convergence does not imply route-split convergence

In this network shape specifically — a permeable low-capacity interior grid running in
parallel with a higher-capacity arterial — interior and boundary routes can be
near-cost-indifferent over a wide range of route splits, since Wardrop's principle
constrains route *costs* at equilibrium, not the *split* between near-equal-cost
alternatives (see [[dynamic-user-equilibrium-and-wardrop]]). `duaIterate` converged
cleanly on cost while the route split — the actual outcome variable for a
cut-through study — kept wandering by a large factor (a 2.8x swing was measured)
depending on which iteration a run happened to stop at. Neither damping the swap rate
nor `--weight-memory` cleanly resolved this: the latter removed the oscillation but
froze the assignment on a stable-but-clearly-inferior fixed point instead. **The
resolution was to report the outcome variable as a mean and standard deviation over a
DUE tail window (treating the plateau width as a form of uncertainty) and to select
the specific route file handed downstream by a pre-declared rule** (the tail iteration
closest to the tail median), rather than by whichever iteration a fixed budget happened
to end on. **Any SUMO study whose outcome variable is which streets traffic uses,
rather than how long trips take, should check the DUE tail trace of that specific
outcome variable — a converged cost trace and a low route-change fraction are not
sufficient evidence the split itself has converged.**

## Practical takeaways

- Report a traffic-calming intervention's boundary-road "exchange rate," not just its
  interior-traffic reduction — expect amplification (a ratio meaningfully above 1.0),
  not a clean 1-for-1 relocation.
- Test the evaporation hypothesis with an elastic-demand model if the claim rests on
  it, and check each outcome measure's own elasticity crossover separately — some
  conclusions flip and others don't.
- Always decompose by OD/traveler class — the group an intervention burdens most is
  not reliably the group it targets.
- Evaluate an intervention's access-cost tradeoff (e.g. emergency response) as a
  separate dimension from its traffic-reduction effectiveness; the two don't
  necessarily correlate, and a selective (vClass-based) mechanism behaves very
  differently from a universal (speed-limit) one.
- In a permeable-grid-plus-parallel-arterial network, verify DUE convergence on the
  actual outcome variable of interest, not just on cost — a near-indifferent
  equilibrium set is a real and hard-to-detect confound.

See `evaluate-neighborhood-traffic-calming-and-cut-through-displacement` for the full
network-construction, demand-design, DUE-convergence-diagnosis, and elastic-demand-test
methodology.
