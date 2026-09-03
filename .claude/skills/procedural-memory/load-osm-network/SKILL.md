---
name: load-osm-network
description: Use this skill when the user wants to build a SUMO network from real-world OpenStreetMap data, as opposed to a synthetic grid/spider/single-intersection network. Covers downloading OSM data for a bounding box/area/polygon with SUMO's osmGet.py tool and converting it into a .net.xml with osmBuild.py/netconvert. Trigger on mentions of OpenStreetMap, OSM, osmGet.py, osmBuild.py, osmWebWizard, importing a real city/region/street network, or requests for a network based on an actual place (e.g. "a network of downtown Chicago").
---

# Load OSM Network

Downloads a real-world road network from OpenStreetMap and converts it into a SUMO `.net.xml`, using SUMO's own `osmGet.py` (download) and `osmBuild.py` (convert, via `netconvert`) tools. Reference: https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html and https://sumo.dlr.de/docs/Tools/Import/OSM.html

## The two-stage pipeline

1. **`osmGet.py`** downloads raw OSM data for an area into `<prefix>.osm.xml`. The area is specified one of three ways:
   - `--bbox west,south,east,north` (geo coordinates, i.e. lon/lat — note the order)
   - `--area <ID>` (an OSM relation/area ID)
   - `--polygon <FILE>` (bounding box computed from a polygon file)
