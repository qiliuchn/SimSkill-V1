---
name: build-atspm-pipeline-and-retime-arterial
description: Use this skill when the user wants to build an ATSPM (Automated Traffic Signal Performance Measures) pipeline in SUMO — a high-resolution enumerated controller event log (Indiana-style event codes) written via TraCI and persisted as a standalone CSV, from which field-observable measures are computed WITHOUT touching simulator ground truth — and then use those measures to diagnose and retime a coordinated arterial. Covers stop-bar/advance detector instrumentation, the Purdue Coordination Diagram, Percent Arrival on Green and Platoon Ratio, GOR5/ROR5 split-failure detection and why the field-standard flag has terrible precision, validating every proxy against tripinfo/queue ground truth with a confusion matrix, and a verified account of which parts of an ATSPM-only retiming actually pay off. Trigger on mentions of ATSPM, Purdue Coordination Diagram, PCD, percent arrival on green, platoon ratio, split failure, GOR/ROR, green occupancy ratio, high-resolution controller event log, or signal performance measures.
---

# Build an ATSPM Pipeline and Retime an Arterial From It

Builds the SUMO analogue of a real agency's ATSPM deployment: a controller event
log, a detector configuration table, and an analysis layer that sees *only those
two files* — then validates every field-observable measure against simulator
ground truth the analysis never gets to read, and uses the measures alone to
retime the corridor.

The discipline that makes this worth doing is the **strict separation**: build
the event log with TraCI, persist it as a standalone CSV, and have the ATSPM
script open nothing else. Any measure that turns out to work is then known to
work *from field-observable data*, not from privileged simulator state. This is
the same proxy-validation discipline as `emulate-and-evaluate-partial-sensor-traffic-state-estimation`
and [[network-link-criticality-and-proxy-validation]], applied to signal timing.

## Pipeline shape

1. **Corridor** — 4 signals, deliberately non-uniform spacing (550/420/500 m),
   dedicated left-turn bays, coordinated-actuated NEMA control
   (`implement-nema-dual-ring-controller`; put the arterial through phases 2,6 in
   `barrier2Phases`). Load at least one movement above its split capacity and give
   the arterial and the cross street *different* temporal demand profiles so the
   directional split is genuinely unbalanced over the period.
2. **Instrumentation** (`scripts/build_detectors.py`) — E2 `laneAreaDetector`
   stop-bar presence on every lane of every approach (15 m through, 30 m
   left-turn bays), E1 `inductionLoop` advance detectors 110 m upstream on the
   coordinated approaches' through lanes. These are **observation-only**, parallel
   to the NEMA controller's own internal actuation detectors, so the log observes
   the controller rather than driving it.
3. **Event log** (`scripts/run_atspm_sim.py`) — TraCI at `--step-length 0.1`,
   using **subscriptions** (`traci.lanearea/inductionloop/trafficlight.subscribe`
   plus `getAllSubscriptionResults()`) so 78 000 steps cost ~2 min rather than
   hours. Writes `timestamp, signal_id, event_code, event_param`.
4. **Analysis** (`scripts/atspm_analysis.py`) — opens ONLY the event CSV and the
   detector config CSV. Cycle length, green/red boundaries, splits and the
   detector setback travel time are all *recovered from the log*.
5. **Validation** (`scripts/validate_proxies.py`) — confusion matrices and
   correlations against tripinfo / queue / per-vehicle ground truth.
6. **Retiming** (`scripts/prescribe_retiming.py`) — offsets and splits prescribed
   from the ATSPM output alone; re-run and compare in both currencies.

## Event codes

Use the Indiana/ATSPM enumerated set: `1` Begin Green, `8` Begin Yellow
Clearance, `10` Begin Red Clearance, `81` Detector Off, `82` Detector On, plus
derived `4` Gap Out / `5` Max Out / `6` Force Off. **Emit 1/8/10/81/82 as direct
observations and treat 4/5/6 as reconstructed** (a real controller emits them
natively; in SUMO you infer them by comparing realised green against `maxDur`).
Make sure no downstream measure depends on the reconstructed codes.

