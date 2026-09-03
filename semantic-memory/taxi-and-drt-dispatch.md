---
summary: SUMO's built-in taxi device dynamically dispatches a fleet of has.taxi.device-equipped vehicles to serve individually-arriving <ride lines="taxi"> passenger reservations, with dispatch-algorithm choice (greedy vs. greedyShared) determining whether rides are pooled across simultaneous passengers.
keywords:
  - taxi-device
  - ride-hailing
  - DRT
  - demand-responsive-transit
  - dispatch-algorithm
  - ride-pooling
  - greedyShared
created: 2026-07-24T15:05:00
last_updated: 2026-07-24T15:05:00
sources:
  - "[[episodic-memory/2026-07-24_14-35-24/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_14-35-24/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Taxi.html
  - https://sumo.dlr.de/docs/Specification/Persons.html
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
  - "[[random-trips]]"
related_skills:
  - simulate-taxi-and-drt-dispatch
  - simulate-multimodal-transit
  - create-grid-network
  - run-simulation
related_skills_for_graph_view:
  - "[[simulate-taxi-and-drt-dispatch]]"
  - "[[simulate-multimodal-transit]]"
  - "[[create-grid-network]]"
  - "[[run-simulation]]"
---

# Taxi and DRT Dispatch

SUMO models on-demand mobility — ride-hailing, taxi service, demand-responsive transit (DRT) — via a built-in **taxi device**: a fleet of vehicles dynamically dispatched to serve individually-arriving passenger ride requests, rather than following a pre-computed route ([[random-trips]] et al.) or a published schedule ([[public-transport-and-intermodal-routing]]). Requests arrive at arbitrary simulated times and the dispatch algorithm decides, live, which idle (or already-en-route, if pooling is enabled) vehicle serves each one.

## Fleet and request definitions

A taxi is an ordinary vehicle whose `vType` carries a device parameter:

```xml
<vType id="taxi" vClass="taxi" personCapacity="4">
    <param key="has.taxi.device" value="true"/>
</vType>
```

`personCapacity` bounds simultaneous passengers; it must be above 1 for ride-pooling to be physically possible at all. A ride request is a `<person>` with a `<ride>` targeting the reserved line name `"taxi"`:

```xml
<person id="p0" depart="120">
    <ride from="edgeA" to="edgeB" lines="taxi"/>
</person>
```

`depart` marks when the reservation is made; actual pickup time is the dispatch algorithm's decision, and the gap between the two is the passenger's wait time.

## Dispatch algorithms

Set via `--device.taxi.dispatch-algorithm`; the log is written via `--device.taxi.dispatch-algorithm.output`, producing a `<DispatchInfo>` file with `<dispatch>` (solo) or `<dispatchShared>` (pooled) elements. **The exact set of available algorithms is SUMO-version-dependent** — check `sumo --help | grep -A3 dispatch-algorithm` on the installed version rather than assuming a fixed list. Verified present in SUMO 1.27.1:

- `greedy` — assigns each request to its nearest available idle taxi; one passenger (or one party) per trip, no pooling.
- `greedyShared` — the pooling variant, which can insert a new pickup/dropoff into an already-occupied taxi's route if it fits capacity/detour constraints, sharing one vehicle across multiple simultaneous passengers. A `<dispatchShared type="2">` log entry indicates both riders were aboard together at some point.

`--device.taxi.dispatch-algorithm.params key:val,...` tunes algorithm-specific behavior (e.g. maximum allowed detour) when available.

## Verifying pooling actually occurred

**A `greedyShared`-configured fleet with capacity > 1 does not guarantee pooling ever actually happens** — under sparse demand relative to fleet size, a taxi may never have two passengers aboard simultaneously even though the algorithm and capacity technically permit it. Verify, don't assume, via at least one of:

1. A live occupancy trace (`traci.vehicle.getPersonNumber(taxi_id)` per step) — any value ≥2 proves pooling occurred at least once, and the trace also yields empty-vs-occupied mileage split (an efficiency metric: empty-mileage fraction).
2. The dispatch log's `<dispatchShared>` count, especially `type="2"` entries (both riders aboard together, not just sequentially assigned).
3. A tripinfo cross-check: two `<personinfo><ride>` records sharing the same vehicle with overlapping ride windows.

Reporting a pooling rate (e.g. taxis-that-reached-occupancy-≥2 / fleet size, or requests-served-via-shared-dispatch / total requests) alongside any efficiency claim keeps the claim honest about how much pooling the specific demand density actually produced.

## Output and metrics

`<personinfo><ride>` in tripinfo carries `waitingTime` (reservation-to-pickup — the primary DRT service-quality metric), `duration` (in-vehicle time), and `routeLength` (actual distance traveled). Dividing `routeLength` by the direct network shortest-path distance between the same origin/destination (via `sumolib.net.getShortestPath`) gives a per-ride detour ratio — the cost side of pooling. `--tripinfo-output.write-unfinished` should always be set when comparing runs for unserved-request counts: without it, a request still waiting (or a ride still in progress) at simulation end is silently omitted from output rather than counted as unserved.

## Measured solo-vs-pooling comparison

On a 4x4-block grid, 10 taxis (capacity 4), 80 ride requests over 1800s, identical demand across both dispatch algorithms: `greedyShared` cut fleet vehicle-kilometres ~11% and empty-mileage fraction from 38% to 34% versus `greedy`, at a modest in-vehicle ride-time cost (+3%, the expected pooling detour). Notably, mean passenger wait time also *improved* under pooling (-32%) rather than trading off against it — attributed to `greedyShared` re-optimizing vehicle-to-request assignments more aggressively than `greedy`'s simpler nearest-idle-taxi matching, confirmed not to be a measurement artifact since the two runs' configs were verified identical except for the dispatch-algorithm option. This result is demand-density-dependent: occupancy never exceeded 2 (of capacity 4) and only ~25% of riders actually shared a ride in this scenario, so the small detour cost reflects sparse demand specifically — a denser scenario would likely show pooling forced onto more riders with a correspondingly larger detour cost. Always measure the actual pooling rate before generalizing an efficiency-vs-detour finding across demand densities.

See the `simulate-taxi-and-drt-dispatch` skill for the full build/run/verify/compare workflow and bundled scripts.
