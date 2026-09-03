---
name: implement-detector-free-cv-adaptive-signal-control
description: Use this skill when a traffic signal controller must run on sparse connected-vehicle (CV) / probe observations instead of loop detectors, and the question is how much market penetration is enough. Covers building an observation layer that is STRUCTURALLY incapable of reading non-CV state (subscribe only connected vehicles), two CV queue estimators (1/p count scaling vs. a last-stopped-probe shockwave estimator), a five-arm comparison against fixed-time and fully-detected actuated benchmarks plus a perfect-information ceiling, an empirical information-isolation audit with positive controls, the Binomial(N,p) phase-starvation failure mode and its max-out mitigation, and a break-even penetration analysis with paired replications. Trigger on mentions of connected vehicles, CV market penetration, probe-based signal control, detector-free or detector-less signal control, V2I signal control, "how many connected vehicles are enough", or sensing-limited adaptive control.
---

# Detector-Free Adaptive Signal Control from Sparse CV Observations

Builds and evaluates a signal controller whose *only* input is a random sample of connected
vehicles, and finds the market penetration at which it beats conventional control. This is a
different object of study from every other signal skill in memory:
`implement-maxpressure-traci-controller` and `implement-nema-dual-ring-controller` assume
perfect or fully-detected state, `control-signals-with-actuated-tls` uses SUMO's own detectors,
and `emulate-and-evaluate-partial-sensor-traffic-state-estimation` studies partial sensing as an
*estimation* problem with no controller in the loop. Here the partial sensing is *closed into
the control loop*, so estimation error, decision error and outcome are three distinct layers
that must be measured — and can disagree.

`scripts/cvcontrol.py` is the reusable core (observation layer, CV assignment, both estimators,
the runtime guard, and `PerfectMP`/`CVMP` controllers built on
`implement-maxpressure-traci-controller`'s phase-mapping / min-green / yellow-and-all-red
machinery). `scripts/runner.py` runs one arm with full three-layer logging;
`scripts/estimator_bench.py` measures the estimation layer on matched traffic;
`scripts/audit_isolation.py` runs the five-part isolation audit.

## Build the observation layer so isolation is structural, not promised

**Subscribe only connected vehicles.** `traci.vehicle.subscribe(vid, [VAR_LANE_ID,
VAR_LANEPOSITION, VAR_SPEED])` at departure for vehicles that pass the CV draw, then read
`traci.vehicle.getAllSubscriptionResults()` once per decision epoch. A non-connected vehicle's
state is then never fetched from SUMO at all — the controller cannot read what was never
retrieved — and the whole observation costs one batched TraCI call instead of one call per
vehicle. Pass the resulting `{lane: [(id, pos, speed)]}` dict into the controller as its only
traffic argument.

**Assign connectivity by a seeded hash of the vehicle ID**, `u(vid) =
blake2b(salt|vid)/2^64`, connected iff `u < p` — never by route, OD, departure order or vehicle
class. This also makes the penetration sweep *nested* (the p=2% fleet is a subset of the p=5%
fleet), which is a free Common-Random-Numbers design across p. Vary the salt with the
replication seed so the CV draw is averaged over, and verify exogeneity directly (chi-square of
realised rate across movement cohorts; correlation between the draw and departure time).

**Wrap every ground-truth getter with a guard that raises while the CV controller is
deciding.** Exempt `:`-prefixed internal lanes — they are read by the all-red clearance
interlock, which is junction safety state, not approach state — but **count** those reads and
report the count rather than allowing them silently.

## The isolation audit (five parts, all empirical)

Accidental ground-truth leakage is the easiest way to fake a good result, so prove isolation
rather than asserting it:

1. **Runtime guard violations = 0** across every CV run, with the exempted internal-lane read
   count reported alongside.
2. **p = 0 degrades to the documented fallback.** Do not test this by expecting tripinfo
   identity with the fixed-time plan — it will not hold. Test the *phase sequence*: reconstruct
   the served-green order and check every transition advances by exactly one step in the
   program's cyclic order. Verified contrast: 0 out-of-order transitions out of ~530 at p=0,
   versus 235–258 out of ~630 at p=10%, which is what gives the check power.
3. **Non-CV perturbation replay.** Record full ground-truth lane states at real decision
   epochs, then replay them offline through the *whole* pipeline (observation layer → estimator
   → pressure → argmax) with non-connected vehicles added and deleted. Both the observation and
   the decision must be bit-identical.
