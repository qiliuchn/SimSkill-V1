---
summary: Classical automatic incident detection (AID) algorithms — the California comparative family, single-station SND/EWMA change detectors, and fixed occupancy/speed thresholds — benchmarked on a replicated SUMO freeway experiment, where the comparative California #8 algorithm never beat a trivial fixed threshold on detection rate at any matched false-alarm budget because SUMO's default Krauss recurrent congestion is far smoother than field stop-and-go and therefore already separable by a single scalar; detector station spacing mattered several times more than algorithm choice.
keywords:
  - automatic-incident-detection
  - AID
  - california-algorithm
  - standard-normal-deviate
  - EWMA-change-detection
  - detection-rate
  - false-alarm-rate
  - time-to-detect
  - detector-spacing
  - E1-induction-loop
created: 2026-08-04T06:00:00
last_updated: 2026-08-04T06:00:00
sources:
  - "[[episodic-memory/2026-08-04_06-00-00/attempts/attempt-1/action-agent-output.json]]"
  - https://sumo.dlr.de/docs/Simulation/Output/Induction_Loops_Detectors_(E1).html
  - https://sumo.dlr.de/docs/TraCI/Change_Vehicle_State.html
related_pages:
  - "[[incident-rerouting-and-closures]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[freeway-work-zone-capacity-closure-representation-and-merge-control]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
related_skills:
  - build-and-benchmark-freeway-incident-detection
  - simulate-incident-rerouting
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - quantify-sumo-run-to-run-variability
  - design-actuated-signal-detector-placement-and-fault-tolerance
related_skills_for_graph_view:
  - "[[build-and-benchmark-freeway-incident-detection]]"
  - "[[simulate-incident-rerouting]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
---

# Automatic Incident Detection Algorithms

Automatic incident detection (AID) infers, online and causally, that a non-recurrent
blockage has occurred somewhere on a freeway, using only what point detectors report —
volume, occupancy and spot speed on 20-60 s intervals. It is the inference counterpart to
[[incident-rerouting-and-closures]], which assumes the incident is already known.

## The three algorithm families

**Comparative / California family (Payne & Tignor).** Operates on an adjacent
upstream/downstream station **pair**, on the physical premise that a lane blockage makes
occupancy rise upstream while the downstream station drains. Three tests on occupancy:

- `OCCDF   = OCC(up,t) − OCC(dn,t)` — spatial difference
- `OCCRDF  = [OCC(up,t) − OCC(dn,t)] / OCC(up,t)` — relative spatial difference
- `DOCCTD  = [OCC(dn,t−2) − OCC(dn,t)] / OCC(dn,t−2)` — relative temporal difference downstream

Algorithm **#8** adds a compression-wave discriminator, `OCC(dn,t) < T4`: a bulk queue
travelling through raises *both* stations, so a genuine blockage is distinguished by the
downstream station staying uncongested. The canonical state machine is two-stage —
`free → tentative → {incident, compression wave}` — so confirmation always costs one extra
interval, giving a hard MTTD floor of two intervals.

**Single-station statistical change detectors.** The Standard Normal Deviate,
`SND(t) = (x_t − μ_{t−w..t−1}) / σ_{t−w..t−1}`, and an EWMA control chart,
`z_t = λ x_t + (1−λ) z_{t−1}` compared against `L·σ·sqrt(λ/(2−λ))`. Both need the in-control
baseline frozen while alarming, or an ongoing incident walks the baseline up to itself and
the alarm silently clears.

**Trivial thresholds.** Alarm when a single station's occupancy exceeds, or its speed falls
below, a fixed value for `k` consecutive intervals. The reference point any sophisticated
algorithm must beat.

## Operational metrics and the conventions that decide the answer

Detection rate (DR), false alarm rate (FAR), mean time to detect (MTTD) and localization
error. Several bookkeeping choices change conclusions more than algorithm choice does:

- **An alarm is an onset**, not an alarming interval — counting intervals inflates FAR by
  each congestion episode's length.
- **Measure FAR on matched incident-free control days only**, so no alarm is ambiguous.
- **Normalise FAR by each algorithm's own decision-unit count** — a pairwise algorithm has
  `n−1` units where a single-station algorithm has `n`. Per-detector-hour, per-decision-
  unit-hour and per-day differ by one to two orders of magnitude (0.006/detector-hour
  ≈ 0.05/day on a 10-station corridor).
