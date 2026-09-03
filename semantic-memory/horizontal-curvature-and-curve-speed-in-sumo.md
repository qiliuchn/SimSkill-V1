---
summary: SUMO stores horizontal curvature faithfully in edge shapes (netconvert reproduces authored radii to 0.047% under its defaults) but no part of the car-following or speed-choice machinery reads it, so vehicles take an R=80 m curve on an 80 km/h road at free-flow speed - median lateral acceleration 4.9 m/s2, maximum 9.03 m/s2 (0.92 g), with a 12 m truck taking the same speed as a car; --junctions.limit-turn-speed cannot supply the missing model because it acts only on junction internal lanes and subtracts a 15 degree min-angle first; and the gap is invisible to Lamm design-consistency Criteria I and II (which certify the unrepaired corridor as 19/19 and 18/18 good precisely because the operating-speed profile is flat) and visible only to Criterion III, the one criterion whose formula contains the radius.
keywords:
  - horizontal-curvature
  - curve-radius
  - lateral-acceleration
  - side-friction
  - superelevation
  - aashto-point-mass
  - lamm-design-consistency
  - V85-operating-speed
  - netconvert-geometry-options
  - limit-turn-speed
created: 2026-08-05T13:30:00
last_updated: 2026-08-07T05:39:34
sources:
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/geometry_verification.json]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/analysis.json]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/verification.json]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/lamm_table.csv]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/element_stats.csv]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/transition_decel.csv]]"
  - "[[episodic-memory/2026-08-05_13-30-00/outputs/combined_friction.json]]"
  - https://www.ijscer.com/uploadfile/2015/0427/20150427034549611.pdf
  - https://sumo.dlr.de/docs/Networks/PlainXML.html
related_pages:
  - "[[road-gradient-and-energy-consumption]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[driver-desired-speed-and-speed-enforcement-evaluation]]"
  - "[[surrogate-safety-measures]]"
  - "[[abstract-network-generation]]"
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[weather-friction-effects-on-capacity-and-safety]]"
  - "[[network-safety-screening-and-crash-prediction]]"
  - "[[protected-bicycle-intersection-design-and-right-hook-mechanics]]"
  - "[[traci]]"
  - "[[sumo-output-files]]"
related_skills:
  - model-horizontal-curvature-and-evaluate-design-consistency
  - model-road-gradient-effects-on-energy
  - evaluate-two-lane-highway-with-hcm-and-passing-lanes
  - calibrate-desired-speed-and-evaluate-speed-enforcement
  - analyze-intersection-safety-with-ssm
  - implement-variable-speed-limits
  - evaluate-protected-bicycle-intersection-design
related_skills_for_graph_view:
  - "[[model-horizontal-curvature-and-evaluate-design-consistency]]"
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[evaluate-two-lane-highway-with-hcm-and-passing-lanes]]"
  - "[[calibrate-desired-speed-and-evaluate-speed-enforcement]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[implement-variable-speed-limits]]"
  - "[[evaluate-protected-bicycle-intersection-design]]"
---

# Horizontal Curvature and Curve Speed in SUMO

SUMO represents horizontal alignment as an ordered list of `x,y` points in each
edge's (and lane's) `shape`. It stores that geometry accurately and uses it for
rendering, routing distance and vehicle position — and **no part of the
car-following, lane-changing or speed-choice machinery reads the curvature it
implies.** This is the plan-geometry twin of the result recorded in
[[road-gradient-and-energy-consumption]]: grade at least reaches the emissions and
battery models, whereas curvature reaches nothing at all.

All figures below come from a 6.0 km rural two-lane mountain highway in SUMO
1.27.1 — one 3.6 m lane per direction, design and posted speed 80 km/h,
superelevation e = 0.06, alternating tangents and circular curves at
R = 600 / 300 / 150 / 80 / 300 / 150 m discretised at 5 m — carrying
400 veh/h/direction with 10% HGV and `speedFactor="normc(1.0,0.1,0.8,1.3)"`.
Five arms, **770 trips each, 0 teleports, 0 collisions, 0 vehicles running at
end, identical vehicle sets and identical per-vehicle speedFactor draws**, and
compiled lane `shape` strings byte-identical across the three static arms
(38/38 named edges, 36/36 internal lanes). See
`model-horizontal-curvature-and-evaluate-design-consistency` for the workflow.

