---
name: model-horizontal-curvature-and-evaluate-design-consistency
description: Use this skill when the user wants HORIZONTAL ALIGNMENT (circular curves, curve radius, superelevation, curvy/mountain/rural roads) to actually influence vehicle behaviour in SUMO - which it does not by default - or wants to evaluate a road against AASHTO/Lamm design-consistency criteria (V85 operating speed, Criterion I/II/III, side friction demanded vs assumed), or to compute lateral acceleration / side-friction demand from simulated trajectories. Covers authoring a dense curve polyline in plain XML, verifying radii survived netconvert (and which --geometry.* options destroy them), why --junctions.limit-turn-speed cannot supply a curve-speed model, the AASHTO point-mass safe speed as a posted per-edge limit, why an approach taper relocates but never softens the braking, and a TraCI look-ahead curvature speed governor with per-vehicle-class comfort budgets. Trigger on mentions of horizontal curve, curve radius, curvature, superelevation, side friction, lateral acceleration, design consistency, Lamm criteria, V85, operating speed profile, mountain/winding road, or curve advisory speed.
related_skills:
  - model-road-gradient-effects-on-energy
  - evaluate-two-lane-highway-with-hcm-and-passing-lanes
  - calibrate-desired-speed-and-evaluate-speed-enforcement
  - analyze-intersection-safety-with-ssm
  - implement-variable-speed-limits
  - implement-glosa-speed-advisory-controller
  - visualize-trajectories-and-timeseries
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[evaluate-two-lane-highway-with-hcm-and-passing-lanes]]"
  - "[[calibrate-desired-speed-and-evaluate-speed-enforcement]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[implement-variable-speed-limits]]"
  - "[[implement-glosa-speed-advisory-controller]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[horizontal-curvature-and-curve-speed-in-sumo]]"
---

# Model Horizontal Curvature and Evaluate Design Consistency

**SUMO has no curvature-speed coupling.** A vehicle traverses an edge at the
posted limit regardless of the radius the edge's `shape` describes. Verified on a
6 km alignment with R = 600/300/150/80 m at 80 km/h: median lateral acceleration
on the R = 80 curve was **4.88–4.93 m/s², maximum 9.03 m/s² (0.92 g)**, and a 12 m
articulated truck took the same curve at the same speed as a passenger car
(V85 77.23 vs 78.07 km/h). This skill builds the alignment, proves the gap from
raw FCD, repairs it two ways, and grades the result with Lamm's criteria.

This is the *plan*-geometry counterpart to `model-road-gradient-effects-on-energy`
(profile geometry): both find that a geometric dimension SUMO faithfully stores
does not reach the longitudinal-dynamics model. Grade reaches only the
emissions/battery models; curvature reaches nothing at all.

## Author the alignment analytically, integrate it arc-exactly

Define the alignment as a chain of `(station, arc length, radius, turn sign)`
tuples and generate everything — node coordinates, edge `shape`, station lookup,
element table — from that one source. Discretise curves at **≤ 5 m**.

**Integrate the centreline arc-exactly, interval by interval, using the curvature
at each interval's MIDPOINT.** A trapezoidal heading integration on a uniform
sample grid looks correct and is not: curvature is discontinuous at every element
boundary, so a trapezoid straddling one adds a spurious `k·ds/2`. Over 6 curves
that accumulated 0.0167 rad and put the far end of a 6 km corridor **9.31 m**
sideways — more than a lane width, which silently mis-projected 18.3% of FCD
samples onto the wrong element.

**The check that catches it: the residual distance from each FCD point to the
projected centreline must equal the lane offset and nothing else.** Correct
result: mean 1.8059 m, max 1.8624 m for a 3.6 m lane at `spreadType="right"`.
Assert it.

Author both directions as opposed edges on shared nodes with explicit
`<connection>` elements. Put a node at **every** element boundary *and* at every
approach-taper boundary in **all** arms, then vary only the `speed` attribute per
arm — this is the geometry-matched control discipline of
`evaluate-two-lane-highway-with-hcm-and-passing-lanes`, and it lets you assert
that the compiled lane `shape` strings are **byte-identical across arms**
(verified: 38/38 named edges and 36/36 internal lanes identical).

