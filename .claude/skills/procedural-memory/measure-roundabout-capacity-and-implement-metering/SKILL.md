---
name: measure-roundabout-capacity-and-implement-metering
description: Use this skill when the user wants to treat a SUMO roundabout as a capacity-and-control problem rather than just a geometry — measuring the HCM-style entry-capacity-vs-circulating-flow law, comparing single-lane/two-lane/turbo ring designs, diagnosing an unbalanced-demand approach-starvation failure mode, or implementing roundabout METERING (a part-time signal on the dominant entry that throttles it to create gaps for a starved minor approach). Covers the 8-ring-node geometry required to separate circulating from exiting flow, proving turbo ring lane-change prohibition from the compiled net, fitting and comparing an entry-capacity curve against HCM's c=1130*exp(-0.001*v_c), building an equity-aware starvation diagnostic, and a TraCI-based metering controller (since SUMO's native actuated logic and custom-detector binding cannot express a detector on one approach driving a signal on another). Trigger on mentions of roundabout capacity, roundabout metering, turbo roundabout, gap acceptance, circulating flow, entry capacity, or roundabout starvation/equity.
---

# Measure Roundabout Capacity and Implement Metering

Extends `create-roundabout-network`'s basic ring-construction/verification skill into a
quantitative capacity-and-control study: fitting SUMO's own gap-acceptance-driven entry
capacity against the HCM roundabout capacity model, diagnosing when unbalanced demand
starves one approach even though aggregate metrics look fine, and building a TraCI
controller that deliberately throttles a roundabout's dominant entry to relieve a
starved one.

## Geometry: eight ring nodes, not four

`create-roundabout-network`'s bundled template uses one ring node per arm, where
entering and exiting traffic share a junction. **That is insufficient for capacity
work**: the HCM entry-capacity law is defined against the circulating flow passing
*in front of* the entry, and with a shared entry/exit node, circulating flow cannot be
separated from exiting flow, either in the conflict structure or by a detector.

Use **two ring nodes per arm** — an exit node `xX` positioned upstream of an entry
node `eX` (e.g. exit at `arm_angle - 22.5deg`, entry at `arm_angle + 22.5deg` on a
regular octagon). The short ring segment between the two carries exactly the
conflicting flow for that arm's entry, and a single detector on it measures
circulating flow `v_c` directly. Compile the same way as the basic skill
(`netconvert --roundabouts.guess true --check-lane-foes.roundabout true`); `netgenerate`
still cannot express a ring.

Build every variant under comparison (single-lane, two-lane, turbo, signalized
reference) from the **same** node positions, approach lengths, and speeds so the only
degrees of freedom are lane count and control type — expect the roundabout variants'
approach lengths to differ slightly from a signalized reference's if the roundabout
approach stops at the ring while the signalized approach runs to a center node; report
this rather than treating it as a defect.

## Turbo lane-change prohibition: prove it, don't just draw it

SUMO permits weaving on a two-lane ring by default. A turbo roundabout's defining
discipline — drivers commit to a lane before entering and cannot change lanes on the
circulatory roadway — must be enforced explicitly and then proven from the compiled
net, not assumed from the network's visual layout.

**`changeLeft="none"`/`changeLeft=""` are NOT valid netconvert connection attributes**
— `changeLeft`/`changeRight` take a **list of permitted vehicle classes**, and
`netconvert` rejects both `none` (parsed as an unknown vehicle class) and the empty
string. Write the prohibition as `changeLeft="authority" changeRight="authority"` on
every circulatory lane instead (only emergency-authority vehicles may weave; the
ordinary fleet cannot).

Prove it two ways:
1. **Structural**: grep the compiled `turbo.net.xml` for these attributes on every
   circulatory lane, and confirm the otherwise-identical two-lane variant has none (a
   negative control confirming the attribute is genuinely doing the work).
2. **Behavioral**: run identical demand/seed on both variants with
   `--lanechange-output`, and confirm ring-edge lane changes collapse to exactly zero
   on the turbo variant while staying substantial on the conventional one — and check
   a **negative control** on the approach edges (unrestricted in both variants):
   nonzero lane-change counts there in both variants confirm the prohibition is scoped
   to the circulatory roadway specifically, not a global lane-changing suppression.

