---
name: create-roundabout-network
description: Use this skill when the user wants to build a roundabout intersection in SUMO — a circulating ring junction where entering traffic yields to circulating traffic, as opposed to a signalized or priority-controlled junction. Covers authoring the ring geometry in plain XML (netgenerate cannot express it), netconvert's roundabout recognition, and — critically — verifying the yield-at-entry right-of-way actually took effect rather than just checking the ring's visual shape. Also covers comparing a roundabout against signalized/priority versions of the same junction on efficiency and safety. Trigger on mentions of roundabout, traffic circle, circulating intersection, or yield-at-entry right-of-way.
---

# Create a Roundabout Network

Builds a compact single-junction roundabout in SUMO — a circulating ring where entering traffic must yield to traffic already on the ring — via hand-authored plain XML compiled with `netconvert`, since `netgenerate` cannot express this asymmetric ring topology (same reasoning `create-single-intersection` uses for per-arm control). This is SimSkill's only skill covering a genuinely different intersection *control paradigm* from every signal-based approach (`optimize-signals-by-tlscycleadaptation`, `control-signals-with-actuated-tls`, `implement-maxpressure-traci-controller`, etc.) — a roundabout has no signal at all; right-of-way is structural, encoded in the network geometry itself.

## Geometry

Four fringe (approach/exit) nodes, four ring nodes on a small circle, one-way ring edges circulating in the traffic-handedness-correct direction (counterclockwise for right-hand traffic), plus an explicit `<roundabout>` element:

```xml
<!-- .nod.xml -->
<node id="N" x="0" y="150" type="priority"/>  <!-- ...E, S, W similarly -->
<node id="rN" x="0" y="22" type="priority"/>  <!-- ring nodes, ...rE, rS, rW -->
```

```xml
<!-- .edg.xml -->
<edge id="in_N"  from="N"  to="rN" numLanes="2" speed="13.89" priority="1"/>
<edge id="out_N" from="rN" to="N"  numLanes="2" speed="13.89" priority="1"/>
<edge id="ring_N" from="rN" to="rW" numLanes="1" speed="8.33" priority="3"/>  <!-- one-way, circulating -->
<roundabout nodes="rN rW rS rE" edges="ring_N ring_W ring_S ring_E"/>
```

Compile with `netconvert --roundabouts.guess true` (plus `--check-lane-foes.roundabout true` for correct multi-lane ring foe handling) — the explicit `<roundabout>` element combined with this flag is what makes SUMO recognize the ring and assign circulating-priority right-of-way, rather than treating it as an ordinary set of one-way streets.

**Match the fringe node names and approach edge ids to whatever other network-creation skills use for the same conceptual junction** (e.g. `create-single-intersection`'s `N`/`E`/`S`/`W` fringe nodes, `in_X`/`out_X` edges) — this lets the *same* demand file route identically on a roundabout, a signalized, and a priority-controlled version of the "same" junction, which is the natural comparison this skill exists to enable.

## Verify right-of-way behaviorally, not just by shape

**A ring-shaped network that wasn't actually recognized as a roundabout has no special right-of-way at all** — it would just be an ordinary set of one-way streets with default priority rules, which may or may not give entering traffic the correct yield behavior. Never assume correctness from the geometry; check the compiled `.net.xml` directly:

1. A `<roundabout nodes="..." edges="..."/>` element exists.
2. Every entry connection (`in_X` → a ring edge) has link state `m` (minor/give-way).
3. Every circulating connection (ring → ring, or ring → `out_X`) has state `M` (major/priority).
4. At each ring junction, decode the `<request>` elements' `response` bitstrings: an entering link's response should have a `1` bit set against the circulating foe link's index (entry yields to circulator), while the circulating link's own response is all zeros (it never yields to anything).

`scripts/verify_roundabout.py` automates all four checks. Run it on every roundabout network before trusting it in a comparison — this is the single most important verification step in the whole skill.

## Comparing against signalized / priority versions of the same junction

Build all three variants sharing identical fringe-node/approach-edge naming (roundabout via this skill, signalized/priority via `create-single-intersection` with `--junction-type traffic_light`/`priority`), generate one demand set, and route it identically onto all three. Enable the SSM device (see `analyze-intersection-safety-with-ssm`) for the safety half of the comparison, and use `analyze-simulation-outputs`-style tripinfo parsing for the efficiency half.

## What comparisons tend to show

Verified across three demand levels on a single-lane-ring roundabout vs. signalized vs. priority:

- **Efficiency is non-monotonic — there is no single "best" design across all demand levels.** The roundabout won on delay at both **low** and **high** demand but **lost badly at medium demand**, where a single-lane ring saturates once heavy left-turns load the circle. The signal was the worst design at low demand (delay imposed with nothing to relieve — echoing the general "signals aren't automatically better at light demand" finding) but the *only* design serving 100% of demand at high load with zero teleports. A bare priority junction won at low demand but needed gridlock-recovery teleports to clear high demand. **Don't assume roundabouts dominate signals across the board — test the actual demand range, since the crossover can be sharply non-monotonic.**
- **Safety: fewer-but-milder vs. more-but-severe is the right framing, not raw conflict count.** The roundabout had **zero angle/crossing conflicts and zero collisions at every demand level tested** — its conflicts were essentially all mild rear-end/merge events from single-lane entry metering. The signalized and priority junctions both logged substantial angle-conflict counts, and the priority junction produced actual simulated collisions at high demand. **But the roundabout can have a *higher total conflict count*** at some demand levels (mild conflicts are simply more frequent) — raw conflict count alone is a misleading safety metric; always break conflicts down by encounter type (see [[surrogate-safety-measures]]'s type-code classification) rather than comparing totals.

## Gotchas

- **`netgenerate` cannot build a custom roundabout ring** — it has no ring topology mode; use plain-XML + `netconvert`, same as `create-single-intersection`.
- **A ring-shaped geometry is not automatically a roundabout.** Verify link states and request/response matrices, not just that the network looks like a circle.
- **Circulating-edge speed should typically be lower than approach speed** (traffic slows through the ring) — a common realistic parameter, not required for correctness but affects the delay comparison.
- **Match fringe/approach naming across variants** or the "same demand on all three variants" comparison won't actually be apples-to-apples.

## Related

- `create-single-intersection` — the plain-XML+netconvert technique this skill's ring construction is adapted from, and the source of the signalized/priority comparison variants.
- `analyze-intersection-safety-with-ssm` — the SSM device and conflict-classification technique used for the safety half of a roundabout comparison.
- `analyze-simulation-outputs` — the efficiency-side metrics (waiting time, time loss, throughput) for the other half.
- [[roundabout-modeling-and-comparison]] — the underlying construction/verification technique and the verified capacity-crossover and safety trade-off findings.
- `measure-roundabout-capacity-and-implement-metering` — extends this skill's ring geometry to 8 ring nodes per ring (a distinct exit and entry node per arm) to separate circulating from exiting flow for capacity-law measurement, and adds turbo/metering variants on top of this skill's base construction/verification workflow.
