---
summary: routeSampler.py samples and scales routes from a candidate route pool so the resulting route file's edge/turn counts match prescribed target counts, for count-based OD demand calibration.
keywords:
  - routeSampler
  - demand-calibration
  - traffic-counts
  - edgeData-counts
  - turn-counts
created: 2026-07-23T15:16:02
last_updated: 2026-07-23T15:16:02
sources:
  - "[[episodic-memory/2026-07-23_14-58-12/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_14-58-12/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Tools/Turns.html
related_pages:
  - "[[random-trips]]"
  - "[[duarouter]]"
  - "[[sumo-output-files]]"
  - "[[geh-statistic]]"
  - "[[jtrrouter]]"
  - "[[sumo-calibrator]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
related_skills:
  - calibrate-demand-with-routesampler
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
related_skills_for_graph_view:
  - "[[calibrate-demand-with-routesampler]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
---

# routeSampler

`routeSampler.py` (in `$SUMO_HOME/tools/`) generates OD vehicle demand that reproduces a prescribed set of traffic counts, by **sampling and scaling routes from a candidate pool** rather than generating trips from scratch. This is the tool behind count-based demand calibration: given real or synthetic loop-detector counts (and optionally turning-movement counts), it picks which routes from the pool to keep, and how many copies of each, so the output route file's simulated counts match the targets as closely as possible.

It is a distinct approach from [[random-trips]] (purely random OD sampling) and `od2trips` (zone-level OD matrices): those two *generate* demand; routeSampler *selects and scales* demand from an existing candidate pool to fit external count data. [[jtrrouter]] is a third approach again — like routeSampler it can target turning-movement ratios, but it generates routes turn-by-turn from fringe flows rather than needing either a candidate route pool or OD information. [[sumo-calibrator]] is a fourth, orthogonal mechanism: it enforces a target flow *live, during* the simulation at a specific edge, rather than calibrating demand before the run starts.

## Inputs

- **A candidate route pool** (`-r`/`--route-files`): typically built by running `randomTrips.py` to generate a large, diverse trip set spanning the network, then routing it with `duarouter --max-alternatives N` to get a route-alternatives file. The pool must be large and varied enough to contain routes through every movement the target counts require — routeSampler can only select from what already exists in the pool, it cannot synthesize a new route through an uncovered edge combination.
- **Target counts**, one or both of:
  - Edge counts (`-d`/`--edgedata-files`): an edgeData-format XML file (same `<interval>`/`<edge>` shape as SUMO's own edgeData *output* — see [[sumo-output-files]]) giving the target vehicle count per edge over a time window.
  - Turn counts (`-t`/`--turn-files`): target counts for specific turning movements at chosen junctions.

## Basic usage

```bash
python routeSampler.py -r pool.rou.xml -d edge_counts.xml -t turn_counts.xml \
    -o calibrated.rou.xml --mismatch-output mismatch.xml -i 3600 --optimize full
```

Key options: `-i`/`--interval` (aggregation interval, should match the counts file's own interval), `--optimize full` (exact LP-based fit vs. the default greedy sampling — full gave an exact routing-level fit in practice), `--geh-ok` (internal GEH acceptance threshold used while sampling), `-a`/`--attributes` (extra XML attributes injected into output vehicles, e.g. `departSpeed="max"`, to ease insertion), `-s`/`--seed` for reproducibility.

## Output and its own fit report

Besides the calibrated route file (`-o`), `--mismatch-output` writes a report of routeSampler's own **routing/assignment-level** fit — how well the selected+scaled routes match the targets purely as a route-selection problem, independent of how the simulation actually plays out. This can report a perfect fit (GEH = 0 everywhere) even before a single simulation step runs.

**This is not the same as validating against a real simulation run.** Once you actually run `sumo` on the calibrated routes and look at its edgeData output, real dynamics — queuing, spillback, edge/lane capacity limits — can make the realized volumes diverge from routeSampler's own reported fit, particularly on capacity-constrained edges under heavy target volumes. Always compute the [[geh-statistic]] (and mean absolute percentage error) against the *simulated* output as the final validation step, not just against `--mismatch-output`.

## Gotchas

- **Pool coverage is the ceiling.** No routeSampler option can hit a target count on a movement the candidate pool never covered — regenerate the pool (different `randomTrips.py` parameters: lower `--min-distance`, higher `--fringe-factor`, more trips) rather than tuning routeSampler itself.
- **Targets that exceed real network capacity won't be matched by simulation**, even with a perfect routing-level fit — a single-lane edge under gridlock has a hard throughput ceiling. Treat a persistent gap on such an edge as a capacity artifact, not a calibration bug, and avoid chasing it by further tweaking routeSampler options (risks overfitting to a simulation quirk).
- **`--optimize full` requires an LP solver** to be available in the Python environment; without it, fall back to the default greedy sampling.
- Single-shot, not iterative: like `duarouter`, it works from one fixed route pool — for feedback between calibrated demand and its own congestion effects, `duaIterate.py` is the relevant (out-of-scope) tool.

See the `calibrate-demand-with-routesampler` skill for the full pipeline (network → target counts → route pool → routeSampler → simulation → validation) and a CLI wrapper.
