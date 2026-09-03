---
summary: A SUMO roundabout is built from hand-authored plain-XML ring geometry compiled with netconvert --roundabouts.guess, and its yield-at-entry right-of-way must be verified from the compiled net's connection states and junction request/response matrix, not assumed from ring shape; a verified 3-way comparison found roundabouts beat signals at low and high demand but lose at medium demand, and have zero angle conflicts/collisions at every level despite sometimes the highest total conflict count.
keywords:
  - roundabout
  - traffic-circle
  - yield-at-entry
  - right-of-way
  - capacity-comparison
created: 2026-07-23T21:25:42
last_updated: 2026-07-23T21:25:42
sources:
  - "[[episodic-memory/2026-07-23_21-03-11/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_21-03-11/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[abstract-network-generation]]"
  - "[[surrogate-safety-measures]]"
  - "[[actuated-traffic-signals]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[diverging-diamond-interchange-unopposed-lefts]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
related_skills:
  - create-roundabout-network
  - create-single-intersection
  - analyze-intersection-safety-with-ssm
  - measure-roundabout-capacity-and-implement-metering
related_skills_for_graph_view:
  - "[[create-roundabout-network]]"
  - "[[create-single-intersection]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
---

# Roundabout Modeling and Comparison

A roundabout is a genuinely different intersection *control paradigm* from every signal-based approach in memory — there is no signal at all; right-of-way is structural, encoded directly in the network geometry as circulating-traffic priority over entering traffic. `netgenerate` cannot express this ring topology (same limitation that requires plain-XML construction for `create-single-intersection`'s per-arm control), so a roundabout must be hand-authored: node/edge XML compiled with `netconvert`.

## Construction

Four fringe (approach/exit) nodes, four ring nodes on a small circle, one-way ring edges circulating in the traffic-handedness-correct direction (counterclockwise for right-hand traffic), and an explicit `<roundabout nodes="..." edges="..."/>` element in the edge file, compiled with `netconvert --roundabouts.guess true --check-lane-foes.roundabout true`. The explicit element plus the guess flag together are what make SUMO recognize the ring and assign circulating traffic priority — omitting either can leave the network merely ring-*shaped* without the actual right-of-way behavior.

## Verification is not optional — check behavior, not shape

**The single most important step, and the one most likely to be skipped:** a network that looks like a roundabout is not necessarily one. Verify directly from the compiled `.net.xml`:

1. A `<roundabout>` element is present.
2. Every entry connection (approach → ring) carries link state `m` (minor/give-way).
3. Every circulating connection (ring → ring, or ring → exit) carries state `M` (major/priority).
4. At each ring junction, decode the `<request>` elements' `response` bitstrings: the entering link's response must have a `1` bit set against the circulating foe's index (it genuinely yields), while the circulating link's own response stays all-zero (it never yields to anything).

A verified real check found this to hold cleanly: all entry connections `m`, all circulating connections `M`, and every ring junction's request matrix confirming entries yield and circulators never do. See `create-roundabout-network` for a bundled verification script automating all four checks.

## Comparing against signalized and priority alternatives

Building a roundabout, a signalized version, and an uncontrolled priority version of the *same* junction (matching fringe-node/approach-edge naming across all three so identical demand routes on all of them) enables a controlled three-way comparison on both efficiency and safety (see `analyze-intersection-safety-with-ssm` for the safety-device setup).

## Verified findings

### Efficiency: the crossover is non-monotonic, not a simple ranking

Across three demand levels (~0.4x/1.0x/1.8x of a nominal flow) on a single-lane-ring roundabout:

- **Low demand**: priority < roundabout < signal (the signal is the *worst* design — imposing delay with no congestion to actually relieve, echoing the general "signals aren't automatically better at light demand" finding also seen with [[actuated-traffic-signals]]).
- **Medium demand**: signal ≪ roundabout < priority — the roundabout's single-lane ring saturates once heavy left-turns load the circle, and the signal's ability to serve movements in discrete, protected phases wins decisively here.
- **High demand**: roundabout < priority < signal — but the signal is the *only* design that served 100% of demand with zero teleports; the roundabout had a small (~2%) throughput deficit, and the priority junction needed teleports (gridlock recovery) to reach full completion.

**There is no universal ranking — the best design depends on where in the demand range the junction actually operates**, and the crossover can be sharp (the roundabout goes from winning at low demand to losing by more than 3x at medium demand). Never generalize a roundabout-vs-signal comparison from a single demand level.

### Safety: fewer-but-milder vs. more-but-severe, not raw conflict count

The roundabout had **zero angle/crossing conflicts and zero collisions at every demand level tested** — its recorded conflicts (via the SSM device) were essentially all mild rear-end/merge encounters from single-lane entry metering. The signalized and priority junctions both logged substantial angle-conflict counts (hundreds to thousands), and the priority junction produced actual simulated collisions (SSM encounter type 111) at high demand. **But the roundabout is not automatically "safest" by every metric** — at higher demand levels it can have a *higher total conflict count* than the alternatives, simply because mild conflicts are much more frequent under ring metering. Raw conflict count is therefore a misleading standalone safety metric; the encounter-type breakdown (following/merging vs. crossing/angle vs. collision — see [[surrogate-safety-measures]]) is what actually distinguishes a genuinely safer design from one that merely logs fewer total events. In the verified comparison, the roundabout and the signal were close on total conflict count at medium demand (roundabout narrowly behind) and the roundabout was clearly highest only at the high demand level — a specific-enough finding that it shouldn't be generalized without checking the actual numbers at whatever demand level is relevant.

See the `create-roundabout-network` skill for the full construction/verification workflow.
