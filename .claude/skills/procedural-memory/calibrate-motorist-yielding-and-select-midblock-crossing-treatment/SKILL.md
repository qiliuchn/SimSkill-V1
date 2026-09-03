---
name: calibrate-motorist-yielding-and-select-midblock-crossing-treatment
description: Use this skill when the user wants to build a MIDBLOCK pedestrian crossing in SUMO (not at a junction), needs vehicles to actually YIELD to pedestrians at a rate that matches a field target (uncontrolled/RRFB/PHB), wants to compare crossing treatments (uncontrolled marked crosswalk, RRFB, pedestrian hybrid beacon/PHB, full pedestrian signal, refuge island / two-stage crossing, no-crossing diversion), or wants to check whether a MUTCD Section 4F PHB warrant decision agrees with simulated pedestrian/vehicle delay and conflict exposure. Covers how to place a crossing where SUMO wants a plain edge, why SUMO's documented jmIgnoreFoeProb parameter silently does nothing without jmIgnoreFoeSpeed also set, a working TraCI-based yield-rate controller, which PHB signal-head phases SUMO can and cannot represent, and Adams/Tanner gap-acceptance theory as a validity check. Trigger on mentions of midblock crossing, crosswalk, RRFB, rectangular rapid flashing beacon, pedestrian hybrid beacon, HAWK signal, refuge island, two-stage crossing, motorist yielding, gap acceptance, or MUTCD 4F warrant.
---

# Calibrate Motorist Yielding and Select a Midblock Crossing Treatment

**SUMO pedestrians at a `priority="true"` crossing do not do gap acceptance —
they step out regardless of traffic**, and vehicles either always yield
(default) or never (documented `jmIgnoreFoeProb`/`jmIgnoreFoeSpeed` tuned) —
there is no continuum. Every prior pedestrian skill in memory
(`build-pedestrian-crossings-and-phasing`) inherited SUMO's default "always
yield," never questioning it. This skill treats yielding as the calibrated
variable it needs to be, and treats the midblock crossing (not a junction
crossing) as a first-class design object.

## Building a crossing where SUMO wants a plain edge

Put an explicit node at the midblock location on the arterial, then declare
`<crossing node="M" edges="A1 B2" priority="..."/>` in the connections file
and compile with `--walkingareas --crossings.guess false
--sidewalks.guess false` (guessed crossings only appear at junctions).
Verify two ways, not one: from the compiled net (an internal edge
`function="crossing"` with the right `crossingEdges` and length), **and** by
observing pedestrians actually route across it (`36/36` used the crossing
with it present; `36/36` diverted to the nearest signal without it, in the
verified build).

**A netconvert trap that silently breaks the arterial if not fixed:**
netconvert's default signal program at a plain 4-leg node can put the two
arterial through movements in *different* phases — verified by reading the
compiled `tlLogic` directly (link 4 green in phase 1, link 10 green in phase
5). Rewrite the flanking signals as an explicit two-phase program
(arterial/cross split, crosswalk on WALK during the cross phase) and
re-derive link indices from the compiled net every time you rebuild — never
hardcode them.

## The documented yielding parameters: verify before trusting the name

`jmIgnoreFoeProb` and `jmIgnoreFoeSpeed` are the only advertised
junction-model yielding knobs. Verified behavior (`outputs/results/probe_channels.json`):

- With `jmIgnoreFoeSpeed = 0` (the default), **`jmIgnoreFoeProb` has zero
  measurable effect at any value from 0.0 to 1.0** — realised yielding is
  bit-identical to three decimals (0.021 at `priority="false"`, 0.768 at
  `priority="true"`).
- Only once `jmIgnoreFoeSpeed` is also set nonzero (e.g. 3.0) does
  `jmIgnoreFoeProb` move anything, and even then only within a narrow band
  (0.768 → 0.708 across the full probability range at `priority="true"`).
- Net result: **the built-in channel offers exactly two usable operating
  points** — roughly 2% yielding (40.5 s pedestrian delay) or roughly
  71–77% (2.1 s delay) — never the field-documented 10–30% (uncontrolled)
  or 95%+ (PHB) targets.
- `traci.vehicle.setParameter(v, "junctionModel.ignoreFoeProb", ...)`
  raises `does not support junctionModel parameter` at runtime; `strings`
  on the SUMO binary shows only `junctionModel.ignoreIDs` and
  `junctionModel.ignoreTypes` are runtime-settable. `ignoreTypes` needs the
  **vType id**, not the vClass — `"pedestrian"` (the vClass) left yielding
  unchanged; `"ped"` (the vType id used in this build) actually worked.

