---
name: calibrate-lane-changing-parameters-at-a-freeway-diverge
description: Use this skill when the user wants to treat SUMO's LANE-CHANGING parameters (lcStrategic, lcCooperative, lcSpeedGain, lcKeepRight, lcAssertive, lcLookaheadLeft, lcSpeedGainRight and the --lanechange.duration setting) as things to be CALIBRATED against per-lane flow shares and lane-change-event field targets, rather than accepted as defaults — typically on a freeway off-ramp diverge where exiting is a genuine mandatory (strategic) lane change. Covers hand-authoring a deceleration/auxiliary-lane diverge whose compiled net proves the exit is mandatory, instrumenting with --lanechange-output plus laneData and per-lane E1, building LC-density-vs-distance-to-gore and cumulative-exit-lane-arrival profiles, Morris screening per observable, GA vs pattern-search calibration against a weighted per-lane-GEH/RMSN plus spatial-LC objective, and the identifiability results (lcKeepRight/lcSpeedGain trade-off, lcStrategic identifiable only below its default from the spatial profile, known-answer recovery). Also documents the lcStrategic=0-is-not-off trap, the wrong-lane teleport mechanism, the tripinfo-only-lists-completed-trips trap, and the hard LC2013/sublane incompatibility. Trigger on mentions of lane-change model calibration, LC2013 parameters, lcStrategic/lcKeepRight/lcSpeedGain, off-ramp diverge modelling, mandatory vs discretionary lane changes, or --lanechange-output.
related_skills:
  - calibrate-car-following-parameters-against-field-targets
  - quantify-sumo-run-to-run-variability
  - model-freeway-weaving-segment
  - compare-zipper-vs-default-merge-at-lane-drop
  - simulate-motorcycle-lane-filtering-with-sublane-model
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[model-freeway-weaving-segment]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[simulate-motorcycle-lane-filtering-with-sublane-model]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[sublane-model-and-lane-filtering]]"
  - "[[sumo-output-files]]"
  - "[[geh-statistic]]"
  - "[[lane-change-model-calibration-and-identifiability-at-a-diverge]]"
---

# Calibrate Lane-Changing Parameters at a Freeway Diverge

The lane-changing analogue of `calibrate-car-following-parameters-against-field-targets`.
That skill treated the car-following vector as the object of study and found it not
uniquely identified from macroscopic data. This one does the same for LC2013 on a facility
where lane changing is the whole physics — a freeway off-ramp diverge — and reaches the
same structural conclusion plus a sharper one: **aggregate per-lane counts and the
lane-change event stream identify different parameters, and neither alone is enough.**

Keep the facility distinct from `model-freeway-weaving-segment`: no on-ramp, no shared
auxiliary lane, the diverge itself is the object.

## Build the diverge so the exit is provably mandatory

Hand-author plain XML + `netconvert` (not `netgenerate`). The pattern that works:

```xml
<!-- edges: A(3) B(3) C(3) mainline, D(4) with lane 0 = the decel lane, E(3), R(1) ramp -->
<connection from="C" to="D" fromLane="0" toLane="1"/>   <!-- through lanes shift LEFT -->
<connection from="C" to="D" fromLane="1" toLane="2"/>
<connection from="C" to="D" fromLane="2" toLane="3"/>
<connection from="D" to="E" fromLane="1" toLane="0"/>
<connection from="D" to="E" fromLane="2" toLane="1"/>
<connection from="D" to="E" fromLane="3" toLane="2"/>
<connection from="D" to="R" fromLane="0" toLane="0"/>   <!-- ONLY feed to the ramp -->
```

`D_0` has **no** incoming connection, so the auxiliary lane can only be entered by a lane
change — that is what makes it a deceleration lane rather than a fourth through lane.
Assert four things from the compiled `.net.xml` before running anything (see
`scripts/build_net.py::verify`): no connection targets `D_0`; the only connection into `R`
comes from `D_0`; `C_0` is the only lane reaching `D_1`; and any junctions you introduced
to make measurement windows exact edges have internal lanes of ~0.1 m.

