---
summary: A planned freeway lane closure in SUMO can be expressed three ways - a rerouter closingLaneReroute, a disallow permission edit, or a rebuilt geometric lane drop - and the first two are verifiably the SAME runtime mechanism, while only the rebuilt geometry can express merge discipline at all. Work-zone queue-discharge capacity measured against the HCM 1600 pc/h/ln reference falls 16% (1 lane closed) to 39% (2 lanes closed) below the same segment's unobstructed per-lane capacity, with the forced merge itself accounting for a growing share of the deficit.
keywords:
  - work zone
  - lane closure
  - work-zone capacity
  - HCM 1600 pc/h/ln
  - closingLaneReroute
  - lane permissions
  - geometric lane drop
  - taper
  - advance warning area
  - early merge
  - late merge
  - zipper merge
  - dynamic late merge
  - merge control
  - diversion compliance
  - detour saturation
  - road-user cost
  - closure scheduling
created: 2026-08-04T04:00:00
last_updated: 2026-08-05T21:00:00
sources:
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/REPRESENTATION.md]]"
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/CAPACITY.md]]"
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/CONTROL.md]]"
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/DIVERSION.md]]"
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/SCHEDULE.md]]"
  - "[[episodic-memory/2026-08-04_04-00-00/outputs/tables/DISCRETIZATION_DECISION.md]]"
  - https://sumo.dlr.de/docs/Simulation/Rerouter.html
related_pages:
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]"
  - "[[sumo-time-discretization]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-output-files]]"
  - "[[one-lane-two-way-alternating-flow-and-shared-lane-representation]]"
related_skills:
  - design-and-control-freeway-work-zone-lane-closures
  - compare-zipper-vs-default-merge-at-lane-drop
  - simulate-incident-rerouting
  - implement-variable-speed-limits
  - implement-coordinated-corridor-ramp-metering
  - choose-time-discretization-and-integration-method
  - control-one-lane-two-way-alternating-flow-through-a-work-zone
related_skills_for_graph_view:
  - "[[design-and-control-freeway-work-zone-lane-closures]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[simulate-incident-rerouting]]"
  - "[[implement-variable-speed-limits]]"
  - "[[implement-coordinated-corridor-ramp-metering]]"
  - "[[choose-time-discretization-and-integration-method]]"
  - "[[control-one-lane-two-way-alternating-flow-through-a-work-zone]]"
---

# Freeway Work-Zone Capacity, Closure Representation and Merge Control

Measured on a hand-authored 9.5 km 3-lane directional freeway with a full MUTCD-style
work zone (advance-warning / taper / activity / termination areas), an off-ramp/on-ramp
pair feeding a parallel signalised arterial detour, and a time-varying peak. All numbers
at **(step-length 0.5 s, ballistic, `actionStepLength` 1.0 s)** unless stated.

## The three closure representations are not three models

| | how the closure is expressed | visible in the compiled net |
|---|---|---|
| R1 | `<rerouter>` + `<closingLaneReroute id="fE_0" disallow="all"/>` | no |
| R2 | `disallow="all"` written onto the lane in the compiled `.net.xml` | yes |
| R3 | `netconvert` rebuild: the activity-area edge has fewer lanes | yes |

**R1 and R2 are the same mechanism.** SUMO implements `closingLaneReroute` as a *runtime
mutation of the lane's permissions*: queried live mid-interval, `fE_0` reported all 33
vClasses disallowed while the adjacent `fE_1` reported none. The two representations then
produced **bit-identical** outcomes on all four CRN seeds — work-zone capacity, mean trip
duration and hard-braking counts every one exactly equal (paired difference `+0.0`,
p = 1.0). Choose between them for bookkeeping reasons (R1 is time-windowed and
self-documenting, R2 survives static inspection), never expecting different behaviour.

`traci.lane.getAllowed` returns an **empty list to mean "all vClasses permitted"**, so it
cannot distinguish "everything allowed" from "nothing allowed" — read `getDisallowed`.

