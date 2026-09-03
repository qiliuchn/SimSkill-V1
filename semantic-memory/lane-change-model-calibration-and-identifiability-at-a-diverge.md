---
summary: A Morris-screen -> optimise -> validate pipeline for SUMO's LC2013 lane-changing parameters on a freeway off-ramp diverge found the defaults reproduce per-lane flow shares (max GEH 1.65) and throughput but place the last mandatory lane change 6.2x too far upstream (85th-percentile 2464 m vs a 400 m target, while the median is fine at 297 m); aggregate lane counts and the --lanechange-output event stream identify disjoint parameter sets (lcKeepRight/lcSpeedGain are equifinal on counts but 3.5x apart in LC rate; lcStrategic is invisible in lane flows below its default and visible above it), lcAssertive is the most influential parameter of the eight, lcStrategic=0 does not disable strategic changing (only negative does), a missed exit is a mainline blockage followed by a teleport onto the ramp, and LC2013 cannot run under the sublane model at all.
keywords:
  - lane-change-calibration
  - LC2013
  - lcStrategic
  - lcKeepRight
  - lcSpeedGain
  - lcAssertive
  - lanechange-output
  - freeway-diverge
  - mandatory-lane-change
  - identifiability
created: 2026-08-05T12:40:00
last_updated: 2026-08-06T08:00:00
sources:
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/LC2013_INFLUENCE_MAP.md]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/LC_REASON_BREAKDOWN.md]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/PER_LANE_FLOW_BEFORE_AFTER.md]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/tables/final_scorecard.json]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/tables/identifiability.json]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/tables/traps.json]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/tables/strategic_lookahead.json]]"
  - "[[episodic-memory/2026-08-05_08-00-00/outputs/tables/minimal_shape_verification.json]]"
related_pages:
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[freeway-weaving-segment-turbulence]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[sublane-model-and-lane-filtering]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[system-interchange-weaving-and-design-selection]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[geh-statistic]]"
  - "[[sumo-output-files]]"
  - "[[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]"
related_skills:
  - calibrate-lane-changing-parameters-at-a-freeway-diverge
  - calibrate-car-following-parameters-against-field-targets
  - model-freeway-weaving-segment
  - quantify-sumo-run-to-run-variability
  - simulate-motorcycle-lane-filtering-with-sublane-model
  - screen-and-decompose-sumo-parameter-sensitivity
related_skills_for_graph_view:
  - "[[calibrate-lane-changing-parameters-at-a-freeway-diverge]]"
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[model-freeway-weaving-segment]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[simulate-motorcycle-lane-filtering-with-sublane-model]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
---

# Lane-Change Model Calibration and Identifiability at a Diverge

[[car-following-parameter-calibration-and-identifiability]] treated SUMO's car-following
parameter vector as the object of study and found it not uniquely identified from
macroscopic data. This page does the same for the **lane-changing** vector — LC2013's
`lcStrategic`, `lcCooperative`, `lcSpeedGain`, `lcKeepRight`, `lcAssertive`,
`lcLookaheadLeft`, `lcSpeedGainRight` plus the `--lanechange.duration` setting — on a
facility where lane changing is the whole physics: a 3-lane 120 km/h freeway with a single
off-ramp fed by a 300 m deceleration lane, so that exiting is a genuine mandatory
(strategic) lane change. Full protocol and reusable machinery:
`calibrate-lane-changing-parameters-at-a-freeway-diverge`.

All figures below are from SUMO 1.27.1 at `--step-length 0.5 --step-method.ballistic`,
1600 veh/h/ln mainline, 20 % off-ramp share, 10 % HGV, `departLane="random"`, with the
seed count stated per result.

## Are SUMO's default lane-changing parameters defensible for a diverge?

**Yes for lane utilisation and throughput; no for the spatial structure of the exit
manoeuvre.** Against a declared field target vector (per-lane share 28/35/37 at a station
1.5 km upstream of the gore; 0.45 discretionary LC per vehicle per km; 85th-percentile
distance-to-gore of the last change into the rightmost through lane = 400 m), the SUMO
default vType scores, on 16 independent seeds:

| observable | target | default | calibrated |
|---|---|---|---|
| per-lane share r/m/l | .28/.35/.37 | .2726/.3428/.3846 | .2747/.3302/.3951 |
| **max per-lane GEH** | < 5 | **1.648 ± 0.126 PASS** | **2.835 ± 0.106 PASS** |
| discretionary LC rate (LC/veh/km) | 0.45 | 0.389 ± 0.008 | 0.313 ± 0.008 |
| **85th-pct last-change distance (m)** | **400** | **2464.5 ± 64.8** | **904.6 ± 129.1** |
| median last-change distance (m) | — | 296.7 ± 2.0 | 277.5 ± 1.0 |
| exiting vehicles failing to reach the exit lane | 0 | 0 | 0 |
| station flow (veh/h) | — | 4798.8 ± 2.7 | 4798.8 ± 2.5 |

The default is **6.2x too far upstream** on the 85th percentile: SUMO pre-positions exiting
traffic far earlier than drivers do (35.2 ± 0.6 % of exiting vehicles are already in the
right lane 1.5 km ahead of the gore, versus 25.3 ± 0.2 % of through vehicles). Calibration
halves the gap but cannot close it, and pays for it — the per-lane split gets *worse*
(RMSN 0.030 -> 0.053) and the discretionary LC rate moves further from target
(0.389 -> 0.313). Throughput is untouched (paired CRN difference −0.06 ± 3.84 veh/h, ns).

## The percentile you choose decides the verdict

The default's **median** last-change distance is 296.7 ± 2.0 m against a 400 m target
(−26 %, entirely acceptable); its **85th percentile** is 2464.5 ± 64.8 m against the same
target (6.2x too far). The failure lives entirely in the upper tail — a minority of exiting
vehicles that settle into the right lane kilometres early and never leave it. **A spatial
lane-change target is meaningless without naming its percentile**, and p85 is far noisier
than p50 (seed SD 195 m vs 5.4 m at the default vector; ~12 replications for a ±5 % CI vs 2).

## Which parameters matter, and they are not the ones you would guess

Morris screening (p=4, Δ=2/3, r=10, 90 points x 4 CRN seeds = 360 runs, 0 failures), μ*
computed per observable:

- **`lcAssertive` is the most influential of the eight** — ranked 1st on the aggregate
  objective (μ\* 0.232), on both outer lane shares, on the median manoeuvre distance and on
  station flow, and 2nd on the discretionary LC rate. It is a parameter practitioners
  almost never calibrate — the lane-changing counterpart of `apparentDecel` in
  [[car-following-parameter-calibration-and-identifiability]].
- **`lcLookaheadLeft` is the top control of the spatial statistic (μ\* 1.90 on p85) and
  simultaneously the weakest of all eight parameters on every lane share** (μ\* 0.054 /
  0.020 / 0.027, last-ranked three times). It is recoverable **only** from the lane-change
  event stream.
- **`lcSpeedGain` dominates the discretionary LC rate** (μ\* 5.94).
- **`lcKeepRight` ranks last** on the objective, the strategic rate and p85 — *at this
  demand only*, see below.
- Observables that are exactly zero in every default replication (the cooperative LC rate
  and the exit-failure fraction under free flow) have a measured seed SD of 0, so any
  "above the noise floor" test on them is vacuous and must be flagged rather than reported
  as an active effect.

## Aggregate counts and the event stream identify disjoint parameter sets

This is the central result, and it is sharper than the car-following equivalent.

**`lcKeepRight` and `lcSpeedGain` are equifinal on per-lane flows.** On a 7x7 grid
(4 CRN seeds each), **69 of 1176 parameter pairs produce per-lane flow distributions
indistinguishable at twice the measured seed-noise threshold**, with unit-cube separations
up to 0.925 — nearly the full diagonal of the 2-D subspace. The most separated tied pair,
`(lcKeepRight 0.25, lcSpeedGain 6.0)` vs `(0.5, 0.5)`, differs by **3.5x in discretionary
lane-change rate** (0.844 vs 0.240 LC/veh/km). A calibration against loop counts alone
cannot separate these two parameters; `--lanechange-output` can.

**`lcStrategic`'s identifiability is asymmetric about its default** — and reporting only
one side would be wrong in one direction:

| lcStrategic range | Δ right-lane share | 6-seed noise band | Δ median distance | verdict from lane flows |
|---|---|---|---|---|
| 0.10 -> 1.00 (default) | **+0.0035** | 0.0041 | 97 -> 299 m (3.07x) | **not identifiable** |
| 1.00 -> 6.00 | **+0.0493** | 0.0041 | 299 -> 2145 m | identifiable (12x noise) |

Below the default — the half of the range a realistic diverge calibration lives in —
`lcStrategic` is invisible in aggregate lane flows and only the spatial mandatory-LC
profile identifies it. Above the default a high `lcStrategic` parks exiting traffic in the
right lane far upstream and that does show up in the counts.