**Use `--junctions.minimal-shape true`.** Without it netconvert displaced the gore junction
by 68.24 m (`Warning: Shape for junction 'n4' has distance 68.24 to its given position`)
and a nominally 300 m auxiliary lane compiled to **364.2 m**, silently invalidating every
distance-to-gore statistic. Check the compiled lane `length`s against the design.

**Split the mainline into edges at the measurement cross-sections** (station, and the start
of the discretionary-LC window). Then `laneData`'s `entered` at the station edge is exactly
the station's per-lane flow and `edgeData`'s `entered` on the window edge is exactly the
LC-rate denominator. The internal lanes cost 0.1 m each and do not suppress lane changing.

## Demand: route-based, and deliberately mis-seeded

Use two explicit routes (`thru`, `exit`) with `<flow>`, not randomTrips, so every vehicle's
exit intention is known a priori. Insert with `departLane="random"` (33/33/33) so the model
has to *produce* the observed split rather than inherit it, and check
`loaded == inserted` and mean `departDelay` from `--statistic-output` before believing any
lane share — a boundary-insertion ceiling would fix the split for you.

## Instrument three ways and cross-check before trusting any of them

1. `--lanechange-output` -> a per-event table keyed by vehicle, time, from/to lane,
   longitudinal position and `reason`. **`pos` is edge-local**: map it to absolute station
   via the compiled edge offsets, and drop (counting them) any event logged on an internal
   junction lane.
2. `<laneData>` meandata on the station edge (`entered` per lane).
3. Per-lane `<inductionLoop>` at the same cross-section.

**Verify 2 and 3 agree before using either.** They agreed here to 0.18 % (1306/1664/1825 vs
1307/1661/1828). **The E1 `period` must divide the meandata window**: a first pass with
`period = window length` wrote intervals `[0,1200]` and `[1200,2400]` against a meandata
window of `[300,1500]`, so E1 totalled the whole run (2134 veh) and meandata the window
(1601 veh) — a 33 % "instrument disagreement" that was purely window misalignment.

`reason` is a `|`-joined string: split the **motivation** token
(`strategic`/`cooperative`/`speedGain`/`keepRight`/`sublane`) from the **urgency**
qualifier (`urgent`). Observed raw strings on a default diverge run: `speedGain` (8617),
`strategic|urgent` (1806), `strategic` (1228), `keepRight` (1186), `cooperative|urgent`
(27) — note `cooperative` appeared *only* in its `|urgent` form.

Derive two spatial products, both normalised so they are comparable across runs:
**LC density per 100 m per 1000 vehicles vs distance to gore**, split by reason; and the
**cumulative fraction of exiting vehicles already in an exit-capable lane vs distance to
gore**, with vehicles that departed in the exit lane and never left counted at their
departure position (otherwise the curve is conditioned on a parameter-dependent
subpopulation).

## There is no advance-signing distance: LC2013's strategic pull is route-global

Do not choose an approach length to "contain" the mandatory manoeuvre — it cannot be
contained. Verified by rebuilding the identical facility with a 7400 m approach instead of
3600 m: **38.6 % of all strategic lane changes then occur more than 3600 m from the gore**,
and the profile is flat (30–81 events per 200 m bin) back to the insertion point.
`bestLanes` spans the whole remaining route, so an exiting vehicle drifts right from the
moment it is inserted. Two genuine peaks remain in both facilities: an insertion-correction
spike in the first bin and the auxiliary-lane-entry spike in the 200–400 m bin.
**Consequence: the measured spatial LC profile depends on where the network boundary is.**

## Screen per observable, and expect a different ranking from car-following

Reuse the Morris sampler from
`calibrate-car-following-parameters-against-field-targets/scripts/morris.py` (import
`trajectory()`; p=4, Δ=2/3) and compute μ*/σ for **every observable separately**, each
normalised by its own target. Verified ranking (r=10, 4 CRN seeds, 360 runs, 0 failures;
**bold** = above 2x the EE seed-noise floor):

- **`lcAssertive` is the most influential parameter overall** — 1st on the objective, on
  both outer lane shares, on p50 and on station flow, 2nd on the discretionary LC rate. It
  is almost never calibrated in practice. (The lane-changing counterpart of
  `apparentDecel`.)
