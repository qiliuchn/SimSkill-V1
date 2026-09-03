---
name: design-bus-stop-placement-type-and-spacing
description: Use this skill when the user wants to treat a SUMO bus stop as an infrastructure design object — placement (near-side/far-side/mid-block), type (in-lane vs pull-out bay vs a physically separate bay lane), or spacing — rather than a routing waypoint, and wants to know the resulting corridor person-delay tradeoff for cars and bus riders together. Covers building a coordinated signalized arterial with endogenous per-passenger dwell, verifying stop geometry/pedestrian access from the compiled net, determining what `<stop parking="true">` vs `parking="false"` actually does to the traffic stream (lane vacancy, re-entry cost, yield rules), the bus-bay tradeoff between car delay and rider re-entry penalty, the near-side/far-side interaction with transit signal priority, in-lane stops as a single-lane bottleneck, and the classical vs. simulated optimal stop-spacing formula. Trigger on mentions of bus stop placement, bus bay/pull-out design, near-side vs far-side stops, bus stop spacing, `parking="true"` busStop, or bus stop as a bottleneck.
related_skills:
  - simulate-multimodal-transit
  - implement-transit-signal-priority
  - design-arterial-signal-progression-and-verify-bandwidth
  - model-curbside-delivery-and-lane-blocking-externality
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[simulate-multimodal-transit]]"
  - "[[implement-transit-signal-priority]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
---

# Design Bus Stop Placement, Type, and Spacing

Treats the SUMO `busStop` as a corridor design object with three independent axes —
**placement** (near-side / far-side / mid-block relative to the next signal), **type**
(in-lane / pull-out bay / a physically separate bay lane), and **spacing** — and measures how
each axis trades car delay against bus-rider delay, reporting person-hours (occupancy-weighted)
rather than either metric alone. Builds on `simulate-multimodal-transit` (base busStop/pedestrian
mechanics) and `implement-transit-signal-priority` (the TSP controller, imported unchanged) layered
onto a `design-arterial-signal-progression-and-verify-bandwidth`-style coordinated arterial.

## Building the parameterized corridor

Write plain-XML `.nod.xml`/`.edg.xml` (as in `create-single-intersection`) for a multi-signal
arterial, run `netconvert` twice: once for the base geometry with
`--sidewalks.guess --crossings.guess --walkingareas`, then a **second** `netconvert` pass that
bakes a hand-built coordinated `tlLogic` program into the already-compiled net (a second `tlLogic`
supplied via an additional file with the same `programID` is rejected — the offsets/splits have to
be authored into the net itself, or into a fresh `programID`).

Model dwell **endogenously**: `boardingDuration` per passenger plus real person demand
(`walk -> ride -> walk` plans) boarding/alighting at each `busStop`, not a fixed `duration=`. Draw
person origins/destinations **independently of the stop layout** (not snapped to the nearest stop
after the fact) so the same CRN seed produces the same OD set across every placement/spacing arm —
otherwise a stop-count or spacing change silently changes who is even eligible to ride, contaminating
every downstream comparison (see the H4/H5 population bias below).

## Verify stop geometry and access from the COMPILED net, not from intent

Never trust the authoring parameters — reconstruct every claim from the compiled `.net.xml` and the
additional file actually loaded:
- each `busStop`'s lane exists, the stop's `[startPos, endPos)` lies inside `[0, laneLength)`, and
  the lane permits `bus`;
- the stop's absolute corridor position, reconstructed from the compiled net's edge geometry, matches
  the intended offset from the signal (verified to 0.000 m in a real build — `netconvert` does not
  silently reposition an explicitly-placed stop the way it can silently shorten an edge/turn-bay
  length elsewhere, but check anyway rather than assume);
- every stop has exactly one `<access lane="..." pos="..."/>` child on a lane that permits
  `pedestrian` and **not** `passenger` — without it, no person can reach or board the stop;
- for a physically separate bay lane, the stop's own lane permits `bus` and **not** `passenger`.