## Verify the radius with a circle FIT, never with consecutive shape points

`netconvert` writes shape coordinates rounded to 2 decimals. At 5 m spacing the
arc sagitta over a 3-point window is `10²/(8R)` = **2.1 cm at R = 600** — two
quantisation steps. Measured on the same compiled net:

| estimator | worst error over 12 curve edges |
|---|---|
| least-squares (Kasa) circle fit per curve edge | **0.047%** |
| 3-consecutive-point circumradius, median | **3.699%** |
| triple at stride 4 (20 m baseline), median | 0.33% |

The naive estimator gets *worse as radius increases* (600 m → 1.5–2.1%,
300 m → 2.7–3.7%, 80 m → 0.3–1.0%), which is the signature of coordinate
quantisation rather than of geometry loss.

Compare against the **lane** radius, not the centreline radius:
`spreadType="right"` offsets the single lane by half the road width, so
`R_lane = R ± w/2`, **with the sign flipping between the two directions** of the
same curve. Compiled lane length differs correspondingly — a 400 m design arc at
R = 600 compiled to 400.89 m outbound and a 300 m arc at R = 300 to 297.93 m
inbound. Read the compiled length; don't quote the authored one.

Tangent edges should compile to exactly **2 shape points** — a structural check
that no spurious curvature was added.

## Which `--geometry.*` options destroy the alignment

Probed on identical plain XML:

| option | effect |
|---|---|
| *defaults* | preserves (0.047%) — **`--geometry.remove` is `false`, `--geometry.max-angle 99` is warn-only, `--geometry.max-angle.fix` is `false`, `--geometry.min-dist -1`** |
| `--geometry.max-angle 3 --geometry.max-angle.fix` | **STRAIGHTENS the R = 80 curve outright** (21 points → 2); corridor 11993.1 → 11972.0 m |
| `--geometry.remove` | **collapses 38 edges → 2** (one per direction); geometry survives to 0.036% but the per-curve speed limit has nowhere to live |
| `--geometry.min-dist 10` | thins 632 → 272 points; radius still recovered (0.218%) but the polyline now departs the true arc by 15.6 cm at R = 80 |
| `--geometry.max-segment-length 2` | 632 → 6322 points, all linearly interpolated; radius fine, local curvature estimation ruined |
| `--geometry.min-radius 200 --geometry.min-radius.fix` | trims 2 points from each **end** of the R = 80 edges only (the option checks start/end, not the interior) |

`--geometry.max-angle.fix` is selective in a dangerous way: the per-segment
deflection is `spacing/R`, so at 5 m spacing it is 3.58° at R = 80 but 0.48° at
R = 600 — a threshold between them destroys the sharpest curve and leaves the
rest looking fine.

Pass `--offset.disable-normalization true` so FCD `x,y` is the design coordinate
system directly (harmless here, since the alignment starts at the origin and
`netOffset` came back `0.00,0.00` either way, but required whenever it does not).

## `--junctions.limit-turn-speed` is not a curve-speed model — record why

It acts **only on junction internal lanes**. Curvature carried in an edge's
`shape` creates no junction, so there is nothing for it to act on. Verified on the
same R = 80 curve built six ways:

| representation | spacing | deflection/junction | internal lanes | derated |
|---|---|---|---|---|
| **one edge, dense `shape`** | 5 m | 3.58° | **0** | 0 |
| chain of edges | 5 / 10 / 20 / 25 m | 3.58–17.90° | 21 / 11 / 6 / 5 | **0** |
| chain of edges | 50 m | 35.81° | 3 | **1**, to 4.44 m/s |

`--junctions.limit-turn-speed.min-angle` (default **15°**) is *subtracted from the
geometric deflection* before the turning radius is computed, so even a 25 m chain
(17.90°, residual 2.90°) escapes. In the real corridor all **36 internal lanes
(8.09 m total) compiled at the posted 22.22 m/s with zero derating**, and setting
the option to `-1` changed nothing. Report this explicitly whenever someone
suggests it as the curve-speed mechanism.

