---
name: validate-kinematic-wave-theory-across-car-following-models
description: Use this skill when the user wants to test whether SUMO obeys kinematic wave (LWR) theory at the link scale, fit and compare fundamental diagrams (flow-density-speed) across car-following models (Krauss, IDM, EIDM, ACC, W99), verify the closed-form parameter-to-FD-feature formulas (jam density from length+minGap, wave speed from tau), measure shock/wave speeds directly from FCD trajectories and compare against Rankine-Hugoniot theory, test for the capacity-drop phenomenon, or test Newell's moving-bottleneck theory. Covers a controlled-density closed-ring FD instrument, the discovery that the textbook w=(l+g)/tau and q_max formulas are Krauss-sigma=0 identities rather than general SUMO relations, direct wave-front tracing from FCD on signalized and incident-blockage links, and a from-scratch moving-bottleneck methodology. Trigger on mentions of fundamental diagram, kinematic wave theory, LWR, shockwave speed, Rankine-Hugoniot, capacity drop, moving bottleneck, Newell, or jam density.
related_skills:
  - build-macroscopic-fundamental-diagram
  - demonstrate-and-stabilize-phantom-traffic-jams
  - visualize-trajectories-and-timeseries
  - simulate-incident-rerouting
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[simulate-incident-rerouting]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
---

# Validate Kinematic Wave Theory Across Car-Following Models

Tests whether SUMO's microsimulation obeys kinematic wave (LWR) theory at the link
scale, and — the more consequential question — how much of any measured traffic-flow
relationship is a property of the chosen car-following model rather than of physics.
This is a foundational methodological skill: many other skills in this project's
memory implicitly assume a specific car-following model's behavior generalizes: this
skill quantifies exactly when that assumption is safe and when it silently substitutes
model choice for traffic physics.

## Instrument: a controlled-density closed ring

Build a single-lane, homogeneous, junction-free closed ring (verify from the compiled
net: zero traffic lights, zero internal edges, a single lane count and speed limit,
and that the edges actually close into a circular walk — see
`demonstrate-and-stabilize-phantom-traffic-jams` for the base construction). On a
closed ring, density is **exact and controlled**, not estimated: `k =
(perimeter_length * N_running) / L`, and space-mean speed on a homogeneous 1-D ring
equals the arithmetic mean speed of vehicles present at an instant — precisely SUMO's
`<summary>` `meanSpeed` — so `q = k*v` is exact too. This is a methodological upgrade
over `build-macroscopic-fundamental-diagram`'s open-road E1-occupancy density
*estimate*, and is the right choice whenever the study needs a clean FD to compare
against, not just a realistic scenario.

**Ring size matters per model, not just per topology.** A ring built from too few
nodes (long, few edges) can produce a genuine free-speed artifact for a model whose
car-following logic has meaningful look-ahead — verified case: a look-ahead-sensitive
model failed to reach its own configured free speed (24.5 m/s instead of 30.0 m/s for
a single vehicle alone on the ring) when the ring used 8 or fewer nodes, but reached
the correct free speed at 16+ nodes. Don't assume a ring construction validated for
one car-following model transfers cleanly to another — re-verify free-speed reach for
each model tested, especially any model with an anticipatory or multi-vehicle
look-ahead mechanism.

**Insertion can silently under-fill a dense ring.** `departSpeed="max"` inserts the
first vehicle at free speed, after which every follower needs a free-flow-sized safe
gap to insert — the insertion cascade aborts above a moderate density and the ring
ends up under-filled with no error (verified: 100 requested vehicles inserting only
87, in one case as few as 12 of 130 for a particularly conservative model). Insert at
an estimated equilibrium speed for the target density instead, and retry with
progressively lower departure speeds until `running == requested` — verify complete
insertion explicitly for every density cell, don't assume the requested count loaded.

## Fitting the fundamental diagram, honestly

