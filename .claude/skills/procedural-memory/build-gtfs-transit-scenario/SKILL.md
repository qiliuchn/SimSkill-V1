---
name: build-gtfs-transit-scenario
description: Use this skill when the user wants a SUMO public-transport scenario built from a REAL published GTFS feed (or from OpenStreetMap public-transport relations) rather than hand-authored busStops and lines — importing with tools/import/gtfs/gtfs2pt.py or ptlines2flows.py, verifying how much of the feed actually survived the import, and measuring schedule adherence against the published stop_times. Trigger on mentions of GTFS, gtfs2pt, gtfs2fcd, ptlines2flows, a transit agency feed, timetable/schedule adherence, on-time performance, real bus lines from a city, or "import the actual bus schedule".
---

# Build a GTFS-based transit scenario in SUMO

Turns a published GTFS feed plus a real OSM network into a running SUMO
public-transport scenario, and — the part that is usually skipped — **proves
quantitatively how much of the feed survived**. Distinct from
`simulate-multimodal-transit`, which hand-authors busStops and a synthetic
headway; here the stops, the routes and the timetable all come from real data and
every one of them can be silently damaged on the way in.

Reference: <https://sumo.dlr.de/docs/Tools/Import/GTFS.html>,
<https://sumo.dlr.de/docs/Tutorials/PT_from_OpenStreetMap.html>

## Pipeline

```
osmGet.py  ->  netconvert (--ptstop-output --ptline-output + sidewalks)
                     |                              |
                     |                              +--> ptlines2flows.py --> headway flows
                     v
GTFS feed -> subset -> gtfs2pt.py --> vtypes + busStops + PT vehicles
                     |
                     +--> verify (attrition, placement error, route distortion)
                     +--> randomTrips (cars) + person demand -> sumo -> stop-output
                     +--> schedule adherence vs stop_times.txt
```

### 1. Network — PT infrastructure is opt-in

```bash
python "$SUMO_HOME/tools/osmGet.py" --bbox=-122.655,45.500,-122.615,45.520 --prefix pdx
netconvert --osm-files pdx_bbox.osm.xml -o pdx.net.xml \
  --type-files "$SUMO_HOME/data/typemap/osmNetconvert.typ.xml,$SUMO_HOME/data/typemap/osmNetconvertPedestrians.typ.xml" \
  --geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.discard-simple --tls.join \
  --sidewalks.guess --crossings.guess --walkingareas \
  --ptstop-output pdx_stops.add.xml --ptline-output pdx_ptlines.xml --osm.stop-output.length 20 \
  --keep-edges.by-vclass passenger,bus,pedestrian --remove-edges.isolated
```

`osmBuild.py` has no PT flag — pass the three `pt*` options through `netconvert`
directly (or via `osmBuild.py -n`). See `load-osm-network` for the download stage
and [[openstreetmap]] for the bbox/typemap gotchas.

### 2. Get a real feed, and subset it honestly

Live feeds that were reachable and served a real zip on a plain `curl -L`:
TriMet `https://developer.trimet.org/schedule/gtfs.zip`, MBTA
`https://cdn.mbta.com/MBTA_GTFS.zip`, BKK Budapest
`https://www.bkk.hu/gtfs/budapest_gtfs.zip`. (`curl -I` returns
`size_download=0` on these CDNs — that is not a failed download; check the real
GET.) Aggregator portals — transitfeeds.com, files.mobilitydatabase.org — 403.

A national feed is far larger than any sensible network (TriMet: 209 MB of
`stop_times.txt`). `scripts/explore_feed.py` streams it and ranks routes by how
many trips have ≥3 stops inside the network bbox; `scripts/gtfs_subset.py` then
writes a schema-valid subset zip that keeps only *selected* published records —
chosen routes, the service date, each trip clipped to its maximal contiguous run
of in-bbox stops, first retained departure inside a chosen window. Nothing is
invented; `stop_sequence` is renumbered (GTFS only requires it to increase) and a
JSON ground-truth timetable is written alongside for adherence measurement.

### 3. Run `gtfs2pt.py` — the real contract