## Verified: the geometry survives, the behaviour does not

Least-squares circle fits on the compiled lane shapes recover the authored radii
to a **worst error of 0.047%** across all 12 curve edges under `netconvert`'s
defaults. The vehicles then ignore them completely:

| curve | R (m) | direction | V85 (km/h) | a_lat median | a_lat p95 | a_lat max | share of samples with v²/R ≤ 1.5 |
|---|---|---|---|---|---|---|---|
| C3 | 150 | E / W | 78.37 / 78.66 | 2.637 / 2.553 | 3.499 / 3.613 | 4.352 / 4.817 | **0.000 / 0.000** |
| C4 | **80** | E / W | 77.26 / 79.78 | **4.881 / 4.925** | 6.306 / 7.045 | 8.205 / **9.025** | **0.000 / 0.000** |
| C6 | 150 | E / W | 75.96 / 84.17 | 2.540 / 2.929 | 3.235 / 4.038 | 3.764 / 5.294 | **0.000 / 0.000** |

Not one of 32 156 vehicle-timesteps on the three sub-minimum-radius curves fell
below a 1.50 m/s² comfort threshold. The V85 inside the R = 80 curve (77.3 /
79.8 km/h) is indistinguishable from the V85 on the tangents either side
(77.7 / 77.1 km/h). The implied side-friction demand on C4 reaches **0.527**
against an AASHTO f_max of 0.14 at that speed, and the friction-ellipse combined
demand (longitudinal and lateral together) peaks at **0.865**.

**Cars and heavy vehicles are treated identically.** Baseline C3 eastbound V85:
78.34 km/h car vs 78.56 km/h HGV; C4 westbound a_lat p95: 7.039 vs 7.136 m/s².
A 12 m articulated truck takes an 80 m radius at 80 km/h exactly as a passenger
car does — the sharpest single statement of the missing model, and the reason a
rollover or truck-stability study cannot be run on stock SUMO without a
controller.

R_min at 80 km/h with e = 0.06 and f_max = 0.140 is **252.0 m**, so R = 300 and
R = 600 need no restriction at all; only radii below that are affected.

## Verified: `--junctions.limit-turn-speed` cannot be the missing model

The option limits speed **only on junction internal lanes**. Curvature carried in
an edge's `shape` creates no junction, so there is nothing for it to act on. The
same R = 80 m / 100 m curve built six ways:

| representation | point spacing | deflection per junction | internal lanes | derated |
|---|---|---|---|---|
| one edge with dense `shape` | 5 m | 3.58° | **0** | 0 |
| chain of straight edges | 5 m | 3.58° | 21 | 0 |
| chain | 10 m | 7.16° | 11 | 0 |
| chain | 20 m | 14.32° | 6 | 0 |
| chain | 25 m | 17.90° | 5 | **0** |
| chain | 50 m | 35.81° | 3 | **1**, to 4.44 m/s |

`--junctions.limit-turn-speed.min-angle` (default **15°**) is *subtracted from the
geometric deflection* before the turning radius is computed, so even a 25 m chain
whose raw deflection exceeds 15° escapes. In the real corridor all **36 internal
lanes (8.09 m of lane in total) compiled at the posted 22.22 m/s with zero
derating**, and setting the option to `-1` changed nothing anywhere. Even where it
does bite, it derates a sub-metre internal lane while both adjoining 50 m edges
stay at the posted limit — a discontinuity, not a curve-speed profile.

## Verified: which netconvert geometry options damage an alignment

Probed on identical plain XML (`--offset.disable-normalization true`):