- **`lcLookaheadLeft` is the top control of the spatial statistic (μ\* 1.90 on p85) and the
  *weakest of all eight* on every lane share** (μ\* 0.054/0.020/0.027, ranked last three
  times). It is recoverable only from the LC event stream.
- **`lcSpeedGain` dominates the discretionary LC rate** (μ\* 5.94, 1.3x the next).
- **`lcKeepRight` ranks last** on the objective, on the strategic rate and on p85 — but see
  the demand caveat below before generalising.
- `lcStrategic` has a large μ\* on lane shares with μ/μ\* = 0.17 (cancelling, non-monotone)
  and μ/μ\* = 0.76 on p85 (monotone). Resolve such a split with a one-at-a-time sweep.
- Observables that are **exactly zero in every default replication** (cooperative rate and
  the exit-failure fraction in free flow) have a measured seed SD of 0, so an
  "above the noise floor" test on them is vacuous. Flag them; do not report them as active.

## Calibrate, then apply the acceptance test separately

Weighted objective over per-lane-share RMSN + a discretionary-LC-rate term + the spatial
term + a failure penalty. Use **log-ratio errors** for the spatial and rate terms: they
span more than an order of magnitude across the parameter box and a plain relative error
saturates the clip and flattens the surface. Scale so "wrong by a factor of 3" scores 1.0.

Run two optimisers on identical objective, CRN seeds and budget accounting. A lock-step
multistart compass search (all restarts' trial points batched into one parallel pool per
iteration) beat a generational GA here on a comparable budget (0.276 vs 0.532 in 639 vs 360
candidate evaluations). Seed one restart at the SUMO defaults — it won.

**Re-evaluate the reported optimum on seeds the optimiser never saw.** The search score is
an optimistic order statistic: 0.276 (3 CRN seeds) became **0.402 ± 0.058 on 16 independent
seeds, 46 % worse**. Then apply GEH < 5 per lane as a *separate* acceptance test, with the
target lane *flow* defined as observed total flow x target share so GEH scores the split,
not the total. The lane-share RMSN term is far too weak to enforce GEH < 5 on its own
(RMSN ~0.05 where the spatial term is ~0.4); if the weighted optimum lands outside the
criterion, re-optimise with a hinge on `max(0, GEH_max − 5)` rather than reweighting by feel.

Report what calibration *cost*, not only what it bought. Here it improved the spatial
statistic by 63 % while making the lane split worse (max GEH 1.65 -> 2.84) and moving the
discretionary LC rate further from target (0.389 -> 0.313 vs a 0.45 target), with
throughput statistically unchanged (paired difference −0.06 ± 3.84 veh/h, ns).

## Identifiability: run these four tests, and check asymmetric answers from both sides

1. **`lcKeepRight` x `lcSpeedGain` grid.** 69 of 1176 pairs on a 7x7 grid were
   indistinguishable in per-lane flow at 2x the 4-seed noise threshold, with unit-cube
   separations up to 0.925. **The tie is broken by the event stream**: the most separated
   tied pair differs 3.5x in discretionary LC rate (0.844 vs 0.240 LC/veh/km). Loop counts
   alone cannot separate these two parameters; `--lanechange-output` can.
2. **`lcStrategic` sweep — the answer is asymmetric.** Below the default (0.10 -> 1.00)
   lane-0 share moves +0.0035, *inside* the 0.0041 six-seed noise band (not identifiable
   from lane flows), while p50 moves 97 -> 299 m (3.07x) and p85 by +431 m (identifiable
   from the spatial profile). Above the default (1.00 -> 6.00) lane-0 share moves +0.0493,
   12x the noise band (identifiable from lane flows). **Reporting only one half would be
   wrong in one direction** — always sweep both sides of the default.
3. **Known-answer recovery.** Perturb the calibrated vector, regenerate the targets from
   *that* vector's own raw output, re-run the optimiser. Observables came back to
   +3.7 %/+0.4 %/−2.8 % on lane shares, +1.8 % on p85 and −11.0 % on the LC rate, while
   individual parameters were off by up to **+128.6 %** (`lcLookaheadLeft`), −65.5 %
   (`lcSpeedGain`), +120.3 % (`lcKeepRight`); total unit-cube distance 0.4609 over 7
   parameters. Note honestly when the winning restart was the default-seeded one and
   coordinates simply never moved — that *is* the identifiability result.
