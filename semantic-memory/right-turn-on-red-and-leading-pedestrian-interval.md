---
summary: SUMO's 's' signal state ("green right-turn arrow requires stopping") is the only faithful representation of right-turn-on-red, and is valid on any traffic_light junction despite the documentation saying it is "only generated for" traffic_light_right_on_red. A verified 2x2 factorial plus a shared-lane replication found RTOR roughly 2.4x's right-turn capacity (56 % of the gain surviving a shared through+right lane), a 5 s leading pedestrian interval gives back only 1.7 % of that gain and charges it to the through movement rather than the right turn, and banning RTOR increased rather than reduced measured pedestrian encroachment.
keywords:
  - right-turn-on-red
  - RTOR
  - no-turn-on-red
  - leading-pedestrian-interval
  - LPI
  - s-signal-state
  - traffic_light_right_on_red
  - exclusive-right-turn-lane
  - shared-through-right-lane
  - pedestrian-encroachment
  - right-turn-capacity
  - HCM-RTOR-credit
created: 2026-08-04T15:00:00
last_updated: 2026-08-07T05:39:34
sources:
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/RESULTS_TABLES.md]]"
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/ENCROACHMENT_TABLE.md]]"
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/per_cell_metrics.json]]"
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/sprobe/s_state_probe.json]]"
  - "[[episodic-memory/2026-08-04_15-00-00/outputs/calibration/capacity_vs_ped.json]]"
  - https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html
related_pages:
  - "[[pedestrian-crossings-and-signal-phasing]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[surrogate-safety-measures]]"
  - "[[webster-method]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
  - "[[protected-bicycle-intersection-design-and-right-hook-mechanics]]"
  - "[[actuated-traffic-signals]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
related_skills:
  - evaluate-right-turn-on-red-and-leading-pedestrian-interval
  - build-pedestrian-crossings-and-phasing
  - compare-left-turn-signal-treatments
  - measure-saturation-flow-and-validate-webster-method
  - analyze-intersection-safety-with-ssm
  - create-single-intersection
  - evaluate-protected-bicycle-intersection-design
related_skills_for_graph_view:
  - "[[evaluate-right-turn-on-red-and-leading-pedestrian-interval]]"
  - "[[build-pedestrian-crossings-and-phasing]]"
  - "[[compare-left-turn-signal-treatments]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[create-single-intersection]]"
  - "[[evaluate-protected-bicycle-intersection-design]]"
---

# Right-Turn-on-Red and the Leading Pedestrian Interval

Right-turn control is the third turn-treatment axis in this memory, alongside
[[left-turn-treatment-tradeoffs]] (permissive / protected / protected-permissive lefts) and
[[pedestrian-crossings-and-signal-phasing]] (exclusive vs concurrent pedestrian phases). Its two
levers are **right-turn-on-red (RTOR) permission** and the **leading pedestrian interval (LPI)**,
and unlike the left-turn case they pull on *different* objectives — capacity and pedestrian
exposure — at exchange rates that differ by two orders of magnitude.

## `s` is the RTOR state, and the documentation's scope note is about the generator

SUMO's traffic-light state alphabet has a character for exactly this manoeuvre:

> **`s`** — "green right-turn arrow" requires stopping — vehicles may pass the junction if no
> vehicle uses a higher priorised foe stream. They always stop before passing. This is only
> generated for junction type `traffic_light_right_on_red`.

**"Only generated for" constrains netconvert's automatic generator, not the validity of the
character.** Verified on SUMO 1.27.1: `s` hand-written into an additional-file `<tlLogic>` on an
ordinary `type="traffic_light"` junction loads, round-trips byte-identically through
`traci.trafficlight.getAllProgramLogics` (12/12 probe runs), and produces the documented behaviour.
Across the 12 probe runs SUMO emitted 259 warning lines — every one an emergency-braking or
pedestrian-jam warning, **none** mentioning the signal state, the tlLogic or the junction type.

### `s` versus `r` versus `g`, measured

A `{r, s, g} × {conflicting through traffic on/off} × {pedestrians on/off}` factorial on one fixed
4-leg geometry, 0.1 s step, right turn saturated at 1200 veh/h/approach, identical phase
boundaries — only the character at the right-turn link indices changed. On-red volume summed over
four approaches:

| red-state char | no conflicts, no peds | + conflicting traffic | + pedestrians | both | full-stop fraction | stop-line speed |
|---|---:|---:|---:|---:|---:|---:|
| `r` | 0 | 0 | 0 | 0 | — | — |
| `s` | 2592 | 1920 (−25.9 %) | 1830 (−29.4 %) | 1524 (−41.2 %) | **1.000** | 2.17–2.28 m/s |
| `g` | 3264 | 2382 | 3114 | 1968 | 0.000–0.329 | 5.59–7.22 m/s |

