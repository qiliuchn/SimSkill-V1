---
summary: SUMO models curbside/lot parking via parkingArea additional-file elements and vehicle stops with parking="true", with rerouter/parkingAreaReroute elements enabling occupancy-aware dynamic redirection to an alternative lot for any vehicle equipped with the rerouting device.
keywords:
  - parkingArea
  - rerouter
  - parkingAreaReroute
  - rerouting-device
  - dynamic-route-choice
created: 2026-07-23T16:28:53
last_updated: 2026-08-18T12:35:00
sources:
  - "[[episodic-memory/2026-07-23_16-14-39/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_16-14-39/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/ParkingArea.html
  - https://sumo.dlr.de/docs/Simulation/Rerouter.html
related_pages:
  - "[[station-based-shared-micromobility-in-sumo]]"
  - "[[sumo-output-files]]"
  - "[[duarouter]]"
  - "[[abstract-network-generation]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[curbside-delivery-blocking-externality]]"
  - "[[cruising-for-parking-search-externality-and-remedies]]"
  - "[[car-to-transit-intermodal-transfer-and-park-and-ride]]"
related_skills:
  - model-parking-with-rerouting
  - create-grid-network
  - convert-trips-to-routes
  - run-simulation
  - model-curbside-delivery-and-lane-blocking-externality
  - model-cruising-for-parking-search-externality
related_skills_for_graph_view:
  - "[[model-parking-with-rerouting]]"
  - "[[create-grid-network]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[model-cruising-for-parking-search-externality]]"
---

# Parking Areas and Rerouters

SUMO models curbside/lot parking as a `<parkingArea>` (an additional-file element attached to a lane) that vehicles stop at, and models the **dynamic route choice** that parking availability triggers via `<rerouter>` elements carrying `<parkingAreaReroute>` alternatives. This is SUMO's main built-in mechanism for a vehicle to change its route mid-simulation in response to live conditions, rather than following a route fixed once at departure (contrast with every other demand/routing page in memory — [[duarouter]] et al. — which compute a route once and never revisit it). See [[incident-rerouting-and-closures]] for the same `rerouter`/rerouting-device mechanism applied to incident/work-zone disruptions instead of parking occupancy, and [[vehicle-class-lane-permissions]] for a *static*, always-on alternative to dynamic rerouting — restricting a lane to a vClass outright rather than redirecting vehicles around a condition.

## Defining a parkingArea

```xml
<additional>
    <parkingArea id="PA0" lane="B1B2_0" roadsideCapacity="6" startPos="5.0" endPos="41.0"/>
</additional>
```

