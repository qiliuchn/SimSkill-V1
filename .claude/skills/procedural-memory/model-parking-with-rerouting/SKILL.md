---
name: model-parking-with-rerouting
description: Use this skill when the user wants to model curbside/lot parking in SUMO and dynamic route choice in response to it — vehicles parking at a parkingArea, lots filling up, and occupancy-aware rerouters redirecting vehicles to an alternative lot with free capacity. Covers parkingArea and rerouter/parkingAreaReroute XML definitions, parking stops, the rerouting device, and how to observe parkingArea occupancy over time (via TraCI, since no CLI output option exists for it). Trigger on mentions of parking, parkingArea, parking search, rerouter, dynamic rerouting, lot occupancy, or "vehicles finding an alternative parking spot."
---

# Model Parking with Occupancy-Aware Rerouting

Models curbside/lot parking and the dynamic route choice it triggers: vehicles heading to an assigned `parkingArea`, some lots filling up under demand, and `rerouter` elements redirecting a vehicle to an alternative lot with free capacity before it wastes time arriving at a full one. This is SimSkill's only skill covering **dynamic route choice** — every other demand/routing skill (`generate-random-trips`, `calibrate-demand-with-routesampler`, `convert-trips-to-routes`) computes a fixed route once and never changes it mid-simulation.

## Defining parking areas

A `<parkingArea>` lives in an additional file, attached to a specific lane:

```xml
<additional>
    <parkingArea id="PA0" lane="B1B2_0" roadsideCapacity="6" startPos="5.0" endPos="41.0"/>
</additional>
```

`roadsideCapacity` is the number of vehicles it can hold; `startPos`/`endPos` bound where along the lane it physically sits (must fit within the lane's length). Set capacities deliberately unequal across lots if the goal is to study over-subscription and rebalancing — a couple of under-provisioned lots alongside several roomier ones is what actually produces failed-to-park events and a rerouting benefit to measure.

## Parking stops on vehicles/routes

A vehicle parks via a `<stop>` element referencing the `parkingArea` id, with `parking="true"` (SUMO writes this back as `parking="1"` once processed by `duarouter`):

```xml
<vehicle id="v0" ...>
    <route edges="..."/>
    <stop parkingArea="PA0" duration="300" parking="true"/>
</vehicle>
```

Attach this stop to trips before or after routing with `duarouter` — `duarouter` preserves stop elements through to the output route file, so it's fine to put the `<stop>` on a `<trip>`/`<vehicle>` before running it through `convert-trips-to-routes`.

## Rerouters: redirecting away from a full lot

A `<rerouter>` additional-file element sits on one or more edges **upstream of** a lot (so a vehicle can still be redirected before committing to the full one) and lists every candidate lot as a `<parkingAreaReroute>` alternative:

```xml
<rerouter id="rr_PA0" edges="A1B1 B0B1 B1B2 B2B1 C1B1">
    <interval begin="0" end="100000">
        <parkingAreaReroute id="PA0" visible="true"/>
        <parkingAreaReroute id="PA1" visible="true"/>
        <!-- ...every other lot the rerouter should consider as an alternative... -->
    </interval>
</rerouter>
```

A working pattern for choosing `edges`: the lot's own edge plus every non-internal edge feeding into its junction (computable programmatically from the network via `sumolib`, rather than hand-picked) — this gives the rerouter a genuine upstream lookahead rather than only firing right at the lot itself. One `<rerouter>` per lot, each still listing *all* lots (including its own) as `parkingAreaReroute` alternatives, lets SUMO's own logic pick the actual nearest one with free capacity.

**A vehicle only responds to a rerouter if it's equipped with the rerouting device.** The simplest way to guarantee this for every vehicle in the scenario is `--device.rerouting.probability 1` on the `sumo` command line — without it (or a per-vehicle device assignment), rerouters have no effect even if they're correctly defined and loaded.

## Running the disabled-vs-enabled comparison

Use the exact same network and route file for both runs — the only difference should be which additional files are loaded and whether the rerouting device is equipped:

```bash
# Disabled: parkingArea file only, no rerouter, no device
python scripts/run_parking_scenario.py --net grid.net.xml --routes routes.rou.xml \
    --additional parking.add.xml --lots PA0,PA1,PA2,PA3,PA4,PA5 --out-dir outputs/disabled \
    --tripinfo-output outputs/disabled/tripinfo.xml --summary-output outputs/disabled/summary.xml

# Enabled: same net/routes, rerouter file added, every vehicle equipped
python scripts/run_parking_scenario.py --net grid.net.xml --routes routes.rou.xml \
    --additional parking.add.xml,rerouter.add.xml --lots PA0,PA1,PA2,PA3,PA4,PA5 \
    --out-dir outputs/enabled --device-rerouting-probability 1 \
    --tripinfo-output outputs/enabled/tripinfo.xml --summary-output outputs/enabled/summary.xml
```

`scripts/run_parking_scenario.py` drives the simulation step-by-step via TraCI (rather than a plain command-line run) specifically to sample `traci.parkingarea.getVehicleCount(lot_id)` every step, building the occupancy-over-time series each lot needs for a hotspot/redistribution plot. It also tracks, per vehicle: when it first arrived at its target lot's edge, when it actually started parking (search time = the gap between the two), which lot it actually ended up in (may differ from its original assignment once rerouted), and which vehicles were teleported (SUMO's stuck-vehicle mechanism — see Gotchas). Results land in `<out-dir>/traci_metrics.json`; standard `tripinfo`/`summary`/`stop-output` files are still written by SUMO itself for the usual travel-time-style metrics.

