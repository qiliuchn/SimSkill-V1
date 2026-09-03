---
name: model-demand-arrival-process-and-its-effect-on-capacity-and-delay
description: Use this skill when the user wants to specify or verify the ARRIVAL PROCESS behind a SUMO demand volume (deterministic vehsPerHour, Poisson period="exp()", flow probability=, randomTrips --binomial, a Cowan M3 / shifted-exponential bunched stream, or a stepped PHF profile), needs to know whether the choice of arrival process actually matters for a result, or is evaluating unsignalized (TWSC/roundabout) capacity against HCM's gap-acceptance formulas. Covers why the realized process at a detector is never what the flow spec promises (a hard car-following headway floor, per-timestep vs per-schedule randomness, discrete departure grids), why unsignalized capacity can swing more than an order of magnitude at a single hourly volume purely from arrival-process choice, how to measure SUMO's own effective critical gap/follow-up time from a deterministic-arrival staircase, and how platoon dispersion actually arises (desired-speed heterogeneity, not distance). Trigger on mentions of arrival process, headway distribution, Poisson arrivals, deterministic arrivals, Cowan M3, gap acceptance, critical gap, follow-up time, randomTrips binomial, or "does the demand distribution matter."
---

# Model Demand Arrival Process and Its Effect on Capacity and Delay

**Every prior demand-generation skill in memory treats the arrival process as
an unexamined default.** This skill treats it as the modeling object it is:
specified, verified at the network boundary AND at every downstream
detector, and held accountable for how much it actually changes an
engineering conclusion. Verified on 3110 CRN-replicated SUMO runs across a
pretimed signal, a two-way-stop-controlled (TWSC) minor approach, and a
single-lane roundabout entry, all fed an identical major-street volume.

## What SUMO actually delivers is never what the spec promises

Verify at the source AND at a downstream detector with a discrete-aware KS
test — never trust a flow tag's name.

- **`period="exp(rate)"` genuinely produces a Poisson schedule at the
  planned/insertion plane** (KS D 0.019–0.040 against the exponential,
  never rejected at α=0.01). **It stops being Poisson the moment it meets
  car-following.** A hard minimum headway (measured 1.58 s in this
  testbed) truncates the distribution, and the resulting KS distance obeys
  an exact identity: `D = F_intended(h_min)`. Verified: predicted
  `1 − exp(−1.58/3.0) = 0.40943`, measured from raw detector XML at
  V=1200 = **0.40943**. Realised CV falls from 1.00 (planned) to 0.842
  (measured, V=1200) purely from this floor — no code bug, just physics
  meeting a stochastic spec.
- **`<flow probability="p">` is a per-TIMESTEP Bernoulli draw, so its
  realized process depends on `--step-length`**, even though the spec
  string never changes. Measured at V=1200: CV 0.811 at dt=1.0 s (minimum
  headway exactly 1.0 s) vs CV 0.961 at dt=0.1 s. `period="exp()"` is
  dt-invariant at the planned plane (KS D ≈ 0.028 at every tested dt) —
  prefer it over `probability=` whenever the result must not depend on an
  unrelated simulation setting.
- **`randomTrips --binomial 1` is a 1-second-slot geometric process, not
  exponential** — departures land only on integer seconds, and a
  continuous-data KS test against the exponential scores the largest
  single atom (naive D ≈ 0.33 at p≈0.33) rather than the genuine fit
  quality (discrete-aware D ≈ 0.02 against the geometric). **Always use a
  discrete-aware goodness-of-fit test for slot-based generators** — a
  naive KS test will report a "bad fit" for a mathematically correct
  discrete process. `--binomial 4` produced 12.2% exactly-zero headways at
  V=1200 (multiple vehicles per slot) — check for this before assuming a
  fine-grained binomial approximates continuous arrivals.
- **Insertion saturation shows up as `departDelay`, not as
  `never_inserted`.** Even at V=1800 veh/h on a 600 m single-lane feeder,
  zero vehicles failed to insert in this testbed — but Poisson-source mean
  `departDelay` rose from 0.65 s to 3.26 s (p95: 15.19 s, 43.5% of
  vehicles delayed >1 s) between V=1400 and V=1800, and realised CV
  collapsed from 0.786 to 0.575 as insertion queuing itself regularizes
  the stream. Check `departDelay`, not just `never_inserted`, for
  insertion-capacity effects.
- **A shifted-exponential/Cowan M3 bunched stream cannot stay bunched
  indefinitely as volume rises** — its CV fell from 2.12 (V=400) to 0.27
  (V=1800) as mean headway approached the minimum bunch spacing Δ. A
  "75%-bunched" specification is only meaningfully bunched below roughly
  half the corresponding saturation flow.
- **Replication-design consequence:** run-to-run standard deviation of the
  *realised* hourly volume scales with the arrival process's own CV
  (renewal theory `sd ≈ √(V·CV²)`, matched to within 0.7–1.25× in this
  testbed: deterministic 0.0, Poisson 29.6, cowan75 45.6 veh/h at V=800,
  10 seeds) — a bunchier spec needs more replications for the same
  confidence interval width, quantifiably, not just qualitatively.