Three things follow:

1. **`r` is a genuine ban** — exactly zero vehicles cross on red in any condition.
2. **`s` yields to both foe classes.** Its on-red volume falls 26 % when conflicting vehicle
   traffic is switched on and 29 % when pedestrians are switched on. It is a real
   permissive-with-stop state, not a disguised protected green.
3. **`g` is not a substitute for `s`.** With identical geometry and demand, `g` passes 26 % more
   vehicles on red and does it at a **0.000 full-stop fraction** against `s`'s 1.000 — the
   mandatory stop is the entire difference, and it is the safety-relevant part of the manoeuvre.

Inside the main 120-run experiment the same signature holds with confidence intervals: minimum
approach speed in the last 15 m under `s` was 0.022 ± 0.001 m/s and the **full-stop fraction was
1.000 ± 0.000 in every cell and both demand regimes** — the stop is structural, not statistical.

**Classify RTOR volume by PHASE, not by state character, whenever a `g`-on-red arm is in the
comparison.** Under a `g` program the character is the same on red and on green, so a
character-based classifier reports zero on-red volume for a purely definitional reason. That
degeneracy is precisely why SUMO needs a distinct `s`.

## An upstream stop-bar detector cannot count turns on red

This is the measurement trap of the whole topic. An `inductionLoop` 2 m upstream of the stop line
agrees on total right-turn volume but mis-labels a large share of RTOR vehicles, because **a
vehicle held at the stop line has already passed every upstream detector**. The loop times the
*arrival* at the line; the RTOR event is the *departure* from it, and the gap between them is the
RTOR waiting time — which can straddle a phase change.

The instrument that works is an `instantInductionLoop` **on the right turn's own internal `via`
lane** (`pos="1.0"`), classified by an analytic reconstruction of the phase table. Verified against
a TraCI reading of the state at the step the vehicle's front enters that internal lane: the two
agree to within 0.5 vehicles per run on both the total and the on-red count, across all 120 runs,
with the analytic reconstruction matching `getRedYellowGreenState` at **every single step**
(0 mismatches). The residual per-vehicle disagreements are vehicles crossing within one time step
of a phase boundary.

Any RTOR study must also report the count of right-turn crossings on a plain `r` — red-light
running. It was **0.00 in every one of the 120 runs**; a non-zero value means the NTOR
representation is wrong.

## Permitted right-turn capacity is set by pedestrians, not by green time

Before choosing any demand level, measure the capacity. Right-turn movement capacity with an
exclusive lane, 30 s green in a 100 s cycle, measured as served volume under deliberate
oversaturation:

| ped/h per crossing | NTOR capacity (veh/h/lane) | RTOR capacity | RTOR gain | on-red component |
|---:|---:|---:|---:|---:|
| 0 | 468 | 885 | +417 (+89 %) | 423 |
| 102 | 305 | 668 | +363 (+119 %) | 380 |
| 201 | 218 | 529 | +311 (+143 %) | 345 |
| 402 | 150 | 422 | +272 (+182 %) | 302 |

**Permitted right-turn capacity collapses by a factor of three as the parallel crossing goes from
empty to 402 ped/h.** A right-turn capacity or an RTOR credit quoted without the conflicting
pedestrian volume attached is meaningless. This also means it is easy to build a degenerate
experiment: at 400 ped/h a 200 veh/h/approach right-turn demand is already oversaturated under
NTOR.

The measured on-green saturation flow for the permitted right turn was **1539 veh/h/lane**
(median discharge headway 2.339 s) — roughly 20 % below the HCM 1900 default and below this
project's own SUMO through-lane measurements of 1791–2000 veh/h/lane
([[hcm-control-delay-vs-sumo-delay-metrics]]), because the movement pays a turn-radius speed
penalty *and* the pedestrian yield. The on-red discharge headway under `s` was **4.556 s**
(≈ 790 veh/h/lane) — close to exactly twice the green headway, which is the signature of the
mandatory stop.

## Verified finding: what RTOR buys, and how much survives a shared lane

4-leg intersection, 100 s pretimed cycle, protected lefts, concurrent pedestrian phasing, ~200
ped/h per crossing, 34.7 % right-turn share, 10 seeds per cell, saturated capacity regime:

| geometry | NTOR capacity | RTOR capacity | gain |
|---|---:|---:|---:|
| exclusive right-turn lane | 883.7 ± 3.9 veh/h | 2154.6 ± 19.1 veh/h | **+1270.9** (+143.8 %) |
| shared through+right lane | 878.2 ± 7.4 veh/h | 1585.7 ± 36.4 veh/h | **+707.5** (+80.6 %) |

