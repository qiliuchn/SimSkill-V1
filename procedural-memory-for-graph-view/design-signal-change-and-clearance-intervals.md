---
name: design-signal-change-and-clearance-intervals
description: Use this skill when the user wants to design or analyze signal CHANGE AND CLEARANCE INTERVALS (yellow and all-red timing) in SUMO as a first-class safety-and-capacity design object, rather than accepting a hardcoded default — testing for the classical dilemma zone, the safety-capacity tradeoff of interval length, whether measured lost time matches the assumed intergreen, and how heavy vehicles/grade/intersection geometry shift the required interval. Covers an ITE/kinematic analytic reference calculator (required yellow and all-red formulas, stopping-distance vs clearing-distance dilemma-zone boundaries), a per-vehicle yellow-onset decision log reconstructing the empirical stop/go probability curve from FCD/TraCI, modeling driver non-compliance via SUMO's junction-model parameters, and the finding that a dilemma zone does not emerge from SUMO's default driving model and must be deliberately injected to study it. Trigger on mentions of yellow interval, all-red clearance, dilemma zone, red-light running, change interval, ITE yellow formula, or ClearanceTime.
related_skills:
  - create-single-intersection
  - control-signals-with-actuated-tls
  - measure-saturation-flow-and-validate-webster-method
  - analyze-intersection-safety-with-ssm
  - measure-heavy-vehicle-passenger-car-equivalent
  - model-road-gradient-effects-on-energy
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
---

# Design Signal Change and Clearance Intervals

Treats the yellow and all-red interval — normally a hardcoded 3-second constant in
every other signal-control skill in this project's memory — as a genuine design
object with a measurable safety-capacity tradeoff, and tests whether SUMO's own
vehicle dynamics reproduce the classical traffic-engineering "dilemma zone"
phenomenon.

## Building the network with explicit intervals

Author yellow (`y` states) and all-red phases explicitly in the `tlLogic` state
strings (see `control-signals-with-actuated-tls` for the hand-authoring mechanics),
with approach speed, approach grade, and heavy-vehicle share all parameterized so
they can be swept independently. **Verify from the compiled net and the actual
loaded program** — not just the input file — that the intended intervals, phase
order, and per-link `y`/`r` assignments took effect, the same discipline
`build-diamond-interchange-with-signal-offset-spillback` establishes for offsets.

## The analytic reference: ITE formulas and the dilemma-zone calculator

Implement the standard ITE/kinematic reference independently, as a cross-check
target rather than something to assume matches simulation behavior:

- **Required yellow**: `y = t_pr + v / (2a + 2*g*G)` (perception-reaction time plus
  braking time, adjusted for grade `G` via gravitational acceleration component).
- **Required all-red**: `r = (W + L) / v` (intersection width plus vehicle length,
  divided by speed).
- **Dilemma-zone boundaries**: the stopping-distance boundary `x_s` (the distance
  from the stop line beyond which a vehicle traveling at design speed cannot stop
  before the line using comfortable/design deceleration) and the clearing-distance
  boundary `x_c` (the distance within which a vehicle can clear the conflict zone
  before the signal turns red, given the design yellow). **A true dilemma zone
  exists only where `x_c > x_s`** — there is a range of positions from which a
  vehicle can neither stop safely nor clear in time. Where `x_c <= x_s`, the zone
  is merely an "option" zone (a vehicle has a legal choice either way), a
  materially different and less safety-critical condition. Compute and report both
  boundaries and explicitly classify which regime a given yellow/speed combination
  falls into — don't assume "yellow interval creates a dilemma zone" without
  checking whether the arithmetic actually produces `x_c > x_s`.

## Measuring SUMO's own stop/go boundary, and comparing it to the analytic reference

Build a **per-vehicle yellow-onset decision log** from FCD/TraCI: at each signal's
yellow onset, record every approaching vehicle's distance-to-stop-line, speed, and
deceleration used, classified into an outcome (stopped cleanly, stopped abruptly
above a hard-braking threshold, cleared on yellow, or entered on red — red-light
running). **A cleaner, more precise alternative to sweeping traffic demand is a
single-vehicle bisection probe**: place one vehicle at a controlled distance from
the stop line at yellow onset and bisect on distance to find SUMO's own exact
stop/go decision boundary, repeated across speeds — this produces a much cleaner
signal than trying to infer the boundary from noisy traffic-demand outcomes.