| option | shape points | curve edges surviving | worst radius error | what it did |
|---|---|---|---|---|
| *defaults* | 632 | 12 | 0.047% | preserves |
| `--geometry.max-segment-length 2` | 6322 | 12 | 0.049% | 10× interpolated points; radius fine, local curvature estimation ruined |
| `--geometry.min-radius 200 --geometry.min-radius.fix` | 628 | 12 | 0.061% | trims 2 points from each **end** of the R = 80 edges only |
| `--geometry.min-dist 10` | 272 | 12 | 0.218% | thins to 10 m spacing; the polyline now departs the true arc by 15.6 cm at R = 80 |
| `--geometry.max-angle 3 --geometry.max-angle.fix` | 594 | **10** | — | **straightens the R = 80 curve outright** (21 points → 2), corridor 11993.1 → 11972.0 m |
| `--geometry.remove` | 596 | **0** | — | **collapses 38 edges → 2**, one per direction (5999.87 / 6000.05 m) |

The defaults are safe: `--geometry.remove` is `false`, `--geometry.min-dist` is
`-1`, and `--geometry.max-angle 99` is **warn-only** because
`--geometry.max-angle.fix` defaults to `false`.

Two failure modes are distinct and both matter. `--geometry.max-angle.fix`
destroys geometry, and does so **selectively**: the per-segment deflection is
`spacing/R`, i.e. 3.58° at R = 80 but 0.48° at R = 600 for 5 m spacing, so a
threshold between those values annihilates the sharpest curve and leaves every
other one looking correct. `--geometry.remove` preserves the geometry perfectly
(the merged edge still fits every curve to within 0.036%) but destroys the
**topology** — with 2 edges instead of 38 there is nowhere to hang a per-curve
speed limit, so any edge-split-based treatment silently becomes unimplementable.

## Verified measurement trap: naive circumradius vs netconvert's cm rounding

`netconvert` writes shape coordinates rounded to 2 decimals. At 5 m point spacing
the arc sagitta over a 3-point window is `10²/(8R)` = **2.1 cm at R = 600** — two
quantisation steps. Measured on one compiled net:

| estimator | worst error over the 12 curve edges |
|---|---|
| least-squares (Kasa) circle fit per curve edge | **0.047%** |
| median 3-consecutive-point circumradius | **3.699%** |
| median triple at stride 4 (20 m baseline) | 0.33% |

The naive estimator's error **grows with radius** (600 m → 1.5–2.1%,
300 m → 2.7–3.7%, 150 m → 0.5–1.0%, 80 m → 0.3–1.0%), which is the signature of
coordinate quantisation, not of geometry loss — an analyst who sees a 3.7% error
on the flattest curve and concludes "netconvert resampled my alignment" has
misread their own estimator.

Compare against the **lane** radius, not the design centreline: `spreadType="right"`
offsets the single lane by half the road width, so `R_lane = R ± w/2` **with the
sign flipping between the two directions** of the same curve. Compiled lane length
follows: a 400 m design arc at R = 600 compiled to 400.89 m outbound, a 300 m arc
at R = 300 to 297.93 m inbound, and the two directions' offsets cancel exactly in
the corridor total (11993.07 m against a 12000 m design centreline, the 6.93 m
deficit being junction trimming against 8.09 m of internal lane).

## Verified: the two repairs, and what each can and cannot do

**Static AASHTO posting.** `V = sqrt(127·R·(e + f(V)))` with f from the AASHTO
high-speed side-friction table, solved as a damped fixed point (the undamped map
diverges at large R): R = 600 → 112.28 km/h, R = 300 → 85.98, R = 150 → 64.797,
R = 80 → 50.332. Posted on the split curve edges (compiled 18.00 and 13.98 m/s,
the authored value rounded to 2 decimals).

**The peak deceleration at a posted-speed step is the vType's `decel`, not a
function of the step size or of any approach taper.** Measured p85/p95/max of the
per-vehicle minimum acceleration in the 400 m approach: **exactly 4.500 m/s²**
(= `decel="4.5"`) for the 80 → 64.8 step (Δ15.2 km/h), for the 80 → 50.3 step
(Δ29.7 km/h), and with a 150 m mid-step taper edge inserted. SUMO's Krauss model
anticipates the next lane's limit and brakes as late as possible at its own decel
limit. Baseline for comparison: p50 1.19–1.26 m/s², **zero** events below −3 m/s².

