---
name: calibrate-demand-with-routesampler
description: Use this skill when the user wants SUMO traffic demand that reproduces a set of prescribed or observed traffic counts (loop-detector edge counts, turning-movement counts, or OD counts) — rather than purely random demand or a zone-based OD matrix. Covers routeSampler.py, which samples/scales routes from a candidate pool so the resulting route file's counts match target values. Trigger on mentions of routeSampler, count-based demand calibration, matching/reproducing traffic counts, loop-detector calibration, turning-movement counts, GEH statistic for demand validation, or "make simulated volumes match these counts."
related_skills:
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[geh-statistic]]"
  - "[[sumo-output-files]]"
---

# Calibrate Demand with routeSampler.py

Generates OD vehicle demand that reproduces a prescribed set of traffic counts, by sampling and scaling routes from a candidate pool rather than generating trips directly. This is the count-based counterpart to `generate-random-trips` (purely random demand) and `convert-od-matrix-to-trips` (zone-level OD demand) — pick this skill specifically when the goal is "make the simulated traffic match these known/target counts," e.g. calibrating against real loop-detector data or crafting a scenario with a specific directional bias. Reference: https://sumo.dlr.de/docs/Demand/Routes_for_Roundabouts_and_Roundabout_Handling.html is unrelated — the authoritative source is `python routeSampler.py --help`, since it's simplest to check the flags directly rather than hunting for the right doc page.

## Locating the tool

`routeSampler.py` lives at `$SUMO_HOME/tools/routeSampler.py` — same location family as `randomTrips.py`, **not** next to the `sumo`/`netgenerate` binaries.

```bash
echo $SUMO_HOME
ls "$SUMO_HOME/tools/routeSampler.py"
```

`scripts/route_sampler.py` resolves this automatically and fails with a clear message if `SUMO_HOME` isn't set or the tool isn't found there.

## The workflow

routeSampler doesn't generate trips itself — it selects and scales routes from a **candidate pool** you build first, so the overall pipeline has three stages:

1. **Build a network** (`create-grid-network`, `create-spider-network`, `load-osm-network`, etc.) — no different from any other demand workflow.
2. **Define target counts** as an edgeData-format XML file (for per-edge counts) and/or a turn-count file (for per-movement counts at specific junctions), covering the time window you want to calibrate against. See [[sumo-output-files]] for the edgeData XML schema — the counts file routeSampler reads has the same `<interval>`/`<edge>` shape as a simulation's own edgeData *output*, just hand-authored (or from real detector data) instead.
3. **Build a large candidate route pool**: use `generate-random-trips` (`randomTrips.py`) to sample many trips spanning the network, then `convert-trips-to-routes` (`duarouter --max-alternatives N`) to turn them into a route-alternatives file. The pool needs to be large and diverse enough to contain routes through every movement the target counts require — routeSampler can only select from what's there, it cannot invent a route through an edge combination the pool never covered.
4. **Run routeSampler** (this skill) to select/scale routes from the pool so the output route file's counts match the targets.
5. **Run the simulation** (`run-simulation`) with the calibrated routes and an edgeData additional file over the same interval.
6. **Validate**: compare the *simulated* edgeData output against the original targets using the [[geh-statistic]] and MAPE — see the Validation section below for why this is a distinct step from routeSampler's own fit report.

## Quick usage

