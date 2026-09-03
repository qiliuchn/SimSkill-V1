---
name: calibrate-desired-speed-and-evaluate-speed-enforcement
description: Use this skill when the user wants to treat DRIVER DESIRED SPEED as a calibrated, heterogeneous population property in SUMO — fitting a vType speedFactor distribution to field spot-speed targets (mean and 85th percentile) — or wants to evaluate AUTOMATED SPEED ENFORCEMENT (point speed cameras, section/average-speed enforcement, posted-limit reductions) with partial driver compliance, including the kangaroo/halo effect, vehicle-kilometres-over-limit exposure, and Nilsson power-model crash estimates. Covers what speedFactor's three syntaxes actually sample, whether normc truncation clips or renormalises, the time-mean vs space-mean vs generating-distribution three-way speed gap, the setSpeedFactor-vs-setMaxSpeed actuator difference, and the finding that a point camera's measured benefit is overstated ~12x when measured at the camera. Trigger on mentions of speedFactor, speedDev, desired speed distribution, 85th percentile speed, spot speed study, speed camera, section control, average speed enforcement, speed limit compliance, kangaroo effect, or Nilsson/Elvik power model.
---

# Calibrate Desired Speed and Evaluate Speed Enforcement

Treats SUMO's `speedFactor` as a *calibratable population distribution* rather
than a nuisance parameter, then uses it to answer a question no other skill in
memory addresses: **how much of a localised speed treatment's measured benefit is
real, and how much is an artifact of measuring it where the treatment is
strongest.** This is the speed-choice analogue of
`calibrate-car-following-parameters-against-field-targets` (which fits
longitudinal dynamics) and it shares
`emulate-and-evaluate-partial-sensor-traffic-state-estimation`'s concern with
what a sensor actually reports versus what is true.

## Build the corridor so that x IS the corridor distance

Author a straight arterial in plain XML (nodes on `y=0`, spaced 200 m) →
`netconvert`, with `--offset.disable-normalization true`. **Without that flag
netconvert shifts the coordinate origin** (verified: a corridor authored from
x=−400 came back with `netOffset="400.00,0.00"`, so `traci.vehicle.getPosition()`
was 400 m off) — and the whole spatial analysis depends on `getPosition()[0]`
being the corridor station directly. Add a 400 m approach edge before the
measured section and use `departSpeed="desired"` so vehicles are already at their
desired speed at station 0. Also pass `--junctions.limit-turn-speed -1` so the
through movements at the 20 intermediate junctions are never derated.

**The compiled posted limit is not the authored one.** netconvert rounds lane
speed to 2 decimals: 50 km/h → `13.89` m/s = 50.004 km/h. Read the limit out of
the compiled net and use *that* number for every threshold, or every
"fraction over the limit" statistic carries a systematic error.

## What speedFactor actually is — verify, don't read the docs

`scripts/stage1_characterize.py` and `scripts/stage1b_bounds.py` answer this
empirically, using `traci.vehicle.getSpeedFactor` at departure (and
`vehicle.remove()` immediately after, so a 8000-vehicle distribution probe costs
seconds rather than minutes).

- **A scalar `speedFactor` is a distribution, not a constant.**
  `speedFactor="1.2"` alone produced SD 0.1022 — the `--default.speeddev` value
  (0.1), not zero. The realised SD equals `speedDev` when given and
  `--default.speeddev` otherwise; only `speedDev="0"` is deterministic.
- **`normc` truncation RENORMALISES (rejection-samples), it does not clip.** With
  `normc(1.0,0.2,0.9,1.1)` the nominal normal puts 61.7% of its mass outside the
  bounds, yet only 0.06% of draws landed exactly on a bound; KS against a
  renormalised truncated normal was 0.0094 versus 0.309 against a clipped one.
- **The scalar+`speedDev` syntax gets ABSOLUTE bounds `[0.2, 2.0]`**, not
  `mu ± 2·speedDev` — confirmed by three probes whose samples cut off at
  0.2005/0.2131/0.2001 and 1.9992/1.9997 regardless of mu and dev, with 2.25%
  and 2.71% of mass sitting outside `mu ± 2·dev`. **Consequence: a large
  `speedDev` silently biases the realised mean upward** (the 0.2 floor bites long
  before the 2.0 ceiling), so the vType's nominal factor stops being the
  population mean once `speedDev` exceeds roughly 0.25.