**Build a real continuum with TraCI instead.** Each vehicle entering a
decision zone with a pedestrian present, for which a comfortable stop is
still kinematically possible (`d >= v²/6 + v + 1`), draws Bernoulli(target
rate); yielders get `setSpeed` refreshed every step toward a comfortable
stop and hold until the crossing has been clear 1.0 s. Two implementation
traps, both fixed and both worth re-checking if you reuse this: (1) a naive
presence test double-counts queued-behind-a-yielder vehicles as fresh
yield events unless queue followers are excluded *continuously*, not just
at zone entry; (2) `slowDown()` alone produces creeping — vehicles crawl
into the crossing at 2–4 m/s and never fully release the pedestrian — use
direct kinematic `setSpeed` toward a real stop instead. Commanded-to-realised
mapping measured directly from trajectories (not assumed): commanded 0.0 →
realised 0.021; 0.2 → 0.200; 0.5 → 0.565; 0.8 → 0.786; 1.0 → 0.992 — close
to linear once the two traps above are fixed.

## Which PHB phases SUMO can and cannot represent

Characterized per signal-head state character in isolation
(`outputs/results/phb_state_char_verification.json`, 120 s per state,
180 s warm-up):

| state | maps to | veh/h through | stop fraction |
|---|---|---|---|
| `O` | dark (off) | 1470 | 0.254 |
| `o` | flashing yellow | 1080 | 0.543 |
| `y` | steady yellow | **0** | 0.998 |
| `r` | steady red + WALK | 0 | 1.000 |
| `s` | **flashing red** | 660 | 0.567 |
| `G` | reference (green) | 2130 | 0.299 |

**Genuinely representable: the flashing-red clearance interval.** SUMO's
stop-then-proceed state character `s` really does make vehicles stop and
then proceed if clear (660 veh/h, 45% of dark throughput) — this is the PHB
phase most likely to be assumed unmodelable, and it isn't.

**Not representable, with evidence, and the direction each bias runs:**

1. No alternating indication exists — `o` and `s` are steady states, so the
   visual flashing itself is lost (behavior is approximated, not the display).
2. Steady yellow (`y`) passes **0 vehicles, stops 99.8%** — SUMO has no
   dilemma-zone "go" decision, so every approach is a hard stop. Real PHBs
   let some vehicles clear on yellow; this **overstates** PHB vehicle delay.
3. A **dark PHB blocks pedestrians entirely** in the natural implementation
   (ped link held `r`), whereas a real dark PHB lets pedestrians cross on a
   natural gap. This **overstates** PHB pedestrian delay at low volume.
4. No pedestrian clearance countdown semantics — only the coarse dark →
   flashing-yellow → steady-yellow → steady-red-with-walk → flashing-red
   sequence.

**How much it matters in a live run** (900 veh/h/dir, 80 ped/h, 1800 s): only
**2 of 917** vehicles crossed the conflict point while a pedestrian was
still on the crossing (0.22%), realised state split dark 1341.5 s / flashing
yellow 84 s / steady yellow 84 s / red-walk 196 s / flashing-red 224 s, 28
calls, 1.29 peds/call. Both leaked encroachments occurred during the
flashing-red state — the one state that is faithfully modelled, which is
itself informative: the approximation is not hiding the risk, it is
concentrated exactly where the real device also carries residual risk.

## Yielding rate, not device identity, drives pedestrian delay

At fixed volume, pedestrian delay is monotone in realised yielding (0.0 →
20.5 s delay, 1.0 → 7.7 s, uncontrolled arm). CRN-paired RRFB-vs-PHB at
matched yielding rate confirms device identity is not the causal variable:
at 300 and 900 veh/h/dir the two are statistically indistinguishable across
the whole RRFB yield range tested (p = 0.20–0.96); at 1200 veh/h/dir RRFB
*beats* PHB by 3.7–5.3 s once its realised yielding reaches ≥0.48 (p ≤
0.003). With the beacon-presence trap above fixed, a properly-tuned RRFB
running at realised 0.70–0.81 (the field-documented band) beat a PHB by
4.5–6.1 s under platooned arrivals (p ≤ 0.03). **Calibrate to a yielding
rate, then pick the cheapest device that reaches it — the device is a means,
not the end.**

## The uncontrolled crossing's volume threshold depends on the arrival process, not just volume