4. **Do not read the optimiser's own tied-band width as equifinality.** Only 5 of 999
   logged candidates fell inside `best + 2·SD_seed`, but that is where a compass search
   samples, not the shape of the surface. The design-independent evidence is the grid and
   the recovery test.

**`lcKeepRight` is demand-dependent, not weak.** It screened last here, which appears to
contradict the earlier finding in `conduct-driveway-signal-warrant-traffic-impact-analysis`
that keep-right badly unbalances a multi-lane approach. Both are right. Sweeping
`lcKeepRight` ∈ {0,1,6}, the right-lane share range is **0.376 at 400 veh/h/ln**, 0.171 at
800, and **0.0265 at 1600** — a 14x collapse in leverage. Never carry a keep-right verdict
across demand levels.

## Four traps, each verified from raw output

**`--lanechange.duration` defaults to 0** (instantaneous, zero-width changes). Turning it to
3 s cut LC events by 6.4 % (default vector) / 15.0 % (a high-`lcSpeedGain` calibrated
vector) and left throughput untouched (station flow 4800 -> 4798, ramp 961 -> 960). The
calibrated vector **transferred on the acceptance criterion** (max GEH 2.80 -> 2.33, still
PASS, lane shares moved ≤0.002) but **not on the spatial statistic** (p85 915 -> 1282 -> 628 m
across 0/1/3 s, non-monotone). This *bounds*
[[system-interchange-weaving-and-design-selection]]'s +10.4 % throughput effect: it acts
through the weaving mechanism, and at an uncongested diverge with no weaving it is absent.

**`lcStrategic = 0` does NOT disable strategic changing** — only a *negative* value does.
At 0.00 every vehicle still exited (ramp flow 957.5 vs 960.2 at the default), zero
teleports, zero failures. Putting 0 at the bottom of a screening range measures nothing.
(Caveat: this row's raw data shows a mean of 0.75 real collisions across its 4 seeds —
not exactly zero on every metric despite being reported as a clean control. Doesn't change
the conclusion, but check every metric on a "clean" control row, not just the one you're
screening for.)

**What SUMO does to an exiting vehicle that misses the exit lane** (forced with
`lcStrategic = -1`), verbatim from stderr:
`Warning: Teleporting vehicle 'f_exit_car.56'; waited too long (wrong lane), lane='D_3', ...`
then `Warning: Vehicle 'f_exit_car.56' ends teleporting on edge 'R', ...`.
It **stops at the lane end and blocks the mainline** until `--time-to-teleport` fires, then
**teleports onto the next edge of its route — the ramp itself**. It does not miss the ramp
and does not re-route. The contamination is upstream and severe: station flow collapsed
4800 -> 402 veh/h, ramp flow 961 -> 16 veh/h, only 1480 of 5333 vehicles ever inserted, and
through vehicles were dragged in (`f_thru_car.21 ends teleporting on edge 'E'`). Congestion
alone did *not* reproduce it (2200 veh/h/ln, default parameters: zero teleports).

**`tripinfo` lists only COMPLETED trips, so a failure-rate metric built on it hides exactly
the failures.** In the gridlocked case the exit-failure fraction read **NaN** (empty
denominator), not 1.0; at a lower demand where vehicles eventually completed via teleport
it read a healthy-looking 0.376. Always cross-check against
`loaded`/`inserted`/`running`/`halting`/`teleports` from `--statistic-output` and
`--summary-output`.

**LC2013 cannot run under the sublane model at all** —
`Error: Lane change model 'LC2013' is not compatible with sublane simulation`. Enabling
`--lateral-resolution` *forces* SL2015, so "the same calibration with sublane on" is not
expressible. Compare three arms (LC2013/off, SL2015/off, SL2015/on) with identical `lc*`
values. Carrying the calibrated values to SL2015+sublane kept GEH < 5 (2.52) but moved the
middle-lane share +4.0 pp, cut LC events 38 % and the discretionary rate 21 %. The same
`lcSpeedGain` change multiplies the discretionary rate by **4.4x under LC2013, 1.11x under
SL2015+sublane and exactly 1.00x (inert) under SL2015 without `--lateral-resolution`** —
and SL2015-without-lateral-resolution is a degenerate configuration that emits *zero*
`speedGain` events and reverses the lane distribution. `lcStrategic` was the one parameter
that behaved consistently across all three arms.

