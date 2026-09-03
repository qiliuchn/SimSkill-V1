---
name: generate-random-trips
description: Use this skill when the user wants to generate travel demand (trips/routes) for an existing SUMO network — random origin-destination vehicle trips, pedestrians, or persontrips — rather than hand-writing a .rou.xml. Covers SUMO's randomTrips.py tool: departure/arrival edge sampling, traffic volume control, fringe-biased demand (through-traffic), intermediate waypoints, vehicle types, and converting trips into validated routes via duarouter. Trigger on mentions of randomTrips.py, random trips, random demand, traffic volume/insertion rate, generating a .rou.xml or .trips.xml, or "add traffic to" a network. Reference: https://sumo.dlr.de/docs/Tools/Trip.html
---

# Generate Random Trips (randomTrips.py)

Generates random origin-destination demand for an existing SUMO network (`.net.xml`) — the usual next step after `create-grid-network`, `create-spider-network`, `create-single-intersection`, or `load-osm-network`, since a bare network has no traffic on it.

## Locating the tool

`randomTrips.py` lives at `$SUMO_HOME/tools/randomTrips.py` — same location family as `osmGet.py`/`osmBuild.py`, **not** next to the `sumo`/`netconvert` binaries.

```bash
echo $SUMO_HOME
ls "$SUMO_HOME/tools/randomTrips.py"
```

`scripts/random_trips.py` resolves this automatically and fails with a clear message if `SUMO_HOME` isn't set or the tool isn't found there.

## Quick usage

```bash
# Simplest: random vehicle trips over 0-3600s on net.xml
python scripts/random_trips.py -n net.xml -o trips.trips.xml

# Fixed vehicle count via period: 200 vehicles between t=0 and t=3600
python scripts/random_trips.py -n net.xml -o trips.trips.xml -b 0 -e 3600 --period 18

# Traffic volume in vehicles/hour instead of period
python scripts/random_trips.py -n net.xml -o trips.trips.xml --insertion-rate 600

# Produce validated routes (calls duarouter automatically, drops disconnected trips)
python scripts/random_trips.py -n net.xml --route-file routes.rou.xml

# Mostly through-traffic entering/leaving at the network boundary
python scripts/random_trips.py -n net.xml -o trips.trips.xml --fringe-factor 10

# Pedestrians instead of vehicles
python scripts/random_trips.py -n net.xml -o peds.trips.xml --pedestrians --max-distance 2000

# Reproducible randomness
python scripts/random_trips.py -n net.xml -o trips.trips.xml --seed 42

# Passthrough for anything not explicitly wrapped
python scripts/random_trips.py -n net.xml -o trips.trips.xml --extra "--intermediate 2" --extra "--min-distance 300"
```

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n, --net-file` | input `.net.xml` (required) | — |
| `-o, --output` | output trips file (ignored if `--route-file` given) | `trips.trips.xml` |
| `-b, --begin` | start time (s) | 0 |
| `-e, --end` | end time (s) | 3600 |
| `--period <FLOAT[,...]>` | seconds between departures (1/period = rate/s); comma/space list divides the interval into sub-periods | 1 |
| `--insertion-rate <FLOAT[,...]>` | vehicles/hour, alternative to `--period` | — |
| `--insertion-density <FLOAT[,...]>` | vehicles/hour/km of road, alternative to both above | — |
| `--seed <INT>` | reproducible pseudo-randomness | — |
| `--random` | true (non-reproducible) randomness | off |
| `--prefix <STR>` | id prefix for generated trips (needed if combining multiple calls) | `""` |
| `--fringe-factor <FLOAT\|max>` | relative probability boost for network-boundary edges (models through-traffic); `max` forces all trips to start/end at the fringe | 1 |
| `--min-distance <FLOAT>` | minimum straight-line start→end distance (m) | — |
| `--max-distance <FLOAT>` | maximum straight-line start→end distance (m) — recommended with `--pedestrians` | — |
| `--intermediate <INT>` | number of via-waypoints per trip (longer, multi-edge journeys) | 0 |
| `--vehicle-class <STR>` | e.g. `passenger`, `bus`, `truck`; adds a matching `vType` and sets `--edge-permission` to match | — |
| `--pedestrians` | generate pedestrians instead of vehicles | off |
| `--persontrips` | generate `<persontrip>` (mode-choice: walk/car/public) instead of vehicle trips | off |
| `--route-file <FILE>` | output validated `.rou.xml` (runs `duarouter` automatically, drops disconnected trips) instead of a raw trips file | — |
| `--validate` | with `--route-file`, also emit validated *trips* (not just routes) | off |
| `--trip-attributes <STR>` | raw XML attribute string added to every trip, e.g. `'departLane="best" departSpeed="max"'` | — |
| `--weights-prefix <STR>` | load custom edge src/dst/via probabilities from `<prefix>.{src,dst,via}.xml` | — |
| `--weights-output-prefix <STR>` | save the edge probabilities actually used, for inspection/reuse | — |
| `--extra <ARG>` | any other raw `randomTrips.py` flag, can be repeated (e.g. `--extra "--angle-factor 2"`) | — |
| `--dry-run` | print the command without running it | off |

## Choosing how to control traffic volume

Only pick one of `--period` / `--insertion-rate` / `--insertion-density` — they're alternative ways to express the same thing:
- `--period` is the classic option: seconds between departures (so smaller = more traffic; `1/period` = vehicles/second).
- `--insertion-rate` is often more intuitive: directly vehicles/hour.
- `--insertion-density` normalizes by road length (vehicles/hour/km) — most useful when comparing networks of different sizes (e.g. across the different grid/spider/intersection sizes the sibling skills can produce).

To get an exact vehicle count `n` between times `t0` and `t1`: `-b t0 -e t1 --period ((t1-t0)/n)`.

## Gotchas

- **Trips ≠ valid routes.** By default `randomTrips.py` doesn't check reachability between the sampled source and destination edges — that's `duarouter`'s job. If the network isn't fully connected, some generated trips will silently fail to route. Use `--route-file` to have `duarouter` run automatically and discard the invalid ones (may need to over-generate trips to compensate — bump the count or lower `--period`).
- **Determinism**: identical options → identical output every time, *unless* `--random` or `--seed` is given. This is usually desired for reproducible experiments but can surprise someone expecting fresh randomness on every run.
- **`--pedestrians` without `--max-distance`** can generate absurdly long walking trips across a large network — set `--max-distance` when generating pedestrian demand.
- **Fringe edges depend on network shape.** For the `create-single-intersection` skill's networks, every arm's outer node is fringe by definition — `--fringe-factor max` there just means "always enter/exit from outside the intersection," which is usually what signal-timing research wants anyway (it's the only sensible option on such a small network).
- **Combining multiple calls** (e.g. cars + pedestrians + buses in one simulation) needs a distinct `--prefix` per call so vehicle/person IDs don't collide.
- Quoting `--trip-attributes` differs by shell — the script passes the string through as-is, so quote it the way your shell expects (e.g. `--trip-attributes 'departLane="best"'` on Linux/macOS).
