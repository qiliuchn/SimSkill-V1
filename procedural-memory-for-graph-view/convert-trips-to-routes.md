---
name: convert-trips-to-routes
description: Use this skill when the user has a SUMO trips file (.trips.xml, just origin/destination edges) and wants actual driveable routes (.rou.xml, a full edge sequence) computed against a network — or wants to repair/validate an existing route file. Covers duarouter, which does shortest/optimal-path routing and can also perform dynamic user assignment (DUA) iteratively. Trigger on mentions of duarouter, converting trips to routes, .rou.xml generation, route repair/validation, or "my trips file doesn't have routes yet."
related_skills:
  - model-vclass-lane-permissions
  - model-urban-freight-delivery-tours
related_skills_for_graph_view:
  - "[[model-vclass-lane-permissions]]"
  - "[[model-urban-freight-delivery-tours]]"
---

# Convert Trips to Routes (duarouter)

Takes a `.trips.xml` (just origin edge, destination edge, and depart time — typically from `generate-random-trips`) plus a `.net.xml` and computes an actual driveable route (a full edge sequence) for each trip, writing a `.rou.xml`. Reference: https://sumo.dlr.de/docs/duarouter.html

This is the same tool `randomTrips.py --route-file` calls internally — this skill is for when the user already has a trips file (or a route file that needs repair) and wants to run the routing step explicitly, with more control than `randomTrips.py`'s automatic call gives.

## Locating the binary

`duarouter` ships alongside `sumo`/`sumo-gui`/`netconvert`/`netgenerate` in the same `bin/` directory, with the same PATH caveat as those (not always linked even when `sumo` is, e.g. on macOS framework installs like `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/bin/`). `scripts/convert_to_routes.py` resolves it automatically: `$PATH` → same directory as `sumo` → `$SUMO_HOME/bin`.

## Quick usage

```bash
# Basic: trips.trips.xml + net.xml -> routes.rou.xml
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml

# Discard/repair invalid trips rather than aborting
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml --ignore-errors --repair

# Limit to a time window (trips outside are discarded)
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml -b 0 -e 3600

# Reproducible route-choice randomness (matters when --weights.random-factor > 1, or persontrip mode choice)
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml --seed 42

# Validate only: write back out as trips (checked for reachability) instead of routes
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o checked.trips.xml --write-trips

# Passthrough for anything not explicitly wrapped
python scripts/convert_to_routes.py -n net.xml -r trips.trips.xml -o routes.rou.xml --extra "--routing-algorithm astar" --extra "--scale 1.5"
```

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n, --net-file` | input `.net.xml` (required) | — |
| `-r, --route-files` | input trips/routes/flows file(s), comma-separated (required) | — |
| `-o, --output-file` | output `.rou.xml` | `routes.rou.xml` |
| `-a, --additional-files` | extra network data (districts/TAZ, bus stops), comma-separated | — |
| `-b, --begin` | discard trips departing before this time (s) | 0 |
| `-e, --end` | discard trips departing after this time (s) | unbounded |
| `--ignore-errors` | continue instead of aborting when a route can't be built | off |
| `--repair` | try to fix an invalid route by patching around the gap | off |
| `--repair-from` | fix an invalid start edge by using the first usable edge instead | off |
| `--repair-to` | fix an invalid destination edge by using the last usable edge instead | off |
| `--remove-loops` | strip loops and start/end turnarounds from the computed route | off |
| `--routing-algorithm` | `dijkstra`, `astar`, `CH`, `CHWrapper` | `dijkstra` |
| `--weight-files` | edge-weight file(s) to route against instead of static net speeds (e.g. from a previous simulation run, for DUA) | — |
| `--scale <FLOAT>` | scale demand by this factor (duplicates or discards vehicles) | 1 |
| `--seed <INT>` / `--random` | reproducible seed / true randomness for route-choice | — |
| `--write-trips` | write back out as trips (not routes) — useful purely to validate/filter a trips file for reachability without committing to routes yet | off |
| `--max-alternatives <INT>` | number of route alternatives kept per vehicle (for DUA) | 5 |
| `--extra <ARG>` | any other raw `duarouter` flag, can be repeated | — |
| `--dry-run` | print the command without running it | off |

## What gets produced

Besides the `.rou.xml` named by `-o`, duarouter also writes a `<name>.rou.alt.xml` alongside it — a *route alternatives* file holding several candidate routes per vehicle with a probability distribution over them. This is what's used for iterative dynamic user assignment (`duaIterate.py`), but it also loads directly into `sumo`/`run-simulation` if the user wants stochastic route choice among alternatives rather than a single fixed route per vehicle.

## Gotchas

- **This is a distinct step from `randomTrips.py --route-file`.** That flag *also* calls duarouter internally and discards invalid trips automatically — if the user is already using it, they don't need this skill on top. This skill is for existing trips files, hand-written demand, or when finer routing control (algorithm choice, repair behavior, weight files for DUA) is needed than `randomTrips.py` exposes.
- **Invalid trips abort the whole run by default.** If the network has any disconnected components, at least one trip will likely fail to route — pass `--ignore-errors` (and usually `--repair`) or duarouter stops on the first failure.
- **`-b`/`-e` filter, they don't clip.** Trips outside the window are dropped entirely, not truncated — if the user's demand and simulation time window don't match, trips can silently vanish.
- **Route-choice randomness only matters with alternatives/perturbation.** A single deterministic shortest path doesn't need `--seed`; it starts to matter once `--weights.random-factor > 1` or persontrip mode choice is in play, since those introduce randomness into which route gets picked.
- **This is only single-shot routing**, i.e. static shortest/optimal paths against fixed edge weights. For traffic-responsive iterative equilibrium (DUA), the sibling tool `duaIterate.py` calls duarouter repeatedly with updated weights — out of scope for this skill but worth mentioning if the user's end goal is equilibrium assignment rather than one-off route computation.

## Related

- `model-vclass-lane-permissions` — running `duarouter` **without** `--ignore-errors` on a restricted-vClass trip set is the reliable way to detect whether a restriction has made some origin/destination pair unreachable for that class, rather than assuming reachability from the restriction's stated coverage.
- `model-urban-freight-delivery-tours` — reuses this technique for freight-tour route-feasibility checking, and documents a gotcha this skill's own reachability check would have caught earlier if applied consistently: a demand generator that skips this check and screens vehicle-class assignment by edge permission alone can fabricate a spurious non-monotone service-vs-restriction-coverage finding.
