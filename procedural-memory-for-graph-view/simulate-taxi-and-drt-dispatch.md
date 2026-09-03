---
name: simulate-taxi-and-drt-dispatch
description: Use this skill when the user wants to model an on-demand ride-hailing, taxi, or demand-responsive transit (DRT) service in SUMO — a fleet of vehicles dynamically dispatched to pick up individually-arriving passenger ride requests, with or without ride-pooling (sharing one vehicle across multiple simultaneous passengers). Covers SUMO's built-in taxi device (has.taxi.device), <ride lines="taxi"> person reservations, the --device.taxi.dispatch-algorithm option (greedy vs. greedyShared), the dispatch log output, and how to verify ride-pooling actually occurred rather than trusting the configuration alone. Trigger on mentions of taxi, ride-hailing, DRT, demand-responsive transit, ride-pooling, ride-sharing, or on-demand mobility.
related_skills:
  - create-grid-network
  - simulate-multimodal-transit
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[simulate-multimodal-transit]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[taxi-and-drt-dispatch]]"
---

# Simulate Taxi and DRT Dispatch

Models an on-demand mobility service — a fleet of vehicles SUMO's built-in **taxi device** dynamically dispatches to serve individually-arriving passenger ride requests, with an optional ride-pooling dispatch algorithm that shares one vehicle across multiple simultaneous passengers. This is SimSkill's only demand paradigm that's neither pre-routed (random/OD/routeSampler/DUE trips) nor fixed-schedule (`simulate-multimodal-transit`'s `line`-based public transport) — requests arrive dynamically and the fleet reacts.

## Defining the taxi fleet

A taxi is an ordinary vehicle whose `vType` carries the taxi device parameter:

```xml
<vType id="taxi" vClass="taxi" personCapacity="4">
    <param key="has.taxi.device" value="true"/>
</vType>
<vehicle id="t0" type="taxi" depart="0"><route edges="..."/></vehicle>
```

`personCapacity` bounds how many simultaneous passengers one taxi can carry — set it above 1 (e.g. 4) if ride-pooling is part of the scenario; a capacity-1 fleet cannot pool regardless of dispatch algorithm. Taxis need an initial route/position like any vehicle, but otherwise idle and reposition entirely under the taxi device's control once dispatched.

## Defining ride requests

A passenger's ride request is a `<person>` carrying a `<ride>` targeting the `"taxi"` line:

```xml
<person id="p0" depart="120">
    <ride from="edgeA" to="edgeB" lines="taxi"/>
</person>
```

`depart` is when the reservation is made (not necessarily when pickup happens — that's the dispatch algorithm's decision, and the gap between them is exactly the wait time to measure). Generate a batch of these across the desired simulated time window, spread over random or clustered origin/destination edges depending on the demand pattern being studied.

## Running with a dispatch algorithm

```bash
sumo -n net.xml -r taxis.rou.xml,persons.rou.xml \
    --device.taxi.dispatch-algorithm greedyShared \
    --device.taxi.dispatch-algorithm.output dispatch.xml \
    --tripinfo-output tripinfo.xml --tripinfo-output.write-unfinished \
    --stop-output stops.xml --summary-output summary.xml
```

