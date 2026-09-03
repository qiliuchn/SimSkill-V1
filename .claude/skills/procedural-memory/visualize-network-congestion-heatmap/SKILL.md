---
name: visualize-network-congestion-heatmap
description: Use this skill when the user wants to render a spatial congestion heatmap of a SUMO network — the network's actual geometry colored by a per-edge metric (speed, occupancy, density) from edgeData/meandata output, using SUMO's plot_net_dump.py. Covers configuring time-sliced edgeData for the tool's input, plot_net_dump.py's real command-line interface (--measures, colormap, width, title substitution), the choice of which metric correctly localizes a bottleneck, and cross-checking the visual hotspot against raw numeric data rather than trusting the image alone. Trigger on mentions of congestion heatmap, plot_net_dump, spatial visualization, or network congestion map.
---

# Visualize Network Congestion Heatmap

Renders a spatial congestion heatmap — the network's own geometry colored by a per-edge metric like speed, occupancy, or density — using SUMO's `plot_net_dump.py` ($SUMO_HOME/tools/visualization/). This is SimSkill's only *spatial* post-processing visualization; every other image-producing capability in memory (`visualize-trajectories-and-timeseries`) produces time-series or time-space-trajectory plots, not a colored map answering "where is congestion happening?"

## Configuring time-sliced edgeData input

`plot_net_dump.py` consumes an `<edgeData>`/`meandata` output file — configure it with a fixed aggregation interval to get multiple time-sliced snapshots:

```xml
<additional>
    <edgeData id="congestion" file="edgedata_congestion.out.xml" freq="600"/>
</additional>
```

**`plot_net_dump.py` does not reliably cycle through multiple `<interval>` blocks in one file across separate invocations** — split the multi-interval output into one file per interval (`scripts/split_intervals.py`) and render each separately for explicit, unambiguous control over which interval's data colors a given PNG.

## `plot_net_dump.py`'s real interface

```bash
python3 $SUMO_HOME/tools/visualization/plot_net_dump.py \
    -n net.xml -i edgedata_600.out.xml \
    -m occupancy --colormap RdYlGn_r --min-color-value 0 --max-color-value 45 \
    -w 14 --color-bar-label "occupancy (%)" --title "Lane occupancy @ t=600s" \
    -o plots/occupancy_600.png -b
```

- **`-m/--measures`**: the color measure **must be an exact `<edge>` attribute name** from the edgeData file (`speed`, `occupancy`, `density`, `speedRelative`, `timeLoss`, ...). A typo or non-existent attribute doesn't error — it silently produces default-colored (missing-data) edges, so verify the rendered colors actually vary before trusting a flat-looking map.
- **`--colormap`**: use `RdYlGn` (low=red=bad) for speed/speedRelative; use `RdYlGn_r` (high=red=bad) for occupancy/density.
- **`--min-color-value`/`--max-color-value`**: fix the color scale so multiple intervals/PNGs are visually comparable against each other, rather than each auto-scaling to its own data range.
- **`-w`**: the *default* edge width. Without a *second* dump file supplying widths, `--min-width`/`--max-width` are ignored and every edge falls back to `--defaultwidth` (0.1 — effectively invisible). Set `-w` explicitly for legible output.
- **`'%s'` substitutes only in the `-o` output filename**, not in `--title` — render one interval at a time (see above) to give each PNG a properly descriptive title rather than a generic one.

## Network geometry must be genuinely 2-D

**A degenerate 1-D network (all nodes collinear, e.g. every node at `y=0`) can render every edge in a single flat color regardless of the actual color data** — the LineCollection needs real 2-D extent for the color mapping to display meaningfully. Build test/demo corridors with genuine 2-D geometry (e.g. a zigzag), not a perfectly straight line, even when the underlying traffic scenario is conceptually 1-D.

## Choosing the right metric: density is per-edge, not per-lane

**SUMO's `density` edgeData attribute is normalized per edge, not per lane** — a wide, multi-lane edge can accumulate a higher density number than a genuinely more-congested single-lane bottleneck simply because it holds more total vehicles across its lanes. This can cause a density-colored heatmap to flag the wrong edge as the worst hotspot when the true bottleneck is a lane-count-change point. **Color by `occupancy` or `laneDensity` to correctly localize a lane-drop or similar capacity-constrained bottleneck** — both reflect per-lane saturation rather than raw vehicle count.