**All three agree on capacity, and that is not the point.** R1/R2 measured
1562 pc/h/ln and R3-priority 1578 (paired difference −15.3 [−39.3, +8.6], p = 0.13, n.s.).
The reason to rebuild the geometry for a long-term closure is **structural**: R1 and R2
keep a 3-lane→3-lane connection set, so there is no contested downstream lane and
`type="zipper"` on the drop node has nothing to act on. Only the rebuilt net produces the
`ZZM` connection-state signature. And that matters behaviourally: switching the drop node
from `priority` to `zipper` on the *same* rebuilt geometry cut near-taper hard-braking
events from 777 to 314 (**−60 %**) at statistically equal capacity.

### The merge-position profile is what actually separates them

Share of vehicles observed in the closing lane at each E2 station along the corridor:

| distance (m) | R1/R2 | R3 priority | R3 zipper |
|---:|---:|---:|---:|
| 200 | 0.291 | 0.291 | 0.310 |
| 1700 | 0.162 | 0.167 | 0.293 |
| 3200 | 0.121 | 0.122 | 0.318 |
| 4600 (taper) | 0.095 | 0.092 | 0.303 |

R1/R2/R3-priority drain the closing lane gradually over ~4.5 km — SUMO's strategic
lane-change lookahead spreads the merge across kilometres. **R3-zipper holds ~0.30 all the
way to the taper: a late merge, produced by the junction type alone, with no controller.**
An aggregate capacity table hides this entire difference.

## Work-zone capacity vs the HCM reference

Definition used throughout: mean flow over queued 60 s intervals at an E1 station 15 m
before the end of the activity area, per **open** lane, excluding the first 300 s after
queue onset. 100 % passenger cars, so veh/h/ln == pc/h/ln and HCM's ~1600 pc/h/ln freeway
work-zone value needs no PCE conversion.

**A flat overloaded demand does not measure capacity in SUMO — it measures insertion.**
Loading 8400 veh/h into the 3-lane corridor inserted only 4650 of 8447 vehicles, and the
upstream and downstream stations both read ~4100 veh/h: the corridor was running at
SUMO's insertion throughput (~1370 veh/h/ln at `departSpeed="max"`). The fix is to build
the queue physically and release it — park blocker vehicles across every lane downstream
for ~900 s, remove them, and measure discharge from release + 120 s (raise
`--time-to-teleport` above the blockage or the probe manufactures its own teleports).

Queue-build-and-release probe, identical segment:

| configuration | capacity (pc/h/open-lane) | vs unobstructed | vs HCM 1600 |
|---|---:|---:|---:|
| 3 lanes, 120 km/h (unobstructed) | **1826** [1811, 1840] | — | +14.1 % |
| 3 lanes, 80 km/h (speed only) | 1717 [1707, 1727] | −5.9 % | +7.3 % |
| 1 lane closed, 2 open, 80 km/h | 1599 [1590, 1608] | −12.4 % | −0.1 % |
| 2 lanes closed, 1 open, 80 km/h | 1274 [1017, 1532] | −30.2 % | −20.3 % |

**H1 holds, and decomposes.** Naturally-formed work-zone queue discharge was
**1534 pc/h/open-lane** at one lane closed (−16.0 % vs unobstructed, −4.1 % vs HCM 1600)
and **1108** at two (−39.3 %, −30.7 %). Comparing each against the *same segment's* own
release-probe capacity separates the roadway from the merge:

- 1 lane closed: 1599 − 1534 = **65 pc/h/ln (4.1 %) is the forced merge**;
- 2 lanes closed: 1274 − 1108 = **166 pc/h/ln (13.0 %) is the forced merge**.

So the deficit grows with lanes closed *and* the merge's own share of it grows — the
merge, not the roadway, is what a second closed lane really costs. The one-lane-closed
number lands almost exactly on HCM's 1600 pc/h/ln; the two-lane-closed number is 20 %
below it, so **the single HCM value should not be applied across lane configurations.**

### Taper length and advance-warning distance barely matter (H5)

