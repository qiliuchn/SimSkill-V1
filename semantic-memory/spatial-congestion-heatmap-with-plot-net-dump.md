---
summary: SUMO's plot_net_dump.py renders network geometry colored by a per-edge edgeData metric, producing a spatial congestion heatmap; density (normalized per-edge, not per-lane) can mis-rank a wider feeder above the true bottleneck, and the general rule is that every metric imports a confounder from whatever normalizes it - lane count for density, posted speed for speedRelative, which mis-ranked an arterial edge from occupancy rank 14 to 118 of 118 - so occupancy and laneDensity are the robust defaults; separately, the classification scheme cannot change a rank but controls how many edges share the worst colour (quantile paints 19% worst by construction).
keywords:
  - plot_net_dump
  - congestion-heatmap
  - spatial-visualization
  - edgeData
  - occupancy-vs-density
  - metric-confounder
  - laneDensity
  - choropleth-classification
created: 2026-07-27T20:50:00
last_updated: 2026-08-11T21:30:00
sources:
  - "[[episodic-memory/2026-07-27_20-32-19/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-27_20-32-19/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/Tools/Visualization.html
  - "[[episodic-memory/2026-08-11_19-40-15/summary.md]]"
related_pages:
  - "[[georeferencing-sumo-output-and-cartographic-fidelity]]"
  - "[[sumo-plotting-tools]]"
  - "[[sumo-output-files]]"
  - "[[variable-speed-limits-and-e2-detectors]]"
  - "[[harmonoise-traffic-noise-modeling]]"
related_skills:
  - publish-georeferenced-and-animated-results
  - visualize-network-congestion-heatmap
  - visualize-trajectories-and-timeseries
  - build-macroscopic-fundamental-diagram
related_skills_for_graph_view:
  - "[[publish-georeferenced-and-animated-results]]"
  - "[[visualize-network-congestion-heatmap]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[build-macroscopic-fundamental-diagram]]"
---

# Spatial Congestion Heatmap with plot_net_dump.py

`plot_net_dump.py` (`$SUMO_HOME/tools/visualization/`) renders a SUMO network's own geometry colored by a per-edge metric from `edgeData`/meandata output — the one spatial visualization in SUMO's toolkit, distinct from every other plotting tool documented in [[sumo-plotting-tools]] (`plot_trajectories.py`'s time-space diagrams, `plot_summary.py`'s time-series charts), all of which are non-spatial.

## Configuring input and the multi-interval gotcha

Configure an `<edgeData>` additional-file with a fixed `freq` for time-sliced snapshots. **`plot_net_dump.py` does not reliably cycle through multiple `<interval>` blocks within one file across separate invocations** — split a multi-interval output into one file per interval and render each separately for explicit control over which interval colors a given PNG.

## Real command-line interface

- **`-m/--measures`** must be an exact `<edge>` attribute name from the edgeData file (`speed`, `occupancy`, `density`, `speedRelative`, etc.) — a typo or nonexistent attribute silently produces default-colored (missing-data) edges rather than an error.
- **`--colormap`**: `RdYlGn` for speed/speedRelative (low=red=bad); `RdYlGn_r` for occupancy/density (high=red=bad).
- **`--min-color-value`/`--max-color-value`** fix a comparable scale across multiple rendered intervals.
- **`-w`** sets the default edge width; without a second dump file supplying per-edge widths, `--min-width`/`--max-width` are ignored and edges fall back to `--defaultwidth` (0.1, effectively invisible) — set `-w` explicitly.
- **`'%s'` substitutes only in the `-o` output filename, not in `--title`** — render per-interval split files to give each PNG a properly descriptive title.

## Network geometry must be genuinely 2-D

A degenerate 1-D network (all nodes collinear) can render every edge in a single flat color regardless of the underlying data — the rendered line collection needs real 2-D extent for color mapping to display meaningfully. Even a conceptually 1-D test corridor should be laid out with genuine 2-D geometry (e.g. a zigzag) for the tool to work correctly.

## Metric choice: density is per-edge, not per-lane

**`density` is normalized per edge, not per lane** — a wide, multi-lane edge can accumulate a higher density figure than a genuinely more-congested single-lane bottleneck simply by holding more total vehicles across its lanes. Coloring a heatmap by raw density can therefore mis-identify the wrong edge as the worst congestion hotspot when the true bottleneck is a lane-count-change point. **`occupancy` and `speedRelative` are normalized per-lane-capacity** and correctly localize such bottlenecks instead.

## Verifying the heatmap, not just eyeballing it

A congestion heatmap's visual "hotspot" should be cross-checked against the raw edgeData numbers — rank every edge per interval by the attribute the map was colored with, and confirm the visually-worst edge genuinely matches the numerically-worst edge, rather than trusting a color impression alone.

## Measured finding

On a 2-lane-to-1-lane corridor under an oversaturated demand period: coloring by `occupancy` or `speedRelative` correctly identified the single-lane bottleneck edge as the worst hotspot in every congested interval, with immediately-upstream multi-lane edges showing a visibly lesser backing-up queue and the downstream edge flowing freely — a spatially coherent and numerically-verified congestion pattern. Coloring by raw `density` alone, in the same interval, mis-ranked the wider upstream feeder edge above the true single-lane bottleneck, directly demonstrating the per-edge-vs-per-lane metric-choice gotcha.

See the `visualize-network-congestion-heatmap` skill for the full build/render/verify workflow and bundled scripts.

## The general rule behind the density trap, and the scheme's separate role

The density-vs-occupancy mis-ranking above is one instance of a general mechanism: **every
per-edge metric imports a confounder from whatever normalizes it**, and which metric breaks
is a property of the network rather than of the metric. Measured on a 402-edge OSM import
against a numerically-established bottleneck
([[georeferencing-sumo-output-and-cartographic-fidelity]]):

- `density` is per **edge**, confounder **lane count**. Mean rank shift `density -> occupancy`:
  1-lane **+23.8**, 2-lane -6.0, 3-lane **-25.7** -- this page's finding, quantified.
- `speedRelative` is relative to the **posted speed**, confounder the **speed limit**. Mean rank
  shift `occupancy -> speedRelative`: 8.9 m/s -12.3, 13.9 -10.9, 22.2 **+21.0**, 27.8 **+40.1**.
  One arterial edge moved from occupancy rank 14 to speedRelative rank **118 of 118**.

On that network all top candidates were 2-lane, so density and occupancy nearly agreed and
**`speedRelative` was the metric that broke -- the reverse of the case recorded here.** So
`speedRelative`, named above as a safe alternative to `density`, is *not* safe on a network
with mixed speed limits. The durable rule is to ask what the metric is normalized by and
whether that quantity varies across the network; `occupancy` and `laneDensity` are the
robust defaults.

Separately, the **classification scheme cannot change an edge's rank** -- a classification is
monotone in the value -- but it does change how many edges share the worst colour. Of 118
edges in 5 classes: Jenks 3, equal-interval 4, log 7, **quantile 23 (19%)**. Quantile paints
1/N worst *by construction, even on an empty network*; log compresses exactly the high end a
congestion map is about and pushed the ground truth out of the worst class. Prefer **fixed,
absolute, externally-anchored breaks** -- the only choice that keeps time slices comparable,
since with data-derived breaks an animation's colour changes are partly reclassification
rather than traffic.
