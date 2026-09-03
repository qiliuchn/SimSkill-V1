---
summary: "SUMO's vType speedFactor is a per-vehicle draw from a RENORMALISED truncated normal with absolute bounds [0.2, 2.0] — a scalar value still carries --default.speeddev dispersion — and calibrating it to a field spot-speed target requires a mean ~5% above the naive target/posted ratio because car-following suppresses realised speed below desired speed even at v/c 0.30; measuring an automated-enforcement treatment at the camera rather than corridor-wide overstates its Nilsson power-model injury-crash benefit by 12.4x for a point camera but only 2.06x for section enforcement, and 0.99x for a spatially uniform limit change, while the SSM device detects no conflict change from either enforcement treatment despite a ~340x increase in hard-braking events at the camera."
keywords:
  - speedFactor
  - speedDev
  - desired-speed-distribution
  - 85th-percentile-speed
  - speed-camera
  - section-control
  - time-mean-vs-space-mean
  - nilsson-power-model
  - kangaroo-effect
  - partial-compliance
created: 2026-08-04T21:00:00
last_updated: 2026-08-05T14:00:00
sources:
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/analysis/headline_numbers.json]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/stage1/calibration.json]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/stage1/stage1_characterization.json]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/stage1/stage1b_bounds.json]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/stage2/actuator_probe.json]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/analysis/nilsson.csv]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/analysis/paired_vs_baseline.csv]]"
  - "[[episodic-memory/2026-08-04_21-00-00/outputs/analysis/extras.json]]"
  - https://sumo.dlr.de/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.html
related_pages:
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[surrogate-safety-measures]]"
  - "[[network-safety-screening-and-crash-prediction]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[glosa-eco-driving]]"
  - "[[change-vehicle-state]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-output-files]]"
  - "[[horizontal-curvature-and-curve-speed-in-sumo]]"
related_skills:
  - calibrate-desired-speed-and-evaluate-speed-enforcement
  - calibrate-car-following-parameters-against-field-targets
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - quantify-sumo-run-to-run-variability
  - implement-variable-speed-limits
  - analyze-intersection-safety-with-ssm
  - screen-network-safety-with-spf-and-empirical-bayes
  - model-horizontal-curvature-and-evaluate-design-consistency
related_skills_for_graph_view:
  - "[[calibrate-desired-speed-and-evaluate-speed-enforcement]]"
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[implement-variable-speed-limits]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[screen-network-safety-with-spf-and-empirical-bayes]]"
  - "[[model-horizontal-curvature-and-evaluate-design-consistency]]"
---

# Driver Desired Speed and Speed-Enforcement Evaluation

SUMO's free-flow speed is `min(vType maxSpeed, speedFactor × posted_limit)`, where
`speedFactor` is a per-vehicle draw from a distribution. Every other calibration
page in this memory concerns *longitudinal dynamics*
([[car-following-parameter-calibration-and-identifiability]]); this one concerns
the *speed-choice* layer sitting on top of it, and what happens when that layer is
used to evaluate a spatially localised policy.

All figures below come from a 4.0 km two-lane-per-direction 50 km/h arterial in
SUMO 1.27.1, demand 1200 veh/h/direction (v/c ≈ 0.30, uncongested), 9 treatment
arms × 8 Common-Random-Number seeds = 72 runs, with **0 teleports, 0 collisions,
0 vehicles left running at simulation end, and 4800/4800 eastbound trips
completed in every arm**. Common random numbers were verified rather than
assumed: the per-vehicle speedFactor map was byte-identical across all nine arms
for every seed, and the compliant driver sets were confirmed nested across the
compliance sweep.

## Verified: what the three speedFactor syntaxes actually sample

Measured with `traci.vehicle.getSpeedFactor` at departure, n = 3000 per case:

| vType spec | CLI | realised mean | realised SD |
|---|---|---|---|
| `speedFactor="normc(1.0,0.1,0.2,2.0)"` | — | 1.0002 | 0.1022 |
| `speedFactor="1.2"` | — | 1.2002 | 0.1022 |
| `speedFactor="1.2" speedDev="0.15"` | — | 1.2004 | 0.1533 |
| `speedFactor="1.2"` | `--default.speeddev 0.25` | 1.1999 | 0.2534 |
| *(none)* | `--default.speeddev 0.25` | 1.0014 | 0.2539 |
| `speedFactor="1.2" speedDev="0"` | — | 1.2000 | 0.0000 |

