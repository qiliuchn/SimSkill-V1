---
summary: SUMO ships Python plotting tools — plot_trajectories.py (tools root) for time-space/speed diagrams from FCD output, and plot_summary.py/plotXMLAttributes.py (tools/visualization/) for time-series charts from summary or other XML output; all non-spatial, contrasted with plot_net_dump.py's spatial network-geometry heatmap (see [[spatial-congestion-heatmap-with-plot-net-dump]]).
keywords:
  - plot_trajectories
  - plot_summary
  - plotXMLAttributes
  - FCD-output
  - time-space-diagram
created: 2026-07-23T19:50:37
last_updated: 2026-07-27T21:05:19
sources:
  - "[[episodic-memory/2026-07-23_19-32-03/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_19-32-03/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[sumo-output-files]]"
  - "[[sumo-command-line]]"
  - "[[tlscoordinator]]"
  - "[[spatial-congestion-heatmap-with-plot-net-dump]]"
related_skills:
  - visualize-trajectories-and-timeseries
  - run-simulation
  - analyze-simulation-outputs
  - optimize-signals-by-tlscoordinator
related_skills_for_graph_view:
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[optimize-signals-by-tlscoordinator]]"
---

# SUMO Plotting Tools

SUMO ships several Python plotting utilities that turn simulation output directly into images — all non-spatial (time-series or time-space-trajectory), contrasted with `plot_net_dump.py`'s spatial network-geometry heatmap (see [[spatial-congestion-heatmap-with-plot-net-dump]]). Every other post-processing skill (`analyze-simulation-outputs`, and the custom comparison scripts bundled with the emissions/SSM/ramp-metering skills) produces numeric tables, not plots.

## Tool locations — not all in the same directory

- **`plot_trajectories.py`** — `$SUMO_HOME/tools/` (the tools root).
- **`plot_summary.py`**, **`plotXMLAttributes.py`** — `$SUMO_HOME/tools/visualization/` (a subdirectory).

Verified directly rather than assumed — check both locations before concluding a plotting tool isn't shipped with a given SUMO install.

## `plot_trajectories.py`: trajectory / time-space diagrams from FCD output

Reads `--fcd-output` XML (one `<timestep>` per simulation step, containing `<vehicle>` elements with position/speed attributes) and plots one line per vehicle.

```bash
python plot_trajectories.py fcd.xml -t td --filter-route "e1,e2,e3" -o timespace.png
```

- **`-t`/`--trajectory-type`**: two letters from `[t, s, d, a, i, x, y, k, g]` (Time, Speed, Distance, Acceleration, Angle, x-Position, y-Position, Kilometrage, leaderGap) selecting the x/y axes. **The default is `ds` (Distance vs. Speed) — not a time-space diagram.** Use `td`/`dt` explicitly for time-space.
- **`--filter-route`/`--filter-edges`/`--filter-ids`**: restrict which vehicles/edges are plotted — essential for isolating a specific movement (e.g. one mainline corridor) out of a network with cross traffic; without filtering, unrelated vehicles clutter the diagram into illegibility.
- **`--xlim`/`--ylim`**, **`--xticks-file`/`--yticks-file`**: zoom to a representative time/distance window and label specific positions (e.g. intersection locations along a corridor).
- **`-o`/`--output`**: accepts a comma-separated list to write multiple files from one invocation.

## `plot_summary.py`: time-series from `summary.xml`

```bash
python visualization/plot_summary.py -i run1/summary.xml,run2/summary.xml -m meanSpeed -o meanspeed.png
```

`-i` takes comma-separated input files — multiple runs overlay naturally on one chart, the direct way to visually compare scenarios. `-m`/`--measures` selects the `summary.xml` attribute to plot (`running`, `meanSpeed`, etc. — see [[sumo-output-files]]). **`meanSpeed=-1` is a "no vehicles running" sentinel, not a real value** — the same gotcha `analyze-simulation-outputs` already documents for hand-parsing `summary.xml` — use `--ylim` to keep it from skewing the plotted scale.

## `plotXMLAttributes.py`: general-purpose attribute plotting

The more flexible fallback when neither of the above tools' specific assumptions fit — it can plot arbitrary attribute pairs from any XML output file, not just FCD or `summary.xml`.

## Overlaying signal state on a trajectory diagram (custom technique — not built into the tools)

None of SUMO's shipped plotting tools draw traffic-signal state on a trajectory plot. For a **straight corridor** (where a vehicle's FCD x-coordinate, or y for a north-south corridor, directly equals its distance along the corridor), this is straightforward to add:

1. Extract exact green/red windows per intersection via a short TraCI session — read `traci.trafficlight.getRedYellowGreenState(tls_id)` every step and record transitions of the tracked movement's controlled-link-index character. A few cycles of a static program is enough (the timing repeats).
2. Parse the FCD XML directly and draw green/red horizontal bars at each intersection's known distance, with vehicle trajectory lines overlaid on the same axes.

The resulting diagram is far more legible than raw trajectories alone for judging signal coordination: an **uncoordinated** plan shows green bars in identical vertical columns at every intersection (a vehicle riding one green predictably hits red at the next), while a **coordinated (green-wave)** plan shows the bars in a diagonal staircase that trajectories visibly thread through. See `visualize-trajectories-and-timeseries` for the bundled scripts implementing this.

## Pairing a plot with a numeric cross-check

A visual difference between two scenarios should be cross-checked against a numeric metric from the same runs (e.g. mean travel/waiting time from `tripinfo.xml`). In one verified green-wave comparison, the visual (diagonal band vs. sawtooth) and the numeric check (travel time -5.7%, **waiting time -69%**) told a consistent story — and the waiting-time collapse was actually the more decisive signature than the travel-time change, since a short signal cycle can cap how much raw travel time a green wave saves even while it eliminates most full stops. Don't rely on the plot alone to establish that an effect is real.

See the `visualize-trajectories-and-timeseries` skill for the full workflow and bundled scripts.
