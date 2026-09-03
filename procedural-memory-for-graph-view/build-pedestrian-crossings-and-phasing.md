---
name: build-pedestrian-crossings-and-phasing
description: Use this skill when the user wants to add sidewalks and marked pedestrian crossings to a SUMO intersection, model pedestrian demand crossing at a signal, and/or compare pedestrian-phasing schemes (exclusive "scramble" phase vs. concurrent/permissive crossing on the vehicle green) — including quantifying pedestrian delay, vehicle delay, and pedestrian-vehicle conflict exposure. Covers netconvert's --sidewalks.guess/--crossings.guess/--walkingareas, the resulting crossing/walkingarea net elements and tlLogic link indexing, building a custom exclusive-pedestrian-phase signal program, and measuring conflict exposure via TraCI since SUMO's SSM device doesn't cover pedestrian-vehicle conflicts. Trigger on mentions of pedestrian crossing, crosswalk, sidewalk, walkingarea, pedestrian scramble, Barnes dance, or pedestrian signal phasing.
related_skills:
  - create-single-intersection
  - simulate-multimodal-transit
  - analyze-intersection-safety-with-ssm
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
  - analyze-simulation-outputs
  - characterize-pedestrian-flow-and-striping-model-artifacts
related_skills_for_graph_view:
  - "[[create-single-intersection]]"
  - "[[simulate-multimodal-transit]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
related_pages:
  - "[[pedestrian-crossings-and-signal-phasing]]"
---

# Build Pedestrian Crossings and Signal Phasing

Adds sidewalks and marked pedestrian crossings to a SUMO network, models pedestrian demand traversing them, and compares signal-phasing schemes for how they serve pedestrians at a crossing — most importantly the **exclusive ("scramble"/Barnes-dance) phase** (all vehicle movements red while every crossing is green) against **concurrent/permissive crossing** (pedestrians cross in parallel with the green vehicle phase, exposed to permitted turns). This is SimSkill's only skill treating pedestrians as first-class simulation agents with real infrastructure, as opposed to `simulate-multimodal-transit`'s walk-as-a-mode-choice-leg treatment.

## Adding sidewalks and crossings

```bash
netconvert -n base.nod.xml -e base.edg.xml \
    --sidewalks.guess --crossings.guess --walkingareas -o net.xml
```

This adds, per approach that has a sidewalk, a `<edge function="crossing" crossingEdges="...">` (the marked crosswalk) and `<edge function="walkingarea">` elements (the corner areas pedestrians traverse to reach a crossing), and extends the intersection's `<tlLogic>` state strings with additional characters for the new crossing signal links.

**Verify on the compiled net, not just by checking netconvert's exit code**: `grep 'function="crossing"'` / `grep 'function="walkingarea"'` should show one crossing per approach that got one, and the `<tlLogic>` phase state-string length should equal `(vehicle link count) + (crossing link count)` — confirm this by counting `<connection tl="<tls-id>" linkIndex="...">` entries in the compiled net and cross-referencing each `linkIndex` against the state string position.

## Understanding crossing link indexing

Each crossing edge has its own `<connection from=":<node>_wN" to=":<node>_cM" tl="..." linkIndex="K">` entry (from an internal walkingarea to the internal crossing lane), assigned a link index in the *same* numbering space as ordinary vehicle `<connection>` entries. The crossing edge's own `<edge function="crossing" crossingEdges="edgeA edgeB">` attribute names the real vehicle edges it physically spans — this is the key to programmatically finding which vehicle movements conflict with a given crossing (any vehicle `<connection>` whose `from` or `to` edge is in `crossingEdges`), without hand-mapping arm names or geometry.

## Building an exclusive/scramble phase

`netconvert --tls.scramble.time <n>` **has been observed to have no effect** on at least one SUMO build (verified by diffing its output against the same command without the flag — byte-identical `tlLogic`). Don't assume the flag works without checking the compiled net's phases actually differ; build the phase explicitly instead:

```xml
<additional>
    <tlLogic id="center" type="static" programID="scramble" offset="0">
        <phase duration="30" state="GGrrrrrrrrrrrrrrrrrrrrrr"/>  <!-- normal vehicle phase, crossings red -->
        <phase duration="4"  state="yyrrrrrrrrrrrrrrrrrrrrrr"/>
        <phase duration="15" state="rrrrrrrrrrrrrrrrrrrrGGGG"/>  <!-- exclusive: all vehicles red, all crossings green -->
        <!-- ...remaining phases... -->
    </tlLogic>
</additional>
```

**An additional-file `<tlLogic>` cannot reuse the network's own `programID`** ("Another logic with id ... exists") — give it a distinct `programID` and activate it explicitly with `traci.trafficlight.setProgram(tls_id, "scramble")` after `traci.start()`, rather than expecting SUMO to pick it automatically at load time from an `--additional-files` entry alone.

**Verify the exclusive phase genuinely holds**, don't just trust the XML: step through the simulation via TraCI, read `traci.trafficlight.getRedYellowGreenState(tls_id)` each step, and confirm at least one observed state has every crossing-link character in `"gG"` and every vehicle-link character equal to `"r"`.

