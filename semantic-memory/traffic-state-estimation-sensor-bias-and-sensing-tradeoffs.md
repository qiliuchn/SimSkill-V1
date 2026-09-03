---
summary: "A controlled comparison of ground-truth traffic state against emulated loop detectors and penetration-limited probe vehicles in SUMO found several genuine, systematic sensor biases (not noise) — loop-based time-mean speed underestimates travel time by ~25%, GPS ping period imposes an irreducible bias floor at any penetration, presence-sampled probes are length-biased toward slow vehicles matching a Var/mean identity exactly, and occupancy-based queue estimation goes structurally blind past its own detector's setback — and found the practical sensing recommendation flips by target: probes dominate for travel time, loops dominate for queue length, because queue length is an extremum statistic that converges far slower under sampling than a mean does."
keywords:
  - traffic-state-estimation
  - sensor-bias
  - probe-penetration
  - floating-car-data
  - loop-detector-bias
  - space-mean-speed
  - queue-estimation
  - length-biased-sampling
created: 2026-08-02T09:30:00
last_updated: 2026-08-06T06:00:00
sources:
  - "[[episodic-memory/2026-08-02_09-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_09-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[sumo-output-files]]"
  - "[[automatic-incident-detection-algorithms]]"
  - "[[driver-desired-speed-and-speed-enforcement-evaluation]]"
  - "[[connected-vehicle-penetration-and-detector-free-signal-control]]"
  - "[[state-serialization-and-rolling-horizon-traffic-forecasting]]"
related_skills:
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - build-macroscopic-fundamental-diagram
  - quantify-sumo-run-to-run-variability
  - build-rolling-horizon-traffic-forecast-with-state-warm-start
related_skills_for_graph_view:
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[build-rolling-horizon-traffic-forecast-with-state-warm-start]]"
---

# Traffic State Estimation: Sensor Bias and Sensing Tradeoffs

Every other post-processing knowledge in this project's memory analyzes SUMO's own
ground-truth output directly. This page instead concerns what happens when the object
of study is the *sensing layer itself* — the sparse, biased data a real traffic
agency actually has (loop detectors, penetration-limited probe/floating-car data) —
compared against ground truth from the identical underlying traffic.

## Verified finding: loop-based spot speed is a structural bias, not noise, and it's worst exactly when accuracy matters most

Loop detectors naturally report the arithmetic mean ("time-mean") of vehicle speeds
passing a point. The physically correct speed for converting a spot measurement into
a travel-time estimate is the **harmonic mean** ("space-mean") — the
arithmetic/harmonic mean inequality guarantees time-mean speed is always at least as
large as space-mean speed, so naive loop-based travel-time estimates are **always**
biased toward underestimating travel time. Measured directly: time-mean speed
exceeded space-mean speed in **100% of 570 station-intervals** tested, producing a
**-24.5% to -25.0% corridor travel-time bias**, essentially unchanged across
aggregation intervals (60s vs. 300s) — confirming the bias is structural, not a
sampling-interval artifact. **The bias grows monotonically with speed variance**: from
essentially zero at low variance (free-flow) up to over -40% at the highest measured
variance (heavily congested conditions) — worst precisely where accurate travel-time
estimation matters most. Switching a loop-based estimator to read SUMO's
`harmonicMeanSpeed` field instead of the naive `speed` field removes most, though not
all, of the bias, for zero additional sensor hardware.

## Verified finding: instantaneous "current conditions" travel time lags reality, asymmetrically

Comparing an instantaneous travel-time estimate (a snapshot of concurrent link speeds
at the moment of departure — what a live traffic dashboard reports) against
experienced travel time (what a vehicle departing at that moment actually accumulates)
found a real hysteresis loop rather than a single instantaneous-vs-experienced curve,
with roughly an order-of-magnitude asymmetry between phases in one tested scenario: the
instantaneous estimator overestimated experienced travel time substantially during
the congestion-*clearing* phase but only marginally (statistically indistinguishable
from a small baseline offset) during the congestion-*building* phase, with a best-fit
lag of about two minutes between the instantaneous series and what departing vehicles
actually experience. **The classic textbook expectation — under-prediction while
building, over-prediction while clearing — did not clearly reproduce in both
directions**; only the clearing-phase overestimate was unambiguous. This should be
treated as scenario-dependent rather than universal until checked against a different
demand-ramp shape.

## Verified finding: probe accuracy needed is a function of travel-time variance, not "how congested it looks"

Sweeping probe penetration and GPS ping period against ground truth found RMSE
decays with penetration close to the theoretical `1/sqrt(n)` rate. **A genuinely
counter-intuitive result**: the minimum penetration needed to hit a ±10%/95%-confidence
accuracy target was *lower* during the oversaturated period than during free-flow in
the tested scenario — the reverse of the naive expectation that congestion needs more
sensing. The mechanism: travel-time coefficient of variation was actually *lower*
under sustained congestion than in free flow, because the signal's discharge process
regularizes vehicle spacing during queuing, while free-flowing traffic has more
naturally dispersed individual travel times. **The required sensing intensity tracks
the underlying travel-time variance, which should be measured per scenario, not
assumed to track how congested a period looks.**

**GPS ping period imposes its own irreducible bias floor that no amount of
penetration fixes.** Even at 100% penetration, coarser ping periods produce a
systematic travel-time *underestimate* (observed: roughly -4% at a 10s ping, growing
to over -20% at a 60s ping), because a probe's last-observed-position-before-arrival
under-samples the trip's final partial interval, and every probe sharing that ping
period has the same structural truncation — so the error does not average out across
more probes. A simple correction (add the ping period back to the raw estimate)
removed nearly all of this bias in the tested scenario.