```bash
# Basic: sample pool.rou.xml against edge counts only
python scripts/route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml

# Edge + turn counts, matching aggregation interval, exact LP-based fit, mismatch report
python scripts/route_sampler.py -r pool.rou.xml -d edge_counts.xml -t turn_counts.xml \
    -o calibrated.rou.xml --mismatch-output mismatch.xml -i 3600 --optimize full

# Reproducible run, GEH-based internal acceptance threshold, easier insertion
python scripts/route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml \
    --geh-ok 5 --seed 42 --attributes 'departSpeed="max" departLane="best"'

# Passthrough for anything not explicitly wrapped
python scripts/route_sampler.py -r pool.rou.xml -d edge_counts.xml -o calibrated.rou.xml \
    --extra "--min-count 2" --extra "--threads 4"
```

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-r, --route-files` | input candidate route pool (comma-separated); typically `randomTrips.py` + `duarouter --max-alternatives` output | — (required) |
| `-d, --edgedata-files` | input edgeData-format file(s) with target edge counts | — |
| `-t, --turn-files` | input turn-count file(s) | — |
| `-o, --output-file` | output calibrated route file | `calibrated.rou.xml` |
| `--mismatch-output <FILE>` | write per-location overflow/underflow + GEH info to this file — **routing-level fit only, see Validation below** | — |
| `-b, --begin` / `-e, --end` | custom time window (s or `H:M:S`) | — |
| `-i, --interval` | aggregation interval — **should match the counts file's own `<interval>` window**, or routeSampler will aggregate the counts differently than they were defined | — |
| `--optimize <full\|INT>` | `full` runs an exact LP-based fit (needs a solver like HiGHS available); an integer sets a boundary for faster greedy sampling with local refinement instead | greedy sampling |
| `--geh-ok <FLOAT>` | GEH threshold routeSampler uses *internally* to judge a location "good enough" while sampling | — |
| `--min-count <INT>` | minimum number of counting locations a route must visit to be eligible | — |
| `--minimize-vehicles <FLOAT>` | optimization factor in `[0,1)` preferring routes that pass multiple counting locations (fewer, more efficient vehicles) | — |
| `--total-count <VALUE>` | target total vehicle count (single value split proportionally across intervals, a per-interval list, or `input` to preserve the pool's own counts) | — |
| `-s, --seed` | random seed | — |
| `--weighted` | sample routes according to their pool probability/count rather than uniformly | off |
| `-a, --attributes` | extra XML attributes injected into every output vehicle, e.g. `'departSpeed="max" departLane="best"'` (helps insertion succeed under high demand) | — |
| `--prefix` | id prefix for output vehicles | — |
| `--extra <ARG>` | any other raw `routeSampler.py` flag, can be repeated | — |
| `--dry-run` | print the command without running it | off |

## Validation: routing-level fit ≠ simulated fit

routeSampler's `--mismatch-output` reports how well the *selected routes* match the targets **at the assignment/routing level** — it can report a perfect fit (GEH = 0 everywhere) purely from route selection math, with no notion of real traffic dynamics. That is not the same as how well the *actual simulated* volumes match once you run `sumo` on the calibrated routes: queuing, spillback, and capacity limits at bottleneck edges can cause the realized simulation output to diverge meaningfully from routeSampler's own reported fit, especially on low-capacity (e.g. single-lane) edges under heavy target volumes.

**Always validate against the real simulation output, not just `--mismatch-output`:**
1. Run the simulation with an edgeData additional file over the same interval as the counts (see `run-simulation`, [[sumo-output-files]]).
2. Parse the resulting edgeData `entered`/`arrived` counts per edge and compare against the original targets.
3. Compute [[geh-statistic]] and mean absolute percentage error per edge and overall — this is the metric transportation engineers actually use to judge whether a calibration is acceptable (commonly GEH < 5 per location as a soft guideline, not a hard requirement).

## Gotchas

- **The candidate pool bounds what's achievable.** If the pool has no route through a movement a target count requires, no `routeSampler` option can manufacture one — fix this by regenerating the pool with different `randomTrips.py` parameters (lower `--min-distance`, higher `--fringe-factor`, more trips), not by tuning `routeSampler` flags.
- **Target counts that exceed real network capacity won't be matched by the simulation even with a perfect routing-level fit.** A single-lane edge under gridlock has a hard throughput ceiling; if a target count exceeds it, the mismatch is a capacity artifact, not a calibration failure — moderate target magnitudes to something the network can plausibly sustain, or accept and report the localized shortfall honestly rather than chasing it by further tweaking `routeSampler` options (which risks overfitting to a simulation quirk rather than genuinely improving the demand estimate).
- **`--optimize full` needs an LP solver available** in the Python environment (e.g. via the `PuLP`/`scipy`/`HiGHS` stack `routeSampler.py` depends on for that mode) — if it's missing, fall back to the default greedy sampling (omit `--optimize`, or pass an integer boundary) rather than a hard failure going unnoticed.
- **`-i`/`--interval` should match the counts file's own aggregation window.** A mismatch between the counts file's `<interval>` and the `-i` passed to `routeSampler` causes it to aggregate/interpret the targets differently than intended.
- **This is single-shot, not iterative traffic assignment.** Like `duarouter`, it works from a fixed route pool computed once — it doesn't re-route based on the calibrated demand's own congestion effects. For that kind of feedback loop, `duaIterate.py` (out of scope here) would be the tool.

## Related

- `generate-random-trips` + `convert-trips-to-routes` (with `--max-alternatives`) build the candidate route pool this skill samples from.
- `run-simulation` runs the calibrated route file and produces the edgeData output needed for validation.
- `analyze-simulation-outputs` is for comparing whole simulation runs (baseline vs. optimized); it's not built for per-edge count validation against external targets — write a small script computing GEH/MAPE directly from the edgeData output instead (see [[geh-statistic]]).
- [[sumo-output-files]] documents the edgeData XML schema shared by both the counts input and the simulation's own output.
