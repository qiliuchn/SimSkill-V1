---
summary: duarouter computes driveable routes from trips against a network, supporting error repair, alternative routing algorithms, route-alternatives output for dynamic user assignment, and trip-only validation.
keywords:
  - duarouter
  - routing
  - route-alternatives
  - repair
  - dynamic-user-assignment
created: 2026-07-21T14:00:00
last_updated: 2026-08-07T10:44:36
sources:
  - "[[raw-materials/duarouter - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/duarouter.html
  - "[[raw-materials/sumodocswebdocsduarouter.md at main.md]]"
  - https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/duarouter.md
related_pages:
  - "[[random-trips]]"
  - "[[od2trips]]"
  - "[[tlscycleadaptation]]"
  - "[[tlscoordinator]]"
  - "[[routesampler]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[parking-areas-and-rerouters]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[route-choice-model-verification-overlap-and-route-set-effects]]"
related_skills:
  - convert-trips-to-routes
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - calibrate-demand-with-routesampler
  - simulate-multimodal-transit
  - model-parking-with-rerouting
  - compute-dynamic-user-equilibrium
  - specify-route-choice-models-and-generate-route-sets
related_skills_for_graph_view:
  - "[[convert-trips-to-routes]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[simulate-multimodal-transit]]"
  - "[[model-parking-with-rerouting]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[specify-route-choice-models-and-generate-route-sets]]"
---

# duarouter

`duarouter` computes an actual driveable route (a resolved edge sequence) for each trip against a `.net.xml`, turning a `.trips.xml` (from [[random-trips]] or [[od2trips]]) into a `.rou.xml`. It's the same routing engine `randomTrips.py --route-file` calls internally, exposed here for cases needing finer control or an explicit separate step.

## Basic usage

```bash
duarouter -n net.xml -r trips.trips.xml -o routes.rou.xml
```

## Handling unroutable trips

Neither `randomTrips.py` nor `od2trips` check edge-to-edge reachability, so on a partially disconnected network some trips will fail to route. By default `duarouter` aborts on the first such failure; the practical fixes are:
- `--ignore-errors`: skip failed trips and continue
- `--repair`: patch around a gap in an otherwise-broken route
- `--repair-from` / `--repair-to`: substitute the nearest usable edge if the trip's start or end edge itself is invalid

## Output modes

- Default: a `.rou.xml` of single routes.
- Alongside it, duarouter also writes a `<name>.rou.alt.xml` **route-alternatives** file — several candidate routes per vehicle with a probability distribution, used by `duaIterate.py` for iterative dynamic user assignment (DUA), but also loadable directly by `sumo` for stochastic route choice among alternatives. This same route-alternatives output (built with `--max-alternatives`) is the standard way to build the large candidate route pool [[routesampler]] needs for count-based demand calibration.
- `--write-trips`: write back out as trips rather than routes — useful purely to validate/filter a trips file for reachability without committing to full routes yet.

## Other notable options

- `--routing-algorithm`: `dijkstra` (default), `astar`, `CH`, `CHWrapper`
- `--weight-files`: route against edge weights from a file (e.g. output from a prior simulation run) instead of static net speeds — the basis of DUA
- `--scale <FLOAT>`: scale demand by duplicating/discarding vehicles
- `--remove-loops`: strip loops and start/end turnarounds from computed routes
- `-b`/`-e`: discard (not clip) trips outside this departure window
- `--seed`/`--random`: matters once alternatives or randomized weighting are in play; a single deterministic shortest-path computation doesn't need it

## Scope

`duarouter` performs single-shot static routing against fixed weights. For traffic-responsive iterative equilibrium assignment, `duaIterate.py` calls `duarouter` repeatedly with updated weights between iterations — a separate tool built on top of this one. See [[dynamic-user-equilibrium-and-wardrop]] for how this actually works and the (verified, non-obvious) limits of what it can equilibrate.

`duarouter` also resolves **intermodal person routing** — given person trips with `modes` including `public`, a network with pedestrian infrastructure, and a scheduled public-transport line's vehicles + busStops passed alongside via `-r`/`--additional-files`, it automatically works out each person's walk/access/ride legs, no separate step required. See [[public-transport-and-intermodal-routing]].

`<stop>` elements (e.g. a parking stop referencing a `parkingArea`) attached to a trip/vehicle before routing survive unchanged through `duarouter` into the output route file — useful when building a parking scenario, see [[parking-areas-and-rerouters]].

Routed output from `duarouter` is also a prerequisite for [[tlscycleadaptation]] and [[tlscoordinator]], both of which need actual `<route>` data (not raw trips/flows) to know real travel times and traffic volumes through each intersection.
