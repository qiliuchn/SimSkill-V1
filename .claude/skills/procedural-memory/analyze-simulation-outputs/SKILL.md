---
name: analyze-simulation-outputs
description: Use this skill when the user wants to compare SUMO simulation runs or scenarios (e.g. baseline vs signal-optimized, or 3+ alternative demand/network configurations) by their performance metrics — travel time, waiting time, time loss, throughput, mean speed, teleports — parsed from tripinfo/summary/edgeData XML outputs, and wants a comparison table and/or plots. This is the post-processing/analysis step that comes *after* `run-simulation` has produced output files, not a way to run SUMO itself. Trigger on mentions of comparing simulation runs, before/after signal optimization results, tripinfo/summary/edgeData analysis, network performance metrics, or "did this optimization actually help."
user-invocable: true
disable-model-invocation: false
---

# Analyze Simulation Outputs

Parses one or more SUMO runs' `tripinfo`/`summary`(/`edgeData`) XML outputs into network-level performance metrics, writes a comparison table, and saves a bar chart plus a time-series chart. Use it any time a task asks "is A better than B" (or "how do A, B, C compare") in terms of simulated traffic performance — this is what turns raw SUMO output files into an actual answer.

This assumes the runs already exist (produced via `run-simulation`, with `--tripinfo-output` and `--summary-output` configured, and optionally an `edgeData` additional file) — this skill only reads and compares their output, it does not run SUMO.

## Quick usage

Explicit files per run — works for any number of runs, `tripinfo` and `summary` required, `edgedata` optional:

```bash
python scripts/analyze_outputs.py \
  --run baseline=tripinfo_baseline.xml,summary_baseline.xml \
  --run optimized=tripinfo_optimized.xml,summary_optimized.xml,edgedata_optimized.xml \
  --out-dir comparison/
```

Or point at a directory per run and let it find conventionally-named files (anything matching `tripinfo*.xml` / `summary*.xml` / `edgedata*.xml` inside it):

```bash
python scripts/analyze_outputs.py \
  --run-dir baseline=runs/baseline \
  --run-dir optimized=runs/optimized \
  --out-dir comparison/
```

`--run` and `--run-dir` can be mixed and repeated for 3+ runs. Add `--xml2csv` to also convert every XML output to CSV via `$SUMO_HOME/tools/xml/xml2csv.py` (useful for spreadsheet inspection; not needed for the metrics or plots, which parse the XML directly). Add `--no-plots` for a table-only comparison.

## What it computes

Per run, from `tripinfo`: completed trips (throughput), mean/total travel time, mean waiting time, mean time loss, mean trip speed (`routeLength / duration`). From `summary`: total teleports (read from the last step, since the field is already a cumulative count — see Gotchas).

**Comparison table** (`comparison_table.csv`, printed as markdown too): with exactly 2 runs, includes a `% change` and `improved?` column (throughput and speed are "higher is better", everything else "lower is better"). With 3+ runs, it reports raw values per run — a % change column would require picking one run as the reference, which this script deliberately leaves to you rather than assuming.

**Plots**: a grouped bar chart of the four key latency/speed metrics across runs (`metrics_bar_comparison.png`), and a two-panel time-series chart of running-vehicle-count and mean-network-speed over simulation time, one line per run, from the `summary` output (`timeseries_comparison.png`).

## Gotchas

- **`summary` output's `teleports` attribute is a cumulative running count, not a per-step delta.** Confirmed directly: a run with 5 real teleports shows `teleports="0"` for many steps then climbs 1→2→3→4→5 and *stays* at 5 for every remaining step — it never resets after a teleport. Read the **last** step's value (or `max()` across steps); summing across steps was a bug in an earlier version of this script and would wildly over-count on any run with real teleports (harmless only when the true count is 0, which is common but not universal).
- **`meanSpeed=-1` in `summary` output is a sentinel, not a real value.** SUMO writes it whenever zero vehicles are running that step (a network with no traffic has no defined mean speed). The script already filters these points out of the time-series speed plot — if you parse `summary` XML yourself elsewhere, do the same, or a normal drain-out period will show up as a misleading dip to -1.
- **`edgeData`'s `file` output path is relative to the additional file's own directory**, not to SUMO's working directory at run time — verified directly against SUMO 1.27.1 by running with cwd and the additional file's directory set to two different locations; the output landed next to the additional file. *(Correction: an earlier version of this skill claimed the opposite, which caused a real bug — parallel batch replications sharing one additional file silently overwrote each other's edgeData output, corrupting a multi-replication study before it was caught.)* If an `edgeData` file seems to be missing after a run, check next to the additional file that defines it, not the invoking cwd — and give every parallel/batch run its own copy of the additional file (or a run-specific absolute `file` path) if outputs must not collide, the same pattern already used for E1/E2 detector files elsewhere in memory (e.g. `implement-alinea-ramp-metering`).
- **Empty `tripinfo` (zero completed trips) raises an error rather than silently reporting zeroed-out metrics** — this usually means gridlock, a routing failure, or a config mistake in that run, which is worth fixing before comparing it to anything.
- **matplotlib may not be installed** in the environment; if so, install with `pip3 install matplotlib --break-system-packages` (needed unless `--no-plots` is passed).
- Locating `xml2csv.py` follows the same `$SUMO_HOME/tools/...` convention as `tlsCycleAdaptation.py`/`randomTrips.py` (see `optimize-signals-by-tlscycleadaptation`, `generate-random-trips`) — it lives at `$SUMO_HOME/tools/xml/xml2csv.py`, not next to the `sumo` binary.

## Related

- Feed it output from `run-simulation` (configure `--tripinfo-output`/`--summary-output`, plus an `edgeData` additional file if you want edge-level cross-checks).
- Common comparison pattern: run the same demand once with a baseline signal plan and once with a plan from `optimize-signals-by-tlscycleadaptation` (or `optimize-signals-by-tlscoordinator` / `optimize-signals-by-qlearning`), then compare the two runs with this skill to quantify the improvement.
- See [[sumo-output-files]] for the underlying tripinfo/summary/edgeData XML schemas this skill parses.
- `quantify-sumo-run-to-run-variability` — before trusting a 2-run comparison from this skill as conclusive, check whether the demand level is far enough from the network's capacity knee that a single-run difference is likely to exceed run-to-run noise; that skill covers how to determine this and how many replications a given effect size actually needs.