2. **`osmBuild.py`** converts that `.osm.xml` into a SUMO network via `netconvert` under the hood, applying a set of recommended options by default (`--geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.discard-simple --tls.join --output.original-names --output.street-names` — verified directly against `osmBuild.py`'s own `DEFAULT_NETCONVERT_OPTS` source) — these fix real-world OSM quirks (duplicate junction nodes, missing ramp lanes, signal nodes offset from the actual intersection, etc.) that a synthetic network never has. **This default set does NOT include `--tls.default-type actuated`** — a default OSM import yields netconvert's own default **static** signal type, same as any other network. Pass `--extra-netconvert-options "--tls.default-type,actuated"` explicitly if actuated signals are wanted (and note this REPLACES the whole default cleanup set rather than adding to it — re-include the full recommended options alongside it, or `osmBuild.py` will pass through only what you specify).

`scripts/get_osm_network.py` wraps both stages into one call and handles locating them (see below).

## Locating the tools

`osmGet.py` and `osmBuild.py` live in `$SUMO_HOME/tools/`, **not** next to the `sumo`/`netconvert` binaries — this is a different location than the `netgenerate`/`netconvert` binary lookup used by the sibling network-generation skills. `SUMO_HOME` must be set:

```bash
echo $SUMO_HOME
ls "$SUMO_HOME/tools/osmGet.py" "$SUMO_HOME/tools/osmBuild.py"
```

If `SUMO_HOME` is unset, ask the user where SUMO is installed rather than guessing — on macOS framework installs it's typically something like `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/` (note: `tools/` sits under this, one level up from `bin/`). `scripts/get_osm_network.py` fails with a clear message if `SUMO_HOME` isn't set or the tools aren't found there.

## Quick usage

```bash
# By bounding box (lon/lat: west,south,east,north)
python scripts/get_osm_network.py --bbox=-122.43,37.76,-122.40,37.79 --prefix sf_downtown

# By OSM area/relation ID
python scripts/get_osm_network.py --area 62422 --prefix some_place

# Only roads usable by passenger cars, with pedestrian infrastructure added
python scripts/get_osm_network.py --bbox ... --prefix mynet --vehicle-classes passenger --pedestrians

# Left-hand-driving country
python scripts/get_osm_network.py --bbox ... --prefix mynet --lefthand

# Pass through arbitrary extra netconvert options
python scripts/get_osm_network.py --bbox ... --prefix mynet --extra-netconvert-options "--remove-edges.isolated,--output.street-names"
```

Finding a bounding box: use https://www.openstreetmap.org/export (drag to select an area, read off the four numbers) or https://boundingbox.klokantech.com/.

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `--bbox W,S,E,N` | bounding box in geo coords (lon/lat) — exactly one of `--bbox`/`--area`/`--polygon` required | — |
| `--area <ID>` | OSM area/relation ID | — |
| `--polygon <FILE>` | compute bbox from a polygon file | — |
| `--prefix <NAME>` | filename prefix for downloaded/generated files | `osm` |
| `--tiles <INT>` | split a large `--bbox` download into INT tiles (forwarded to `osmGet.py`) | — |
| `--output-dir <DIR>` | where downloaded/generated files land | current directory |
| `--vehicle-classes` | `all`, `road`, `passenger`, or `publicTransport` — filters which OSM ways get imported | `all` |
| `--pedestrians` | add the pedestrian typemap (sidewalks, crossings-friendly permissions) | off |
| `--bicycles` | add the bicycle typemap (adjusts bike lane widths) | off |
| `--urban-de` | add the urban-Germany typemap (realistic urban speed limits, ~50 km/h, when OSM `maxspeed` is missing) | off |
| `--typemap <FILE,FILE,...>` | additional typemap file(s) beyond the above shortcuts, appended after the default `osmNetconvert.typ.xml` | — |
| `--lefthand` | add `--lefthand` to netconvert options, for left-hand-driving regions | off |
| `--extra-netconvert-options "OPT1,OPT2,..."` | raw passthrough to `osmBuild.py --netconvert-options` | — |
| `--extra-polyconvert-options "OPT1,OPT2,..."` | raw passthrough to `osmBuild.py --polyconvert-options` (only relevant if a typemap is set, since that's what triggers polygon output) | — |
| `--keep-osm-file` | keep the intermediate `<prefix>.osm.xml` (kept by default; use `--no-keep-osm-file` — see script `--help`) | kept |
| `--dry-run` | print the two commands without running them | off |

The `--pedestrians`/`--bicycles`/`--urban-de` shortcuts just append the corresponding file from `$SUMO_HOME/data/typemap/` — per the SUMO docs' caution, the base `osmNetconvert.typ.xml` is always loaded first so these act as patches rather than replacements.

## After generating the network

Same as the other network skills: a `.net.xml` alone has no traffic. Typical next steps:
- **Routes**: `randomTrips.py` (in `$SUMO_HOME/tools/`) for stochastic demand, or `od2trips` if origin-destination data exists.
- **Polygons** (buildings, water, landuse): pass `--typemap`/the shortcut flags above and `osmBuild.py` will also emit a `.poly.xml` via `polyconvert`, loadable in `sumo-gui` for visual context (this doesn't affect simulation dynamics, just rendering).
- **TraCI control loop**: the `run-simulation` skill covers stepping the simulation once network + routes exist.

For synthetic (non-real-world) networks instead, see `create-grid-network`, `create-spider-network`, or `create-single-intersection`.

## Gotchas

**A negative-longitude bbox must be ONE argv token joined with `=`.** `osmGet.py` parses `--bbox` with argparse, and a space-separated value starting with `-` — which every western-hemisphere longitude is — is read as an option string, because the commas defeat argparse's negative-number heuristic:

```bash
osmGet.py --bbox -87.648,41.874,-87.620,41.899   # error: argument -b/--bbox: expected one argument (exit 2)
osmGet.py -b     -87.648,41.874,-87.620,41.899   # same error
osmGet.py --bbox=-87.648,41.874,-87.620,41.899   # parses
osmGet.py --bbox 13.40,52.50,13.42,52.52         # parses — eastern hemisphere works either way
```

This is easy to miss because eastern-hemisphere bboxes work in every form, so the failure looks regional rather than syntactic. `scripts/get_osm_network.py` built the call as two argv tokens and therefore **failed for every bbox in the Americas**, aborting with exit 2 at the download stage (`run()` exits on a non-zero return, so it does not reach `osmBuild.py`). Fixed 2026-08-18; the same rule applies to any hand-written `osmGet.py` call.

---

### Other gotchas


- **`--bbox` order is lon/lat (west,south,east,north)**, not lat/lon — a very common source of "empty network" or "wrong location" errors. Double-check against a map export tool rather than guessing coordinate order.
- **Western-hemisphere longitudes are negative** (e.g. `-122.43` for San Francisco). Because of how Python's argparse handles values starting with `-`, always pass it as `--bbox=-122.43,37.76,...` (with `=`) rather than `--bbox -122.43,...` (space-separated) — the latter raises "expected one argument". The same applies to `--extra-netconvert-options` whenever the value itself starts with `--` (which it always does, e.g. `--extra-netconvert-options="--remove-edges.isolated"`).
- **Large areas** need `--tiles` and can still take a long time or produce huge networks; see the "Importing large Networks" section of the docs for `--keep-edges.by-type`/`--remove-edges.by-type` filtering if the user only needs major roads.
- **Overpass API rate limits, timeouts, or a down/rate-limited default endpoint**: `osmGet.py` calls the public Overpass API; very large bboxes may fail or time out. **The `/api/status` endpoint reporting healthy is not proof the actual data query will work** — verified directly: the default endpoint's `/api/status` reported available slots while the real bbox query still 504'd, and a `kumi.systems` mirror 502'd on the same query. Try narrowing the area, `--tiles`, or an alternate mirror via `osmGet.py --url`; as a last resort, a direct `curl` to a different public Overpass mirror's `/api/map?bbox=...` endpoint (e.g. `maps.mail.ru`'s) produces the same `.osm.xml` format and can be fed straight into `osmBuild.py`/`netconvert --osm-files` when the primary tooling's endpoints are unreachable.
- **Junctions may need manual joining**: `--junctions.join` (on by default via `osmBuild.py`) uses a heuristic and can occasionally over-join complex intersections (verified: one real aggressively-joined cluster produced an "Intersecting left turns... increase junction radius" warning) — if the user reports weird junction shapes, point them at `--junctions.join-exclude` or manual node joins (see the linked docs' Junctions section). Joining multiple OSM signal-pole nodes into one `cluster_*` junction is the normal, desired outcome, not a defect. Conversely, when netconvert *refuses* a join ("Not joining junctions ... not compact"), don't force it — measured on a real network, overriding a refusal raised link travel time +126% (significant) and roughly quadrupled teleports under congestion; netconvert's refusal heuristic was right (see `audit-repair-and-persist-imported-network-defects`).
- **Traffic lights may be missing or misplaced**: OSM often marks the *signal pole* rather than the intersection itself; `osmBuild.py`'s default `--tls.guess-signals` handles the common case, but isolated/complex intersections may still need `--tls.guess-signals.dist`/`--tls.guess-signals.slack` tuning via `--extra-netconvert-options`. **`--tls.discard-simple` (also on by default) can legitimately drop some guessed signals** that end up controlling no remaining links after vehicle-class filtering/geometry cleanup — a "does not control any links" warning here is expected, not a broken import.
- **The default TLS type from a fresh import is `static`, not `actuated`** (verified directly against `osmBuild.py`'s actual `DEFAULT_NETCONVERT_OPTS` — an earlier version of this skill incorrectly claimed the default included `--tls.default-type actuated`). If actuated signals are wanted, request them explicitly via `--extra-netconvert-options` (this script always re-includes the full recommended cleanup set alongside any extra options, so nothing is silently lost — see `scripts/get_osm_network.py`'s `DEFAULT_NETCONVERT_OPTS` constant).
- **To convert an already-built OSM network's TLS type, rebuild from the source `.osm.xml`/`.osm` file with the desired `--tls.default-type`, not by re-running `netconvert -s` on the existing `.net.xml`.** `--tls.default-type` only fills in *unspecified* TLS types; once a junction's `tlLogic` already has an explicit `type=` (as any `osmBuild.py` output does), a second netconvert pass with only `--tls.default-type` leaves it unchanged (verified directly — see `control-signals-with-actuated-tls`'s corrected gotcha for the general version of this). Rebuilding from the same source data is deterministic, so the two variants end up with identical topology/geometry and only the TLS type differing — a clean basis for a static-vs-actuated comparison.
- **The classic "trips die on OSM dead-end/fringe edges" problem is avoidable**: filter to the target vehicle class (`--vehicle-classes passenger`, or `--keep-edges.by-vclass passenger` via `--extra-netconvert-options`) and remove disconnected stubs (`--remove-edges.isolated`) *before* generating demand — verified this combination alone produced 0 unroutable trips on a real network. Validate with a **strict** `duarouter` pass (no `--repair`/`--ignore-errors`) to see the true unroutable count, since repair silently masks drops.
- **Real OSM extracts often carry public-transport relations** (bus routes/stops); expect harmless `netconvert` warnings about removed PT elements when importing for passenger-car-only simulation.
- Re-running with the same `--prefix` in the same `--output-dir` will overwrite previous output silently.