## Repair (a): AASHTO point-mass posting per edge

`V = sqrt(127·R·(e + f(V)))`, f interpolated from the AASHTO high-speed
side-friction table, solved as a **damped** fixed point (the undamped map diverges
near large R). At e = 0.06:

| R | f at solution | V | applied |
|---|---|---|---|
| 600 | 0.1054 | 112.28 | 80 (capped at design speed) |
| 300 | 0.1340 | 85.98 | 80 (capped) |
| 150 | 0.1604 | **64.797** | 64.797 → compiled 18.00 m/s |
| 80 | 0.1893 | **50.332** | 50.332 → compiled 13.98 m/s |

**State the friction table you use.** The AASHTO exhibit could not be verified
against a primary source reachable from this environment, so print the values
rather than cite them. Note also that `R_min` at 80 km/h is 252 m, so only 2 of 4
distinct radii need any restriction — an "inconsistent alignment" study should be
designed knowing that.

The compiled lane speed is the authored value **rounded to 2 decimals**; read the
limit from the net for every threshold.

## The speed step: peak deceleration is `decel`, and a taper cannot change it

**Verified: the peak deceleration at a posted-speed step is set by the vType's
`decel`, not by the step size or the taper length.** Measured p85/p95/max of the
per-vehicle minimum acceleration in the 400 m approach: **exactly 4.500 m/s²**
(= `decel="4.5"`) for the 80 → 64.8 step (Δ15.2 km/h) *and* the 80 → 50.3 step
(Δ29.7 km/h), *and* with a 150 m mid-step taper edge inserted. SUMO's Krauss model
anticipates the next lane's limit and brakes as late as possible at its own decel
limit. Baseline for comparison: p50 1.19–1.26 m/s², **0** events below −3 m/s².

**What the taper does change is where.** Eastbound hard-braking samples more than
100 m upstream of the curve entry:

| curve | abrupt step | + 150 m taper |
|---|---|---|
| C3 (R150) | 2 of 276 (0.7%) | **241 of 297 (81%)** |
| C4 (R80) | 9 of 674 (1.3%) | **407 of 608 (67%)** |
| C6 (R150) | 2 of 250 (0.8%) | **188 of 270 (70%)** |

Under the abrupt step the busiest bin sits **12 m past the tangent point** (190
samples at station 3512 on a curve starting at 3500), and **30.3% of all
hard-braking samples occur inside a curve**, where longitudinal and lateral demand
share one friction ellipse. The taper buys a 2.8% cut in total hard braking for
+3.3 s of travel time. **It is a placement fix, not a magnitude fix — say so.**

Make the taper **directional** (only the approaching direction's edge is
derated); a symmetric taper charges the exiting direction for nothing.

## Repair (b): TraCI look-ahead curvature governor

Per class and direction, build the classical critical-speed profile by backward
recursion over a 0.5 m station grid, **once, before the run**:

```
v_perm[i] = sqrt(a_allowed · R[i])          a_allowed = g·e + a_unbalanced_max
v_crit[i] = min(v_perm[i], sqrt(v_crit[i±1]² + 2·a_brake·ds))
```

Then each step: project position → station, take `v_crit` and issue
`slowDown(v_target, (v − v_target)/a_brake)`, `setSpeed(v_target)` to hold,
`setSpeed(-1)` to release when the constraint stops binding below the vehicle's
own `speedFactor × limit`. Keep the default `speedMode` so car-following safety
still caps the command.

**Take the MINIMUM of `v_crit` over `[current station, station + v·T_antic]`, not
the value at the look-ahead point.** Evaluating only at the look-ahead point
releases the vehicle `v·T_antic ≈ 13 m` *before the curve exit*, so it
accelerates while still inside: 573 samples overshot to a_lat 2.53 m/s² against a
2.089 target, all in the first and last 10 m of the element. The window minimum
removed it exactly (`alat_max` 2.528 → 2.090).

Per-class budgets work cleanly and are the thing SUMO cannot otherwise express:

