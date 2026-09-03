---
summary: SUMO models electric vehicles via a per-vType battery device (energy consumption, state of charge) and chargingStation additional-file infrastructure, with the stationfinder device enabling automatic charge-aware rerouting to the nearest station once state of charge drops below a threshold — verified to cut stranded vehicles by ~89% in a controlled comparison.
keywords:
  - battery-device
  - chargingStation
  - stationfinder
  - electric-vehicle
  - state-of-charge
created: 2026-07-23T17:26:26
last_updated: 2026-08-05T05:00:00
sources:
  - "[[episodic-memory/2026-07-23_17-13-29/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_17-13-29/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Models/Electric.html
related_pages:
  - "[[vehicle-emissions-modeling]]"
  - "[[sumo-output-files]]"
  - "[[random-trips]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[battery-electric-bus-energy-and-charger-sizing]]"
related_skills:
  - simulate-ev-charging
  - simulate-fleet-emissions
  - create-grid-network
  - generate-random-trips
related_skills_for_graph_view:
  - "[[simulate-ev-charging]]"
  - "[[simulate-fleet-emissions]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
---

# Electric Vehicle Battery and Charging

SUMO models electric vehicles through a per-vehicle **battery device** tracking state of charge over a trip, **chargingStation** infrastructure vehicles can stop at to recharge, and an optional **stationfinder** device that automatically reroutes a low-charge vehicle to the nearest reachable station before it strands itself. This is the energy/range-anxiety analogue of [[vehicle-emissions-modeling]]'s pollutant tracking — same general per-vType-device-attachment pattern, but modeling a resource the vehicle can actually run out of, with real behavioral consequences.

## Battery device and energy-consumption model

Enabled via `<param key="has.battery.device" value="true"/>` on a `vType`, alongside sizing and consumption parameters:

```xml
<vType id="ev" mass="1600" emissionClass="Energy/unknown">
    <param key="has.battery.device" value="true"/>
    <param key="maximumBatteryCapacity" value="2000"/>  <!-- Wh -->
    <param key="actualBatteryCapacity" value="400"/>    <!-- Wh, initial charge -->
    <param key="frontSurfaceArea" value="2.6"/>
    <param key="airDragCoefficient" value="0.35"/>
    <param key="rollDragCoefficient" value="0.01"/>
    <param key="propulsionEfficiency" value="0.9"/>
    <param key="recuperationEfficiency" value="0.9"/>
</vType>
```

**`emissionClass="Energy/unknown"` (aliased to `Energy/default`) is the real, correct electric-vehicle energy class — `Energy/ElectricVehicle` does not exist** and errors at startup (verified directly by triggering the error). As with HBEFA3 classes for combustion emissions, don't guess an energy-class name without checking it actually loads. `mass` is a plain `vType` attribute, not a `<param>`. `maximumBatteryCapacity`/`actualBatteryCapacity` (in Wh) still work in SUMO 1.27 but emit a deprecation warning pointing at newer names (`device.battery.capacity`/`device.battery.chargeLevel`) — both forms are currently accepted. Explicit drag/rolling-resistance/rotating-mass/efficiency parameters make the consumption model physically grounded rather than purely emission-class-driven.

## Charging stations

```xml
<chargingStation id="cs_A" lane="B2C2_0" startPos="20" endPos="60"
                 power="100000" efficiency="0.95" chargeDelay="0" chargeInTransit="0"/>
```

**`power` is in watts** (100000 = 100 kW), not kilowatts — an easy order-of-magnitude mistake. `chargeInTransit="0"` (false) means a vehicle must actually stop within the station's lane range to charge; setting it `"1"` would allow charging while merely passing through, rarely the intended realistic behavior.

## Stationfinder: automatic charge-aware rerouting

A real SUMO device (confirm via `sumo --devices-help` for the installed version) enabled via command-line flags, not a vType param:

```bash
sumo ... --device.stationfinder.probability 1 \
    --device.stationfinder.needToChargeLevel 0.15 \
    --device.stationfinder.saturatedChargeLevel 0.6 \
    --device.stationfinder.emptyThreshold 0.05 \
    --device.stationfinder.rescueAction remove \
    --device.stationfinder.radius 600
```

`needToChargeLevel` triggers the search-and-reroute; `saturatedChargeLevel` is the target charge at which the vehicle stops charging and resumes its trip; `emptyThreshold` marks a vehicle as a rescue case if it's still below this level without reaching a station; `rescueAction` (e.g. `remove`) determines what happens to an unrescuable vehicle; `radius` bounds the search distance. Enabling this purely via command-line flags (rather than embedding it in the route/vType files) means the identical route file can be run twice — with and without these flags — for a clean control-vs-treatment comparison.

## Output files

- **`--battery-output`**: one `<vehicle>` record per vehicle **per simulation step** — `actualBatteryCapacity`, `maximumBatteryCapacity`, `energyConsumed`, `totalEnergyConsumed`/`totalEnergyRegenerated`, `energyCharged`, `chargingStationId` (when actively charging). Grows large fast (tens of MB for a few hundred vehicles over an hour) — parse with streaming `iterparse`, not a full-document load.
- **`--chargingstations-output`**: one `<chargingStation>` per station with `totalEnergyCharged` (Wh) and `chargingSteps`, containing child `<vehicle>` elements with `totalEnergyChargedIntoVehicle`, `chargingBegin`, `chargingEnd` — this is the authoritative file for per-station energy delivery and session counts, since `battery-output` can over-report credited charge by a few steps of departure-acceleration overlap (see [[battery-electric-bus-energy-and-charger-sizing]]). **Correction: it is not reliably "much smaller."** By default each `<vehicle>` element also nests one `<step>` child per simulation step the vehicle spent charging, so with many short, frequent charging sessions (e.g. a scheduled bus fleet) the file can itself grow to several MB — pass `--chargingstations-output.aggregated` for the compact per-vehicle-total form if the per-step detail isn't needed, but note it is a different schema (no per-step children) from the default output.
- A control/baseline run with no charging activity shows `totalEnergyCharged="0.00"` at every station — expected, not a bug.
- **Without `stationfinder`, SUMO does not immobilize a depleted vehicle** — it keeps moving (unrealistically) and finishes its trip with an empty battery; the actual signal for "would have been stranded" in a baseline run is a "battery is depleted" warning in `sumo`'s stderr log, not a crash or a stopped vehicle in the standard outputs.

## Verified finding

On a grid network with 250 EVs given deliberately long routes and a low (20%) initial charge against a small battery, comparing a no-rerouting baseline against `stationfinder`-enabled charge-aware rerouting: **stranded/depleted vehicles fell from 220/250 (88%) to 25/250 — an 88.6% reduction** — with final state-of-charge shifting from nearly all vehicles pinned at 0-5% (baseline) to a healthy spread across 40-100% for most vehicles under `stationfinder`. 268 charging sessions across 226 distinct vehicles delivered a combined 249.5 kWh across 3 stations, versus zero charging in the baseline. This demonstrates the device does what it claims — a substantial, measurable reduction in stranding from a purely reactive, threshold-triggered rerouting rule.

See the `simulate-ev-charging` skill for the full build/run/compare workflow and a bundled analysis script.