- **speedFactor is drawn once per vehicle** — 60 consecutive samples of 5
  vehicles gave 1 distinct value each.
- **On a free link the vehicle attains `speedFactor × limit` exactly**
  (ratio 1.00008 = the netconvert rounding, SD 0), reaching it in a median 7 s
  from standstill. **`maxSpeed` is the interference that matters**: set to
  14.5 m/s it truncated 72.8% of the population and realised speed then tracked
  `min(maxSpeed, sf × limit)` to 0.002%. **`speedFactorPremature` had no effect**
  — it only applies to arriving early at a scheduled `<stop>`.

## Calibrating to a spot-speed target — and why the naive parameters are wrong

`scripts/stage1_calibrate.py` runs a two-moment fixed-point iteration against an
E1 detector's per-vehicle spot speeds:

```
mu    <- mu    * target_mean / measured_mean
sigma <- sigma * (target_p85 - target_mean) / (measured_p85 - measured_mean)
```

Four iterations, 3 seeds each, hit mean 56.052 km/h (target 56.0) and 85th
percentile 64.001 km/h (target 64.0) on a 50 km/h road, giving
`normc(1.17563,0.17517,0.2,2.0)`.

**Do not set `mu = target_mean / posted_limit`.** That naive value (1.1199) gave a
measured spot mean of only 53.42 km/h. The fitted mu is **5.0% higher** and the
fitted sigma **13.5% higher** than the naive closed form, because car-following
suppresses realised speed below desired speed even at v/c ≈ 0.30. Always close
the loop against measured detector output.

**Use per-vehicle spot speeds, not the aggregated E1 `speed` field, for a
percentile target.** Add an `<instantInductionLoop>` alongside the
`<inductionLoop>`: the aggregated interval gives you `speed` and
`harmonicMeanSpeed`, but the 85th percentile needs the per-vehicle records
(`state="enter"`). Confirm the record count (603 records for 600 vehicles here —
the excess is lane changes over the loop, not double counting).

## The three-way speed gap — get the sign right

Three different "mean speeds" exist and two of the gaps run in *opposite*
directions. Measured at the same location on the same calibrated runs:

| quantity | km/h |
|---|---|
| generating distribution (mean speedFactor × limit) | 58.985 |
| E1 point detector, arithmetic mean of per-vehicle spot speeds | 56.052 |
| SUMO's own E1 `harmonicMeanSpeed` field | 55.047 |
| FCD space-mean over the same segment (Edie: Σv·Δt / ΣΔt) | 54.871 |

- **Detector time-mean − space-mean = +1.182 km/h**, against Wardrop's prediction
  `σ²_space / v_space` = **+1.200 km/h** — agreement to 0.018 km/h. Compute the
  space mean two ways (Edie's definition and the harmonic mean of per-vehicle
  traversal speeds) as a cross-check; they agreed to 0.035 km/h.
- **Detector time-mean − generating-distribution mean = −2.933 km/h.**
  **A point detector does NOT flow-weight the sample above the population mean
  when each vehicle passes once** — the detector sample *is* the departure
  population, and car-following pulls it *below* the desired-speed distribution.
  The common claim that a loop over-samples fast vehicles applies relative to a
  *spatial* population (which it does, exactly by the Wardrop amount), not
  relative to the generating distribution. Check which comparison is being made
  before asserting a direction.
- **Calibrate against the E1 time-mean**, because field spot-speed studies and
  the speed–crash literature are both built on point measurements.

## The enforcement controller: two actuators that are not interchangeable

`scripts/run_scenario.py` implements four modes (`baseline`, `limit40`, `point`,
`section`) in one stepping loop, with a compliant fraction `p` drawn from a
stream keyed on `(seed, vehicle id)` **only** — so the same vehicle draws the same
`u` in every arm and the compliant sets are *nested* across p. Verify this with
`scripts/verify_crn.py` rather than assuming it.

Measured actuator semantics (`scripts/stage2_actuator_probe.py`):

- **Neither takes effect on the current step.** The getter reflects the new value
  immediately (`getSpeedFactor` → 1.0, `getMaxSpeed` → 13.89) but `getSpeed` is
  unchanged until the next `simulationStep()`.