At one lane closed, marginal means across a 3x3 factorial were 1533 / 1537 / 1526 pc/h/ln
for tapers of 80 / 200 / 500 m and 1532 / 1534 / 1530 for advance warning of
500 / 1500 / 3000 m — all inside each other's confidence intervals. **H5 is not supported
for capacity**: in SUMO these are geometry parameters that change *where* vehicles merge,
not *how many* can. (They do change queue location and therefore where delay is stored.)
At two lanes closed the taper effect was larger and non-monotone (1076 / 1108 / 983 for
80 / 200 / 500 m), i.e. a *longer* taper measured worse — treat with caution, this cell
also carried the study's only material teleport count.

### Posted work-zone speed costs throughput (H6)

Capacity rose monotonically with the posted work-zone speed: 1428 / 1498 / 1534 / 1573 /
1590 pc/h/ln at 50 / 65 / 80 / 95 / 110 km/h. OLS slope **+26.6 veh/h/lane per +10 km/h**
(R² = 0.950). **A 10 km/h speed reduction costs ~27 veh/h/lane, about 1.7 % of capacity —
the reduction does not protect throughput, it buys safety with throughput.** The effect is
real but an order of magnitude smaller than closing a lane.

## Merge control: static early merge wins, dynamic does not

Five arms plus a negative control on identical CRN demand and seeds; headline metric is
TSTT including the origin-insertion integral (early/dynamic merge hold vehicles *out* of
the network — 43.0 and 41.5 origin veh-h at 4000 veh/h against 8.0 for do-nothing — so an
in-network-only metric would flatter them).

Lowest-TSTT arm by demand, one lane closed (work-zone capacity ≈ 3068 veh/h):

| peak demand | v/c | best arm |
|---:|---:|---|
| 2400 | 0.78 | late (margin 3.1 veh-h) |
| 2800 | 0.91 | late (margin 2.6 veh-h) |
| 3200 | 1.04 | do-nothing (margin 1.4 veh-h) |
| 3600 | 1.17 | **early** (margin 41.3 over dynamic) |
| 4000 | 1.30 | **early** (margin 50.4) |
| 4400 | 1.43 | **early** (margin 34.9) |

**H2 is rejected.** There is no demand band in which dynamic late merge beats both
statics. It beat do-nothing at every oversaturated level (−28.7 to −37.9 veh-h) and tied
or beat static late merge, but **lost to static early merge at every oversaturated level**
(+41.3, +50.4, +38.5 veh-h, all p < 0.02). Late merge is the right strategy only while the
work zone is undersaturated, where its advantage is tiny.

### The detector-placement error that manufactured the opposite answer

The natural place for the controller's detector — just upstream of the taper — is
**downstream of the early-merge bottleneck**. With early merge active it read 7-11 %
occupancy where do-nothing at identical demand read 30-39 %. A controller that starts in
EARLY mode is then blind to its own queue: it **never switched once in 180 runs**, silently
degenerating into static early merge, and that broken version *appeared to beat both
statics at the highest demand*. Moving the station upstream of every candidate merge point
made it read 29.0 vs 32.9 % across the two modes at equal demand; the fixed controller
then switched 3-4 times per run (28-74 % of time in LATE) — and **reversed the finding**.
This is the same failure mode
[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]] records for ramp metering:
a controller-configuration error masquerading as a result.

Calibrate the hysteresis band from no-control runs at the chosen station: free-flow
demands never exceeded 10 % occupancy there and congested ones reached 29-48 %, so an
18 % ON / 9 % OFF band is comfortably separated.

### VSL adds nothing here

The VSL arm was byte-identical to do-nothing at undersaturated demand (it never
activated) and slightly worse once it did — consistent with
[[variable-speed-limits-and-e2-detectors]]: with no genuine capacity drop to recover, a
controller that meters inflow can only subtract flow.

## The capacity-safety exchange at the taper (H3)

