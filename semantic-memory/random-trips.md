---
summary: randomTrips.py generates random origin-destination vehicle, pedestrian, or persontrip demand for a SUMO network, with controls for traffic volume, fringe-biased through-traffic, and optional automatic routing via duarouter.
keywords:
  - randomTrips
  - trip-generation
  - demand
  - fringe-factor
  - insertion-rate
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T17:26:26
sources:
  - "[[raw-materials/Trip - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/Tools/Trip.html
  - "[[raw-materials/sumodocswebdocsToolsTrip.md at main.md]]"
  - https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Tools/Trip.md
related_pages:
  - "[[od2trips]]"
  - "[[duarouter]]"
  - "[[abstract-network-generation]]"
  - "[[openstreetmap]]"
  - "[[routesampler]]"
  - "[[vehicle-emissions-modeling]]"
  - "[[activitygen]]"
  - "[[evacuation-clearance-time-analysis]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[electric-vehicle-battery-and-charging]]"
related_skills:
  - generate-random-trips
  - convert-trips-to-routes
  - calibrate-demand-with-routesampler
  - simulate-fleet-emissions
  - simulate-multimodal-transit
  - simulate-ev-charging
related_skills_for_graph_view:
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[simulate-fleet-emissions]]"
  - "[[simulate-multimodal-transit]]"
  - "[[simulate-ev-charging]]"
---

# Random Trips

`randomTrips.py` (in `$SUMO_HOME/tools/`) generates random origin-destination demand for an existing `.net.xml` — the usual next step after building a network, whether synthetic ([[abstract-network-generation]]) or real ([[openstreetmap]]). Its demand is temporally flat by construction; see [[activitygen]] for SUMO's population/activity-based alternative, which produces genuine time-of-day structure (a bimodal commute peak) instead.

## Basic usage

```bash
python randomTrips.py -n net.xml -o trips.trips.xml
python randomTrips.py -n net.xml -o trips.trips.xml -b 0 -e 3600 --period 18
python randomTrips.py -n net.xml --route-file routes.rou.xml
```

`-n`/`--net-file` and `-o`/`--output-trip-file` are the essentials; `-b`/`--begin` and `-e`/`--end` set the time window.

## Controlling traffic volume

Exactly one of three equivalent controls is normally used:
- `--period <FLOAT>` — seconds between departures (smaller = more traffic; `1/period` = vehicles/second). Comma/space-separated values divide the time window into sub-periods.
- `--insertion-rate <FLOAT>` — vehicles/hour directly.
- `--insertion-density <FLOAT>` — vehicles/hour/km of road, useful when comparing networks of different sizes.

## Shaping where trips start and end

- `--fringe-factor <FLOAT|max>` boosts the relative probability that a trip starts/ends at a network-boundary ("fringe") edge, modeling through-traffic; `max` forces every trip to start and end at the fringe.
- `--min-distance`/`--max-distance` bound the straight-line start→end distance (the latter is particularly worth setting for `--pedestrians`, to avoid absurdly long walking trips).
- `--intermediate <INT>` adds via-waypoints for longer, multi-edge journeys.
- `--weights-prefix <STR>` loads custom edge source/destination/via probabilities from `<prefix>.{src,dst,via}.xml`; `--weights-output-prefix` saves whichever probabilities were actually used.

## Modes

- Default: SUMO vehicle trips (`<trip>` elements), optionally with `--vehicle-class` to set the class and matching edge permissions.
- `--pedestrians`: generates walking trips instead.
- `--persontrips`: generates `<persontrip>` elements with mode choice (walk/car/public transport) rather than fixed-mode trips. Pair with `--persontrip.modes public` to actually enable walk-or-transit choice, and route the result with `duarouter` against a network that has both pedestrian infrastructure and a scheduled public-transport line — see [[public-transport-and-intermodal-routing]] for the full setup and its gotchas.

`--min-distance`/`--intermediate` are also the levers for deliberately biasing toward long, multi-edge trips — useful when a scenario needs meaningful depletion of a depletable per-vehicle resource, e.g. an EV's battery (see [[electric-vehicle-battery-and-charging]]).

## Routing directly

`randomTrips.py` doesn't validate that a sampled origin/destination pair is actually reachable — that's [[duarouter]]'s job. Passing `--route-file <FILE>` instead of `-o` makes the script call duarouter internally, discard unroutable trips, and write a validated `.rou.xml` directly, at the cost of less routing control than calling duarouter separately (see [[duarouter]]).

## Reproducibility and other controls

`--seed <INT>` gives reproducible randomness; `--random` uses a fresh seed each run. `--prefix <STR>` namespaces generated ids — required when combining demand from multiple `randomTrips.py` calls (e.g. cars + pedestrians in one simulation) to avoid id collisions. `--trip-attributes <STR>` injects a raw XML attribute string into every generated trip (e.g. `departLane="best"`); the same mechanism (`--trip-attributes 'type="<distribution-id>"'` plus `--additional-files <vtypes-file>`) is how a heterogeneous fleet gets assigned — see [[vehicle-emissions-modeling]] for defining a `vTypeDistribution` with per-type HBEFA3 emission classes.

## Related tool

[[od2trips]] is the alternative path when demand comes from a zone-level origin-destination matrix (survey data, a transportation planning model) rather than being generated randomly. [[routesampler]] is a third path: rather than generating demand outright, it samples/scales routes from a large `randomTrips.py`-generated pool so the result matches prescribed traffic counts — useful when the goal is calibration against known count data rather than plausible-looking synthetic demand.
