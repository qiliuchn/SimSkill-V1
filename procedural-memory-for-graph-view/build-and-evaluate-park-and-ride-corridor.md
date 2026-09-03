---
name: build-and-evaluate-park-and-ride-corridor
description: Use this skill when the user wants to model park-and-ride (P+R), kiss-and-ride, or any car-to-transit intermodal trip in SUMO — a traveller who drives to a lot or station, parks, and completes the trip by bus/BRT/rail. Covers building a suburban-to-CBD radial corridor with a parallel transit line and pedestrian stop access, sizing parkingArea lots with finite capacity, routing personTrip modes="car public" with duarouter's --persontrip.transfer.car-walk option (parkingAreas vs ptStops vs allJunctions), the mandatory post-processing step that actually couples the car to a parking space, measuring lot occupancy / P+R mode share / door-to-door time decomposition / arterial relief, and running lot-capacity, overflow-rerouting, lot-siting and headway sensitivity sweeps. Trigger on park-and-ride, P+R, kiss-and-ride, park & ride lot, car-to-transit transfer, intermodal transfer, persontrip.transfer.car-walk, drive-to-station, or "drive part-way then take the train."
related_skills:
  - model-parking-with-rerouting
  - simulate-multimodal-transit
  - convert-trips-to-routes
  - analyze-simulation-outputs
  - create-grid-network
related_skills_for_graph_view:
  - "[[model-parking-with-rerouting]]"
  - "[[simulate-multimodal-transit]]"
  - "[[convert-trips-to-routes]]"
  - "[[analyze-simulation-outputs]]"
  - "[[create-grid-network]]"
related_pages:
  - "[[car-to-transit-intermodal-transfer-and-park-and-ride]]"
  - "[[parking-areas-and-rerouters]]"
  - "[[public-transport-and-intermodal-routing]]"
---

# Build and Evaluate a Park-and-Ride Corridor

Builds a radial suburb→CBD corridor with a parallel transit line and finite-capacity P+R
lots, lets `duarouter` choose drive-all-the-way vs. drive-to-lot-then-ride for each person,
and measures what that choice does to lot occupancy, mode share, door-to-door time and
corridor delay. This is the only skill in memory that exercises a **car leg followed by a
transit leg inside one person's plan** — `simulate-multimodal-transit` covers walk-or-ride
only, and `model-parking-with-rerouting` covers parking without any person/transit side.

## The single most important thing to know

**`duarouter --persontrip.transfer.car-walk parkingAreas` does NOT park the car.**
Verified on SUMO 1.27.1: the router uses `parkingArea` elements purely as *permitted transfer
geometry*. It ends the car leg at the lot's position (`<ride ... arrivalPos="1025.00"/>`) but
writes **no** `<stop parkingArea=... parking="true"/>` into the `<vehicle>` it generates. At
simulation time the car simply arrives and is removed. Consequences if you don't fix this:

- `traci.parkingarea.getVehicleCount()` stays **0** for every lot, all run long.
- `roadsideCapacity` is **never enforced** — a 20-space lot happily "serves" 200 P+R trips.
- Every capacity/overflow/pricing experiment you build on top is silently meaningless.

The fix is `scripts/attach_parking_stops.py`: it matches each multi-leg person's car-leg
`arrivalPos` against the lots' `[startPos,endPos]` on the same edge and injects the missing
stop. **Always run it, and always verify a nonzero peak occupancy afterwards.**

## Workflow

```bash
export SUMO_HOME=/path/to/sumo            # sumolib/traci live in $SUMO_HOME/tools
export PYTHONPATH=$SUMO_HOME/tools

# 1. network: dispersed suburb -> arterial -> signalised CBD grid, plus a
#    bus-only busway parallel to the arterial, with sidewalks/crossings.
python scripts/build_network.py --out-dir outputs/net

# 2..6. one case, end to end (supply -> route -> couple -> simulate -> analyse)
python scripts/run_case.py --name A_parkingAreas --transfer parkingAreas
python scripts/run_case.py --name D_cap50  --lots PR_MID,PR_MID2 --cap-mid 50 --cap-mid2 0
python scripts/run_case.py --name E_cap50_rr --lots PR_MID,PR_MID2 --cap-mid 50 \
       --cap-mid2 400 --rerouter PR_MID:PR_MID2       # overflow remedy
python scripts/make_tables.py                          # CSVs + figures over all cases
```

`run_case.py` chains `build_scenario.py` → `duarouter` → `attach_parking_stops.py` →
`run_pr_scenario.py` (TraCI) → `analyze_pr.py`. Knobs: `--cap-main/--cap-overflow/--cap-mid/
--cap-mid2`, `--only-lots` (siting), `--headway`, `--transfer`, `--rerouter PRIMARY:ALTS`,
`--pm-share`, `--release-at`.

### Making P+R actually competitive

Under free-flow weights `duarouter` puts **100 %** of demand on drive-all-the-way — driving
6 km at 22 m/s beats any walk+wait+ride chain. P+R only appears once the router sees
congestion. Do a two-pass assignment:

1. Run a drive-only baseline (`--modes car`), letting SUMO write `edgeData`.
2. Feed that file back as `duarouter -w baseline/edgedata.xml` for the intermodal pass.

