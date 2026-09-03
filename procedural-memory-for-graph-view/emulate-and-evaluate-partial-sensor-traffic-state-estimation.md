---
name: emulate-and-evaluate-partial-sensor-traffic-state-estimation
description: Use this skill when the user wants to evaluate how well real, partial traffic sensors (loop detectors, probe/floating-car data at limited penetration) can estimate travel time or queue length in SUMO, as opposed to analyzing ground-truth simulation output directly. Covers building a ground-truth-vs-emulated-sensor-layer comparison over IDENTICAL underlying traffic (CRN across sensing configurations, not just across seeds), emulating E1 loops at multiple setbacks and probe data via --device.fcd.probability/--device.fcd.period, four named estimators (time-mean vs space-mean speed, instantaneous vs experienced travel time, probe RMSE vs penetration, cumulative-count vs occupancy-threshold queue length), and testing for systematic sensor bias (not just noise) including probe length-bias and detector blind spots. Trigger on mentions of traffic state estimation, sensor penetration, probe vehicle data, floating car data, detector placement accuracy, loop detector bias, or "how much sensing is enough."
related_skills:
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - build-macroscopic-fundamental-diagram
  - validate-congested-scenario-results-against-teleport-artifacts
  - quantify-sumo-run-to-run-variability
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
---

# Emulate and Evaluate Partial-Sensor Traffic State Estimation

Every other post-processing skill in this project's memory analyzes SUMO's own
ground-truth output (full tripinfo, full FCD, edgeData) directly. This skill instead
treats the sensing layer itself as the object of study: build one ground-truth
scenario, then deliberately throw away most of the data the way a real traffic
agency's actual detectors and probe fleet would, and measure how much the resulting
partial-data estimators diverge from ground truth — and specifically whether that
divergence is unbiased noise (which more data fixes) or a systematic bias (which it
doesn't).

## Structure: one ground-truth run, many observation layers over the identical traffic

Build a signalized corridor (a multi-intersection arterial works well — it gives both
a genuine bottleneck and enough spatial extent for probe-length-bias effects to show
up) with a demand profile that ramps to oversaturation and back down, so both
congestion onset and dissipation are observable in one run. Run **one** full-FCD
ground-truth simulation, then re-run the **identical** scenario (same network, same
demand, same signal plan, same random seed) varying only:

- **Loop-detector configuration**: E1 detectors at the stop bar plus advance loops at
  several setback distances, aggregated at realistic intervals (e.g. 30s/60s/300s).
- **Probe/floating-car configuration**: `--device.fcd.probability` (penetration rate)
  crossed with `--device.fcd.period` (GPS ping interval).

**This is a stronger requirement than the usual CRN discipline** (same seed across
comparison arms) — here, every sensing arm's underlying vehicle trajectories must be
*exactly* identical, since sensing configuration should never change the traffic
itself, only what's observed of it. Verify this directly by hashing each arm's
`tripinfo` output and confirming every arm matches the ground-truth run's hash.

**Gotcha: SUMO's `tripinfo` output includes device-attachment bookkeeping (a
`devices` attribute) that legitimately differs between sensing arms by construction**
(an arm with probes attached has different device strings than one without) — a naive
full-record hash comparison will report a false CRN failure. Exclude
observation-layer bookkeeping attributes from the comparison and verify per-vehicle
`duration` (or another genuine traffic-outcome field) matches exactly instead.

## The four estimators

**A. Time-mean vs. space-mean (harmonic) spot speed.** Loop detectors naturally
report the arithmetic mean of vehicle speeds passing a point (time-mean speed), but
the physically correct speed for converting a spot measurement into a travel-time
estimate is the **harmonic mean** (space-mean speed) — the arithmetic/harmonic mean
inequality guarantees time-mean speed is always >= space-mean speed, which means
naive loop-based travel-time estimates are **always** biased toward under-estimating
travel time, and the bias grows with the variance of speeds observed at that point
(worse exactly during the congested, stop-and-go conditions where accuracy matters
most). This is a structural bias, not sampling noise — it doesn't shrink with more
aggregation interval and isn't fixed by adding more loops of the same kind, only by
using the correct averaging (SUMO's E1 output already reports `harmonicMeanSpeed`
alongside the naive `speed` field — switching which field an estimator reads is a
free fix). Even the harmonic correction typically leaves a smaller residual bias
(don't assume it's a perfect fix); report both the raw and corrected bias.