## Validate on a hold-out, and prefer the target-free statement

Hold out a different mainline demand *and* a different exit share. Here the GEH < 5
criterion failed on every hold-out cell for **both** the default and the calibrated vector
— but the useful result does not depend on the declared hold-out targets: **SUMO's LC2013
lane distribution is nearly invariant to both demand and off-ramp share.** Raising the exit
share 20 % -> 35 % at constant demand moved the right-lane share by +0.68 pp (default) /
+0.01 pp (calibrated); dropping demand 1600 -> 1200 veh/h/ln moved it by −0.62 / −0.88 pp.
The calibrated vector was *less* transferable than the default, for an identifiable reason:
calibration drove `lcKeepRight` to 0.262, and that is precisely the parameter that makes
the split demand-sensitive. **When a hold-out target is declared rather than measured,
always report the target-free comparison alongside the GEH verdict.**

## State which percentile a spatial LC target refers to

The default vector's *median* last-change distance was 296.7 ± 2.0 m against a 400 m target
(−26 %), while its *85th percentile* was 2464.5 ± 64.8 m against the same target (6.2x too
far). Same model, same data, opposite verdicts. p85 is also a noisy statistic (seed SD 195 m
at the default vector, 263 m at the calibrated one, needing ~12 replications for a ±5 % CI),
so quote it with its seed set and CI.

## Gotchas

- **`--junctions.minimal-shape true`** or netconvert silently lengthens the auxiliary lane
  (300 -> 364.2 m here) by displacing the gore junction.
- **E1 `period` must divide the meandata window**, or the two instruments disagree by the
  ratio of run length to window length for no physical reason.
- **`lcStrategic = 0` is not "off"**; only negative values disable strategic changing.
- **A missed exit is a blockage-then-teleport-onto-the-ramp, not a missed ramp** — and it
  poisons upstream flow, not just the diverge.
- **`tripinfo`-based failure rates go NaN, not 1.0, when the failure gridlocks the network.**
- **LC2013 + `--lateral-resolution` is a hard error**, and SL2015 without
  `--lateral-resolution` is degenerate (zero `speedGain` events).
- **`lcKeepRight`'s influence collapses 14x between 400 and 1600 veh/h/ln** — screen it at
  the demand you care about.
- **LC2013's strategic pull is route-global**; a longer approach adds strategic events
  rather than revealing an onset, so the spatial profile is boundary-dependent.
- **The search objective is an optimistic order statistic** (+46 % worse on unseen seeds
  here) — always re-score on independent seeds.

## Related

- `calibrate-car-following-parameters-against-field-targets` — the Morris sampler
  (`scripts/morris.py::trajectory`), CRN evaluation-pool design, optimiser-comparison and
  known-answer-recovery discipline reused verbatim here; this skill is its lane-changing
  counterpart and reproduces its equifinality result on a different parameter family.
- `quantify-sumo-run-to-run-variability` / [[sumo-stochastic-variability-and-replication-design]]
  — the seed-noise-floor and required-replication method that every "above the noise"
  claim here rests on.
- `model-freeway-weaving-segment` — the `--lanechange-output` spatial-binning technique;
  this skill's facility is deliberately the *non*-weaving counterpart (no on-ramp, no
  shared auxiliary lane).
- `compare-zipper-vs-default-merge-at-lane-drop` — the merge-side analogue of a mandatory
  lane change at a lane discontinuity.
- `simulate-motorcycle-lane-filtering-with-sublane-model` / [[sublane-model-and-lane-filtering]]
  — the sublane configuration whose LC2013 incompatibility is documented here.
- `analyze-simulation-outputs` / [[sumo-output-files]] — meandata/E1/tripinfo parsing
  conventions, including the per-run additional-file rule this skill's parallel pool follows.
- [[geh-statistic]] — the per-lane GEH < 5 acceptance criterion.
- [[lane-change-model-calibration-and-identifiability-at-a-diverge]] — the verified
  screening, calibration, identifiability, trap and transferability findings.
