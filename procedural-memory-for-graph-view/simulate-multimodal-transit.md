---
name: simulate-multimodal-transit
description: Use this skill when the user wants to model pedestrians, public transport (bus/rail lines with stops and schedules), or intermodal trips (walk-or-ride mode choice) in SUMO — as opposed to purely private-vehicle traffic. Covers generating pedestrian infrastructure (sidewalks, crossings) with netconvert, defining busStop/public-transport-line elements with schedules, generating and routing intermodal person demand, running a simulation with both vehicles and persons loaded, and analyzing the resulting walk-vs-ride modal split. Trigger on mentions of pedestrians, public transport, bus lines/stops, transit, modal split, intermodal trips, persontrips with mode choice, or "people walking or taking the bus."
related_skills:
  - create-grid-network
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
  - equilibrate-endogenous-mode-choice-with-transit-supply-feedback
  - design-bus-stop-placement-type-and-spacing
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[equilibrate-endogenous-mode-choice-with-transit-supply-feedback]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
related_pages:
  - "[[public-transport-and-intermodal-routing]]"
  - "[[sumo-output-files]]"
---

# Simulate Multi-Modal Transit

Models a scenario where people (not just vehicles) move through the network, choosing between walking and riding public transport — a different demand paradigm from every vehicle-only skill (`generate-random-trips`, `calibrate-demand-with-routesampler`, etc.), which never has to decide *how* a traveler gets somewhere, only *which route*. Here mode choice itself is part of what's being simulated and analyzed.

## The workflow

1. **Base network**: build with any network skill (`create-grid-network`, etc.) as usual.
2. **Add pedestrian infrastructure**: run the resulting `.net.xml` back through `netconvert` with pedestrian options — `netgenerate`/most network builders don't add sidewalks/crossings directly, so this is a required extra pass:
   ```bash
   netconvert -s base.net.xml --sidewalks.guess --crossings.guess --walkingareas -o pedestrian.net.xml
   ```
   This adds a sidewalk lane to every edge (pedestrian-only; the original driving lane(s) become pedestrian-disallowed) and generates crossing and walking-area geometry at intersections. See "What the network actually gets" below for what to expect in the output XML. Buses can simply use the normal driving lane (its default `vClass` permissions already include `bus`) — a dedicated bus lane isn't required unless the scenario specifically calls for one.
3. **Define PT infrastructure**: a `<busStop>` per stop location (an "additional" file) plus one or more **scheduled** lines. Use `scripts/generate_pt_lines.py` rather than hand-writing this — it emits the busStops (with the pedestrian `<access>` link every stop needs) and the scheduled vehicles for however many corridors you specify:
   ```bash
   python scripts/generate_pt_lines.py --line "ew:A2B2,B2C2,C2D2,D2E2" --line "ns:C0C1,C1C2,C2C3,C3C4" \
       --out-dir pt/ --headway 300 --horizon 3600
   ```
   See [[public-transport-and-intermodal-routing]] for why this must be **scheduled vehicles with `until=` times**, not a `<flow>` with plain `duration=` stops — the intermodal person router silently treats an unscheduled line as unusable, and it fails quietly (every person just walks) rather than erroring.
4. **Generate and route intermodal person demand**:
   ```bash
   python "$SUMO_HOME/tools/randomTrips.py" -n pedestrian.net.xml -o persons.trips.xml \
       --persontrips --persontrip.modes public -b 0 -e 3600 --period 12 --seed 42

   duarouter -n pedestrian.net.xml --additional-files pt/busstops.add.xml \
       -r pt/pt_vehicles.rou.xml,persons.trips.xml -o routed.rou.xml --ignore-errors
   ```
   `--persontrip.modes public` is the real flag for allowing walk-or-public-transport mode choice (values: `car`, `public`, `taxi`, combinable) — don't assume a specific "transfer" flag exists without checking `randomTrips.py --help`/`duarouter --help` first; SUMO's actual intermodal flag surface has changed across versions and doesn't always match what a task description or older tutorial says. Passing both the PT vehicles and the person trips to the same `duarouter -r` call (plus `--additional-files` for the busStops) is what lets it resolve each person's plan into concrete `<walk>`/`<access>`/`<ride>` legs automatically — no separate "transfer" step is needed.
