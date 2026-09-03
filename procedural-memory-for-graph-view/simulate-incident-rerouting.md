---
name: simulate-incident-rerouting
description: Use this skill when the user wants to model a mid-simulation incident, work zone, or lane/edge closure in SUMO and quantify how much SUMO's en-route rerouting device mitigates it — a primary route plus a parallel detour, a rerouter that closes a lane/edge for a fixed window, and a baseline (no rerouting device) vs dynamic-rerouting comparison. Covers closingReroute/closingLaneReroute rerouter elements, the device.rerouting.* travel-time-adaptation parameters, and the network-design and comparison-design pitfalls specific to incident scenarios. Trigger on mentions of incident, work zone, lane closure, road closure, disruption, closingReroute, closingLaneReroute, or "how much does rerouting help when a road closes."
related_skills:
  - create-single-intersection
  - model-parking-with-rerouting
  - compute-dynamic-user-equilibrium
  - analyze-simulation-outputs
  - visualize-trajectories-and-timeseries
  - measure-travel-time-reliability-with-simulated-days
  - scan-network-link-criticality-and-vulnerability
  - sweep-rerouting-device-market-penetration
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[model-parking-with-rerouting]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[analyze-simulation-outputs]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[measure-travel-time-reliability-with-simulated-days]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[sweep-rerouting-device-market-penetration]]"
related_pages:
  - "[[incident-rerouting-and-closures]]"
---

# Simulate Incident-Triggered Dynamic Rerouting

Builds a mid-simulation incident/work-zone scenario — a primary route and a parallel detour, a temporary closure on the primary route via a `<rerouter>`'s `<closingReroute>`/`<closingLaneReroute>`, and a clean baseline-vs-dynamic-rerouting comparison that isolates the rerouting **device** as the sole cause of any diversion. This is SimSkill's disruption-response counterpart to `model-parking-with-rerouting` (occupancy-triggered rerouting) and `compute-dynamic-user-equilibrium` (offline, pre-simulation route optimization) — here the trigger is a real-time incident and the response happens live, in one simulation run.

## Network design: put the queue where it can't trap diverters

A primary route (e.g. `O -> A -> C -> B -> D`) and a parallel detour (e.g. `A -> P -> B`) must diverge at a real junction (`A`) upstream of the incident, and the detour should normally be somewhat slower (~15-20%) so it's a genuine tradeoff, not a strictly-dominant alternative that would divert traffic even without an incident.

**Placement of the incident matters.** Put the closure on an edge *downstream* of the diverge point (e.g. `C->B`, not `A->C`), with at least one main-exclusive edge (e.g. `A->C`) between the diverge and the closure. If the incident sits directly at or upstream of the diverge, the resulting queue backs up onto the diverge junction itself and can trap vehicles that would otherwise have been able to reach the detour — confounding "rerouting is slow to react" with "the network design physically prevented diversion." Verify the queue actually stores on the main-exclusive edge (via edgeData speed/occupancy during the incident window), not spilling back past the diverge.

## The incident: `closingReroute` vs `closingLaneReroute`

Both live inside a `<rerouter>` additional-file element, active for a specific `<interval>`:

```xml
<additional>
    <rerouter id="workzone" edges="OA">
        <interval begin="600" end="1500">
            <!-- full edge closure: -->
            <closingReroute id="CB" allow=""/>
            <!-- OR a lane drop (partial capacity loss), naming a specific lane: -->
            <closingLaneReroute id="CB_0" disallow="all"/>
        </interval>
    </rerouter>
</additional>
```

The `rerouter`'s `edges` attribute is where vehicles are evaluated for rerouting — put it **upstream** of the diverge point (e.g. on the edge feeding into `A`), not on the closed edge itself, so a device-equipped vehicle has enough lookahead to actually take the detour rather than being evaluated for a decision it has already passed.

**Prefer `closingLaneReroute` (a lane drop) over `closingReroute` (a full closure) whenever the comparison needs a clean "baseline = zero rerouting" run.** A full closure invalidates every static route through the closed edge for the window's duration — a vehicle inserted during the window with a pre-planned route through it either aborts with a routing error, or has its route silently repaired by SUMO's own error-handling, independent of whether the rerouting device is enabled. Either outcome introduces route changes in the *baseline* run that have nothing to do with the device under test, contaminating the comparison. A lane drop keeps the edge passable on its remaining lane(s), so every static route stays technically valid — no abort, no silent repair — making the rerouting device the *sole* possible cause of any route change in the dynamic run. Use a full `closingReroute` only when the scenario intentionally wants to study forced route repair itself, not when isolating the device's effect.

## The baseline-vs-dynamic comparison

Run the identical network, demand, and incident config twice, varying only the rerouting device:

```bash
# Baseline: incident happens, but no vehicle can react to it
sumo -n network.net.xml -r demand.rou.xml -a incident.add.xml,edgedata_baseline.add.xml \
  --device.rerouting.probability 0 \
  --tripinfo-output outputs/baseline/tripinfo.xml --summary-output outputs/baseline/summary.xml \
  --vehroute-output outputs/baseline/vehroutes.xml --vehroute-output.exit-times true \
  --queue-output outputs/baseline/queue.xml --statistic-output outputs/baseline/stats.xml \
  --begin 0 --end 3600 --time-to-teleport 300 --no-step-log true

# Dynamic: every vehicle equipped, live travel-time-adaptive rerouting
sumo -n network.net.xml -r demand.rou.xml -a incident.add.xml,edgedata_dynamic.add.xml \
  --device.rerouting.probability 1 \
  --device.rerouting.period 30 --device.rerouting.pre-period 5 \
  --device.rerouting.adaptation-interval 1 --device.rerouting.adaptation-steps 4 \
  --tripinfo-output outputs/dynamic/tripinfo.xml --summary-output outputs/dynamic/summary.xml \
  --vehroute-output outputs/dynamic/vehroutes.xml --vehroute-output.exit-times true \
  --queue-output outputs/dynamic/queue.xml --statistic-output outputs/dynamic/stats.xml \
  --begin 0 --end 3600 --time-to-teleport 300 --no-step-log true
```

Key `device.rerouting.*` parameters (see [[incident-rerouting-and-closures]] for the full semantics):
- `probability` — fraction of vehicles equipped; `1` for a scenario where every vehicle can respond.
- `period` — how often an equipped vehicle re-evaluates its route (seconds).
- `pre-period` — a shorter initial period right after departure/insertion, so a vehicle can react fast if it enters near an already-active incident.
- `adaptation-interval` / `adaptation-steps` — control how the live edge-weight estimate is smoothed from recent travel times; smaller values make the device react faster but noisier.

A separate small `edgedata_*.add.xml` per run (own `<edgeData>` output declaration) keeps baseline/dynamic edge-level outputs from colliding on the same file path.

## Post-processing: `scripts/analyze_incident.py`

```bash
python scripts/analyze_incident.py \
  --baseline-dir outputs/baseline --dynamic-dir outputs/dynamic \
  --incident-begin 600 --incident-end 1500 \
  --incident-edge AC --detour-edge AP \
  --out-dir analysis/ --plots-dir plots/
```

Produces:
- `analysis/comparison_table.csv` — arrived count, mean/total travel time, time loss, waiting time, depart delay, total system time (in-network + depart delay), max network queue length, teleports, and route split (main vs detour), each with a baseline-vs-dynamic %-change.
- `analysis/diversion_summary.txt` — detour share and first-detour-departure time per run.
- `plots/incident_edge_and_detour_timeseries.png` — mean speed and vehicle count on the incident edge vs the detour edge, both runs overlaid, incident window shaded.
- `plots/detour_uptake_over_time.png` — cumulative vehicles entering the detour edge over time, both runs — shows reaction speed and diversion magnitude directly.
- `plots/metrics_bar_baseline_vs_dynamic.png` — bar comparison of the four headline per-vehicle metrics.

It classifies each vehicle's actual route (main vs detour) from `vehroute-output`: a rerouted vehicle carries a `<routeDistribution>` whose **last** `<route>` child is the one actually driven — always read the last route, not the first, or every rerouted vehicle gets misclassified as having taken its original route.

## Gotchas

- **A `closingReroute`/`closingLaneReroute` with no equipped vehicles downstream of it (or `edges` placed on/after the closure instead of upstream of the diverge) is a silent no-op** in the dynamic run too — if the dynamic run shows zero diversion, check `device.rerouting.probability` and the rerouter's `edges` placement before assuming the incident had no effect.
- **Full closures contaminate the baseline** (see above) — default to `closingLaneReroute` unless the scenario specifically needs to study forced route repair.
- **`stats.xml`'s `<teleports total=.../>` is a cumulative running count for the whole run, not a per-interval delta** — read the single final value, never sum across intervals (see [[sumo-output-files]]).
- **Network geometry determines whether diversion is even physically possible** — verify the queue stores on a main-exclusive edge downstream of the diverge before trusting a "rerouting barely helped" result; it may just mean the diverge itself got jammed.

## Related

- `create-single-intersection` / any network skill for the base topology (plain-XML `.nod.xml`/`.edg.xml` + `netconvert` is sufficient for a primary-route-plus-detour topology).
- `model-parking-with-rerouting` — SimSkill's other dynamic-rerouting skill (occupancy-triggered rather than incident-triggered); shares the `device.rerouting.*` mechanism.
- `compute-dynamic-user-equilibrium` — the offline counterpart: iterative pre-simulation route optimization rather than live in-simulation response to a disruption.
- `analyze-simulation-outputs`, `visualize-trajectories-and-timeseries` — general output-analysis/plotting skills this one specializes for the incident-comparison case.
- [[incident-rerouting-and-closures]] — the underlying SUMO concepts (`closingReroute`/`closingLaneReroute` syntax and semantics, `device.rerouting.*` parameters, the route-validity reasoning for lane-drop vs full-closure).
- `measure-travel-time-reliability-with-simulated-days` — uses this skill's stochastic-incident mechanics as one input to a Monte Carlo simulated-day reliability framework, treating incident-driven variability as part of what's measured rather than a one-off scenario.
- `scan-network-link-criticality-and-vulnerability` — scales this skill's single-link closure mechanics to a network-wide scan across every link, finding that full closure (not the lane-drop this skill usually prefers) is the right choice when the goal is measuring genuine route invalidity/criticality rather than isolating the rerouting device's effect.
- `sweep-rerouting-device-market-penetration` — extends this skill's baseline-vs-fully-equipped comparison to a full penetration sweep, adding subgroup (equipped vs. unequipped) attribution and finding that real-time information behaves as a congestible good.
