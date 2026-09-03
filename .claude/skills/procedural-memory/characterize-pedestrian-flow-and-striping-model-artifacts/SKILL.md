---
name: characterize-pedestrian-flow-and-striping-model-artifacts
description: Use this skill when the user wants to treat pedestrians as a first-class flow entity in SUMO — building a pedestrian fundamental diagram, measuring sidewalk/crosswalk capacity, testing counterflow, or evaluating the striping pedestrian model's known artifacts (lateral stripe quantization, jam-resolution push-through) — rather than treating pedestrians only as signal-phasing objects or an abstract mode-choice leg. Covers deriving pedestrian density/speed/flow from FCD person records (SUMO has no induction-loop equivalent for persons), fitting a pedestrian fundamental diagram, the discovery that sidewalk capacity is quantized by the striping model's stripe width (rising in discrete steps, not proportionally, as width increases), the corrected default value of --pedestrian.striping.jamtime and its artifact implications, counterflow/lane-formation testing via a lateral-position segregation index, and comparing the striping/nonInteracting/jupedsim pedestrian models. Trigger on mentions of pedestrian fundamental diagram, sidewalk capacity, striping model, pedestrian LOS, crowd flow, or pedestrian counterflow.
---

# Characterize Pedestrian Flow and Striping Model Artifacts

Treats pedestrians in SUMO as a genuine flow entity — the first project skill to do
so — building a pedestrian fundamental diagram, measuring real sidewalk/crosswalk
capacity, and characterizing specific artifacts of SUMO's default `striping`
pedestrian model that can silently distort any capacity or level-of-service claim
built on top of it. Distinct from `build-pedestrian-crossings-and-phasing` (which
treats pedestrians as signal-phasing objects at a single junction) and
`simulate-multimodal-transit` (which treats walking as an abstract mode-choice leg).

## Measurement: no induction-loop equivalent exists for persons

SUMO has no pedestrian analog of an E1/E2 detector. Derive density, speed, and flow
from `--fcd-output` person records via Edie-style space-time averaging (density =
total person-time in a space-time window / window area; flow = total person-distance
/ window area; mean speed = flow/density), and **validate the reconstruction against
at least two independent references before trusting it**: (1) compare total flow
against the known realized demand rate, and (2) compare against an independent
"virtual loop" style count (a narrow crossing-line count of persons transiting a
fixed point) rather than relying on the FCD reconstruction alone. Also cross-check
against `<personinfo>`/`<walk>` entries in `tripinfo` for a third, coarser sanity
check. A reconstruction that agrees with all of these to within a few percent can be
trusted for the fundamental-diagram work below.

## Fitting a pedestrian fundamental diagram

Sweep demand from free-flow to jam and fit speed-density/flow-density curves (a
Weidmann-style model is a reasonable functional form). Report free-flow speed,
capacity (both in persons/s and persons/s per meter of width, for cross-scenario
comparability), critical density, and jam density, and compare against published
real-world pedestrian benchmarks (roughly 1.2-1.5 persons/s/m capacity, 4-5
persons/m² jam density) to judge whether the simulated pedestrian is realistic.

**Expect SUMO's default pedestrian fundamental diagram to be internally clean (a
good model fit) but its levels to fall meaningfully below real-world benchmarks —
and check whether the entire gap is explained by the stripe-quantization mechanism
below before concluding the underlying pedestrian dynamics model itself is
unrealistic.** Verified case: reported capacity and jam density were both
substantially below real-world reference ranges, but capacity computed **per
lateral stripe** (rather than per meter of raw width) landed inside the real-world
band, and jam density was structurally explained by the ratio of stripe width to
pedestrian body width — the deficit was a discretization artifact of the model's
lateral space representation, not a flaw in its longitudinal (speed-density)
dynamics.

## Stripe quantization: sidewalk capacity is a staircase function of width, not a linear one

**This is the central, most transferable finding of this skill.** SUMO's default
`striping` pedestrian model discretizes a sidewalk's width into lateral stripes
(`--pedestrian.striping.stripe-width`, default 0.64 m) — a pedestrian effectively
occupies one stripe, and the number of stripes a sidewalk can hold is
`floor(width / stripe_width)`. **Measured capacity therefore rises in discrete steps
at stripe-count boundaries, not proportionally with sidewalk width.** Sweep width in
fine increments and fit both a staircase model (`capacity = c * floor(width /
stripe_width)`) and a naive proportional model against the data — expect the
staircase model to fit dramatically better (verified case: R² above 0.999 for the
staircase model vs. the low-0.9s for a proportional fit), and expect a large
fraction of tested width increments to buy essentially **zero** additional capacity
(verified case: three-quarters of tested increments were within a stripe boundary
and produced no measurable capacity gain). **Confirm the mechanism, don't just
observe the pattern**: re-run a subset of the sweep with a changed
`--pedestrian.striping.stripe-width` and verify the step (riser) locations move to
the new stripe-width's multiples — this rules out the staircase pattern being a
coincidental artifact of the specific widths tested.