**Also verify the two variants' junction foe/response matrices are byte-identical**
(same connection states, same request rows) before attributing any measured difference
to the lane-change prohibition alone — this rules out the prohibition having silently
altered the conflict topology too.

**Know the limitation of a 4-arm 2-lane "turbo" in SUMO.** A genuine turbo roundabout
removes the inner-lane-exit-vs-outer-lane-through crossing conflict by dropping the
outer lane at each exit (a 3-lane turbo block); this cannot be expressed on a 4-arm
2-lane ring that must still serve a third exit. If `netconvert` flags the inner-lane
exit connection as a minor (`m`) link identically in both the turbo and conventional
two-lane variants, the conflict-point topology is genuinely identical between them —
so "turbo reduces conflict points" is not a testable claim on this geometry. What *is*
testable is narrower and should be stated as such: whether removing ring weaving alone
changes measured conflicts, holding topology fixed.

## Measuring the entry-capacity vs circulating-flow law

Hold circulating flow at a ladder of fixed levels (via a dedicated circulating-stream
route occupying the ring segment in front of the entry under test) while a separate
subject entry is deliberately oversaturated; measure the subject entry's actual
discharge from a detector, and plot discharge against the **measured** circulating
flow on the segment (not the requested/nominal value — insertion and downstream
effects can make them differ).

**Critical rig requirement: the circulating stream must use Poisson (negative-
exponential) headways, not `vehsPerHour`'s equally-spaced arrivals.** A deterministic,
equally-spaced circulating stream with a constant headway sitting just below the
entering vehicle's critical gap can nearly fully block the entry, producing a
severely deflated "capacity" that is a rig artifact, not roundabout physics — HCM's
own gap-acceptance model assumes random arrivals, so an equally-spaced circulating
stream is not a fair comparison basis. Use `period="exp(rate)"` for every circulating
flow definition.

Fit the resulting capacity-vs-v_c curve to an exponential decay form
(`c = A * exp(-B * v_c)`) via log-space linear regression, and report the fitted `A`
(free-flow capacity ceiling) and `B` (decay rate) with a goodness-of-fit statistic.
**Compare against HCM's single-lane form `c = 1130 * exp(-0.001 * v_c)` by computing
the SUMO/HCM ratio across the swept range, not just at one point** — the comparison
can be non-uniform (optimistic at low circulating flow, pessimistic at high
circulating flow, with a crossover point in between), and reporting only a single
"SUMO is optimistic" or "SUMO is pessimistic" verdict can be actively misleading.
Decompose *why* the curves differ into a **level** effect (a saturation-flow/discharge-
rate difference — check whether it matches the same discharge-rate overshoot found
independently by `measure-saturation-flow-and-validate-webster-method` at a signalized
stop line) and a **decay-rate** effect (a genuine gap-acceptance-model difference, from
SUMO's minor-link entry criterion vs. HCM's implicit critical gap) — these are
different mechanisms and can have different remedies.

**Identify which SUMO parameter controls which part of the curve** via one-at-a-time
sensitivity variants, refitting the curve each time. In one tested case, a
*driver/junction* parameter (`impatience`) controlled the curve's **level** far more
than any car-following parameter, while `tau` (not the more obvious junction-specific
gap parameter) controlled the **decay rate**, and no single tested parameter could
bring the decay rate fully into HCM's range — meaning matching HCM's roundabout
capacity curve exactly may require a different gap-acceptance model, not a parameter
tweak. Don't assume the "obvious" junction-model gap parameter is the most powerful
lever — check systematically.

## Two-lane capacity as a multiple of single-lane

Report **two different framings explicitly, since they answer different questions**:
1. **At matched (typically zero) circulating flow**: measures whether a two-lane entry
   is "worth" two single-lane entries. Expect a shortfall below 2.0x, from (a) a real
   yield relationship where the inner ring lane's exit connection is a genuine minor
   link crossing the outer lane's through movement (verify this from the compiled net,
   not assumed), and (b) lane-utilization imbalance.
2. **At matched total circulating flow**: measures the benefit of spreading a fixed
   total circulating volume over two lanes so each entry lane faces roughly half the
   conflicting flow — this framing can show the multiple *exceeding* 2.0x and *rising*
   with circulating flow, which is a genuinely different (and equally real) effect from
   framing 1. Reporting only one framing is misleading.

