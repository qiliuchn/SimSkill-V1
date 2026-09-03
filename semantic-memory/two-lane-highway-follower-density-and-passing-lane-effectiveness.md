---
summary: SUMO's rural two-lane highway reproduces HCM 7th Ed. Ch. 15 capacity almost exactly (1663 pc/h/direction, 97.8% of the 1700 pc/h reference) but produces 1.44-4.26x the percent followers a memoryless local-flow model predicts, because platoons accumulate with cumulative distance travelled since origin rather than with fixed spatial position (verified across both directions of travel, which encounter the same segments in opposite order) - a trip-history dependence segment-level HCM prediction structurally cannot carry; a passing lane's downstream benefit decays exponentially with an effective length that shrinks with flow (matching HCM's trend) while imposing a small but replicated penalty on the OPPOSING direction by removing the inter-platoon gaps it was using to overtake; and two measurement traps (netconvert's --opposites.guess overriding selective plain-XML <neigh>, and overtaking vehicles faking near-zero headways at a cross-section) will silently corrupt the segmentation and the follower count if not checked.
keywords:
  - two-lane-highway
  - follower-density
  - percent-followers
  - passing-lane
  - HCM-chapter-15
  - passing-constrained
  - length-of-effectiveness
created: 2026-08-05T07:00:00
last_updated: 2026-08-07T03:22:15
sources:
  - "[[episodic-memory/2026-08-05_07-00-00/outputs/FINDINGS.md]]"
  - https://www.nationalacademies.org/read/27897/chapter/5
  - https://epg.modot.org/index.php/232.2_Passing_Lanes
related_pages:
  - "[[opposite-direction-overtaking-mechanics]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[zipper-merge-lane-drop-discharge]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[grade-aware-heavy-vehicle-physics-and-climbing-lane-warrants]]"
  - "[[horizontal-curvature-and-curve-speed-in-sumo]]"
related_skills:
  - evaluate-two-lane-highway-with-hcm-and-passing-lanes
  - model-opposite-direction-overtaking
  - generate-hcm-los-report-and-validate-against-microsimulation
  - measure-heavy-vehicle-passenger-car-equivalent
  - quantify-sumo-run-to-run-variability
  - visualize-trajectories-and-timeseries
  - model-horizontal-curvature-and-evaluate-design-consistency
  - model-grade-aware-heavy-vehicle-performance-and-climbing-lanes
related_skills_for_graph_view:
  - "[[evaluate-two-lane-highway-with-hcm-and-passing-lanes]]"
  - "[[model-opposite-direction-overtaking]]"
  - "[[generate-hcm-los-report-and-validate-against-microsimulation]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[model-horizontal-curvature-and-evaluate-design-consistency]]"
  - "[[model-grade-aware-heavy-vehicle-performance-and-climbing-lanes]]"
---

# Two-Lane Highway Follower Density and Passing-Lane Effectiveness in SUMO

HCM 7th Ed. Chapter 15 replaced the old Class I/II/III two-lane-highway
classification and Percent Time Spent Following with a single service measure,
**follower density** (followers per mile per lane), where a *follower* is a vehicle
at a headway of **2.5 s or less** (reduced from the 6th Ed.'s 3.0 s by NCHRP
17-65). This page records the first attempt in this memory to build a rural
two-lane two-way corridor in SUMO, measure those service measures from raw output,
and test a passing lane's downstream length of effectiveness — on a 16 km corridor,
128 runs, 3.29 million vehicle-km. See
`evaluate-two-lane-highway-with-hcm-and-passing-lanes` for the full workflow.

## Verified: SUMO reproduces HCM's two-lane capacity almost exactly

Sweeping demand to 4000 veh/h two-way and taking capacity as the **peak** of the
served-flow-vs-demand curve (not the flow at the heaviest demand — see
[[sumo-stochastic-variability-and-replication-design]]), the corridor delivered a
directional capacity of **1584 veh/h** and a two-way capacity of **3160 veh/h** with
a 10% heavy-vehicle fleet. Converted with `f_HV = 1/(1 + P_T(E_T − 1))` at
E_T = 1.5 (the level-terrain reference, which is also SUMO's own freeway-measured
value per [[heavy-vehicle-passenger-car-equivalent-in-sumo]]), that is
**1663 pc/h/direction — 97.8% of HCM's 1700 pc/h/direction reference** — and
3318 pc/h two-way against the 3200 pc/h reference. At a 70/30 split the loaded
direction pinned at 1525–1551 veh/h from 2800 veh/h demand onward, an unambiguous
plateau rather than a collapse.