Sweeping 600→3600 major veh/h (`outputs/results/H2_volume_threshold.csv`):
platoon-coordinated arrivals through a synchronized signal pair **never**
explode in the tested range (7.5→9.9 s at 1 lane, LOS B throughout) because
zero-offset coordination guarantees one crossable window per cycle. Poisson
arrivals on a 2-lane cross-section reach LOS F by 1800 veh/h/dir (48–58 s,
81–97% waiting >30 s). Poisson arrivals on 1 lane are **non-monotone** —
13.1 → 23.2 → 17.9 → 14.1 s across 600/1200/1800/2400 veh/h — because the
arterial itself saturates above ~1200 veh/h (time loss 21 → 31 → 135 → 193
s/veh) and congested, broken-up traffic yields more crossing opportunities
than free-flowing traffic at the same volume. **Caveat on the mechanism:**
the run's own `mean_acc_gap` statistic stays roughly flat (16.6–17.4 s)
across this same range rather than rising, so "congestion creates larger
accepted gaps" is not itself the measured cause — the delay reduction is
real and repeatable, but the whole-run accepted-gap average is too coarse
to pin down the exact mechanism; a local approach-speed or platoon-gap
measure taken right at the crossing, not yet collected, would be needed to
confirm it.

## The measured critical gap does not scale with crossing width — and the refuge-island benefit inherits that

Minimum accepted gap measured directly from trajectories
(`outputs/results/adams_vs_simulation.csv`, `H4_refuge_vs_theory.csv`):
**4.2–6.5 s at the 12.8 m (2-lane) full crossing, 6.7–9.5 s at the 6.4 m
(1-lane) full crossing** — the *wider* crossing shows the *smaller* measured
gap, backwards from a nominal-crossing-time model (`τ = L/1.2 + 1` predicts
11.67 s and 6.33 s respectively). Half-crossings (refuge stages) confirm
the same near-invariance: the 3.2 m one-lane stage measures 4.8–7.8 s, the
6.4 m two-lane stage measures 4.1–6.8 s — width is a weak predictor of
accepted gap in SUMO's pedestrian model.

Because of this, the two-independent-gaps refuge-island theory (predicted
benefit +3.7/+12.7/+34.5/+87.4 s, rising with volume) only holds at
low-to-moderate Poisson volume (+10.2 s observed at 1200 veh/h/dir total,
within ~20% of the +12.7 s prediction) and then **reverses sign**, reaching
−33.5 s at 2400 veh/h/dir total. Under platooned arrivals it is negative
at every volume tested (−3.5 to −19.9 s, all p ≤ 0.003). Mechanism,
verified from trajectories: SUMO's pedestrian crosses stage 1 at the first
adequate near-direction gap **without checking the far direction**, then
gets marooned mid-refuge — combined with the gap not scaling down with the
shorter half-crossing distance, the intended benefit never fully
materializes at volume. The refuge also raises pedestrian-vehicle conflict
exposure (PET<2s) in **every one of the 16 demand/yielding cells tested,
p<0.05 in all 16 and p≤0.001 in 11 of 16**, by +0.36 to +1.14 events per
pedestrian — it is the worst-performing arm on safety in every condition
tested, not just some.

## PHB vehicle cost is sublinear in pedestrian volume; a full pretimed signal's is flat, not linear

Sweeping pedestrian volume 10→150/h at fixed 900 veh/h/dir
(`outputs/results/H3_pedvolume_scaling.csv`, `H3b_loglog_slopes.csv`):
PHB vehicle delay log-log slope is **0.261** (21.4 → 44.5 s/veh, ×2.08 for
a ×15 pedestrian-volume increase) — genuinely sublinear, driven by call
consolidation (peds/call rises 1.00 → 1.48 as the 20 s minimum recurrence
interval binds). A **full pedestrian signal's vehicle-delay slope is
0.001** — essentially flat (30.4 → 30.5 s/veh) — because its pedestrian
phase runs on recall every cycle regardless of demand: a fixed toll, not a
cost that scales with pedestrians at all. Consequence: a crossover near
70–80 ped/h below which the PHB is cheaper for vehicles and above which
the flat-cost pretimed signal is; the PHB beats the full signal on
pedestrian delay at every volume tested (10.3–14.7 s vs 22.4–28.1 s).

## Delay-induced risk-taking reverses sign with the arrival process — check both directions

Within-cell correlation of pedestrian delay against the minimum accepted
gap (volume held fixed, only yielding varied,
`outputs/results/H5_within_cell.csv`): under **Poisson** arrivals, longer
waits genuinely predict shorter accepted gaps (r = −0.70 to −0.78, p <
1e-6) — the expected "impatience" story. Under **platooned** arrivals the
sign **reverses** (r = +0.35 to +0.44, p ≤ 0.029) — a long wait there means
the pedestrian rode out a platoon and then crossed in the very large
inter-platoon gap that follows, not that they got impatient. The
conflict-exposure half of the story (delay vs. PET<2s) stays positive in
both regimes. Report both halves of an asymmetric delay/risk claim — the
convenient (Poisson) half alone would have been actively wrong for
platooned demand.