**Lane utilization on a multi-lane entry is not automatic — verify it.** With SUMO's
default `departLane` policies (`best`/`free`/`random`), entering traffic can
concentrate heavily on one lane, making a nominally two-lane entry's measured capacity
barely exceed a single-lane one's. Force an explicit destination-based lane assignment
(e.g. right-turning traffic to the outer lane, left-turning to the inner) and confirm
`lcKeepRight` is or isn't the cause before assuming a lane-utilization fix is needed —
in one tested case it was not.

## Diagnosing unbalanced-demand starvation

**A symmetric two-way major-axis demand pattern does not starve a minor entry on a
single-lane ring.** The mechanism: with a two-way major axis, the dominant entry's own
conflicting stream is fed by the *opposing* major direction, so the dominant entry is
itself gap-limited and structurally cannot deliver enough flow onto the ring to starve
anyone. **The pattern that genuinely starves a minor entry is one-way peak-direction
dominance** — construct demand so one entry's circulating conflict stays low (feeds
mostly from movements that don't burden it) while the flow it dumps onto the ring in
front of a minor entry grows essentially unbounded with total demand.

Report **per-approach** throughput and delay, not just the network mean — an unbalanced
starvation failure is specifically the kind of result that a network-mean statistic
hides: the starved approach can show ratio-of-tens delay increases while the aggregate
mean looks entirely acceptable. Report an explicit equity statistic (max/min
approach-delay ratio, or a Gini coefficient across approaches) alongside the per-
approach breakdown.

**Cross-check the starvation threshold against the independently measured entry-
capacity law** — if you've already fit the entry-capacity-vs-circulating-flow curve,
the demand level at which starvation begins should be close to where that curve's
predicted capacity at the starved approach's actual circulating flow crosses the
starved approach's own demand. Agreement between these two independently-derived
numbers is strong evidence both measurements are capturing the same real phenomenon,
not artifacts of either rig.

**Starvation can be non-monotone in demand — check the full range, don't stop at the
worst-looking point.** Beyond a high enough total-demand level, the *dominant* entry
can itself saturate and cap the amount of circulating flow it delivers, which
paradoxically lets the previously-starved minor approach's delay fall back down even
as the junction as a whole gets much worse. **A single scalar equity statistic can
mask this reversal or even keep climbing while its meaning flips** (the "worst-off"
approach at high demand can become the *dominant* one, not the minor one) — always
report the per-approach breakdown alongside any aggregate equity number, especially
across a wide demand sweep.

## Implementing roundabout metering

**Roundabout metering means throttling the DOMINANT entry to relieve a DIFFERENT,
starved entry — this wiring cannot be expressed by SUMO's native actuated-signal
logic or its `<param key="<laneID>" value="<detID>"/>` custom-detector binding** (see
`design-actuated-signal-detector-placement-and-fault-tolerance`), both of which drive
a signal's own extension logic from a detector on that signal's *own* approach.
Metering needs a detector on one approach controlling a signal on a structurally
different approach — build this via **TraCI**: a small polling loop that reads a
queue/occupancy detector on the starved approach, and switches a one-link
`traffic_light` on the dominant approach between an idle (permanently green) state and
an active metering cycle (e.g. yellow -> red -> green, sized to create periodic gaps)
based on a threshold with hysteresis (a deadband between the activation and
deactivation thresholds prevents rapid on/off chattering).

**Isolate the metering effect from the geometry change of adding a signal node at
all**: run the "unmetered control" on the *identical* network with the metering
signal's phase held permanently green, not on a plain roundabout without the signal
node — otherwise any measured effect conflates metering with the minor geometry change
of splitting the approach edge.