**Pedestrian access must also be verified behaviourally, not just structurally.** `--sidewalks.guess`
alone does not connect the two sides of an intersection on the same side of a street —
`--crossings.guess` is what closes that loop. Without it, mean pedestrian access-walk distance can
inflate by ~4x (a forced detour of exactly 2x the cross-street length was measured in a verified
run) with zero structural error — the `<access>` element still exists and validates, the walk to
reach it is just absurd. Confirm via the realised mean walk distance, not just element presence.

## The `parking="true"` vs `parking="false"` mechanism — treat as a question, not an assumption

This is the single most important thing to establish before any placement/type comparison, and it
requires four separate instrument channels (the first three transferred directly from
`model-curbside-delivery-and-lane-blocking-externality`'s lane-blocking verification protocol):

1. **Does `parking="true"` actually vacate the lane?** Yes, completely — verified via (a) the
   `stop-output` `parking` attribute, (b) a **zero-car clean-room** `<laneData>` `sampledSeconds`
   comparison on the stop lane (with an identical dwell workload, in-lane occupies substantially more
   lane-seconds than bay — a verified run measured 686.7 s vs 537.1 s for 120 s of total configured
   dwell), and (c) counting forced (`strategic`/`urgent`) lane changes off the stop lane as car flow
   rises — a verified sweep found 24-34 forced changes/run in-lane vs. **exactly 0** at every flow
   for a bay. No physical geometry is required — SUMO's abstract `parking="true"` bay is
   behaviourally a real bay.

2. **What governs re-entry, and where does the cost hide?** The naive measurement — "time from
   `stop-output`'s `ended` timestamp until the vehicle exceeds a small speed threshold" — reports
   **exactly 0.0 s at every flow tested**, and `blockedDuration` is always 0. **This looks like "no
   re-entry penalty exists" and is wrong.** The penalty is real, flow-dependent, and hidden *inside*
   the dwell's own `ended` timestamp: regress dwell duration on realised boarding/alighting load in a
   zero-car clean room to get the baseline dwell function, then repeat the regression at each tested
   flow level — the intercept increase between clean-room and loaded is the parking overhead. A
   verified sweep found this overhead rising **monotonically and convexly with per-lane car flow**,
   from ~0 s at zero flow to 12-14 s/stop near 900 veh/h/lane, essentially independent of lane count
   at equal per-lane flow — consistent with a classical gap-acceptance wait
   `E[W] = (exp(q*tau) - 1)/q - tau`, with the per-point implied critical gap itself rising with flow
   (not a single constant tau). **Methodological gotcha to carry forward: a post-stop FCD timing
   measurement will report a re-entry penalty of exactly zero even when a real, substantial,
   flow-dependent penalty is being applied — check the dwell-vs-load regression's intercept shift,
   not simple post-stop movement timing.**

3. **Is re-entry gap-checked or forced?** Checked, by an ordinary car-following/lane-change safety
   criterion, not a dedicated merge model — a verified run found a nonzero minimum accepted gap
   (~20 m) and measurable follower deceleration on some departures, meaning part of the re-entry cost
   is transferred to the following car rather than fully borne by the bus.

4. **Is there any yield-to-bus rule?** No — confirmed by scanning `sumo --help` for any
   bus/yield-priority option and by enumerating the complete junction-model (`jm*`) attribute surface
   in SUMO's route XSD. SUMO does not model a bus-must-be-yielded-to obligation of the kind some
   real-world traffic codes impose. If a study needs one, it must be added externally via TraCI or an
   authored stop/priority rule — don't assume it exists by default.

## The bus bay tradeoff (car delay vs. rider re-entry penalty)

A pull-out bay always removes car delay and always imposes a rider penalty via the mechanism above,
but **whether the net corridor person-hours effect favors the bay is a genuine, non-obvious
crossover, not a foregone conclusion in either direction.** In a broad sweep across lane counts, car
flows, and passenger loads, a native (unaugmented) SUMO bay won on total person-hours in every tested
cell — the trap is real but narrow: it requires simultaneously (a) high bus occupancy (roughly 35+
riders per bus — a busy trunk route, not a feeder), (b) 2+ general-traffic lanes per direction (so
the in-lane alternative was cheap for cars to overtake), and (c) moderate rather than heavy car flow
(so the car-side saving is small). Only inside that narrow region does the corridor land at
break-even, at which point a **critical car occupancy** (`= -Δrider_person_h / Δcar_vehicle_h`) near
a realistic value (~1.2 persons/car) is reached, and a small additional pull-out penalty beyond
SUMO's own (on the order of a few seconds per stop) is enough to flip the sign. Report this crossover
explicitly (critical car occupancy per cell, and the additional pull-out penalty needed to flip
break-even cells) rather than a single "bays are good/bad" verdict.

**Building a physically separate bay lane (splitting the link) is a genuine junction-geometry
confound**, not a clean type comparison — the extra priority junctions it creates at each end of the
split can cost general traffic substantial extra time-loss with *no change in bus activity at all*,
exactly the confound `model-curbside-delivery-and-lane-blocking-externality` warns about for
mid-block driveways. Use a physically separate bay lane only to confirm the lane-vacating mechanism
(each variant compared against itself), not for a cross-type person-hours comparison, unless the
junction-geometry confound is itself measured and controlled for.

## Placement under transit signal priority (near-side / far-side / mid-block)

TSP benefit and placement interact strongly and can **reverse the placement ranking**. Measure the
mechanism directly from bus FCD via a per-second state machine (`DWELL` inside the stop window,
`SIGNAL_STOP` halted near the signal, `SLOW`, `RUNNING`) rather than asserting it:

- A **near-side** stop consumes the priority green with dwell — the bus is still stopped boarding
  when the extended/advanced green arrives, so it requests priority again, hits the per-cycle grant
  cap, and TSP removes a much smaller fraction of its signal delay than at far-side/mid-block (a
  verified run: -46% signal-stop time near-side vs. -89% to -91% far-side/mid-block, despite issuing
  **more** grant requests near-side, not fewer). The net effect can be that **TSP makes the corridor
  worse** at a near-side stop (higher cross-street cost for less bus benefit) while still being a
  clear net win far-side/mid-block.
- **Without** TSP, the ranking can be the opposite — a near-side stop's dwell partly "hides" inside a
  red the bus would have waited through anyway, making near-side the *fastest* placement for the bus
  with no priority in play. **Decide whether the corridor will run TSP before deciding stop
  placement** — evaluating placement first gets the answer backwards.
- The textbook claim that near-side stops worsen car queues by blocking the intersection approach did
  not reproduce in a verified test with no right-turn demand at the stop (the usual real-world
  mechanism for that effect) — instead, **far-side** in-lane stops produced the measurably longer
  queues, because a bus dwelling immediately downstream of the signal blocks the link's discharge and
  the queue reaches back into the junction. Don't assume the textbook mechanism without checking
  whether the geometry (e.g. right-turn volume at the stop) that produces it is actually present.

## In-lane stop as a single-lane bottleneck

On a single lane per direction (no escape lane), sweep bus frequency x mean dwell at **constant
total curb-blockage time** to isolate the effect of dwell *shape* from total blockage *amount*.
**Few long dwells produce measurably worse car delay than many short dwells at equal total blockage**
— the opposite sign from the multi-lane finding in [[curbside-delivery-blocking-externality]] ("many
short stops cost more than few long stops"). The two are reconcilable, not contradictory: on a
multi-lane street the cost is the *number of forced merge events*, which scales with stop count; with
no escape lane the cost is the queue that grows behind each individual blockage, and queueing delay
grows faster than linearly with a single stop's duration. Track queue spillback (max queue vs. link
storage) alongside mean delay — the point where queue length starts reaching the upstream signal is
the practically actionable threshold, more useful than fitting a specific growth-rate exponent (an
exponent fit on this kind of sweep needs its derivation script explicitly checked/retained — an
unretained or ad hoc exponent claim is exactly the kind of number that doesn't survive independent
re-verification).

## Stop spacing: analytic vs. simulated optimum

The classical formula `s* = sqrt(2*v_w*L_ride*t_stop)` (access-walk time traded against an
in-vehicle stop penalty `t_stop` = door/dead time + kinematic accel/decel loss, walking speed `v_w`,
mean ride distance `L_ride`) predicts the **rider-only** optimal spacing reasonably well against a
simulated sweep (a verified comparison found the analytic and simulated rider-optimal spacing within
~10% of each other). Per-passenger boarding time does not belong in `t_stop` — every passenger boards
exactly once regardless of spacing, so it cancels out of the optimization; only the door/dead-time
and kinematic penalty terms are spacing-dependent.

**Critical bias to fix before running any spacing sweep: the rider population itself shrinks as
spacing widens**, because a person whose nearest boarding and alighting stop coincide can no longer
make a transit trip at all — they don't get counted as a delay, they simply vanish from the sample. A
raw per-arm comparison is therefore a survivorship-censored comparison that can show a spurious,
much-wider "optimum" than the true one. **Fix by restricting every spacing comparison to a matched
cohort — the persons who can ride in every tested spacing arm** — the same discipline used elsewhere
in this project for CRN-paired comparisons. Once the car externality (fewer in-lane blocking events
at wider spacing) is included in a corridor-total objective, the optimum shifts wider than the
rider-only optimum and then goes **flat** across a broad range — meaning above some threshold,
spacing choice stops being an efficiency question and becomes a purely distributional transfer
between riders and drivers. State it that way rather than as a single "optimal spacing" number.

**Consolidation (widening spacing) is never a free mean-time win — decompose it.** Report the
percentage of riders made *worse* off (not just the mean shift, which can look small while a large
majority of riders lose), the loss distribution's upper tail (p90/p99/worst case can be several times
the mean), and — separately from the delay figures — the riders who lose the ability to make a
transit trip at all as their nearest stop pair collapses to zero distance. A mean-only report of a
consolidation study systematically understates who bears the cost.

