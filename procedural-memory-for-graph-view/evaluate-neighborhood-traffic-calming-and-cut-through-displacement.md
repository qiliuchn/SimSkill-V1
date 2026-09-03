---
name: evaluate-neighborhood-traffic-calming-and-cut-through-displacement
description: Use this skill when the user wants to study neighborhood traffic management in SUMO — cut-through/rat-running traffic through a residential grid, and whether traffic-calming interventions (modal filters, diagonal diverters, speed limits, one-way loop cells) cause "traffic evaporation" or merely "traffic displacement" onto boundary roads. Covers building a permeable residential grid enclosed by a signalized arterial ring, a three-class OD matrix (through/rat-run, resident, local) routed to dynamic user equilibrium SEPARATELY per network variant, instrumenting cut-through share and per-street interior volume, six standard intervention patterns (vClass modal filters, connection-prohibition diverters, one-way cells, speed limits, and combinations), the displacement/amplification ratio onto boundary roads, an elastic-demand crossover test for the evaporation hypothesis, and the diagnosis that a permeable-grid-plus-parallel-arterial DUE fixed point can be converged in cost but only weakly identified in route split. Trigger on mentions of cut-through traffic, rat-running, modal filter, diagonal diverter, traffic calming, low-traffic neighborhood, LTN, traffic evaporation, or traffic displacement.
related_skills:
  - create-grid-network
  - compare-one-way-vs-two-way-street-grid-conversion
  - compute-dynamic-user-equilibrium
  - model-vclass-lane-permissions
  - model-cordon-tolling-with-generalized-cost-surcharge
  - validate-congested-scenario-results-against-teleport-artifacts
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[compare-one-way-vs-two-way-street-grid-conversion]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[neighborhood-traffic-calming-displacement-and-evaporation]]"
---

# Evaluate Neighborhood Traffic Calming and Cut-Through Displacement

Studies where traffic actually goes when residential streets are selectively made
impassable to cars, in a network shape (a permeable interior grid wrapped in a
parallel-capacity arterial) that turns out to have a genuinely hard route-choice
convergence problem this skill exists to diagnose and work around, not just the
traffic-calming comparison itself.

## Network: a permeable residential grid enclosed by an arterial ring

Hand-author plain XML (`netgenerate --grid` cannot express this) for: a low-speed
residential interior grid (1 lane/direction, low speed, `right_before_left` at
interior junctions — **not** plain `priority` with equal edge priorities, which makes
`netconvert` pick one axis as the major road at every junction by tie-breaking rule
and biases any spatial cut-through analysis toward that axis) fully enclosed by a
higher-capacity arterial ring (multi-lane, signalized at intervals, `priority` at the
residential-connector T-junctions), with residential connectors joining *every*
interior boundary junction to the ring (deliberately high permeability — the classic
rat-running geometry) and a handful of external gateway stubs.

**Size Webster signal timing on the ring from its own equilibrium volumes** (using the
baseline variant's converged route file, per
`measure-saturation-flow-and-validate-webster-method`/`optimize-signals-by-tlscycleadaptation`),
then **load the identical signal-plan file in every variant and every replication** —
any signal-performance difference between variants must be a consequence of the
intervention's traffic effect, not a re-timing artifact. Verify via TraCI that the
intended (Webster) program, not netconvert's default program, is actually active.

**Verify every structural claim from the compiled `.net.xml`, not the generator
input**: interior edge count/speed/lanes/priority per variant, and specifically:

- **Modal filter** (a vClass-restricted plug, e.g. `allow="bus bicycle pedestrian
  emergency"` with no `passenger`): confirm the filtered edges' compiled permission
  sets genuinely lack `passenger` in the filtered variant and retain it in others.
  Place the filter on the edges forming the *perimeter* of a target block, not on all
  links incident to one central junction — a central-junction plug can strand block
  faces that a well-placed perimeter plug leaves reachable; verify full passenger-vClass
  forward/backward reachability from every external gateway in every variant as a
  connectivity check.