- **`setSpeedFactor` is limit-relative; `setMaxSpeed` is absolute.** Capped
  vehicles driven onto a link whose limit was raised to 20 m/s reached 19.999 m/s
  under `setSpeedFactor(1.0)` and exactly 13.89 m/s under `setMaxSpeed(13.89)`.
  For "obey whatever is posted", only `setSpeedFactor` is correct.
- **`setMaxSpeed` brakes at `emergencyDecel`, `setSpeedFactor` at `decel`.**
  From 18.93 m/s: −4.5 m/s² under `setSpeedFactor`, **−9.0 m/s² under
  `setMaxSpeed`**. This is the single most important gotcha in the skill —
  see the actuator-artifact section below.
- **Both restore heterogeneity correctly if you restore the right value.**
  `setSpeedFactor(own_sf)` and `setMaxSpeed(vType maxSpeed)` both returned 100%
  of vehicles to within 1% of their own desired speed. The naive
  `setMaxSpeed(the speed it had when I capped it)` lost 3.7% of the population
  dispersion. The failure mode is the restored *value*, not the *setter*.

## A posted-limit reduction is not modellable without re-specifying speedFactor

Because desired speed is `speedFactor × posted_limit`, lowering the sign rescales
the entire distribution. Verified over 8 seeds and ~4800 spot observations
(`scripts/stage2_limit_reduction.py`), 50 → 40 km/h:

- mean ratio **0.79344** [0.79136, 0.79553], SD ratio 0.805, 85th-pct ratio 0.796
- **violation rate against the OWN posted limit: 0.7601 → 0.7461** — essentially
  invariant. 76% exceeded 50 before; 75% exceeded 40 after.

Field studies of *unenforced* limit changes find the opposite: mean speed moves a
fraction of the sign change and the violation rate jumps. **Report this as a
modelling caveat** — SUMO cannot represent an unenforced limit change at all
unless speedFactor is re-fitted for the new sign. The KS test against exact
rescaling marginally rejects (0.031 vs crit 0.028) and CV rose 0.1471 → 0.1492,
both from the denser traffic at the lower speed — real second-order effects, not
noise.

## Measure exposure over space, not speed at a point

`scripts/compute_metrics.py` reduces each run's FCD to a 50 m spatial profile plus
**vehicle-kilometres above the limit** (`Σ v·Δt` restricted to samples with
`v > limit`). This is the metric that separates the treatments; the spot mean is
the metric that hides the difference. At p=0.95, point vs section enforcement:

| | at-camera E1 time-mean | corridor space-mean | frac veh-km over limit |
|---|---|---|---|
| point camera | 47.938 | 53.759 | 0.6975 |
| section (2 km) | 47.925 | 50.870 | 0.3920 |
| paired diff (section − point) | **−0.013, CI [−0.104, +0.078], n.s.** | −2.889 [−3.007, −2.771] | −0.3055 [−0.3149, −0.2961] |

**At the camera the two are statistically indistinguishable; corridor-wide the
section removes 30.6 more percentage points of over-limit vehicle-kilometres.**

## The halo, and the overshoot SUMO does not produce

`scripts/stage3_analyze.py` measures the halo as the contiguous run of 50 m bins
where seed-paired mean speed sits more than 1 km/h below baseline. The measured
halo reproduces the controller's configured awareness zone almost exactly
(300 m up / 30 m down configured → 300/50 measured; a 1000–3000 m section →
1000/1050), which is itself the check that the controller did what it was told.

**SUMO reproduces the halo but essentially not the "kangaroo" overshoot.** Maximum
downstream excess over baseline was **+0.34 km/h, 125 m past the camera** — 19x
smaller than the −6.50 km/h reduction. Released drivers return to exactly their
own desired speed and no further; nothing in the car-following or speedFactor
machinery models time-recovery motivation. **Do not report a simulated speed
overshoot as evidence for the real kangaroo effect** — measure it, and expect it
to be near zero.

## Three artifacts that will corrupt the safety numbers if unchecked

1. **Hard braking is a property of the compliance BOUNDARY, not the camera.**
   Both treatments produced ≈441 vs ≈450 hard-braking events at p=0.95; they
   differ only in *where* (382 of 441 within ±300 m of the point camera; ~0 there
   for the section, which puts them at its entry). Always report the spatial
   distribution.