This is a **one-shot informed assignment, not an equilibrium** — after the shift, driving gets
faster than the weights said, so the P+R users' realised travel time can end up *worse* than
the drive-alone users they relieved. Report it as such (or iterate to convergence with
`compute-dynamic-user-equilibrium`'s machinery if equilibrium matters).

## The three car-walk transfer options are three different policies

| `--persontrip.transfer.car-walk` | plan shape | ties to a lot? |
|---|---|---|
| `parkingAreas` | `ride(car)` → `walk` → `access` → `ride(PT)` → `access` → `walk` | yes — car leg ends inside a `parkingArea` |
| `ptStops` | `ride(car, busStop=…)` → `ride(PT)` → `walk` | **no** — car leg ends *at the stop*; this is kiss-and-ride, parking supply is bypassed entirely |
| `allJunctions` | car may be abandoned at any junction, then walk | only by accident |

Only `parkingAreas` produces a plan whose car leg can be coupled to finite parking supply.
If a study is about lot capacity/pricing, `ptStops` will look like it works and quietly
enforce nothing. See [[car-to-transit-intermodal-transfer-and-park-and-ride]] for measured
mode shares and travel-time decompositions under each.

## What to measure, and from where

- **Lot occupancy over time** — TraCI only (`traci.parkingarea.getVehicleCount/getVehicleIDs`);
  there is still no `--parking-output` CLI flag in 1.27.x. `run_pr_scenario.py` samples it.
- **Door-to-door decomposition** — straight off `<personinfo>` legs in `tripinfo.xml`:
  car `<ride>` = drive, pre-PT `<walk>`+`<access>` = walk-access, `waitingTime` on the PT
  `<ride>` = wait, PT `<ride>` duration = ride, post-PT legs = egress. `analyze_pr.py` does this.
- **Corridor relief** — `edgeData` `entered` / `traveltime` / `timeLoss` on the arterial and
  CBD gate links, differenced against the drive-only baseline.
- **Failure counts** — teleports, persons still in `traci.person.getIDList()` at the end
  (never arrived), and `<ride vehicle="NULL" duration="-1">` legs (waited for a PT vehicle
  that never came).

## Gotchas

- **`<stop parkingArea>` is mandatory for occupancy** — see the box above. Verify peak
  occupancy > 0 before believing any capacity result.
- **`duarouter` is capacity-blind.** With a 20-space lot it still assigns all ~190 P+R trips
  to it. Nothing warns you; the mismatch only shows up in the simulation.
- **A vehicle turned away from a full lot does not give up and does not self-reroute.** It
  waits on the approach lane for a space — measured car-leg means of 5 191 s (max 18 586 s) —
  and blocks general traffic behind it. `--time-to-teleport` is what eventually converts that
  into a countable failure. Persons whose car is teleported can end up never arriving.
- **The remedy is `parkingAreaReroute` + `--device.rerouting.probability 1`**, and it composes
  safely with person plans: when the car is redirected to a different lot, the rider gets off
  there and SUMO **re-resolves the following walk leg** to the target `busStop` even though the
  routed plan named a different edge. Requirement: the alternative lot must have pedestrian
  access to a stop on the same line, otherwise the re-resolved walk is long or impossible.
- **`--stop-output` writes nothing for a car still parked at simulation end** — stop rows are
  only emitted when a stop *ends*. Add `--stop-output.write-unfinished`, or use the TraCI
  occupancy series instead.
- **A stop ends at `max(until, arrival+duration)`.** Setting `until=` while leaving a long
  `duration=` makes `until` a silent no-op — drop `duration` to ~1 s when you want an absolute
  release time (`attach_parking_stops.py --release-at`).
- **`file=` inside an `<edgeData>`/additional element resolves relative to that additional
  file's own directory**, not the cwd. Passing a cwd-relative path produces a doubled path and
  a hard `Could not build output file` abort.
- **SUMO has no notion of "my car is parked at the station."** A PM return `personTrip` from the
  CBD generates a **brand-new vehicle** at the CBD; the AM car sits in the lot forever unless
  you script its release. `--release-at` does that (verified: 188 spaces drain to 0 within
  ~300 s of the release time), but it is a modelling device, not SUMO reuniting a person with
  their car.
- **A bus-only busway physically disconnected from the road network works fine** as a
  rail/BRT stand-in, provided every `busStop` carries `<access lane="<sidewalk>" length="…"/>`.
  The `<access>` legs show up explicitly in `<personinfo>` and are how walk-access/egress time
  enters the decomposition.
- **`summary-output`'s `collisions=` is an instantaneous state count, not a cumulative event
  count.** Summing it over steps gave 18 472 for a run that `--collision-output` showed
  contained exactly **one** collision (a 0.64 m/s rear-end inside the CBD gate queue) whose
  state simply persisted for the rest of the run. Use `--collision-output` to count collisions.
- **`--sidewalks.guess` adds a sidewalk even to `allow="bus"` edges**, and skips edges above
  `--sidewalks.guess.max-speed` (default 13.89 m/s) — raise it if the arterial needs one.

## Related

- `model-parking-with-rerouting` — the `parkingArea`/`rerouter`/`parkingAreaReroute` mechanics
  and the TraCI occupancy-sampling pattern this skill's runner is adapted from.
- `simulate-multimodal-transit` — the busStop/`<access>`/scheduled-`until=`-line half of the
  scenario; its "an unscheduled line silently routes everyone to walk" gotcha applies here too.
- `convert-trips-to-routes` — `duarouter` conventions, including `-w` weight files.
- `analyze-simulation-outputs` — output-file parsing conventions.
- `create-grid-network` — grid/network construction conventions for the CBD portion.
- [[car-to-transit-intermodal-transfer-and-park-and-ride]] — the mechanism reference and all
  measured findings behind this workflow.
- [[parking-areas-and-rerouters]], [[public-transport-and-intermodal-routing]] — the two
  underlying SUMO subsystems this skill joins together.