```bash
python "$SUMO_HOME/tools/import/gtfs/gtfs2pt.py" \
  -n pdx.net.xml --gtfs subset.zip --date 20260805 --modes bus --repair \
  --use-gtfs-stopids \
  --vtype-output pt_vtypes.xml --route-output pt_vehicles.rou.xml \
  --additional-output pt_stops.add.xml
```

| option | what it actually does |
|---|---|
| `-n/--network` | required; the tool internally splits it per vClass into `resources/<region>/<mode>.net.xml` |
| `--gtfs` | zip only (or `--merged-csv` from a previous run) |
| `--date YYYYMMDD` | selects `service_id`s via `calendar.txt`+`calendar_dates.txt`. Outside the feed's validity you get **zero trips and exit code 0** |
| `--modes` | comma list from bus,train,tram,light_rail,monorail,subway,aerialway,ferry,trolleybus |
| `--repair` | runs `duarouter --repair` over map-matched traces; prints `Warning! Fixed route X ... (added edges: N)` — **treat every such line as a damaged route, not a fixed one** |
| `--route-output` | `<route>` per distinct mapped stop sequence + `<vehicle>` per GTFS trip |
| `--additional-output` | the `<busStop>`s (+`<access>` only where needed) |
| `--vtype-output` | just `<vType id="bus" vClass="bus"/>` — **must be loaded**, or SUMO aborts with "The vehicle type 'bus' ... is not known" |
| `--use-gtfs-stopids` | names busStops `gtfs_<stop_id>`; makes every later verification a join instead of a guess. Use it |
| `--duration` (default 10) | the per-stop dwell floor written as `duration=`, and the offset applied to each vehicle's `depart` |
| `--radius` (default 150) | candidate-edge matching radius; stops further than this from a permitted lane are dropped |
| `--osm-routes` | optional OSM `ptline-output` used as route hints instead of pure trace matching |
| `--min-stops`, `--skip-access`, `--access-radius`, `--center-stops`, `--warn-unmapped` | see `--help`; `--warning-output`/`--dua-repair-output` only fill in on the `--osm-routes` path |

Needs `rtree` and `pyproj` — neither ships with SUMO. On a PEP-668 Python make a
venv: `python3 -m venv venv && venv/bin/pip install rtree pyproj`.

**Schedule semantics (verified, and easy to get wrong):** `writeRoute()` writes
each `<stop until>` *relative to the route's first stop*, and each vehicle's
`depart` is `published_first_stop_time − --duration`. SUMO shifts a referenced
route's stop times by the vehicle's depart time, so the published inter-stop
timetable does survive — but shifted `--duration` seconds early. Consequently
`<stopinfo delay>` is **not** deviation from the published timetable; compute it
yourself against `stop_times.txt`. Trips sharing a mapped stop sequence collapse
onto one `<route>`, so per-trip differences in the published stop list are lost.

`<access>` children are written **only when the stop's edge does not already
allow pedestrians** (`gtfs2osm.getAccess`). On a `--sidewalks.guess` network zero
`<access>` elements is the correct output, not a bug.

### 4. Verify before believing — `scripts/verify_import.py`

Emits the attrition table (feed trips/stop-visits/unique stops vs vehicles,
routes, busStops, retained stop visits), the stop-position error distribution
against the published lat/lon, a wrong-direction check, per-route U-turn-pair and
detour-factor diagnostics, and a fringe-distance comparison of lost vs kept stops.
The full protocol is in `references/validation-checklist.md`. Do not skip it: on a
real feed it found 10.2 % of stop visits lost, all of them within 200 m of the
network boundary, and four routes silently lengthened by 1.7-2.5x by `--repair`.

When computing a route's length from `<route edges>`, add the junction-internal
lengths (or `sumolib.net.readNet(..., withInternal=True)`): the edge list omits
internal edges and a naive sum under-estimates by 20-30 %, which is enough to
make a distorted route look shorter than the straight line through its own stops.

### 5. Demand, and the run

