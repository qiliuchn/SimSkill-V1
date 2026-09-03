---
name: generate-activity-based-demand
description: Use this skill when the user wants to generate population/activity-driven travel demand in SUMO — realistic time-of-day demand with a bimodal morning/evening commute peak, derived from a population, household car-ownership rate, and work/school locations and hours, rather than a temporally flat or externally-imposed demand set. Covers SUMO's activitygen tool, authoring its <city> statistics-file schema (which has no shipped XSD), classifying network edges into residential/work/school/gate roles, running activitygen -> duarouter, and verifying the resulting departure-time distribution against a flat randomTrips control. Trigger on mentions of activitygen, activity-based demand, population-driven demand, or rush-hour/peak-hour demand generation.
related_skills:
  - create-grid-network
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[activitygen]]"
---

# Generate Activity-Based Demand

Generates travel demand endogenously from a synthetic population's daily activity schedule — commuting to work or school and back — using SUMO's `activitygen` tool, rather than a flat or externally-imposed demand set. This is SimSkill's only demand paradigm with genuine time-of-day structure: every other demand skill (`generate-random-trips`, `convert-od-matrix-to-trips`, `calibrate-demand-with-routesampler`) produces demand that's either temporally flat or set by an external count/OD file, not derived from population/schedule parameters.

## Locating and verifying activitygen

`activitygen` is a compiled binary shipped alongside `sumo`/`netconvert` (check `$SUMO_HOME/../bin/activitygen` or `which activitygen`), not a Python tool in `$SUMO_HOME/tools`. Confirm it's present and check its actual `--help` output before assuming flag names.

**No XSD ships for `activitygen`'s `<city>` input format** — `$SUMO_HOME/data/xsd/statistic_file.xsd`, despite the similar name, is the *simulation-output* statistics schema (`<performance>`, `<vehicles>`, `<safety>`, `<persons>` elements), unrelated to `activitygen`'s input. Derive the `<city>` schema from SUMO's documentation (Demand/Activity-based_Demand_Generation) and confirm it empirically with a clean run — don't assume the shipped XSD applies.

## Classifying network edges for the statistics file

The `<city>` file needs edges tagged with roles: residential (`population` weight), work/CBD (`workPosition` weight), schools (with hours/capacity), and city gates (fringe edges carrying incoming/outgoing commuter flow). `scripts/make_city_stats.py` automates this for a `create-grid-network`-style grid (junction ids like `B1C1`): edges whose both endpoints fall inside a configurable central column/row range become work edges, everything else on the grid becomes residential, a couple of residential edges become schools, and fringe/attach edges matching a gate-prefix pattern become city gates.

```bash
python scripts/make_city_stats.py --net grid.net.xml --out city.stat.xml \
    --cbd-cols BCD --cbd-rows 123 --n-schools 2 --n-gates 6 \
    --inhabitants 1000 --households 450 --car-rate 0.60 \
    --work-open "07:30:0.25,08:00:0.55,08:30:0.20" \
    --work-close "16:00:0.20,17:00:0.55,18:00:0.25"
```

Key `<city>` parameters and their effect on the resulting demand shape:
- **`<workHours>` `<opening>`/`<closing>` proportions** — cluster tightly (e.g. all within 60-90 minutes) for a sharp peak, spread out for a broader one. The peak whose contributing hours cluster tighter comes out sharper and taller even at equal total volume.
- **School hours** — schools typically have a single opening/closing time (less spread than work), so if school and work opening times coincide, that peak sharpens further.
- **`departureVariation`** — smooths each activity's departure time into a bell curve around its nominal hour rather than a hard spike; larger values produce broader, more realistic-looking peaks.
- **`uniformRandomTraffic`** — adds a small flat background component on top of the activity-driven peaks, producing nonzero off-peak demand rather than a hard-zero trough.
- **`carRate`** — the fraction of the population that drives at all; scales total generated vehicle volume without affecting temporal shape.

## Running the pipeline

