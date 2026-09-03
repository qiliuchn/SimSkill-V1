---
summary: SUMO restricts individual lanes to or away from specific vehicle classes via allow/disallow lane attributes — the mechanism behind bike lanes, bus lanes, and truck bans — and models bicycles as a first-class vClass with distinct dynamics from cars.
keywords:
  - vClass
  - lane-permissions
  - allow
  - disallow
  - bicycle
  - bike-lane
  - netconvert
created: 2026-07-24T10:20:00
last_updated: 2026-08-06T20:18:44
sources:
  - "[[episodic-memory/2026-07-24_09-47-48/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_09-47-48/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html
  - https://sumo.dlr.de/docs/Networks/PlainXML.html
related_pages:
  - "[[duarouter]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-command-line]]"
  - "[[parking-areas-and-rerouters]]"
  - "[[sublane-model-and-lane-filtering]]"
  - "[[dedicated-bicycle-lanes-and-mode-share]]"
  - "[[reversible-lane-encoding-and-changeover-safety]]"
  - "[[neighborhood-traffic-calming-displacement-and-evaporation]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
  - "[[urban-freight-delivery-tours-container-semantics-and-policy-levers]]"
  - "[[street-running-tram-reservation-and-right-of-way-tradeoffs]]"
related_skills:
  - model-vclass-lane-permissions
  - create-grid-network
  - generate-random-trips
  - simulate-street-running-tram-corridor
  - convert-trips-to-routes
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - model-managed-lanes-with-dynamic-tolling-and-self-selection
  - model-urban-freight-delivery-tours
related_skills_for_graph_view:
  - "[[model-vclass-lane-permissions]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[simulate-street-running-tram-corridor]]"
  - "[[convert-trips-to-routes]]"
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[model-managed-lanes-with-dynamic-tolling-and-self-selection]]"
  - "[[model-urban-freight-delivery-tours]]"
---

# Vehicle Class Lane Permissions

SUMO assigns every vehicle a `vClass` (`passenger`, `bicycle`, `bus`, `truck`, `pedestrian`, etc.) and can restrict any individual **lane** to a specific subset of classes via `allow`/`disallow` attributes. This is the general mechanism underneath bike lanes, bus-only lanes, truck bans, and HOV lanes — a static, always-on restriction, distinct from the *dynamic* route-choice mechanisms in [[parking-areas-and-rerouters]] and incident rerouting, which redirect vehicles mid-simulation rather than making a lane categorically illegal for a class.

## allow / disallow syntax

```xml
<edge id="A0B0" from="A0" to="B0" numLanes="2" speed="13.9">
    <lane index="0" allow="bicycle"/>
    <lane index="1" disallow="bicycle"/>
</edge>
```

`allow` is a whitelist (only the listed classes may use the lane); `disallow` is a blacklist (every class except the listed ones may). They're mutually exclusive on a single lane — set one or the other, never both. Lane `index="0"` is the network's rightmost lane. A lane with neither attribute keeps the network's default permissions (normally all vClasses).

These attributes can be set directly in a plain-XML `.edg.xml` (as `<lane>` children of an `<edge>`) before compiling with `netconvert`, or edited directly in a compiled `.net.xml`. Editing the source and recompiling is the more maintainable path when producing multiple permission variants of the same base topology.

## The connection/TLS-regeneration requirement

Changing a lane's permitted classes can change which turn movements are actually legal from that lane — most sharply when a lane is dropped to a narrow subset (e.g. bicycle-only), forcing the remaining general-traffic lane(s) to absorb turn movements they previously shared. **If a permission-edited `.edg.xml` is recompiled together with the *original* network's `.con.xml` (explicit lane-to-lane connections) and `.tll.xml` (traffic-light logic tied to specific link indices), those files still encode the old lane layout's connections and link indices** — the result is often "no connection" routing errors for vehicles that can no longer use the lane they were assigned, or a traffic light program referencing link indices that no longer correspond to real movements. The fix is to let `netconvert` regenerate connections and TLS logic from the node and edge files alone (omit `--connection-files`/`--tllogic-files`) whenever lane permissions change — this is the single most common way a lane-permission variant silently breaks.

## Verifying a permission change actually took effect

Inspect the **compiled** `net.xml`, not just the source `.edg.xml` — `netconvert` is the ground truth for what will actually be simulated. `grep`/diff the same edge's `<lane>` elements across a restricted and an unrestricted variant to confirm they genuinely differ where intended. Separately, route the restricted vClass's demand against the restricted network with `duarouter` **without** `--ignore-errors`: a route through a now-illegal lane assignment fails loudly as a routing error rather than silently succeeding, which is the cleanest confirmation that the permission is both present and actually being respected by routing.

## Bicycles as a vClass

Bicycles are modeled as their own `vClass="bicycle"` with meaningfully different dynamics from motor vehicles — a distinct `vType` is standard:

```xml
<vType id="bike_bicycle" vClass="bicycle" maxSpeed="5.5" width="0.65" length="1.8"/>
```

`randomTrips.py --vehicle-class bicycle` (or manual trip tagging) generates bicycle demand; merging it with car demand into one trips file before routing keeps departure schedule and seed identical across any compared network variants, isolating the network change as the only difference.

## Interpreting a mode-split comparison

A restricted vClass's raw mean travel time can look worse even when the restriction genuinely helped it, if the restriction also lengthens its typical route (e.g. rerouted around a merge or junction it can no longer use in the way it used to). Check route length alongside travel time — and per-meter speed (`routeLength / duration`) if the two move in the same direction — before concluding a restriction hurt or helped a vClass's actual speed, rather than trusting raw travel time alone.

**Measured effect** (4-signal corridor, rightmost of 2 lanes/direction made bicycle-only, ~1000 cars + ~360 bicycles, identical demand across both variants): the dedicated lane cut bicycle mean waiting time 7.5% with unchanged throughput; bicycle mean travel time rose 1.7%, but this tracked a 2.6% increase in mean route length rather than a real slowdown (per-meter speed was flat-to-slightly-better). The cost fell almost entirely on cars losing a lane: car mean travel time +16.0%, car mean waiting time +57.8%, total network time loss +22.9% — while car throughput was fully preserved (no gridlock at this demand level). The general lesson: a lane restriction that benefits one vClass tends to show up as *delay*, not *throughput loss*, for the class that lost lane capacity, at least below the demand level where losing a lane causes genuine gridlock.

See the `model-vclass-lane-permissions` skill for the full build/verify/compare workflow and bundled scripts. [[urban-freight-delivery-tours-container-semantics-and-policy-levers]] extends the reachability-checking technique this page recommends (`duarouter` without `--ignore-errors`) into a critical modeling gotcha: a demand generator that screens candidate vehicle classes by edge permission alone, rather than round-trip route feasibility, can fabricate a fictitious non-monotone "partial restrictions worse than complete restrictions" finding under a partial, exempted restriction.