| curve | V85 car | V85 HGV | a_unbalanced p95 car | HGV |
|---|---|---|---|---|
| R = 150 | 63.72 | **55.58** | 1.500 | **1.001** |
| R = 80 | 46.55 | **40.57** | 1.501 | **0.999** |

against a baseline where the two classes were within 0.2–0.8 km/h of each other.

**The governor dominates the static posting on both axes.** It cost *less* travel
time (+8.0/+7.1 s vs +8.7/+8.9 s abrupt, +12.0/+12.1 s tapered), left hard braking
at exactly the baseline count (14 samples), and had p50 deceleration **1.500 m/s²
= the commanded `a_brake`** — because it brakes on the approach tangent at a rate
it chooses, instead of handing the braking to the car-following model.

## Compute a_lat from FCD, and be explicit about which threshold

Request `--fcd-output.attributes x,y,speed,type,acceleration,lane` — **comma
separated**; a space-separated argv token makes SUMO treat the whole string as one
attribute name, error with `Unknown attribute '...'`, and still write an id-only
FCD file that looks fine until you parse it.

Project each sample onto the design centreline (`scipy.cKDTree` over a 0.5 m
polyline), read R from the element, then report **all three** of:

- **A total** `v²/R ≤ 1.50 m/s²`
- **B unbalanced** `v²/R − g·e ≤ 1.50 (car) / 1.00 (HGV)`
- **C AASHTO friction** `v²/(gR) − e ≤ f_max(V85)`

They are not equivalent and the treatments meet different ones. **An AASHTO
point-mass posting does NOT deliver 1.5 m/s² of comfort, by construction** — the
equation admits `g(e + f)` = 2.16 m/s² total / 1.57 unbalanced at R = 150 and
2.45 / 1.86 at R = 80. Use a
~2% numerical tolerance, because a governor that *targets* a threshold sits
exactly on it and a bare `<=` scores that as failure on float noise.

## Lamm design consistency — and the criterion that disagrees with the other two

- **I** `|V85 − V_D|`; **II** `|V85,i − V85,i+1|`: good ≤ 10, fair ≤ 20, poor > 20 km/h
- **III** `Δf_R = f_RA − f_RD`: good ≥ +0.01, fair ≥ −0.04, poor < −0.04, with
  `f_RA = 0.25 − 2.04e-3·V_D + 0.63e-5·V_D²` and `f_RD = V85²/(127R) − e`

**The headline: Criteria I and II certify the unrepaired simulation as perfectly
consistent.** Baseline scored *good* on 19/19 elements for I (worst
|V85 − V_D| = 4.53 km/h eastbound, 5.86 km/h corridor-wide) and 18/18 for II
(worst ΔV85 = **1.51 km/h**) — precisely
*because* SUMO ignores the curves, so the operating-speed profile is flat.
Criterion III, the only one whose formula contains R, was the only one that saw
anything: Δf = **−0.135 / −0.400 / −0.116** at R = 150/80/150.

Both repairs then move the criteria in **opposite** directions: III improves
monotonically (3 poor → 1 poor → 0 poor → 6/6 good) while I and II degrade, worst
under the strictest treatment. That is not a defect — it is the repaired model
finally reproducing the inconsistency actually present in the alignment.

**Read the table per direction in order of travel**, and check the
distance-travelled confound: baseline V85 regressed against distance travelled
since origin gave slope **−1.809 km/h/km, r = −0.958, p = 4.8e−21**, while the
same data against fixed station label gave **r = 0.119, p = 0.478 — nothing**
(the westbound sign flips). Platoons accumulate with travel time, as
[[two-lane-highway-follower-density-and-passing-lane-effectiveness]] found for
percent followers. It changed no grade on a 6 km corridor but would push
Criterion I into "poor" on a 12 km one with no geometry involved. Warm the demand
up on fringe sections.

State whether `f_RA` is evaluated at `V_D` or at `V85` — both readings exist and
it changed the grade in **6 of 60 curve rows (10.0%)** here.

## Safety metrics: the SSM device is structurally empty on this facility