2. **Audit where hard-braking events actually occur before reporting a count.**
   The posted-limit-reduction arm showed an apparent 60x increase (452.5 vs 7.5)
   — but **98.7% of its events sat in the first 200 m**, where the limit stepped
   50→40 at the study boundary. Excluding that bin the arm is statistically
   indistinguishable from baseline (paired CI [−3.1, +0.8]). `scripts/stage3_extras.py`
   does this audit; skipping it would have produced a badly wrong headline.
3. **The actuator choice changes the safety statistics with the speeds held
   fixed.** `setMaxSpeed` and `setSpeedFactor` gave identical at-camera speed
   (diff +0.005 km/h, n.s.) but `setMaxSpeed` **doubled near-camera SSM conflicts**
   (13.88 vs 6.88, CI [+4.5, +9.5]) while *reducing* the hard-braking count
   (−96 near camera) — fewer, harsher events, worst deceleration −9.0 m/s²
   versus −5.4 m/s². Run this control arm; a study that used `setMaxSpeed` and
   concluded "the camera creates conflicts" would be reporting its own actuator.

Also: **`tripinfo`'s `timeLoss` is unusable here** (the confounding
[[variable-speed-limits-and-e2-detectors]] documents, in a sharper form). It fell
while `duration` rose in both enforcement arms — point p=0.95 timeLoss −0.69 s
but duration +2.63 s; section p=0.95 timeLoss −2.30 s but duration +17.87 s.
Use `duration`.

## Nilsson's power model, applied at two spatial supports

Apply the literature exponents (Nilsson 2004: injury 2, fatal 4; Elvik 2009:
slight 1.5, serious 3.0, fatal 4.5) to the **per-seed** speed ratio, then take the
paired mean and CI — not the exponent of the mean ratio. `scripts/stage3_analyze.py`
does this at three supports: the camera detector, the corridor space-mean, and an
upstream control detector.

**The headline: measuring at the camera overstates a point camera's benefit by
~12x, and the overstatement is a geometry property, not a compliance property.**

| arm | at-camera injury % | corridor-wide injury % | overstatement |
|---|---|---|---|
| point p=0.40 / 0.70 / 0.95 | −13.13 / −20.49 / −25.23 | −1.10 / −1.63 / −2.03 | **11.9× / 12.6× / 12.4×** |
| section p=0.40 / 0.70 / 0.95 | −14.86 / −21.52 / −25.27 | −7.41 / −10.44 / −12.27 | 2.00× / 2.06× / 2.06× |
| posted-limit reduction (uniform) | −36.98 | −37.26 | **0.99×** |

The uniform-treatment row is the control that proves the mechanism: a spatially
uniform change gives the same answer wherever you measure. **Always include one.**

## Reconciling the power model against the conflict evidence

Three verdicts on the same point camera at p=0.95:

1. at-camera power model: **−25.2% injury, −44.1% fatal**
2. corridor-wide power model: **−2.0% injury, −4.0% fatal** (12.4× smaller)
3. SSM conflicts: **no detectable change anywhere** (+0.38 episodes corridor,
   CI [−4.56, +5.31]; −0.75 near camera, CI [−2.58, +1.08])

(1) and (2) do not contradict — they are the same estimator on different spatial
supports, and their *ratio* is the finding. (3) contradicts the usual expectation
that camera-induced braking is a disbenefit: 382 hard-braking events per run
appeared near the camera against a baseline of 1.1, with **no** SSM conflict
increase, because the deceleration is **coordinated** — every compliant driver
brakes at the same place, so following distances and TTC stay comfortable.
**Hard braking counts the manoeuvre; TTC/DRAC count the interaction.** Report
both; do not treat a hard-braking increase as automatic evidence of conflict risk,
and do not treat a null SSM result as proof that hard braking is harmless (this
was tested at v/c ≈ 0.30 only).

**Which measurement location lets an evaluator overstate a point camera:
the camera site.** It gives an estimate identical, within noise, to what 2 km of
section enforcement delivers. The defensible protocol: state the spatial support
of every reported speed change, use vehicle-kilometres over the limit as the
primary exposure metric, and require an upstream control site — here x=600
correctly showed +0.04% injury change, CI [−0.12, +0.20], the diagnostic that
reveals a benefit to be purely local.

## Running it