**A scalar `speedFactor` is a distribution, not a constant.** `speedFactor="1.2"`
alone produced SD 0.1022 — draw-for-draw the default distribution shifted by
+0.2 (sample min 0.771 vs 0.571, max 1.5446 vs 1.3446). The realised SD equals
`speedDev` when given and `--default.speeddev` otherwise; only `speedDev="0"`
removes dispersion. A model that sets `speedFactor="1.2"` intending a
deterministic 20%-over-limit fleet does not get one.

## Verified: `normc` truncation renormalises, and the bounds are absolute [0.2, 2.0]

With `normc(1.0,0.2,0.9,1.1)` (n=8000) the nominal normal places 61.7% of its mass
outside the bounds. If SUMO clipped, that mass would pile up as atoms on the two
bounds. Observed: **0.05% at the lower bound and 0.0125% at the upper**.
Kolmogorov–Smirnov against a renormalised truncated normal = **0.0094**; against a
clipped normal = **0.3086** (5% critical value 0.0152). The asymmetric case
`normc(1.0,0.2,0.95,1.4)` gave 0.0079 vs 0.4014. SUMO rejection-samples until the
draw falls inside the interval.

The scalar + `speedDev` syntax receives **absolute** bounds `[0.2, 2.0]`, not
`mu ± 2·speedDev`:

| spec | sample min | sample max | mass below mu−2σ | mass above mu+2σ | SD/speedDev |
|---|---|---|---|---|---|
| `1.0 / 0.5` | 0.2005 | 1.9992 | 0 | 0 | 0.831 |
| `1.5 / 0.3` | 0.2131 | 1.9997 | 2.25% | 0 | 0.903 |
| `0.5 / 0.2` | 0.2001 | 1.3140 | 0 | 2.71% | 0.890 |

`speedFactor="1.0" speedDev="0.5"` produced mean 1.0324 and SD 0.4157 against
truncated-normal theory values 1.0309 and 0.4144 — agreement to 0.0015 and 0.0013.
**Practical consequence: a large `speedDev` silently biases the realised mean
upward**, because the 0.2 floor bites at −1.6σ while the 2.0 ceiling is +2.0σ
away. Above roughly `speedDev = 0.25` the vType's nominal factor is no longer the
population mean.

## Verified: attainment, and what interferes

| case (n=600) | max realised / (sf × limit) | within 1% |
|---|---|---|
| free link, `departSpeed="desired"` | 1.00008 (SD 0) | 100% |
| free link, `departSpeed="0"` | 0.99977 | 100% (median 7 s to reach it) |
| `maxSpeed="14.5"` | 0.8958 | 27.2% |
| `speedFactorPremature="0.5"`, no `<stop>` on route | 1.00008 | 100% |

On a free link a vehicle attains its desired speed **exactly** — the residual
1.00008 is `netconvert`'s 2-decimal rounding of the lane speed (50 km/h authored →
13.89 m/s = 50.004 km/h compiled), not a behavioural effect. **`maxSpeed` is the
interference that matters**: at 14.5 m/s it truncated 72.8% of the population, and
realised speed then tracked `min(maxSpeed, sf × limit)` to within 0.002%.
**`speedFactorPremature` had no measurable effect** without a scheduled `<stop>`.
`speedFactor` is drawn **once per vehicle** — 60 consecutive samples of 5 vehicles
returned one distinct value each.

## Verified: the naive calibration parameters are wrong by 5%

Fitting a spot-speed target of mean 56.0 km/h and 85th percentile 64.0 km/h on a
50 km/h road, by fixed-point iteration on the two moments against an E1 detector's
per-vehicle records, converged in four iterations to
**`normc(1.17563, 0.17517, 0.2, 2.0)`**, achieving mean 56.052 km/h (error
+0.052) and 85th percentile 64.001 km/h (error +0.0008), SD 8.050, n = 1805.