### The general rule: every metric imports a confounder from whatever normalizes it

The density-vs-occupancy trap above is one instance of a general one, and the metric that
breaks depends on the network rather than being a fixed property of the metric. Measured on
a 402-edge OSM import against a numerically-established ground-truth bottleneck
([[georeferencing-sumo-output-and-cartographic-fidelity]]):

- `density` is per **edge**, so its confounder is **lane count**. Mean rank shift
  `density → occupancy` by lane count: 1-lane **+23.8**, 2-lane −6.0, 3-lane **−25.7** — the
  finding above, now quantified.
- `speedRelative` is relative to the **posted speed**, so its confounder is the **speed
  limit**. Mean rank shift `occupancy → speedRelative`: 8.9 m/s −12.3, 13.9 −10.9, 22.2
  **+21.0**, 27.8 **+40.1**. One arterial edge went from occupancy rank 14 to speedRelative
  rank **118 of 118**.

On that network every top candidate happened to be 2-lane, so density and occupancy nearly
agreed and **`speedRelative` was the metric that broke — the reverse of the case recorded
here.** So don't memorise "density bad": ask what the metric is normalized by, and whether
that quantity varies across your network. `speedRelative` is *not* a safe default on a
network with mixed speed limits.

### The classification scheme cannot change a rank — but it changes what reads as worst

A classification is a monotone function of the value, so an edge's rank is scheme-invariant.
What the scheme controls is **dilution** — how many edges share the top colour (measured, of
118 edges, 5 classes): Jenks 3, equal-interval 4, log 7, **quantile 23 (19 %)**. Quantile
paints 1/N worst *by construction, even on an empty network*, and here it buried the true
bottleneck among 22 equally-red edges; log compresses exactly the high end a congestion map
is about, and pushed the ground truth out of the worst class entirely.

Use **fixed, absolute, externally-anchored breaks** (e.g. occupancy 0/10/25/40/60/100 %).
That is the only choice that makes time slices comparable — with data-derived breaks, an
animation's colour changes are partly *reclassification rather than traffic*. Publish the
metric and the breaks in the legend.

## Verifying the heatmap against raw data — don't just eyeball the PNG

```bash
python scripts/verify_hotspot.py --edgedata edgedata_congestion.out.xml --expected-bottleneck CD
```

Ranks every edge per interval by the same attributes the heatmap was colored with, confirming the visually-worst edge in the image genuinely corresponds to the numerically-worst edge in the raw data — and flags cases (like the density-vs-occupancy divergence above) where different metrics would identify different edges as the "hotspot."

## What a correct bottleneck heatmap looks like

Measured on a 2-lane-to-1-lane corridor under an oversaturated demand period: coloring by occupancy or speedRelative correctly flagged the single-lane bottleneck edge as the reddest (worst) hotspot in every congested interval, with the immediately-upstream multi-lane edges showing a visible but lesser backing-up queue and the downstream edge flowing freely — a spatially coherent, verifiable congestion pattern. Coloring by raw density alone mis-ranked a wider upstream feeder edge above the true bottleneck in the same interval, demonstrating the metric-choice gotcha directly.

## Gotchas

- **A typo'd or nonexistent `-m` measure name silently yields default-colored edges, not an error** — verify the rendered map actually shows color variation.
- **Set `-w` explicitly** — without a width dump file, edges default to a near-invisible 0.1 width.
- **`'%s'` substitutes only in `-o`, not `--title`** — split multi-interval data and render per-interval for properly titled plots.
- **A degenerate/collinear network can render entirely in one flat color** regardless of the underlying data — ensure genuine 2-D geometry.
- **`density` is per-edge, not per-lane** — prefer `occupancy`/`speedRelative` to correctly localize a lane-count-change bottleneck.

## Related

- `visualize-trajectories-and-timeseries` — SimSkill's other (non-spatial) plotting skill; this one's spatial complement.
- `build-macroscopic-fundamental-diagram`, `implement-variable-speed-limits` — the lane-drop-bottleneck-construction technique this skill's demo scenario builds on.
- `analyze-simulation-outputs` — general edgeData/output-parsing skill this one specializes for the visual-vs-raw-data cross-check.
- [[spatial-congestion-heatmap-with-plot-net-dump]] — the underlying `plot_net_dump.py` mechanics, gotchas, and the verified metric-choice/bottleneck-localization finding.
