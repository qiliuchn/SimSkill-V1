---
name: simulate-ev-charging
description: Use this skill when the user wants to model electric vehicles in SUMO — battery state of charge, energy consumption, charging stations, or charge-aware routing/rerouting to a charger before running out of power. Covers the battery device and its energy-consumption model, chargingStation infrastructure, the stationfinder device for automatic charge-aware rerouting, and the battery-output/chargingstations-output files. Trigger on mentions of electric vehicles, EVs, battery simulation, state of charge, charging stations, range anxiety, or stationfinder.
---

# Simulate EV Charging

Models electric vehicles in SUMO — battery depletion over a trip, physical energy consumption, stopping at charging stations, and (optionally) automatic charge-aware rerouting via the `stationfinder` device before a vehicle strands itself. This is SimSkill's only skill covering vehicle *energy* as a depletable resource with real consequences (stranding), as opposed to `simulate-fleet-emissions`, which models pollutant output but never anything the vehicle can run out of.

## The battery device

Enable it on a `vType` (an additional file) via a `<param>` child, alongside sizing and energy-consumption parameters:

```xml
<vType id="ev" vClass="passenger" mass="1600" emissionClass="Energy/unknown">
    <param key="has.battery.device" value="true"/>
    <param key="maximumBatteryCapacity" value="2000"/>  <!-- Wh -->
    <param key="actualBatteryCapacity" value="400"/>    <!-- Wh, initial charge -->
    <param key="maximumPower" value="60000"/>
    <param key="frontSurfaceArea" value="2.6"/>
    <param key="airDragCoefficient" value="0.35"/>
    <param key="rollDragCoefficient" value="0.01"/>
    <param key="radialDragCoefficient" value="0.5"/>
    <param key="rotatingMass" value="100"/>
    <param key="constantPowerIntake" value="100"/>
    <param key="propulsionEfficiency" value="0.9"/>
    <param key="recuperationEfficiency" value="0.9"/>
</vType>
```

- **`emissionClass="Energy/unknown"` (aliased to `Energy/default`) is the real electric-vehicle energy class** — the more intuitive-sounding `Energy/ElectricVehicle` does **not** exist and errors at startup (verified directly). Check `sumo --help`/the actual error message before assuming a class name, the same way [[vehicle-emissions-modeling]]'s HBEFA3 classes need verifying rather than guessing.
- `maximumBatteryCapacity`/`actualBatteryCapacity` (Wh) still work as of SUMO 1.27 but trigger a deprecation warning recommending `device.battery.capacity`/`device.battery.chargeLevel` instead — both forms are accepted; expect the newer names to eventually be the only ones.
- `mass` is a plain `vType` attribute (not a `<param>`), unlike everything else here.
- The drag/rolling-resistance/efficiency params make the energy-consumption model physically explicit rather than relying purely on the emission-class lookup table — set a low initial charge relative to `maximumBatteryCapacity` (e.g. 15-25%) if the goal is to actually see depletion/stranding behavior within a scenario's timeframe.

## Charging stations

```xml
<additional>
    <chargingStation id="cs_A" lane="B2C2_0" startPos="20" endPos="60"
                     power="100000" efficiency="0.95" chargeDelay="0" chargeInTransit="0"/>
</additional>
```

