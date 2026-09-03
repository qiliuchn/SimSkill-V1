---
summary: What SUMO's intermodal router and person outputs actually do — duarouter applies no transfer penalty and no minimum connection buffer at all (a zero-second connection is an accepted plan), `<ride depart>` is the boarding time so `ride@duration` excludes wait, every person stage reconciles to `personinfo@duration` with 0.0 s error, stranded travellers still appear with `duration="-1"` but a real `waitingTime`, and a generous `until=` timetable silently erases traffic delay from measured bus cycle times.
keywords:
  - intermodal-routing
  - transfer-penalty
  - personinfo
  - person-stage-decomposition
  - duarouter
  - schedule-awareness
  - incomplete-trips
  - timetable-binding
created: 2026-09-01T10:21:28
last_updated: 2026-09-01T10:21:28
sources:
  - "[[episodic-memory/2026-09-01_10-21-28/summary.md]]"
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[transit-network-design-and-frequency-setting]]"
  - "[[gtfs-import-and-pt-representation-semantics]]"
  - "[[car-to-transit-intermodal-transfer-and-park-and-ride]]"
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
related_skills:
  - design-transit-service-plan-under-a-bus-hour-budget
  - simulate-multimodal-transit
  - evaluate-multimodal-accessibility-and-equity
related_skills_for_graph_view:
  - "[[design-transit-service-plan-under-a-bus-hour-budget]]"
  - "[[simulate-multimodal-transit]]"
  - "[[evaluate-multimodal-accessibility-and-equity]]"
---

# Intermodal Transfer and Person-Stage Semantics in SUMO

Everything on this page was established empirically against SUMO 1.27.1, not read
from documentation. It matters because a transit study's headline number is a
weighted sum over person stages, and three of the five semantics below are easy
to get silently wrong.

## duarouter applies NO transfer penalty and NO connection buffer

The intermodal router minimises **arrival time and nothing else**. It charges no
penalty for the act of transferring and enforces no minimum connection time.

The test: a one-seat ride of controllable duration `T_dir` against a two-seat
plan whose two legs meet at the *identical* `busStop` (so the transfer walk is
genuinely zero), sweeping the hub wait `w` and scanning `T_dir` to 1-second
resolution to find where the router abandons the direct ride.

| hub wait `w` | two-seat total | router switches at `T_dir` = | implied extra penalty |
|---|---|---|---|
| -120 s | 280 s | never — two-seat plan **rejected** | n/a |
| -60 s | 340 s | never — two-seat plan **rejected** | n/a |
| 0 s | 400 s | **401 s** | **+1 s** |
| 30 s | 430 s | **431 s** | **+1 s** |
| 120 s | 520 s | **521 s** | **+1 s** |
| 300 s | 700 s | **701 s** | **+1 s** |

The constant +1 s is the strict-inequality tie-break, not a penalty. **A
zero-second connection is accepted as a valid plan** — the router will happily
build an itinerary in which a passenger alights and boards in the same instant. A
cross-junction variant (two different stops) shifted the switch point by exactly
**5 s** at both hub gaps tested: the physical walk, charged as ordinary clock
time and nothing more.

The router *does* enforce chronological feasibility — a leg departing before the
feeding vehicle arrives is rejected (the negative-`w` rows above).

**Consequence.** Any transfer cost must be applied in post-processing as an
explicit generalized-cost weight, plus a sensitivity over the assumed penalty.
Route choice will not respond to that penalty, so it is a *scoring* assumption,
not a behavioural one — say so when reporting. `design-transit-service-plan-under-a-bus-hour-budget`
sweeps 0-1200 s for exactly this reason.

## Person stages are fully separable, and reconcile exactly

`<personinfo>` legs appear as `<walk>`, `<access stop="...">` and `<ride>` in plan
order. The arithmetic that matters:

- **`<ride depart=...>` is the BOARDING time**, so `ride@duration` is in-vehicle
  time and **excludes wait**.
- `ride@waitingTime` is the wait that preceded that boarding.
- `personinfo@traveltime = personinfo@duration - sum(ride.waitingTime)`.