`roadsideCapacity` bounds how many vehicles can park simultaneously; `startPos`/`endPos` place it along the lane (must fit within the lane's own length). Unequal capacities across lots (a couple deliberately under-provisioned alongside several roomier ones) is the natural way to engineer a scenario where some lots fill up and others don't.

## Parking stops

A vehicle parks via a `<stop>` referencing the lot, with `parking="true"` (SUMO round-trips this as `parking="1"` in output/processed files):

```xml
<stop parkingArea="PA0" duration="300" parking="true"/>
```

`duarouter` preserves `<stop>` elements through routing — attach the stop to a trip/vehicle before routing it, and it survives into the final `.rou.xml` unchanged (aside from the `true`→`1` normalization).

**This attachment is not automatic for an intermodal `personTrip`.** When a person's car leg ends at a `parkingArea` via `--persontrip.transfer.car-walk parkingAreas`, `duarouter` positions the vehicle's arrival inside the lot's `[startPos,endPos]` range but does **not** itself write a `<stop parkingArea=.../>` element — verified directly: a car-to-transit vehicle's routed `.rou.xml` had zero `<stop>` elements, and lot occupancy sampled via TraCI stayed at 0 for the whole run despite every planned park-and-ride trip completing. See [[car-to-transit-intermodal-transfer-and-park-and-ride]] for the fix (a post-processing step that injects the `<stop>` explicitly) and the further findings this unlocks.

## Rerouters and parkingAreaReroute

A `<rerouter>` sits on one or more edges and, within a time `<interval>`, lists candidate lots as `<parkingAreaReroute>` elements:

```xml
<rerouter id="rr_PA0" edges="A1B1 B0B1 B1B2 B2B1 C1B1">
    <interval begin="0" end="100000">
        <parkingAreaReroute id="PA0" visible="true"/>
        <parkingAreaReroute id="PA1" visible="true"/>
    </interval>
</rerouter>
```

When a vehicle equipped with the rerouting device passes over a rerouter's edges heading toward a full (or soon-to-be-full) target lot, SUMO redirects it to the nearest listed alternative with free capacity instead. Effective `edges` placement needs genuine upstream reach — a rerouter confined to only the lot's own edge fires too late to meaningfully redirect anyone; include the edges feeding into the lot's junction (computable from the network via `sumolib`) so vehicles are redirected before they've essentially already arrived.

**The rerouting device is required for a vehicle to respond at all.** `--device.rerouting.probability 1` on the `sumo` command line equips every vehicle; without it (or an equivalent per-vehicle device assignment), rerouters are correctly-defined no-ops — a common silent-failure mode when a rerouting scenario "doesn't seem to do anything."

## Observing parking occupancy over time

**No `--parking-output`-style CLI flag or parkingArea `output` attribute exists** for emitting an occupancy-over-time file directly (checked as of SUMO 1.27.x via `sumo --help`) — don't assume one without verifying against the installed version's actual help output. There are **two** mechanisms, and the offline one is easy to miss. **(1) `--stop-output`** (with `--stop-output.write-unfinished`) emits one `<stopinfo>` per stop, and a **`parkingArea` stop record carries a `parkingArea` attribute** alongside `started`/`ended` — so the full per-lot occupancy series can be reconstructed offline from a plain command-line run, with no TraCI loop (verified against SUMO 1.27.1; see [[station-based-shared-micromobility-in-sumo]], where it is used to rebuild a dock inventory ledger from a channel the controlling script never touches — 168 station-interval cells, 0 disagreements). Prefer it whenever the occupancy series is being used to *check* a TraCI controller, since sampling occupancy inside that same controller makes any conservation check tautological. **(2) The live mechanism is TraCI:** `traci.parkingarea.getVehicleCount(lot_id)` (and `getVehicleIDs` to identify which vehicles are where) sampled once per simulation step while driving the run via `traci.simulationStep()`, rather than a plain command-line run. See `model-parking-with-rerouting` for a bundled script that does this while still letting SUMO write the normal `tripinfo`/`summary`/`stop-output` files.

## Teleports as a failed-to-park signal

`--time-to-teleport` (SUMO's general stuck-vehicle handling) becomes the mechanism that turns unresolved lot over-subscription into a **countable failure event**: a vehicle stuck waiting for space at a full lot with no viable alternative eventually gets teleported once it's been stuck longer than this threshold. Set it short enough relative to the scenario's own timeframe (e.g. 120 s in a ~1-hour scenario) that genuine over-subscription actually produces teleports to count — otherwise vehicles may simply queue indefinitely without the scenario ever registering a failure, making a "did rerouting help" comparison look artificially flat.

## What a disabled-vs-enabled comparison tends to show

Measured on a small grid with two deliberately under-provisioned lots (capacity 6) against four roomier alternatives (capacity 8), enabling occupancy-aware rerouting: eliminated all failed-to-park/teleport events, let every vehicle park, substantially cut mean waiting time and time loss network-wide (not just for the vehicles that were rerouted — congestion caused by stuck/queuing vehicles affects everyone nearby), and visibly rebalanced peak occupancy from the over-subscribed lots onto the underused alternatives (cutting the cross-lot utilization imbalance roughly in half). A meaningful fraction of vehicles end up parking somewhere other than their originally-assigned lot — track actual-vs-assigned lot per vehicle to quantify this redistribution rather than assuming it.

See the `model-parking-with-rerouting` skill for the full build/run workflow and a bundled TraCI-driven scenario script. [[cruising-for-parking-search-externality-and-remedies]] extends this mechanism into the search process itself — treating parking as a source of traffic rather than a routing destination — and finds, among other things, that search time diverges super-linearly with occupancy and that curb occupancy alone can be an unreliable saturation signal once demand exceeds capacity.
