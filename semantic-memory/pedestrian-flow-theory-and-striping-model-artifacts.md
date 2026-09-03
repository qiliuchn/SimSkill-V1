---
summary: SUMO's default striping pedestrian model produces a clean fundamental-diagram fit but capacity levels 9-27% below real-world benchmarks, entirely explained by lateral stripe quantization (sidewalk capacity rises in discrete steps at floor(width/stripe_width) boundaries, not proportionally with width, confirmed by moving the steps when stripe-width itself is changed, down to a floating-point rounding quirk); the jam-resolution parameter --pedestrian.striping.jamtime actually defaults to 300s (not the commonly-cited 10s), and only the low, non-default value produces meaningful capacity-inflating artifacts; the model's counterflow behavior is qualitatively backwards from real crowds (a lateral segregation index decreases, not increases, under saturation); nonInteracting silently discards all pedestrian congestion; and in a station-egress application, widening a bottleneck mostly relocates the queue to a downstream signalized crossing, making signal re-timing dramatically more cost-effective than physical widening in most tested cases.
keywords:
  - pedestrian-fundamental-diagram
  - striping-model
  - stripe-width-quantization
  - jamtime
  - pedestrian-counterflow
  - pedestrian-level-of-service
  - crowd-flow
created: 2026-08-02T21:30:00
last_updated: 2026-08-02T21:30:00
sources:
  - "[[episodic-memory/2026-08-02_21-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-02_21-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[pedestrian-crossings-and-signal-phasing]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[evacuation-clearance-time-analysis]]"
related_skills:
  - characterize-pedestrian-flow-and-striping-model-artifacts
  - build-pedestrian-crossings-and-phasing
  - build-macroscopic-fundamental-diagram
  - validate-congested-scenario-results-against-teleport-artifacts
  - simulate-emergency-evacuation
related_skills_for_graph_view:
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
  - "[[build-pedestrian-crossings-and-phasing]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[simulate-emergency-evacuation]]"
---

# Pedestrian Flow Theory and Striping Model Artifacts

SUMO's default `striping` pedestrian model has never previously been characterized
in this project as a flow entity — earlier pedestrian work treated pedestrians only
as signal-phasing objects at a crossing, or as an abstract mode-choice leg. This
page treats pedestrians as first-class flow agents: what is the pedestrian
fundamental diagram, where does the striping model depart from real-world crowd
physics, and what design and validity implications follow.

## Verified finding: sidewalk capacity is a staircase function of width, not a proportional one

SUMO's `striping` pedestrian model discretizes a sidewalk's width into lateral
stripes (`--pedestrian.striping.stripe-width`, default 0.64 m); a sidewalk holds
`floor(width / stripe_width)` pedestrians abreast. **Measured capacity was found to
rise in discrete steps at these stripe-count boundaries rather than proportionally
with sidewalk width** — a staircase model (`capacity = c * floor(width/stripe_width)`)
fit a fine width sweep dramatically better than a proportional model (R² above 0.999
vs. the low 0.9s), and roughly three-quarters of tested width increments produced
essentially zero measurable capacity gain, because they fell within a single stripe
boundary. **The mechanism was confirmed, not just observed**: re-running a subset of
the sweep with a different `--pedestrian.striping.stripe-width` moved the step
(riser) locations to the new stripe-width's multiples exactly as predicted, down to
reproducing a specific floating-point rounding quirk in the underlying
`floor(width/stripe_width)` computation (a width that is mathematically an exact
multiple of the stripe width can round down to one fewer stripe due to raw
floating-point evaluation, shifting that riser's actual location by one
stripe-width). **A sidewalk-widening design intervention that doesn't cross a stripe
boundary buys no measurable capacity** — this is directly actionable for pedestrian
facility design, and directly explains why a naive design model would predict a
capacity benefit that the simulation (and, plausibly, striping-model-calibrated
real infrastructure) would not deliver.

**This quantization mechanism also explains SUMO's default pedestrian's apparent
below-benchmark fundamental-diagram capacity and jam density.** Measured capacity
and jam density both fell meaningfully below commonly-cited real-world benchmarks
(roughly 1.2-1.5 persons/s/m capacity, 4-5 persons/m² jam density) when computed
per raw meter of width — but capacity computed **per lateral stripe** landed inside
the real-world band, and jam density was structurally explained by the ratio of the
stripe width to pedestrian body width. The underlying longitudinal (speed-density)
dynamics fit a Weidmann-style model extremely well (R² above 0.99); the entire
apparent capacity deficit is a lateral-discretization artifact, not a flaw in the
model's core car-following-analog dynamics.

## Verified finding: the jam-resolution parameter's actual default is far higher than commonly assumed, and only the low value produces meaningful artifacts