Splitting access walk / initial wait / in-vehicle / transfer walk / transfer wait
around the first and last boarded ride, then summing, reconciled to
`personinfo@duration` with **max absolute error 0.0 s and 0 mismatches over 937
completed persons**. The decomposition is exact — if yours does not reconcile,
the parser is wrong, not the simulator.

## The router is schedule-aware, and frequency changes route choice

It is genuinely timetable-driven, not frequency-approximating. Given line P
(departs 200, 600 s ride, arrives 800) against line Q (departs 700, 150 s ride,
arrives 850), the router chose **P** — trading a 4x longer ride for a 50 s
earlier arrival. Moving Q's arrival to 650 flipped the choice.

Raising a line's frequency therefore changes **route choice**, not merely
realised wait. With 240 persons departing uniformly, choosing between a slower
frequent line SF (520 s in-vehicle) and a faster hourly line FR (330 s):

| SF headway | chose SF | chose FR | walked | SF share |
|---|---|---|---|---|
| 120 s | 175 | 65 | 0 | 0.729 |
| 180 s | 180 | 60 | 0 | 0.750 |
| 300 s | 150 | 90 | 0 | 0.625 |
| 600 s | 125 | 115 | 0 | 0.521 |
| 900 s | **0** | 223 | 17 | **0.000** |

The mechanism is concrete next-departure times from each person's own departure
instant — not an aggregate frequency term in a utility function. At a 900 s
headway SF collapses to zero share and 17 travellers give up and walk.

## Stranded travellers are reported, and a naive parser drops them

A person who never completes still gets a `<personinfo>`, with
`duration="-1"`. The leg they were stuck on carries `vehicle="NULL" depart="-1"
duration="-1"` **but a real, non-negative `waitingTime`** (observed up to
1442 s). A parser that treats `duration="-1"` as a zero-duration completion will
silently count these as free trips.

On a reference run, 974 persons produced **937 complete and 37 stranded at a
stop**. That is small in count and large in consequence: see
[[transit-network-design-and-frequency-setting]], where completed-only versus
censored-inclusive accounting **reversed which service plan won**. Always report
both, charging still-travelling passengers their realised stages as a lower
bound.

Teleports are a separate censoring channel — read `summary@teleports` at the last
step (it is cumulative, never sum it) and check per
[[teleport-artifacts-and-gridlock-resolution-validity]]. In the reference study
teleports were confined to background cars (23 of 448 runs, 1-9 each, max 0.08%
of vehicles) and never touched a bus or a person.

## A generous `until=` timetable silently erases traffic delay

SUMO departs a stop at `max(arrival + duration, until)`. So a published timetable
with any slack turns every transit vehicle into a **schedule-adherent** vehicle,
and congestion stops showing up in its measured round-trip cycle time.

Verified: a timetable built from a guessed 7.2 m/s bus speed produced a measured
cycle of **1216 s with 10,827 background cars and 1216 s with none** —
bit-identical. Rebuilding the timetable from an *uncongested buses-only* run
(measured 9.1-10.1 m/s per line) gave **1010 s uncongested vs 1169 s congested,
+15.7%**, with per-line inflation of 12.1-21.2%.

This is the same family of trap as `simulate-multimodal-transit`'s "a `<stop>`
with only `duration=` is not a schedule", from the other direction: `duration=`
alone gives no schedule at all, while a loose `until=` gives one so strong it
overrides traffic. Assert that congested and uncongested cycle times *differ*
before believing any congestion-related transit result.

### The a-priori plan is optimistic, and travellers do not re-plan

Because the timetable is calibrated on uncongested speeds, duarouter's plan is
systematically ahead of reality. Realised boarding lagged planned boarding by a
mean of **49.6-54.3 s** (median 30.5-41.0 s, p90 175-233 s) across three service
plans, with **71-78% of riders boarding later than planned**.

But the *number* of ride legs matched the plan **100% of the time**. Persons in
SUMO do not re-plan mid-trip when their connection degrades — they simply wait
longer, and 0.7-2.0% never finish. Do not model a passenger response to
unreliability by expecting the router to reroute them; it will not.