Key dispatch algorithms (verify the exact set available against the installed SUMO version via `sumo --help | grep -A3 dispatch-algorithm`, since this isn't necessarily stable across versions):
- `greedy` — assigns each request to its nearest available idle taxi, one passenger per trip at a time (no pooling).
- `greedyShared` — the pooling variant: can insert a new pickup/dropoff into an already-occupied taxi's route if it fits within slack/capacity constraints, sharing the ride across multiple passengers.

`--device.taxi.dispatch-algorithm.params key1:val1,key2:val2` tunes algorithm-specific parameters (e.g. maximum allowed detour) when needed.

`--tripinfo-output.write-unfinished` is important for a fair comparison — without it, a request that's still waiting (or a taxi still mid-ride) when the simulation ends is silently dropped from the output rather than showing up as unserved.

## Verifying ride-pooling actually occurred

**A pooling-capable configuration does not guarantee pooling actually happens** — under sparse demand, a `greedyShared`-dispatched fleet may never have two passengers aboard the same taxi simultaneously, especially if `personCapacity` is generous relative to request density. Don't report "pooling was modeled" from the dispatch-algorithm setting alone; verify it occurred, in at least one of these ways:

1. **Occupancy trace via TraCI** — step through the simulation and record `traci.vehicle.getPersonNumber(taxi_id)` per taxi per step; any taxi reaching occupancy ≥2 proves pooling happened. `scripts/run_taxi_scenario.py` does this automatically, also splitting each taxi's odometer distance into empty (occupancy 0) vs. occupied mileage — the basis for an empty-mileage-fraction efficiency metric.
2. **The dispatch algorithm's own log** — `--device.taxi.dispatch-algorithm.output` writes a `<DispatchInfo>` file with `<dispatchShared>` elements (vs. plain `<dispatch>`) whenever a shared assignment was made; a `type="2"` shared dispatch means both riders were aboard together at some point.
3. **tripinfo cross-check** — find two `<personinfo>` records whose `<ride>` legs show the same vehicle and overlapping/adjacent arrival times.

Cross-checking at least two of these (as opposed to trusting just the dispatch-algorithm setting) is what makes a pooling claim verifiable rather than assumed.

## Comparing dispatch strategies

Run identical network/fleet/demand through two dispatch algorithms (differing in nothing but `--device.taxi.dispatch-algorithm`), then compare with `scripts/compare_dispatch_algorithms.py`:

```bash
python scripts/run_taxi_scenario.py --net net.xml --fleet taxis.rou.xml --persons persons.rou.xml --algo greedy --label solo --outdir out/solo
python scripts/run_taxi_scenario.py --net net.xml --fleet taxis.rou.xml --persons persons.rou.xml --algo greedyShared --label pool --outdir out/pool
python scripts/compare_dispatch_algorithms.py --net net.xml --persons persons.rou.xml --run solo=out/solo --run pool=out/pool --out-dir analysis/
```

Produces a comparison table: throughput/unserved count, mean and p90 wait time (reservation-to-pickup, parsed from each `<ride>`'s `waitingTime` attribute in tripinfo), mean in-vehicle ride time, mean detour ratio (actual route length over the direct network shortest-path distance between the same O-D, via `sumolib.net.getShortestPath`), fleet total/empty vehicle-kilometres, empty-mileage fraction, and the pooling-verification numbers above.

## What the solo-vs-pooling comparison tends to show

Measured on a 4x4-block grid, 10 taxis (capacity 4), 80 requests over 1800s: pooling (`greedyShared`) cut fleet vehicle-kilometres ~11% and empty-mileage fraction from 38% to 34%, at a small in-vehicle ride-time cost (+3%, the expected detour from sharing). Passenger wait time can *improve* under pooling too, not just get better fleet efficiency at wait-time's expense — `greedyShared`'s more aggressive re-optimization of vehicle-to-request assignments outweighed any detour-related wait penalty in this scenario. **This is demand-density-dependent**: at low request density relative to fleet capacity, occupancy rarely exceeds 2 and only a modest fraction of riders actually share a ride — don't generalize a low-density result's near-zero net cost to higher-density scenarios without re-measuring; report the observed pooling rate (taxis-that-pooled / fleet size, or served-via-shared-dispatch / total requests) alongside any efficiency claim.

## Gotchas

- **`personCapacity` above 1 is necessary but not sufficient for pooling** — verify occupancy actually reached ≥2 rather than assuming a `greedyShared` + capacity-4 fleet pooled anyone.
- **`--tripinfo-output.write-unfinished` matters for a fair unserved-request count** — omitting it silently drops still-in-progress requests/rides from the output rather than counting them.
- **The exact set of dispatch algorithms available is SUMO-version-dependent** — check `sumo --help` on the installed version rather than assuming `greedy`/`greedyShared` are the only options.
- **Two runs being compared must be identical except for the dispatch-algorithm option** — diff the two `.sumocfg`/command invocations directly to confirm before trusting a comparison; any other difference (different demand realization, different fleet size) confounds the result.

## Related

- `create-grid-network` / any network skill for the base topology.
- `simulate-multimodal-transit` — SimSkill's fixed-schedule transit skill (`line`-based, scheduled), the closest existing demand paradigm before this one; contrast dynamically-dispatched on-demand service against a published schedule.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for taxi/DRT tripinfo (`<personinfo><ride waitingTime=...>`) parsing.
- [[taxi-and-drt-dispatch]] — the underlying SUMO concepts (taxi device mechanics, dispatch algorithms, the dispatch log format, and the verified pooling-efficiency-vs-detour finding).
