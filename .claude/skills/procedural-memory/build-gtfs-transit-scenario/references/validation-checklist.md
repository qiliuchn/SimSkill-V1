# Checklist: validating a GTFS import before trusting any result from it

Every item below is a *check that failed or nearly failed* on a real feed
(TriMet, 2026-07-05 edition) imported onto a real OSM network (SE Portland,
4.1 x 3.0 km), so none of them is hypothetical. Run them in order; each one is a
single command or a few lines of parsing, and each catches a distinct silent
failure mode.

## 0. Prove the inputs are real

- [ ] **Did the feed actually download?** Check HTTP status *and* the byte count,
      then open the zip and list members. A 200 with `size_download=0` (what a
      `curl -I` gives on many CDNs) is not a download.
- [ ] **Is the feed valid for the date you will import?** `feed_info.txt`
      (`feed_start_date`/`feed_end_date`) and `calendar.txt` must both cover
      `--date`. A date outside the calendar yields *zero* trips and `gtfs2pt`
      still exits 0.
- [ ] **Does the network carry PT infrastructure at all?** `netconvert` only
      emits stops/lines when asked: `--ptstop-output`, `--ptline-output`,
      `--osm.stop-output.length`. Without them the OSM path silently has nothing
      to import.
- [ ] **Can pedestrians reach the stops?** Build with `--sidewalks.guess
      --crossings.guess --walkingareas`. Note that `gtfs2pt` writes an
      `<access>` child **only when the stop's edge does not already allow
      pedestrians** (`gtfs2osm.getAccess`), so on a sidewalk-guessed network the
      expected, correct output is **zero** `<access>` elements — do not read
      that as a failure.

## 1. Count everything on both sides of the import

Never assume `gtfs2pt` imported what you handed it. Build this table:

| quantity | where from |
|---|---|
| trips in the feed for `--date` | `trips.txt` x `calendar(.txt/_dates.txt)` |
| stop visits in the feed | `stop_times.txt` rows for those trips |
| unique stops in the feed | distinct `stop_id` among those rows |
| PT vehicles written | `<vehicle>` count in `--route-output` |
| distinct routes written | `<route>` count in the same file |
| busStops written | `<busStop>` count in `--additional-output` |
| stop visits retained | sum over routes of `<stop>` children |
| PT vehicles **inserted** | `statistic-output` `<vehicles inserted=>` minus cars |
| stop visits **served** | rows in `--stop-output` |
| vehicles completing the full sequence | group `--stop-output` by vehicle id |

Trip loss and stop loss are *different numbers* and can move independently: in
the verified case trip loss was 0% while stop-visit loss was 10.2%.

## 2. Check *where* the losses are, not just how many

- [ ] Compute each lost stop's distance to the network boundary. If losses cluster
      in a fringe band (verified: all 10 lost stops sat 156-203 m from the edge,
      while retained stops had a median fringe distance of 723 m), the attrition
      is a **clipping artifact**, not random noise, and it biases exactly the
      terminal ends of every line.
- [ ] For each lost stop, find the nearest lane that `allows("bus")`. If none is
      within the matcher's `--radius` (default 150 m), the stop was unmappable
      because the road it belongs to was cut away by the bbox or by
      `--keep-edges.by-vclass`.

## 3. Check stop placement quality, not just stop existence

- [ ] Convert each emitted `busStop`'s lane position back to lon/lat and compare
      with the feed's published `stop_lat`/`stop_lon`. Report the whole
      distribution: verified median 8.1 m, p90 14.9 m, p95 50.3 m, max 143.6 m,
      with 8.7% of stops beyond 25 m. A good median hides a bad tail.
- [ ] Check the **direction** of the lane each stop landed on against the bearing
      implied by the published stop sequence. A stop matched onto the opposing
      carriageway is geometrically within a few metres and completely wrong
      operationally.

## 4. Check for repaired-but-distorted routes

- [ ] Count U-turn pairs (`edge` immediately followed by `-edge`) in every
      generated `<route>`. `--repair` fixes disconnected traces by routing around
      them, and the repair shows up as these pairs.
- [ ] Compare route length (edge lengths **plus junction-internal lengths** —
      `<route edges>` omits internal edges, so a naive sum under-estimates by
      20-30%) against the straight-line chain through the retained stops.
      Verified separation: routes with 0 U-turn pairs had detour factor
      1.03-1.09; every route that needed `--repair` had 1.70-2.52. A repaired
      route is not a warning to ignore — it is a bus driving up to 2.5x the
      distance it should.

## 5. Check what the schedule actually means in SUMO

- [ ] `gtfs2pt` writes one shared `<route>` per distinct mapped stop sequence with
      `<stop until>` values **relative to that route's first stop**, plus one
      `<vehicle depart>` per GTFS trip, where
      `depart = published_first_stop_time - --duration`. SUMO shifts a referenced
      route's stop times by the vehicle's depart time, so the published
      *inter-stop* timetable does survive — but the effective schedule sits
      `--duration` seconds ahead of the published one. **Verified** by rebuilding
      the identical run with absolute published `until` values: across all 412
      stop events the SUMO-reported `<stopinfo delay>` was ~10 s larger in the
      relative-until arm (modal difference exactly 10 s, spread ±2 s from
      micro-dynamics) while actual arrival times were unchanged (modal difference
      0 s). So **`stopinfo delay` is not the deviation from the published
      timetable** — compute deviation yourself against `stop_times.txt`.
- [ ] Trips that map to the same stop sequence are collapsed onto one route, so
      per-trip differences in the published stop list are lost (verified: 15 of
      412 vehicle-stop pairs, 3.6%, could not be traced back to that specific
      trip's `stop_times`).
- [ ] Decide explicitly whether you want schedule *holding*. With `until` present
      an early bus is held at the stop; strip `until` and dwell becomes purely
      endogenous. The two give different adherence numbers from identical supply.

## 6. Check the simulation, not just the import

- [ ] Teleports per 1000 inserted vehicles, at every demand level. Verified on
      this network (gtfs_rel arm): 0 at 0 veh/h, 88.9/1000 at 1200, 138.4/1000 at
      2400 and 282.5/1000 at 3600 veh/h — the top level is dominated by teleport
      artifacts and its travel times are not physically meaningful.
- [ ] Completed vs still-running accounting for vehicles **and** persons: a person
      still riding at `--end` never contributes a ride waiting time, so a metric
      that only averages finished trips silently gets better as the network gets
      worse.
- [ ] Run a **zero-car negative control**. Free-flow adherence is the ceiling; if
      the timetable is already infeasible with no other traffic, the network,
      the stop placement or the repaired route is at fault, not congestion.

## 7. Cross-check against the second import path

- [ ] Run `ptlines2flows.py` on the same network from the `--ptline-output` file
      and compare stop counts per line. Verified: the OSM relations for the same
      four bus lines yielded 27 stop visits across 7 line variants versus 397
      across 8 from GTFS, and one line (9) disappeared entirely because its OSM
      relation retained fewer than 2 stops inside the bbox. `completeness=` in the
      `ptline-output` is the early warning — values of 0.01-0.16 mean the relation
      is mostly outside your extract.