**A taper relocates the braking without softening it.** Eastbound hard-braking
samples more than 100 m upstream of the curve entry rose from 2/276, 9/674 and
2/250 (abrupt) to **241/297, 407/608 and 188/270** (tapered) — from under 1.3% to
67–81%. Under the abrupt step the busiest 25 m bin sits **12 m past the tangent
point** (190 samples at station 3512 on a curve starting at 3500), and **30.3% of
all hard-braking samples fall inside a curve**, where longitudinal and lateral
demand share one friction ellipse. The taper bought a 2.8% cut in total
hard-braking samples (3527 → 3430) for +3.3 s of travel time. It is a placement
fix, not a magnitude fix.

**A TraCI look-ahead governor is strictly better on both axes.** A backward
recursion over a 0.5 m station grid gives the critical-speed profile
`v_crit[i] = min(sqrt(a_allowed·R[i]), sqrt(v_crit[i±1]² + 2·a_brake·ds))`;
commanding it with `slowDown(v_target, (v − v_target)/a_brake)` produced a p50
deceleration of **1.500 m/s² — exactly the commanded `a_brake`** — with hard
braking at the baseline count (14 samples), while costing *less* travel time than
the static posting (+8.0/+7.1 s vs +8.7/+8.9 s abrupt, +12.0/+12.1 s tapered).
It also expresses what infrastructure cannot: per-class comfort budgets gave
V85 63.72 km/h car vs **55.58 km/h HGV** at R = 150 and 46.55 vs **40.57** at
R = 80, landing on the configured 1.500 and 1.001 m/s² unbalanced budgets exactly.

**Governor implementation trap:** evaluating the critical-speed profile at the
look-ahead point *only* releases the vehicle `v·T_antic ≈ 13 m` **before the curve
exit**, so it accelerates while still inside — 573 samples overshot to
2.53 m/s² against a 2.089 target, all in the first and last 10 m of the element.
Taking the minimum over `[current station, look-ahead station]` removed it exactly.

## Verified: "a_lat ≤ 1.5" and "AASHTO point-mass" are different criteria

The point-mass equation admits `g·(e + f)` of total lateral acceleration, which at
R = 150 with f = 0.160 is **2.16 m/s² total / 1.57 m/s² unbalanced** and at R = 80
with f = 0.189 is 2.45 / 1.86. **An AASHTO-derived posting therefore cannot
deliver a 1.5 m/s² total-lateral-acceleration comfort standard, by construction.**
Minimum fraction of vehicle-timesteps satisfying each criterion, over all 12
curve × direction rows:

| arm | A: v²/R ≤ 1.50 | B: unbalanced ≤ 1.50 car / 1.00 HGV | C: f_dem ≤ AASHTO f_max(V85) |
|---|---|---|---|
| baseline | 0.000 | 0.000 | 0.000 |
| static AASHTO, abrupt | 0.006 | 0.505 | 0.651 |
| static AASHTO + taper | 0.010 | 0.537 | 0.670 |
| governor (unbalanced 1.5/1.0) | 0.000 | **1.000** | **0.961** |
| governor (total 1.5/1.2) | **1.000** | **1.000** | **1.000** |

Any claim of the form "after treatment ≥95% of samples are below the comfort
threshold" is meaningless until the threshold is named, and a study that mixes an
AASHTO-based treatment with a superelevation-free comfort test will report a
failure that is definitional. The static arms additionally fall well short of even
criterion B (0.50–0.54) because vehicles are still decelerating at the curve
entry: a 120 m curve gives only ~7 s of traversal, so incomplete approach braking
contaminates a large share of its samples.

## Verified, and the most consequential result: Lamm Criteria I and II certify the broken model

Applying Lamm's design-consistency criteria to the raw simulation output
(Criterion I `|V85 − V_D|`, II `|V85,i − V85,i+1|`, both good ≤ 10 / fair ≤ 20 /
poor > 20 km/h; Criterion III `Δf_R = f_RA − f_RD`, good ≥ +0.01 / fair ≥ −0.04 /
poor < −0.04, with `f_RA = 0.25 − 2.04e-3·V_D + 0.63e-5·V_D²` = 0.12712 at 80 km/h
and `f_RD = V85²/(127R) − e`):