**Detect phase green from protected `'G'` only, never `'Gg'`.** With permissive
left turns the left-turn links carry `'g'` during the opposing through phase; a
`'Gg'` test makes the left-turn phase appear green (and then yellow) whenever the
through phase runs. Also run a per-phase GREEN→YELLOW→RED state machine so a
phase can only enter yellow from green.

## Verify the log before trusting anything computed from it

`scripts/verify_control.py` runs four independent checks. The critical one:
**SUMO's NEMA controller exposes its own internal active phase pair via
`traci.trafficlight.getPhaseName()`** (e.g. `"2+6"`) — an information source
completely separate from the link-state string the logger derives events from.
Cross-check every logged begin-green against it (verified: 480/480 agreements).
Also confirm the coordinated-vs-actuated signature (coordinated phases long and
stable, non-coordinated short and `maxDur`-capped) and detector fidelity.

**Detector count fidelity, verified**: counting `82` rising edges on an E1 loop
equals the number of distinct vehicles detected **exactly** (323/323, 231/231 on
two busy loops). SUMO's own `getIntervalVehicleNumber()` reads ~0.27 % *lower*,
because it counts completed longitudinal passages and misses vehicles that
lane-change off the loop. The rising-edge count is the more faithful arrival
count — don't "fix" it toward SUMO's counter.

## The measures, and what each one is actually good for

- **PCD** — plot advance-detector arrival time-in-cycle (cycle reference = the
  coordinated phase's observed begin-green) against time of day, with the
  *per-cycle measured* green length overlaid. Because the cycle boundaries come
  from observed begin-green events, the diagram handles a coordinated green that
  floats (see below) with no extra work.
- **AoG / Platoon Ratio** `PR = AoG / (g/C)` — the diagnostic that works.
- **GOR5 / ROR5 split failure** — needs repair before use (below).
- **Approach volume** — use the ADVANCE detectors. **Stop-bar presence detectors
  are not volume counters**: measured against advance counts on the same
  approaches they recovered only **15–79 % of true volume** (ratio 0.39, 0.15,
  0.70, 0.22, 0.79, 0.31, 0.67, 0.51 across the eight coordinated approaches),
  because a presence zone cannot resolve individual vehicles inside a
  discharging platoon. Reporting volume from stop-bar detectors is a silent
  2–7× undercount.
- **Setback travel time, estimated from the log alone** — take advance
  actuations that are *isolated* (no other actuation on that lane within ±8 s)
  whose lane stop-bar detector was unoccupied at that instant, then the next
  stop-bar rising edge on that lane is almost certainly the same vehicle; the
  10th percentile of those lags estimates free-flow setback travel time.
  Verified: 5.40–6.02 s against a physical range of 5.28 s (fastest drivers) to
  6.33 s (nominal speed limit) for a 95 m detector-to-detector distance.
  **It fails on busy approaches** — several approaches yielded fewer than the
  30 isolated samples required and returned nothing. Report AoG both raw and
  setback-corrected; the correction moved AoG by up to 10 points (J2 WB
  46.9 → 36.8 %), so it is not negligible.

## Split failure: the field-standard flag has ~0.31 precision — fix it

Ground truth must be **"did every vehicle standing in the queue when green began
cross the stop bar before the green ended"**, computed from per-vehicle stop-bar
crossing times. **Do not use halting-vehicle counts** — a queue that starts
*moving* shows zero halting vehicles long before it has actually cleared, so both
"halting never reached zero during green" and "vehicles still halted at end of
green" badly under-detect (both gave 4.6 % where the correct definition gave
9.2 %, and both scored an over-capacity left turn as passing).

Against that ground truth, over 2 255 phase-green instances:

| flag | precision | recall | F1 | accuracy | MCC |
|---|---|---|---|---|---|
| field standard `GOR5≥0.80 AND ROR5≥0.80` | 0.309 | 1.000 | 0.472 | 0.795 | 0.489 |
| + 3-of-5 consecutive-cycle rule | 0.400 | 0.947 | 0.562 | 0.865 | 0.562 |
| **+ occupancy continuity across end of green** | **0.900** | **1.000** | **0.947** | **0.990** | **0.943** |

