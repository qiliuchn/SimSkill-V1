---
summary: How to build a SUMO network from real-world OpenStreetMap data using osmGet.py to download and osmBuild.py/netconvert to convert, including the recommended cleanup options and typemap system.
keywords:
  - OpenStreetMap
  - osmGet
  - osmBuild
  - real-world-network
  - typemap
created: 2026-07-21T14:00:00
last_updated: 2026-08-04T13:00:00
sources:
  - "[[raw-materials/OpenStreetMap - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html
related_pages:
  - "[[abstract-network-generation]]"
  - "[[sumo-command-line]]"
  - "[[random-trips]]"
  - "[[actuated-traffic-signals]]"
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[cutroutes-and-subnetwork-extraction]]"
  - "[[imported-network-defect-classes-and-traffic-impact]]"
related_skills:
  - load-osm-network
  - control-signals-with-actuated-tls
  - generate-random-trips
  - convert-trips-to-routes
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[load-osm-network]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[analyze-simulation-outputs]]"
---

# OpenStreetMap

SUMO can build a network from real-world [OpenStreetMap](https://www.openstreetmap.org) data as an alternative to the synthetic networks covered in [[abstract-network-generation]]. The pipeline has two stages: download, then convert.

## Downloading: osmGet.py

`osmGet.py` (in `$SUMO_HOME/tools/`) fetches raw OSM data for an area from the Overpass API into `<prefix>.osm.xml`. The area can be given as a bounding box (`--bbox west,south,east,north`, in lon/lat — not lat/lon), an OSM area/relation ID (`--area`), or a polygon file to compute a bbox from (`--polygon`). Large areas may need `--tiles <INT>` to split the download and avoid Overpass timeouts.

## Converting: osmBuild.py

`osmBuild.py` turns the downloaded `.osm.xml` into a `.net.xml` via `netconvert` under the hood, and applies a set of **recommended cleanup options by default**: `--geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.discard-simple --tls.join --output.original-names --output.street-names` (verified directly against `osmBuild.py`'s `DEFAULT_NETCONVERT_OPTS` source — **this does NOT include `--tls.default-type actuated`**, contradicting an earlier version of this page. A default OSM import gives netconvert's own default **static** signal type, same as any other network — actuated must be requested explicitly). The cleanup options exist because raw OSM data has quirks a synthetic network never does — duplicate/nearby junction nodes that should be one intersection, missing highway on/off-ramp lanes, and traffic-signal nodes offset from the actual physical intersection (OSM often tags the position of the signal pole, not the junction center). **`--netconvert-options` passed to `osmBuild.py` REPLACES this default set entirely rather than appending to it** — any extra option must be combined with the full recommended set explicitly, or the cleanup silently disappears.

## Typemaps

Which OSM way tags map to which SUMO edge attributes (lanes, speed, permissions) is controlled by a **typemap** file, normally `$SUMO_HOME/data/typemap/osmNetconvert.typ.xml`, passed to `osmBuild.py` via **`--netconvert-typemap`** (verified against `osmBuild.py --help` — there is no `--type-file` flag; `-m`/`--typemap` is a *different* option, for polyconvert's colored-area extraction, not netconvert's way-to-edge type mapping). Passing a custom `--netconvert-typemap` **replaces** the default rather than extending it, so the base typemap must be listed explicitly alongside any additions — e.g. combining it with `osmNetconvertPedestrians.typ.xml` (sidewalks/crossings), `osmNetconvertBicycle.typ.xml` (bike lane width adjustments), or `osmNetconvertUrbanDe.typ.xml` (realistic urban speed limits when OSM's `maxspeed` tag is missing).

`--vehicle-classes` (`all`, `road`, `passenger`, `publicTransport`) filters which OSM ways get imported in the first place.

## Vehicle classes and polygons

If a typemap is set, `osmBuild.py` also runs `polyconvert` to emit a `.poly.xml` of buildings/water/landuse — purely for visual context in `sumo-gui`, with no effect on simulation dynamics.

## Practical notes

- Junction joining (`--junctions.join`, on by default here) is heuristic and can occasionally over-join a complex intersection (verified: one aggressively-joined cluster produced an "Intersecting left turns... increase junction radius" warning) — `--junctions.join-exclude` or manual node edits are the fallback for that direction. Joining OSM's separate per-approach signal-pole nodes into one `cluster_*` junction is the *normal*, desired outcome — OSM tags the pole position, not the intersection center, so without joining you'd get several tiny disconnected "junctions" instead of one real signalized intersection. **When netconvert instead *refuses* a join (logging "Not joining junctions" as "not compact"), don't override it**: on a real network, forcing a refused join measurably made link travel time worse (1.58s -> 3.56s, +126%, significant) and roughly quadrupled teleports under congestion — the refusal heuristic was correct. See [[imported-network-defect-classes-and-traffic-impact]] for the measurement.
- `--lefthand` should be added for left-hand-driving regions.
- Very large `--bbox` areas may hit Overpass API rate limits or simply take a long time; narrowing the area, using `--tiles`, or filtering with `--keep-edges.by-type`/`--remove-edges.by-type` (for e.g. major-roads-only imports) are the usual mitigations.

## Verified end-to-end lessons (real network, not just the pipeline in isolation)

From a full network→demand→signals→analysis pass on a real downtown extract:

- **The Overpass `/api/status` endpoint responding is not proof the actual data query will work.** In one real run, `overpass-api.de/api/status` reported healthy slots while the actual `osmGet.py` bbox query 504'd, and a kumi.systems mirror 502'd. The `maps.mail.ru` Overpass mirror's lighter `/api/map?bbox=...` endpoint (fetched directly, e.g. via `curl`, then fed to `netconvert --osm-files` the same as any `.osm.xml`) was the working fallback when the primary endpoints failed. `osmGet.py --url`/`--retries`/`--retry-delay` are the built-in mitigations to try first.
- **`--tls.guess-signals` + `--tls.discard-simple` can legitimately drop some guessed signals** — after passenger-only vehicle-class filtering and geometry cleanup, a signal node may end up controlling no remaining links, and gets discarded with a "does not control any links" warning. This is expected behavior, not a sign of a broken import.
- **The classic "trips die on OSM dead-end fringe edges" problem is avoidable, not inevitable**: filtering to the target vehicle class (`--keep-edges.by-vclass passenger`) and removing disconnected stubs (`--remove-edges.isolated`) *before* generating demand prevented any unroutable trips in one verified run (1500/1500 routed, confirmed with a **strict** `duarouter` pass — no `--repair`/`--ignore-errors` — to see the true drop count rather than letting repair silently mask it).
- **Real OSM extracts often carry public-transport relations** (bus routes, stops) that generate harmless `netconvert` warnings about removed PT elements when importing for passenger-car-only simulation — expected noise, not an error to chase.
- **Converting an already-built network's TLS type in a second `netconvert` pass does not work the way it does for a fresh network** — see [[actuated-traffic-signals]] and `control-signals-with-actuated-tls`'s corrected gotcha: `--tls.default-type` only fills in *unspecified* types, so a network whose signals already have an explicit type (as any `osmBuild.py`/`netconvert` output does) needs to be rebuilt from the source `.osm.xml` with the desired `--tls.default-type`, not re-converted from the existing `.net.xml`.

As with any freshly-built network, there's no demand on it yet — see [[random-trips]] for generating some.

If an OSM-built network later needs to be exchanged with another tool (a driving simulator, an HD-map pipeline, MATSim), see [[opendrive-and-network-format-interoperability]] — a real-world OSM network's mixed vClass permissions (sidewalks, bike lanes) and guessed signals are exactly the features most vulnerable to silent loss on a format round trip. If instead the goal is to make a large OSM import computationally tractable by keeping only a study area, see [[cutroutes-and-subnetwork-extraction]] — the same guessed-signal and mixed-permission geometry that's fragile under format conversion is also what a network cut silently damages at the boundary.