**Watch for a subtle floating-point quirk in exactly which width triggers a given
stripe count.** The `floor(width/stripe_width)` computation can be evaluated in raw
floating point without a tolerance/epsilon adjustment, so a width that is
*mathematically* exactly `n * stripe_width` can floating-point-round to just under
`n` and get assigned `n-1` stripes instead of `n` — verified directly (e.g.
`2.4/0.8` evaluating to `2.9999999999999996` rather than `3.0` in the underlying
computation, moving that riser's actual location by one stripe-width's worth of
distance from the naive prediction). If a specific riser location doesn't match the
naive `n * stripe_width` prediction, check for this before assuming the mechanism
is wrong.

**Practical implication**: a sidewalk-widening design intervention can be
completely ineffective if it doesn't cross a stripe-count boundary — check the
target width against `floor(width/stripe_width)` before recommending or evaluating
a specific widening amount, rather than assuming capacity scales continuously with
added width.

## The jam-resolution parameter: verify the actual default, don't assume a commonly-cited value

`--pedestrian.striping.jamtime` controls how long a pedestrian can be stuck before
the model pushes them through a jam as an escape-valve mechanism (loosely analogous
to vehicle teleporting). **Verify the actual default value directly** (e.g. via
`sumo --save-template`) rather than trusting a commonly-cited or intuitively-assumed
number — verified case: the actual default was substantially higher (300 s) than a
commonly-assumed value (10 s) that appears in some contexts as a "default." At the
genuine default, artifact contamination of measured high-density capacity was
negligible; at the lower, commonly-assumed value, measured flow was inflated by a
substantial margin (verified case: 16-33%) accompanied by genuine simulated
pedestrian collision events. **This means a study that assumes the lower value
either explicitly or by copying an example configuration could be measuring a
significantly artifact-inflated capacity without realizing it.**

**Quantify artifact contamination directly by scanning simulation logs for jam/
push-through events and checking whether they fall inside or outside the
measurement region/window** — this is the pedestrian analog of
`validate-congested-scenario-results-against-teleport-artifacts`'s vehicle-teleport
discipline. **Density alone is not a reliable trust criterion for whether a given
run's results are artifact-free** — verified case: the demand-to-capacity ratio was
a much better predictor of contamination than raw measured density, since the
densest *clean* runs and the *most contaminated* runs were not the same runs. Check
contamination as a function of demand/capacity ratio, not density alone.

## Counterflow: check for realistic lane formation, don't assume it

Sweep the directional demand split at fixed total demand and measure the capacity
penalty from mixing opposing pedestrian flows. **Test explicitly whether the model
reproduces spontaneous lane formation** (opposing streams self-organizing into
lateral bands, reducing conflict) by computing a segregation index from the
lateral-position distribution of each direction's pedestrians via FCD, comparing
free-flow to saturated conditions. **Do not assume the model reproduces this
correctly — verify the direction of the effect.** Verified case: the striping
model's segregation index actually *decreased* under counterflow saturation,
opposite to the increased segregation real pedestrian crowds exhibit under
pressure — traced to a specific parameter (`reserve-oncoming`, which reserves
lateral space for an oncoming stream) defaulting to a value that doesn't produce
the expected behavior on an ordinary (non-designated-counterflow) lane. **A
counterflow capacity-penalty percentage computed under this artifact should be
treated as reflecting the striping model's actual (backwards) behavior, not
real-world pedestrian counterflow physics**, until the segregation-index check
confirms realistic lane formation is actually occurring.

## Model choice: know what a simplified model silently discards