- **Diagonal diverters** (connection/turn prohibitions at selected interior
  junctions, written as explicit `<delete from= to=/>` entries in the `.con.xml`):
  count movements present at the targeted junctions in the compiled net for the
  diverted variant versus the baseline — confirm the intended movements are
  structurally absent, not merely discouraged.
- **One-way loop cells**: confirm the intended direction survives and the removed
  direction is genuinely absent from the compiled net (`oneway_removed_still_present`
  should be empty), and **report interior lane-km explicitly** — a naive
  (capacity-reducing) one-way conversion mixes a topology effect with a capacity
  effect, unlike the lane-km-neutral "fair" conversion in
  `compare-one-way-vs-two-way-street-grid-conversion`; state which version was built.

## Demand: three OD classes, one trips file routable on every variant

Define TAZs so that a **single trips file is routable on every network variant by
construction**: interior TAZ edge lists should only include directed edges that exist
in every variant (i.e. the directions retained under the one-way conversion) and
exclude any modal-filtered edges — this makes "identical demand across variants" a
structural guarantee, not something to verify after the fact. Build with `od2trips`,
one call per OD class with a distinct id prefix, so each vehicle's class (through/
rat-run, resident inbound, resident outbound, local, background arterial) is
recoverable exactly from its vehicle id in post-processing — this is what makes the
equity decomposition (which class bears the cost of an intervention) possible at all.

**Search for the demand level explicitly rather than picking one.** Too little demand
never activates cut-through behavior; too much either gridlocks (large teleport count)
or produces unstable route-choice convergence (see below) before any intervention
comparison is meaningful. Bracket the level by testing: does free-flow (all-or-nothing)
routing gridlock; does DUE loading produce a large mean departure delay (network can't
absorb the demand); does the route *split* — not just cost — stay stable across DUE
iterations at this level. Report the resulting boundary-arterial volume/capacity ratio
so the reader knows displaced traffic has somewhere non-trivial to go.

## The hardest problem: DUE cost convergence does not imply route-split convergence

**This is the most transferable finding of this skill.** In a permeable grid wrapped in
a parallel-capacity arterial, the interior route and boundary route can be
*near-cost-indifferent* over a wide range of route splits — Wardrop's first principle
constrains route *costs* at equilibrium, not the route *split*, and when many interior
and boundary paths have nearly equal cost, the split is genuinely under-determined.
`duaIterate` can converge cleanly on **cost** (a flat, low route-change-fraction trace)
while the **route split** — often exactly the study's outcome variable, e.g. which
streets carry cut-through traffic — keeps wandering by a large factor depending
entirely on which iteration the run budget happens to end on. **A converged cost trace
and a small route-change fraction are NOT sufficient evidence that route split has
converged** if route split (not just cost) is what the study measures.

