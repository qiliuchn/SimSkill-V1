---
summary: "SUMO exposes a rail_crossing junction as an ordinary TraCI traffic light (road links only; GG/yy/rr/uu; the gate goes red exactly 15 s before the train reaches the crossing), which makes MUTCD/ITE railroad preemption of a nearby signal directly implementable - but SUMO's default driving model never lets a vehicle stand inside the crossing, so the trapped-vehicle failure mode has to be injected via jmIgnoreKeepClearTime and verified against a negative control. Verified on a 55 m crossing-to-stop-bar corridor: preemption drives track occupancy to exactly zero at and above a demand-dependent advance preemption time (15-20 s), occupancy is NON-MONOTONE in advance time so an inadequate advance time (~10 s) is 2.6x WORSE than no preemption at all, the simulated design point matches the ITE best-case decomposition rather than the worst case because preemption phase-locks the signal to the train schedule, trapped vehicles delay the trains as well as the cars, and the cost is borne by the cross street at roughly 60-300 vehicle-seconds per train event."
keywords:
  - railroad-preemption
  - advance-preemption-time
  - track-clearance-green
  - rail_crossing
  - keep-clear
  - jmIgnoreKeepClearTime
  - minimum-track-clearance-distance
  - dwell-limited-service
created: 2026-08-04T20:00:00
last_updated: 2026-08-04T20:00:00
sources:
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/instrumentation/instrumentation_report.json]]"
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/instrumentation/junction_blocking_probe.json]]"
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/tables/occupancy_by_cell.csv]]"
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/tables/design_curve.csv]]"
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/tables/ite_comparison.json]]"
  - "[[episodic-memory/2026-08-04_20-00-00/outputs/tables/failure_modes.json]]"
related_pages:
  - "[[rail-crossing-junction-mechanics]]"
  - "[[rail-simulation-and-railsignal]]"
  - "[[emergency-vehicle-preemption-and-bluelight]]"
  - "[[transit-signal-priority]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
related_skills:
  - implement-railroad-preemption-at-a-signalized-intersection
  - build-rail-road-grade-crossing
  - implement-emergency-vehicle-preemption
  - design-signal-change-and-clearance-intervals
  - measure-saturation-flow-and-validate-webster-method
related_skills_for_graph_view:
  - "[[implement-railroad-preemption-at-a-signalized-intersection]]"
  - "[[build-rail-road-grade-crossing]]"
  - "[[implement-emergency-vehicle-preemption]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
---

# Railroad Preemption of Nearby Signalized Intersections

When a signalized intersection sits within a few car lengths of an at-grade rail
crossing, the signal's red queue can extend back over the tracks and strand
vehicles when the gates descend. MUTCD/ITE railroad preemption is the response:
the railroad's advance-warning circuit calls the signal some seconds before the
gates drop, and the controller runs a fixed sequence - right-of-way transfer,
track clearance green, dwell/limited service, exit - rather than a single phase
jump. This page records what SUMO does and does not model about that situation.

## A `rail_crossing` junction is a TraCI traffic light

The crossing node appears in `traci.trafficlight.getIDList()` under the node's
own id, next to the real signal. Verified structure:

- It controls **only the road links** - two here, one per road direction. The
  rail links are not TLS-controlled.
- Its program has four phases: `GG` (duration 0.001), `yy` (5.0), `rr` (0.001),
  `uu` (3.0). The observed cycle is `GG -> yy -> rr -> uu -> GG`, where `u` is
  SUMO's red-yellow, i.e. the gates rising.
- **Gate-down is `getRedYellowGreenState(<crossing>) == "rr"`,** and it begins
  **15 s before the train reaches the crossing** - SUMO's rail-crossing time-gap
  default. Measured lead was 14.69 s in all three probe events at 1 s polling
  (the switch falls inside the sampling interval), with the approaching train
  travelling at a constant 22 m/s.

That constant makes advance preemption predictable without any calibration:
`predicted_gate_down = now + distance_to_crossing / train_speed - 15`. Over 23
preemption cells the mean prediction error against the observed `rr` onset was
**0.31 s**, and the achieved advance time equalled the requested value exactly
at every one of 10-22 gate events per cell. The independent fallback channel -
reading train distance and speed straight off `traci.vehicle` /
`traci.lane.getLength` on the rail approach edges - is also the ETA source, so
it is worth building even when the crossing *is* exposed as a traffic light.