## Unsignalized capacity can swing an order of magnitude at one hourly volume

Measured entry capacity via a permanently-queued minor-approach probe, 10
CRN seeds, steady-state window only (the probe has its own queue-formation
transient — discard the ramp-up):

| TWSC capacity, conflicting flow V=800 veh/h | det | cowan30 | bin | poi | cowan75 | HCM (random) |
|---|---|---|---|---|---|---|
| veh/h | **40.2** | 478.4 | 466.4 | **521.6** | **870.6** | 320.4 |

That is a **~13× swing at a single hourly volume purely from arrival-process
choice**, and the assumption-matched Poisson spec still over-shoots HCM's
own formula by +62.8% (see the mechanism below). At the roundabout entry
the same volume gives det 57.2 / poi 368.6 / cowan75 572.7 veh/h against
an HCM prediction of 507.7. Error versus HCM's random-arrival formula
spans **−87.5% (deterministic) to +171.7% (cowan75)**, entirely from
arrival-process choice at fixed mean volume.

**The ordering flips with volume, and CV predicts exactly when.** At
V=1200 a moderately-bunched Cowan stream (cowan30) gives *lower* TWSC
capacity than Poisson (112.2 vs 255.3 veh/h, −56%) — the reverse of the
V=400 ordering — because that spec's realised CV is above Poisson's at low
volume (1.09 at V=400) and below it at high volume (0.55 at V=1200) as
saturation compresses the bunching. **Conflicting-stream CV, not the
distribution's name, is the sufficient statistic**: adding measured CV to
a flow-only log-capacity regression (excluding the degenerate
deterministic arm) raises R² from 0.854→0.977 (TWSC) and 0.936→0.991
(roundabout), and cuts RMSE from 47%→14% and 30%→12% respectively.

## Why SUMO disagrees with HCM: measure the effective t_c/t_f directly, don't assume it

An equidistant (deterministic) conflicting stream makes measured capacity
a **staircase** — vehicles can only enter in the gap between conflicting
arrivals, so capacity jumps at headways `h0 = t_c, t_c + t_f, t_c + 2t_f, …`.
Sweeping conflicting headway and reading the risers off the empirical
capacity curve gives SUMO's own effective values directly, no formula
assumed:

| | SUMO measured (this testbed) | HCM |
|---|---|---|
| TWSC critical gap `t_c` | 6.75 s | 6.5 s |
| TWSC follow-up time `t_f` | **2.25 s** | 4.0 s |
| Roundabout critical gap `t_c` | 8.0 s | 5.19 s |
| Roundabout follow-up time `t_f` | 0.49 s | 3.19 s |

SUMO's TWSC critical gap matches HCM closely, but its follow-up time is
**roughly half** HCM's — that single parameter accounts for most of the
TWSC over-prediction against HCM's random-arrival formula. At the
roundabout, SUMO's critical gap is genuinely *larger* than HCM's, which
**reverses the HCM capacity ordering**: HCM predicts the roundabout beats
the stop-controlled crossing (507.7 vs 320.4 veh/h at V=800), while SUMO's
own measured behavior has the TWSC crossing beating the roundabout
(521.6 vs 368.6 veh/h, Poisson arrivals) — a genuine, verified SUMO
modeling-gap finding, not a parameterization choice.

**Robustness check, and an honest limitation of it.** Rebuilding the
roundabout at a larger radius plus a faster ring speed together
(`rbt_big`) and at the baseline radius with only a faster ring speed
(`rbt_fast`) both preserve the TWSC-beats-roundabout ordering at V=800
Poisson arrivals (395.4 and 327.6 veh/h respectively, both below the
TWSC's 521.6). Only `rbt_fast` cleanly isolates a single factor (ring
speed 8.33→11.11 m/s at fixed ring-edge length 16.66 m, verified from the
compiled net); `rbt_big` changed both ring radius (16.66→28.14 m) and ring
speed simultaneously (verified from the compiled net), so it should be
described as "a larger, faster ring," not a radius-only isolation — the
script that generated these two specific variants was not preserved,
which is itself a reproducibility gap worth disclosing rather than hiding.

## Real platoons: capacity impact is large, and the dispersion mechanism is desired-speed heterogeneity, not distance

Physically generating platoons via an upstream signal (rather than
statistically specifying bunching) at TWSC, V=800, D=300 m: minor-approach
capacity rose from 521.6 veh/h (no upstream signal) to 992.3 veh/h (with
it) — **+470.7 veh/h, 95% CI [+447.2, +494.2]**, roughly matching the
platoon/no-platoon gap already measured for the *statistical* cowan75
spec above. Roundabout: 368.6 → 594.6 veh/h (+61.3%).