**B. Instantaneous vs. experienced travel time, and its hysteresis.** Compute
corridor travel time two ways at every departure instant: **instantaneous** (sum of
concurrent per-link travel times measured *at that instant* — what a live "current
conditions" dashboard reports) vs. **experienced** (what a vehicle departing at that
instant actually accumulates by arrival, from ground truth). Expect asymmetric
error between the congestion-*building* and congestion-*clearing* phases, tracing a
hysteresis loop rather than a single instantaneous-vs-experienced curve, with a
measurable best-fit time lag between the two series. **Don't assume the classic
textbook sign pattern (under-prediction while building, over-prediction while
clearing) will cleanly reproduce in both directions** — in one tested scenario only
the clearing-phase over-prediction was clearly distinguishable from a fixed baseline
offset; the building-phase sign was statistically ambiguous. Check significance (e.g.
via standard-error bars) before asserting a directional claim for each phase
separately.

**C. Probe-based mean travel time: RMSE vs. penetration.** Sweep
`--device.fcd.probability` and compute RMSE of probe-only mean travel time against
ground truth. Expect RMSE to decay close to the theoretical `1/sqrt(n)` rate, possibly
steepening at very high penetration as a finite-population correction becomes
non-negligible. **Report the minimum penetration needed to hit a stated accuracy
target separately for free-flow and oversaturated periods — don't assume congestion
requires more sensing.** In one tested case, the required penetration was *lower*
during oversaturation than free-flow, because a signal's discharge process can
regularize vehicle spacing (and thus travel-time variance) during sustained queuing
more than free-flowing traffic's naturally dispersed travel times — the penetration
requirement tracks the underlying travel-time coefficient of variation, not
"how bad the regime looks," and CV should be measured, not assumed to track
congestion level.

**GPS ping period imposes its own bias floor that penetration cannot fix.** Even at
100% penetration, a coarse ping period systematically *under*-estimates travel time
(the last-observed-position-before-arrival truncates the final partial interval, and
every probe at that ping period shares the same structural truncation, so it doesn't
average out across more probes). A simple correction — add the ping period itself
back to the raw travel-time estimate — removes most or all of this bias; don't rely
on penetration alone to fix a ping-period-driven bias.

**D. Queue length: cumulative-count/input-output vs. occupancy-threshold.** Compare
both classical loop-based queue-length estimation methods against true per-cycle
maximum back-of-queue measured directly from vehicle positions (not from any
detector). See the occupancy blind-spot discussion below — this is where the most
consequential bias in this skill's methodology shows up.

## Bias hypothesis: probe presence-sampling is length-biased toward slow vehicles

Compare mean travel time computed from probes sampled **by presence in the network**
(what fraction of vehicles currently on the road are equipped — the natural
interpretation of a live probe feed) against sampling **by departure** (what fraction
of completed trips were equipped). **Presence-based sampling overestimates mean
travel time, and the magnitude matches a textbook statistical identity exactly**: the
overestimate equals `Var(travel_time) / mean(travel_time)` — a length-biased ("inspection
paradox") sampling effect, since a vehicle that takes longer to traverse the corridor
is present in the network, and therefore visible to a presence-based probe, for
longer, over-representing slow trips relative to their true share of total trips.
**This bias is penetration-independent** (it doesn't shrink with more probes, since it's
a sampling-mechanism bias not sampling noise) — verify this explicitly by comparing the
bias magnitude across a penetration sweep, and correct it with inverse-duration
(Horvitz-Thompson-style) reweighting if presence-based sampling must be used.

**This same mechanism compounds severely at coarse ping periods, at the individual-link
level**: a long enough ping period can make the large majority of individual link
traversals structurally unobservable (the vehicle enters and exits a short link
between two ping snapshots), and the small surviving observed fraction is
dramatically slower than the true link population — a much larger version of the same
presence/length-biased-sampling mechanism, worth checking separately from the
whole-corridor version since the magnitude can be far larger at fine spatial scale.

## Bias hypothesis: occupancy-based queue estimation goes blind past setback

An occupancy-threshold queue-length estimator cannot report a queue longer than the
distance to its own detector, by construction — once the true queue extends past an
advance loop's setback distance, the estimate pins at (or near) the setback rather
than continuing to track the true, longer queue. **This produces a hard ceiling, not
a gradually growing error** — verify by checking, per setback distance, what fraction
of "engulfed" cycles (true queue > setback) actually pin at the setback; expect this
fraction to be high but **not necessarily exactly 100% at every tested setback** — a
setback distance that happens to coincide with the sub-vehicle-length occupancy-
periodicity artifact (see Gotchas) can locally suppress even the pinning signature
itself, since the loop can simply fail to register a genuine standing queue if it
happens to sit in the recurring inter-vehicle gap.

**There is no single-setback solution to the placement dilemma.** Moving the loop
farther back shrinks the blind-spot's magnitude (a deeper-set loop starts missing the
queue's true extent later) but monotonically *worsens* free-flow accuracy at the same
time, because a deep loop reads elevated occupancy from merely dense *moving* traffic
that isn't actually queued at all. Measure both regimes (RMSE on engulfed cycles vs.
RMSE on non-engulfed/free-flow cycles) separately across the setback sweep — the
optimal single setback for one regime is typically far from optimal for the other,
and **a multi-setback ladder (several loops at different distances) is required to
perform well in both regimes simultaneously**, not any single setback choice.

