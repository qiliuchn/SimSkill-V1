---
name: evaluate-two-lane-highway-with-hcm-and-passing-lanes
description: Use this skill when the user wants to build a rural two-lane two-way highway in SUMO and evaluate it with the HCM 7th Ed. Chapter 15 two-lane-highway methodology - percent followers, follower density (followers/mi/ln), average travel speed, platoon-length distribution and the follower-density LOS letter - and/or wants to measure how far downstream a passing lane's benefit persists (downstream length of effectiveness). Covers authoring HCM "Passing Constrained" vs "Passing Zone" segments by controlling which lanes carry a reciprocal <neigh> marker (and the verified trap that --opposites.guess overrides selective plain-XML authoring), measuring percent followers from virtual cross-section headways rather than proxies, the overtaking-vehicle-abreast headway artifact, adding a passing lane with tapers and a lane drop, and fitting the downstream follower-density recovery. Trigger on mentions of two-lane highway, rural highway LOS, percent followers, follower density, passing lane, no-passing zone, passing constrained, HCM Chapter 15, or downstream length of effectiveness.
related_skills:
  - model-opposite-direction-overtaking
  - generate-hcm-los-report-and-validate-against-microsimulation
  - measure-heavy-vehicle-passenger-car-equivalent
  - quantify-sumo-run-to-run-variability
  - visualize-trajectories-and-timeseries
  - validate-congested-scenario-results-against-teleport-artifacts
  - compare-zipper-vs-default-merge-at-lane-drop
related_skills_for_graph_view:
  - "[[model-opposite-direction-overtaking]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
related_pages:
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[opposite-direction-overtaking-mechanics]]"
---

# Evaluate a Two-Lane Highway with HCM Ch. 15 and Passing Lanes

Builds a rural two-lane, two-way highway in SUMO, segments it into HCM 7th Ed.
Chapter 15 segment types, measures the HCM service measures from raw output, and
measures a passing lane's downstream length of effectiveness. This is the
corridor-scale counterpart to `model-opposite-direction-overtaking` (which
established the oncoming-lane mechanism on a 2 km testbed) and the two-lane-highway
counterpart to `generate-hcm-los-report-and-validate-against-microsimulation`
(signalized LOS).

## Authoring no-passing zones: guess-then-strip, never selective authoring alone

Plain edge files *do* accept `<neigh lane="..."/>` (`$SUMO_HOME/data/xsd/edges_file.xsd`,
under both `<edge>` and `<lane>`), and selective authoring works **on its own**.

**But `netconvert --opposites.guess true` OVERRIDES it** — verified on a 3-node
test net: authoring `<neigh>` on one edge pair only and *also* passing the flag
re-guesses every reversed pair, silently discarding the selective marking. There
is no per-edge suppression option.

**And the guess additionally writes `<neigh>` on the 0.10 m internal junction
lanes** (`:B_0_0` ↔ `:B_1_0`), which plain XML cannot author at all.

So: **compile with `--opposites.guess true`, then strip `<neigh>` from the
no-passing edges' lanes and from the internal lanes of the junctions inside those
ranges**, then verify lane by lane in the compiled net that

- every intended passing lane has a **reciprocal** `<neigh>` (A→B and B→A), and
- every no-passing lane has none.

Verify **behaviourally** too, not just structurally: count completed oncoming-lane
overtakes per segment and confirm the Passing Constrained segments are exactly
zero. Verified on a 16 km corridor, split-0.50 arm (2 no-passing segments × 9
volume levels × 2 directions = 36 rows): 0 excursions in every no-passing row,
against a nonzero rate in 53 of the 54 passing-zone rows (3 segments × 9 volumes
× 2 directions; up to 92.5 completed overtakes per 1000 veh-km). A broader check
across every arm/split/seed (392 rows) confirms 0 completed overtakes in every
no-passing row project-wide.

Corridor recipe: ~1 km edges per direction on shared node pairs reversed, plus
**long fringe feeders** (2 km each end) so the analysed segments never see
insertion loss.

## Measure percent followers from virtual cross-sections, per lane

Do not compute headways from a per-step spacing scan and do not use any proxy.
Record, per vehicle, the **interpolated time it crosses each of a series of virtual
cross-sections** (250 m spacing works well) plus the **lane class** it was on at
that instant. Everything else follows from those records:

- percent followers = share of headways ≤ threshold, **within a physical lane**
- flow = crossings / window
- space-mean speed = section length / mean section traversal time
- follower density = `PF/100 × flow/(nlanes × speed)`
- platoon-length distribution = maximal runs of headways ≤ threshold

This is far cheaper than FCD for a sweep (a TraCI subscription loop with no
per-step file writes), and it is exactly the HCM field measurement.