**Isolating the dispersion mechanism required a matched-baseline
comparison, not a cross-series splice.** At each tested distance
(150/300/600/1000/1500 m), holding `speedDev=0` (no desired-speed
heterogeneity) leaves capacity essentially flat (994.1 → 989.6 → 989.4
veh/h across the full range, platoon phase concentration ≈ 1.000 at every
distance). Holding `speedDev=0.10` at the *same* distances gives a real
decline from 976.2 veh/h (D=150 m) to a trough of 888.5 veh/h (D=1000 m,
paired diff −101.1, p=1e−6), with a **partial, non-monotonic recovery to
907.5 veh/h at D=1500 m** — the capacity series itself is noisier than a
clean monotonic decline. The platoon phase-concentration index is the
cleaner signal: it declines monotonically under `speedDev=0.10`
(0.983 → 0.933 → 0.845 → 0.747 → 0.657) while staying flat under
`speedDev=0` at every distance. **Platoon dispersion in SUMO is caused by
desired-speed heterogeneity between vehicles, not by distance or
car-following noise alone** — report the concentration index as primary
evidence for this mechanism and the capacity numbers as a noisier,
directionally-consistent secondary signal, not as a clean monotonic curve.

Downstream signal offset, independent of platoon strength, swings major
delay by itself: 0.40 s to 18.24 s purely on offset at fixed volume and
distance, with the delay-minimizing offset tracking `(D / free-flow
speed) mod cycle length` exactly at all five tested distances.

## Decision rule: does arrival-process choice matter, and how does it compare to a real treatment?

| Control / metric | Low volume | Mid volume | High volume |
|---|---|---|---|
| Signal, major control delay | **immaterial** (no spec differs from Poisson at p<0.01) | marginal (spec range 17.6% of the Poisson mean, ~43% of a +5s-green-split treatment effect) | **matters** (spec range 52.7% of the Poisson mean, exceeding the +5s-green-split effect) |
| Signal, Q95 major queue | matters at every level tested | | |
| Signal, minor delay | **immaterial everywhere — structurally**, because an exclusive-phase signal's minor approach cannot depend on the major stream's arrival process at all | | |
| TWSC capacity/minor delay | **matters at every volume tested**, spec range exceeding what an added minor-approach lane buys | | |

Direction is consistent: bunching (high realised CV) is **optimistic** for
unsignalized capacity and **pessimistic** for signal delay/queue;
deterministic `<flow vehsPerHour>` is **catastrophically pessimistic** for
unsignalized capacity whenever the mean headway (3600/V) falls below the
facility's own critical gap.

## Gotchas

- **The roundabout re-shapes its own conflicting stream at high
  circulating flow** — above roughly 800 veh/h in this testbed, queuing at
  the circulating approach itself regularizes headways (measured CV
  collapsing from 1.04 at V=200 to 0.196 at V=1400), so arrival-process
  conclusions at a roundabout are only clean below that point; the TWSC
  arm's major-approach delay stayed negligible (≤0.09 s) throughout,
  making it the cleaner facility for high-volume arrival-process work.
- **A flared 2-lane approach can be an invalid yardstick, not a finding.**
  A flared minor-approach and roundabout-entry variant tested in this
  episode *reduced* measured capacity and accounted for **100% of every
  teleport in the entire 3110-run study** (1563 teleports on that one
  network, exactly 0 on every other network tested) — its compiled
  geometry also shrank unexpectedly relative to the single-lane baseline.
  It was withdrawn as an invalid comparison rather than reported as a
  negative result; check teleport counts per network before trusting any
  capacity comparison that includes a geometry variant.
- **Measured gap-acceptance capacity is `--step-length`-fragile**, partly
  because step length itself changes the realised arrival-process CV:
  TWSC capacity rose 427.5→539.7 veh/h (+26%) and roundabout 243.9→370.8
  (+52%) moving from dt=1.0 s to dt=0.1 s at otherwise identical settings.
  State the step length with any absolute capacity figure.
- **`departDelay` carries a deterministic ≈dt/2 rounding floor** whenever
  3600/V happens to be a multiple of the step length — don't mistake this
  grid artifact for a genuine zero-delay condition.
- **Verify delay-arm censoring is actually zero before trusting an
  oversaturated-demand delay figure**, don't assume it. In this testbed a
  20-minute unloaded drain period cleared every residual queue and
  measured censoring fraction was exactly 0.000 in every delay cell —
  which also means the oversaturated-demand delay figures here are scoped
  to a one-hour demand pulse with recovery time, not a continuously
  oversaturated hour.

See `compare-unsignalized-intersection-control-types` for the TWSC/AWSC
control-type comparison this skill's capacity probe extends,
`measure-roundabout-capacity-and-implement-metering` for the roundabout
geometry and capacity-curve-fitting method reused here, and
`generate-hcm-los-report-and-validate-against-microsimulation` for the
HCM control-delay accounting and upstream-reference truncation diagnostic
also reused here.