**Known-answer recovery reproduces the car-following equifinality result.** Perturbing the
calibrated vector, regenerating the targets from that vector's own raw output and re-running
the optimiser recovered the *observables* well — per-lane shares to +3.7 / +0.4 / −2.8 %,
p85 to +1.8 %, LC rate to −11.0 % — while individual parameters remained off by up to
**+128.6 %** (`lcLookaheadLeft`), −65.5 % (`lcSpeedGain`) and +120.3 % (`lcKeepRight`);
total unit-cube distance 0.4609 over 7 parameters. Caveat recorded honestly: the winning
restart was the one seeded at the SUMO defaults and four of seven coordinates never moved,
which *is* the identifiability finding rather than an optimiser failure.

**Do not read an optimiser's own tied-band width as equifinality.** Only 5 of 999 logged
candidates fell inside `best + 2·SD_seed` here — a property of where a compass search
samples, not of the objective surface. The design-independent evidence is the grid and the
recovery experiment.

## `lcKeepRight` is demand-dependent, not weak

`lcKeepRight` screened last on almost every observable, which appears to contradict the
earlier finding in [[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]] that
SUMO's keep-right rule badly unbalances a multi-lane approach. Both are correct; the
difference is demand. Sweeping `lcKeepRight` ∈ {0, 1, 6} (4 CRN seeds, 95 % noise band on a
share difference 0.0050):

| mainline | right-lane share at kr=0 / 1 / 6 | range |
|---|---|---|
| 400 veh/h/ln | 0.2041 / 0.4339 / 0.5803 | **0.3762** (75x noise) |
| 800 veh/h/ln | 0.2240 / 0.2913 / 0.3946 | 0.1706 |
| 1600 veh/h/ln | 0.2609 / 0.2706 / 0.2873 | **0.0265** (5x noise) |

Its leverage collapses **14x** between 400 and 1600 veh/h/ln. Never carry a keep-right
verdict across demand levels in either direction.

## LC2013's strategic pull is route-global — there is no advance-signing distance

`bestLanes` spans the whole remaining route, so an exiting vehicle begins drifting right
the moment it is inserted, however far from the gore. Verified by rebuilding the identical
facility with a 7400 m approach instead of 3600 m: **38.6 % of all strategic lane changes
then occur more than 3600 m from the gore**, with a flat 30–81 events per 200 m bin all the
way back to insertion. Lengthening the approach adds strategic activity rather than
revealing an onset. Two genuine peaks survive in both facilities: an insertion-correction
spike in the first bin and the auxiliary-lane-entry spike in the 200–400 m bin.
**Consequence: a measured spatial lane-change profile on a diverge is boundary-dependent**,
and cannot be interpreted as a driver response to advance signing.

## Transferability: the lane split barely responds to demand or exit share

On hold-out conditions (1200 veh/h/ln and/or 35 % exit share) the per-lane GEH < 5 criterion
failed for **both** the default and the calibrated vector against declared hold-out targets.
The target-free version of that result is the more useful one: raising the off-ramp share
from 20 % to 35 % at constant demand moved SUMO's right-lane share by only **+0.68 pp**
(default) / **+0.01 pp** (calibrated), and dropping demand from 1600 to 1200 veh/h/ln moved
it by **−0.62 / −0.88 pp**. Across all four conditions the default's right-lane share spans
1.5 pp and the calibrated vector's 1.0 pp, while real lane distributions shift by several
percentage points with both drivers. **The calibrated vector transferred *worse* than the
default, for an identifiable reason**: calibration drove `lcKeepRight` to 0.262, and that
is exactly the parameter that makes the split demand-sensitive. Zero teleports and zero
collisions in every hold-out cell, so this is not a congestion artifact.

## Four verified SUMO traps

1. **`--lanechange.duration` defaults to 0** (instantaneous, zero-width lane changes).
   Setting it to 3 s cut lane-change events by 6.4 % (default vector) / 15.0 % (a
   high-`lcSpeedGain` calibrated vector) and left throughput untouched (station flow
   4800 -> 4798, ramp flow 961 -> 960). The calibrated vector **transferred on the acceptance
   criterion** (max GEH 2.80 -> 2.33, still PASS; lane shares moved ≤0.002) but **not on the
   spatial statistic** (p85 915 -> 1282 -> 628 m across 0/1/3 s, non-monotone). This *bounds*
   [[system-interchange-weaving-and-design-selection]]'s +10.4 % cloverleaf-throughput
   effect: the duration acts through the weaving mechanism, and at an uncongested diverge
   with no weaving the throughput effect is absent — which supports that page's mechanism
   claim while showing its magnitude does not generalise.
