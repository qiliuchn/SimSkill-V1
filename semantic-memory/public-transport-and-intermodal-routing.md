---
summary: SUMO models public transport via scheduled busStop-serving vehicles carrying a `line` attribute, and resolves intermodal person demand (walk-or-ride mode choice) automatically through duarouter once persons request mode "public" and a scheduled line with pedestrian access exists.
keywords:
  - public-transport
  - intermodal-routing
  - busStop
  - persontrips
  - modal-split
created: 2026-07-23T15:53:30
last_updated: 2026-09-01T10:21:28
sources:
  - "[[episodic-memory/2026-07-23_15-38-33/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_15-38-33/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Simulation/Public_Transport.html
  - https://sumo.dlr.de/docs/Simulation/Intermodal_Routing.html
  - https://sumo.dlr.de/docs/Simulation/Pedestrians.html
related_pages:
  - "[[sumo-output-files]]"
  - "[[random-trips]]"
  - "[[duarouter]]"
  - "[[abstract-network-generation]]"
  - "[[taxi-and-drt-dispatch]]"
  - "[[rail-simulation-and-railsignal]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[gtfs-import-and-pt-representation-semantics]]"
  - "[[accessibility-measurement-and-transport-equity]]"
  - "[[car-to-transit-intermodal-transfer-and-park-and-ride]]"
  - "[[intermodal-transfer-and-person-stage-semantics-in-sumo]]"
  - "[[transit-network-design-and-frequency-setting]]"
related_skills:
  - simulate-multimodal-transit
  - create-grid-network
  - generate-random-trips
  - convert-trips-to-routes
  - equilibrate-endogenous-mode-choice-with-transit-supply-feedback
  - design-bus-stop-placement-type-and-spacing
  - design-transit-service-plan-under-a-bus-hour-budget
related_skills_for_graph_view:
  - "[[simulate-multimodal-transit]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[equilibrate-endogenous-mode-choice-with-transit-supply-feedback]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
---

# Public Transport and Intermodal Routing

SUMO supports scenarios where people, not just vehicles, are the simulated agents — choosing between walking and riding public transport. This requires three things layered on top of a normal vehicle network: pedestrian infrastructure, scheduled public-transport lines, and person demand that can express mode choice. Contrast with [[taxi-and-drt-dispatch]], where a person's `<ride>` targets a dynamically-dispatched taxi fleet rather than a fixed, published `line` schedule, and with [[rail-simulation-and-railsignal]], which covers SUMO's structurally distinct rail mode (bidirectional single track, `rail_signal` conflict arbitration) rather than buses running as ordinary road vehicles.

## Pedestrian infrastructure

A network built by `netgenerate`/`netconvert` without pedestrian options has no sidewalks or crossings. Add them with a `netconvert` pass over the existing `.net.xml`:

```bash
netconvert -s base.net.xml --sidewalks.guess --crossings.guess --walkingareas -o pedestrian.net.xml
```

Resulting structure: every edge gains a pedestrian-only sidewalk lane (the original driving lane(s) become `disallow="pedestrian"`); crossings appear as `<edge function="crossing">` (not a distinct `<crossing>` element); `--walkingareas` adds `<edge function="walkingarea">` polygons connecting sidewalks/crossings at junctions so pedestrians aren't confined to moving edge-by-edge. See [[abstract-network-generation]] for the base network step this precedes.

## Public-transport lines: busStop + access + schedule

A `<busStop>` (declared in an additional file) sits on a driving lane and needs an `<access>` child linking it to the adjacent sidewalk lane, or pedestrians have no path to reach/board it:

```xml
<additional>
    <busStop id="ew_1" lane="A2B2_1" startPos="50.0" endPos="70.0" lines="ew" friendlyPos="true">
        <access lane="A2B2_0" pos="60.0"/>
    </busStop>
</additional>
```

A line becomes an actual PT service via vehicles that reference its stops with `<stop busStop="..." duration="..."/>` and carry a `line` attribute:

