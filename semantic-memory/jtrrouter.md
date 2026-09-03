---
summary: jtrrouter generates SUMO demand from fringe inflow rates plus per-junction turning-movement ratios (a <turns> edgeRelation specification), with no OD matrix or route pool required — verified to reproduce specified turn splits within a few percentage points per run, converging to spec across seeds, with fringe insertion loss confirmed not to skew the realized proportions.
keywords:
  - jtrrouter
  - turning-ratio
  - turning-movement-counts
  - edgeRelation
  - turns-file
  - fringe-flow
created: 2026-07-25T14:50:00
last_updated: 2026-07-25T14:50:00
sources:
  - "[[episodic-memory/2026-07-25_14-30-01/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-25_14-30-01/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/jtrrouter.html
related_pages:
  - "[[routesampler]]"
  - "[[duarouter]]"
  - "[[od2trips]]"
  - "[[random-trips]]"
related_skills:
  - generate-demand-with-jtrrouter
  - calibrate-demand-with-routesampler
  - create-single-intersection
  - convert-trips-to-routes
related_skills_for_graph_view:
  - "[[generate-demand-with-jtrrouter]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[create-single-intersection]]"
  - "[[convert-trips-to-routes]]"
---

# jtrrouter

`jtrrouter` generates SUMO travel demand from fringe/source-edge inflow rates plus explicit per-junction turning-movement ratios — no origin-destination matrix ([[od2trips]]), no random OD sampling ([[random-trips]]), and no candidate route pool matched against target counts ([[routesampler]]). Each vehicle's path is determined turn-by-turn as it's routed, sampled against the specified probability of each possible movement at every junction it passes through. This is the natural fit when turning-movement counts — a standard field-data product collected at real intersections — are available but origin-destination information isn't.

## Flow definitions

Flows declare inflow rate at fringe/source edges only, with no destination:

```xml
<flow id="f_N" from="in_N" begin="0" end="3600" number="600"/>
```

## The `<turns>` schema

Per interval, per `fromEdge`, `<edgeRelation>` elements give the probability of continuing onto each reachable `toEdge`. Probabilities for one `fromEdge` within an interval should sum to 1.0 (jtrrouter normalizes otherwise):

```xml
<turns>
    <interval begin="0" end="3600">
        <edgeRelation from="in_N" to="out_E" probability="0.25"/>
        <edgeRelation from="in_N" to="out_S" probability="0.55"/>
        <edgeRelation from="in_N" to="out_W" probability="0.20"/>
    </interval>
</turns>
```

Which `to` edge corresponds to "left"/"through"/"right" should be determined from the compiled network's actual `<connection dir="l"/"s"/"r"/"t">` attributes at the junction, not inferred from edge naming or geometry assumptions — an unusual layout can invert naive compass-based guesses.

## Command line

```bash
jtrrouter -n net.xml -r flows.xml -t turns.xml \
    --sink-edges out_N,out_E,out_S,out_W --seed 42 -o routes.rou.xml --randomize-flows
```

`--sink-edges` tells `jtrrouter` where a route may legally terminate. Flag names (`-t`/`--turn-ratio-files`, sink-edge handling) should be checked against `jtrrouter --help` for the installed version rather than assumed.

## Verifying realized turn ratios

A `jtrrouter` run completing without error is not proof the realized turn split matches the specification. Verification requires reclassifying every route's actual from/to edge transition at the junction, independently, from **both** the router's own output (`routes.rou.xml`, confirming `jtrrouter` itself assigned movements correctly) and the simulation's executed routes (`vehroute-output`, confirming nothing downstream — insertion failures, rerouting — distorted the distribution before vehicles actually completed their trips). Reading the specification directly from the `<turns>` file (rather than re-encoding it by hand elsewhere) keeps the verification honest against what was actually specified.

## Single-run deviation vs. systematic bias

A single seeded run can show a realized split deviating from specification by a few percentage points purely from finite-sample stochastic assignment — not evidence of a tool bug. Measured on a single 4-way intersection (25/55/20 L/T/R specification, 600 veh/h/approach): one seed showed a maximum deviation of 2.25 percentage points, but a 4-seed sweep's mean converged to within 0.05 points of the specified 25% left-turn fraction, confirming the single-run gap was sampling noise around the correct specification rather than systematic bias. Always check multiple seeds before concluding a deviation reflects a real tool limitation.

## Fringe insertion loss and turn-ratio proportions

At high enough demand relative to a junction's capacity, some fraction of fringe-inserted vehicles may never actually enter the simulation — SUMO's insertion queue can starve an oversaturated source edge. This reduces total throughput but, because the insertion queue is movement-agnostic FIFO, does **not** by itself skew the surviving vehicles' turn-ratio proportions. Measured case: 299 of 2400 generated vehicles (12.5%) were never inserted, entirely from one oversaturated approach (600 veh/h at a single-priority-junction approach), with zero teleports; the executed vehicles' realized turn split still matched the router's own output closely (27.27/54.59/18.13% executed vs. 27.25/54.54/18.21% routed) — confirming the loss was turn-neutral in this case. This should be verified explicitly per scenario, not assumed.

See the `generate-demand-with-jtrrouter` skill for the full build/run/verify workflow and bundled verification script.