The naive closed form — `mu = target_mean / posted_limit` = 1.1199 — produced a
measured spot mean of only **53.42 km/h**. The fitted mu is **1.0498× the naive
value** and the fitted sigma **1.135×** the naive `(p85−mean)/posted/z₀.₈₅`.
Car-following suppresses realised speed below desired speed even at v/c ≈ 0.30, so
the generating distribution must be specified materially above the field target.
**Always close the calibration loop against measured detector output.**

Use per-vehicle records from an `<instantInductionLoop>` for a percentile target;
the aggregated `<inductionLoop>` interval gives `speed` and `harmonicMeanSpeed`
but no distribution.

## Verified: three "mean speeds", two gaps, opposite signs

Measured at the same location on the same calibrated runs:

| quantity | km/h |
|---|---|
| generating distribution (mean speedFactor × limit) | 58.985 |
| E1 point detector, arithmetic mean of per-vehicle spot speeds | 56.052 |
| SUMO's own aggregated E1 `speed` field, flow-weighted | 56.005 |
| SUMO's own aggregated E1 `harmonicMeanSpeed` field | 55.047 |
| FCD space-mean over the same segment (Edie: Σv·Δt / ΣΔt) | 54.871 |
| FCD space-mean (harmonic mean of per-vehicle traversal speeds) | 54.836 |

- **Detector time-mean − space-mean = +1.182 km/h**, against Wardrop's prediction
  `σ²_space / v_space` = **+1.200 km/h** — agreement to 0.018 km/h. This confirms
  and quantifies, on the speed-choice side, the structural loop bias documented in
  [[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]].
- **Detector time-mean − generating-distribution mean = −2.933 km/h.**

**Correction to a common claim.** A point detector does *not* flow-weight the
sample above the population mean when each vehicle passes once: 603
instant-loop `enter` records were logged for 600 eastbound vehicles (1.005 per
vehicle, the excess being lane changes over the loop), so the detector sample *is*
the departure population, unweighted, and it sits **below** the desired-speed
distribution because car-following holds vehicles under their desired speed. What
the detector *does* overstate is the **space-mean**, by exactly the Wardrop amount.
Establish which of the three quantities is being compared before asserting a
direction of bias.

**Field spot-speed targets should be calibrated against the E1 time-mean**, since
field spot-speed studies and the speed–crash literature are both built on point
measurements. Calibrating the generating distribution to 56 km/h would leave the
corridor ~2.9 km/h slow; calibrating against the space-mean would leave it
~1.2 km/h fast.

## Verified: a posted-limit reduction rescales the distribution and leaves the violation rate invariant

Because desired speed is multiplicative, lowering the sign from 50 to 40 km/h with
no enforcement rescales everything (8 seeds, ~4800 spot observations per arm):

- mean ratio **0.79344** [0.79136, 0.79553]; SD ratio 0.805; 85th-pct ratio 0.796
- **violation rate against the own posted limit: 0.7601 → 0.7461** — 76% exceeded
  50 km/h before, 75% exceeded 40 km/h after
- fraction over own limit + 10 km/h: 0.3098 → 0.1924

This is the direct signature of a multiplicative desired-speed model, and it is
**not** what field studies of unenforced limit changes find (mean speed moves a
fraction of the sign change; the violation rate rises sharply). **SUMO cannot
represent an unenforced limit change without re-fitting speedFactor for the new
sign** — this must be stated as a modelling caveat in any limit-change study. Two
second-order deviations from exact proportionality are real rather than noise: the
mean ratio is significantly below 0.80 (CI excludes it), a KS test marginally
rejects exact rescaling (0.031 vs critical 0.028), and CV rose 0.1471 → 0.1492 —
all because the same flow at a lower speed is denser and car-following bites harder.

## Verified: `setSpeedFactor` and `setMaxSpeed` are not interchangeable actuators

- **Neither takes effect on the current step.** After the call, the getter reflects
  the new value immediately (`getSpeedFactor` → 1.0, `getMaxSpeed` → 13.89) but
  `getSpeed` is unchanged until the next `simulationStep()`. `setMaxSpeed` leaves
  `getSpeedFactor` untouched.
- **`setSpeedFactor` is limit-relative; `setMaxSpeed` is absolute.** Capped
  vehicles driven onto a link whose posted limit was raised to 20 m/s reached
  19.999 m/s under `setSpeedFactor(1.0)` and exactly 13.89 m/s under
  `setMaxSpeed(13.89)`. Only `setSpeedFactor` models "obey whatever is posted".