**`power` is in watts, not kilowatts** — `100000` = 100 kW fast charging, an easy 1000x error to make. `chargeInTransit="0"` (false) requires the vehicle to actually stop at the station to charge — set it `"1"` only if the scenario wants charging while merely passing through (uncommon; usually not what's wanted for a realistic "vehicle must wait to charge" scenario).

## Charge-aware rerouting: the stationfinder device

A real, documented SUMO device (confirm via `sumo --devices-help` before assuming it exists in a given SUMO version) that automatically reroutes a vehicle to the nearest reachable charging station once its state of charge drops below a threshold, waits/charges, then resumes its original trip. **Enabled via command-line flags, not a vType param:**

```bash
sumo ... --device.stationfinder.probability 1 \
    --device.stationfinder.needToChargeLevel 0.15 \
    --device.stationfinder.saturatedChargeLevel 0.6 \
    --device.stationfinder.emptyThreshold 0.05 \
    --device.stationfinder.rescueAction remove \
    --device.stationfinder.radius 600
```

- `needToChargeLevel` — state-of-charge fraction below which the vehicle starts searching for and rerouting to a station.
- `saturatedChargeLevel` — target state-of-charge at which it stops charging and resumes its trip.
- `emptyThreshold` — state-of-charge fraction below which a vehicle that still hasn't reached a station is considered a rescue case.
- `rescueAction` — what happens to a vehicle that can't make it (`remove` tows/removes it from the simulation; other values exist, check the docs for the current option set).
- `radius` — search radius (m) for candidate stations.

Enabling this via the command line (rather than baking it into the vType/route file) means the *exact same* route file can be run twice — once with, once without these flags — for a clean baseline-vs-rerouting comparison.

## Outputs

- `--battery-output <file>`: one `<vehicle>` record **per vehicle per step** — `actualBatteryCapacity`, `maximumBatteryCapacity`, `energyConsumed`, `totalEnergyConsumed`, `totalEnergyRegenerated`, `energyCharged`, `chargingStationId` (when charging), plus position/speed. This file gets large fast (tens of MB for a few hundred vehicles over an hour) — parse it with a streaming `iterparse`, and don't assume it's small enough to load with `ElementTree.parse()`.
- `--chargingstations-output <file>`: one `<chargingStation>` element per station with `totalEnergyCharged` (Wh) and `chargingSteps`, each containing child `<vehicle>` elements with `totalEnergyChargedIntoVehicle`, `chargingBegin`, `chargingEnd` — this is the file to read for "how much energy did each station deliver" and "how many charging sessions happened," much smaller than battery-output.
- Neither file exists (or shows zero activity) if no vehicle actually charges — a chargeless baseline run's `chargingstations.xml` will show `totalEnergyCharged="0.00"` at every station, which is the expected control-condition result, not a bug.

## Analyzing the comparison

```bash
python scripts/analyze_ev_charging.py --baseline scenario_baseline/ --stationfinder scenario_stationfinder/
```

Reports, per scenario: how many vehicles ran their battery down to ~0 (a proxy for "would be stranded"), the final state-of-charge distribution across bins, energy delivered per station, and total charging sessions/distinct vehicles charged — then a head-to-head reduction-in-stranded-vehicles comparison. Note: **without `stationfinder`, SUMO does not immobilize a vehicle whose battery reaches 0** — it keeps "driving" (physically unrealistic, since there's no separate low-level enforcement of this in the base simulation) and finishes its trip with a depleted battery; `stderr` logs a "battery is depleted" warning per vehicle, which is the actual signal to count for "would-be-stranded" in a baseline run, not a crash or a stopped vehicle in the output.

## Related

- `create-grid-network` (or any network skill) for the base topology.
- `generate-random-trips` — bias toward longer trips (`--min-distance`, `--intermediate`) so a small initial charge actually depletes meaningfully within the scenario's timeframe; use the same `--trip-attributes type="..."` + `--additional-files` pattern as `simulate-fleet-emissions` to assign the EV vType.
- `convert-trips-to-routes` — note `duarouter` copies the full vType (including all battery params) into its output route file, so the *original* vType additional-file should NOT also be loaded when running `sumo`, or it errors on a duplicate vType definition.
- `run-simulation` — general command-line run mechanics this skill's `--battery-output`/`--chargingstations-output`/`--device.stationfinder.*` flags plug into.
- [[electric-vehicle-battery-and-charging]] — the underlying SUMO concepts (battery/energy model, chargingStation semantics, stationfinder thresholds, output schemas) this skill's workflow is built on.