## Modeling pedestrian demand

```bash
randomTrips.py -n net.xml -o ped.trips.xml --pedestrians --fringe-factor max
duarouter -n net.xml -r ped.trips.xml -o ped.rou.xml
sumo -n net.xml -r veh.rou.xml,ped.rou.xml --pedestrian.model striping --tripinfo-output tripinfo.xml
```

Combine vehicle and pedestrian route files as a comma-separated `-r` list (or in a `.sumocfg`). `--pedestrian.model striping` is SUMO's higher-fidelity 2D pedestrian model (vs. the simpler `nonInteracting` default) and is what makes pedestrians occupy specific positions on a crossing edge, which the conflict-exposure measurement below depends on.

Tripinfo output mixes `<tripinfo>` (vehicles) and `<personinfo>` (pedestrians) elements in the same file — `scripts/parse_tripinfo_by_mode.py` splits and summarizes both.

## Measuring pedestrian-vehicle conflict exposure

**SUMO's SSM device only covers vehicle-vehicle conflicts** (see [[surrogate-safety-measures]]) — it has no pedestrian-aware mode. Pedestrian-vehicle conflict exposure has to be measured directly via TraCI. `scripts/measure_conflict_exposure.py` derives, purely from the compiled net.xml's own `crossingEdges` attributes and `<connection>` list (no hardcoded arm names or link tables — works on any signalized intersection with crossings), which vehicle movements conflict with each crossing, then steps the simulation counting ticks where a pedestrian physically occupies a crossing **while** its signal is walk **and** a conflicting vehicle movement is simultaneously signal-permitted and physically present on its via-lane:

```bash
python scripts/measure_conflict_exposure.py \
    --net net.xml --veh-routes veh.rou.xml --ped-routes ped.rou.xml \
    --tls-id center --tripinfo out/tripinfo.xml --conflict-out out/conflict.json \
    --additional scramble.tll.xml --program scramble --scramble-program scramble
```

It also reports two sanity denominators — `ped_on_crossing_ticks` (any signal state) and `phys_conflict_ticks_ignoring_signal` (physical co-occupancy regardless of signal permission) — cross-check the headline `conflict_exposure_ticks` against these: a signal-aware count that's implausibly close to the signal-agnostic physical count for a scheme that's supposed to prevent conflicts (e.g. an exclusive scramble) is a sign the signal-state gating isn't actually working.

## What the exclusive-vs-concurrent comparison tends to show

Measured on a 4-way intersection at equal 90s cycle length, 200 vehicles + 334 pedestrians, identical demand across both configs: an exclusive scramble phase **eliminates** pedestrian-vehicle conflict exposure (0 signal-aware conflict ticks vs. a concurrent scheme's real, nonzero count), but at a fixed cycle length it costs **both** modes delay — pedestrians wait longer for their one narrow crossing window, and vehicles lose green time to the added all-red interval — rather than being a free win for pedestrians. Concurrent/permissive crossing is faster for both pedestrians and vehicles but sustains genuine conflict exposure from permitted turns. Neither dominates; it's a real delay-vs-safety tradeoff, not a one-sided improvement — don't report an exclusive phase as strictly better for pedestrians without checking its delay cost too.

## Gotchas

- **`netconvert --tls.scramble.time` may not inject a phase** — verify the compiled program actually differs from a run without the flag before relying on it; build the phase explicitly via an additional-file `tlLogic` if it doesn't.
- **An additional-file `tlLogic` needs a distinct `programID`** from the network's own program, and needs `traci.trafficlight.setProgram` to actually activate it.
- **The SSM device does not cover pedestrians** — don't reach for it for a pedestrian-vehicle conflict measurement; use TraCI directly as above.
- **A crossing's own link index sits in the same state-string position space as vehicle links** — always re-derive indices from the compiled net's actual `<connection>`/`<edge function="crossing">` elements per network; never hardcode indices across different intersections or even across different variants of "the same" intersection (netconvert's link assignment can shift between compiles).

## Related

- `create-single-intersection` for the base 4-way network geometry before crossings are added.
- `simulate-multimodal-transit` — covers pedestrians as an intermodal mode-choice leg (walk-or-ride), distinct from this skill's focus on crossing infrastructure and signal-phase interaction.
- `analyze-intersection-safety-with-ssm` — vehicle-vehicle conflict measurement; this skill's TraCI-based approach is the pedestrian-vehicle analogue where the SSM device doesn't reach.
- `generate-random-trips`, `convert-trips-to-routes`, `run-simulation`, `analyze-simulation-outputs` — general demand/routing/run/analysis skills this one specializes for the pedestrian-crossing case.
- [[pedestrian-crossings-and-signal-phasing]] — the underlying SUMO concepts (crossing/walkingarea net elements, tlLogic link indexing, exclusive-phase construction, and the verified delay-vs-conflict-exposure tradeoff).
- `characterize-pedestrian-flow-and-striping-model-artifacts` — builds on this skill's crossing/walkingarea network construction and link-indexing technique, but treats pedestrians as a flow entity (fundamental diagram, capacity, congestion) rather than only a signal-phasing object.
