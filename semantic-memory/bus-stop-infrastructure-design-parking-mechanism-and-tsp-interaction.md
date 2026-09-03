---
summary: On a coordinated signalized arterial with endogenous per-passenger dwell, SUMO's `<stop parking="true">` bus bay genuinely vacates the lane but hides a real, flow-dependent re-entry cost (0-14 s/stop, gap-acceptance-shaped) inside the dwell's own end timestamp rather than in post-stop movement timing, and has no yield-to-bus rule at all; the resulting bay-vs-in-lane person-hours tradeoff favors the bay almost everywhere except a narrow high-ridership/multi-lane/moderate-flow region, near-side stops cancel most of a transit-signal-priority benefit and can flip TSP into a net corridor loss (while being the fastest placement without priority), a single-lane in-lane stop's car-delay cost is driven by individual dwell length rather than total blockage (opposite sign to the multi-lane curbside-delivery finding), and the classical stop-spacing formula predicts the rider-optimal spacing well while the corridor-total optimum is wider and then flat, with consolidation making the large majority of remaining riders worse off.
keywords:
  - bus-stop
  - bus-bay
  - pull-out-bay
  - stop-placement
  - stop-spacing
  - transit-signal-priority
  - near-side-far-side
  - parking-attribute
  - dwell-time
  - person-delay
created: 2026-08-03T09:30:00
last_updated: 2026-08-03T09:30:00
sources:
  - "[[episodic-memory/2026-08-03_09-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-03_09-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[transit-signal-priority]]"
  - "[[curbside-delivery-blocking-externality]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
related_skills:
  - design-bus-stop-placement-type-and-spacing
  - simulate-multimodal-transit
  - implement-transit-signal-priority
  - model-curbside-delivery-and-lane-blocking-externality
related_skills_for_graph_view:
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[simulate-multimodal-transit]]"
  - "[[implement-transit-signal-priority]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
---

# Bus Stop Infrastructure Design: Parking Mechanism and TSP Interaction

Treats the SUMO `busStop` as a corridor design object — placement, type, and spacing — rather than
a routing waypoint, measured on a coordinated signalized arterial with fully endogenous
per-passenger dwell (real persons boarding/alighting, `boardingDuration`-driven). Every result below
reports occupancy-weighted rider person-time alongside vehicle delay, replicated with Common Random
Numbers and paired-t confidence intervals. See `design-bus-stop-placement-type-and-spacing` for the
full construction and verification methodology.

## Verified finding: `parking="true"` fully vacates the lane, but the re-entry cost hides inside the dwell timestamp, not in post-stop movement

A `parking="true"` bus stop removes the vehicle from the lane's traffic stream entirely — verified
via the `stop-output` `parking` attribute, a zero-car clean-room lane-occupancy comparison (686.7 s
in-lane vs. 537.1 s bay for identical dwell workload), and forced (`strategic`/`urgent`) lane-change
counts off the stop lane (24-34/run in-lane vs. **exactly 0 at every car flow tested** for a bay). No
physical bay geometry is required for this behavior.

The re-entry cost is real but genuinely hard to see. Measuring "time from `stop-output`'s `ended`
timestamp until the bus moves" reports **0.0 s at every flow from 0 to 1000 veh/h**, and
`blockedDuration` is always 0 — a naive reading concludes SUMO models no re-entry penalty at all.
It does: the penalty is absorbed *inside* the dwell's own `ended` timestamp. Regressing dwell
duration on realised boarding/alighting load in a zero-car clean room versus at increasing car flow
isolates it — a verified sweep found the parking-specific overhead rising **monotonically and
convexly from ~0 s at zero flow to 12-14 s/stop near 900 veh/h/lane**, essentially independent of
lane count at equal per-lane flow, and shaped like a classical gap-acceptance wait
`E[W] = (exp(q*tau) - 1)/q - tau` with the implied critical gap itself rising with flow (roughly 4-7
seconds) rather than being a single constant. Re-entry is checked by an ordinary car-following safety
criterion, not a dedicated merge model, and part of its cost is transferred to the following car
(nonzero measured follower deceleration on some departures). **There is no yield-to-bus rule anywhere
in SUMO** — confirmed by scanning the CLI option surface and the complete junction-model attribute
list in the route XSD; a real-world bus-priority-to-merge obligation must be imposed externally.

**Methodological consequence:** a post-stop FCD timing measurement of bus re-entry delay will read
as exactly zero even when a real, substantial, flow-dependent penalty is being applied. Always
cross-check against a dwell-vs-load regression's intercept shift between a clean-room and a loaded
condition, not simple post-event movement timing.

## Verified finding: the bus-bay tradeoff has a narrow, specific crossover region, not a universal answer

A pull-out bay always reduces car delay and always imposes the rider re-entry penalty above, but in
a broad sweep of lane count, car flow, and passenger load, the native (unaugmented) SUMO bay won on
total corridor person-hours in every tested cell. The trap is real but requires simultaneously: high
bus occupancy (roughly 35+ riders/bus — a trunk route, not a feeder), 2+ general-traffic lanes per
direction (making the in-lane alternative cheap for cars to overtake), and moderate rather than heavy
car flow (small car-side saving). Only there does the corridor reach break-even, with a **critical
car occupancy** (`-Δrider_person_h / Δcar_vehicle_h`) near a realistic urban value (~1.2 persons/car,
vs. <0.3 elsewhere in the sweep), at which point a small additional pull-out penalty beyond SUMO's
own (a few seconds/stop) is enough to flip the sign. A physically separate bay lane (splitting the
link) is a genuine junction-geometry confound — the extra priority junctions it creates can cost
general traffic substantial extra delay with *no change in bus activity*, so it should only be used
to confirm the lane-vacating mechanism, not for a person-hours type comparison, unless that confound
is itself measured and controlled.