**Do not assume SUMO's stop/go boundary matches the ITE formula — measure it and
compare.** Verified case: SUMO's own measured boundary followed a clean closed
form, `min(v²/2a, v*yellow)` (essentially a deceleration-based stopping distance
capped by how far the vehicle can travel during the yellow itself), fitting
measured data to within roughly a meter — but this formula implies **zero
perception-reaction time**, since SUMO's deterministic car-following models react
to a signal-state change essentially instantaneously rather than after a realistic
human reaction delay. This produces a substantially *smaller* effective stopping
boundary than the ITE formula predicts (which includes a perception-reaction term)
— meaning a naive comparison against ITE reference values, without checking this,
will systematically misjudge how conservative SUMO's simulated drivers actually
are.

## Non-compliance must be deliberately injected — check whether it's emergent first

**Test explicitly whether a measurable dilemma zone (nonzero red-light-running
rate) emerges from SUMO's default driving model at all, before assuming it does.**
Verified case: with the driver-behavior parameter controlling how long after a
signal change a vehicle will still proceed (`jmDriveAfterRedTime` or equivalent)
left at its default/absent setting, red-light-running was measured at **exactly
zero** across tens of thousands of decision-log entries — SUMO's deterministic,
compliant-by-default driving model does not spontaneously produce the
non-compliance that creates a real-world dilemma zone's crash risk. **To study the
phenomenon at all, non-compliance must be deliberately modeled** via SUMO's
junction-model parameter family (`jmDriveAfterRedTime`, `jmDriveAfterYellowTime`,
`jmIgnoreFoeProbs`, `jmTimegapMinor`, driver imperfection/impatience). **Verify each
parameter's effect is real with a negative control** (e.g. confirm a parameter set
to a value that should have no effect on the movements being studied genuinely
produces none) before trusting a swept parameter's apparent effect.

## Testing the safety-capacity tradeoff

Sweep yellow (and separately all-red) length and report multiple safety metrics
simultaneously, not just one — **expect the tradeoff to show up as
non-monotonicity BETWEEN metrics, not necessarily as a U-shape within any single
metric.** Verified case: as yellow lengthened, right-angle conflict exposure
(measured via post-encroachment time at the conflict point) genuinely improved
monotonically, while rear-end conflict indicators (hard-braking event rate)
significantly *worsened* — the safety-optimal interval is therefore not simply "as
long as possible," but a genuine tradeoff between two different crash types that
must be weighed against each other, not a single metric with an interior optimum.

**Test all-red length's exchange rate explicitly, and expect a sharp threshold
rather than a smooth benefit curve.** Verified case: the first added second of
all-red produced a statistically significant right-angle-conflict benefit only at
one specific, identifiable geometry (a wide, high-speed crossing) — at every other
tested geometry, and at every subsequent second of all-red beyond the first at any
geometry, the marginal safety benefit was not statistically significant while the
delay cost remained real and significant. **All-red is not a "more is safer"
dial — it has a narrow window of genuine effectiveness tied to specific geometry,
and should be sized to that geometry rather than applied uniformly.**

## Lost time and its Webster-cycle consequences

