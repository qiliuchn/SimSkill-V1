---
name: generate-demand-with-jtrrouter
description: Use this skill when the user wants to generate SUMO traffic demand from fringe inflow rates plus per-junction turning-movement ratios (left/through/right splits) — jtrrouter — rather than an OD matrix (od2trips), random sampling (randomTrips), or a candidate route pool matched to counts (routeSampler). Covers authoring the <turns> edgeRelation XML schema, fringe-only flow definitions, the jtrrouter command line (--sink-edges, --turn-ratio-files), and verifying the realized turn split against the specification from both the router's own output and the simulated executed routes. Trigger on mentions of jtrrouter, turning-movement counts, turn ratios, or turning-ratio-based demand.
related_skills:
  - calibrate-demand-with-routesampler
  - convert-od-matrix-to-trips
  - generate-random-trips
  - create-single-intersection
  - create-grid-network
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[calibrate-demand-with-routesampler]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[generate-random-trips]]"
  - "[[create-single-intersection]]"
  - "[[create-grid-network]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[jtrrouter]]"
---

# Generate Demand with jtrrouter

Generates SUMO traffic demand from fringe/source-edge inflow rates plus explicit per-junction turning-movement ratios (e.g. 25% left / 55% through / 20% right), using `jtrrouter` — with no origin-destination matrix and no candidate route pool. This is SimSkill's only demand paradigm driven by turning-movement counts, the standard field-data product real traffic engineers collect at intersections; every other routing skill (`convert-od-matrix-to-trips`, `generate-random-trips`, `calibrate-demand-with-routesampler`) needs either OD information or a pre-existing route pool that `jtrrouter` doesn't require.

## Flow definitions (fringe-only)

`jtrrouter`'s input is a flow file declaring inflow rate at each **source/fringe edge only** — no destination is specified, since `jtrrouter` determines each vehicle's path turn-by-turn as it's routed:

```xml
<routes>
    <flow id="f_N" from="in_N" begin="0" end="3600" number="600"/>
    <flow id="f_E" from="in_E" begin="0" end="3600" number="600"/>
</routes>
```

## The `<turns>` turning-ratio specification

Per-interval, per-`fromEdge`, an `<edgeRelation>` element gives the probability of continuing onto each possible `toEdge`. Probabilities for a given `fromEdge` within one interval should sum to 1.0 (jtrrouter normalizes if they don't):

```xml
<turns>
    <interval begin="0" end="3600">
        <edgeRelation from="in_N" to="out_E" probability="0.25"/>  <!-- left -->
        <edgeRelation from="in_N" to="out_S" probability="0.55"/>  <!-- through -->
        <edgeRelation from="in_N" to="out_W" probability="0.20"/>  <!-- right -->
    </interval>
</turns>
```

Determine which `to` edge is "left"/"through"/"right" from the compiled network's actual `<connection dir="l"/"s"/"r"/"t">` attributes at the junction — don't infer it from edge names or geometry assumptions alone; verify against the compiled net.

## Running jtrrouter

```bash
jtrrouter -n net.xml -r flows.xml -t turns.xml \
    --sink-edges out_N,out_E,out_S,out_W --seed 42 -o routes.rou.xml --randomize-flows
```

`--sink-edges` lists the network's exit edges so `jtrrouter` knows where a route may legally terminate. `--randomize-flows` avoids overly regular inter-vehicle spacing. Check `jtrrouter --help` for the current version's exact flag set before assuming names — flags like `--turn-ratio-files`/`-t` and sink-edge handling can be version-dependent.

## Verifying the realized ratios (don't trust a successful run alone)

**A `jtrrouter` run completing without error says nothing about whether the realized turn split actually matches the specification** — verify it by reclassifying every generated route's actual edge-to-edge transition at the junction, independently, from two sources:

1. **The router's own output** (`routes.rou.xml`) — confirms `jtrrouter` itself assigned movements per the specification.
2. **The simulation's executed routes** (`vehroute-output`) — confirms nothing downstream (insertion failures, rerouting) distorted the distribution before vehicles actually completed their trips.

```bash
python scripts/verify_turn_ratios.py --turns turns.xml \
    --routes routes.rou.xml --routes vehroutes.out.xml --out comparison.txt
```

This reads the specification directly from the `<turns>` file (not hardcoded), classifies every vehicle's route by its first from/to edge pair that matches a specified relation, and reports realized fraction vs. specified probability per movement, with the maximum absolute deviation.

## Interpreting a single-run deviation: check multiple seeds before concluding bias

A single seeded run's realized split can deviate from the specification by a few percentage points purely from finite-sample stochastic assignment — this is not evidence of a systematic tool bug. **Run several seeds and check whether the deviation's sign is consistent (systematic bias) or scattered around the target (sampling noise)**: in one verified case, a single run showed a 2.25-percentage-point deviation, but a 4-seed sweep's mean converged to within 0.05 points of the 25% specification, confirming the single-run gap was noise, not bias.

## Fringe insertion loss doesn't necessarily skew turn proportions

At high enough demand relative to a junction's capacity, some fraction of fringe-inserted vehicles may never actually enter the simulation (SUMO's insertion queue can starve a source edge under sustained oversaturation). This reduces total throughput but — because the insertion queue is movement-agnostic FIFO — does not by itself skew the surviving vehicles' turn-ratio proportions relative to the full generated set. Verify this explicitly (compare the turn split of inserted vs. all-generated vehicles) rather than assuming insertion loss is turn-neutral; if a particular approach or movement is disproportionately affected, the loss is not neutral and should be reported as a real confound.

## Gotchas

- **XML comments cannot contain a literal double-hyphen (`--`) anywhere in their body** — spelling out a command-line flag like `--turn-ratio-files` inside an XML comment breaks parsing; escape or reword such comments in any `.xml`/`.sumocfg` file.
- **Determine left/through/right from the compiled network's actual connection directions**, not from edge-name or geometry assumptions — a network with an unusual layout can have "left" and "right" reversed relative to a naive compass-based guess.
- **A completed `jtrrouter` run is not proof of a correct turn split** — always reclassify and verify against the specification from real route data.

## Related

- `calibrate-demand-with-routesampler` — SimSkill's other count-calibration demand skill; contrast `routeSampler`'s need for a pre-existing candidate route pool against `jtrrouter`'s pool-free, turn-by-turn generation.
- `convert-od-matrix-to-trips` (`od2trips`), `generate-random-trips` — SimSkill's OD-based and random-sampling demand skills, the other two paradigms `jtrrouter` doesn't need.
- `create-single-intersection`, `create-grid-network` — for the network `jtrrouter` routes demand across.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for turn-ratio verification.
- [[jtrrouter]] — the underlying `<turns>` XML schema, `jtrrouter`'s command-line conventions, and the verified specified-vs-realized-ratio findings.