Sweep vehicle count across the full density range, run each cell to a genuine
steady state (discard a transient warm-up window), and fit a triangular FD (free-flow
branch through the origin, congested branch through jam density) via least squares.
**Report the fit quality (R²) per branch and overall, and don't assume every
car-following model actually produces a triangular FD** — a model whose equilibrium
speed-spacing relation only asymptotically approaches free speed (rather than
plateauing) can show a genuinely curved free-flow branch, and a through-origin linear
fit to such a model is biased by construction: the fitted apex can exceed the model's
own highest ever observed flow, because the fit's free-branch line overshoots data
that never actually reaches it. When this happens, report **both** the fitted
low-density free speed (the model's true free speed) and the biased triangular-fit
value, and be explicit about which one downstream calculations use.

**Watch for two failure modes that corrupt the congested branch specifically, not
just add noise to it:**

- **Ring gridlock below a model's expected jam density.** Some car-following models
  can permanently lock the entire ring at a density where the implied standstill
  spacing is physically implausible (well above the vehicle-length-plus-minGap
  floor) — verified case: complete, permanent gridlock at a spacing roughly double
  the physical minimum, reproduced at every departure speed and over long run
  durations. When this happens, the model's jam density and wave speed above the
  gridlock threshold are **extrapolations past the last flowing observation, not
  measurements** — report them as such (or omit them) rather than presenting a
  regression-fit value as if it were measured data.
- **Collisions in the high-density tail.** At very short following distances or
  aggressive parameter settings, some models can produce genuine simulated collisions
  rather than a clean jam. **Check `collisions` from the run summary at every density
  cell, not just teleports** — a cell with nonzero collisions should be flagged and
  either re-run under conditions that eliminate the collisions or explicitly excluded
  from any fitted statistic, exactly like a teleport-contaminated cell would be. An
  unusually large seed-to-seed standard deviation at one demand/density point is a
  useful early warning sign of collision contamination and should be investigated
  before being reported as ordinary variance.

**Test for bistability, not just a single steady-state curve.** Run every density
cell twice — once undisturbed, once with a single, small, one-shot perturbation (e.g.
a brief stop by one vehicle, per `demonstrate-and-stabilize-phantom-traffic-jams`'s
brake-pulse technique). Some models can sustain meaningfully different steady-state
flow at the *same* density depending on whether a perturbation ever triggered
breakdown — the fundamental diagram is not necessarily single-valued, and a model
that shows large unperturbed-vs-perturbed flow gaps at a given density has a genuinely
different multi-state character from one that always returns to the same flow
regardless of perturbation history.

## Testing the closed-form parameter-to-FD-feature formulas

Textbook formulas relate car-following parameters directly to FD features:
`k_j = 1 / (length + minGap)`, `w = (length + minGap) / tau`, and
`q_max = v_f / (v_f*tau + length + minGap)`. **Test these empirically by sweeping
each parameter (tau, minGap, length, and, for models that have it, a stochastic
driver-imperfection parameter like sigma) one at a time and comparing the fitted FD
against the closed-form prediction — do not assume they hold generally.**

**The critical finding to check for**: these formulas can turn out to be exact
identities of one specific car-following model at its *deterministic* (zero driver
imperfection) setting, not general SUMO relations. Verified case: at zero
imperfection, one model reproduced all three formulas to within a fraction of a
percent; introducing SUMO's typical nonzero default level of driver imperfection
cost a consistent, substantial fraction of both predicted wave speed and capacity
(a clean, nearly linear degradation as the imperfection parameter increased); a
different model with fundamentally different dynamics failed the wave-speed formula
by up to ~75%, because its wave speed barely responds to the tau parameter at all.
**Only the jam-density relation (`k_j = 1/(length+minGap)`) held robustly across every
tested model** — treat this as the one safe generalization, and treat the wave-speed
and capacity formulas as model-specific until verified for the specific model in use.

**Produce a practical parameter-to-FD-feature guide** stating, per vType parameter,
which FD features it controls, the direction and rough magnitude of the effect, and a
confidence rating per model (high where the closed-form prediction was verified to
hold, low where a model's behavior diverges or is untested) — this is the single most
reusable artifact for anyone tuning a vType to hit a target capacity or wave speed.

## Measuring wave/shock speeds directly and testing Rankine-Hugoniot

Beyond the ring, measure wave fronts directly on open-road scenarios by tracing FCD
trajectories on a time-space diagram (see `visualize-trajectories-and-timeseries`) and
fitting a line to the position of a clearly-identifiable congestion-marker front over
time — its slope is the measured wave speed. Test at least two independent
mechanisms: a temporary full-lane blockage (an incident, via
`simulate-incident-rerouting`'s `closingReroute`/`closingLaneReroute`) and a
signalized link's stopping wave (formed at red) and start-up wave (released at
green).

**Compare the measured wave speed against the Rankine-Hugoniot prediction computed
from that SAME model's OWN measured fundamental diagram** (`w = (q2-q1)/(k2-k1)`
between the two flow states bracketing the wave), not a generic textbook value — the
whole point is testing self-consistency between a model's steady-state FD and its
transient shock behavior, and a comparison against an external reference FD would
conflate two different questions.

**Expect strong agreement on a physical blockage and expect the possibility of real,
mechanistically-explainable disagreement on a signal.** A physical lane blockage
creates a genuine two-state, conservation-law-obeying shock, and agreement with
Rankine-Hugoniot there is a meaningful confirmation that the conservation law itself
holds even though different models' predicted wave speeds can differ substantially
from each other. A signalized link's stop/start cycle is a shorter, repeated
disturbance, and disagreement there is diagnostic, not necessarily a failure of
kinematic wave theory itself — check two specific alternative explanations before
concluding the theory fails: (1) **the transition may not be a genuine shock** if a
model's stopping behavior is anticipatory rather than reactive (bringing vehicles to a
full stop well before they'd need to under simple car-following, producing a stopping
wave that travels faster than the model's own jam-density physics would predict,
because it isn't tracking a jam-density front at all); (2) **the queue state itself
may not be the jammed state the theory assumes** if the signal's red phase is too
short relative to the model's dynamics for the queue to actually reach jam density
(a fast-release "queue" at well below jam density will show a release wave faster
than the jam-to-capacity Rankine-Hugoniot prediction, because it's releasing from a
less-dense state than assumed). Distinguish these from a genuine conservation-law
failure by checking the actual measured queue density against the model's own k_j.

## Testing for capacity drop

At a fixed bottleneck (a lane drop or a speed-limit drop), measure discharge flow
before and after the queue breaks down. **Use two different bottleneck mechanisms
that differ specifically in whether lane changing is involved** (a lane-drop
bottleneck requires merging; a same-lane speed-drop bottleneck does not) — this
isolates whether any observed capacity drop is a lane-changing/merging phenomenon or
a more fundamental car-following effect. Verified pattern: capacity drop can be large
(25-47%) at a merge-requiring bottleneck across every tested model, while being
essentially absent (within measurement noise) for some models but still present
(~15%) for others at a lane-change-free bottleneck — meaning capacity drop in SUMO is
frequently, but not exclusively, a lane-changing-model artifact rather than a pure
car-following/FD phenomenon, and this split should be tested explicitly rather than
assumed.

## Testing Newell's moving-bottleneck theory (a genuine gap — build from first principles)

A slow-moving vehicle (e.g. a truck at speed `u` below free-flow speed) that other
vehicles cannot pass acts as a moving bottleneck. Two testable regimes:

- **Single lane, passing physically impossible**: every follower is forced to speed
  `u`, so the state behind the truck is the FD point whose chord slope `q/k` equals
  `u`: `k_u = w*k_j/(u+w)`, `q_u = u*k_u` (with `u`, `w` in consistent units).
  Predicted platoon flow is `min(demand, q_u)`.
- **Multiple lanes, truck occupies one lane with lane-changing disabled for it**: in
  the truck's reference frame, only the other lane(s) are available for passing, so
  the passing rate is the moving-frame throughput of a single lane,
  `r = max_k[q(k) - u*k]`. For a triangular FD, downstream conservation collapses the
  multi-lane discharge capacity to exactly the *single-lane* capacity, **independent
  of `u`** — a genuinely testable, non-obvious prediction.

**Verify state-dependence explicitly**: sweep both truck speed `u` and upstream
demand, and confirm a queue forms behind the truck only once demand exceeds the
predicted passing capacity `q_u` — the demand level at which discharge stops tracking
offered demand should bracket the theoretical prediction. **Expect the multi-lane
u-independence prediction to hold for models whose FD genuinely governs multi-lane
discharge, and expect it to fail specifically for a model whose lane-change gap
acceptance is the binding constraint** rather than its underlying FD — a large,
consistent (not noisy) shortfall from the theoretical multi-lane capacity, present
at every tested truck speed, is the signature of a lane-changing-limited rather than
FD-limited discharge process.

## Gotchas

- **A multi-lane E1 detector "station" must sum flow across lanes and compute
  density per lane before summing** — pooling every lane's vehicle-count/duration
  ratio into one combined figure silently returns the per-lane *mean* flow, not the
  station's total flow, which can be roughly half the true value on a 2-lane station.
  This is a severe, sign-preserving-but-magnitude-halving bug that can make a correct
  discharge measurement look like a major theory disagreement — verify any multi-lane
  discharge measurement against a single-lane sanity check before trusting it.
- **A ring built with too few nodes can produce a model-specific free-speed artifact**
  for car-following models with meaningful look-ahead — re-verify free-speed reach
  per model, don't assume a ring validated for one model transfers to another.
  `departSpeed="max"` silently under-fills a dense ring above a moderate density
  threshold — verify complete insertion (`running == requested`) at every density
  cell.
- **The textbook `w=(l+g)/tau` and `q_max=v_f/(v_f*tau+l+g)` formulas can be
  identities of one specific car-following model's deterministic setting, not
  general SUMO relations** — verify per model before relying on them, and expect
  driver-imperfection parameters (where present) to cost a consistent, measurable
  fraction of both predicted quantities even for the model where the formulas hold at
  their deterministic setting.
- **A through-origin linear FD fit is biased for a model whose free-flow branch is
  genuinely curved (asymptotic, not plateaued)** — the fitted apex can exceed the
  model's own highest observed flow. Report both the fitted and the true low-density
  free speed, and state which one any downstream calculation uses.
- **Check `collisions`, not just `teleports`, at every density/demand cell of any
  sweep involving a congested or aggressive-parameter regime** — an unusually large
  seed-to-seed standard deviation is an early warning sign, and a cell with nonzero
  collisions should be flagged or excluded exactly like a teleport-contaminated cell,
  never left silently inside a reported average.
- **Some car-following-model parameter sets take effect only as vType attributes,
  not as `<param>` children** — verify a parameter override actually changed behavior
  (not just that it produced no error) before trusting it took effect.
- **A model's congested-branch fit can be an extrapolation well past its last
  actually-flowing observation** if the model gridlocks (permanently, at every
  departure speed and run duration tested) at a density below its nominal physical
  jam density — treat such a model's jam density and wave speed as not measured, not
  as a regression-fit value.

## Related

- `build-macroscopic-fundamental-diagram` — the E1-occupancy-based open-road FD
  measurement this skill's closed-ring instrument upgrades on for cases needing an
  exact, controlled density rather than a realistic-scenario estimate.
- `demonstrate-and-stabilize-phantom-traffic-jams` — the closed-ring construction and
  brake-pulse perturbation technique this skill's bistability test and ring
  methodology directly reuse.
- `visualize-trajectories-and-timeseries` — the time-space diagram construction this
  skill's wave-front tracing depends on.
- `simulate-incident-rerouting` — the `closingReroute`/`closingLaneReroute` mechanics
  used to author this skill's incident-blockage wave-measurement experiment.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN replication and teleport/collision validity discipline applied throughout every sweep in this skill.
- [[macroscopic-fundamental-diagram]] — the network/open-road FD concepts this skill's
  link-scale, model-comparative study extends.
- [[kinematic-wave-theory-validity-across-car-following-models]] — the verified
  agreement/departure findings, the FD-as-model-property finding, the anticipatory-
  stopping and non-jammed-queue wave-speed mechanisms, and the matched-capacity-
  still-differs-in-queueing consequence finding this skill's methodology produced.