4. **Positive controls, or the replay test is worthless.** Mirror the perturbation on the CV
   side — delete one connected vehicle, and add the same number of connected vehicles that you
   added non-connected ones. Verified: adding 20 non-CVs changed 0/191 decisions while adding 20
   CVs changed the observation 191/191 times and the decision 66/191 times. Without the mirror
   you cannot distinguish "isolated" from "inert".
5. **A full-penetration exactness check.** At p = 100 % the `k/p` estimator must reproduce
   `getLastStepHaltingNumber` **exactly** (verified: bias 0.000, RMSE 0.000) and the CV
   controller must agree with the perfect-information controller on **every** decision epoch
   (verified: 1.0000 ± 0.0000). This is the strongest single end-to-end wiring check available;
   if it does not hold, something in the pipeline is wrong.

## Two estimators, and the crossover between them

- **Naive**: `q̂ = (observed stopped CVs)/p`. Close to unbiased for the two arterial movement
  groups in a verified sweep, but bias is **movement-group-dependent** — the busier cross-street
  group reached |bias| up to ~0.99 veh at low p, not a uniform small figure. Variance, not bias,
  is its dominant problem at low p.
- **Shockwave / last-probe** (Comert–Cetin spirit): from the upstream-most *stopped* probe at
  distance `d` behind the stop bar, `q̂ = d/spacing + 1 + (1−p)/p`, capped at physical storage.
  The `(1−p)/p` term is the mean Geometric count of unobserved vehicles behind the last probe.
  Position, not count, carries the information — one probe deep in a queue reveals the whole
  queue behind it.

**Expect a crossover, not a winner — and expect it to be movement-group-dependent, not one
number.** Verified per-movement RMSE crossovers ranged from p ≈ 2–5 % (busiest arterial through
movement) to p ≈ 10–20 % (cross street) to p ≈ 20–50 % (lighter arterial left-turn movement) —
don't quote a single corridor-wide crossover penetration; measure it per movement. **The
shockwave estimator has a bias floor that penetration cannot remove** — on the arterial through
movement its bias ran from about −0.4 veh at p = 2 % up to +5.4 veh at p = 100 %, crossing sign
as penetration rose, and its RMSE bottoms out around p = 20 % and then rises, because converting
a distance to a count at a fixed jam spacing over-counts whenever the standing queue contains
larger gaps. This is the same class of structural bias as the GPS-ping-period floor in
[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]; report it rather than assuming
the "better" estimator dominates everywhere.

## Measure three layers separately, and expect them to disagree

**Estimation layer — measure it on MATCHED traffic, not inside the closed loop.** A low-p
controller creates much longer queues, so an RMSE measured inside its own run is confounded by
its own bad control. Run one *open-loop* simulation per seed under a neutral benchmark and
evaluate every estimator at every p against ground truth on the same traffic state
(`scripts/estimator_bench.py`). Ship both tables and be explicit about which is which — the
gap between them is itself the point.

**Decision layer.** At every CV decision epoch, compute what the perfect-information controller
would have chosen *on the identical state* (in-run, immediately after the CV decision, outside
the guarded region) and record agreement. **Agreement is not a good predictor of outcome**:
verified case where the estimator with *lower* agreement had equal-or-better delay, and the
best-performing high-p variant had the lowest agreement of all. Disagreeing with greedy
max-pressure is not the same as being wrong.

**Outcome layer.** Mean and 95th-percentile delay, stops, throughput and max queue, **reported
separately for arterial-origin and cross-street-origin cohorts**. This is not optional
bookkeeping: max-pressure is a *redistribution*, not a uniform improvement — verified case where
perfect-information max-pressure was statistically tied with actuated network-wide
(+0.59 ± 4.13 s, n.s.) while being 37.8 s worse on the arterial and 24.1 s better on the side
street. A single network-wide number hides the entire effect.

## The starvation failure mode is exactly Binomial

Log, per decision epoch and per approach, the observed CV count alongside the true halting
count. Then compute `P(observe zero CVs | true queue = N)` and compare against `(1−p)^N`.
**Verified to match almost exactly** (absolute error < 0.02 in 32 of 40 cells for the naive
estimator across p ∈ {2,5,10,20,50}% × N ∈ {1..8}, worst-case cell still within 0.04); match
quality degrades somewhat at larger N, where the residual excess is platoon correlation.

