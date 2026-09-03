---
name: simulate-fleet-emissions
description: Use this skill when the user wants to model or analyze traffic emissions (CO2, NOx, PMx, fuel consumption) in SUMO, especially with a heterogeneous/mixed vehicle fleet (different vehicle types with different emission classes, e.g. modern vs. older cars, vans, heavy-duty trucks). Covers defining a vTypeDistribution with SUMO/HBEFA3 emission classes, assigning it to generated demand, running the simulation with both per-vehicle emission-trajectory output and per-edge aggregated emission data, and analyzing/plotting per-pollutant totals by vehicle type and by location. Trigger on mentions of emissions, CO2/NOx/PMx/pollutants, fuel consumption, HBEFA, vTypeDistribution, mixed/heterogeneous fleet, emission hotspots, or "environmental impact" of traffic.
---

# Simulate Fleet Emissions

Models the pollutant output of a heterogeneous vehicle fleet on a SUMO network — as opposed to the travel-time/throughput focus of `run-simulation` + `analyze-simulation-outputs` — by giving vehicles distinct HBEFA3 emission classes, enabling SUMO's emission tracking, and reporting who (which vehicle type) and where (which edges) the emissions actually come from. This is a fundamentally different analysis dimension: a network can look fine on travel-time metrics while still being dominated by a small share of high-emitting vehicles or concentrated at a few congested approaches.

## The workflow