The field-standard flag never misses a real failure but produces **463 false
positives against 207 true ones**. The mechanism: ROR5 asks "was the stop-bar
detector occupied 5 s into red?", which cannot distinguish a *residual queue*
from a *fresh arrival that stopped for the red*. On a through movement with a
continuous arrival stream that happens nearly every cycle — arterial through
movements had a 0 % true failure rate and a 51.6 % flag rate.

**The repair**: add `occupancy over [green_end − 10 s, red_start + 5 s] ≥ 0.90`.
A genuine residual queue is still discharging over the detector right up to the
end of green, so occupancy is continuous; a fresh arrival leaves a gap. This is
computable from the same event log, costs nothing, and raised precision
0.309 → 0.900 with no loss of recall. The 3-of-5 sustained rule (real field
practice) helps far less — it *removes true positives* (recall 1.000 → 0.947)
while only reaching 0.400 precision.

## Where the proxies mislead — verified mechanisms

- **Short queue on a long detector.** 30 m left-turn presence loops produced 114
  false positives whose ground-truth maximum queue had a **median of 1 vehicle**;
  68 % had ≤ 2 vehicles. One car parked on a long loop reads identically to a
  standing queue.
- **Continuous arrivals on through movements** — the dominant false-positive
  source (295 of 567 FPs on arterial through movements alone), mechanism above.
- **Permissive left turns produce absent records, not just wrong ones.** At a
  protected-permissive junction the protected left phase is *skipped* on cycles
  where the permissive movement already cleared demand — 54 of 72 cycles in one
  case, 26 of 72 after retiming. The ATSPM record for that phase simply doesn't
  exist on those cycles, so any per-cycle failure rate has a moving denominator.
  Report green-instance counts alongside percentages.
- **Spillback** — instrument storage explicitly. A 320 m left-turn bay reached
  41 vehicles against ~42 vehicles of storage; a permanently covered detector
  reports `GOR5 = ROR5 = green_util = 1.000` and **zero volume** (no rising
  edges at all), which is a distinctive and recognisable saturation signature.

## Platoon Ratio genuinely tracks delay — at the approach level

Across 8 coordinated approaches, `r(PR, mean control delay) = −0.802` and
`r(AoG %, delay) = −0.852` (−0.736/−0.839 and −0.792/−0.874 on the retimed
runs — stable across plans). **Per cycle within a single approach the
relationship is much weaker and unstable**: mean within-approach
`r(AoG, delay) = −0.414`, ranging from −0.769 to **+0.053**. Use PR to rank
approaches and to decide where to act; do not use it as a per-cycle delay
estimator.

## Retiming from ATSPM alone: what actually paid off

Prescribe splits by moving green from phases the log shows are under-utilised
(coordinated phases ran at 0.40–0.59 green utilisation) to phases in sustained
*refined* split failure (0.91–1.00 utilisation). Prescribe offsets by searching
the shift that maximises volume-weighted AoG over the observed PCD points.

Verified outcome (2 h, 10 233 vehicles, 0 teleports, 0 collisions):

| plan | GT split-failure rate | mean timeLoss | corridor-through timeLoss | trips |
|---|---|---|---|---|
| before (deployed) | 9.2 % | 78.75 s | 74.97 s | 9 475 |
| ATSPM splits only | **0.0 %** | 61.70 s | 75.22 s | 9 535 |
| ATSPM offsets only | 7.6 % | 74.43 s | **67.17 s** | 9 481 |
| **both (adopted)** | **0.0 %** | **59.14 s** | 70.45 s | 9 537 |
| second offset iteration | 0.0 % | 63.69 s | 86.12 s | 9 545 |
| second iteration, damped 0.5 | 0.0 % | 64.58 s | 85.59 s | 9 541 |