```xml
<vehicle id="bus_ew_0" type="bus" line="ew" depart="0" departPos="free">
    <route edges="A2B2 B2C2 C2D2 D2E2"/>
    <stop busStop="ew_1" duration="20" until="35"/>
    <stop busStop="ew_2" duration="20" until="73"/>
</vehicle>
```

**Critical requirement: the intermodal person router only treats a line as usable when its stops carry an absolute `until=` arrival timetable.** A `<stop>` with only `duration=` (a dwell time, no fixed schedule) is not enough — routing silently falls back to walk-only for every person, with no error or obvious warning. Repeat the same route+stops pattern as a series of explicit `<vehicle>` elements (one per departure, `until` times computed from a chosen headway) rather than a single `<flow>` if the flow's stops don't carry timetables. This is the single most important gotcha in the whole workflow — it fails silently rather than loudly, so verify a nonzero ride count after routing, not just a clean exit code.

**The same attribute fails silently in the opposite direction too.** SUMO departs a stop at `max(arrival + duration, until)`, so a timetable that is merely *generous* makes every PT vehicle schedule-adherent and erases traffic delay from its measured round-trip time entirely — a measured cycle of 1216 s with 10,827 background cars and 1216 s with none. Too loose an `until=` is as dangerous as none at all, just harder to notice. See [[intermodal-transfer-and-person-stage-semantics-in-sumo]] for the measurement and the fix (calibrate the published timetable from an uncongested buses-only run first).

## Intermodal person demand and routing

Generate persons with mode choice via `randomTrips.py`:

```bash
python randomTrips.py -n pedestrian.net.xml -o persons.trips.xml --persontrips --persontrip.modes public -b 0 -e 3600 --period 12
```

`--persontrip.modes public` (values: `car`, `public`, `taxi`, combinable) is the real flag controlling which modes a person may choose among — don't assume a specific "transfer" flag (e.g. an invented `--persontrip.transfer.walk-public`) exists without checking `--help` first; exact intermodal flag names have shifted across SUMO releases and a task description or tutorial may reference one that no longer (or never did) exist.

Route with `duarouter`, passing the PT vehicles, the person trips, and the busStops together:

```bash
duarouter -n pedestrian.net.xml --additional-files busstops.add.xml -r pt_vehicles.rou.xml,persons.trips.xml -o routed.rou.xml
```

No separate "transfer" step is needed — once a person's mode set includes `public`, a scheduled line exists, and its stops have pedestrian access, `duarouter` automatically resolves each person's plan into concrete `<walk>`/`<access>`/`<ride>` legs (walk to the stop, ride the line, walk from the destination stop). `duarouter` does not echo the PT vehicles into a separate "PT-only" file — the eventual simulation run needs to load both the PT vehicle route file and the routed person file (comma-separated `-r`, or merged).

## What the results tend to look like

On a compact/dense network, riding transit is not automatically faster door-to-door — per-stop dwell time plus waiting for the next scheduled departure can outweigh a bus's speed advantage over walking a short distance directly. Seeing a modal split favor walking, or bus riders showing *longer* mean travel time than walkers, is a legitimate outcome reflecting the network's actual geometry/headway, not a sign of a bug — always check whether the trip lengths and headway make the result plausible before treating it as broken.

See the `simulate-multimodal-transit` skill for the full pipeline with bundled scripts, and [[sumo-output-files]] for the `<personinfo>`/`<walk>`/`<access>`/`<ride>` output schema this workflow's analysis reads from. [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]] extends the `<busStop>`/`<access>` mechanics documented here into a full placement/type/spacing design study, including the verified finding that `<stop parking="true">` fully vacates the lane while hiding a real re-entry cost inside the dwell timestamp. Everything above assumes hand-authored stops/lines with an invented schedule; [[gtfs-import-and-pt-representation-semantics]] covers the alternative of importing a *real* published GTFS feed or OSM public-transport relations instead, including how much of a real timetable survives that import. Everything above also assumes the person's whole trip is walk-or-ride; [[car-to-transit-intermodal-transfer-and-park-and-ride]] covers `modes="car public"` park-and-ride trips, where the car leg is a genuinely separate vehicle the router never actually parks in a parkingArea unless a post-processing fix injects the stop explicitly.