## Analysis scripts (`scripts/`)

- `scenario.py` — parameterized corridor + endogenous-dwell demand builder (two-pass netconvert).
- `runner.py` — one experimental cell → reduced metrics (person + vehicle delay, validity counters).
- `expbase.py` — CRN replication harness with paired-t statistics (reuse rather than re-deriving —
  see `quantify-sumo-run-to-run-variability` for why unpaired comparisons on CRN-shared-seed data can
  reverse a conclusion).
- `verify_infrastructure.py` — compiled-net stop/access/placement verification.
- `verify_parking_mechanism.py` — the `parking="true"`/`"false"` lane-vacancy instrument channels.
- `verify_reentry.py` / `verify_reentry_forced.py` / `fit_reentry_gap.py` / `verify_dwell_model.py` —
  the re-entry-cost-is-hidden-in-dwell measurement chain.
- `h1_bay_trap.py` / `h1b_bay_trap_probe.py` — the bay-tradeoff sweep and crossover probe.
- `h2_nearside_farside_tsp.py` / `h2_mechanism.py` / `h2b_nearside_car_queue.py` — placement x TSP.
- `h3_inlane_bottleneck.py` — the single-lane frequency x dwell sweep.
- `h4h5_spacing.py` / `make_figures.py` — spacing sweep, matched-cohort correction, consolidation
  decomposition.
