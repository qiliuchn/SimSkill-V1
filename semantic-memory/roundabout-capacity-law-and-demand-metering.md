---
summary: SUMO's default gap-acceptance entry-capacity curve is neither uniformly optimistic nor pessimistic versus the HCM roundabout capacity formula — it over-predicts at low circulating flow and under-predicts at high circulating flow because its decay rate runs roughly 2.4x steeper — two-lane entries deliver only ~1.8x (not 2.0x) of single-lane capacity, unbalanced one-way-dominant demand starves a minor entry at a threshold that matches the independently measured capacity curve and then non-monotonically reverses at higher demand, and metering the dominant entry with a part-time signal is a statistically significant net win in a specific demand window just above the starvation threshold.
keywords:
  - roundabout-capacity
  - gap-acceptance
  - hcm-roundabout-formula
  - circulating-flow
  - roundabout-metering
  - turbo-roundabout
  - approach-starvation
  - equity
created: 2026-08-02T00:00:00
last_updated: 2026-08-05T19:00:00
sources:
  - "[[episodic-memory/2026-08-01_18-00-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_18-00-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[roundabout-modeling-and-comparison]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[webster-method]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[surrogate-safety-measures]]"
  - "[[demand-arrival-process-and-unsignalized-capacity]]"
related_skills:
  - measure-roundabout-capacity-and-implement-metering
  - create-roundabout-network
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - measure-saturation-flow-and-validate-webster-method
  - model-demand-arrival-process-and-its-effect-on-capacity-and-delay
related_skills_for_graph_view:
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[create-roundabout-network]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[model-demand-arrival-process-and-its-effect-on-capacity-and-delay]]"
---

# Roundabout Capacity Law and Demand Metering

Extends the basic roundabout-vs-signal comparison in [[roundabout-modeling-and-comparison]]
into a quantitative capacity-and-control study: how well does SUMO's gap-acceptance
behavior reproduce the classic HCM roundabout entry-capacity law, what happens when
demand is genuinely unbalanced across approaches, and can a roundabout be actively
*controlled* (metered) rather than left purely to structural yield-at-entry
right-of-way?

## Verified finding: SUMO's capacity curve is not uniformly optimistic or pessimistic vs. HCM

A directly measured entry-capacity-vs-circulating-flow curve (subject entry
oversaturated, circulating flow held at fixed levels with Poisson arrivals, capacity
fit as an exponential decay `c = A * exp(-B * v_c)`) compared against HCM's canonical
single-lane form `c = 1130 * exp(-0.001 * v_c)` found the comparison is **not a single
verdict**: SUMO was measured to be optimistic (predicting more capacity than HCM) by
up to +59% at low circulating flow, crossing over to pessimistic (predicting less) by
up to -71% at high circulating flow, because SUMO's fitted decay rate ran roughly
**2.4x steeper** than HCM's. Two distinct mechanisms drive this, and they should not
be conflated:

- **The level offset** (SUMO's higher free-flow capacity ceiling) is not a
  gap-acceptance effect — it is a **saturation-flow/discharge-rate** effect: SUMO's
  default `passenger` vehicle discharges roughly 30% faster than the textbook/tool
  default assumption, the same effect independently documented for signalized stop
  lines (see `measure-saturation-flow-and-validate-webster-method`). HCM's `c(0)` is a
  calibrated field value that already embeds real driver hesitancy SUMO doesn't model.
- **The steeper decay rate** is a genuine **gap-acceptance-model** difference: SUMO's
  minor-link entry logic requires a gap large enough that no circulating vehicle is
  forced to brake — a stricter criterion than HCM's implicit critical gap.

**Parameter sensitivity separates cleanly along this same line.** Across 15
one-at-a-time parameter variants, a driver/junction parameter (`impatience`) was the
single strongest lever on the capacity curve's **level**, while `tau` (not the more
obviously-relevant junction gap parameter, `jmTimegapMinor`, which was weaker than
both) was the strongest lever on the **decay rate**. No single tested parameter could
bring the decay rate down to HCM's value — matching HCM's roundabout capacity curve
exactly would need a different gap-acceptance model, not a parameter tweak.

## Verified finding: two-lane capacity is ~1.8x, not 2.0x, of single-lane — and the multiple depends on how you ask

At matched (zero) circulating flow, measured two-lane entry capacity was **1.80x**
single-lane capacity, a real ~10% shortfall below the naive 2.0x expectation,
attributable to a genuine yield relationship (the inner ring lane's exit connection
is a true minor link, verified from the compiled network, crossing the outer lane's
continuing through movement — a real conflict of a 4-arm two-lane ring, not a
modeling artifact) plus lane-utilization imbalance. **Multi-lane entry capacity is not
automatically well-utilized**: without an explicit destination-based lane assignment,
SUMO's default lane-choice heuristics can concentrate the large majority of entering
traffic onto one lane, making a nominally two-lane entry's measured capacity barely
exceed a single-lane one's — always verify lane utilization directly rather than
assuming a multi-lane entry's capacity scales with lane count.