The maximum achievable advance preemption time is bounded by how far upstream
trains are detectable: `rail_approach_length / train_speed - 15 s`. A 900 m
approach at 22 m/s caps advance preemption at 25.9 s, which silently truncated a
30 s request before the approach was lengthened.

## The trapped-vehicle failure mode does not emerge from SUMO's defaults

**Under SUMO's default driving model no road vehicle ever comes to a standstill
inside the crossing footprint, at any demand.** A negative control at eastbound
demands of 450, 600, 750 and 1200 veh/h (the last far above the approach's ~970 veh/h
signal capacity - 40/90 green ratio times the measured 2184 veh/h saturation
flow - so the queue is permanently backed up past the crossing) recorded a maximum of **exactly 0** stopped vehicles overlapping the
crossing at **every** simulated instant. Neither `--ignore-junction-blocker`, nor `jmIgnoreJunctionFoeProb`,
`jmIgnoreFoeProb`, nor `impatience="1"` changed this - SUMO's keep-clear
avoidance simply stops the vehicle short of the junction.

The parameter that governs it is **`jmIgnoreKeepClearTime`** (vType, default
`-1` = never enter a junction the vehicle cannot leave). Setting it to `0`
produced up to **3** simultaneously stopped vehicles on the same 17 m crossing,
at 239 / 355 / 538 / 632 distinct instants for the four demand levels
respectively.

This is the same structural lesson as
[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]'s
dilemma-zone finding: **the non-compliant behaviour that creates the real-world
hazard has to be deliberately injected, and the SUMO-default negative control has
to be run and reported.** A study that omits it will report "no trapped
vehicles" and mistake a modelling default for a safety result.

## Measuring track occupancy: geometry, not queue length

Occupancy must be the count of vehicles whose **physical extent** overlaps the
crossing, computed from polled front-bumper positions projected backwards along
the heading (SUMO's angle is degrees clockwise from north, heading vector
`(sin a, cos a)`), intersected with the crossing footprint read from the
compiled junction shape.

Two definitions must be reported separately:

- the **bare junction footprint** - a vehicle inside it is genuinely on the
  tracks;
- the footprint **plus the MUTCD 1.83 m (6 ft) margin** - which also catches
  vehicles stopped *at* the gate stop line, which are safe.

Conflating them inflates the measured failure rate by roughly **3x**: across the
70 no-preemption gate-down events in the sweep, the MUTCD-margin definition
counted **121** vehicle-instances in **64** events, against **39** instances in
**18** events for the bare footprint (ratios 3.10 and 3.56). A minimum-overlap
threshold (0.5 m) is also needed, or a vehicle whose bumper merely touches the
boundary is counted.

This also explains the **residual occupancy that remains after preemption
succeeds**: across the 134 gate-down events at or above the design advance time,
footprint occupancy was **0** while the MUTCD-margin count was **95** - every
one of those is a vehicle correctly stopped *at* the gate stop line by the
crossing itself, which is the intended outcome, not a failure.

**The compiled crossing footprint, not the node coordinate, is the occupancy
zone - and with default lane widths it is far too short.** A default-width
crossing compiled to a 6.2 m footprint, shorter than a car plus its gap, so at
most one vehicle could ever be inside. Widening the rail edges (`width="14"`)
is a purely geometric lever that stretched the compiled footprint to 17.0 m - a
realistic MUTCD *minimum track clearance distance* for a double-track gated
crossing - without touching train dynamics, and only then did an occupancy
distribution of 0/1/2/3 vehicles become observable.

## Verified: preemption drives occupancy to zero, but only above a threshold

On a corridor with 37.5 m of MUTCD clear storage between the crossing and the
stop bar (about 5 vehicles) and a 90 s fixed-time cycle (40 s of green per
street, 3 s yellow, 2 s all-red):

