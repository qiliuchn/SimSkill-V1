---
summary: SUMO's arrival-process specs deliver what they promise only at the planned schedule, never at a detector — Poisson period="exp()" is truncated to KS distance F(h_min) by the car-following headway floor, flow probability= is a per-timestep Bernoulli whose realised process depends on --step-length, and randomTrips --binomial is a discrete geometric process a naive KS test misjudges as ill-fitting; the consequence is that measured TWSC minor-approach capacity swings roughly 13x (40 to 871 veh/h) at one fixed conflicting-flow volume purely from arrival-process choice, driven by conflicting-stream headway CV as the sufficient statistic, and a deterministic-arrival staircase reveals SUMO's own effective follow-up time is roughly half HCM's at a TWSC crossing (2.25s vs 4.0s) while its critical gap at a roundabout is larger than HCM's (8.0s vs 5.19s) — reversing HCM's predicted capacity ordering between the two facility types.
keywords:
  - arrival-process
  - headway-distribution
  - poisson-arrivals
  - cowan-m3
  - gap-acceptance
  - critical-gap
  - follow-up-time
  - randomtrips-binomial
  - platoon-dispersion
created: 2026-08-05T18:00:00
last_updated: 2026-08-05T22:30:00
sources:
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/process_fidelity_summary.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/process_fidelity_ecdf.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/randomtrips_verification.json]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partC_summary.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/capacity_cv_regression.json]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partH_critical_gap_staircase.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partH_critical_gap_estimate.json]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partI_roundabout_geometry_check.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partD_platoon_vs_random.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/partD_dispersion_mechanism.csv]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/decision_rule.json]]"
  - "[[episodic-memory/2026-08-05_18-00-00/outputs/analysis/validity_audit_all_runs.csv]]"
related_pages:
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[random-trips]]"
  - "[[intersection-sight-distance-and-sumo-visibility-parameter]]"
related_skills:
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
  - compare-unsignalized-intersection-control-types
  - measure-roundabout-capacity-and-implement-metering
  - generate-hcm-los-report-and-validate-against-microsimulation
  - quantify-sumo-run-to-run-variability
  - model-intersection-sight-distance-restriction-at-a-twsc-junction
related_skills_for_graph_view:
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[model-intersection-sight-distance-restriction-at-a-twsc-junction]]"
---

# Demand Arrival Process and Unsignalized Capacity

Every prior demand-generation page in memory treats the arrival process
behind an hourly volume as an unexamined default. This page treats it as a
modeling object: verified at the network boundary and at every downstream
detector, and held accountable for how much it actually changes an
engineering conclusion — measured across a pretimed signal, a two-way-stop
(TWSC) minor approach, and a single-lane roundabout entry, all fed an
identical major-street volume, 3110 CRN-replicated runs.

## The spec is not the delivered process

`period="exp(rate)"` genuinely produces a Poisson schedule at the
planned/insertion plane (KS distance 0.019–0.040 against the exponential,
never rejected). It stops being Poisson the moment it meets car-following:
a hard minimum headway (measured 1.58 s) truncates the distribution, and
the resulting KS distance obeys an exact identity `D = F_intended(h_min)`
— verified: predicted `1 − exp(−1.58/3.0) = 0.40943`, measured from raw
detector XML at V=1200 = **0.40943**. Realised CV falls from 1.00 (planned)
to 0.842 (measured) from this floor alone.

`<flow probability="p">` is a per-**timestep** Bernoulli draw, so its
realised process depends on `--step-length` even though the spec string is
unchanged: measured CV 0.811 at dt=1.0 s vs 0.961 at dt=0.1 s, at the same
target volume. `period="exp()"` is dt-invariant at the planned plane
(KS D ≈ 0.028 at every tested dt) — prefer it whenever a result must not
depend on an unrelated simulation setting.

`randomTrips --binomial 1` is a 1-second-slot **geometric** process, not
exponential — a continuous-data KS test against the exponential scores the
largest single atom (naive D ≈ 0.33) rather than genuine fit quality
(discrete-aware D ≈ 0.02 against the geometric). Use a discrete-aware
goodness-of-fit test for any slot-based generator. `--binomial 4` produced
12.2% exactly-zero headways at V=1200 — check for this before assuming a
coarse binomial approximates continuous arrivals.

Insertion saturation shows up as **`departDelay`, not `never_inserted`**:
even at V=1800 on a 600 m single-lane feeder, zero vehicles failed to
insert, but Poisson-source mean `departDelay` rose from 0.65 s to 3.26 s
(p95 15.19 s, 43.5% of vehicles delayed >1 s) between V=1400 and V=1800,
and realised CV collapsed from 0.786 to 0.575 as insertion queuing itself
regularizes the stream.