- `timespace.py` — bus time-space diagram + per-stop delay decomposition (running/slow/signal/dwell
  seconds per corridor segment) from bus-only FCD.
- `validity_summary.py` — global teleport/completion/stop-service audit.

## Gotchas

- A second `<tlLogic>` with the same `programID` in an additional file is rejected by SUMO for an
  already-compiled coordinated program — bake a second signal program into the net via a second
  `netconvert` pass (or use a fresh `programID`), don't expect an additional file to override one.
- Person origins/destinations must be drawn **independently of stop layout**; snapping to nearest
  stop after generation makes the rider population layout-dependent and silently biases every
  spacing/placement comparison (see the H4 matched-cohort fix above).
- `personCapacity` must be set high enough for the demand level under test — a too-low capacity
  silently censors ridership (persons never board, and this is easy to miss because it doesn't error
  or teleport, it just quietly reduces the rider sample in exactly the highest-demand cells that
  matter most). Check the completed-vs-still-waiting/riding person count explicitly, the same
  discipline `validate-congested-scenario-results-against-teleport-artifacts` applies to vehicles.
  The censoring is now quantified: SUMO has **no pass-up observable at all** — no output field, no
  TraCI counter, no warning — so a line refusing a third of its passengers looks exactly like a
  healthy one. If a binding capacity is the *subject* rather than a hazard, see
  `model-capacity-constrained-transit-passenger-loading`, which reconstructs pass-ups by joining
  `--stop-output` with tripinfo `<ride>`.