- **`setMaxSpeed` brakes at `emergencyDecel`; `setSpeedFactor` brakes at `decel`.**
  From 18.93 m/s: −4.5 m/s² versus **−9.0 m/s²**. An absolute cap is a hard
  constraint SUMO enforces with emergency braking; a factor change is a
  desired-speed change respected with comfortable braking.
- **Both restore heterogeneity correctly if the restored value is right.**
  `setSpeedFactor(own_sf)` and `setMaxSpeed(vType maxSpeed)` each returned 100% of
  vehicles to within 1% of their own desired speed. The naive
  `setMaxSpeed(the speed the vehicle had when capped)` lost 3.7% of the population
  dispersion (SD 2.1031 vs 2.1832 m/s) and only 95% of vehicles recovered. The
  failure mode is the restored *value*, not the *setter* — a sharper statement
  than "use setSpeedFactor to restore heterogeneity".

## Verified: the halo is reproduced, the kangaroo overshoot essentially is not

Halo = contiguous 50 m bins where seed-paired mean speed sits more than 1 km/h
below baseline:

| arm | halo upstream | halo downstream | max reduction | max downstream overshoot |
|---|---|---|---|---|
| point camera, p=0.40 / 0.70 / 0.95 | 300 m | 50 m | −3.53 / −5.29 / −6.61 km/h | +0.15 / +0.26 / **+0.34** km/h |
| section (2 km), p=0.95 | 1000 m | 1050 m | −6.72 km/h | +0.65 km/h |
| posted-limit reduction | whole 4000 m corridor | — | −11.48 km/h | none |

The measured halo reproduces the controller's configured awareness zone almost
exactly (300 m upstream / 30 m downstream configured → 300/50 measured), which is
itself the verification that the controller did what it was told. **SUMO
reproduces the halo but essentially not the overshoot**: the maximum downstream
excess over baseline for the point camera is **+0.34 km/h at 125 m past the
camera**, 19× smaller than the −6.50 km/h reduction it follows. Released drivers
return to exactly their own desired speed and no further, because nothing in the
car-following or speedFactor machinery models time-recovery motivation. **A
simulated speed overshoot is not evidence for the real-world kangaroo effect** —
measure it and expect it to be near zero.

## Verified: measuring at the camera overstates a point camera's benefit by 12x

Nilsson (2004) exponents (injury 2, fatal 4) applied to per-seed speed ratios,
paired, n = 8. (Elvik 2009 exponents 1.5/3.0/4.5 were computed alongside; both
are literature values applied to simulated speed changes, not estimated here.)

| arm | at-camera injury % | corridor-wide injury % | overstatement |
|---|---|---|---|
| point camera p=0.40 / 0.70 / 0.95 | −13.13 / −20.49 / −25.23 | −1.10 / −1.63 / −2.03 | **11.9× / 12.6× / 12.4×** |
| section (2 km) p=0.40 / 0.70 / 0.95 | −14.86 / −21.52 / −25.27 | −7.41 / −10.44 / −12.27 | 2.00× / 2.06× / 2.06× |
| posted-limit reduction (spatially uniform) | −36.98 | −37.26 | **0.99×** |

The uniform-treatment row is the control that proves the mechanism: a spatially
uniform change yields the same answer wherever it is measured. **The overstatement
is a function of how localised the treatment is relative to the measurement
point, and it is stable across compliance levels — a geometry property, not a
compliance property.**

At the camera, point and section enforcement are **statistically
indistinguishable** at p=0.95: paired at-camera speed difference −0.013 km/h,
95% CI [−0.104, +0.078], not significant. Corridor-wide the section version
removes **30.6 additional percentage points** of over-limit vehicle-kilometres
(0.6975 → 0.3920), **17.5 (km/h)² more speed variance**, and delivers **6.0× the
injury-crash reduction** — for 15.2 s more travel time per vehicle. Throughput was
600/600 completed trips in every arm; no treatment cost any throughput.

**The corridor-wide exposure metric that separates the treatments is the fraction
of vehicle-kilometres travelled above the posted limit, not any spot mean speed.**

## Verified: hard braking and SSM conflicts give different answers, and both need auditing