**Sweep both the activation threshold and the metering red/green split** — there is a
real over-metering failure mode where too aggressive a duty cycle cuts the starved
approach's delay dramatically while driving the *dominant* approach's delay far worse
and making the junction as a whole worse off than doing nothing. Identify the Pareto
frontier and a reasonable automatic selection rule (e.g. lowest starved-approach delay
among configs that don't significantly worsen junction throughput) rather than picking
one configuration by inspection.

**Report which demand range makes metering a genuine net win versus only a
one-sided transfer, and check statistical significance at every rung, not just the
point estimate.** A metering benefit can look like a "net win" (both the starved
approach and the junction as a whole improve) in a point-estimate table while the
junction-wide improvement's confidence interval spans zero at the highest tested
demand — report the paired CI at every demand level and qualify any "net win" claim
whose CI isn't clearly on one side of zero. Expect metering to do the most good near
the starvation threshold itself and to increasingly become a one-sided transfer
(helping the starved approach at the junction's expense) as demand climbs further
above it — and to have no effect at all, without harm, below the threshold where it
never triggers.

## Gotchas

- **A 4-node-per-arm roundabout ring cannot separate circulating from exiting flow** —
  use 8 nodes (a distinct exit node upstream of the entry node per arm) for any
  capacity-law measurement.
- **`changeLeft="none"`/`""` are invalid netconvert connection attributes** — use
  `changeLeft="authority" changeRight="authority"` to forbid lane changing on specific
  lanes, and always include a negative control (an unrestricted lane/edge with nonzero
  lane changes) to prove the restriction is scoped correctly.
- **`vehsPerHour`'s equally-spaced arrivals can nearly block an entry outright** when
  used for a circulating stream in a gap-acceptance measurement — always use
  `period="exp(rate)"` for circulating flows in a capacity rig.
- **Multi-lane entry capacity without an explicit `departLane` policy can understate
  true capacity substantially** — SUMO's default lane-choice heuristics can concentrate
  entering traffic on one lane.
- **A genuine turbo roundabout's conflict-point reduction cannot be tested on a 4-arm
  2-lane ring** — the inner-lane-exit crossing conflict persists identically whether or
  not ring weaving is forbidden, so only "does forbidding weaving change measured
  conflicts" is a testable question on this geometry, not "does turbo have fewer
  conflict points."
- **A symmetric two-way major-axis demand pattern will NOT reproduce roundabout
  starvation** — the starving pattern specifically requires one-way peak-direction
  dominance; don't assume any "unbalanced" demand pattern will do.
- **Starvation and its equity statistics can be non-monotone in demand** — sweep past
  the worst-looking point to check for a reversal, and always report the per-approach
  breakdown alongside any single equity number.
- **Roundabout metering (one approach's detector driving another approach's signal)
  needs TraCI** — neither native actuated logic nor custom-detector `<param>` binding
  can express this wiring.
- **A "net win" metering claim needs the paired confidence interval checked at every
  demand rung**, not just the point estimate — the junction-wide component of a net
  win can lose significance at higher demand even while the starved-approach component
  remains clearly significant.

## Related

- `create-roundabout-network` — the base ring-construction and yield-at-entry
  verification technique this skill extends with the 8-ring-node capacity-measurement
  geometry.
- `compare-unsignalized-intersection-control-types` — the shared-geometry-multiple-
  variants comparison pattern and loaded/inserted/arrived throughput discipline this
  skill's 4-5-way comparison reuses.
- `control-signals-with-actuated-tls` / `design-actuated-signal-detector-placement-and-fault-tolerance` — the signal/detector mechanics this skill's metering controller builds on, and the specific limitation (own-approach-only binding) that forces the metering controller to use TraCI instead.
- `measure-saturation-flow-and-validate-webster-method` — the measured (not assumed)
  discharge-rate methodology this skill's Webster-sized signalized reference and
  capacity-law level-offset diagnosis both depend on.
- `analyze-intersection-safety-with-ssm` — SSM device setup for the safety comparison
  across variants.
- `quantify-sumo-run-to-run-variability` / `validate-congested-scenario-results-against-teleport-artifacts` — the CRN and teleport-artifact validity disciplines applied throughout the 5-6-way comparison.
- [[roundabout-modeling-and-comparison]] — the prior basic roundabout-vs-signal-vs-priority comparison this skill's variant set extends with capacity, equity, and metering dimensions.
- [[roundabout-capacity-law-and-demand-metering]] — the verified SUMO-vs-HCM capacity-law comparison, the two-lane multiple finding, the starvation threshold and its reversal, the metering net-win range, and the turbo safety counter-finding this skill's methodology produced.
