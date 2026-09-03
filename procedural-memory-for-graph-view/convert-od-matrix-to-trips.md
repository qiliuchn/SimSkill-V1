---
name: convert-od-matrix-to-trips
description: Use this skill when the user has origin/destination (O/D) traffic demand — a matrix of vehicle counts between zones/districts over time — and wants it converted into a SUMO .trips.xml, as opposed to purely random demand. Covers od2trips, which needs both a TAZ (traffic assignment zone) file mapping districts to edges and an O/D-matrix file (O-format, V-format/VISUM-VISSIM, tazRelation, or Amitran). Trigger on mentions of od2trips, O/D matrix, OD matrix, traffic assignment zones/TAZ, district-based demand, VISUM/VISSIM matrix import, or converting zone-level travel demand into vehicle trips.
---

# Convert OD Matrix to Trips (od2trips)

Converts origin/destination demand — vehicle counts moving between traffic assignment zones (TAZs/districts) over a time period — into a SUMO `.trips.xml`, by mapping each zone to a set of network edges. This is the standard path for demand that comes from real survey/count data or a transportation planning model, as opposed to the synthetic demand `generate-random-trips` produces. Reference: https://sumo.dlr.de/docs/od2trips.html and https://sumo.dlr.de/docs/Demand/Importing_O/D_Matrices.html

## Two required inputs (this is the main gotcha)

Unlike `randomTrips.py`, `od2trips` needs **two** separate files, both keyed by matching zone IDs:

1. **A TAZ file** (`-n`) mapping each zone to the edges vehicles can depart from / arrive at in that zone. If the network wasn't imported from VISUM (which embeds districts automatically), this has to be authored by hand or drawn as polygons in `netedit` and converted with `edgesInDistricts.py`. Minimal format:
   ```xml
   <tazs>
       <taz id="Z1" edges="edge1 edge2 edge3"/>
       <taz id="Z2" edges="edge4 edge5"/>
   </tazs>
   ```
   Or with separate weighted source/sink edges:
   ```xml
   <tazs>
       <taz id="Z1">
           <tazSource id="edge1" weight="0.6"/>
           <tazSource id="edge2" weight="0.4"/>
           <tazSink id="edge3" weight="1.0"/>
       </taz>
   </tazs>
   ```
   `scripts/make_taz_file.py` builds this from a simple JSON zone→edges mapping if the user doesn't have one yet (see below).

2. **An O/D-matrix file** (`-d`, `-z`, or `--od-amitran-files`) giving vehicle counts between zone pairs for a time period. The simplest to hand-write is the **O-format**:
   ```
   $OR;D2
   * From-Time  To-Time
   7.00 8.00
   * Factor
   1.00
   * Z1->Z1  Z1->Z2  Z2->Z1  Z2->Z2
   Z1 Z1 1.00
   Z1 Z2 2.00
   Z2 Z1 4.00
   Z2 Z2 5.00
   ```
   First line is a literal format tag (`$OR;D2`). Then: time range as `H.MM H.MM` (24h clock, end exclusive), a global scale factor, then one `FROM TO COUNT` line per zone pair (`*`-prefixed lines are comments). Zone names here must exactly match TAZ ids from the `-n` file.

   Other supported formats: **V-format** (VISUM/VISSIM matrix layout), **tazRelation** (XML, `-z`), **Amitran** (XML, `--od-amitran-files`) — see the linked docs if the user's data is already in one of these.

## Locating the binary

`od2trips` ships alongside `sumo`/`sumo-gui`/`netconvert`/`netgenerate`/`duarouter` in the same `bin/` directory, with the same PATH caveat (not always linked even when `sumo` is, e.g. on macOS framework installs like `/Library/Frameworks/EclipseSUMO.framework/Versions/<ver>/EclipseSUMO/bin/`). `scripts/od_to_trips.py` resolves it automatically: `$PATH` → same directory as `sumo` → `$SUMO_HOME/bin`.

## Quick usage

