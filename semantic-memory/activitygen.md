---
summary: activitygen is SUMO's population/activity-based demand generator, producing travel demand from a <city> statistics file (population, household car-ownership, work/school locations and hours) that reproduces a genuine bimodal morning/evening commute peak — unlike every other SUMO demand method, which is temporally flat or externally imposed.
keywords:
  - activitygen
  - activity-based-demand
  - population-driven-demand
  - city-statistics-file
  - commute-peak
  - departure-time-distribution
created: 2026-07-25T09:10:00
last_updated: 2026-07-25T09:10:00
sources:
  - "[[episodic-memory/2026-07-24_21-54-28/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-24_21-54-28/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Demand/Activity-based_Demand_Generation.html
related_pages:
  - "[[random-trips]]"
  - "[[duarouter]]"
  - "[[abstract-network-generation]]"
  - "[[sumo-output-files]]"
related_skills:
  - generate-activity-based-demand
  - create-grid-network
  - generate-random-trips
  - convert-trips-to-routes
related_skills_for_graph_view:
  - "[[generate-activity-based-demand]]"
  - "[[create-grid-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
---

# activitygen

`activitygen` generates SUMO travel demand from a synthetic population's daily activity schedule — commuting to work or school and back — rather than a temporally flat distribution ([[random-trips]]) or an externally-supplied count/OD file. It's the only demand mechanism in memory that produces genuine time-of-day structure, specifically the bimodal morning/evening commute peak real urban traffic exhibits.

## Tool location and the missing input schema

`activitygen` is a compiled binary (alongside `sumo`/`netconvert`), not a Python script in `$SUMO_HOME/tools`. **No XSD ships with SUMO for `activitygen`'s `<city>` input format** — `$SUMO_HOME/data/xsd/statistic_file.xsd`, despite its similar name, is actually the *simulation-output* statistics schema (`<performance>`, `<vehicles>`, `<safety>`, `<persons>` elements written by a completed sim run), unrelated to `activitygen`'s input. The `<city>` schema must be derived from SUMO's own documentation (Demand/Activity-based_Demand_Generation) and confirmed empirically via a working run, not assumed from any XSD found by searching the install.

## The `<city>` statistics file

Top-level elements: `<general>` (population totals, car ownership rate, unemployment rate), `<parameters>` (behavioral knobs including `departureVariation` and `uniformRandomTraffic`), `<population>` (age brackets), `<workHours>` (`<opening>`/`<closing>` proportions by time), `<streets>` (per-edge `population`/`workPosition` weights), `<schools>` (per-edge hours/capacity), and `<cityGates>` (fringe edges carrying incoming/outgoing commuter flow).

Parameter-to-temporal-shape mapping (verified empirically, not just documented):
- **`<workHours>` opening/closing proportions clustered tightly in time produce a sharper, taller peak**; spread across a wider window produces a broader, lower one — even at equal total volume. A run with work openings clustered within a single hour (07:30/08:00/08:30) and closings spread across two hours (16:00/17:00/18:00) produced a visibly sharper AM peak than PM peak.
- **School opening/closing times typically have less internal spread than work hours** (often a single time), so a school opening coinciding with the tightest work-opening cluster sharpens that peak further.
- **`departureVariation`** smooths each scheduled activity's departure into a bell curve around its nominal time rather than a hard spike — larger values (e.g. 600 seconds) produce visually realistic peaks rather than delta-function spikes.
- **`uniformRandomTraffic`** adds a small flat background on top of the activity-driven peaks, giving nonzero (rather than hard-zero) off-peak demand.
- **`carRate`** scales total generated vehicle volume without affecting the temporal shape.

## Running the pipeline

```bash
activitygen --net-file grid.net.xml --stat-file city.stat.xml --output-file trips.rou.xml \
    --begin 0 --end 86400 --duration-d 1 --seed 42
duarouter -n grid.net.xml -r trips.rou.xml -o routes.rou.xml --ignore-errors --repair
```

`--duration-d` sets how many days of activity the statistics file represents; `--begin`/`--end` bound the simulated window (86400s = one full day).

## Verifying the demand structure against a flat control

A meaningful demonstration of activity-based demand's value requires a matched-total-volume flat control (e.g. `randomTrips` over the identical horizon), with both sets' departure-time histograms compared numerically — peak-hour fraction of total daily volume, AM/PM/midday window shares, and hourly coefficient of variation — not just a visual impression from one plot.

## Measured finding

On a 5x5 grid, population 1000, matched-volume flat control: `activitygen`'s busiest hour carried ~27% of the entire day's demand versus ~4% (exactly uniform, 1/24) for the flat control — roughly a 6x concentration difference. AM window (07:00-09:00) share was 44% and PM window (16:00-18:00) share was 29% of daily demand for the activity-based set, versus the flat control's proportional ~8%/8%; midday (11:00-14:00) share for the activity-based set was under 2%, a genuine trough a flat distribution categorically cannot produce. Hourly coefficient of variation was 1.63 (activity-based) vs. 0.01 (flat, essentially zero variation as expected of a uniform distribution) — a quantitative, not just visual, confirmation of the bimodal structure.

See the `generate-activity-based-demand` skill for the full edge-classification, statistics-file-authoring, and departure-time-verification workflow with bundled scripts.