Two distinct small-sample mechanisms drive the control cliff, and both must be reported —
"less data is worse" is not an explanation:

1. **Sampling variance.** `K ~ Binomial(N,p)`, so `k/p` has CV `√((1−p)/(Np))`. Once that
   exceeds 1, an argmax over several such estimates is close to uniformly random — which is
   *worse* than a fixed plan, because it randomises phase order without randomising demand.
2. **Discreteness — the quantum exceeds the queue.** The naive estimate lives on the lattice
   `{0, 1/p, 2/p, …}`. Verified: at p = 2 % the estimator took **6 distinct values** over 40 978
   epochs and was exactly 0 in 77.5 % of them, while the position-based estimator took 32 (and
   1 529 at p = 5 % against the naive estimator's 10). The pressure comparison is then decided by
   *which approach happens to contain a probe*, not by how long its queue is. Report the
   distinct-value count and the fraction-exactly-zero — they make the collapse of resolution
   visible in a way RMSE does not.

Map blindness to consequence: track the **maximum time between successive services of each
phase** (from the actual `traci.trafficlight.getPhase` trace, so it works for controller and
non-controller arms alike) and the **95th-percentile side-street delay**. Verified: at p = 2 %
the cross street went 430–608 s without service against 67 s under the fixed-time plan, with
p95 side-street delay of 868 s against 427 s for actuated.

## Mitigate by bounding the failure, not by imagining the data

Ablate mitigation components separately — a combined "mitigation" arm hides opposite effects:

- **A per-phase max-out / force-off timer works and is the component that helps at very low
  penetration.** Verified: −26.5 ± 20.6 s at p = 2 % (significant), and it flattens the worst
  service gap to a constant ~150–166 s at *every* penetration. It is also significantly
  *harmful* at p = 10 % (+9.2 ± 5.2 s) — once the estimator is good enough, a fixed max-out
  overrides correct decisions.
- **Exponential-smoothing / memory imputation of unobserved approaches actively hurts exactly
  where it is supposed to help.** Verified: adding memory on top of force-off cost
  **+66.6 ± 21.7 s at p = 2 %**. With most non-empty approaches invisible, carrying a stale
  non-zero estimate forward makes the controller sticky precisely where it is least informed.
  It only pays off at high penetration (significant gains at p ≥ 20–50 %).

The transferable rule: **bound the failure, don't imagine the data.** A max-out timer costs
nothing when information is good and rescues the tail when it is not; imputation helps only
when you already had enough data.

## Running the comparison honestly

- **Five arms, one demand.** Fixed-time (Webster splits + a real coordination plan — use
  `design-arterial-signal-progression-and-verify-bandwidth`'s exact MAXBAND search, not zero
  offsets, or the baseline is a strawman), fully-detected actuated (tune `max-gap` and `maxDur`
  over a small grid — an untuned actuated arm can be 40 % worse than a tuned one), max-pressure
  with perfect state, and the two CV variants. Identical route file, identical `sumo --seed`
  list, identical per-seed CV salt.
- **Run the benchmark arms through TraCI too**, with no controller attached, so the
  ground-truth instrumentation (per-approach queue, service gaps, max queue) is produced
  identically for every arm.
- **≥ 10 seeds per configuration, paired t-tests, and say which differences are not
  significant** (follow `quantify-sumo-run-to-run-variability`). Several of the most important
  results here are non-significant ones.
- **Check `departDelay` separately.** It is *not* included in `timeLoss`, and in the failing
  configurations it is where much of the cost hides — verified: 0.8 s at p ≥ 10 % but 34.9 s
  (max 775 s) at p = 2 %, so the headline delay understates the low-p penalty.

## Gotchas

- **`netconvert -s net.xml -i plan.add.xml -o out.net.xml` APPENDS the plan as a second program
  alongside netconvert's own default program `"0"`** (verified: 4 junctions → 8 `<tlLogic>`
  elements). `traci.trafficlight.getAllProgramLogics(tls)[0]` then returns the *wrong* program
  and every phase index in the controller is silently off. Strip the default and rename the
  intended plan to programID `"0"` so there is exactly one program per junction.
