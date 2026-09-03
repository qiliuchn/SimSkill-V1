---
summary: What SUMO's two public-transport import paths actually produce — gtfs2pt.py's relative-until shared routes and depart-time offset, and ptlines2flows.py's headway flows from OSM relations — plus the four measured map-matching failure modes (fringe stop loss, placement error tail, opposing-carriageway matches, repair-induced route distortion) that make a "successful" import quietly wrong.
keywords:
  - gtfs
  - gtfs2pt
  - ptlines2flows
  - map-matching
  - schedule-adherence
  - public-transport-import
created: 2026-08-03T19:00:00
last_updated: 2026-08-03T19:00:00
sources:
  - "[[episodic-memory/2026-08-03_19-00-00/outputs/IMPORT_ATTRITION_TABLE.md]]"
  - "[[episodic-memory/2026-08-03_19-00-00/outputs/GTFS_IMPORT_VALIDATION_CHECKLIST.md]]"
  - https://sumo.dlr.de/docs/Tools/Import/GTFS.html
  - https://sumo.dlr.de/docs/Tutorials/PT_from_OpenStreetMap.html
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[openstreetmap]]"
  - "[[sumo-output-files]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[duarouter]]"
related_skills:
  - build-gtfs-transit-scenario
  - load-osm-network
  - simulate-multimodal-transit
  - demonstrate-and-control-bus-bunching
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[build-gtfs-transit-scenario]]"
  - "[[load-osm-network]]"
  - "[[simulate-multimodal-transit]]"
  - "[[demonstrate-and-control-bus-bunching]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# GTFS import and PT representation semantics in SUMO

SUMO has two independent ways to turn real-world public transport into simulated
vehicles, and they are not interchangeable. `tools/import/gtfs/gtfs2pt.py`
converts a published GTFS feed into scheduled vehicles; `tools/ptlines2flows.py`
converts the OpenStreetMap public-transport relations that `netconvert
--ptline-output` extracted into headway-based flows. This page records what each
one actually emits, verified against source and against a real import (TriMet
feed + SE Portland OSM extract), and the failure modes that survive a clean exit
code. See `build-gtfs-transit-scenario` for the executable pipeline and
[[public-transport-and-intermodal-routing]] for the underlying busStop/line model.

## Getting PT out of OSM at all

`netconvert` emits nothing PT-related unless asked: `--ptstop-output`,
`--ptline-output`, and `--osm.stop-output.length`. `osmBuild.py` has no flag for
these — pass them through `-n/--netconvert-options` or call `netconvert`
directly. Adding `--sidewalks.guess --crossings.guess --walkingareas` in the same
pass is what lets persons reach the stops.

## What `gtfs2pt.py` emits

Three files: `--vtype-output` (literally `<vType id="bus" vClass="bus"/>` — the
simulation aborts with *"The vehicle type 'bus' ... is not known"* if you forget
to load it), `--additional-output` (`<busStop>`s), and `--route-output`.

The route file's structure is the part that surprises people:

- **One `<route>` per distinct *mapped* stop sequence**, not per trip. Trips whose
  published stop lists differ but which map to the same sequence are collapsed;
  the per-trip detail is lost silently (measured: 3.6 % of vehicle-stop events
  could not be traced back to their own trip's `stop_times`).
- **`<stop until>` is written relative to the route's first stop.** `writeRoute()`
  subtracts the first stop's time as an offset.
- **`depart = published_first_stop_time − --duration`** (`filter_trips()`).
- SUMO **shifts a referenced route's stop times by the vehicle's depart time**, so
  the published *inter-stop* timetable does survive — displaced `--duration`
  seconds early. Verified by rebuilding the same scenario with per-trip absolute
  `until` values: over 412 stop events the reported `<stopinfo delay>` was ~10 s
  larger in the relative-until arm (modal difference exactly 10 s) while actual
  arrival times were unchanged (modal difference 0 s).

**Therefore `<stopinfo delay>` is not schedule deviation from the feed.** Compute
deviation as `stopinfo.started − stop_times.arrival_time` yourself; `--use-gtfs-stopids`
(busStops named `gtfs_<stop_id>`) turns that from a guess into a join.

`--duration` (default 10 s) also *is* the dwell model in a default import: many
feeds publish `arrival_time == departure_time` at intermediate stops, so the
GTFS-implied dwell is zero and everything above the floor has to come from
endogenous boarding — which contributed only ~0.5 s per stop at ~0.6 boardings
per stop visit.

`<access>` children appear **only when the stop's edge does not already allow
pedestrians** (`gtfs2osm.getAccess`). On a sidewalk-guessed network, zero
`<access>` elements is correct output.

Dependencies: `rtree` (imported at module load) and `pyproj`. Neither ships with
SUMO; on a PEP-668 Python this means a venv.

## How stops are map-matched

`gtfs2pt` converts each trip into an FCD trace (from `shapes.txt` + stop
coordinates), splits the network per vClass, and map-matches with
`sumolib.route.mapTrace` inside `--radius` (default 150 m); each stop is then
snapped to a lane with `gtfs2osm.getBestLane`. Two things go wrong quietly:

1. **"Found no candidate edges for x,y (index k)"** — the stop is dropped from
   that route, and the *remaining* busStops are renumbered, so busStop index no
   longer equals published stop index.
2. **`--repair`** then routes around the gap with `duarouter --repair`, printing
   `Warning! Fixed route X between A and B (added edges: N)`. That warning is the
   signature of a distorted route, not a fixed one.

## The four measured failure modes

Measured on 34 real trips / 442 published stop visits / 102 unique stops:

| mode | how to detect | measured |
|---|---|---|
| **fringe stop loss** | distance from each lost stop to the network boundary | 10 stops lost (9.8 %), all 156-203 m from the edge vs a 723 m median for retained stops; 4 had no bus-permitting lane within 200 m |
| **placement error tail** | busStop lane position → lon/lat vs published lat/lon | median 8.1 m but p95 50.3 m, max 143.6 m, 8.7 % beyond 25 m |
| **opposing carriageway** | sign of the dot product of the stop lane's direction with the bearing implied by the published stop order | 2 of 92 stops |
| **repair-induced distortion** | count `edge`/`-edge` adjacent pairs; compare route length (edges **plus junction-internal lengths**) against the straight-line chain through its stops | detour factor 1.03-1.09 for routes needing no repair vs **1.70-2.52** for all four repaired ones — perfect separation |

The `<route edges>` list omits internal edges, so a naive length sum
under-estimates by 20-30 % — enough to make a distorted route appear *shorter*
than the straight line through its own stops. Add the connection/via lengths (or
read the net `withInternal=True`).

**Trip-level and stop-level attrition are independent numbers.** In the verified
import 34 of 34 trips were written, inserted and completed — a 0 % trip loss
sitting on top of a 10.2 % stop-visit loss.

## Consequences for schedule adherence

Route distortion, not congestion, dominated adherence in the verified scenario.
With **zero** background traffic the mean deviation from the published timetable
was already +155 s and on-time performance 78.5 %; split by route, the repaired
lines averaged 310.7 s of free-flow deviation against 52.7 s for the cleanly
imported ones (5.9x). Adding 1 200/2 400/3 600 veh/h of background car demand
raised mean deviation to 272/346/497 s and dropped on-time performance to
70/64/58 %, all paired increments significant — real, but second-order compared
to the import artifact. **Always split adherence by line before attributing it to
traffic**, and always run a zero-car negative control as the feasibility ceiling.

Buses themselves teleport under congestion (16-28 % of them at 2 400-3 600 veh/h
on this network), which makes congested adherence *optimistic* — see
[[teleport-artifacts-and-gridlock-resolution-validity]].

## `ptlines2flows.py`: the other path

Input is `netconvert --ptline-output` plus `--ptstop-output`; output is one
`<route>` + `<flow period=...>` per line variant, its own full `<vType>` set, and
stop `until` offsets that the tool derives by **running SUMO once internally**
("running SUMO to determine actual departure times"). Lines with fewer than
`--min-stops` (default 2) surviving stops are skipped with a warning.

Its ceiling is the OSM relations' completeness, which `netconvert` reports as the
`completeness=` attribute on each `<ptLine>` and as
`PT line '%' ... has a gap of % stops, only keeping first part` warnings. On a
4x3 km extract the ten relations for four TriMet bus lines carried
`completeness` 0.01-0.16, yielding **27 stop visits across 7 line variants**
against **397 across 8** from the GTFS feed for the same four lines — and one
line disappeared entirely. Check `completeness=` before trusting this path.

### Decision rule

- **Use `gtfs2pt`** whenever a feed covering the modelled date exists and
  schedule adherence, timetable realism, per-trip variation, or on-time
  performance is part of the question.
- **Use `ptlines2flows`** when no feed exists, when only steady-state service
  *frequency* matters, or as an independent cross-check of stop coverage.
- **They disagree on content, not just on form.** At matched mean frequency
  (period set to the observed GTFS mean headway of 847 s) the headway-flow arm
  produced 4x more regular service (headway CV 0.04 vs 0.18 in free flow, 0.11 vs
  0.31 at 3 600 veh/h) and 31-155 s shorter mean passenger waits — but also half
  the ridership (114 vs 233 rides of 400 travellers), because its stop coverage
  is a fraction of the feed's. On real OSM data those two effects cannot be
  separated, which is itself the practical finding.

Stripping `until` from the imported routes (endogenous dwell, no schedule
holding) barely moved vehicle adherence — 154.4 vs 154.7 s mean deviation,
p = 0.62 — because the buses are late rather than early and holding almost never
binds (<1 % of arrivals more than 60 s early). It did move *passengers* a lot:
mean ride wait rose from 271.6 s to 410.5 s, because SUMO's intermodal router
loses the timetable it plans against. **Which dwell/schedule representation you
choose changes the passenger conclusion far more than the vehicle one.**