`--pedestrian.striping.jamtime` is the pedestrian model's escape-valve mechanism —
loosely analogous to vehicle teleporting — that pushes a stuck pedestrian through a
jam after a timeout. **Its actual default value, verified directly against SUMO's
own parameter defaults, is 300 seconds, substantially higher than a value (10
seconds) that is commonly assumed or cited as the default in some contexts.** At the
genuine default, scanning simulation logs for jam/push-through events and checking
whether they fall inside the measurement region found artifact contamination of
measured high-density capacity to be negligible. At the lower, commonly-assumed
value, measured flow was inflated by a substantial margin (16-33% in the tested
configuration), accompanied by genuine simulated pedestrian collision events —
meaning a study that copies an example configuration assuming the lower value is
"the default" could be reporting a significantly artifact-inflated capacity without
realizing it. **Density alone was found to be an unreliable predictor of which runs
are contaminated — demand/capacity ratio was a substantially better indicator**,
since the densest runs were not the same runs as the most artifact-contaminated
ones. This is the pedestrian-flow analog of
[[teleport-artifacts-and-gridlock-resolution-validity]]'s vehicle-side teleport
discipline.

## Verified finding: the striping model's counterflow behavior runs backwards from real crowds

Testing counterflow (opposing pedestrian streams sharing a corridor) at varying
directional splits found a real capacity penalty from mixing directions, but
**testing explicitly for spontaneous lane formation** (via a lateral-position
segregation index computed separately for each direction from FCD data) found the
striping model's segregation **decreased**, not increased, under counterflow
saturation — the opposite of the self-organizing lane formation real pedestrian
crowds exhibit under pressure. This was traced to a specific model parameter
(`reserve-oncoming`, which reserves lateral space for an oncoming stream)
defaulting to a value that does not produce realistic counterflow segregation on an
ordinary lane. **A counterflow capacity-penalty percentage computed under this
condition should be understood as reflecting the striping model's actual
(non-realistic) counterflow mechanics, not validated real-world pedestrian
counterflow physics**, until a segregation-index check confirms lane formation is
genuinely occurring.

## Verified finding: `nonInteracting` silently discards all pedestrian congestion

Comparing the default `striping` model against `--pedestrian.model nonInteracting`
on a crowded design scenario found `nonInteracting` produces **identical** clearance
time and walk speed across designs that should differ substantially under real
congestion (e.g. a narrow vs. a wide bottleneck) — the expected signature of a model
that does not represent pedestrian-pedestrian interaction or congestion at all, not
a sign of a broken comparison. Anyone evaluating a pedestrian facility design under
`nonInteracting` is silently discarding the entire phenomenon (crowding, queuing,
capacity limits) the design question usually depends on.

## Verified finding: widening a bottleneck often just relocates the queue

Applying the above to a station/venue egress design (a plaza feeding a narrow
sidewalk bottleneck, then a signalized street crossing) found that widening the
sidewalk bottleneck mostly **relocated** the binding constraint to the downstream
signalized crossing rather than reducing total egress clearance time — a design
that "fixes" the measured bottleneck can leave overall clearance time nearly
unchanged if the crossing's green time becomes the new binding constraint.
Comparing exchange rates between competing interventions (signal re-timing vs.
physical widening) found re-timing paid off far more favorably per unit of cost in
most tested conditions — physical widening was worthwhile primarily where it
crossed a stripe-count boundary (see above) and where the corridor design still
required extra plaza-side capacity for other reasons (e.g. crowd safety margin).
**The reverse coupling was also measured**: a pedestrian surge at the crossing
measurably degraded vehicle throughput on the crossed street, a cost that should be
weighed against any pedestrian-side benefit when comparing interventions.

## Practical takeaways

- Check `floor(target_width / stripe_width)` before recommending or evaluating a
  sidewalk-widening amount — a widening that doesn't cross a stripe-count boundary
  buys essentially no capacity in SUMO's default pedestrian model.
- Verify `--pedestrian.striping.jamtime`'s actual default directly rather than
  trusting a commonly-cited value; using an incorrect lower value can silently
  inflate measured pedestrian capacity via jam-resolution artifacts.
- Use demand/capacity ratio, not raw density, to judge which pedestrian-flow runs
  are likely to be jam-artifact contaminated.
- Don't assume the striping model reproduces realistic counterflow lane formation
  — check the segregation-index direction explicitly.
- Treat `nonInteracting` pedestrian results as informative about routing/geometry
  only, never about congestion or capacity.
- When evaluating a bottleneck-widening design, measure level-of-service along the
  entire corridor (not just at the widened point) to check whether the queue has
  actually been eliminated or merely relocated.

See `characterize-pedestrian-flow-and-striping-model-artifacts` for the full
FCD-based measurement, fundamental-diagram-fitting, and artifact-validation
methodology.