5. **Run the simulation** with both the routed persons and the PT vehicles loaded (they can be one combined route file or comma-separated `-r` files), pedestrian dynamics on (the default `--pedestrian.model striping` is fine), and `--tripinfo-output` requested — once persons are loaded, SUMO automatically emits a `<personinfo>` element per person inside the tripinfo output alongside the normal per-vehicle `<tripinfo>` elements. See [[sumo-output-files]] for the `<personinfo>`/`<walk>`/`<access>`/`<ride>` schema.
6. **Analyze the modal split**:
   ```bash
   python scripts/analyze_modal_split.py --tripinfo tripinfo.xml --out-dir analysis/
   ```
   Classifies each person as "walked the whole trip" (no `<ride>` legs) or "rode transit" (≥1 `<ride>` leg), and reports per-group counts/share, mean travel time, mean walking distance, and mean waiting time, plus per-line boardings and mean PT-vehicle travel time. Produces `modal_split.csv` and a two-panel bar chart (`modal_split.png`).

## What the network actually gets from `--sidewalks.guess --crossings.guess`

- Every regular edge gains an additional lane (typically index `_0`) with `allow="pedestrian"`; the original driving lane(s) shift index and get `disallow="pedestrian"`.
- Pedestrian crossings appear as `<edge function="crossing">` elements, **not** a literal `<crossing>` tag — don't grep for the wrong element name when checking whether crossings were actually generated.
- `--walkingareas` adds `<edge function="walkingarea">` polygons at junctions, letting pedestrians move between sidewalks/crossings at an intersection instead of only along edges.
- A `busStop`'s `<access lane="<sidewalk-lane-id>" pos="..."/>` child is what actually connects a stop (which sits on the driving lane) to the pedestrian network — without it, persons have no path to reach or board at that stop.

## Gotchas

- **A `<stop>` with only `duration=` is not a schedule.** The intermodal person router requires an absolute `until=` arrival time at each stop for a line to be usable — otherwise it silently resolves every person to walk-only (no error, no warning that stands out; check for a nonzero ride count as your actual signal that routing worked, don't just check for a clean exit code).
- **Don't trust illustrative flag names from a task description or old tutorial without verifying.** `randomTrips.py --help` and `duarouter --help` are the ground truth for the current SUMO version — intermodal/persontrip flags have shifted names across releases.
- **`duarouter` does not echo PT vehicles into a separate "PT-only" output** — the simulation needs to load both the PT vehicle file and the routed person file (comma-separated `-r`, or merged), plus the busStops additional file.
- **A "reasonable" scenario can still show buses losing to walking on travel time** — on a small/dense network, per-stop dwell time plus waiting for the next scheduled departure can make riding slower door-to-door than walking directly, especially for short trips. That's a real result, not a sign something's broken; report it as part of the modal-split finding rather than assuming a bug.
- **Netgenerate-built networks default every junction to `priority`** unless told otherwise — if signals matter for the scenario, pass `-j traffic_light` when building the base network (see `create-grid-network`'s gotchas; `--tls.guess` alone is not reliable on a uniform grid).

## Related

- `create-grid-network` (or any other network skill) for the base network before adding pedestrian infrastructure.
- `generate-random-trips`, `convert-trips-to-routes` — the vehicle-only demand/routing skills this one extends into the person/intermodal domain.
- `run-simulation` for the actual simulation run mechanics (command-line vs. TraCI).
- [[public-transport-and-intermodal-routing]] — the underlying SUMO concepts (busStop/access/schedule syntax, intermodal routing mechanics) this skill's workflow is built on.
- [[sumo-output-files]] — the `<personinfo>` output schema this skill's analysis script parses.
- `equilibrate-endogenous-mode-choice-with-transit-supply-feedback` — extends this skill's fixed-frequency transit line to a ridership-responsive one, making mode choice a genuine equilibrium (with an operator headway rule and a Downs-Thomson-paradox test) rather than a one-shot output.
- `design-bus-stop-placement-type-and-spacing` — extends this skill's basic `busStop`/`access` mechanics into a full placement/type/spacing design study on a coordinated arterial, including verification of what `<stop parking="true">` actually does to the traffic stream.