**56 % of the RTOR capacity gain survives a shared through+right lane.** The practitioner rule that
"RTOR yields little or nothing without an exclusive turn lane" is directionally right but
overstated — the shared lane loses 44 % of the gain, not all of it. The mechanism is far more
visible in the on-red *share* at operational demand: **65.3 ± 1.1 % of right turns execute on red
with an exclusive lane against 15.8 ± 0.9 % with a shared lane**, because a through vehicle at the
head of the queue blocks the right-turner from ever reaching the stop line during the red.

At operational demand (v/c = 0.78 against the measured NTOR capacity) RTOR cut right-turn control
delay from 70.7 ± 4.9 s to 9.8 ± 0.4 s and intersection-wide control delay from 46.0 ± 2.2 s to
25.4 ± 0.7 s.

## Verified finding: an LPI is nearly free for the right turn, and the through movement pays

A 5 s LPI built by *splitting* the green (5 s all-vehicle-red with the parallel crossings walking,
then 25 s of vehicle green) rather than by adding time — cycle, phase boundaries and the 30 s
pedestrian WALK interval identical to the no-LPI program:

| | RTOR no LPI | RTOR + LPI | NTOR no LPI | NTOR + LPI |
|---|---:|---:|---:|---:|
| right-turn capacity (veh/h) | 2154.6 | 2133.2 (−1.0 %) | 883.7 | 886.7 (+0.3 %, p = 0.19) |
| right-turn control delay (s) | 9.8 | 10.1 (p = 0.32) | 70.7 | 69.1 (p = 0.58) |
| through control delay (s) | 29.9 | 34.8 | 29.1 | 33.3 |
| intersection control delay (s) | 25.4 | 27.9 (p = 1.4e-05) | 46.0 | 47.5 |

**The LPI gives back only 1.7 % of the RTOR capacity gain (21.4 of 1270.9 veh/h), and its cost does
not fall on the right-turn movement at all** — right-turn delay is statistically unchanged while
the through movement absorbs +4.2 to +4.9 s. Under NTOR the LPI is capacity-free outright.

The mechanism is worth remembering because it generalises: **at a concurrent crossing the permitted
right turn is pedestrian-constrained, not green-time constrained.** The first ~5 s of the vehicle
green is exactly when the pedestrian platoon that queued through the red is discharging across the
receiving leg, so the right-turner could not move then anyway. An LPI confiscates precisely the
seconds the right turn was not using. **This result inverts at a low crossing volume**, where the
right turn *is* green-time constrained and an LPI would cost real capacity — do not carry the
"LPI is free" conclusion to a quiet crosswalk.

Pedestrian delay was invariant across all four cells (crossing wait 17.57 ± 0.06 s vs
17.64 ± 0.07 s; walk `timeLoss` 27.67 ± 0.06 s vs 27.82 ± 0.07 s), by construction — which is what
makes the conflict differences attributable to the LPI rather than to a different pedestrian
service rate.

## Verified finding: banning RTOR *increased* measured pedestrian encroachment

SUMO's SSM device has no pedestrian-aware mode ([[surrogate-safety-measures]]), so ped-vehicle
exposure is a TraCI measurement. The gate used here: a right-turning vehicle within 8 m of a
pedestrian on one of *that turn's* foe crossings, with `d/v < 2 s` while the vehicle moves at
`>= 1 m/s`.

**That gate alone is not enough, and getting this wrong reverses the conclusion.** It also fires
for a vehicle still *upstream* of the stop line — creeping in a queue or decelerating — so a
heavily-queued No-Turn-on-Red baseline reports a large "on-red conflict" count for vehicles that
never legally enter anything. Split the measure by whether the vehicle was **past the stop line, on
the turn's internal via lane**, at minimum distance:

| treatment (exclusive lane) | encroachment /h | on-red | on-green |
|---|---:|---:|---:|
| NTOR, no LPI | 368.0 ± 13.4 | 0.0 | 368.0 |
| RTOR, no LPI | 205.6 ± 6.2 | 30.0 ± 5.2 | 175.6 ± 10.5 |
| NTOR + LPI | 20.0 ± 10.5 | 0.0 | 20.0 |
| RTOR + LPI | 107.2 ± 40.3 | 56.0 ± 23.9 | 51.2 ± 16.4 |