**The SSM device logged zero `<conflict>` elements in every arm, including the
baseline**, even at TTC < 5.0 / DRAC > 1.5. One lane per direction, no lane
changes, no crossing/merging conflict areas, opposing traffic on a separate
non-conflicting edge — the pairwise layer has nothing to populate. Use
`<globalMeasures><maxBR>` (which does discriminate: 1.87 baseline vs 4.15 static,
14 vs 732 of 770 vehicles above 3 m/s²) and compute car-following TTC directly
from the FCD samples as an independent check.

That check confirmed the null rather than contradicting it: 15–16 closing pairs
below 3 s and exactly 2 below 1.5 s in **every** arm, minimum TTC 1.166–1.225 s,
despite the static arms multiplying hard braking ~250×. The deceleration is
**coordinated** — every vehicle brakes at the same station — so gaps and closing
speeds never tighten. Same mechanism as
[[driver-desired-speed-and-speed-enforcement-evaluation]]: hard braking counts the
manoeuvre, TTC counts the interaction.

Add the **combined friction demand** `sqrt(f_lat² + f_long²)` restricted to curve
samples; it is the metric that separates the arms where TTC cannot (in-curve p99:
0.553 baseline / 0.304 static / 0.176 dynamic; max 0.865 / 0.571 / 0.316).

## Gotchas

- **`--fcd-output.attributes` must be comma separated** — space-separated fails
  loudly and writes an id-only file anyway.
- **Trapezoidal heading integration drifts at every curvature discontinuity.**
  Integrate arc-exactly and assert the FCD lateral offset equals the lane offset.
- **Naive 3-point circumradius is dominated by netconvert's cm rounding.** Fit a
  circle; expect the error to grow with radius, not shrink.
- **`--geometry.max-angle.fix` straightens sharp curves selectively**;
  `--geometry.remove` merges the split edges the static treatment needs. Both off
  by default — keep them off.
- **`--junctions.limit-turn-speed` sees only junction internal lanes**, and
  `min-angle` (15°) is subtracted before the radius is computed.
- **A speed-step's peak deceleration is `decel`, not a function of the step.** A
  taper relocates the braking; it does not soften it.
- **Look-ahead-only governors release inside the curve.** Take the window minimum.
- **`v²/R ≤ 1.5` and "AASHTO point-mass" are different criteria** — the latter
  admits `g(e+f)` ≈ 2.2 m/s². Report both or the verification is meaningless.
- **Short curves contaminate the compliance fraction** — a 120 m curve is ~7 s of
  traversal, so incomplete approach braking is a large share of its samples
  (worst row 0.608 vs 0.79–0.83 on the 200 m curve).
- **SSM conflicts are structurally zero on a single-lane uninterrupted facility.**
  Check the baseline before reading anything into a treatment's null.

## Related

- `model-road-gradient-effects-on-energy` — the profile-geometry counterpart;
  together they establish that *neither* vertical nor horizontal geometry reaches
  SUMO's longitudinal-dynamics model.
- `evaluate-two-lane-highway-with-hcm-and-passing-lanes` — the rural two-lane
  corridor construction, the geometry-matched-control rule, and the
  distance-travelled-not-position finding this skill reproduces for V85.
- `calibrate-desired-speed-and-evaluate-speed-enforcement` — the `speedFactor`
  semantics, `slowDown`/`setSpeed` actuator behaviour, the hard-braking spatial
  audit, and the coordinated-deceleration explanation of a null SSM result.
- `analyze-intersection-safety-with-ssm` — the SSM device setup and de-duplication
  this skill uses, and the reason its pairwise layer is empty here.
- `implement-variable-speed-limits` / `implement-glosa-speed-advisory-controller`
  — the other two TraCI speed controllers; this one is commanded by geometry
  rather than by a detector or a signal.
- `visualize-trajectories-and-timeseries` — the station-indexed profile plot used
  for the speed / lateral-acceleration overlay.
- `validate-congested-scenario-results-against-teleport-artifacts` — the
  teleport / completion screen applied to every arm.
- [[horizontal-curvature-and-curve-speed-in-sumo]] — the verified mechanics, the
  netconvert geometry-option matrix, the Lamm results and the criterion
  disagreement.