## Verified finding: probe sampling is length-biased toward slow vehicles, matching a textbook identity exactly

Mean travel time computed from probes sampled **by presence in the network at a
random instant** (the natural reading of "what fraction of vehicles currently on the
road are equipped") overestimates the true mean relative to sampling **by departure**
("what fraction of trips are equipped") — a length-biased ("inspection paradox")
sampling effect, since a slower trip is present in the network, and therefore visible
to a presence-based probe, for longer, over-representing slow trips relative to their
true share of total departures. **The overestimate matches the statistical identity
`Var(travel_time) / mean(travel_time)` essentially exactly** (verified to many
decimal places against the raw travel-time distribution) and is **penetration-
independent** — it appears at the same magnitude whether 1% or 100% of vehicles are
probed, confirming it is a sampling-mechanism bias, not sampling noise that more
probes would average away. Inverse-duration (Horvitz-Thompson-style) reweighting
removed nearly all of it.

**The same mechanism compounds severely at the individual-link level under a coarse
ping period**: in the tested scenario, a 60-second ping period made the large majority
of individual link traversals structurally unobservable (the vehicle entered and
exited the link between two ping snapshots), and the small surviving observed
fraction was dramatically slower than the true link population — a substantially
larger version of the same length-biased-sampling mechanism, worth checking
separately at fine spatial scale since its magnitude can dwarf the whole-corridor
version.

## Verified finding: occupancy-based queue estimation has a hard, structural blind spot — with a twist

An occupancy-threshold queue-length estimator cannot, by construction, report a queue
longer than the distance to its own detector. Measured directly: in cycles where the
true queue extended past an advance loop's setback distance, the estimate pinned at
(or very near) the setback in most, but **not all**, tested setback distances — one
tested setback pinned in only about a quarter of its engulfed cycles, a striking
exception to an otherwise near-universal pattern. Investigating the exception led to
an unplanned, and materially useful, third finding: **occupancy readings from a
fixed-position loop are periodic in exactly the vehicle length plus minimum-gap
spacing** — a one-meter change in loop placement swung measured occupancy by 70+
percentage points in the tested vehicle-type configuration, and a nontrivial fraction
of possible 1-meter positions along a queue never registered a genuine standing queue
at all, because the loop happened to sit in the recurring inter-vehicle gap rather
than under a vehicle. **This is a repeatable positioning artifact, not measurement
noise, and it can locally suppress even the blind-spot's own pinning signature** at
specific setback distances that happen to coincide with the periodic pattern.

**There is no single-setback solution to the resulting placement dilemma.** Moving
the loop farther back shrinks the blind spot's magnitude but *monotonically worsens*
free-flow accuracy at the same time (a deep loop reads elevated occupancy from merely
dense *moving* traffic, not just a genuine standing queue) — RMSE on free-flow cycles
degraded by roughly 20x between the shallowest and deepest tested setbacks in the
tested scenario. Only a multi-setback ladder of several loops performed well in both
regimes simultaneously; any single setback was dominated by the ladder in at least one
regime.

## Practical sensing recommendation: the answer flips by target

**For travel time: probes beat loops, decisively, at very low penetration.** A tiny
probe sample (0.5% penetration, 1s ping) outperformed a fully instrumented multi-loop
corridor's best configuration in the tested scenario, because loop-based error is
*systematic* (the space-mean bias above) and cannot be fixed by adding more loops of
the same kind, while probe error is closer to unbiased sampling noise that genuinely
shrinks with more probes. Two free fixes apply to the loop layer regardless of
penetration: switching from raw spot speed to harmonic-mean speed, and coarsening the
aggregation interval (which reduces RMSE, distinct from the level-bias fix).

**For queue length: loops beat probes, except at penetration above roughly
10-15%.** The structural reason queue length behaves oppositely from travel time:
queue length is an **extremum statistic** (a maximum over the sampled population),
which converges far more slowly under random sampling than a **mean** statistic like
travel time does — a small probe sample can easily miss the single vehicle that
defines the true back-of-queue. A spacing-based bias correction for probe queue
estimates fixed the *bias* at low penetration but slightly *increased* RMSE — a
genuine bias/variance tradeoff, not a free improvement.

## Practical takeaways

- Verify CRN across sensing configurations by hashing genuine traffic-outcome fields
  (e.g. per-vehicle `duration`), not a full raw-record hash — SUMO's `tripinfo` output
  includes observation-layer bookkeeping (a `devices` attribute) that legitimately
  differs between sensing arms and will produce a false CRN failure if included.
- Always use space-mean (harmonic) speed for a loop-based travel-time estimator, never
  the naive time-mean spot speed.
- Measure the underlying travel-time coefficient of variation before assuming a
  congested period needs more sensing than a free-flow one — the relationship is not
  guaranteed to run in the intuitive direction.
- Correct for a GPS ping period's structural truncation bias directly (add the ping
  period to the estimate); don't rely on penetration alone.
- Presence-based probe sampling is length-biased toward slow vehicles by an amount
  predictable from the travel-time distribution's own variance-to-mean ratio; correct
  with inverse-duration reweighting if presence-based sampling is unavoidable.
- Build a fine-resolution diagnostic detector ladder if an occupancy-based
  queue-estimation result looks inconsistent between nearby setback distances — a
  sub-vehicle-length positioning artifact is a real and repeatable failure mode, not
  noise.
- Match the sensing layer to the estimation target's statistical character (mean vs.
  extremum), not a single "which sensor is better" verdict.

See `emulate-and-evaluate-partial-sensor-traffic-state-estimation` for the full
ground-truth-vs-emulated-sensor-layer construction and estimator workflow, including
the reusable scripts for all four estimators and both bias-hypothesis tests.