CRN-paired late-minus-early at one lane closed: late merge **lost** capacity
(−34 to −80 pc/h/ln, all p < 0.001) *and* raised near-taper hard-braking events
(+112 to +216, all p ≤ 0.001). **There is no exchange rate to quote, because late merge
was not a throughput win in the first place** — it is dominated on both axes in this
topology. That extends `compare-zipper-vs-default-merge-at-lane-drop`'s finding (zipper
reduced discharge at a saturated 2→1 drop) rather than contradicting it: the
throughput-vs-safety trade that late merge is usually sold on does not appear, and what
appears instead is that the *junction type* (zipper vs priority) buys the safety while the
*merge-point policy* (early vs late) buys the throughput, and they are separable.

SUMO registered **zero collisions in every run of the study** (`--collision-output` empty
and `summary`'s `collisions` attribute zero throughout), so all safety conclusions rest on
surrogate measures.

## Diversion: the optimum compliance share is strictly below 100 % (H4)

TSTT vs VMS/detour compliance share phi is an **inverted U only when the freeway is
genuinely oversaturated**:

| peak demand | phi* | TSTT at phi=0 | at phi* | at phi=1 |
|---:|---:|---:|---:|---:|
| 3200 (v/c 1.04) | **0.00** | 326.4 | 326.4 | 1735.8 |
| 4000 (v/c 1.30) | **0.20** | 843.0 | **490.6** | 2377.9 |

**H4 is confirmed at oversaturation and refuted below it.** The mechanism is directly
observable and is the same delay transfer as ramp metering: the arterial's discharge
saturates at ~1500-1680 veh/h, so past phi ≈ 0.3 sending *more* traffic delivers *less*
(1678 vehicles offered to the detour vs 1513 delivered at phi = 0.6; 1273 offered vs 1167
delivered at phi = 1.0), and the surplus lands in the origin-insertion term, which grows
from 0 to **1499 veh-h** at phi = 1. **Size a diversion recommendation to the detour's
saturation flow, not to the freeway's deficit.**

## Scheduling: partial vs full closure

Road-user cost against a matched no-work-zone reference, VOT 20/veh-h, fuel 1.80/L,
carbon 0.10/kg, fuel and CO2 from HBEFA3 `edgeData type="emissions"`.

**Full closure with mandatory detour was never cheaper per closure-hour, at any demand
tested (600-3600 veh/h)** — this corridor's detour carries a large free-flow penalty
(6.0 km of 60 km/h signalised arterial vs 5.5 km of 120 km/h freeway) that every diverted
vehicle pays even when the arterial is empty. The scheduling decision therefore turns on
**duration compression** `k` = partial-closure project duration / full-closure duration:
full closure is justified when `k > RUC_full / RUC_partial`. That break-even is U-shaped
in demand — **7.8x at 3600 veh/h and 9.8x at 600 veh/h, but 40-41x through the 2200-3000
veh/h middle** — because at low demand the partial closure costs almost nothing to keep
open, and at high demand it starts queueing badly itself. **Night full closures are
defensible at roughly a 10x work-rate advantage; mid-demand full closures need an
implausible 40x.**

## Practical contract

1. Rebuild the geometry (R3) for a long-term closure; it is the only representation that
   can express merge discipline. Use R1/R2 for time-windowed or scripted closures, knowing
   they are the same mechanism as each other.
2. Verify every geometry variant from the **compiled** net — lane counts, lengths, speeds,
   permissions, and the `fD->fE` connection states.
3. Measure capacity by queue discharge with a physically-built queue, never by flat
   overload; report the release-probe segment capacity alongside it so the merge's own
   contribution is visible.
4. Use `dt <= 0.5 s`: work-zone capacity is a gap-acceptance metric and is dt-fragile even
   though [[sumo-time-discretization]]'s stored table puts capacity in the dt-robust class.
5. Place a merge controller's detector upstream of **every** candidate merge point, and
   calibrate its thresholds from no-control runs at that same station.
6. Report TSTT with the origin-insertion integral, plus
   loaded/inserted/completed/still-running.