```bash
activitygen --net-file grid.net.xml --stat-file city.stat.xml --output-file trips.rou.xml \
    --begin 0 --end 86400 --duration-d 1 --seed 42
duarouter -n grid.net.xml -r trips.rou.xml -o routes.rou.xml --ignore-errors --repair
```

`--begin`/`--end` bound the simulated period (86400s = one full day); `--duration-d` sets how many days of activity the statistics represent. Route the output with `duarouter` exactly as any other trip file.

## Verifying the demand structure, not just trusting the tool

Build a matched-total-volume flat `randomTrips` demand over the identical horizon as a control, run both through a full-day simulation, and compare departure-time histograms directly from each `.rou.xml`'s `<vehicle depart=...>` — don't just assume `activitygen` "worked" because it ran without error. `scripts/analyze_departures.py` bins both demand sets (default 30-minute bins), computes peak-hour fraction and AM/PM/midday window shares for each, runs a bimodality check on the activity-based set (AM and PM peak hours both ≥2x the hourly mean, with a midday trough below the mean, AM before PM), and produces overlay and side-by-side comparison plots:

```bash
python scripts/analyze_departures.py \
    --activity-rou activitygen_routed.rou.xml --control-rou random_routed.rou.xml \
    --out-dir plots/ --am-window 7,9 --pm-window 16,18 --midday-window 11,14
```

## What a well-configured activitygen run tends to produce

Measured on a 5x5 grid, population 1000, matched-volume flat control: `activitygen`'s busiest hour carried ~27% of the entire day's demand versus ~4% (uniform 1/24) for the flat control — roughly a 6x concentration difference. AM and PM window shares (44% and 29% of daily demand respectively in one run) dwarfed the flat control's proportional ~8%/8% shares, with a genuine midday trough (under 2% of daily demand) that a flat distribution categorically can't produce. The AM peak came out sharper/taller than the PM peak because work-opening times and the schools' single opening time clustered into the same narrow window, while work-closing times were spread wider.

## Scope limit: activitygen is population-*driven*, not population-*resolved*

`activitygen` parameterizes a whole city with scalars — `inhabitants`, `households`,
`carRate`, work/school hours. That is enough to produce a genuine commute peak, which is
what this skill is for, but there is no household object anywhere in the model: no
traveller has an income, and car availability is a global rate rather than a property of
the household a person belongs to.

So if the question is **who** — mode share or travel burden by income or by car
ownership, equity incidence, a policy that bites differently on carless households —
activitygen structurally cannot answer it, and segmenting its output by zone averages
gives a measurably wrong answer (a zone-average estimator assigned a 32.8% car share to
carless households and inverted the sign of a travel-burden gap). Use
`synthesize-population-and-generate-disaggregate-demand` for those questions: it fits
PUMS-style seed microdata to zonal control totals by IPF, integerizes into whole
households, and constrains each person's mode availability by their own household's
vehicles. See [[population-synthesis-and-aggregation-bias]].

Conversely, if the question is network loading, stay here — the same study found a
properly segmented aggregate model reproduces disaggregate link volumes at GEH<5 on 100%
of links, so household synthesis is not worth its cost for that.

## Gotchas

- **No XSD ships for the `<city>` input schema** — don't assume `statistic_file.xsd` (or any XSD found by searching `$SUMO_HOME`) validates `activitygen`'s input; verify field names against documentation and a real successful run.
- **`activitygen` is a compiled binary, not a `$SUMO_HOME/tools` Python script** — locate it via `$SUMO_HOME/../bin/` or `which activitygen`, not by searching `tools/`.
- **A demand set "having structure" needs verification against a flat control**, not a visual glance at one histogram — compute peak-hour fraction, window shares, and coefficient of variation, and compare both sets numerically.

## Related

- `create-grid-network` for the base network this skill's edge classifier expects.
- `generate-random-trips` for building the flat-demand control condition.
- `convert-trips-to-routes` (`duarouter`) for routing `activitygen`'s trip output.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for departure-time-distribution comparison.
- [[activitygen]] — the underlying `<city>` statistics-file schema, parameter-to-profile mapping, and the verified bimodal-vs-flat finding.