| EB demand | baseline mean occupancy at gate-down | events with trapped vehicles | minimum advance preemption time for zero occupancy |
|---|---|---|---|
| 450 veh/h | 0.2 (max 1) | 2 of 10 | 15 s |
| 600 veh/h | 0.6 (max 2) | 4 of 10 | 20 s |
| 750 veh/h | 0.9 (max 3) | 4 of 10 | 20 s |

At and above those advance times occupancy was **exactly zero at every one of
the 10 gate events**, at every larger swept advance time, in every demand cell.

## Verified: occupancy is NOT monotone in advance preemption time - a short advance time is worse than none

Mean occupancy at gate-down as a function of advance preemption time is a
**hump peaking near 10 s**:

| advance time (s) | 0 | 5 | 10 | 15 | 20 | 25 | 30 | (no preemption) |
|---|---|---|---|---|---|---|---|---|
| EB 600 veh/h | 0.2 | 0.8 | **1.4** | 0.3 | 0 | 0 | 0 | 0.6 |
| EB 750 veh/h | 0.9 | 1.6 | **2.3** | 0.9 | 0 | 0 | 0 | 0.9 |

At 750 veh/h a 10 s advance time left **2.6x more vehicles standing on the
tracks than running no preemption at all**. The mechanism is direct: an
inadequate advance time terminates the through green for the right-of-way
transfer (yellow plus red clearance) exactly as the gate drops, freezing on the
tracks the queue that the normal cycle would otherwise have been discharging.
**The design value must therefore be the smallest advance time from which
occupancy is zero AND stays zero at every larger swept value** - a lucky zero at
a short advance time (0 s and 5 s both gave zero at 450 veh/h, while 10 s did
not) is not a design point.

## Verified: the simulation lands on the ITE *best-case* branch, because preemption phase-locks the signal

Decomposing the ITE closed form `APT = right-of-way transfer + queue clearance +
separation` with **measured** inputs - saturation headway 1.648 s and startup
lost time 1.706 s, taken from an `<instantInductionLoop>` at the stop bar over
the saturated band of the headway-by-queue-position profile (headway settles at
1.61-1.68 s for positions 5-13, then variance jumps by an order of magnitude
once the standing queue is exhausted):

| EB demand | design queue (veh) | ITE queue clearance | ITE APT, worst-case ROW (18 s) | ITE APT, best-case ROW (5 s) | simulated minimum APT |
|---|---|---|---|---|---|
| 450 | 7 | 13.2 s | 31.2 s | 18.2 s | 15 s |
| 600 | 8 | 14.9 s | 32.9 s | 19.9 s | 20 s |
| 750 | 9 | 16.5 s | 34.5 s | 21.5 s | 20 s |

The simulated design point tracks the **best-case** branch to within a few
seconds and is nowhere near the worst case. The reason is a genuine artifact of
running preemption at all: **each preemption cycle ends with an explicit
`setProgram` / `setPhase` recovery, which re-synchronises the signal cycle to
the train schedule.** After the first event the phase at the preempt call is
deterministic - across 10 events the call landed in the cross-street green 9
times, so the pedestrian-interval truncation (walk 7 s + flashing-don't-walk 6 s
= 13 s minimum) was exercised **once**, giving a 16 s right-of-way transfer on
that single event and a bare 5 s (yellow + all-red) on the other nine. The ITE
worst case exists precisely to cover the call that lands at the start of a
pedestrian interval, and a preemption simulation systematically under-samples
it. **Report the worst-case branch as the design basis; a simulation-derived
advance preemption time is optimistic by roughly the full pedestrian minimum.**

The closed form also over-predicts queue clearance because it charges the
*maximum* design queue at the full saturation headway: measured clearance (track
clearance green onset to zero occupancy) averaged 1.0 / 4.9 / 9.0 s with maxima
of 6 / 11 / 12 s, against the ITE estimates of 13.2 / 14.9 / 16.5 s.

## Verified: trapped vehicles delay the trains, not only the cars