## A safety-metric trap: naive TTC mis-ranks a signalized crossing as the most dangerous

At one tested cell (Poisson arrivals, 600 veh/h/dir — the pattern direction
holds across all 8 demand/arrival-process cells tested, see
`outputs/results/safety_encounter_level.csv`): the **full pedestrian
signal** scores *highest* of any real crossing treatment on naive
encounter-level TTC<1.5s (0.504 events/pedestrian) while scoring
near-lowest on PET<2s (0.005) — refuge scores 0.005 on the TTC measure
(near-safest) while scoring worst by nearly two orders of magnitude on PET
(1.370). **Naive TTC = distance/speed to the conflict point flags a
vehicle approaching a red light at speed as an imminent collision even
though it is decelerating to a stop** — this is a measurement artifact, not
a real safety signal. Use PET or encroachment rate (fraction of crossings
with a vehicle physically present in the conflict zone while a pedestrian
occupies it) to rank crossing treatments; a distance/speed TTC computed
without accounting for commanded deceleration will systematically
penalize signal-controlled crossings.

## The MUTCD Section 4F PHB warrant is systematically conservative here, not aligned

Comparing MUTCD's digitized warrant boundary (400/110/28 ped/h required at
600/1200/1800 major veh/h for a 21 ft crosswalk) against a CRN-paired
PHB-vs-uncontrolled benefit test
(`outputs/results/warrant_boundary_comparison.csv`,
`decision_rule.csv/json`): simulated pedestrian-delay benefit is already
significant at the **lowest tested volume (15 ped/h)** at every major-road
volume checked (≥26.7×, ≥7.3×, ≥1.9× the reduction needed to matter, at
600/1200/1800 veh/h respectively) — the true benefit boundary is ≤15 ped/h
and was not resolved below that floor. A least-intrusive-device decision
rule (cheapest device meeting mean delay ≤30 s, share >30 s ≤0.20, and
PET no worse than baseline) agrees with the MUTCD warrant in 20 of 32
tested cells; in the other 12, MUTCD warrants a PHB where a lesser device
(uncontrolled or RRFB) already satisfies every criterion — **zero cells
ran the other direction**. The disagreement is entirely one-directional:
MUTCD 4F over-warrants relative to simulated pedestrian-delay benefit in
this testbed, never under-warrants.

**This reverses under platooned arrivals, and the reversal matters more
than the headline number**: at a coordinated-signal arterial, a PHB can
make pedestrian delay *worse*, not better (+0.4 to +7.1 s at the 21 ft
crosswalk), because the coordinated signals already hand the uncontrolled
crossing a free gap every cycle — installing a PHB there forces pedestrians
to wait for its own actuation cycle instead. Any residual "benefit" in
that condition is a *vehicle*-delay benefit (arterial time loss falls up
to 65.9 s/veh), not a pedestrian-service one; do not read it as
vindicating the warrant.

## Gotchas

- **`priority="true"` crossings skip gap acceptance entirely** — pedestrians
  step out unconditionally. Use `priority="false"` if you want SUMO
  pedestrians to make a real accept/reject decision against traffic.
- **`min_acc_gap` computed from the merged passage stream is not comparable
  across lane counts** — more lanes means more merged passages means
  shorter apparent gaps, independent of any real behavior change. Compare
  only within a fixed lane count.
- **A path reused across parallel batch workers silently corrupts output.**
  63 of 2310 runs in this episode errored from exactly this — a shared
  tripinfo path across five parallel RRFB-yield-target runs. Put every
  swept parameter into the run id used for output paths, not just the
  logical run name.
- **A calibrated yield-rate treatment can look identical to the default
  even at extreme parameter values** if you calibrate the wrong channel —
  verify realised yielding from raw trajectories every time, never trust a
  documented parameter name at face value.

See `build-pedestrian-crossings-and-phasing` for junction-crossing
construction and phasing that this skill's midblock crossing extends,
`conduct-driveway-signal-warrant-traffic-impact-analysis` for the
warrant-met-vs-benefit-measured framing this reuses for MUTCD 4F, and
`analyze-intersection-safety-with-ssm` for why the SSM device itself
(no pedestrian mode) was not used for the safety comparisons here.
