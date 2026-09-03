---
summary: od2trips converts zone-based origin-destination demand matrices into SUMO vehicle trips, requiring a TAZ file mapping zones to edges alongside a matrix file in O-format, V-format, tazRelation, or Amitran.
keywords:
  - od2trips
  - OD-matrix
  - TAZ
  - traffic-assignment-zones
  - O-format
created: 2026-07-21T14:00:00
last_updated: 2026-07-21T14:00:00
sources:
  - "[[raw-materials/od2trips - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/od2trips.html
related_pages:
  - "[[random-trips]]"
  - "[[duarouter]]"
  - "[[sumo-command-line]]"
related_skills:
  - convert-od-matrix-to-trips
related_skills_for_graph_view:
  - "[[convert-od-matrix-to-trips]]"
---

# OD2Trips

`od2trips` converts origin-destination (O/D) demand — vehicle counts moving between traffic assignment zones (TAZs/districts) over a time period — into SUMO trips, and is the natural entry point when demand comes from real survey/count data or a transportation planning model rather than being synthesized (compare [[random-trips]]).

## The two required inputs

1. **A TAZ file** (`-n`/`--taz-files`), mapping each zone to the network edges vehicles can depart from and arrive at within it. Simple form: `<taz id="Z1" edges="edge1 edge2 edge3"/>`. Weighted/differentiated source vs. sink edges use nested `<tazSource>`/`<tazSink>` elements with `weight` attributes instead. Zones not imported from VISUM (which embeds districts automatically) generally need this authored by hand, drawn in `netedit`, or generated with `edgesInDistricts.py`.
2. **A matrix file**, in one of:
   - **O-format** (`-d`/`--od-matrix-files`) — the simplest to hand-write: a `$OR;D2` header, a `FROM-TIME TO-TIME` line (`H.MM H.MM`, 24h clock, end exclusive), a scale factor line, then one `FROM TO COUNT` line per zone pair.
   - **V-format** (`-d`, same flag) — VISUM/VISSIM-style matrix layout.
   - **tazRelation** (`-z`/`--tazrelation-files`) — XML.
   - **Amitran** (`--od-amitran-files`) — XML; vehicle type comes from the file's `actorConfig` id rather than `--vtype`.

Zone IDs must match exactly between the TAZ file and the matrix file — a mismatch silently yields zero trips for that pair rather than an obvious error.

## Common options

- `-b`/`-e`: discard trips outside this time window
- `--scale <FLOAT>`: multiply all matrix counts by this factor
- `--spread.uniform`: space each cell's departures evenly instead of randomly within its period
- `--different-source-sink`: never pick an identical source and sink edge for a trip
- `--vtype <STR>`: attach a vehicle type name to every trip (O/V-format only)
- `--prefix <STR>`: id prefix, needed when combining demand from multiple `od2trips` calls

## Output and next steps

Output is a `.trips.xml`, same as [[random-trips]]'s default output — not yet routed. Like random trips, `od2trips` doesn't check edge-to-edge reachability; feed the result through [[duarouter]] (with `--ignore-errors`/`--repair` if the network may be only partially connected between zones) to get an actual `.rou.xml`.