- **Hard braking is a property of the compliance boundary, not the camera type.**
  Both treatments produced comparable counts at p=0.95 (≈441 point vs ≈450
  section) and differ only in *where*: 382 of 441 within ±300 m of the point
  camera, versus ~0 there for the section, which concentrates them at its
  entry. A point camera puts its braking exactly where an evaluator would site
  the before/after detector.
- **Audit the spatial distribution of hard-braking events before reporting a
  count.** The posted-limit-reduction arm showed an apparent 60× increase
  (452.5 vs 7.5 events) — but **98.7% of them sat in the first 200 m**, where the
  limit stepped 50→40 at the study boundary. Excluding that bin the arm is
  statistically indistinguishable from baseline (paired CI [−3.1, +0.8]).
- **The SSM device detected no conflict change from either enforcement treatment**
  (point p=0.95: +0.38 episodes corridor-wide, CI [−4.56, +5.31]; −0.75 near the
  camera, CI [−2.58, +1.08]; section p=0.95 similarly null), despite a
  ~340× increase in hard-braking events near the camera (1.1 baseline vs 382.0
  at point p=0.95, +381 events/run). The mechanism: the
  deceleration is **coordinated** — every compliant driver brakes at the same
  location, so following distances and closing speeds stay comfortable and TTC
  never approaches threshold. **Hard braking counts the manoeuvre; TTC/DRAC count
  the interaction.** Baseline minimum TTC never fell below ~3.4 s, so the device
  is operating far from its severity range on a free-flowing arterial — log with
  a wide threshold and filter afterwards, and de-duplicate, since SUMO writes each
  encounter twice with the roles swapped (see [[surrogate-safety-measures]]).
- **The actuator choice changes the safety statistics with speed held fixed.**
  `setMaxSpeed` and `setSpeedFactor` gave identical at-camera speed
  (+0.005 km/h, n.s.) but `setMaxSpeed` **doubled near-camera SSM conflicts**
  (13.88 vs 6.88, CI [+4.5, +9.5]) while *reducing* hard-braking count by 96 near
  the camera — fewer, harsher events, worst deceleration −9.0 m/s² versus
  −5.4 m/s². A study using `setMaxSpeed` that concluded "the camera creates
  conflicts" would be reporting its own actuator.

## Verified: `timeLoss` inverts under a speed intervention

The confounding documented in [[variable-speed-limits-and-e2-detectors]] appears
here in a sharper form: `timeLoss` did not merely understate the cost, it changed
**sign**. Point camera p=0.95: `timeLoss` −0.69 s while `duration` +2.63 s.
Section p=0.95: `timeLoss` −2.30 s while `duration` +17.87 s. The posted-limit
arm: `timeLoss` +7.14 s while `duration` +69.90 s. **Use `duration`** for any
comparison in which posted limits or commanded speeds differ between arms.

## Reconciling the three verdicts

For the point camera at 95% compliance:

1. **at-camera power model: −25.2% injury, −44.1% fatal** — correctly computed,
   for the 350 m of road inside the halo;
2. **corridor-wide power model: −2.0% injury, −4.0% fatal** — also correct, and
   12.4× smaller, because 3650 m of the 4000 m corridor is untouched (the upstream
   control detector at x=600 showed +0.04% injury change, CI [−0.12, +0.20]);
3. **conflict evidence: no detectable change anywhere.**

(1) and (2) do not contradict — they are the same estimator on different spatial
supports, and their *ratio* is the finding. (3) contradicts the usual expectation
that camera-induced braking is a safety disbenefit, and does so for an
identifiable reason (coordinated deceleration), tested only at v/c ≈ 0.30 —
higher demand or more heterogeneous compliance would be expected to separate the
two, and this study does not test that.

**The measurement location that lets an evaluator overstate a point camera's
benefit is the camera site itself**, where the estimate is indistinguishable from
what 2 km of section enforcement delivers. A defensible evaluation protocol
states the spatial support of every reported speed change, uses
vehicle-kilometres above the limit as the primary exposure metric rather than a
spot mean, and requires an upstream control site — the diagnostic that reveals a
benefit to be purely local.

See the `calibrate-desired-speed-and-evaluate-speed-enforcement` skill for the full
build/characterise/calibrate/enforce/measure workflow and the bundled scripts.