- **Detection instant is the END of the alarming interval** — the algorithm cannot decide
  before the interval is aggregated.
- **Compare at matched FAR *and* at matched DR.** They rank algorithms differently, and the
  comparative algorithm's only measured advantage appeared in the matched-DR view.

## Verified benchmark: the comparative algorithm never beat a fixed threshold

Measured on a 3-lane, 6 km instrumented SUMO mainline (E1 loops all lanes every 250 m, 30 s
aggregation), 40 incident days + 40 CRN-matched control days at each of three demand levels
(81%, 92%, 108% of measured bottleneck capacity), incidents being one or two stopped
vehicles injected by `traci.vehicle.setStop` at a randomly drawn location, time and
duration. Zero teleports and zero collisions across all 240 runs.

Taking the better of the two California variants against the better of the two naive
thresholds, **California won 0 of the 45 (demand × spacing × FAR-budget) cells tested, tied
5, and lost 40**. It was significantly *worse* in 9 of 36 paired-seed McNemar comparisons
(p < 0.05, every one favouring the baseline). Discordance was almost entirely
one-directional: in 26 of 36 cells the count of "California detected and the baseline did
not" was exactly zero. The only cells where California came out ahead at all were against
SND and EWMA — not against the fixed thresholds — at 108% of capacity with 250 m spacing,
and neither was significant.

At 500 m spacing, FAR ≤ 0.05 false alarms per detector-hour:

| demand | California #8 | California #8 (2-stage) | SND | EWMA | fixed occupancy | fixed speed |
|---|---|---|---|---|---|---|
| 81% of capacity | 0.72 | 0.72 | 0.80 | 0.78 | 0.78 | 0.82 |
| 92% of capacity | 0.85 | 0.85 | 0.93 | 0.88 | 0.88 | 0.88 |
| 108% of capacity | 0.80 | 0.78 | 0.85 | 0.85 | 0.97 | 1.00 |

Two independent California #8 implementations — a strict per-interval conjunction with a
tunable persistence count, and the canonical two-stage state machine — scored within a few
points of each other everywhere, which is what makes the null result reportable rather than
a suspected coding error.

## The mechanism: SUMO's recurrent congestion is too smooth to need a comparative test

Comparative algorithms exist because in the field, recurrent stop-and-go congestion
produces spot speeds and occupancies that overlap heavily with incident queues, so no
single scalar separates them. Under SUMO's default Krauss car-following that overlap
largely does not exist — measured directly, not assumed:

| demand | recurrent-congestion speed p50/p10/p1 | incident-queue speed p50/p10/p1 | congested intervals < 8 m/s (recurrent vs incident) | best single-scalar separation |
|---|---|---|---|---|
| 81% of capacity | 23.5 / 18.9 / 15.4 m/s | 5.0 / 1.0 / 0.4 m/s | **0.0%** vs 58.6% | 85.1% balanced accuracy |
| 92% of capacity | 22.4 / 16.6 / 14.3 m/s | 4.2 / 1.0 / 0.5 m/s | **0.0%** vs 78.4% | 93.7% |
| 108% of capacity | 12.4 / 3.8 / 1.4 m/s | 3.6 / 1.0 / 0.4 m/s | 25.8% vs 92.8% | 84.4% |

Below capacity SUMO's "congestion" is a mild, smooth speed reduction that never approaches
a standing queue — the coefficient of variation of spot speed within a congested station
series was ~0.10, versus 0.39 once demand exceeded capacity and genuine stop-and-go waves
appeared. The discriminating work the California tests are designed to do is therefore
already done by the raw signal level.

**This is substantially a finding about the car-following model's congestion realism, not
about the algorithms.** Any claim of the form "algorithm X beats the California algorithm
in SUMO" must be qualified this way; re-testing under a model with stronger oscillatory
instability (see `demonstrate-and-stabilize-phantom-traffic-jams`) would be required before
generalising. It is also a caution for any SUMO study whose conclusion depends on false
alarms generated by recurrent congestion — SUMO will systematically under-produce them.

**The comparative algorithm's one genuine advantage is speed and localization, not
sensitivity.** Under recurrent congestion at matched DR ≥ 0.80, California #8 reached that
DR at 0.0067 FA/detector-hour with MTTD **256 s**, versus 318 s for fixed occupancy and
343 s for fixed speed — 60-90 s faster, because a spatial difference responds to the
queue's leading edge while a level threshold waits for the level to build. Localization was
essentially perfect (mean error 0.0 stations) where single-station algorithms drifted to
0.1-0.5 stations under recurrent congestion. Conversely, at 81% of capacity California
needed FAR ≈ 1.16/detector-hour to reach DR 0.80 at all — two orders of magnitude worse
than SND's 0.012 — because its relative-difference tests are numerically unstable when the
upstream occupancy denominator is small.