## Gotchas

- **There is no `--parking-output`-style CLI flag or parkingArea `output` attribute** (checked as of SUMO 1.27.x) that writes an occupancy-over-time file directly — don't assume one exists without checking `sumo --help | grep -i park` for the current version. `traci.parkingarea.getVehicleCount`/`getVehicleIDs` are the actual mechanism; this skill's script already handles that.
- **`--time-to-teleport` is what turns unresolved over-subscription into a countable failure**, not just a generic anti-gridlock setting here: a vehicle stuck waiting for space at a full lot with no viable alternative eventually gets teleported by SUMO's normal stuck-vehicle handling. Set it to something short enough (e.g. 120 s) that the scenario's actual timeframe can produce these events if the demand truly can't be satisfied — otherwise a "disabled rerouting" baseline might just show vehicles queuing forever without ever registering as a failure.
- **A rerouter with no equipped vehicles is a silent no-op.** If enabling rerouting doesn't change anything, check `--device.rerouting.probability` was actually set (or per-vehicle devices were assigned) before assuming the rerouter definitions themselves are wrong.
- **Rerouter `edges` need genuine upstream reach.** A rerouter placed only on the lot's own edge fires too late to actually redirect a vehicle before it's already essentially there — include the edges feeding into the lot's junction, not just the lot's edge itself.
- **A vehicle's actual parked lot can differ from its route's original `parkingArea` stop reference** once rerouted — track this separately (as `scripts/run_parking_scenario.py` does) rather than assuming every vehicle ends up where its route said, or a "how much redistribution happened" analysis will be silently wrong.

## Related

- `create-grid-network` (or any network skill) for the base topology.
- `convert-trips-to-routes` (`duarouter`) for turning trips-with-parking-stops into full routes — it preserves the `<stop>` element through routing.
- `run-simulation` for the general command-line-vs-TraCI distinction this skill's TraCI-based occupancy sampling builds on.
- [[parking-areas-and-rerouters]] — the underlying SUMO concepts (parkingArea/rerouter/parkingAreaReroute semantics, the rerouting device, teleport-as-failure-signal) this skill's workflow is built on.
- `model-curbside-delivery-and-lane-blocking-externality` — contrasts this skill's off-street `parkingArea` mechanic (never affects travel-lane capacity) against a genuinely different mechanic, a `<stop parking="false"/>` that physically blocks a travel lane, and measures the resulting externality on general traffic.
- `model-cruising-for-parking-search-externality` — extends this skill's occupancy-visibility mechanism into the search process itself: how long a vehicle actually spends looking for a space as occupancy rises, the delay externality that imposes on other traffic, and whether pricing, added supply, or driver information (a scaled-up version of this skill's rerouter mechanism) is the effective remedy.