Compare the default `striping` model against `--pedestrian.model nonInteracting`
(and `jupedsim` if the SUMO build supports it) on a genuinely crowded scenario.
`nonInteracting` pedestrians do not interact with or congest each other at all —
**verify this produces identical results across designs that should differ under
real congestion** (e.g. a narrow vs. wide bottleneck design producing the same
clearance time and walk speed under `nonInteracting` is the expected signature of
the model silently discarding the entire congestion phenomenon, not a bug). If
testing `jupedsim`, check for interoperability side effects with the rest of the
scenario (verified case: a `jupedsim` run produced vehicle-side teleports and an
implausibly high peak pedestrian density not seen under `striping`) — **disclose
and explicitly exclude a model's results from headline conclusions if it produces
such side effects**, rather than silently smoothing over an interoperability issue.

## Application to design questions: distinguish "relocates the queue" from "fixes the bottleneck"

When applying pedestrian flow results to a design question (e.g. widening a
sidewalk bottleneck upstream of a signalized crossing), **measure the queue at
every point along the corridor, not just at the bottleneck** — a design that "fixes"
the measured bottleneck by widening it can simply relocate the binding constraint
downstream (e.g. to a signalized crossing's green time) without improving total
clearance time. Compute Fruin-style pedestrian level-of-service from measured
density along the full corridor to visualize where the actual constraint sits.
**Report the reverse coupling explicitly**: a pedestrian surge at a crossing can
measurably degrade vehicle throughput on the crossed street, and this cost should
be weighed against a design intervention's pedestrian-side benefit — compute
exchange rates (e.g. person-hours saved per vehicle-hour cost) for competing
interventions (signal re-timing vs. physical widening) rather than evaluating each
in isolation.

## Gotchas

- **Sidewalk capacity is quantized by the striping model's stripe width — a design
  widening that doesn't cross a stripe-count boundary can buy essentially zero
  additional capacity.** Check `floor(target_width/stripe_width)` before
  recommending or evaluating a widening amount.
- **`floor(width/stripe_width)` can be computed in raw floating point without
  tolerance handling** — a width that's mathematically an exact multiple of the
  stripe width can round down to one fewer stripe than expected, shifting the
  observed riser location by one stripe-width.
- **Verify `--pedestrian.striping.jamtime`'s actual default directly** (e.g. via
  `sumo --save-template`) rather than trusting a commonly-cited value — using an
  assumed-but-wrong lower value can silently and substantially inflate measured
  capacity via jam-resolution push-through artifacts.
- **Density alone is not a reliable indicator of jam-artifact contamination** —
  demand/capacity ratio is a better predictor; the densest runs are not necessarily
  the most contaminated.
- **Do not assume the striping model reproduces realistic counterflow lane
  formation** — verify the direction of the segregation-index effect explicitly;
  it can run backwards from real-world pedestrian crowd behavior depending on
  `reserve-oncoming` and related parameters.
- **`nonInteracting` silently discards all pedestrian congestion phenomena** —
  producing identical clearance-time/speed results across designs that should
  differ is the expected signature of this, not evidence the designs don't matter.
- **A widening intervention that "fixes" a measured bottleneck can just relocate
  the binding constraint downstream** — measure level-of-service along the entire
  corridor, not just at the widened point.

## Related

- `build-pedestrian-crossings-and-phasing` — the crossing/walkingarea network
  construction and tlLogic link-indexing technique this skill's egress network
  builds on; that skill treats pedestrians as signal-phasing objects, this skill
  treats them as a flow entity.
- `build-macroscopic-fundamental-diagram` — the vehicle-side fundamental-diagram
  methodology (demand sweep, flow/density/speed derivation, capacity/critical-
  density identification) this skill's pedestrian FD directly adapts, substituting
  FCD person records for E1-loop vehicle counts.
- `validate-congested-scenario-results-against-teleport-artifacts` — the vehicle
  teleport-artifact validation discipline this skill's jam-resolution artifact
  quantification directly parallels.
- `visualize-trajectories-and-timeseries` — the FCD-based time-space diagram
  technique this skill's pedestrian time-space diagrams reuse.
- `simulate-emergency-evacuation` — the interior-to-boundary egress demand
  construction and clearance-time analysis technique this skill's venue-egress
  application extends.
- `quantify-sumo-run-to-run-variability` — the CRN replication discipline applied
  throughout; this skill's demand sweeps run straight through the free-flow-to-jam
  transition, where CRN benefit is not uniform across metrics and must be checked
  per metric.
- [[pedestrian-flow-theory-and-striping-model-artifacts]] — the verified
  stripe-quantization staircase law, the corrected jamtime default and its
  artifact implications, the inverted counterflow-segregation finding, the
  model-choice comparison, and the widen-vs-retime egress design finding this
  skill's methodology produced.
