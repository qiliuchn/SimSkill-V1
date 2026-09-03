---
summary: An emergency evacuation demand pattern (interior-origin, boundary-exit-destination) is verified via fringe-node neighbor-count classification against the compiled network, and departure-release strategies are compared via network clearance-time curves and peak in-network accumulation; a verified staged-release comparison found ~2x faster overall clearance than simultaneous release despite a 3x-longer departure window, driven by avoiding exit-junction gridlock.
keywords:
  - emergency-evacuation
  - clearance-time
  - egress-demand
  - staged-release
  - peak-accumulation
created: 2026-07-26T09:55:00
last_updated: 2026-07-26T09:55:00
sources:
  - "[[episodic-memory/2026-07-26_09-39-03/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-26_09-39-03/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[random-trips]]"
  - "[[duarouter]]"
  - "[[sumo-output-files]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
related_skills:
  - simulate-emergency-evacuation
  - create-grid-network
  - generate-random-trips
  - analyze-simulation-outputs
  - characterize-pedestrian-flow-and-striping-model-artifacts
related_skills_for_graph_view:
  - "[[simulate-emergency-evacuation]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[analyze-simulation-outputs]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
---

# Evacuation and Clearance-Time Analysis

An emergency evacuation demand pattern is a genuinely distinct paradigm from every OD-matrix, turning-ratio, or through-traffic demand method: every trip originates on an *interior* network edge and terminates at a network-*boundary* exit — many-to-boundary egress, not point-to-point travel. Clearance-time analysis is the corresponding post-processing question: given this demand, how quickly does the network empty, and how does the answer depend on the departure-release schedule?

## Classifying interior vs. fringe-exit edges

Edge classification must be verified against the compiled network, not assumed from grid coordinates or node naming conventions. A **fringe node** is one with exactly one distinct neighbor — a dead-end stub at the map boundary (produced, e.g., by `netgenerate --grid.attach-length`). A **fringe exit edge** is any edge whose `to`-node is a fringe node — reaching it means leaving the network, making it a valid evacuation destination. An **interior origin edge** is any edge that isn't a fringe-exit edge and whose `from`-node isn't fringe — a genuine in-grid street segment. An edge whose `from`-node is fringe but `to`-node isn't is an inbound stub (brings traffic in) and belongs to neither set.

## Constructing release-strategy variants with identical routes

To isolate the effect of a departure-release *schedule* (as opposed to route choice), build demand variants that share identical vehicle routes — same origin, destination, and path for every vehicle — differing *only* in departure time. This requires generating one route pool and producing multiple `.rou.xml` files that reuse the same routed vehicles' edge sequences with rewritten `depart` attributes only. Verify the variants genuinely have identical routes (not just similar vehicle counts) before trusting any comparison between them — an accidental route difference would confound the release-schedule comparison entirely.

A staged/phased release strategy partitions vehicles into concentric zones by their origin edge's distance from the network's geometric center, releasing outer zones (closest to exits) first and progressively inner zones later, spreading total departures over a longer window than a simultaneous release.

## Clearance-time and peak-accumulation metrics

- **Clearance time** at a percentile (e.g. 90%/95%/100%) is the sorted `arrival` time from `tripinfo` at which that fraction of vehicles has reached its destination — the standard cumulative clearance curve used in evacuation traffic engineering.
- **Peak in-network accumulation** is the maximum value of `summary.xml`'s `running` attribute across the simulation — read directly rather than estimated, since it's the number of vehicles simultaneously present, the quantity that determines whether exit junctions gridlock.
- **Depart delay** (from insertion queuing) should be reported alongside in-network travel time — a heavily saturated network can force vehicles to wait to even enter the simulation, a distinct failure mode from being stuck in traffic after departing.

## Measured finding: staged release beats simultaneous, driven by peak-load reduction

On a 5x5 grid with 2000 evacuating vehicles and 20 fringe exits: simultaneous release (departures uniform over a 300s window) drove peak in-network accumulation to over 1500 vehicles converging on the 20 exits, overwhelming the priority-junction merges — hundreds of teleports and several hundred seconds of mean depart-delay from insertion-queue saturation, with full network clearance not reached until nearly an order of magnitude past the departure window's own end. Staged release (three concentric zones spread over a 900s window, roughly 3x longer) roughly halved peak accumulation, kept the exit junctions flowing, and cleared the network overall about 2x faster than simultaneous release despite the longer departure spread — the flow benefit of avoiding exit gridlock substantially outweighed the cost of releasing the last vehicles later. This is a genuine capacity/gridlock effect, verified from real teleport counts and depart-delay figures, not merely an artifact of how "clearance time" is defined; any report of such a comparison should still explicitly note the departure-window asymmetry (e.g. 300s vs. 900s) as context for interpreting the total-clearance-time result.

## Gotcha (reapplied from prior findings)

`summary.xml`'s cumulative fields (e.g. `teleports`) are running totals across the whole simulation, not per-step deltas — always read the last value, never sum across steps, when computing a total teleport count for a run.

See the `simulate-emergency-evacuation` skill for the full edge-classification, demand-construction, and clearance-analysis workflow with bundled scripts.