A shifted-exponential/Cowan M3 bunched stream cannot stay bunched
indefinitely as volume rises — its CV fell from 2.12 (V=400) to 0.27
(V=1800) as mean headway approached the minimum bunch spacing.

**Run-to-run variability of the *realised* hourly volume scales with the
arrival process's own headway CV** (renewal theory `sd ≈ √(V·CV²)`,
matched to within 0.7–1.25× here: deterministic 0.0, Poisson 29.6,
cowan75 45.6 veh/h at V=800, 10 seeds) — a bunchier specification needs
more replications for the same confidence-interval width, quantifiably.

## Unsignalized capacity can swing an order of magnitude at one hourly volume

Measured entry capacity via a permanently-queued minor-approach probe (10
CRN seeds, steady-state window only — the probe has its own queue-formation
transient that must be discarded):

| TWSC capacity, conflicting flow V=800 veh/h | det | cowan30 | bin | poi | cowan75 | HCM (random) |
|---|---|---|---|---|---|---|
| veh/h | **40.2** | 478.4 | 466.4 | **521.6** | **870.6** | 320.4 |

A **~13× swing at one fixed hourly volume purely from arrival-process
choice**. The assumption-matched Poisson spec still overshoots HCM's own
formula by +62.8% (mechanism below). At the roundabout entry, same volume:
det 57.2 / poi 368.6 / cowan75 572.7 veh/h against HCM's 507.7. Error
versus HCM's random-arrival formula spans **−87.5% (deterministic) to
+171.7% (cowan75)** from arrival process alone.

**The ordering flips with volume, and CV predicts exactly when.** At
V=1200, a moderately-bunched Cowan stream gives *lower* TWSC capacity than
Poisson (112.2 vs 255.3 veh/h, −56%) — reversed from the V=400 ordering —
because that spec's realised CV sits above Poisson's at low volume (1.09
at V=400) and below it at high volume (0.55 at V=1200) as saturation
compresses the bunching. **Conflicting-stream CV, not the distribution's
name, is the sufficient statistic**: adding measured CV to a flow-only
log-capacity regression (excluding the degenerate deterministic arm)
raises R² from 0.854→0.977 (TWSC) and 0.936→0.991 (roundabout), cutting
RMSE from 47%→14% and 30%→12% respectively.

## Why SUMO disagrees with HCM: a deterministic-arrival staircase measures the real cause

An equidistant conflicting stream makes measured capacity a **staircase**
— entry only happens in the gap between conflicting arrivals, so capacity
jumps at conflicting headways `h0 = t_c, t_c + t_f, t_c + 2t_f, …`.
Sweeping conflicting headway and reading the risers off the empirical
capacity curve gives SUMO's own effective critical gap and follow-up time
directly, with no formula assumed:

| | SUMO measured | HCM |
|---|---|---|
| TWSC critical gap `t_c` | 6.75 s | 6.5 s |
| TWSC follow-up time `t_f` | **2.25 s** | 4.0 s |
| Roundabout critical gap `t_c` | 8.0 s | 5.19 s |
| Roundabout follow-up time `t_f` | 0.49 s | 3.19 s |

SUMO's TWSC critical gap matches HCM closely, but its follow-up time is
roughly half HCM's — this single parameter accounts for most of the TWSC
over-prediction against HCM's random-arrival formula. At the roundabout,
SUMO's critical gap is genuinely *larger* than HCM's, which **reverses the
HCM capacity ordering**: HCM predicts the roundabout beats the
stop-controlled crossing (507.7 vs 320.4 veh/h at V=800), while SUMO's own
measured behavior has the TWSC beating the roundabout (521.6 vs 368.6
veh/h, Poisson arrivals) — a genuine, verified SUMO modeling gap, not an
artifact of parameterization.