**This is by a wide margin the closest agreement with an HCM capacity reference
recorded in this memory** — compare the signalized case, where SUMO's protected
left came out ~30% below HCM's default saturation flow
([[hcm-control-delay-vs-sumo-delay-metrics]]). Uninterrupted two-way flow appears
to be a regime SUMO's default Krauss fleet gets right almost for free, while
interrupted flow at a stop line is not.

## Verified: SUMO produces far more followers than a local-flow model predicts, and the excess grows with distance already travelled

Against a fully derivable random-arrivals benchmark (`PF = 100(1 − e^(−q·t_c))`),
SUMO's measured percent followers ran **1.44× to 4.26× higher, an excess of up to
+53.9 percentage points (mean +30.2 pp)**; against a shifted-exponential model
using the measured 1.38 s minimum headway the excess was larger still.

**The mechanism is identifiable and structural, not a calibration offset — but it
tracks cumulative distance travelled since origin, not absolute position on the
corridor.** Read naively by spatial segment label in one direction only, the
eastbound excess ratio looks like it rises from segment 1 to segment 5 (2.13 at
S1 to a peak of 4.26 at S4, dipping slightly to 3.86 at S5, at 200 veh/h
two-way) — but the opposing (westbound) direction shows the ratio *falling*
across the same segment labels (2.40 at S1 down to 0.83 at S5, same volume),
which looks like a contradiction until the two directions are re-indexed by
**order of encounter along each direction's own travel path** rather than by
fixed spatial label. Eastbound vehicles encounter the segments S1→S2→S3→S4→S5 in
order of increasing distance travelled; westbound vehicles physically traverse the
corridor the other way, so *their* first-encountered segment is S5 and their
last-encountered is S1. Re-plotted against distance actually travelled rather
than segment label, the two directions collapse onto the same curve — at higher
volumes (1200, 2400 veh/h two-way) the direction-reindexed series are nearly
numerically identical position-by-position. **The excess grows with how far a
vehicle has already travelled since insertion, because platoons accumulate behind
slow trucks as a function of following time, not of which physical segment the
vehicle currently occupies**, and it *falls* with volume because the analytical
model itself saturates. A memoryless model that knows only the local flow rate
cannot represent that upstream trip history. **Any segment-level analytical
percent-followers prediction will therefore under-predict a long corridor, by an
amount that depends on how far into the trip a vehicle already is when it reaches
the segment being graded — not on the segment's fixed position on the map.** A
SUMO-vs-HCM comparison for a two-lane highway should be reported per segment
*and* per direction, checked for this distance-travelled effect, never as a
single corridor-average bias or from one direction alone.

(The full HCM 7th Ed. Ch. 15 percent-followers regression was deliberately *not*
reproduced: its coefficient exhibits could not be verified against any source
reachable from this environment, and inventing them would be fabrication. The same
applies to Exhibit 15-6's LOS thresholds — nine sources were checked and every one
references the exhibit without reproducing it. **State the threshold table used and
bound the risk**: grading the same data with the < 50 mi/h posted-speed column
changed the letter in 29.4% of rows, whereas the 2.5 s vs 3.0 s follower threshold
changed it in only 1.1% — the speed column is the first-order grading risk, not the
headway threshold.)

## Verified: the passing-lane effective length shrinks with flow, as HCM says

Fitting `D(x) = D0·exp(−(x − x0)/L)` to the control-minus-treatment follower-density
deficit downstream of a 1.5 km passing lane, effective length (90% decay) fell from
10.0 mi at 300 veh/h directional to **4.5 mi at 1200 veh/h** — Spearman ρ = −0.893
(p = 0.0068) against directional flow at a 50/50 split. This matches both the sign
and roughly the magnitude of HCM's tabulated downstream length of effectiveness
(13.0 / 8.1 / 5.6 / 3.6 mi for ≤ 200 / > 200–400 / > 400–700 / > 700 pc/h
directional). At a 70/30 directional split the trend did **not** reproduce (only 3
clean fits, reversed sign) — reported as inconclusive rather than forced.

**The honest limitation dominates the result.** A mid-corridor passing lane on a
16 km road leaves only ~6.6 km of observable downstream, so nearly every fitted
length is an **extrapolation beyond the observation window**, and a 5-seed paired
test found the deficit still statistically significant at *every* downstream station
out to the corridor end at every tested volume. The trend survives because a purely
observational statistic — the fraction of the just-downstream deficit still present
at the last station — reproduces it without any extrapolation (38.9% → 14.5% as
directional flow rises 300 → 1200 veh/h, ρ = −0.929, p = 0.0025). **Design a
corridor with 25–30 km downstream of the treatment if the effective length itself,
rather than its trend, is the deliverable.**

## Verified, counter-intuitive: a passing lane penalises the OPPOSING direction