1. **Network**: any existing network-creation skill works (`create-grid-network`, etc.) — nothing emissions-specific here, except that signalized junctions matter more than usual, since stop-go behavior at lights is a real emissions driver (see Gotchas for `netgenerate`'s TLS-assignment quirk).
2. **Define the fleet** as a `<vTypeDistribution>` (an "additional" file) with one `<vType>` per class, each carrying an `emissionClass="HBEFA3/<code>"` attribute and a `probability` (shares should sum sensibly — SUMO normalizes them, but write them to already sum to 1 for clarity). See "Defining the fleet" below for the exact syntax and validated class codes.
3. **Generate and assign demand**: use `generate-random-trips` (`randomTrips.py`) as usual, but pass `--trip-attributes 'type="<distribution-id>"'` and `--additional-files <vtypes-file>` so every generated trip references the distribution; when the trips are routed (either via `randomTrips.py --route-file` or a separate `convert-trips-to-routes`/`duarouter` call), duarouter samples a concrete vehicle type per vehicle from the distribution and writes it into the output route file — you can verify this by counting `type="..."` occurrences in the resulting `.rou.xml`.
4. **Run the simulation with emissions enabled** — two independent outputs, both needed:
   - `--emission-output <file>` plus `--device.emissions.probability 1.0` (or another nonzero share) — the emissions device attaches to each selected vehicle; per-step per-vehicle pollutant data goes to the `--emission-output` file, and a per-vehicle **totals** summary appears as an `<emissions>` child element inside each vehicle's `<tripinfo>` entry (so `--tripinfo-output` alone, with the device enabled, already gives you the per-vehicle totals you likely want — the raw `--emission-output` trajectory is step-by-step and can get very large for anything but a short run or small fleet).
   - An `<edgeData type="emissions">` additional file (a meandata definition, same mechanism as any other edgeData output — see [[sumo-output-files]]) for **aggregated per-edge** pollutant totals over the run.
5. **Analyze**: `scripts/analyze_emissions.py` parses the tripinfo emissions + edgeData emissions files and produces per-vehicle-type totals/shares/per-km rates, plus two plots (a per-pollutant bar chart by type, and a spatial CO2 hotspot map using the network's own edge geometry).

## Defining the fleet

```xml
<additional>
    <vTypeDistribution id="fleet">
        <vType id="car_modern" vClass="passenger" emissionClass="HBEFA3/PC_G_EU4"
               probability="0.55" length="4.5" maxSpeed="14.0" accel="2.6" decel="4.5" sigma="0.5"/>
        <vType id="car_old" vClass="passenger" emissionClass="HBEFA3/PC_G_EU2"
               probability="0.25" length="4.5" maxSpeed="13.0" accel="2.0" decel="4.0" sigma="0.6"/>
        <vType id="van_diesel" vClass="delivery" emissionClass="HBEFA3/LDV_D_EU4"
               probability="0.15" length="6.5" maxSpeed="12.5" accel="1.8" decel="4.0" sigma="0.5"/>
        <vType id="truck_hdv" vClass="truck" emissionClass="HBEFA3/HDV"
               probability="0.05" length="12.0" maxSpeed="10.0" accel="1.0" decel="4.0" sigma="0.5"/>
    </vTypeDistribution>
</additional>
```

- `emissionClass` follows SUMO's HBEFA3 naming (`HBEFA3/<vehicle-category>_<fuel>_<euro-standard-or-class>`, e.g. `PC_G_EU4` = passenger car, gasoline, Euro 4; `HDV` = heavy-duty vehicle as a whole class). Fetch https://sumo.dlr.de/docs/Models/Emissions/HBEFA3-based.html for the full list rather than guessing — an invalid string makes `sumo` fail at startup.
- `vClass` (`passenger`/`delivery`/`truck`/etc.) is separate from `emissionClass` — it governs lane/edge access permissions, not emissions math; set both, don't conflate them.
- Give each type distinct physical parameters (`length`, `maxSpeed`, `accel`/`decel`) where it's realistic (a truck is longer and slower-accelerating than a car) — this also affects the emissions result indirectly, since acceleration/deceleration behavior changes instantaneous emission rates in HBEFA3.
- `$SUMO_HOME/tools/createVehTypeDistribution.py` can generate a distribution from parameter distributions instead of hand-listing types — check its `--help` if the user wants many types or randomized parameters within each type rather than a small hand-curated set.

## Assigning the fleet to demand

```bash
python <generate-random-trips>/scripts/random_trips.py -n net.xml -b 0 -e 3600 --period 3.0 \
    --trip-attributes 'type="fleet"' --additional-files vtypes.add.xml --route-file routes.rou.xml
```

If routing separately via `convert-trips-to-routes` instead of `--route-file`, pass the same `--additional-files vtypes.add.xml` to `duarouter` so it can resolve the `type="fleet"` reference and sample concrete types while routing.

## Running with emissions enabled

```bash
sumo -n net.xml -r routes.rou.xml -a edgedata_emissions.add.xml \
    --tripinfo-output tripinfo.xml --emission-output emission_trajectory.xml \
    --device.emissions.probability 1.0 --summary-output summary.xml
```

```xml
<!-- edgedata_emissions.add.xml -->
<additional>
    <edgeData id="edgeEmissions" type="emissions" file="edge_emissions.xml" period="3600" begin="0" excludeEmpty="true"/>
</additional>
```

`period` is the aggregation window (seconds) — set it to cover your whole analysis window for network-wide per-edge totals, or shorter if you want emissions over time. `excludeEmpty="true"` keeps the output file from listing every edge with zero traffic, which matters on larger networks.

## Analyzing the results

```bash
python scripts/analyze_emissions.py --tripinfo tripinfo.xml --edge-emissions edge_emissions.xml \
    --net-file net.xml --out-dir analysis/
```

Produces `emission_summary.csv` (per-type totals, fleet-wide pollutant share %, and mg/veh-km rate, for CO2/NOx/PMx/fuel), `edge_co2_ranking.csv`, and two plots (`emissions_by_type.png`, `co2_hotspot.png`). The key thing this analysis is built to surface: **a vehicle type's share of a pollutant is very often wildly disproportionate to its share of the fleet** — a small percentage of heavy-duty/older vehicles routinely accounts for a majority of NOx/PMx even though they contribute a much smaller (sometimes even minority) share of CO2/fuel, since CO2/fuel scale more with vehicle-km traveled while NOx/PMx scale more steeply with vehicle class and age.

## Gotchas

- **`--tls.guess` alone does not reliably signalize a uniform grid** — `netgenerate`'s TLS-guessing heuristic can leave every junction as `priority`-controlled even when guessing is enabled. If the goal is "every junction should have a traffic light," pass `--default-junction-type traffic_light` (or `-j traffic_light`) directly instead of relying on `--tls.guess` (see `create-grid-network`'s own gotchas section, which already recommends this).
- **The per-step `--emission-output` file is large.** It's a per-vehicle-per-timestep trace — for anything beyond a short run or small fleet, it can reach tens of megabytes quickly. If all you need is per-vehicle *totals* (not the full trajectory), the `<emissions>` child inside `--tripinfo-output` (enabled by the same `--device.emissions.probability`) already has it — you may not need to keep the raw `--emission-output` file around at all once totals are extracted, only the aggregated files.
- **`PMx_abs` can be legitimately ~0 for some HBEFA3 classes** (e.g. modern diesel with particulate filters) — don't mistake a near-zero value for a data or config bug; cross-check against the HBEFA3 docs for that class before assuming something's broken.
- **Emission totals in tripinfo/edgeData are in milligrams** (fuel too) — convert explicitly (divide by 1000 for grams, by 1e6 for kg) before reporting; mixing up units is an easy way to be off by 1000x.
- **`vClass` and `emissionClass` are independent attributes** — setting one does not imply a matching value for the other; both need to be set explicitly per vType.

## Related

- `create-grid-network`, `generate-random-trips`, `convert-trips-to-routes`, `run-simulation` — the network/demand/routing/execution steps this workflow builds directly on top of.
- [[sumo-output-files]] documents the general tripinfo/edgeData XML schema this skill's `<emissions>` child and `type="emissions"` edgeData extend.
- `analyze-simulation-outputs` is the travel-time/throughput analogue of this skill's `scripts/analyze_emissions.py` — use that one instead when the question is about speed/delay/congestion rather than pollutants.
- `model-urban-freight-delivery-tours` — uses this skill's mixed-fleet HBEFA3 emission-class setup to quantify a truck-route restriction's exposure-vs-emissions exchange rate, finding a case where the exempt vehicle class's cleaner per-km emission factor made total freight emissions **fall** with rising restriction coverage, refuting the standard "restriction reduces exposure but worsens emissions" framing for that fleet.