**Diagnose this by tracing the outcome variable itself across DUE iterations, not just
cost.** If it oscillates or drifts across a wide tail window, do not report a single
iteration's value. **Three fix attempts to be aware of, and what each actually does**
(don't assume any one is a clean solution):

1. **`--weight-memory`** can remove the oscillation, but can also freeze the
   assignment on a *stable but clearly inferior* fixed point (verified case: ~63%
   worse total generalized cost than the unstable configuration's better iterations,
   with the trajectory still declining when the run budget ran out) — stability is not
   the same as having found a good equilibrium.
2. **Damping the swap rate alone** (a lower Gawron `gA`) does not necessarily fix
   either the oscillation or a steady one-directional drift — don't assume damping the
   swap parameter is sufficient on its own.
3. **Reducing demand** until the *cost* equilibrium is clean can remove genuine
   route-split *instability* (where the interior's much-lower capacity than the
   arterial makes a modest inflow shift produce a large cost swing that a
   best-response dynamic overshoots) without removing the underlying *indifference
   plateau* — the split can still wander within a band even once cost behaves.

**Resolution**: (1) report the outcome variable as a **mean +/- sd over a DUE tail
window** (a property of the equilibrium *set*, with the plateau width itself reported
as a form of uncertainty, alongside seed-level replication sd) rather than a single
iteration's value; (2) select the specific route file handed to the downstream
simulation stage by a **pre-declared, non-cherry-pickable rule** (e.g. the tail
iteration whose outcome-variable value is closest to the tail median) — never "whichever
iteration the run budget happened to end on," since that choice alone can swing the
headline result by several-fold in either direction. Retain every attempted assignment
configuration's full trace as evidence, even the rejected ones — they document that
the final methodology was arrived at deliberately, not by taking the first run that
looked plausible.

## Instrumenting cut-through and equity

Classify every completed vehicle by its OD class (recoverable from the id-prefix
convention above) and compute, per variant: cut-through share (fraction of
through/rat-run-class vehicles whose realized route touches any interior residential
edge), interior-street veh-km broken out by OD class, the spatial distribution of
interior volume (which specific streets absorb the diverted traffic — report a Gini
coefficient or equivalent concentration measure, not just a network-wide mean), and
mean trip time/distance **broken out by OD class** so a resident-vs-through-traffic
detour penalty (the equity dimension) is visible rather than hidden in an aggregate.

**Expect the equity result to run counter to the intervention's stated intent**: verify
explicitly whether the largest time penalty from an intervention falls on the
targeted through-traffic class or on residents' own local/resident trips — in one
tested case it was consistently the latter, in every variant, never the former.
**Also expect volume concentration (Gini) to rise even in variants that reduce total
interior exposure** — a scheme that improves the neighborhood-wide average can still
make specific streets (those flanking a modal filter, the surviving direction of a
one-way pair, the outer ring of a diverter pinwheel) measurably worse.

## Measuring displacement: the boundary-arterial exchange rate

Compute the ratio of **boundary-arterial veh-km increase** to **interior veh-km
decrease** for each intervention — this "exchange rate" is typically well above 1.0
(the boundary route is longer than the interior shortcut it replaces), meaning
displacement is not merely a 1-for-1 relocation but an *amplification* of total system
vehicle-km. **State precisely what the interior-veh-km-decrease denominator measures**:
if an intervention's interior reduction is partly offset by an increase in some other
interior-traffic class (e.g. diverted through traffic funneling extra distance onto
residents' own routes), the ratio is being computed against *total* interior change,
not a pure cut-through-only figure — this distinction matters for precise reporting
and is easy to blur in prose even when the underlying computation is correct.

## Testing displacement vs. evaporation with elastic demand

A fixed OD matrix cannot show evaporation by construction — there is no mechanism for
a trip to simply stop existing. To genuinely test the evaporation hypothesis, re-run
the best-performing intervention with a **generalized-cost feedback loop** that
suppresses or mode-shifts trips whose equilibrium cost rises past a threshold (an
MSA-damped outer loop reusing the mechanism in
`model-cordon-tolling-with-generalized-cost-surcharge`'s TraCI perceived-cost
rerouting, or an elastic-demand model), swept across a range of demand elasticities.

**Expect only some conclusions to flip with elasticity, not all of them — check each
outcome measure's own crossover point separately.** In one tested case, "this
intervention raises total system travel time" and "this intervention adds delay to
the boundary arterial" each flipped at a real, empirically-plausible elasticity value,
but "this intervention puts more vehicle-km onto the boundary arterial" **never**
flipped even at a high elasticity with a substantial fraction of demand suppressed —
evaporation can settle a pure system-efficiency argument while leaving an
interior-vs-boundary equity argument completely unresolved. Report each outcome
measure's own elasticity crossover (or its absence) rather than a single blanket
"evaporation solves it" or "evaporation doesn't matter" verdict.

## Measuring the access-cost tradeoff

Compute shortest-path response time/distance from an external point to every interior
address for both an exempted vClass (e.g. `emergency`) and an ordinary passenger car,
under each intervention. **A vClass-based modal filter and a speed-limit intervention
have structurally different access-cost signatures, and this is worth verifying
explicitly, not assuming**: a modal filter that exempts a vClass can cost that vClass
*exactly zero* additional time (its shortest path is unaffected, since it's permitted
through the filter) while still costing ordinary cars real detour time — a speed limit,
by contrast, is not selective and imposes the same relative time cost on every vehicle
class using the affected streets, exempted or not.

## Gotchas

- **`priority`-type junctions with equal edge priorities bias which axis `netconvert`
  treats as major at every interior junction** — use `right_before_left` for a
  symmetric unsignalized residential grid unless a genuine major/minor hierarchy is
  intended.
- **A modal filter placed on all links incident to one central junction can strand
  block faces** — place it on the perimeter edges of a target block instead, and
  verify full vClass connectivity from every external gateway as a check.
- **A converged DUE cost trace and a low route-change fraction do NOT guarantee the
  route split has converged**, in a network shape where interior and boundary routes
  are near-cost-indifferent — trace the actual outcome variable across the DUE tail,
  not just cost, whenever the study's outcome is which streets are used rather than
  how long trips take.
- **`--weight-memory` can trade oscillation for a stable-but-clearly-inferior fixed
  point** — don't treat stability alone as evidence of a good equilibrium.
- **A naive (capacity-reducing) one-way conversion mixes a topology effect with a
  capacity effect** — state explicitly which version (naive vs. lane-km-neutral
  "fair") was built, per `compare-one-way-vs-two-way-street-grid-conversion`.
- **The displacement/amplification ratio's denominator should be stated precisely**
  (pure cut-through reduction vs. total interior veh-km change) — the two can differ
  materially for an intervention whose interior reduction is partly offset by another
  interior-traffic class's increase.
- **Only some outcome measures flip under an elastic-demand evaporation test** — check
  each measure's own crossover elasticity separately rather than assuming evaporation
  either resolves or doesn't resolve the whole comparison uniformly.

## Related

- `create-grid-network` — the base Manhattan-grid construction technique this skill's
  hand-authored (not `netgenerate`) interior grid departs from, for the same reasons
  `compare-one-way-vs-two-way-street-grid-conversion` gives for needing hand-authored
  connections.
- `compare-one-way-vs-two-way-street-grid-conversion` — the hand-authored one-way-cell
  construction and the naive-vs-fair conversion distinction this skill's variant E
  directly reuses; also the source of the route-circuity through-vs-local-access
  decomposition this skill's equity metric is modeled on.
- `compute-dynamic-user-equilibrium` — the `duaIterate.py` mechanics and dual-cost
  Wardrop check this skill's per-variant DUE methodology builds on, extended here with
  the tail-window/tail-median resolution for a near-indifferent equilibrium set.
- `model-vclass-lane-permissions` — the plain-XML permission-editing mechanism this
  skill's modal-filter variant is built from.
- `model-cordon-tolling-with-generalized-cost-surcharge` — the TraCI perceived-cost/
  generalized-cost-feedback mechanism this skill's elastic-demand evaporation test
  reuses.
- `validate-congested-scenario-results-against-teleport-artifacts` — the
  `--time-to-teleport`-vs-longest-red-phase check applied to this skill's signal plan.
- `quantify-sumo-run-to-run-variability` — the CRN/replication discipline layered on
  top of the DUE tail-window resolution (seed variance and DUE-plateau variance are
  reported as two distinct sources of uncertainty, not conflated).
- [[neighborhood-traffic-calming-displacement-and-evaporation]] — the verified
  displacement-with-amplification finding, the partial elastic-demand crossover, the
  Braess-flavored modal-filter speedup, the resident-bears-the-cost equity finding, and
  the selective-vs-universal access-cost distinction this skill's methodology produced.