```bash
# Basic: TAZ file + O-format matrix -> trips.trips.xml
python scripts/od_to_trips.py -n taz.xml -d matrix.od -o trips.trips.xml

# Multiple matrices (e.g. AM + PM peak), scaled up 20%
python scripts/od_to_trips.py -n taz.xml -d am.od,pm.od -o trips.trips.xml --scale 1.2

# Uniform spread within each time period instead of random jitter
python scripts/od_to_trips.py -n taz.xml -d matrix.od -o trips.trips.xml --spread-uniform

# Avoid trips where source and sink edge are literally the same
python scripts/od_to_trips.py -n taz.xml -d matrix.od -o trips.trips.xml --different-source-sink

# tazRelation (XML) input instead of O-format
python scripts/od_to_trips.py -n taz.xml -z relations.xml -o trips.trips.xml

# Assign a specific vehicle type, prefix ids (needed when combining multiple od2trips calls)
python scripts/od_to_trips.py -n taz.xml -d truck_matrix.od -o truck_trips.trips.xml --vtype truck --prefix truck_
```

## Building a TAZ file from scratch

If the user has network edges grouped into zones but no TAZ file yet:
```bash
python scripts/make_taz_file.py --zones zones.json -o taz.xml
```
where `zones.json` is:
```json
{
  "Z1": ["edge1", "edge2", "edge3"],
  "Z2": ["edge4", "edge5"]
}
```
This produces the simple (undifferentiated source/sink) TAZ format shown above. For weighted/differentiated source vs. sink edges, write the TAZ XML by hand using the second format shown above — that level of nuance isn't worth a generator script.

## Script options (od_to_trips.py)

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n, --taz-files` | TAZ/district file(s), comma-separated (required) | — |
| `-d, --od-matrix-files` | O/V-format matrix file(s), comma-separated | — |
| `-z, --tazrelation-files` | tazRelation-format (XML) matrix file(s), comma-separated | — |
| `--od-amitran-files` | Amitran-format (XML) matrix file(s), comma-separated | — |
| (exactly one of the three matrix inputs above is required) | | |
| `-o, --output-file` | output `.trips.xml` | `trips.trips.xml` |
| `-b, --begin` / `-e, --end` | discard trips outside this window (s) | 0 / 86400 |
| `--scale <FLOAT>` | multiply all matrix counts by this factor | 1 |
| `--spread-uniform` | space each cell's departures evenly instead of randomly within its time period | off |
| `--different-source-sink` | never pick identical source and sink edge for a trip | off |
| `--vtype <STR>` | vehicle type name attached to every trip (type itself isn't generated — define it separately if needed, e.g. via an additional file when running `run-simulation`) | — |
| `--prefix <STR>` | id prefix — required if combining trips from multiple od2trips calls | — |
| `--pedestrians` / `--persontrips` | generate that mode instead of vehicles | off |
| `--seed <INT>` / `--random` | reproducible seed / true randomness for departure-time jitter | — |
| `--extra <ARG>` | any other raw `od2trips` flag, can be repeated (e.g. `--extra "--timeline.day-in-hours"` with `--extra "--timeline 0.9,0.5,..."`) | — |
| `--dry-run` | print the command without running it | off |

## After generating trips

Same as `generate-random-trips`: the output here is a `.trips.xml`, not yet a routed `.rou.xml`. Feed it into `convert-trips-to-routes` (duarouter) next, then `run-simulation`.

## Gotchas

- **Zone IDs must match exactly** between the TAZ file and the matrix file — a typo'd or differently-cased zone name causes od2trips to silently produce zero trips for that zone pair (or error, depending on whether it's missing from one side or both — see "Dealing with broken Data" in the linked docs).
- **od2trips doesn't check edge reachability any more than randomTrips.py does** — feed the output through `convert-trips-to-routes` with `--ignore-errors`/`--repair` if the network might be only partially connected between zones.
- **O-format time range is `H.MM H.MM`, not `H:MM`**, and the end time is exclusive — `7.00 8.00` means departures span second 25200 to 28799.
- **`--vtype` only applies with `-d`/`--od-matrix-files` (O/V-format)**; for Amitran, the vehicle type instead comes from the `actorConfig` `id` attribute in the input file.
- **A TAZ needs at least one source and one sink edge** — a zone with only through-edges or only dead-ends may fail to generate trips in one direction.
- **Multiple od2trips calls need distinct `--prefix` values** to avoid id collisions, same as with `randomTrips.py`.