**Robustness check, with an honest limitation disclosed.** Rebuilding the
roundabout at a larger radius plus faster ring speed together, and
separately at the baseline radius with only a faster ring speed, both
preserve the TWSC-beats-roundabout ordering at V=800 Poisson arrivals
(395.4 and 327.6 veh/h respectively, both below the TWSC's 521.6). Only
the speed-only variant cleanly isolates a single factor (ring speed
8.33→11.11 m/s at fixed ring-edge length, verified from the compiled net);
the larger-ring variant changed both radius (16.66→28.14 m) and speed
simultaneously (also verified from the compiled net), so it should be read
as "a larger, faster ring," not a radius-only isolation. The script that
generated these two specific network variants was not preserved in this
episode's deliverables — disclosed as a reproducibility gap rather than
hidden.

## Real platoons: large capacity impact, and the true dispersion mechanism

Physically generating platoons via an upstream signal (rather than
statistically specifying bunching), TWSC, V=800, D=300 m: minor-approach
capacity rose from 521.6 veh/h (no upstream signal) to 992.3 veh/h (with
it) — **+470.7 veh/h, 95% CI [+447.2, +494.2]** — comparable in scale to
the platoon/no-platoon gap already measured for the statistical cowan75
spec above. Roundabout: 368.6 → 594.6 veh/h (+61.3%).

**Isolating the dispersion mechanism required matched-baseline comparison
at each distance, not a cross-series splice.** Holding `speedDev=0` (no
desired-speed heterogeneity) at distances 150/300/600/1000/1500 m leaves
capacity essentially flat (994.1 → 989.6 → 989.4 veh/h across the full
range), with platoon phase concentration ≈ 1.000 at every distance.
Holding `speedDev=0.10` at the *same* distances gives a real decline from
976.2 veh/h (150 m) to a trough of 888.5 veh/h (1000 m, paired diff −101.1,
p=1e−6), with a **partial, non-monotonic recovery to 907.5 veh/h at
1500 m** — the capacity series itself is noisier than a clean monotonic
decline would suggest. The platoon phase-concentration index is the
cleaner signal: it declines monotonically under `speedDev=0.10`
(0.983 → 0.933 → 0.845 → 0.747 → 0.657) while staying flat under
`speedDev=0` at every distance. **Platoon dispersion in SUMO is caused by
desired-speed heterogeneity between vehicles, not by distance or
car-following noise alone** — the concentration index is the primary
evidence for this mechanism; the capacity figures are a noisier,
directionally-consistent secondary signal, not a clean monotonic curve.

Downstream signal offset alone, independent of platoon strength, swings
major delay from 0.40 s to 18.24 s at fixed volume and distance, with the
delay-minimizing offset tracking `(D / free-flow speed) mod cycle length`
exactly at all five tested distances — an independent confirmation, on a
different metric, of the mechanism already documented in
[[arterial-signal-progression-resonance-bandwidth-and-delay]].

## Decision rule: when does arrival-process choice matter?

Signal major-approach control delay is **immaterial** at low volume (no
spec differs from Poisson at p<0.01), **marginal** at moderate volume (spec
range ≈ 43% of a +5 s green-split treatment effect), and **matters** at
high volume (spec range exceeds the green-split treatment effect). Signal
Q95 major queue matters at every volume tested. Signal **minor**-approach
delay is immaterial everywhere — structurally, because an exclusive-phase
signal's minor approach cannot depend on the major stream's arrival
process at all. **TWSC capacity and minor delay matter at every volume
tested**, with the spec range exceeding what an added minor-approach lane
would buy.

Direction is consistent throughout: bunching (high realised CV) is
**optimistic** for unsignalized capacity and **pessimistic** for signal
delay/queue; deterministic `<flow vehsPerHour>` is **catastrophically
pessimistic** for unsignalized capacity whenever the mean headway
(3600/V) falls below the facility's own critical gap.

## Gotchas

- The roundabout re-shapes its own conflicting stream at high circulating
  flow — above roughly 800 veh/h in this testbed, queuing at the
  circulating approach itself regularizes headways (measured CV collapsing
  from 1.04 at V=200 to 0.196 at V=1400), so arrival-process conclusions
  at a roundabout are only clean below that point.
- A flared 2-lane approach and roundabout-entry variant tested in this
  episode *reduced* measured capacity and accounted for **100% of every
  teleport in the entire 3110-run study** (1563 on that one network, 0 on
  every other network tested), with an unexpectedly shrunken compiled
  geometry as a second confound — withdrawn as an invalid comparison
  rather than reported as a negative finding. Check teleport counts per
  network before trusting any capacity comparison spanning geometry
  variants.
- Measured gap-acceptance capacity is `--step-length`-fragile, partly
  because step length itself changes the realised arrival-process CV: TWSC
  capacity rose 427.5→539.7 veh/h (+26%) and roundabout 243.9→370.8
  (+52%) moving from dt=1.0 s to dt=0.1 s. State the step length with any
  absolute capacity figure.
- `departDelay` carries a deterministic ≈dt/2 rounding floor whenever
  3600/V happens to be a multiple of the step length — don't mistake this
  grid artifact for a genuine zero-delay condition.
- Verify delay-arm censoring is actually zero before trusting an
  oversaturated-demand delay figure — don't assume it. Here a 20-minute
  unloaded drain period cleared every residual queue and measured
  censoring fraction was exactly 0.000 in every delay cell, which also
  scopes the oversaturated-demand delay figures to a one-hour demand pulse
  with recovery time, not a continuously oversaturated hour.

See `model-demand-arrival-process-and-its-effect-on-capacity-and-delay`
for the full build/verification/measurement workflow, and
[[hcm-control-delay-vs-sumo-delay-metrics]] and
[[roundabout-capacity-law-and-demand-metering]] for the HCM comparison
methodology this page's gap-acceptance findings extend.