2. **`lcStrategic = 0` does not disable strategic changing; only a negative value does.**
   At 0.00 every vehicle still exited (ramp flow 957.5 vs 960.2 at the default), with zero
   teleports and zero failures. A screening range whose lower bound is 0 measures nothing.
   **Caveat found on review**: this row's raw data shows a mean of 0.75 real `<collision>`
   events across its 4 seeds (i.e. collisions occurred in some but not all seeds) — a small,
   undisclosed anomaly in what was otherwise reported as a clean control. It does not change
   the "0 disables nothing, only negative does" conclusion, but a genuinely clean control
   should read exactly zero on every metric; this one didn't, and that wasn't reported.
3. **A missed exit is a mainline blockage followed by a teleport onto the ramp, not a
   missed ramp.** With `lcStrategic = -1`, stderr reads
   `Teleporting vehicle 'f_exit_car.56'; waited too long (wrong lane), lane='D_3'` followed
   by `Vehicle 'f_exit_car.56' ends teleporting on edge 'R'`. The vehicle stops at the end
   of its lane and blocks the mainline until `--time-to-teleport` fires, then is placed on
   the next edge of its route — the ramp itself. Contamination is upstream and severe:
   station flow collapsed 4800 -> 402 veh/h, ramp flow 961 -> 16 veh/h, only 1480 of 5333
   vehicles ever inserted, and through vehicles were dragged in too. Congestion alone did
   not reproduce it (2200 veh/h/ln with default parameters: zero teleports). See
   [[teleport-artifacts-and-gridlock-resolution-validity]].
4. **LC2013 is hard-incompatible with the sublane model** —
   `Error: Lane change model 'LC2013' is not compatible with sublane simulation`. Enabling
   `--lateral-resolution` *forces* SL2015, so "the same calibration with sublane on" is not
   expressible at all. Carrying the calibrated `lc*` values into SL2015 + sublane kept
   GEH < 5 (2.52) but moved the middle-lane share +4.0 pp, cut lane-change events 38 % and
   the discretionary rate 21 %. The same `lcSpeedGain` change (0.2 -> 4) multiplies the
   discretionary rate by **4.4x under LC2013, 1.11x under SL2015 + sublane, and exactly
   1.00x (inert) under SL2015 without `--lateral-resolution`** — and that last
   configuration is degenerate, emitting zero `speedGain` events and reversing the lane
   distribution (right lane 0.374 vs 0.272). `lcStrategic` was the one parameter that
   behaved consistently across all three arms. See [[sublane-model-and-lane-filtering]].

## Two measurement traps that silently corrupt the evidence

**`tripinfo` lists only completed trips, so any failure-rate metric built on it hides
exactly the vehicles that failed.** In the gridlocked case above, the exit-failure fraction
computed from `tripinfo` read **NaN** (empty denominator), not 1.0; at a lower demand where
the failing vehicles eventually completed via teleport it read a healthy-looking 0.376.
Cross-check against `loaded`/`inserted`/`running`/`halting`/`teleports` from
`--statistic-output` and `--summary-output`.

**A per-lane E1 detector and a `laneData` meandata element only agree if the detector
`period` divides the meandata window.** With `period` set to the window *length* but the
window starting at t=300 s, the loops totalled the whole run (2134 veh) while the meandata
totalled the window (1601 veh) — a 33 % apparent instrument disagreement that was purely
window misalignment. With `period=60 s` and only in-window intervals summed, the two agreed
to **0.18 %** (1306/1664/1825 vs 1307/1661/1828), which is the check that licenses using
either. See [[sumo-output-files]].

## Practical rule

**Calibrate a lane-changing model against the event stream, not only against counts.**
Per-lane flows at a station constrain a low-dimensional combination of `lcAssertive`,
`lcSpeedGain`, `lcKeepRight` and (only above its default) `lcStrategic`; the
`--lanechange-output` rate and spatial profile constrain `lcSpeedGain`, `lcLookaheadLeft`
and `lcStrategic` below its default. Neither observable alone identifies the vector, and a
calibration that reaches GEH < 5 on lane counts can still be placing the mandatory exit
manoeuvre kilometres from where drivers make it.