**Threshold: 2.5 s** (HCM 7th Ed. / NCHRP 17-65 reduced it from the 6th Ed.'s
3.0 s). Report 3.0 s alongside as a sensitivity.

**Cross-check the two routes to follower density.** The spatial mean of
per-station densities and the HCM identity `FD = PF × k` should agree; verified
agreement to a mean 0.06% and max 0.68%. A disagreement means a units or
lane-count bug.

## The overtaking-abreast headway artifact — filter it or over-count followers

**A vehicle passing in the oncoming lane crosses a cross-section abreast of the
vehicle it is passing, producing a near-zero headway that scores as a follower.**
Verified: minimum observed headway was 0.05 s at 100 km/h before filtering —
physically impossible for genuine car-following. Record the lane class at each
crossing and **exclude crossings made from an opposing lane**, then recompute
headways on the filtered per-lane sequence. Verified magnitude: percent followers
falls by a mean of 0.58 pp and up to 3.47 pp. Keep the unfiltered value in the
output so the artifact size stays auditable.

## Truck speed differential must be authored, not terrain

SUMO grade does not affect longitudinal dynamics (see
`measure-heavy-vehicle-passenger-car-equivalent`). Author the car/truck desired-speed
differential explicitly via `speedFactor` (a `normc(...)` distribution centred
below 1.0 for trucks) with `maxSpeed` as a secondary limiter, and `lcOpposite="0"`
on trucks. **Verify the realised differential from `tripinfo` (routeLength/duration),
not from the parameters** — verified 96.9 km/h cars vs 78.3 km/h trucks on a
100 km/h road.

Use `period="exp(rate)"` for Poisson arrivals; `vehsPerHour` is deterministic.

## Passing lane: geometry-matched control, and read the profile carefully

Build **three** networks: base; a **geometry-matched control** carrying the same
extra node splits (and the same no-passing marking over the treated extent) but no
added lane; and the treatment. Comparing the treatment against the *base* network
instead confounds the added lane with the junction splits.

- netconvert trims edges at a widening junction (verified 300 → 296.0 m,
  200 → 196.0 m, etc.) — read the compiled extent, don't quote the authored one.
- With right-spread geometry the added lane is index ≥ 1 (leftmost, adjacent to the
  centreline) and the through lane shifts laterally; that is correct.
- netconvert produces the lane drop by connecting only lane 0 onward — verify that
  the added lane has no continuation.
- **Inside the 2-lane section per-lane follower density falls partly by definition**
  (flow ÷ 2 lanes). Only the single-lane downstream stations are a clean comparison.

## Downstream effective length: fit the deficit, and admit the extrapolation

Fit `D(x) = D0·exp(-(x - x0)/L)` to the control-minus-treatment follower-density
deficit over the stations downstream of the lane drop, and report effective length
as the distance at which the deficit has decayed by 90% (`L·ln10`). Report the fit
R² and **discard any level whose fit is not clean** (verified: R² 0.25–0.65 at low
volume where the deficit sits in seed noise, versus 0.86–0.98 above ~600 veh/h
two-way).

**State the observation window.** A passing lane mid-corridor on a 16 km road
leaves only ~6.6 km of observable downstream, while HCM's tabulated effectiveness
runs 3.6–13 mi — so nearly every fitted length is an extrapolation. Report
alongside it a **purely observational** statistic: the fraction of the
just-downstream deficit still present at the last station. Verified: that fraction
falls 38.9% → 14.5% as directional flow rises 300 → 1200 veh/h, giving the same
conclusion with no extrapolation at all. Also test per-station whether the deficit
is still significant across seeds — verified significant at *every* downstream
station out to the corridor end at all tested volumes, which is itself the honest
statement that the corridor is too short.

Design a corridor with 25–30 km downstream of the treatment if the effective length
itself, rather than its trend, is the deliverable.

## Verified findings

- **Effective length shrinks with flow**, matching HCM's trend: Spearman ρ = −0.893
  (p = 0.0068) between directional flow and fitted L_eff at a 50/50 split, and
  ρ = −0.929 (p = 0.0025) for the non-extrapolated fraction-remaining statistic.
  4.5 mi at 1200 veh/h directional vs HCM's 3.6 mi (> 700 pc/h); 9.3 mi at
  400 veh/h vs HCM's 8.1 mi (> 200–400 pc/h). At a 70/30 split the trend did **not**
  reproduce (3 clean fits, reversed sign) — report inconclusive, don't force it.
- **A passing lane is not a one-directional treatment.** It raised the *opposing*
  direction's follower density by 0.24–0.62 followers/mi/ln (significant on 5
  paired seeds), because breaking up the treated direction's platoons removes the
  long inter-platoon gaps the opposing direction was using to overtake — its
  oncoming-lane overtake rate fell by a mean 33.9% (11 of 12 comparisons).