## Verified finding: near-side stops largely cancel transit signal priority, and the placement ranking reverses with vs. without TSP

Measured directly from a per-second FCD state machine (dwell / signal-stop / slow / running), TSP
removed 89-91% of a far-side or mid-block bus's signal-stop time but only 46% of a near-side bus's,
despite the near-side stop issuing **more** priority-grant requests, not fewer — the granted green
arrives while the bus is still dwelling, so it requests again, and the per-cycle grant cap binds. The
net corridor effect can flip sign entirely: TSP made the corridor **worse** at a near-side stop
(higher cross-street cost for less bus benefit realised) in a verified run, while being a clear net
win far-side and mid-block. **Without** TSP the ranking can invert — near-side's dwell partly hides
inside a red the bus would have waited through anyway, making near-side the fastest placement with
no priority in play. **Placement should be decided after deciding whether TSP will run, not before**
— deciding placement first gets the answer backwards. Separately, the textbook claim that near-side
stops worsen car queues by blocking the intersection approach did not reproduce in a geometry with no
right-turn demand at the stop; instead **far-side** in-lane stops produced the measurably longer
queues, because a bus dwelling immediately downstream of a signal blocks the link's discharge and the
queue reaches back into the junction — check for the mechanism (e.g. right-turn volume) that would
actually produce the textbook effect rather than assuming it.

## Verified finding: single-lane in-lane bottleneck severity depends on dwell shape, with the opposite sign from the multi-lane curbside-delivery finding

On a single lane per direction (no escape lane), sweeping bus frequency x mean dwell at constant
total curb-blockage time isolates dwell *shape* from blockage *amount*. Few long dwells produced
measurably worse car delay than many short dwells at equal total blockage — the **opposite sign**
from [[curbside-delivery-blocking-externality]]'s verified finding that many short stops cost more
than few long stops at equal curb-occupancy time. The two are reconcilable, not contradictory: on a
multi-lane street the cost mechanism is the *number of forced merge events*, which scales with stop
count; with no escape lane, the cost is the queue that grows behind each individual blockage, and
queueing delay grows faster than linearly with a single stop's duration. Track queue spillback (max
queue vs. link storage) alongside mean delay for the practically actionable threshold — a specific
growth-rate exponent fit on this kind of sweep needs its derivation explicitly retained and checked;
an unretained ad hoc exponent claim did not survive independent re-verification in this episode and
was removed rather than re-guessed.

## Verified finding: the classical spacing formula predicts the rider optimum well; the corridor-total optimum is wider and then flat

The classical `s* = sqrt(2*v_w*L_ride*t_stop)` (access-walk time vs. an in-vehicle door/dead-time +
kinematic accel/decel penalty, excluding per-passenger boarding time since every passenger boards
exactly once regardless of spacing) predicted the simulated rider-only optimal spacing within about
10% in a verified comparison. **A critical bias must be fixed before running any spacing sweep:** the
rider population itself shrinks as spacing widens, because a person whose nearest boarding and
alighting stop coincide can no longer make a transit trip and simply vanishes from the sample rather
than being counted as delayed — a raw per-arm comparison is a survivorship-censored comparison that
can show a spuriously much-wider "optimum" (verified case: raw data suggested an 800 m optimum;
correcting to a matched cohort of riders present in every spacing arm moved it to 250 m). Once the
car externality (fewer in-lane blocking events at wider spacing) is added to a corridor-total
objective on the matched cohort, the optimum shifts wider than the rider-only optimum and then goes
**flat** across a broad range — above that threshold, spacing choice is a purely distributional
transfer between riders and drivers, not an efficiency decision, and should be reported as such
rather than as a single "optimal spacing" number.

## Verified finding: stop consolidation is never a free mean-time win

Reporting only the mean travel-time change from consolidating stops conceals who actually pays. In a
verified matched-cohort comparison, a spacing widening produced a modest mean rider-time increase
while a large majority (~70-80%) of remaining riders were made worse off, with the upper-tail loss
(p99, worst-case) several times the mean. Separately from the delay figures, a substantial share of
the original rider population can lose the ability to make a transit trip at all as their nearest
stop pair collapses to zero distance when stops are removed — this loss is invisible to a mean-time
metric entirely, since those trips are gone rather than merely slower. Report the loser share, the
tail of the loss distribution, and the lost-trip count together, not the mean alone.

## Practical takeaways

- Verify the `parking="true"`/`"false"` mechanism (lane vacancy, hidden re-entry cost, no yield rule)
  for the specific SUMO version and scenario in question before assuming a bay's cost/benefit —
  it is not simply "bay = good for cars, bad for buses" in a fixed proportion; the crossover is
  narrow and occupancy/lane-count/flow dependent.
- A post-stop FCD movement-timing measurement cannot detect the bay re-entry penalty; use a
  dwell-vs-load regression instead.
- Decide whether TSP will run before deciding stop placement — the near-side/far-side ranking
  depends on it and can fully reverse.
- On a single lane with no escape, prefer several short dwells over few long ones for car delay —
  opposite to the multi-lane curbside-delivery guidance.
- Fix the survivorship bias (matched cohort) before drawing any spacing-optimum conclusion, and
  report consolidation's distributional losers and lost trips, not just the mean travel-time shift.

See the `design-bus-stop-placement-type-and-spacing` skill for the full corridor-construction and
verification methodology, and the practical design decision rule stated in measurable corridor
conditions (lane count, car flow, bus occupancy, dwell length thresholds).