Train delay is an independent, purely rail-side confirmation of the failure
mode. With preemption at or above the design advance time, total train time loss
was **exactly 0.0 s** and the gate-down interval was a clean 20.3 s in every
cell. Without preemption it rose with the trapped-vehicle count - 16.5 s of
train time loss at 450 veh/h, 69.2 s at 750 veh/h, and 272.9 s (54 s of it fully
stationary) at 750 veh/h with a 120 s train headway, where the mean gate-down
interval inflated from 20.3 s to **66.7 s** as blocked trains held the gates
closed. Inadequate preemption showed the same signature at reduced magnitude
(55.7 s of train time loss at a 0 s advance time, 0.0 s at 15 s and above).

## Verified: the cost lands on the cross street, and shrinks as advance time grows

Per train event, relative to the no-preemption baseline on the same demand and
seed (vehicle-seconds of time loss, from `tripinfo`):

| configuration | approach across the tracks | approach feeding the crossing | cross street (2 approaches) | max cross-street queue |
|---|---|---|---|---|
| 450 veh/h, APT 15 s | -197 | +9 | +257 / +296 | 7 -> 10 |
| 450 veh/h, APT 25 s | -261 | +36 | +80 / +102 | 7 -> 7 / 8 |
| 600 veh/h, APT 20 s | -525 | +31 | +275 / +205 | 6 -> 11, 7 -> 10 |
| 600 veh/h, APT 25 s | -565 | +49 | +95 / +62 | 6 -> 7, 7 -> 7 |

The approach lying across the tracks *gains* substantially, because the track
clearance green is extra green time it would not otherwise receive. **A longer
advance time is cheaper for the cross street, not more expensive**: at 25 s the
sequence completes before the gate drops and the controller exits sooner, so the
cross-street penalty is roughly a third of what it is at the minimum viable
advance time.

**Check that the no-preemption baseline is stable before quoting a cost.** At
750 veh/h with 290 s headway, and at both demands with 120 s headway, the
no-preemption baseline is over capacity once the repeated gate closures are
subtracted from the approach's ~970 veh/h green-time capacity, and it gridlocks; preemption then improves *every*
approach (e.g. -7089 / -503 / -768 / -1243 vehicle-seconds per event at
750 veh/h and 120 s headway), which is a recovery from collapse, not the
tradeoff the study is meant to expose.

## Verified: preemption is what makes a short train headway survivable

At a 120 s train headway the no-preemption corridor **never recovers between
events**. The standing eastbound queue at successive gate-downs diverged
monotonically: at 600 veh/h from a mean of 2.3 vehicles over the first three
events to **34.7** over the last three (individual values reaching 58); at
750 veh/h from 17.7 to **41.3**, with recurring 70-72 vehicle queues. Throughput
collapsed to 456 completed eastbound trips against 729 with preemption.

With preemption at a 25 s advance time on the identical demand, the same
corridor is stable: occupancy **zero at all 22 gate events**, the standing queue
at successive gate-downs flat at 0-3 vehicles (first-three mean 1.33, last-three
mean 1.33 at 600 veh/h), and the intersection returning to normal cycling for
**84-85 s between every pair of consecutive events** (22 of 22 completed exits).
Repeated preemption at a short headway is therefore *stabilising* here, not
destabilising - but that conclusion depends on the recovery gap being measured,
not assumed.

## Practical takeaways

- Read the crossing's gate state from `traci.trafficlight` on the crossing node
  id, and build the train-distance fallback anyway - it is the ETA source.
- Inject `jmIgnoreKeepClearTime` to create the hazard, and publish the
  SUMO-default negative control next to the result.
- Measure occupancy geometrically against the compiled junction footprint, with
  a minimum-overlap threshold, and report the MUTCD-margin variant separately.
- Widen the rail edges if the compiled crossing is too short for a vehicle to
  stand inside; the node coordinate is not the occupancy zone.
- Never treat occupancy as monotone in advance preemption time - require zero at
  the candidate value and at every larger value.
- Design to the ITE worst-case right-of-way transfer, not to the simulated
  minimum, because preemption phase-locks the cycle and under-samples the
  pedestrian worst case.
- Report train delay and gate-down duration as an independent check on the
  trapped-vehicle measurement.
- Test the short-headway case by looking for divergence in the queue at
  successive gate-downs and for a genuine return to normal cycling between
  events.

See `implement-railroad-preemption-at-a-signalized-intersection` for the network
build, instrumentation, FSM, sweep and analysis workflow that produced all of
the above.