**At matched TOTAL circulating flow (rather than matched zero), the multiple instead
exceeds 2.0x and rises with circulating flow** (measured range 2.03x-5.74x) — a
different, equally valid framing reflecting that spreading one fixed total circulating
volume across two lanes lets each entry lane face roughly half the conflicting flow.
Reporting only one of these two framings is misleading; they answer genuinely
different questions ("is a two-lane entry worth two single-lane entries" vs. "what
capacity gain does adding a lane buy at a given total ring load").

## Verified finding: unbalanced one-way demand starves a minor entry, and it reverses

**A symmetric two-way major-axis demand pattern does NOT starve a minor entry** —
measured directly, the dominant two-way approaches instead carried substantially more
delay than the minor ones, because a two-way major axis's own dominant entry is fed by
its opposing direction and is therefore itself gap-limited, unable to ever deliver
enough circulating flow to starve anyone. **The pattern that genuinely starves a minor
entry is one-way peak-direction dominance**, where one entry's own conflicting stream
stays structurally small while the flow it dumps onto the ring in front of a minor
entry grows with total demand.

In a swept one-way-dominant demand pattern, starvation set in sharply at a specific
demand threshold (in the tested condition: dominant-approach demand ~800 veh/h,
dominant-axis demand share ~0.565, circulating flow in front of the starved entry
~740 veh/h) — and this threshold **independently matched** where the separately
measured entry-capacity curve predicted the starved approach's own capacity would
drop below its demand, cross-confirming that the capacity law and the starvation
threshold are the same underlying phenomenon measured two different ways. Aggregate
network-mean delay and throughput looked acceptable throughout — the starved
approach's own delay (in the tested condition: reaching over 4x the network mean) and
an explicit equity statistic (max/min approach-delay ratio, or a Gini coefficient
across approaches) were required to reveal the failure at all.

**Starvation is non-monotone in demand — it can reverse.** Beyond a high enough total
demand, the *dominant* entry itself saturates and caps how much circulating flow it
can deliver, which paradoxically lets the previously-starved minor approach's delay
fall back down even as the junction as a whole gets dramatically worse. A single
equity statistic can keep climbing through this reversal while its meaning silently
flips (the worst-off approach becomes the dominant one, not the minor one) — the
per-approach breakdown, not just an aggregate equity number, is required to correctly
interpret a wide demand sweep.

## Verified finding: metering the dominant entry is a real, statistically-bounded net win in a specific window

A part-time actuated signal placed on only the dominant entry, triggered by a
queue/occupancy detector on the starved approach (implemented via TraCI, since
neither SUMO's native actuated logic nor its custom-detector `<param>` binding can
express a detector on one approach driving a signal on a structurally different
approach), was swept across activation threshold and red/green duty cycle. Metering
produced a genuine, statistically significant improvement to **both** the starved
approach's delay **and** the junction-wide delay/throughput in a demand window just
above the starvation threshold — but the range where the junction-wide component is
independently significant (not just a favorable point estimate) is narrower than the
range where the starved-approach component is significant on its own. Outside that
window, metering increasingly becomes a one-sided transfer: it continues to
substantially cut the starved approach's delay at higher demand, but at the cost of
worse junction-wide delay and throughput, and below the starvation threshold it never
triggers and does no measurable harm. **Over-metering is a real, distinct failure
mode** — too aggressive a duty cycle can cut the starved approach's delay
dramatically while driving the dominant approach's delay far worse, leaving the
junction as a whole worse off than doing nothing.

## Verified finding: a "turbo" ring's reduced conflict points are not testable on a 4-arm 2-lane SUMO geometry — and forbidding weaving alone increased measured conflicts

A true turbo roundabout removes a two-lane ring's inner-lane-exit-vs-outer-lane-through
crossing conflict by dropping the outer lane at each exit (a genuine turbo geometry
needs a 3-lane spiral block), which cannot be expressed on a 4-arm 2-lane ring that
must still serve a third exit — the inner-lane exit connection compiles as a minor
(`m`) link identically in both a conventional two-lane ring and a weaving-forbidden
"turbo" variant, so their conflict-point topology is genuinely identical (confirmed
byte-identical junction foe/response matrices). **Testing only whether forbidding ring
weaving alone changes measured conflicts (holding topology fixed), the weaving-
forbidden variant showed substantially MORE measured crossing conflicts than the
conventional ring** (a 4x increase in one tested condition) — the opposite of the
intuitive expectation. The mechanism: the conventional ring's lane-change model lets
inner-lane vehicles weave out to the outer lane before reaching their exit, avoiding
the inner-exit crossing conflict; forbidding that weaving forces every inner-lane exit
through the crossing link that a weave would otherwise have sidestepped. **This is a
finding about modeling turbo roundabouts on a topology that can't express true spiral
lane-dropping in SUMO — it is explicitly not evidence that real turbo roundabouts
(with the crossing conflict actually engineered out) are less safe than conventional
ones.**

## Practical takeaways

- Build any roundabout capacity-law comparison with 8 ring nodes (a distinct exit and
  entry node per arm), not 4 — otherwise circulating flow cannot be separated from
  exiting flow.
- Always use Poisson (`period="exp(rate)"`), not equally-spaced (`vehsPerHour`),
  arrivals for a circulating stream in a gap-acceptance capacity measurement.
- Report a capacity-law comparison against a reference formula (like HCM's) as a full
  curve-vs-curve comparison across the swept range, decomposed into a level effect and
  a decay-rate effect — a single-point "optimistic" or "pessimistic" verdict can hide
  a crossover.
- Verify multi-lane entry lane utilization explicitly rather than assuming it — and
  report both the matched-zero-flow and matched-total-flow framings of a multi-lane
  capacity multiple, since they answer different questions.
- The starving demand pattern for a roundabout is specifically one-way peak-direction
  dominance, not any generic demand imbalance — and starvation can reverse at high
  enough demand, so sweep past the worst-looking point and always report the
  per-approach breakdown alongside any aggregate equity statistic.
- Roundabout metering (one approach's detector controlling another approach's signal)
  requires a TraCI controller, and any "net win" claim needs its confidence interval
  checked at every demand level, not just its point estimate.
- Don't assume a topological "fewer conflict points" argument about turbo roundabouts
  transfers to a SUMO model that can't express the geometry that actually removes
  those conflict points.

See `measure-roundabout-capacity-and-implement-metering` for the full construction,
measurement, and metering-controller workflow, including the reusable capacity-rig
and TraCI-metering scripts.