## Detector station spacing dominates algorithm choice

At 92% of capacity, 1-lane blocks, FAR ≤ 0.05, DR went 0.30 → 0.70 → 0.95 for California
and 0.50 → 0.75 → 0.95 for fixed occupancy as spacing tightened from 1000 m to 500 m to
250 m. The spread *between algorithms* within a spacing was ~0.1-0.3; the spread *across
spacings* for one algorithm was ~0.5-0.65. **Recommending an AID algorithm without stating
the station spacing it was measured at is close to meaningless.** California degraded worst
at coarse spacing, since a longer pair baseline makes the downstream station of the pair
more likely to be independently disturbed.

## Verified failure modes

1. **The incident never queues back to the nearest upstream station.** The strongest single
   predictor of a miss is the distance from the incident to its nearest upstream detector —
   not demand, not duration. At 500 m spacing DR fell monotonically from 0.94-1.00 (< 150 m)
   to 0.56-0.69 (300-450 m) to 0.00 (> 450 m) at all three demand levels. This is the
   freeway analogue of the occupancy blind spot in
   [[actuated-signal-detector-design-and-fault-tolerance]]: station spacing is really a
   bound on this distance.
2. **Sub-capacity demand plus a 1-lane blockage produces no queue at all.** Blocking 1 of
   3 lanes leaves capacity above demand at 81% loading, so nothing propagates. DR was
   0.10-0.85 for 1-lane blocks versus a uniform 0.85-1.00 for 2-lane blocks — severity
   dominates demand as a detectability driver.
3. **The incident lies downstream of the last station.** At 1000 m spacing the last station
   sat 750 m upstream of the furthest possible incident; California detected 0-1 of the 4
   such incidents, single-station algorithms 2-4, and only via much later upstream queue
   arrival.
4. **Recurrent congestion raises the floor.** At 108% of capacity the downstream 60% of the
   corridor was congested 40-62% of the time on incident-free days; every algorithm's
   zero-FAR operating point degraded (California DR 0.85 → 0.50 from 92% to 108% of
   capacity) and single-station localization error grew from 0.0 to 0.3-0.5 stations.

## SUMO-specific practicalities

- **A stopped vehicle, not a `closingLaneReroute`, is the right incident for AID.** The
  rerouter mechanism is a runtime permission change (see
  [[freeway-work-zone-capacity-closure-representation-and-merge-control]]) — it stops new
  vehicles entering the lane but leaves no physical obstruction and no standing queue at
  the blockage, which is exactly the detector signature AID must key on.
- **`--time-to-teleport -1` is the correct setting for an incident-detection freeway**, and
  needs stating: a freeway with at least one open lane cannot deadlock, whereas any finite
  value teleports vehicles out of the very queue being detected (legitimate waits behind a
  900 s blockage exceed any sane threshold). Verify no running-count freeze regardless —
  see [[teleport-artifacts-and-gridlock-resolution-validity]].
- **Measure capacity, do not assume it.** This corridor's 3-lane pre-breakdown throughput
  peaked at ~5241 veh/h (~1747 veh/h/ln) before the mainline itself broke down, with the
  3->2 lane-drop bottleneck downstream settling to ~4500-5000 veh/h once congested; demand
  levels were set as a percentage of that measured bottleneck capacity (81/92/108%), not a
  textbook per-lane figure.
- **Build the mainline from short equal-length edges** so a station sits at each edge's
  start and every coarser spacing is a post-hoc sub-sample of one instrumented run — the
  whole spacing sensitivity sweep then costs zero extra simulation.
- **Site the recurrent bottleneck downstream of the instrumented corridor.** Queues grow
  upstream, so only a downstream bottleneck's queue propagates into the detection zone,
  which is what creates the masking regime worth measuring.
- **A too-narrow threshold grid manufactures a fake conclusion.** An early sweep capped the
  fixed-occupancy threshold at 32% and reported "no feasible operating point under
  recurrent congestion"; extending the grid to 70% removed that finding entirely. Extend a
  baseline's parameter grid past the point of apparent usefulness before declaring it
  infeasible — the honest comparison depends on it.