Background cars with `randomTrips.py --fringe-factor 5 --vehicle-class passenger
--edge-permission passenger --validate`; intermodal travellers as
`<personTrip modes="public">` resolved by SUMO internally at insertion (no
`duarouter` pass needed, and each arm then uses its own transit supply).
Anchoring person origins/destinations near stops of the same line
(`scripts/gen_persons.py`) is what makes wait time measurable at all — uniform
random person trips on a few-km network mostly walk.

```bash
sumo -n pdx.net.xml -a pt_stops.add.xml,pt_vtypes.xml \
     -r pt_vehicles.rou.xml,persons.rou.xml,cars.rou.xml \
     --begin 25200 --end 34200 --stop-output stopinfo.xml \
     --tripinfo-output tripinfo.xml --statistic-output stats.xml \
     --duration-log.statistics --pedestrian.model striping --ignore-route-errors
```

`--stop-output` is the adherence instrument: one `<stopinfo>` per vehicle x stop
with `started`, `ended`, `busStop`, `loadedPersons`, `blockedDuration`.

### 6. Measure adherence — `scripts/analyze_runs.py`, `scripts/hypothesis_tests.py`

Per-stop deviation vs the published arrival, on-time share, deviation growth
along the stop sequence, headway CV per served stop, dwell attribution, ride
waiting time, plus teleport/completion accounting. **Always split adherence by
line**: a repaired route and a clean route on the same network differed by 5.9x
in free-flow deviation, and pooling them hides the cause.

### 7. The other import path

```bash
python "$SUMO_HOME/tools/ptlines2flows.py" -n pdx.net.xml -l pdx_ptlines.xml \
   -s pdx_stops.add.xml -o pt_flows.rou.xml -p 847 -b 25200 -e 30600 --min-stops 2
```

Produces `<flow period=...>` per line variant plus its own `<vType>` set, and runs
SUMO once internally to derive stop `until` offsets. **Decision rule**: use
`gtfs2pt` whenever a feed exists for the modelled date and adherence/timetable
realism matters; use `ptlines2flows` when there is no feed, when only steady-state
frequency matters, or as a cross-check. Read `completeness=` in the
`--ptline-output` first — on a small extract the OSM relations are usually
truncated (observed 0.01-0.16, i.e. 7 % of the GTFS stop detail, with whole lines
dropped for `--min-stops`).

## Gotchas

- **`gtfs2pt.py` exits 0 with an empty import** if `--date` is outside the feed's
  calendar, or if every stop falls outside the network. Count the outputs.
- **`rtree` missing** is the first failure you will hit; it is an unvendored
  dependency of `gtfs2pt.py` (`import rtree` at module import time).
- **Forgetting `--vtype-output`'s file in `-a`** aborts the whole simulation.
- **Teleporting buses**: at 2 400-3 600 veh/h background demand, 16-28 % of the
  34 buses teleported at least once. A teleported bus skips the queue, so
  measured adherence becomes *optimistic* exactly where it looks worst. Apply
  `validate-congested-scenario-results-against-teleport-artifacts` before
  reporting any congested-transit number.
- **The `--duration` floor does all the dwell modelling** in a default import:
  many feeds publish `arrival_time == departure_time` at intermediate stops, and
  endogenous boarding adds only ~0.5 s/stop at low ridership.
- **Stripping `until`** (endogenous dwell, no schedule holding) barely changes
  vehicle adherence but drastically worsens passenger wait (+139 s in one paired
  test), because the intermodal router loses the timetable it plans against.

## Related

- `load-osm-network` — the network-acquisition stage.
- `simulate-multimodal-transit` — the hand-authored busStop/line/persontrip
  baseline this skill replaces with real data.
- `demonstrate-and-control-bus-bunching` — headway-CV methodology reused here.
- `validate-congested-scenario-results-against-teleport-artifacts` — mandatory
  before reporting congested-transit results.
- `generate-random-trips`, `analyze-simulation-outputs` — background demand and
  output parsing.
- [[gtfs-import-and-pt-representation-semantics]] — what the two importers mean
  and how they fail.
- [[public-transport-and-intermodal-routing]], [[openstreetmap]],
  [[sumo-stochastic-variability-and-replication-design]].
