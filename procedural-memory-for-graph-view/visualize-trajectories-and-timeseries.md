---
name: visualize-trajectories-and-timeseries
description: Use this skill when the user wants an actual PLOT or IMAGE from SUMO simulation output — a time-space (trajectory) diagram showing vehicle position over time, or a time-series chart of a summary metric (running vehicles, mean speed, etc.) — rather than a numeric table. Covers SUMO's shipped Python plotting tools (plot_trajectories.py, plot_summary.py, plotXMLAttributes.py), FCD output, and overlaying signal state on a trajectory plot. Trigger on mentions of time-space diagram, trajectory plot, green wave visualization, plot_trajectories, plot_summary, or "show me a chart/graph of" simulation behavior.
related_skills:
  - visualize-network-congestion-heatmap
  - publish-georeferenced-and-animated-results
  - run-simulation
  - optimize-signals-by-tlscoordinator
  - optimize-signals-by-tlscycleadaptation
  - analyze-simulation-outputs
  - implement-maxpressure-traci-controller
  - validate-kinematic-wave-theory-across-car-following-models
related_skills_for_graph_view:
  - "[[visualize-network-congestion-heatmap]]"
  - "[[publish-georeferenced-and-animated-results]]"
  - "[[run-simulation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
related_pages:
  - "[[sumo-plotting-tools]]"
---

# Visualize Trajectories and Time-Series

Produces actual plots from SUMO output — time-series and time-space-trajectory charts, as opposed to every other post-processing skill in memory (`analyze-simulation-outputs`, the emissions/SSM/ramp-metering comparison scripts), which all turn XML into numeric tables rather than images. This skill covers SUMO's own shipped Python plotting tools plus a custom overlay technique for showing signal state alongside vehicle trajectories. `visualize-network-congestion-heatmap` is this skill's spatial complement — it colors the network's own geometry rather than plotting time-series/trajectory data.

## Locating the tools — they are NOT all in the same directory

- `plot_trajectories.py` lives directly in `$SUMO_HOME/tools/` (the tools root).
- `plot_summary.py` and `plotXMLAttributes.py` live in `$SUMO_HOME/tools/visualization/` (a subdirectory) — verified directly; don't assume every plotting tool shares one location.

```bash
ls "$SUMO_HOME/tools/plot_trajectories.py"
ls "$SUMO_HOME/tools/visualization/plot_summary.py" "$SUMO_HOME/tools/visualization/plotXMLAttributes.py"
```

## Time-space (trajectory) diagrams from FCD output

Enable floating car data when running the simulation (`--fcd-output fcd.xml`, alongside whatever other outputs are needed — see `run-simulation`), then:

```bash
python "$SUMO_HOME/tools/plot_trajectories.py" fcd.xml \
    -t td --filter-route "edge1,edge2,edge3,...,edgeN" \
    --xlabel "Simulation time (s)" --ylabel "Distance along corridor (m)" \
    --title "Vehicle trajectories" -o timespace.png
```

- **`-t`/`--trajectory-type` takes two letters selecting the x/y axes** from `[t, s, d, a, i, x, y, k, g]` (Time, Speed, Distance, Acceleration, Angle, x-Position, y-Position, Kilometrage, leaderGap) — **the default is `ds` (Distance vs. Speed), not a time-space diagram.** Use `-t td` (or `dt`, depending on which axis should be which) for an actual time-space plot. Verify via `--help` rather than assuming the default matches what's wanted.
- **`--filter-route`/`--filter-edges`/`--filter-ids`** restrict which vehicles/edges get plotted — essential for isolating one movement (e.g. a mainline through corridor) out of a network with cross traffic, or the diagram becomes an unreadable tangle.
- `--xlim`/`--ylim` zoom to a representative window; `--yticks-file`/`--xticks-file` can label specific positions (e.g. intersection locations) on an axis.
- `-o`/`--output` accepts a comma-separated list to write multiple output files from one invocation.

## Overlaying signal state on a trajectory plot (custom, not built into plot_trajectories.py)

`plot_trajectories.py` doesn't have built-in support for drawing traffic-signal state alongside trajectories — this needs a custom overlay, but it's straightforward for a **straight corridor**, where a vehicle's FCD x-coordinate (or y, if the corridor runs north-south) directly equals its distance along the corridor:

1. **Extract exact green/red windows per intersection via TraCI** (`scripts/extract_green_windows.py`): run a short simulation, read `traci.trafficlight.getRedYellowGreenState(tls_id)` every step, and record start/end times whenever the tracked movement's controlled-link-index character transitions to/from green. A few cycles of a static program is enough — the timing repeats.
2. **Draw signal bars at each intersection's known distance and overlay trajectories** (`scripts/plot_annotated_timespace.py`): parse the FCD XML directly (`xml.etree.ElementTree`, one `<timestep>` containing `<vehicle>` elements with `x`/`y`), filter to the movement of interest (e.g. by an id prefix), and plot green/red horizontal bars at each intersection's y-position alongside the vehicle trajectory lines.

This produces a far more legible diagram than raw trajectories alone: an **uncoordinated** signal plan shows green bars in identical vertical columns across every intersection (so a vehicle riding one green predictably hits red at the next), while a **coordinated (green-wave)** plan shows the bars in a diagonal staircase that trajectories visibly thread through — this pattern is the single most convincing visual evidence that coordination is actually working, more so than the base trajectory plot alone.

## Summary time-series plots (second plotting pathway)

```bash
python "$SUMO_HOME/tools/visualization/plot_summary.py" -i run1/summary.xml,run2/summary.xml \
    -m meanSpeed --ylim 5,14 --xlabel "Time (s)" --ylabel "Mean speed (m/s)" \
    --title "Mean network speed" -o summary_meanspeed.png
```

