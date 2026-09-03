---
name: build-and-benchmark-freeway-incident-detection
description: Use this skill when the user wants to build or benchmark an automatic incident detection (AID) system on a simulated freeway in SUMO - instrumenting a mainline with E1 loop stations, injecting randomly located/timed stopped-vehicle incidents via TraCI across many replicated "days", running causal online detection algorithms (California #7/#8, SND, EWMA, fixed occupancy/speed thresholds) strictly on the detector time series, and scoring them with detection rate, false alarm rate per detector-hour, mean time to detect and localization error over a threshold sweep. Covers the incident/control CRN day-pair design, the alarm-onset scoring convention, detector station spacing sensitivity, and the verified reasons detection fails (incident never queues back to the nearest upstream station, incident downstream of the last station, incident inside recurrent congestion). Trigger on mentions of incident detection, AID, California algorithm, detection rate, false alarm rate, time to detect, freeway surveillance, loop detector incident detection, or "how well can loop detectors find a crash."
related_skills:
  - simulate-incident-rerouting
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - design-and-control-freeway-work-zone-lane-closures
  - demonstrate-and-stabilize-phantom-traffic-jams
related_skills_for_graph_view:
  - "[[simulate-incident-rerouting]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[design-and-control-freeway-work-zone-lane-closures]]"
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
related_pages:
  - "[[automatic-incident-detection-algorithms]]"
---

# Build and Benchmark Freeway Automatic Incident Detection

Treats **detection of a non-recurrent event** as the object of study, as opposed to
`simulate-incident-rerouting` (whose object is the rerouting *response* to a known
closure) and `design-and-control-freeway-work-zone-lane-closures` (a *planned* closure
you design). Here nobody tells the system an incident happened — an algorithm must infer
it, online and causally, from loop-detector volume/occupancy/speed alone, and be scored
against incident-free control days.

## Pipeline

`scripts/` holds the whole pipeline; `config.py` carries the geometry/demand/detector
constants every other script imports.

| step | script | produces |
|---|---|---|
| network | `build_network.py` | 3-lane, 6 km instrumented mainline + on-ramp + 3->2 downstream lane drop |
| demand | `build_demand.py` | stochastic flows, one route file per demand level |
| detectors | `build_detectors.py` | E1 station ladder, all lanes, every 250 m |
| calibration | `capacity_sweep.py` | measured demand-vs-served-flow curve -> capacity |
| one day | `run_day.py` | TraCI run + incident injection -> `det.npz` + `meta.json` |
| replication | `run_experiment.py` | N seeds x {incident, control} x demand level, 8-way parallel |
| verification | `verify_incident.py` | proves the injection produces a measurable disturbance |
| algorithms | `aid_algorithms.py` | California #8 (two variants), SND, EWMA, fixed occ, fixed speed |
| scoring | `score.py` | full threshold sweep -> DR/FAR/MTTD/localization per cell |
| reporting | `report.py`, `analysis_extra.py`, `mechanism.py` | tables, DR-FAR curves, failure modes |

240 runs (3 demand levels x 40 seeds x 2 arms) of one simulated hour took ~5 minutes
8-way parallel; the full threshold sweep (~1600 parameter settings x 9 cells) is the
expensive half at ~25 minutes and is pure post-processing on the saved `det.npz`.

## Network: put the recurrent bottleneck DOWNSTREAM of the detection zone

The detection target must be the randomly located mid-segment incident, not the
recurrent bottleneck — but you still want a recurrent bottleneck, because "incident
masked by recurrent congestion" is one of the failure modes worth measuring. Site it
**downstream of the whole instrumented corridor** (here a 3->2 lane drop at the corridor's
downstream end): queues grow upstream, so a downstream bottleneck's queue propagates
*into* the detection zone, whereas an upstream merge bottleneck's queue never can.

Build the mainline as a chain of short equal-length edges (250 m here) rather than a few
long ones. A station then sits at `pos=5` of edge `m{k}`, and **every coarser spacing is a
post-hoc sub-sample of the same instrumented run** (`stations_for_spacing()`), so the
entire spacing sensitivity sweep costs zero extra simulation.

**Measure capacity, don't assume it.** SUMO's 3-lane pre-breakdown throughput here peaked
at ~5241 veh/h (~1747 veh/h/ln, measured at the station just upstream of where occupancy
starts climbing) before the mainline itself broke down as inserted demand kept rising;
the 3->2 lane-drop bottleneck downstream settled to ~4500-5000 veh/h once congested. Sweep
demand and read the peak of the served-flow curve (`capacity_sweep.py`), then express
every demand level as a % of the *measured* bottleneck capacity (81% / 92% / 108% here) —
don't assume a textbook per-lane figure.

**Stochastic arrivals are required for day-to-day variation.** Use
`period="exp(RATE)"` on `<flow>` (exponential headways) plus a vType `speedFactor` with
real dispersion, e.g. `normc(1.0,0.10,0.7,1.3)`. With `sigma=0`/no speed deviation the
`sumo --seed` can have literally zero effect (see `quantify-sumo-run-to-run-variability`)
and every "day" is the same day.

## Incident injection: a TraCI-stopped vehicle, not a rerouter

`closingLaneReroute` (the `simulate-incident-rerouting` mechanism) is a *permission*
change: it stops new vehicles entering the lane but leaves no physical obstruction and no
standing queue right at the blockage. For AID you want the detector signature of a real
stopped vehicle, so pick a live vehicle and `traci.vehicle.setStop(vid, edge, pos,
laneIndex, duration, flags=0)`.

- **Pick a blocker with enough lead distance** — 120-500 m upstream of the intended stop
  point, searching both the incident edge and the one before it. Too close and SUMO
  cannot honour the stop; with this rule all 120 injections landed within 8 s of the
  intended time.
- **Draw the incident from the seed alone**, not from run state, so the incident day and
  its control day are a matched CRN pair by construction.
- **Hash the seed before seeding the RNG.** `random.Random(k)` for consecutive integers
  `k` produces visibly correlated first draws — verified here: incident segment clustered
  onto a few values until seeding switched to `sha256(f"...{seed}")`.

## Verify the injection before scoring anything

`verify_incident.py` runs CRN incident/control pairs and checks four things — do this
before trusting any detection number:

1. **CRN holds**: the two arms' detector arrays are *byte-identical* before the injection
   instant (`np.array_equal`). This was true for every pair tested.
2. **The incident is measurable**: occupancy at the station immediately upstream of the
   blockage rises from ~6% to 30-38%; downstream volume drops.
3. **No teleports, no collisions** (0 and 0 across all 240 runs). A freeway with at least
   one open lane cannot deadlock, so `--time-to-teleport -1` is the right setting here —
   a finite value would manufacture teleports out of the incident queue itself, since
   legitimate waits behind a 900 s blockage exceed any sane threshold. Confirm no
   running-count freeze (`validate-congested-scenario-results-against-teleport-artifacts`).
4. **The disturbance is not always there** — at sub-capacity demand a 1-lane block of a
   3-lane road leaves capacity above demand, so no queue forms at all. That is a real
   result, not a broken injection; check it rather than assuming every incident is visible.

## Scoring conventions that decide the answer

- **An alarm is an ONSET** (non-alarm -> alarm transition) per decision unit, not an
  alarming interval. Counting intervals inflates FAR by the length of each congestion
  episode and makes every algorithm look arbitrarily bad.
- **Measure FAR on the control days only.** Incident days contain a genuine disturbance;
  every alarm there is either the detection or an ambiguous echo of it. Matched
  incident-free days make FAR unambiguous.
- **FAR per decision-unit-hour, not per station-hour.** A pairwise algorithm has `n-1`
  decision units to a single-station algorithm's `n`; normalising by each algorithm's own
  unit count is what makes the comparison fair.
- **Detection = first alarm inside both a time and a space window.** Time
  `[t_injection, t_injection + duration + 120 s]`; space, the incident's own upstream
  station through 2 stations further upstream (queues propagate upstream) plus one station
  downstream for single-station algorithms.
- **Detection instant is the END of the alarming interval**, since the algorithm cannot
  decide before the interval has been aggregated. MTTD therefore has a hard floor of
  `persist x interval`.
- **Compare at matched FAR *and* at matched DR.** They rank algorithms differently: at
  matched FAR the question is who detects most, at matched DR it is who is cheapest and
  fastest. California's only genuine win here appeared in the matched-DR view.
- Sweep the whole parameter grid and keep the **Pareto frontier** in (FAR, DR) rather than
  a single hand-picked threshold per algorithm.

## The headline null result: the comparative algorithm never beat a fixed threshold

Verified across 3 demand levels x 3 station spacings x 5 FAR budgets, 40 incident + 40
control days each: taking the better of the two California variants against the better of
the two naive thresholds, California **won 0 of the 45 cells, tied 5, and lost 40**. It was
significantly *worse* in 9 of 36 paired-seed McNemar comparisons (p<0.05, every one
favouring the baseline). Discordance was almost entirely one-directional — in 26 of 36
cells the count of "California detected and the baseline did not" was exactly **0**.
The only cells where California came out ahead at all were against SND and EWMA (not
against the fixed thresholds) at 108% of capacity with 250 m spacing, and neither was
significant.

Examples at 500 m spacing, FAR <= 0.05 false alarms/detector-hour:

| demand | California #8 | fixed occupancy | fixed speed |
|---|---|---|---|
| 81% of capacity | DR 0.72 | 0.78 | 0.82 |
| 92% of capacity | DR 0.85 | 0.88 | 0.88 |
| 108% (recurrent queue) | DR 0.80 | 0.97 | 1.00 |

**Confirm the null is not an implementation artifact** before reporting it. Two
independent California #8 state machines were implemented — a strict per-interval
conjunction with a tunable persistence count, and the canonical Payne/Tignor two-stage
`free -> tentative -> incident/compression-wave` machine — and they scored within a few
points of each other everywhere. This double-implementation check is what makes the null
reportable rather than suspicious.

**The mechanism is measurable, not speculative** (`mechanism.py`). Comparative algorithms
exist because in the field, recurrent stop-and-go congestion produces spot speeds and
occupancies that *overlap heavily* with incident queues, so no single scalar separates
them. Under SUMO's default Krauss car-following that overlap largely does not exist:

- At 81%/92% of capacity, **0.0%** of congested station-intervals on control days had
  space-mean speed below 8 m/s, versus 59%/78% of incident-queue intervals. SUMO's
  sub-capacity "congestion" is a mild, smooth speed reduction (CV of spot speed within a
  congested series ~0.10) that never approaches a standing queue.
- Even at 108% of capacity, where genuine stop-and-go does appear (CV 0.39, 26% of
  congested intervals below 8 m/s), the best single scalar still separated recurrent from
  incident conditions with ~83-84% balanced accuracy.

So the discriminating work the California tests are designed to do is already done by the
raw signal level. **Do not report "algorithm X beats the California algorithm in SUMO" as
a finding about the algorithms** — it is substantially a finding about the car-following
model's congestion realism. Re-testing under a model with stronger oscillatory
instability (see `demonstrate-and-stabilize-phantom-traffic-jams`) is the honest next step.

**California's one genuine advantage**: under recurrent congestion at matched DR >= 0.80,
it reached that DR at 0.0067 FA/detector-hour with **MTTD 256 s**, versus 318 s for fixed
occupancy and 343 s for fixed speed — 60-90 s faster, because the spatial difference
responds to the queue's *leading edge* while a level threshold waits for the level to
build. It also localized essentially perfectly (mean error 0.0 stations) where the
single-station algorithms drifted to 0.1-0.5 stations. Conversely at 81% of capacity
California needed FAR ~1.16/detector-hour to reach DR 0.80 at all — two orders of
magnitude worse than SND's 0.012 — because its relative-difference tests are unstable when
the upstream occupancy denominator is small.

## Verified conditions under which detection fails

1. **The incident never queues back to the nearest upstream station.** The single
   strongest predictor of a miss is the *distance from the incident to its nearest
   upstream detector*, not demand or duration. At 500 m spacing, DR fell monotonically
   from 0.94-1.00 (incident within 150 m of its upstream station) to 0.56-0.69 (300-450 m)
   to 0.00 (>450 m) across all three demand levels. Station spacing is really a bound on
   this distance, which is why halving spacing helps so much.
2. **Sub-capacity demand plus a 1-lane block leaves no queue at all.** At 81% of capacity
   a 1-lane block of 3 lanes leaves capacity above demand; DR was 0.10-0.85 depending on
   algorithm and spacing, versus a uniform 0.85-1.00 for 2-lane blocks. Severity dominates
   demand as a detectability driver.
3. **The incident lies downstream of the last station.** At 1000 m spacing the last
   station sits at x=5000 m while incidents were drawn up to x=5750 m, so 4/40 incidents
   were downstream of all instrumentation. California detected 0-1 of those 4; the
   single-station algorithms caught 2-4 of them, but only via the queue eventually
   reaching an upstream station much later.
4. **Recurrent congestion raises the floor.** At 108% of capacity the downstream 60% of
   the corridor was congested 40-62% of the time on incident-free days. Every algorithm's
   zero-FAR operating point degraded (California DR 0.85 -> 0.50 going from 92% to 108%
   of capacity at FAR=0), and the single-station algorithms' localization error grew from
   0.0 to 0.3-0.5 stations.

## Sensitivity: station spacing dominates algorithm choice

Halving spacing bought far more than switching algorithms. At 92% of capacity, 1-lane
blocks, FAR <= 0.05: DR went 0.30 (1000 m) -> 0.70 (500 m) -> 0.95 (250 m) for California,
and 0.50 -> 0.75 -> 0.95 for fixed occupancy. The spread *between algorithms* within a
spacing was ~0.1-0.3; the spread *across spacings* for one algorithm was ~0.5-0.65.
**Report the spacing sweep before the algorithm comparison** — recommending an algorithm
without stating the spacing it was measured at is close to meaningless. California
degraded worst with coarse spacing, because a longer pair baseline means the downstream
station of the pair is more likely to be independently disturbed.

## Gotchas

- **`random.Random(consecutive_int)` gives correlated first draws** — hash the seed, or
  randomized incident locations will silently cluster.
- **E1/edgeData `file` paths resolve relative to the additional file's own directory** —
  in a parallel batch every run needs its own additional file with an absolute output path,
  or workers overwrite each other's detector output.
- **Aggregate lane speeds with the flow-weighted harmonic mean** (`harmonicMeanSpeed`),
  not the raw `speed` field — see
  [[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]].
- **Raw E1 XML is the bulk of the disk cost** (~1.5 MB/run here). Aggregate to a per-run
  `.npz` inside the run function and delete the XML; the sweep only ever needs the
  aggregate.
- **A too-narrow threshold grid manufactures a fake conclusion.** An early sweep capped
  fixed occupancy at 32% and reported "no feasible operating point under recurrent
  congestion" — extending the grid to 70% removed the finding entirely. Extend a
  baseline's grid past the point of apparent usefulness before declaring it infeasible.
- **`--time-to-teleport -1` is correct here but must be justified**, not defaulted to:
  a freeway with an open lane cannot deadlock, and a finite value would teleport vehicles
  out of the very queue being detected. Verify no running-count freeze regardless.
- **Do not report FAR without stating the normalisation.** Per detector-hour, per
  decision-unit-hour and per day differ by one to two orders of magnitude
  (0.006/detector-hour = 0.05/day for a 10-station corridor here).

## Related

- `simulate-incident-rerouting` — the incident *response* counterpart; its
  `closingLaneReroute` mechanism is the wrong tool for AID (no physical obstruction), which
  is why this skill injects a stopped vehicle via TraCI instead.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — the sensing-layer-as-
  object-of-study methodology and the `harmonicMeanSpeed` correctness point this skill reuses.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — the detector-placement
  blind-zone finding whose freeway analogue is this skill's distance-to-nearest-upstream-
  station result.
- `quantify-sumo-run-to-run-variability` — the CRN replication design and the
  measure-capacity-from-the-flow-peak discipline this skill's day-pair experiment applies.
- `validate-congested-scenario-results-against-teleport-artifacts` — the teleport/freeze
  checks run over all 240 replications here.
- `design-and-control-freeway-work-zone-lane-closures` — the planned-closure counterpart;
  shares the freeway geometry and lane-drop capacity measurement technique.
- `demonstrate-and-stabilize-phantom-traffic-jams` — the natural follow-up: this skill's
  null result hinges on SUMO's recurrent congestion being too smooth, which that skill's
  oscillatory regimes would change.
- [[automatic-incident-detection-algorithms]] — the verified DR/FAR/MTTD numbers, the
  separability mechanism behind the null result, and the failure-mode taxonomy.