- **SUMO produces 1.44–4.26× the percent followers a random-arrivals model
  predicts** (excess up to +54 pp), and the excess **grows with cumulative
  distance travelled since origin, not with fixed spatial segment label** —
  verify this by re-indexing both directions of travel by their own order of
  segment encounter (they traverse the same segments in opposite order); read
  naively by segment label in one direction alone, the trend looks monotone but
  the opposing direction appears to contradict it, and both reconcile once
  distance-travelled replaces position as the x-axis. Platoon accumulation is a
  function of following time, which a memoryless local-flow model structurally
  cannot represent regardless of which segment a vehicle currently occupies.
- **Directional capacity 1584 veh/h ≈ 1663 pc/h at 10% HGV, i.e. 97.8% of HCM's
  1700 pc/h/direction reference** (two-way 3160 veh/h ≈ 3318 pc/h vs 3200).
  The closest agreement with an HCM capacity reference in this memory.
- **The conservative overtaking parameterization is low-collision, not
  collision-free.** 6 genuine frontal collisions in 3.29 M veh-km (1.82 per million
  veh-km) with `lcOpposite=1.0, lcAssertive=1.0, lcPushy=0.0, lcImpatience=0.0` —
  see the gotcha below.

## Gotchas

- **`--opposites.guess true` silently overrides selectively authored `<neigh>`.**
  Strip after compiling; never rely on authoring alone if the flag is also passed.
- **Internal junction lanes carry `<neigh>` under the guess and cannot be authored
  in plain XML** — a further reason to strip rather than to author.
- **Overtaking vehicles crossing a cross-section abreast fake a near-zero headway.**
  Record the lane class and filter, or percent followers is inflated by up to 3.5 pp.
- **`model-opposite-direction-overtaking`'s "zero collisions" is an exposure result,
  not a property of the parameters.** It was verified at ~130 vehicles on 2 km;
  scaled to 16 km and 1000–3000 vehicles per run the same tuning produces genuine
  `<collision type="frontal">` events. **Report collisions per vehicle-km**, keep
  `--collision-output` on, and never claim collision-freeness from a small scenario.
- **Westbound gradients must be sign-flipped** when regressing a metric against x —
  a metric per km *travelled* is the negative of the metric per km of x for the
  decreasing-x direction. Averaging the two directions without the flip cancels a
  real effect to exactly nothing (this bug produced a null result before it was
  caught).
- **Capacity is the peak of the served-flow-vs-demand curve**, not the flow at the
  heaviest demand; and check `never_inserted` before interpreting any high-demand
  row (verified 0 up to 3200 veh/h two-way, 347 and 639 at 3600/4000 with a 70/30
  split).
- **HCM 7th Ed. Exhibit 15-6's numeric LOS thresholds are not reproduced in any
  openly accessible source** — nine were checked. State the table you use, and
  report how many letters change under the alternative posted-speed column
  (verified 29.4% of rows), because that is a bigger grading risk than the
  2.5 s vs 3.0 s follower threshold (1.1% of rows).

## Related

- `model-opposite-direction-overtaking` — the oncoming-lane mechanism, `lcOpposite`
  and the safe lane-change tuning this skill's corridor is built on; this skill
  corrects its zero-collision claim to a per-vehicle-km rate.
- `generate-hcm-los-report-and-validate-against-microsimulation` — the
  measure-don't-assume LOS discipline and the `period="exp(...)"` arrival-process
  requirement reused here.
- `measure-heavy-vehicle-passenger-car-equivalent` — why the truck speed
  differential must be authored via `speedFactor`/`maxSpeed` rather than terrain,
  and the E_T = 1.5 used for the pc/h conversion.
- `quantify-sumo-run-to-run-variability` — the CRN paired-seed design and the
  "capacity is the peak of the curve" rule applied here.
- `visualize-trajectories-and-timeseries` — the time-space diagram used to show
  platoon formation and dissipation across the passing lane.
- `validate-congested-scenario-results-against-teleport-artifacts` — the
  teleport / never-inserted validity screen applied to every run.
- `compare-zipper-vs-default-merge-at-lane-drop` — the lane-drop connection
  conventions the passing lane's exit taper reuses.
- [[two-lane-highway-follower-density-and-passing-lane-effectiveness]] — the
  verified HCM-vs-SUMO divergence, the effective-length trend, the
  cross-directional passing-lane penalty and the measurement artifacts.
- [[opposite-direction-overtaking-mechanics]] — the underlying `<neigh>` /
  `lcOpposite` mechanics.