```bash
python scripts/build_network.py --outdir scenario

python scripts/stage1_characterize.py --net scenario/arterial.net.xml --outdir stage1
python scripts/stage1b_bounds.py scenario/arterial.net.xml stage1

python scripts/stage1_calibrate.py --net scenario/arterial.net.xml \
    --outdir stage1 --workdir /tmp/cal --mu0 1.12 --sigma0 0.154 --iters 4

python scripts/stage2_actuator_probe.py scenario/arterial.net.xml stage2

python scripts/run_batch.py --net $PWD/scenario/arterial.net.xml --root $PWD/runs \
    --mu 1.175628 --sigma 0.175172 --seeds 1,2,3,4,5,6,7,8 --jobs 6
python scripts/verify_crn.py $PWD/runs crn_verification.json
python scripts/stage3_analyze.py --root $PWD/runs --outdir analysis
python scripts/stage3_extras.py --root $PWD/runs --out analysis/extras.json
python scripts/stage2_limit_reduction.py --root $PWD/runs --out analysis/limit_reduction.json
```

`run_batch.py` reduces each run to `metrics.json` + `profile.csv` immediately and
then gzips the bulky XML, keeping the FCD only for the first seed of each arm —
72 runs land in ~62 MB with one fully auditable raw run per arm.

## Gotchas

- **`netconvert` normalises coordinates unless told not to** — pass
  `--offset.disable-normalization true` or `traci.vehicle.getPosition()` will not
  be the corridor station.
- **The compiled lane speed is the authored one rounded to 2 decimals** — read the
  limit from the net, not from the input file.
- **A scalar `speedFactor` still carries `--default.speeddev` dispersion**; only
  `speedDev="0"` is deterministic.
- **`normc` bounds are absolute `[0.2, 2.0]` for the scalar+`speedDev` syntax**,
  and truncation renormalises — a large `speedDev` biases the realised mean up.
- **`mu = target/posted` under-shoots the calibration target by ~5%** because of
  car-following; iterate against measured detector output.
- **`setMaxSpeed` brakes at `emergencyDecel` (−9 m/s²)** and is limit-absolute;
  `setSpeedFactor` brakes at `decel` and is limit-relative. Neither takes effect
  on the current step.
- **Audit the spatial distribution of hard-braking events** before reporting a
  count — a treatment boundary at a study edge can generate 98.7% of them.
- **`timeLoss` can fall while `duration` rises** under any speed intervention; use
  `duration`.
- **SSM conflict counts are near-degenerate on a free-flowing arterial** (minimum
  TTC never below ~3.4 s at baseline) — log with a wide threshold (TTC<5,
  DRAC>1.5) and filter afterwards, and de-duplicate: SUMO writes every encounter
  **twice**, once per ego with the roles swapped.

## Related

- `calibrate-car-following-parameters-against-field-targets` — the longitudinal-
  dynamics counterpart; this skill calibrates free-speed choice instead, and both
  share the "close the loop against measured output, not a closed form" discipline.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — established the
  loop time-mean vs space-mean bias; this skill adds the third quantity (the
  generating desired-speed distribution) and shows the two gaps run in opposite
  directions.
- `quantify-sumo-run-to-run-variability` — the CRN and paired-test discipline used
  for every comparison here; `verify_crn.py` is the concrete identity check.
- `implement-variable-speed-limits` — the other posted-speed-limit TraCI
  intervention (`lane.setMaxSpeed` on infrastructure rather than
  `vehicle.setSpeedFactor` on drivers), and the origin of the `timeLoss`
  confounding gotcha this skill reproduces in a sharper form.
- `implement-glosa-speed-advisory-controller` — the other vehicle-side speed
  controller; GLOSA commands absolute speed via `setSpeed`, this one commands the
  limit-relative desired speed, which is what preserves heterogeneity on release.
- `analyze-intersection-safety-with-ssm` — the SSM device setup and encounter-type
  conventions the conflict layer reuses, including the double-logging de-duplication.
- `screen-network-safety-with-spf-and-empirical-bayes` — the crash-prediction layer
  the Nilsson power-model estimates here feed into; both convert a simulated
  quantity into expected crashes and both must state their validity limits.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport /
  completion accounting discipline applied here (0 teleports, 0 unfinished trips).
- `analyze-simulation-outputs` — tripinfo/summary parsing conventions, including
  the cumulative-`teleports` rule.
- [[driver-desired-speed-and-speed-enforcement-evaluation]] — the verified
  speedFactor semantics, the calibration, the three-way speed gap, the actuator
  difference, and the 12x measurement-location overstatement finding.