**Run the split-only and offset-only ablations** — the headline number hides that
the two halves fix nearly orthogonal problems. Splits delivered essentially all
of the network delay reduction (−21.6 %) and none of the corridor progression
gain; offsets delivered the corridor gain (−10.4 %) and almost no network gain.

**A per-intersection PCD-maximising offset rule does not converge.** Each signal
optimises against an arrival pattern its neighbours' changes then invalidate. A
second iteration made things *worse* than the first (mean timeLoss 59.14 → 63.69 s,
corridor through 70.45 → 86.12 s), and **50 % damping did not rescue it**
(64.58 s) — so this is not simple overshoot. Take one pass from a badly-timed
baseline, verify against ground truth, and stop; do not iterate the greedy rule.

## The NEMA offset/split coupling gotcha

Verified by comparing predicted against measured coordinated-green onset shift
(an ad hoc check during retiming, not a saved script output — reproduce it by
diffing `cycles_*.csv`'s coordinated-phase-onset column across an offset-only
plan pair before trusting the exact figures below):

- With splits unchanged, changing `offset` moves the coordinated green onset
  **exactly 1:1** (J0: predicted −43.5 s, measured −43.43 s, residual 0.07 s).
- **As soon as splits change, the naive correction fails by 5.5–6.6 s** at every
  junction where it was applied. In coordinate mode the coordinated phase begins
  when *both rings actually cross the barrier* under gap-out, not after the
  nominal lead-left split — and its own split length also moves the barrier. A
  model of the form "barrier drift = change in lead-left split" is wrong.

Because of this, **do not prescribe offsets and splits in the same pass and
expect the offsets to land.** Either change splits first, re-log, and prescribe
offsets against the new barrier structure, or accept a several-second offset
error and verify it from the AFTER event log rather than assuming it.

Also expect the coordinated green to **float earlier when lead phases gap out**
(observed sd of onset within a cycle: 2.0–3.9 s, and coordinated greens running
55–70 s against a nominal `maxDur` of 45–53 s because they absorb unused time).

## Gotchas

- **The ATSPM analysis script must be structurally incapable of reading ground
  truth** — one accidental `tripinfo` read invalidates the whole validation.
- **Halting-vehicle counts are not a "did the queue clear" ground truth.**
- **Stop-bar presence detectors under-count volume by 2–7×.**
- **`GOR5 AND ROR5` alone has ~0.31 precision** — add occupancy continuity.
- **Detect phase green from `'G'`, not `'Gg'`, when permissive lefts exist.**
- **Poll TraCI with subscriptions**, not per-object getters, at 0.1 s steps.
- **SUMO discards out-of-order flow departures silently** during incremental
  route loading — sort flows by `begin` (this cost a run: 6 vehicles loaded
  instead of 375).
- **`--summary-output` at 0.1 s step-length writes ~21 MB per run** — don't
  enable it unless you need it.

## Related

- `implement-nema-dual-ring-controller` — the coordinated-actuated controller this
  skill instruments; the `barrier2Phases` coordinated-phase assignment is reused
  and re-verified here, and this skill adds the offset/split coupling finding.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — detector
  placement and binding conventions; note that skill's rule that only E1
  detectors bind to a tlLogic, which is why the stop-bar E2 detectors here are
  observation-only.
- `design-arterial-signal-progression-and-verify-bandwidth` — the analytic
  bandwidth/offset theory this skill's *measured* PCD complements; the offset
  sign-convention discipline applies directly.
- `analyze-simulation-outputs` — tripinfo/edgeData parsing for the ground-truth layer.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — the same
  sensor-proxy-vs-ground-truth validation discipline in an estimation context.
- `generate-hcm-los-report-and-validate-against-microsimulation` — the HCM
  control-delay framing that Platoon Ratio feeds.
- [[automated-traffic-signal-performance-measures]] — the measure definitions,
  the verified proxy-validation numbers, and the retiming findings.
- [[nema-dual-ring-controller]], [[arterial-signal-progression-resonance-bandwidth-and-delay]],
  [[hcm-control-delay-vs-sumo-delay-metrics]].