## Gotchas

- **`tripinfo`'s `devices` attribute differs between sensing arms by construction** —
  exclude it (and any other observation-layer bookkeeping field) from any
  CRN byte-identity check across sensing configurations, or a correct CRN setup will
  falsely appear to have failed.
- **Loop-based travel-time estimators must use `harmonicMeanSpeed`, not the naive
  `speed` field** — the naive field is structurally, always biased toward
  under-estimating travel time, worse under higher speed variance, and this is a free
  fix requiring no new hardware.
- **A GPS ping period imposes an irreducible bias floor at ANY penetration** — a
  `TT + ping_period` style correction is required; penetration alone cannot fix it.
- **Probe sampling "by presence" is length-biased toward slow vehicles** — the bias
  magnitude follows `Var(travel_time)/mean(travel_time)` exactly, is
  penetration-independent, and compounds severely at coarse ping periods at the
  individual-link level (can make the majority of link traversals unobservable).
- **Occupancy-based queue estimation has a hard, structural ceiling at the detector's
  own setback distance — but the exact pinning rate at a given setback can be
  perturbed by a fine-grained positioning artifact** (see below), so don't assume a
  clean, monotone "100% pinned past setback" result without checking per-setback.
- **A fixed-position occupancy loop's reading can be periodic in the vehicle
  length-plus-minimum-gap spacing.** A one-meter change in loop placement can swing
  measured occupancy by tens of percentage points, and some fraction of possible
  1-meter positions can systematically fail to detect a genuine standing queue at
  all, because the loop happens to sit in the recurring inter-vehicle gap rather than
  under a vehicle. This is a repeatable positioning artifact, not measurement noise —
  build a fine-resolution (e.g. 1-meter) diagnostic loop ladder if a queue-detection
  result looks inconsistent between nearby setback distances.
- **Which sensing layer "wins" depends entirely on the estimation target, not a
  single overall answer.** A mean-type statistic (travel time) converges with
  penetration roughly like an unbiased sample mean; an extremum-type statistic (queue
  length) converges far more slowly under random sampling, since a small sample can
  easily miss the single observation that defines the true maximum — expect probes to
  dominate for travel time and loops to dominate for queue length at low-to-moderate
  penetration, with a crossover point rather than a universal ranking.
- **SUMO silently ignores out-of-order `<flow>` elements in a route file** — no error,
  only a warning, and the offending flow's vehicles are simply never generated. Always
  verify the total generated vehicle count against the intended demand total before
  trusting a multi-flow route file, especially one assembled programmatically from
  several movement classes.

## Related

- `design-actuated-signal-detector-placement-and-fault-tolerance` — the E1
  custom-binding and blind-zone-cost-asymmetry findings this skill's occupancy
  blind-spot analysis extends from a signal-actuation context to a state-estimation
  context.
- `build-macroscopic-fundamental-diagram` — the flow/density/space-mean-speed
  measurement methodology (and the `harmonicMeanSpeed` correctness point) this
  skill's Estimator A directly reuses.
- `validate-congested-scenario-results-against-teleport-artifacts` — the
  `--time-to-teleport` sweep and survivorship-censoring discipline applied to this
  skill's oversaturated-period ground truth.
- `quantify-sumo-run-to-run-variability` — the CRN discipline this skill extends to
  hold across sensing configurations rather than only across independent seeds.
- `analyze-simulation-outputs` — general tripinfo/summary/edgeData conventions this
  skill's many-arm comparison reuses.
- [[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]] — the verified bias
  directions/magnitudes, the two confirmed bias hypotheses, and the target-dependent
  practical sensing recommendation this skill's methodology produced.