The westbound placebo comparison (the added lane was eastbound-only) was **not**
null: westbound follower density rose by 0.24–0.62 followers/mi/ln with the passing
lane, significant on 5 paired seeds at every tested volume. The mechanism was then
confirmed directly — **the passing lane cut the westbound stream's own
oncoming-lane overtake rate by a mean 33.9%** (negative in 11 of 12 segment ×
volume comparisons, up to −51%). Breaking up the eastbound platoons makes the
eastbound stream more evenly spaced, which destroys the long inter-platoon gaps
westbound drivers were using to overtake into the eastbound lane.

**A passing lane on an undivided two-way road is a coupled, two-directional
intervention, not a one-directional one.** The penalty is an order of magnitude
smaller than the benefit and would not have been credible from a single run — it
only became defensible under Common Random Numbers with 5 paired seeds, exactly the
regime [[sumo-stochastic-variability-and-replication-design]] recommends.

## Verified: the no-passing marking must be verified structurally AND behaviourally

`netconvert --opposites.guess true` **overrides selectively authored plain-XML
`<neigh>`** — authoring the marker on one edge pair only and also passing the flag
re-guesses every reversed pair and discards the authoring silently. There is no
per-edge suppression option. The guess additionally writes `<neigh>` onto the
0.10 m internal junction lanes, which plain XML cannot author at all. The working
method is **guess-then-strip**: compile with the flag, delete `<neigh>` from the
no-passing edges and their interior junction internal lanes, then verify every
corridor lane has (or lacks) a *reciprocal* marker as intended.

Structural verification is necessary but not sufficient — confirm the marking binds
by counting completed oncoming-lane overtakes per segment. Verified, on the
split-0.50 arm (2 Passing-Constrained segments × 9 volumes × 2 directions = 36
rows): **0 excursions in every Passing-Constrained row**, against a nonzero rate
in 53 of the 54 Passing-Zone rows (3 segments × 9 volumes × 2 directions; up to
92.5 completed overtakes per 1000 veh-km). A broader check across every arm,
split and seed (392 rows total) confirms 0 completed overtakes in every
Passing-Constrained row project-wide — an even stronger version of the same
result. The overtake rate itself is **non-monotone in volume**, peaking near
400–800 veh/h two-way and collapsing at high volume — the demand-for-passing
versus supply-of-gaps tradeoff.

## Verified measurement artifact: overtaking vehicles fake near-zero headways

A vehicle passing in the oncoming lane crosses a virtual cross-section **abreast**
of the vehicle it is passing, producing a headway a naive all-vehicles sequence
scores as a follower. The observed minimum headway before filtering was **0.05 s**
at 100 km/h — physically impossible for genuine car-following. Recording the lane
class at each crossing and excluding opposing-lane crossings lowered percent
followers by a mean of 0.58 pp and **up to 3.47 pp**. Any headway-based
follower/platoon statistic on a road where opposite-direction overtaking is enabled
must filter these, and should keep the unfiltered value so the artifact size stays
auditable.

## Verified correction: the "collision-free" overtaking tuning is only low-collision

[[opposite-direction-overtaking-mechanics]] records zero SUMO-detected collisions
for the conservative parameterization `lcOpposite=1.0, lcAssertive=1.0,
lcPushy=0.0, lcImpatience=0.0`. That result was obtained on a 2 km corridor with
~130 vehicles per run. **Scaled to a 16 km corridor with 1000–3000 vehicles per
run, the same tuning produced 6 genuine `<collision type="frontal">` events across
128 runs — 1.82 collisions per million vehicle-km**, all of them on an
opposing-direction lane, i.e. failed oncoming-lane passes. The parameterization is
not "safe"; it was **under-exposed**. Zero collisions in a small scenario is an
exposure result, not a property of the parameters — **report collisions per
vehicle-km, keep `--collision-output` active, and never generalise
collision-freeness from a scenario an order of magnitude smaller than the one being
claimed for.**

## Practical takeaways

- Verify a network feature both structurally (in the compiled `.net.xml`) and
  behaviourally (in the output) — a flag can override authored XML silently.
- Measure percent followers from virtual cross-section headways *per physical
  lane*, filtering vehicles that were mid-overtake; it is both the HCM field
  definition and far cheaper than FCD for a sweep.
- Cross-check follower density two ways (spatial mean of station values vs the
  identity `FD = PF × k`); verified agreement to 0.06% mean / 0.68% max.
- Compare a treatment against a **geometry-matched** control that carries the same
  node splits, not against the original network.
- State the observation window before quoting any fitted decay length, and pair it
  with a statistic that needs no extrapolation.
- Treat an unexpected "placebo" signal as a mechanism to test, not noise to
  dismiss — the opposing-direction penalty here was real and explainable.
- Expect a zero-count safety result to be an exposure artifact until it has been
  re-tested at the scale it is being claimed for.