- `-i`/comma-separated input files lets multiple runs overlay on one chart — the natural way to visually compare scenarios (e.g. baseline vs. optimized).
- `-m`/`--measures` selects which `summary.xml` attribute to plot (`running`, `meanSpeed`, etc. — see [[sumo-output-files]] for the full attribute list).
- **`meanSpeed=-1` is a sentinel for "no vehicles running," not a real value** (see `analyze-simulation-outputs`'s own documented gotcha) — use `--ylim` to keep it from dominating the plot's scale, or filter it out before plotting if doing so manually.
- `plotXMLAttributes.py` (same directory) is the more general-purpose alternative — it can plot arbitrary attribute pairs from any XML output (not just `summary.xml`), useful when neither `plot_trajectories.py` nor `plot_summary.py`'s specific assumptions fit the data.

## Cross-checking a visual difference is real

A plot showing a visual difference between two scenarios should always be paired with a numeric cross-check from the same runs — e.g. mean corridor travel time or waiting time from `tripinfo.xml` (see `analyze-simulation-outputs`). In a verified green-wave comparison, the visual (diagonal band vs. sawtooth) and the numeric cross-check (travel time -5.7%, waiting time -69%) told a consistent story — the waiting-time collapse was actually the more decisive quantitative signature than the modest travel-time change, since a short signal cycle can limit how much raw travel time a green wave can save even when it eliminates most stops.

## FCD sampling period: choose it by measurement, not habit

`--device.fcd.period` sets how often FCD records a vehicle, and it is the single parameter
that decides whether a trajectory plot or animation built from that FCD is *true*. Measured
by comparing shockwave speeds read off the output against ground truth from a 0.1 s FCD
(= the simulation step) — see [[georeferencing-sumo-output-and-cartographic-fidelity]]:

| period | FCD MB | stopping-wave err | discharge-wave err | cycles resolvable | wave travel/frame |
|---|---|---|---|---|---|
| 0.5 s | 45.13 | −1.7 % | +1.5 % | 13/13 | 0.2 veh |
| **1 s** | **22.56** | −2.5 % | **+2.4 %** | 12/13 | 0.5 veh |
| 2 s | 11.28 | −0.6 % | −6.0 % | 10/13 | 1.0 veh |
| 5 s | 4.51 | −8.7 % | **+18.7 %** | 9/13 | 1.9 veh |
| 10 s | 2.25 | +13.1 % | +5.7 % | **4/13** | **4.4 veh** |

**≤1 s faithful, 2 s the ceiling, 5 s misleading, 10 s broken.** Judge aliasing by
*resolvability* and per-frame travel rather than by an averaged error — the 10 s row's median
discharge error looks fine at +5.7 %, but the wave is unmeasurable in 69 % of green onsets and
the front jumps 4.4 vehicle lengths per frame.

**The asymmetry to remember**: a slow queue-envelope wave (−0.176 m/s) is essentially immune to
sampling period, while fast stop/discharge waves (−1.55 / −3.46 m/s) alias badly. So a period
that looks fine on a congestion map or a coarse time-series is far too coarse for a trajectory
plot or animation of the same run.

Restrict output with `--fcd-output.filter-edges.input-file` rather than sampling coarser — at
0.1 s an unfiltered network easily reaches hundreds of MB (225 MB for one corridor-hour).

**Measurement trap:** when tracking a wave front across frames, never enforce monotonicity by
*discarding* frames where it did not move — that biases the fit hard toward fast waves
(measured −3.46 → **−12.19 m/s**). Use a running minimum and keep every frame.

## Gotchas

- **Don't assume `plot_trajectories.py`'s default axes are a time-space diagram** — the default is distance-vs-speed; pass `-t td` (or the axis order needed) explicitly.
- **Plotting tools live in different directories** (`tools/` vs. `tools/visualization/`) — check both before concluding a tool isn't shipped.
- **FCD output can be large** (tens of MB for a modest scenario over an hour) — parse it with streaming techniques if writing custom analysis on top, same caution as any other per-step, per-vehicle output file.
- **The custom signal-overlay technique only works directly for a straight corridor.** For a curved or branching route, derive a genuine along-route distance (e.g. cumulative edge length up to the vehicle's current position) rather than assuming x/y position equals corridor distance.

## Related

- `visualize-network-congestion-heatmap` — this skill's spatial complement; colors network geometry by an edgeData metric rather than plotting time-series/trajectory data.
- `publish-georeferenced-and-animated-results` — the step past a static plot: headless FCD-driven MP4/GIF animation (11.55 ms/frame at 1280x720), GeoJSON export in real-world coordinates, and the sampling-period fidelity measurement quoted above.
- `run-simulation` — general command-line output configuration (`--fcd-output`, `--summary-output`) this skill's plots are built from.
- `optimize-signals-by-tlscoordinator` / `optimize-signals-by-tlscycleadaptation` — the green-wave scenario this skill was developed against; note `tlsCoordinator.py` can emit an offset-only override (no phases) depending on SUMO version — merge it onto a unified-cycle program rather than loading both as separate `tlLogic` definitions for the same id.
- `analyze-simulation-outputs` — the numeric-table analogue; pair its metrics with this skill's plots for the "is the visual difference real" cross-check.
- `implement-maxpressure-traci-controller` — the same `getControlledLinks`/phase-introspection technique this skill's `extract_green_windows.py` uses to find the right controlled-link index for a movement.
- [[sumo-plotting-tools]] — the underlying tool locations, options, and conventions this skill's workflow is built on.
- `validate-kinematic-wave-theory-across-car-following-models` — uses this skill's time-space diagram construction to trace wave fronts directly from FCD and fit their speed, then compares against each car-following model's own Rankine-Hugoniot prediction.