**Banning turns on red raised pedestrian encroachment by 79 % (205.6 → 368.0 /h).** The
RTOR-specific hazard is real but small — 30 encroachments/h occur on red, against exactly zero
under NTOR by construction — and it is swamped by what the ban does to the *permitted on-green*
right turn: forcing the whole right-turn demand to discharge inside the 30 s green drives it
straight into the pedestrian platoon. **The dominant pedestrian hazard of a right turn is the
permitted turn on green, not the turn on red.**

What the ban does buy is on the vehicle-vehicle side: SSM right-turn merge conflicts (encounter
types 6/7/8/19, ego a right-turner, foe destined for the same receiving edge) fell from
51.7 ± 4.1 /h to 14.9 ± 2.5 /h (−71 %, p = 2.8e-11) — i.e. of order 35 veh/h of right-turn capacity
surrendered per merge conflict per hour removed.

## Verified finding: the LPI dominates the ban as a pedestrian-safety lever

| lever, from RTOR-no-LPI | encroachment removed /h | capacity surrendered (veh/h) | veh/h per encroachment/h |
|---|---:|---:|---:|
| add a 5 s LPI | +98.4 | 21.4 | **0.22** |
| ban turns on red | −162.4 (exposure rises) | 1270.9 | not defined |
| do both | +185.6 | 1267.9 | 6.83 |

**RTOR + LPI delivers 2133 veh/h at 107 encroachments/h against the conventional
NTOR-without-LPI design's 884 veh/h at 368 encroachments/h — 2.4× the capacity and 71 % less
pedestrian encroachment simultaneously.** NTOR without an LPI is not on the Pareto frontier at all:
NTOR + LPI matches its capacity (887 vs 884 veh/h) at 20 encroachments/h instead of 368. The
practitioner framing of RTOR permission as *the* pedestrian-safety lever is, at this pedestrian
volume and demand mix, aimed at the wrong variable.

One thing the LPI cannot do, and one open question: the LPI acts on the vehicle green, so it
cannot touch the on-red exposure that occurs during the *cross street's* phase. Measured, it cut
the on-green component hard (175.6 → 51.2 /h) while the on-red component moved the other way
(30.0 → 56.0 /h) — but that increase rests on 3 seeds with a ±23.9 interval and should be treated
as **unresolved**, not as a finding.

## The HCM RTOR credit is directionally right and arithmetically optimistic

HCM practice credits the observed RTOR volume against right-turn demand — i.e. treats the on-red
volume as the capacity the manoeuvre adds. Measured:

| geometry | on-red volume | actual capacity gain | over-statement | on-green component, NTOR → RTOR |
|---|---:|---:|---:|---:|
| exclusive lane | 1389.1 veh/h | 1270.9 veh/h | +118.2 (**9.3 %**) | 874.0 → 751.0 (−123.0) |
| shared lane | 733.8 veh/h | 707.5 veh/h | +26.3 (**3.7 %**) | 862.6 → 836.8 (−25.8) |

**Turning on red cannibalises the green.** It removes the standing queue that would otherwise have
discharged at saturation headway when the green came up, so the on-green component *falls* — by
123.0 veh/h with an exclusive lane, which almost exactly accounts for the 118.2 veh/h discrepancy.
The direction of the HCM assumption is supported (RTOR is genuine extra capacity), but the
arithmetic is optimistic, and **the error is not a fixed factor**: 9.3 % vs 3.7 % across two
geometries of the same intersection, and it also moves with the conflicting pedestrian volume.

## Scope

All figures: SUMO 1.27.1, `--step-length 0.5` (0.1 s for the state probe), ballistic integration,
Krauss with `speedFactor="1.0" speedDev="0"`, `--pedestrian.model striping`,
`--time-to-teleport -1` with 0 teleports and 0 collisions in all 120 runs. Control delay uses the
HCM segment convention (250 m upstream to 100 m downstream) against a **measured** per-movement
free-flow datum of 27.0–28.5 s; the geometric datum of 25.20 s would have inflated every delay by
1.8–3.3 s ([[hcm-control-delay-vs-sumo-delay-metrics]]). Operational demand sat at v/c = 0.78
against the measured NTOR capacity, below the capacity knee where
[[sumo-stochastic-variability-and-replication-design]] found few-seed comparisons unreliable. SSM
counts are ordinal, not cardinal ([[surrogate-safety-measures]]). The encroachment figures come
from 3 supplementary seeds per cell carrying the extended instrument; every other figure from 10.
The shared-lane variant is oversaturated under NTOR at the common operational demand (right-turn
control delay 269 s) — which is why every capacity claim comes from the separate saturated regime.

See the `evaluate-right-turn-on-red-and-leading-pedestrian-interval` skill for the full
build/verify/measure workflow and the bundled scripts.