| arm | dir | Crit I good/fair/poor | Crit II | Crit III |
|---|---|---|---|---|
| baseline | E | **19 / 0 / 0** | **18 / 0 / 0** | 3 / 0 / **3** |
| baseline | W | **19 / 0 / 0** | **18 / 0 / 0** | 2 / 1 / **3** |
| static + taper | E | 14 / 4 / 1 | 13 / 4 / 1 | 3 / 2 / 1 |
| governor (unbalanced) | E | 16 / 2 / 1 | 13 / 3 / 2 | **3 / 3 / 0** |
| governor (total) | E | 15 / 1 / **3** | 11 / 3 / **4** | **6 / 0 / 0** |

**The unrepaired corridor scores good on 19/19 elements for Criterion I (worst
|V85 − V_D| = 4.53 km/h eastbound, 5.86 km/h corridor-wide at station S18
westbound) and 18/18 for Criterion II (worst ΔV85 = 1.51 km/h) — precisely
because the simulator ignores the curves, so the operating-speed profile
is flat.** Criterion III, the only one of the three whose formula contains R, is
the only one that detects anything: Δf = **−0.135**, **−0.400** and **−0.116** at
R = 150, 80 and 150.

**The two repairs then move the criteria in opposite directions.** Criterion III
improves monotonically (3 poor → 1–2 poor → 0 poor → 6/6 good) while I and II
degrade, worst under the strictest treatment. This is not a defect of the repair:
it is the repaired model finally reproducing the design inconsistency that is
actually in the alignment (R = 80 on an 80 km/h road, against R_min = 252 m). In
every treated arm the element flagged poor on I and II is the R = 80 curve, and
under the static posting it is poor on Criterion III as well (Δf = −0.058) —
**no speed posting can satisfy Criterion III there**, because the criterion
compares the friction demanded at the actual operating speed against the friction
*assumed at the design speed*; only realignment closes that.

The practical consequence is a warning about method, not about SUMO: **an
operating-speed-based design-consistency audit run on default SUMO output is
structurally incapable of failing a curve**, and will return its cleanest possible
verdict on the most dangerous alignment. Only the driving-dynamics criterion
survives contact with a simulator that does not model curve-speed choice.

*Source note.* The Criterion III formulation is taken from Atashafrazeh & Mohabbi
Yadollahi (2013), *Int. J. Struct. & Civil Engg. Res.* 2(2):129–136, Eq. (1)–(2)
and Table 1, citing Lamm (1991) and AASHTO (2001). That table's printed
Criterion I "Fair" row (`10 < |V85−V_D| ≤ 10`) and Criterion II "Poor" row
(`ΔV85 ≥ 10`) are internally inconsistent typographical errors; the
self-consistent reading (fair ≤ 20, poor > 20) is used above. The `f_RA`
coefficients reconcile exactly with the commonly quoted
`f_RA = 0.925·n·f_T`, `n = 0.45`, `f_T = 0.59 − 4.85e-3·V + 1.51e-5·V²`
(0.41625 × 0.59 / 4.85e-3 / 1.51e-5 = 0.2456 / 2.019e-3 / 6.285e-6), which is the
cross-check that these are the published values rather than a transcription.
Whether `f_RA` is evaluated at `V_D` or at `V85` changed the grade in **6 of 60
curve rows (10.0%)** — state which reading is used, as
[[two-lane-highway-follower-density-and-passing-lane-effectiveness]] does for
HCM Exhibit 15-6.

## Verified confound: V85 falls with distance travelled, not with position

Baseline V85 regressed against **distance travelled since origin**, pooling both
directions (38 element × direction rows): slope **−1.809 km/h per km,
r = −0.958, p = 4.8×10⁻²¹**. The same data against **fixed station label**: slope
+0.232 km/h/km, **r = 0.119, p = 0.478 — no relationship**, because the westbound
sign flips (−2.003 by distance travelled, +2.003 by station). This is the same
mechanism [[two-lane-highway-follower-density-and-passing-lane-effectiveness]]
identified for percent followers: platoons accumulate behind the 10% HGV fleet as
a function of travel time, not of map position.