- **The dwell law is a `max()`, not a sum, and there is no `alightingDuration`.** Verified with zero
  residual across 33 configurations: `dwell = max(door_time, boardingDuration × (boarded + alighted))`.
  Boarding and alighting are strictly *serial* and share the single `boardingDuration`; the fixed
  `<stop duration=>` door time is **absorbed, not added** (5 board + 5 alight at `boardingDuration=2`
  gives 20.00 s with a 4 s door, and still 20.00 s with a 20 s door). SUMO 1.27.1's vType schema has
  only `boardingDuration`, `loadingDuration` (containers) and `boardingFactor` — and a bogus
  `alightingDuration` is **accepted silently, exit code 0**, unless `--xml-validation always` is
  passed. Validate a vType once when authoring it. See
  [[transit-capacity-passenger-loading-and-pass-up-dynamics]].
- The TraCI stepping-loop exit condition for a mixed car+person simulation must check
  `traci.person.getIDCount() > 0` in addition to `traci.simulation.getMinExpectedNumber() > 0` —
  the latter counts vehicles only and will truncate persons still walking if used alone.
- A post-stop FCD timing measurement of re-entry delay will read as exactly zero even when a real
  penalty is being applied (see the parking mechanism section above) — always cross-check against a
  dwell-vs-load regression, not just movement timing after the stop event ends.

## Related

- `simulate-multimodal-transit` — the base busStop/pedestrian-access/intermodal-demand mechanics this
  skill builds on.
- `implement-transit-signal-priority` — the TSP controller imported unchanged for the placement x
  priority interaction.
- `design-arterial-signal-progression-and-verify-bandwidth` — the coordinated-arterial construction
  (offsets, `(t - offset) mod C` convention) this skill's corridor is layered onto.
- `model-curbside-delivery-and-lane-blocking-externality` — the lane-blocking verification protocol
  (stop-output, laneData, forced lane changes) transferred directly to the `parking` mechanism
  investigation here, and the source of the opposite-sign finding this skill's H3-equivalent result
  is reconciled against.
- `quantify-sumo-run-to-run-variability` — CRN replication design and the paired-vs-unpaired
  statistical discipline used throughout every hypothesis test here.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport-artifact checking
  methodology, and the model for the completed-vs-still-riding/waiting person accounting this skill
  extends from vehicles to persons.
- [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]] — the knowledge page with
  the full verified findings (parking mechanism, bay crossover, near/far-side TSP reversal, spacing
  results) this skill's workflow is built on.
- [[bus-bunching-and-forward-headway-holding]] — the dwell-scales-with-load mechanism reused here for
  endogenous dwell, and the source of the per-stop dwell-growth-along-the-corridor progression-loss
  feedback this skill's time-space diagram also shows.
