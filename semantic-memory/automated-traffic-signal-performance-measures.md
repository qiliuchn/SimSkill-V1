---
summary: ATSPM (Automated Traffic Signal Performance Measures) derive signal-timing diagnostics — the Purdue Coordination Diagram, Percent Arrival on Green, Platoon Ratio, and GOR5/ROR5 split failure — from a high-resolution enumerated controller event log alone; validated against simulator ground truth, Platoon Ratio tracks approach delay well but the field-standard split-failure flag has only ~0.31 precision until an occupancy-continuity criterion is added.
keywords:
  - ATSPM
  - Purdue Coordination Diagram
  - percent arrival on green
  - platoon ratio
  - split failure
  - GOR ROR
  - high-resolution event log
  - proxy validation
created: 2026-08-04T10:00:00
last_updated: 2026-08-07T01:30:23
sources:
  - "[[episodic-memory/2026-08-04_10-00-00/attempts/attempt-1/action-agent-output.json]]"
  - https://sumo.dlr.de/docs/TraCI.html
  - https://sumo.dlr.de/docs/Simulation/NEMA.html
related_pages:
  - "[[nema-dual-ring-controller]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
related_skills:
  - build-atspm-pipeline-and-retime-arterial
  - implement-nema-dual-ring-controller
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - design-arterial-signal-progression-and-verify-bandwidth
  - implement-scats-style-coordinated-adaptive-signal-control
related_skills_for_graph_view:
  - "[[build-atspm-pipeline-and-retime-arterial]]"
  - "[[implement-nema-dual-ring-controller]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
  - "[[implement-scats-style-coordinated-adaptive-signal-control]]"
---

# Automated Traffic Signal Performance Measures (ATSPM)

ATSPM is the practice of diagnosing signal timing from what a **controller and
its detectors can actually observe** — a high-resolution enumerated event log —
rather than from a model, a manual count, or (in simulation) privileged internal
state. Its defining constraint is also its scientific value: every measure is
computed from field-observable data, so a measure that survives validation is
known to be deployable.

## The enumerated event log

The Indiana/ATSPM convention records `(timestamp, signal_id, event_code,
event_param)` at sub-second resolution. The codes used in practice for the core
measures are `1` Phase Begin Green, `8` Phase Begin Yellow Clearance, `10` Phase
Begin Red Clearance, `81` Detector Off and `82` Detector On, with `event_param`
carrying the phase number for phase events and the detector channel for detector
events. Codes `4` Gap Out, `5` Max Out and `6` Force Off are emitted natively by
real controllers; in a simulation they must be reconstructed from realised green
versus configured `maxDur`, so no measure should depend on them.

Alongside the log, every ATSPM deployment stores a **detector configuration
table** mapping channel to signal, phase and movement. That table is
configuration metadata, not state — an analysis that reads the event log plus the
configuration table is still a purely field-observable analysis.

Two instrumentation classes matter and are not interchangeable:
**stop-bar presence detectors** (a zone covering the last 15–30 m of each lane,
used for occupancy) and **advance/setback count detectors** (a point loop
~90–120 m upstream on the coordinated approaches, used for arrival times). See
[[actuated-signal-detector-design-and-fault-tolerance]] for placement conventions.

## The core measures

**Purdue Coordination Diagram (PCD)** plots each advance-detector actuation's
time-in-cycle against time of day, with the green band overlaid. Defining the
cycle reference as the *observed* begin-green of the coordinated phase, rather
than a nominal cycle clock, makes the diagram robust to a coordinated green that
floats — which it does in a coordinated-actuated controller.

**Percent Arrival on Green (AoG)** is the fraction of those arrivals falling in
the green band. **Platoon Ratio** `PR = AoG / (g/C)` normalises it by the green
fraction, so `PR ≈ 1` means arrivals are effectively random, `PR < 0.85` is poor
progression and `PR > 1.15` is favourable (HCM framing).

**Split failure** is detected from stop-bar occupancy: `GOR5`, the Green
Occupancy Ratio over the first 5 s of green, and `ROR5`, the Red Occupancy Ratio
over the first 5 s of red. The field-standard flag is `GOR5 ≥ 0.80 AND
ROR5 ≥ 0.80` — the phase started with a queue and ended with one still present.

## Verified proxy validation

Measured on a 4-signal coordinated-actuated arterial in SUMO (2 h, 10 233
vehicles, non-uniform 550/420/500 m spacing, 0 teleports and 0 collisions), with
the ATSPM layer reading only the event log and the ground-truth layer never
exposed to it:

**Platoon Ratio tracks delay at the approach level but not per cycle.** Across
eight coordinated approaches, `r(PR, mean control delay) = −0.802` and
`r(AoG %, delay) = −0.852`, stable across re-timed plans (−0.72 to −0.87). Within
a single approach, per cycle, the mean correlation collapses to `−0.414` with a
range from `−0.769` to `+0.053`. PR is a sound instrument for ranking approaches
and deciding where to act; it is not a per-cycle delay estimator.

**The field-standard split-failure flag has very poor precision.** Against the
ground truth "did every vehicle standing in the queue at the start of green cross
the stop bar before green ended", over 2 255 phase-green instances:

| flag | precision | recall | F1 | MCC |
|---|---|---|---|---|
| `GOR5 ≥ 0.80 AND ROR5 ≥ 0.80` | 0.309 | 1.000 | 0.472 | 0.489 |
| + 3-of-5 consecutive-cycle rule | 0.400 | 0.947 | 0.562 | 0.562 |
| + occupancy continuity across end of green | 0.900 | 1.000 | 0.947 | 0.943 |

The flag never misses a real failure (recall 1.000) but produced 463 false
positives against 207 true ones. **The mechanism is that ROR5 cannot distinguish
a residual queue from a fresh arrival that stopped for the red.** On a through
movement with continuous arrivals that happens almost every cycle: arterial
through movements showed a 0 % true failure rate and a 51.6 % flag rate.

**The repair is computable from the same log**: additionally require occupancy
over `[green_end − 10 s, red_start + 5 s] ≥ 0.90`. A genuine residual queue is
still discharging over the detector at the end of green, so its occupancy is
continuous; a fresh arrival leaves a gap. The 3-of-5 "sustained" rule that real
practice uses helps much less and costs recall.

## Choosing the ground truth is itself a modelling decision

**Halting-vehicle counts are not a valid "did the queue clear" ground truth.** A
queue that begins *moving* reports zero halting vehicles well before it has
cleared the stop bar. Both "halting never reached zero during green" and "vehicles
still halted when green ended" scored the same 4.6 % failure rate where the
correct served-versus-queued definition gave 9.2 %, and both scored a left turn
deliberately loaded to v/c ≈ 1.2 as passing. The defensible definition compares
the queue present at green start against the vehicles that actually crossed the
stop bar during that green.

## Where the proxies mislead

- **Short queues on long detectors.** 30 m left-turn presence loops generated 114
  false positives whose ground-truth maximum queue had a median of **1 vehicle**
  (68 % had ≤ 2). A single stationary car reads identically to a standing queue.
- **Stop-bar presence detectors are not volume counters.** Against advance counts
  on the same approaches they recovered only **15–79 %** of true volume, because
  a presence zone cannot resolve vehicles inside a discharging platoon. Volume
  must come from the advance count detectors.
- **Permissive left turns remove records rather than corrupting them.** At a
  protected-permissive junction the protected left phase is skipped entirely on
  cycles where the permissive movement cleared demand (54 of 72 cycles in one
  case), so per-cycle failure rates have a moving denominator.
- **Spillback has a distinctive signature.** A left-turn bay at storage capacity
  (41 of ~42 vehicles) leaves its detector permanently covered, reporting
  `GOR5 = ROR5 = green utilisation = 1.000` with **zero volume** — no rising
  edges at all.
- **Setback travel time can be estimated from the log** (isolated advance
  actuations matched to the next stop-bar rising edge on the same lane, 10th
  percentile of the lag): verified at 5.40–6.02 s against a physical 5.28–6.33 s
  range. But busy approaches supply too few isolated arrivals and the estimator
  returns nothing. The correction is not cosmetic — it moved one approach's AoG
  from 46.9 % to 36.8 %.

## Retiming from ATSPM alone

Splits reallocated from phases the log shows under-utilised (coordinated phases
ran at 0.40–0.59 green utilisation) to phases in sustained refined split failure
(0.91–1.00), and offsets set to maximise volume-weighted AoG over the observed
PCD points, produced:

| plan | ground-truth split failure | mean timeLoss | corridor-through timeLoss |
|---|---|---|---|
| deployed | 9.2 % | 78.75 s | 74.97 s |
| splits only | 0.0 % | 61.70 s | 75.22 s |
| offsets only | 7.6 % | 74.43 s | 67.17 s |
| both | 0.0 % | **59.14 s** | 70.45 s |

**The two halves fix nearly orthogonal problems** — splits delivered essentially
all of the network delay reduction and none of the progression gain; offsets the
reverse. Reporting only the combined number hides which diagnosis mattered, so
the ablation is worth running.

**A per-intersection PCD-maximising offset rule does not converge.** Each signal
optimises against an arrival pattern that its neighbours' offset changes then
invalidate. A second iteration was *worse* than the first (mean timeLoss
59.14 → 63.69 s; corridor-through 70.45 → 86.12 s), and 50 % damping did not
rescue it (64.58 s), so this is not simple overshoot but a genuine coupling
problem. One pass from a badly-timed baseline is worth taking; iterating the
greedy rule is not.

## The NEMA offset/split coupling

In a coordinated-actuated ring-barrier controller (see
[[nema-dual-ring-controller]]) the coordinated phase begins when *both rings
actually cross the barrier* under gap-out, not after a nominal lead-phase split.
Verified consequence (an ad hoc check during retiming rather than a saved
script output — reproduce by diffing `cycles_*.csv`'s coordinated-phase-onset
column across an offset-only plan pair): with splits unchanged, changing
`offset` moves the coordinated green onset **exactly 1:1** (predicted −43.5 s,
measured −43.43 s). As soon as splits change, a correction of the form "barrier
drift = change in lead-left split" is wrong by **5.5–6.6 s** at every junction
tested. Prescribe
splits first, re-log, then prescribe offsets against the new barrier structure —
or verify the realised offset from the AFTER event log rather than assuming it.
Expect the coordinated green onset to float by 2–4 s (sd) cycle to cycle as lead
phases gap out, and coordinated greens to run well past their nominal `maxDur`
(55–70 s against 45–53 s) because they absorb unused time.
