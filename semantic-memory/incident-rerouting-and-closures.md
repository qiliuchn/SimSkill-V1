---
summary: SUMO models a mid-simulation incident/work-zone via a rerouter's closingReroute (full edge closure) or closingLaneReroute (lane drop) element, and only vehicles equipped with the rerouting device react to it in real time via live travel-time adaptation.
keywords:
  - closingReroute
  - closingLaneReroute
  - rerouter
  - incident
  - work-zone
  - rerouting-device
  - dynamic-route-choice
created: 2026-07-24T09:40:00
last_updated: 2026-07-24T09:40:00
sources:
  - "[[episodic-memory/2026-07-24_08-58-09/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_08-58-09/attempts/attempt-2/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Rerouter.html
  - https://sumo.dlr.de/docs/Demand/Automatic_Routing.html
related_pages:
  - "[[parking-areas-and-rerouters]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[sumo-output-files]]"
  - "[[duarouter]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[information-penetration-and-congestible-routing]]"
  - "[[travel-time-reliability-metrics-in-sumo]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[automatic-incident-detection-algorithms]]"
related_skills:
  - simulate-incident-rerouting
  - model-parking-with-rerouting
  - compute-dynamic-user-equilibrium
  - run-simulation
  - sweep-rerouting-device-market-penetration
  - measure-travel-time-reliability-with-simulated-days
  - scan-network-link-criticality-and-vulnerability
related_skills_for_graph_view:
  - "[[simulate-incident-rerouting]]"
  - "[[model-parking-with-rerouting]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[run-simulation]]"
  - "[[sweep-rerouting-device-market-penetration]]"
  - "[[measure-travel-time-reliability-with-simulated-days]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
---

# Incident Rerouting and Closures

SUMO models a temporary incident or work zone — a lane drop or full edge closure lasting a fixed window mid-simulation — via `<rerouter>` additional-file elements carrying a `<closingReroute>` or `<closingLaneReroute>` child. This is the disruption-response sibling of [[parking-areas-and-rerouters]]'s occupancy-triggered rerouting: same underlying mechanism (a `rerouter` element plus the vehicle-side rerouting device), different trigger.

## closingReroute vs closingLaneReroute

```xml
<additional>
    <rerouter id="workzone" edges="OA">
        <interval begin="600" end="1500">
            <!-- full closure of an entire edge -->
            <closingReroute id="CB" allow=""/>
            <!-- OR: partial closure of one specific lane -->
            <closingLaneReroute id="CB_0" disallow="all"/>
        </interval>
    </rerouter>
</additional>
```

- `closingReroute` closes an entire **edge** (referenced by edge id) for the `<interval>`'s duration — nothing can pass through it at all, on any lane.
- `closingLaneReroute` closes one specific **lane** (referenced by lane id, e.g. `CB_0`) — the edge stays passable on its remaining lane(s), just at reduced capacity.

The `rerouter`'s own `edges` attribute is *not* the closed edge — it's where vehicles are evaluated for a routing decision, and should sit **upstream** of the diverge point leading to an alternative, giving an equipped vehicle enough lookahead to actually act on the closure before passing the point where it could have detoured.

## Why prefer a lane drop when isolating the rerouting device's effect

A full `closingReroute` invalidates every **static** route that runs through the closed edge for the whole window: a vehicle inserted mid-window with a pre-planned route through it either aborts with a routing error, or gets silently route-repaired by SUMO's own error-handling — independent of whether that vehicle carries the rerouting device. Either outcome introduces route changes in a **baseline** (rerouting-device-disabled) run that have nothing to do with the device under test, contaminating any "baseline = zero rerouting" comparison.

`closingLaneReroute` avoids this: because the edge stays passable on its other lane(s), every statically-planned route through it remains technically valid for the whole window — no abort, no silent repair. That makes the rerouting **device** the sole possible cause of any route change observed in a dynamic-rerouting run, which is exactly the property a clean device-effect comparison needs. Reserve a full `closingReroute` for scenarios that specifically want to study forced route repair itself, rather than isolate the device's contribution.

## The rerouting device and live travel-time adaptation

Only vehicles equipped with SUMO's `rerouting` device react to a closure (or to a `parkingAreaReroute`) in real time; unequipped vehicles drive their originally-computed static route regardless of what a `rerouter` defines. Equip every vehicle in a scenario with `--device.rerouting.probability 1`, or a fraction for a mixed-equipage study — see [[information-penetration-and-congestible-routing]] for a verified sweep of this fraction as a treatment variable, which found real-time information behaves as a congestible good: private benefit to being equipped decays and reverses past moderate penetration, and network-wide benefit is non-monotonic in penetration.

Key parameters (`--device.rerouting.<name>`):
- `probability` — fraction of vehicles equipped.
- `period` — how often an equipped vehicle re-evaluates and potentially recomputes its route, in seconds.
- `pre-period` — a shorter period applied right after a vehicle departs/is inserted, so vehicles entering near an already-active incident can react quickly rather than waiting a full `period`.
- `adaptation-interval` / `adaptation-steps` — control the smoothing window over which recent edge travel times are aggregated into the live weight estimate the router uses; smaller values track disruptions faster but are noisier, larger values are more stable but slower to reflect a sudden change like an incident onset.

A vehicle's actual re-route shows up in `vehroute-output` as a `<routeDistribution>` element containing multiple `<route>` children (one per recomputation) — the **last** child is the route actually driven; the first is only its original plan. Any post-processing that classifies vehicles by their final route must read the last `<route>`, not the first, or every rerouted vehicle is misclassified.

## Network-design consideration: where the queue can go

A closure's induced queue needs somewhere to store that doesn't back up onto the diverge junction itself — otherwise vehicles that would have taken the detour get trapped in the queue before ever reaching the point where a reroute decision is possible, confounding "the device reacted slowly" with "the network physically prevented diversion." Placing the closure at least one main-exclusive edge downstream of the diverge, and verifying via edgeData that the queue's speed/occupancy collapse is confined to that edge during the incident window, rules this out.

## Measured mitigation effect

On a primary-route-plus-parallel-detour network (detour ~18% slower under free-flow, single dominant O→D flow, 900s lane-drop incident on a downstream main-route edge), equipping vehicles with the rerouting device against an identical no-device baseline: mean travel time -11.3%, mean time loss -22.6%, mean depart delay -81.8%, total system time (in-network + depart delay) -19.1%, max network queue length -21.0% — at the cost of diverted vehicles' mean waiting time rising +129% (waiting at the detour's merge/yield junctions) and a small throughput dip (-1.6%, more vehicles still finishing on the slower detour at the run's end). Diversion was fast (reroute began 9s after incident onset) and front-loaded at incident onset. Numbers are scenario-specific but the direction — a real mitigation-vs-tradeoff pattern, not a free win — is the generalizable takeaway; always measure both the mitigation and the tradeoff, not just one side.

See the `simulate-incident-rerouting` skill for the full build/run/analyze workflow and a bundled comparison-analysis script.
