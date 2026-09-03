---
name: simulate-emergency-evacuation
description: Use this skill when the user wants to model an emergency evacuation scenario in SUMO — many-to-boundary egress demand (all trip origins interior, all destinations at network-boundary exits) and compare departure-release strategies (e.g. simultaneous vs. staged/phased) via network clearance-time analysis. Covers classifying interior-vs-fringe edges from the compiled network, constructing matched-route demand variants that differ only in departure schedule, and computing/plotting clearance-time curves, peak in-network accumulation, and travel-time metrics. Trigger on mentions of evacuation, clearance time, egress, staged release, or many-to-boundary demand.
related_skills:
  - create-grid-network
  - generate-random-trips
  - convert-trips-to-routes
  - analyze-simulation-outputs
  - visualize-trajectories-and-timeseries
  - characterize-pedestrian-flow-and-striping-model-artifacts
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[analyze-simulation-outputs]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
related_pages:
  - "[[evacuation-clearance-time-analysis]]"
---

# Simulate Emergency Evacuation

Models an emergency evacuation scenario in SUMO: a many-to-boundary egress demand pattern (every trip originates on an interior edge and terminates at a network-boundary exit), used to compare departure-release strategies via network clearance-time analysis. This is SimSkill's only demand pattern that is neither through-traffic, OD-matrix-based, nor turning-ratio-based — every vehicle's destination is "leave the network," not a specific interior point.

## Classifying interior vs. fringe-exit edges

**Verify edge classification against the compiled network, never assume it from grid coordinates or node naming.** A fringe node has exactly one distinct neighbor (a dead-end stub at the map boundary — with `netgenerate --grid.attach-length`, these are the outward attach edges). A fringe *exit* edge is any edge whose `to`-node is a fringe node — reaching it means leaving the network, making it a valid evacuation destination. An interior *origin* edge is any edge that isn't a fringe-exit edge and whose `from`-node isn't a fringe node — a genuine in-grid street segment, valid as an evacuation origin. (An edge whose `from`-node is fringe but `to`-node isn't is an *inbound* stub bringing traffic in — exclude it from both sets.)

```bash
python scripts/classify_evacuation_edges.py --net grid.net.xml --out-dir demand/ --n-zones 3
```

Writes `randomTrips.py`-compatible weight files restricting trip origins to interior edges and destinations to fringe-exit edges, plus a concentric-zone assignment (by distance from the network's geometric center) for staged release.

## Constructing matched-route demand variants

Generate one pool of interior-origin/fringe-destination trips via `randomTrips.py` with `--weights-prefix` pointing at the classification script's weight files, route with `duarouter`, and verify **zero constraint violations** (every vehicle's first edge is interior, last edge is fringe-exit) directly from the route file before proceeding. Build multiple release-strategy variants that share **identical routes** — the same vehicle IDs and edge-sequences — differing *only* in departure time, so any difference in outcome is attributable purely to the release schedule:

- **Simultaneous**: all departures within a short window (e.g. uniform over 0-300s).
- **Staged/phased**: partition vehicles by their origin edge's concentric zone (from the classification manifest) and offset each zone's departure window in sequence (e.g. outer zone first, since it's closest to exits, then progressively inner zones), spreading total departures over a longer window.

Verify the variants genuinely share identical routes (diff the edge-sequences for every vehicle ID) before trusting a release-strategy comparison — any accidental route difference would confound the result.

## Computing clearance-time and peak-accumulation metrics

```bash
python scripts/analyze_clearance.py \
    --run "Simultaneous (0-300s)=runs/simultaneous" \
    --run "Staged (0-900s, 3 zones)=runs/staged" \
    --out-json metrics.json --out-plot clearance_comparison.png
```

- **Clearance time** at a given percentile (e.g. 90%/95%/100%) is the sorted `arrival` time of the corresponding tripinfo record — the simulation time by which that fraction of vehicles has reached its exit and left the network.
- **Peak in-network accumulation** is the maximum value of `summary.xml`'s `running` attribute across all steps — read directly, not estimated from throughput.
- Compare mean travel time and mean depart-delay too: a saturated network can force vehicles to queue at insertion before they even depart, inflating depart-delay independently of in-network travel time.

Produces two panels: the cumulative-clearance curve (with 90/95/100% markers) and the in-network-accumulation-over-time curve, overlaid across all compared strategies.

## What a staged-vs-simultaneous comparison tends to show

Measured on a 5x5 grid (2000 evacuating vehicles, 20 fringe exits): simultaneous release (0-300s departure window) drove peak in-network accumulation to over 1500 vehicles converging on the exits, overwhelming the priority-junction merges — hundreds of teleports and hundreds of seconds of mean depart-delay from insertion saturation, with total clearance not reached until nearly an order of magnitude past the departure window's end. Staged release (three concentric zones spread over a 3x-longer departure window) roughly halved peak accumulation, kept exits flowing, and cleared the network over **2x faster overall** despite the longer departure spread — the flow benefit of avoiding exit gridlock far outweighed the cost of releasing the last vehicles later. When reporting this kind of comparison, always note the departure-window asymmetry (e.g. 300s vs. 900s) explicitly as context for interpreting the total clearance-time comparison, rather than letting it go unstated.

## Gotchas

- **Verify edge classification from the compiled network, not assumed grid geometry** — a fringe node's neighbor count is the reliable signal, not node-id naming conventions.
- **Confirm demand variants share identical routes before comparing release strategies** — any route difference confounds the comparison.
- **`summary.xml`'s cumulative fields (e.g. `teleports`) are running totals across the whole simulation, not per-step deltas** — read the last value, never sum across steps (a previously-established SimSkill gotcha that reapplies here).
- **A saturated network can inflate depart-delay independently of in-network travel time** — report both, since a vehicle stuck queuing to even insert isn't the same failure mode as one stuck in traffic after departing.

## Related

- `create-grid-network` — for building the base network this scenario's edge classification operates on.
- `generate-random-trips`, `convert-trips-to-routes` — the demand-generation/routing skills this one specializes with interior/fringe weight constraints.
- `analyze-simulation-outputs`, `visualize-trajectories-and-timeseries` — general analysis/plotting skills this one specializes for the clearance-curve/peak-accumulation case.
- [[evacuation-clearance-time-analysis]] — the underlying edge-classification method, clearance-curve construction technique, and the verified staging-vs-simultaneous-release finding.
- `characterize-pedestrian-flow-and-striping-model-artifacts` — extends this skill's clearance-time/peak-accumulation analysis to a genuinely pedestrian (not vehicle) egress scenario, and found that widening a sidewalk bottleneck often just relocates the queue to a downstream signalized crossing rather than reducing total clearance time.