On this 6 km corridor the drift is ~11 km/h end to end and changed **no** Lamm
grade (baseline worst Criterion I 5.86 corridor-wide, worst Criterion II 1.51,
both deep inside "good"). On a 12 km corridor it would alone push Criterion I into "poor" with no
geometry involved. **Read a Lamm table per direction in order of travel, and warm
the demand up on fringe sections before the first graded element.**

## Verified: the SSM device is structurally empty on this facility

The SSM device logged **zero `<conflict>` elements in every arm, including the
baseline**, even with thresholds opened to TTC < 5.0 s and DRAC > 1.5 m/s². One
lane per direction, no lane changes, no crossing or merging conflict areas, and
opposing traffic on a separate non-conflicting edge leave the pairwise
TTC/DRAC/PET layer nothing to populate (see [[surrogate-safety-measures]]). Only
`<globalMeasures><maxBR>` discriminates: mean 1.867 m/s² baseline vs 4.154 under
the static posting, with **732 of 770 vehicles** exceeding 3 m/s² and 431
exceeding 4.4 against 14 and 0 at baseline.

A car-following TTC computed directly from the FCD samples (198 220 closing pairs
at baseline) **confirmed the null rather than contradicting it**: 15–16 pairs
below 3 s and exactly 2 below 1.5 s in *every* arm, minimum TTC 1.166–1.225 s,
despite the static arms multiplying hard-braking samples ~250× (14 → 3527). The
deceleration is **coordinated** — every vehicle brakes at the same station — so
gaps and closing speeds never tighten, exactly the mechanism recorded in
[[driver-desired-speed-and-speed-enforcement-evaluation]]. Hard braking counts the
manoeuvre; TTC counts the interaction. The metric that does separate the arms on a
curved alignment is the **combined friction demand** `sqrt(f_lat² + f_long²)`
restricted to in-curve samples: p99 0.553 / 0.304 / 0.176 and max 0.865 / 0.571 /
0.316 for baseline / static / governor.

## Verified integration trap in the analysis itself

Projecting FCD onto a design centreline requires the centreline to be integrated
**arc-exactly, interval by interval, from the curvature at each interval's
midpoint.** A trapezoidal heading integration on a uniform sample grid adds a
spurious `k·ds/2` at every curvature discontinuity; over 6 curves that accumulated
0.0167 rad and displaced the far end of a 6 km corridor by **9.31 m**, silently
mis-projecting 18.3% of samples onto the wrong element. The diagnostic that
catches it is cheap and should be an assertion: **the residual distance from each
FCD point to the projected centreline must equal the lane offset and nothing
else** — correct result mean 1.8059 m, max 1.8624 m for a 3.6 m lane at
`spreadType="right"`.

Also verified: `--fcd-output.attributes` is a `STR[]` that must be **comma**
separated. Passing it as one space-separated argv token makes SUMO treat the whole
string as a single attribute name, emit `Error: Unknown attribute '...'`, and
still write a syntactically valid id-only FCD file that only fails at parse time.

## Practical takeaways

- Curvature is stored, not simulated. Any curve-speed effect in SUMO must be
  authored as a posted limit or commanded through TraCI.
- Verify a compiled radius with a circle fit, not with consecutive shape points,
  and compare against the **lane** radius with its direction-dependent offset.
- `--geometry.remove` and `--geometry.max-angle.fix` are the two options that
  break a curved alignment, in different ways (topology vs geometry); both are off
  by default.
- `--junctions.limit-turn-speed` is a junction option with a 15° dead band; it is
  not and cannot be made into a curve-speed model.
- A posted-speed step is braked at the vType's `decel` regardless of its size; an
  approach taper moves the braking upstream but does not soften it. A vehicle-side
  governor is the only way to control the deceleration *rate*.
- Name the lateral-acceleration criterion before claiming compliance — AASHTO's
  own design speeds admit ~2.2 m/s².
- Grade design consistency with all three Lamm criteria; on simulated data I and
  II can certify a corridor that Criterion III condemns.