- **`<param key="coordinated" value="true"/>` + `<param key="cycleTime" .../>` on an
  `actuated` `tlLogic` is silently ignored** (SUMO 1.27.1). It survives into the compiled
  `.net.xml` and looks applied, but tripinfo is byte-identical to the plain actuated run for
  every vehicle on every seed. This is another instance of the documented
  "unrecognized `<param>` is ignored, not rejected" hazard — verify by a behaviour-changing
  comparison, never by absence of an error.
- **Max-pressure summed over the SET of incoming/outgoing lanes systematically starves the
  arterial on a corridor**, because the through phase's receiving lane is the next
  intersection's approach and is usually queued. Sum over the phase's green lane-to-lane
  **links** instead (the Varaiya per-movement form) — verified: 251.8 s → 179.2 s mean delay at
  otherwise identical settings.
- **A uniform short min-green makes max-pressure lose to fixed-time on lost time alone.**
  Verified: min-green 10 s produced 296 phase switches × 4 s = 25 % of the hour in lost time
  versus 13 % for a 90 s fixed cycle. Scale min-green to the *programmed* green
  (`max(floor, frac × programmed)`) and tune `frac`; verified plateau at 0.6–0.8 with a
  109 s result versus 179 s at the untuned setting. Apply the same tuning to the
  perfect-information arm and every CV arm, or the comparison measures tuning, not information.
- **`tlsCycleAdaptation.py` re-orders the phase table** (emits a lead-lag structure, drops the
  all-red). That breaks phase-index comparability across arms and makes any decision-agreement
  metric undefined. Compute Webster directly on the fixed phase structure and validate against
  the tool's `--write-critical-flows` output instead.
- **`ET.iterparse` with `el.clear()` on a child element destroys the parent's data** — clearing
  `<route>` at its own end event blanks the `edges` attribute before the enclosing `<vehicle>`
  end event fires. Clear only the element you are actually finished with.
- **A raw run store gets large fast** (~5 MB/run of `tripinfo` + `summary` at ~7 000 vehicles;
  312 runs ≈ 1.5 GB). Compact to a per-vehicle CSV of exactly the fields the analysis uses,
  keep the full XML for one seed per arm so the compaction itself is auditable, and make the
  analysis read either form.
- **A fixed `--end` with no `--tripinfo-output.write-unfinished` silently censors exactly the
  worst-starvation cells.** In the lowest-penetration arms, some vehicles never escape gridlock
  before the simulation horizon and are dropped from `tripinfo` entirely rather than charged a
  large delay — one verified case lost 35% of vehicles from a single p=2% seed. This produces a
  survivor-biased subsample precisely in the regime a CV-penetration study exists to
  characterize, silently understating the true severity there. Always pass
  `--tripinfo-output.write-unfinished` and either extend the horizon or apply a stated
  horizon-censoring penalty (see [[network-link-criticality-and-proxy-validation]]) before
  reporting delay statistics for a starvation-prone low-penetration cell.

## Related

- `implement-maxpressure-traci-controller` — the phase-mapping, min-green and
  yellow/all-red-clearance machinery this skill's controllers subclass; this skill corrects its
  set-based pressure sum to the per-movement form and adds the min-green scaling finding.
- `emulate-and-evaluate-partial-sensor-traffic-state-estimation` — the open-loop counterpart:
  same sensing-as-object-of-study framing, but with no controller in the loop. Its
  "penetration-independent structural bias" pattern reappears here as the shockwave estimator's
  jam-spacing bias floor.
- `control-signals-with-actuated-tls` — the fully-detected benchmark, and the source of the
  "unrecognized `<param>` is silently ignored" hazard that the `coordinated` finding extends.
- `design-arterial-signal-progression-and-verify-bandwidth` — the corridor geometry, the
  Webster/unified-cycle discipline and the exact MAXBAND offset search used to build a
  non-strawman fixed-time baseline.
- `quantify-sumo-run-to-run-variability` — the CRN and replication-count discipline; this skill
  extends CRN to hold across market-penetration levels via a nested CV draw.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — the detector-based
  counterpart of the same "what happens when the controller goes blind" question.
- `analyze-simulation-outputs` — tripinfo/summary conventions for the outcome layer.
- [[connected-vehicle-penetration-and-detector-free-signal-control]] — the verified break-even
  penetrations, the Binomial blindness law, the discreteness cliff, the estimator crossover and
  the mitigation asymmetry this skill's methodology produced.
- [[max-pressure-signal-control]] — the control law's background and the prior
  beats-fixed-time/ties-actuated finding this study reproduces and localises by cohort.