Measure startup lost time and clearance lost time directly from stop-line discharge
data (see `measure-saturation-flow-and-validate-webster-method`'s methodology), and
compare the **measured** total lost time against the **assumed** intergreen
(yellow + all-red) that a Webster-style cycle-length calculation typically uses as
its lost-time proxy. **Don't assume these are the same quantity.** Verified case: a
real, consistent gap of a fraction of a second existed between measured lost time
and the assumed intergreen for an all-passenger-car fleet, and this gap **changed
sign** (became negative) once a substantial heavy-vehicle share was introduced —
meaning the direction of the Webster-cycle-length error depends on fleet
composition, not just a fixed correction factor. Feed the measured (not assumed)
lost time back into the Webster cycle-length formula and report the resulting shift
in optimal cycle length and the associated delay cost — a modest-looking lost-time
discrepancy can shift the optimal cycle length by a double-digit percentage even
while costing only a small delay penalty if the shift is in the direction of a
shorter cycle.

## Heavy vehicles and grade: check both, expect asymmetric results

Test truck share and approach grade as separate factors shifting the required
interval and the dilemma-zone boundary — **do not assume they behave symmetrically
or that SUMO models both equally well.** Verified case: heavy-vehicle share
produced a large, statistically robust effect on measured stopping/time-loss
behavior, closely matching physical expectation. **Grade, despite the analytic
(ITE) formula predicting a substantial shift in the required stopping distance,
produced almost no change in SUMO's own measured stop/go boundary** — a genuine gap
between real physics and SUMO's braking/junction model, not a modeling choice that
happens to look different. **This kind of divergence should be reported explicitly
as a SUMO modeling limitation, not folded into the headline finding as if it were
additional confirmation of the analytic theory** — a study of grade effects on
signal timing using SUMO's default longitudinal dynamics should not expect the
simulated stopping-distance sensitivity to match real-world truck-on-a-downgrade
physics.

## Capacity-optimal vs. safety-optimal intervals: locate both, quantify the gap

Sweep the interval jointly with both a capacity/delay objective and a safety
objective, and locate the optimum under each separately — expect them to differ in
the large majority of tested configurations, with the safety-optimal choice costing
a real, and sometimes substantial, delay penalty relative to the capacity-optimal
choice. Report the gap in both seconds of interval and in delay/conflict units, and
present this as a genuine, unavoidable design tradeoff rather than implying a
single "correct" interval exists independent of which objective is prioritized.

## Statistical discipline: paired comparisons for CRN-replicated sweeps

**When comparing two configurations under Common Random Numbers, use a paired test
on the seed-matched differences, not an unpaired comparison of each configuration's
own confidence interval.** An unpaired per-configuration CI comparison can produce
a materially different, more favorable-looking conclusion than the methodologically
correct paired test on the same data — verified case: an unpaired comparison
suggested one detector-placement design significantly beat a conventional
alternative, while the correct CRN-paired test on the identical underlying runs
found no significant difference between those same two configurations, with the
one genuinely significant effect the paired test did find lying on a metric that
was separately flagged as a likely SUMO artifact rather than a real safety signal.
**Always use the paired test when seeds are shared across compared arms — this is
not a minor technicality, it can reverse a headline conclusion.**

## Gotchas

- **SUMO's default driving model does not spontaneously produce a nonzero
  red-light-running rate** — a dilemma zone's crash risk must be deliberately
  modeled via junction-model non-compliance parameters, not assumed to emerge from
  default settings.
- **SUMO's measured stop/go boundary implies zero perception-reaction time** — its
  effective stopping distance is systematically smaller than the ITE formula's
  prediction, which includes a real perception-reaction term.
- **All-red's safety benefit is not a smooth "more is better" curve** — it has a
  narrow effective range tied to specific intersection geometry (width, speed), and
  most of a typical sweep range buys no significant safety benefit while still
  costing delay.
- **Measured lost time can diverge from the assumed intergreen in a direction that
  depends on fleet composition** — a heavy-vehicle-share change can flip the sign
  of the lost-time discrepancy, not just its magnitude.
- **SUMO's braking/junction model can fail to reproduce a real physical effect
  (like grade's effect on stopping distance) even when the analytic theory
  predicts a large effect** — check for and honestly report this kind of gap
  rather than assuming simulation results validate the underlying physics.
- **A CRN-replicated comparison must use a paired test on seed-matched
  differences** — an unpaired per-arm comparison of confidence intervals can
  produce a reversed or overstated conclusion relative to the correct paired test.
- **When cross-checking a scripted analysis pipeline's completeness, verify
  silently-failing steps didn't leave an entire hypothesis's output missing** — a
  script that raises an uncaught exception partway through a multi-stage pipeline
  can leave a downstream file simply absent rather than obviously broken.

## Related

- `create-single-intersection` — the base parameterized-junction network-building
  technique this skill's swept-approach-speed/grade/truck-share network extends.
- `control-signals-with-actuated-tls` — the hand-authored `tlLogic` state-string
  technique this skill's explicit yellow/all-red phase authoring builds on.
- `measure-saturation-flow-and-validate-webster-method` — the stop-line discharge
  measurement methodology this skill's lost-time measurement directly reuses, and
  the Webster cycle-length formula this skill's lost-time-feedback analysis
  extends.
- `analyze-intersection-safety-with-ssm` — the SSM device (TTC/PET/DRAC) setup this
  skill's right-angle/rear-end conflict metrics are built on.
- `measure-heavy-vehicle-passenger-car-equivalent` — the heavy-vehicle-fleet
  construction and measured-impact methodology this skill's truck-share sweep
  reuses.
- `model-road-gradient-effects-on-energy` — the verified z-coordinate grade-authoring
  technique this skill's grade sweep is built from.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — the
  custom-detector-binding and negative-control-verification technique this skill's
  dilemma-zone detector-placement cross-check reuses.
- `quantify-sumo-run-to-run-variability` — the CRN replication discipline this
  skill's paired-vs-unpaired comparison finding specifically extends and
  reinforces.
- [[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]] — the
  verified stop/go boundary formula, the dilemma-zone-is-not-emergent finding, the
  lost-time/Webster divergence, all-red's narrow effective-benefit geometry, the
  heavy-vehicle/grade asymmetry, the capacity-vs-safety-optimal divergence, and the
  corrected detector-placement finding this skill's methodology produced.
