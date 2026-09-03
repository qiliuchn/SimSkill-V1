---
summary: How SUMO's local XY frame inverts to WGS84 via the <location> element, and why a round-trip residual proves nothing (a deliberately broken transform round-trips perfectly while sitting 4209 km off) so only a comparison against source OSM nodes discriminates; plus the two measured ways a published result lies — the per-edge metric you color by moves the ranking because every metric imports a confounder from whatever normalizes it (lane count for density, speed limit for speedRelative), while the classification scheme cannot move a rank and instead controls dilution (quantile paints 19% of edges worst by construction); and an FCD sampling period above ~2 s aliases fast shockwaves into visual falsehood while leaving slow queue waves untouched.
keywords:
  - georeferencing
  - convertXY2LonLat
  - netOffset
  - projParameter
  - WGS84
  - GeoJSON
  - RFC-7946
  - coordinate-precision
  - polyconvert
  - choropleth-classification
  - jenks
  - quantile-classification
  - metric-confounder
  - fcd-sampling-period
  - shockwave-aliasing
  - animation-fidelity
created: 2026-08-11T21:30:00
last_updated: 2026-08-11T21:30:00
sources:
  - "[[episodic-memory/2026-08-11_19-40-15/summary.md]]"
  - https://sumo.dlr.de/docs/Geo-Coordinates.html
  - https://datatracker.ietf.org/doc/html/rfc7946
related_pages:
  - "[[spatial-congestion-heatmap-with-plot-net-dump]]"
  - "[[sumo-output-files]]"
  - "[[openstreetmap]]"
  - "[[sumo-plotting-tools]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[opendrive-and-network-format-interoperability]]"
  - "[[accessibility-measurement-and-transport-equity]]"
related_skills:
  - publish-georeferenced-and-animated-results
  - visualize-network-congestion-heatmap
  - visualize-trajectories-and-timeseries
  - load-osm-network
related_skills_for_graph_view:
  - "[[publish-georeferenced-and-animated-results]]"
  - "[[visualize-network-congestion-heatmap]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[load-osm-network]]"
---

# Georeferencing SUMO Output and Cartographic Fidelity

A SUMO network lives in an anonymous local Cartesian frame. Publishing a result — as a GIS
layer, a web map, or an animation — means inverting that frame back to the real world and
then making a series of representation choices, two of which measurably change what the
audience concludes. All figures below come from a 402-edge downtown Oakland OSM import with
a numerically-established ground-truth bottleneck.

## The transform

```
(x_local, y_local) = proj(lon, lat) + netOffset
(lon, lat)         = proj⁻¹(x_local − netOffset.x, y_local − netOffset.y)
```

`netOffset` is a **pure translation in projected metres** — no rotation, no scale — and both
it and `projParameter` (a PROJ string, e.g. `+proj=utm +zone=10 +ellps=WGS84 …`) live in the
net's `<location>` element alongside `origBoundary` and `convBoundary`. `sumolib`'s
`net.convertXY2LonLat` / `convertLonLat2XY` implement exactly this.

## A round-trip residual is not validation

This is the central methodological point. A round trip XY → lon/lat → XY measures only that
two functions invert each other, which they do **even when both are wrong**. Measured: the
round-trip residual over 2 000 shape points was 2.873e−09 m max — and a control with
`netOffset` deliberately applied twice round-tripped just as cleanly while sitting
**4 209 729 m** from the true position.

The discriminating check compares against an **external ground truth**: the `lon`/`lat` of
the source `.osm` nodes. SUMO preserves OSM node ids as junction ids for junctions it did
not synthesise, so the join is exact where it exists. Measured over **190 junctions**: max
**0.0097 m**, RMS **0.0052 m**, median 0.0050 m — *below* the ~0.011 m quantum of OSM's own
7-decimal coordinates, so the transform contributes essentially nothing to the residual.
Always report the match count; a check resting on three joins is not evidence.

A related trap: cross-checking `sumolib` against SUMO's own C++ `--fcd-output.geo` appears
to show a **7.1 cm** disagreement, which is not a transform difference at all — it is the
default `--precision.geo 6` (≈0.11 m of latitude) compounded by the default `--precision 2`
quantising local x/y to 1 cm. At `--precision 10 --precision.geo 12` the two agree to
6.75e−08 m.

## Networks with no projection

Read `projParameter` **first**: a synthetic `netgenerate` network carries `projParameter="!"`.
`sumolib` then raises

```
RuntimeError: Network does not provide geo-projection or pyproj not installed.
```

which is the right behaviour — no silent identity transform, no fabricated lon/lat — but the
message **conflates a missing projection with a missing dependency**, so read `<location>`
rather than trusting the exception text.

The honest fallback is to publish **local ENU metres and declare it**, never fake lon/lat.
RFC 7946 *forbids* a `crs` member (lon/lat WGS84 is mandatory and implicit), so the frame goes
in a top-level `metadata` foreign member, which is legal. An operator-supplied anchor should
be recorded as `declared_by: user/publisher, NOT derived from the network` — and the
tangent-plane error it implies is real: **max 11.38 m, RMS 7.93 m** over a 1.6 × 1.5 km extent.

## GeoJSON precision: 6 decimals, and precision is not your compression lever

Sweep against a 12-decimal reference:

| decimals | layer-set kB | size vs 7 dp | max err m | vertices collapsed |
|---|---|---|---|---|
| 7 | 2 760.3 | 100.0 % | 0.0070 | 0 |
| **6** | **2 692.8** | **97.6 %** | **0.0691** | **0** |
| 5 | 2 610.8 | 94.6 % | 0.6987 | 53 |
| 4 | 2 383.4 | 86.3 % | 6.9602 | 572 |

6 dp is the last precision with **zero vertex collapse**, and below it there is nothing to
buy: even 4 dp is only **13.7 %** smaller, because property values and JSON punctuation
dominate the file, not coordinates. Shrink a layer set by splitting intervals into separate
files or normalising geometry out of the per-interval layer — not by degrading coordinates.

(Note the tempting-but-wrong justification: 0.069 m at 6 dp is *not* "below OSM's own
7-decimal quantum" — that quantum is ~0.011 m. 6 dp does add error beyond the source data's
resolution; it is simply negligible in absolute terms.)

Two more publishing facts: emit **x = longitude first** (the most common GeoJSON bug), and
validate a **known-bad** file as well as the good one — a validator that has never rejected
anything is not evidence. `ogrinfo`/`ogr2ogr` (GDAL, the same driver QGIS uses) is the
external reader of record. For context polygons, `polyconvert --osm-files … --net-file … 
--type-file $SUMO_HOME/data/typemap/osmPolyconvert.typ.xml` works, and the `--net-file` is
what supplies the projection and offset.

## The metric moves the ranking; the classification scheme cannot

A classification is a monotone function of the value, so an edge's **rank is
scheme-invariant by construction**. What varies with the scheme is *dilution* — how many
features share the top colour. Both effects were measured against a bottleneck established
numerically before any map was drawn (118 edges, 5 classes):

| metric | ground-truth rank | in worst class? (equal / quantile / Jenks / log) |
|---|---|---|
| `density`, `laneDensity` | **1** | YES / YES / YES / YES |
| `occupancy` | 2 | YES / YES / YES / YES |
| `speedRelative` | **10** | YES / YES / YES / **NO** |

**Every metric imports a confounder from whatever normalizes it**, and which confounder
bites is a property of the network, not of the metric:

- `density` is per *edge*, so its confounder is **lane count**. Mean rank shift
  `density → occupancy`: 1-lane **+23.8**, 2-lane −6.0, 3-lane **−25.7** — it over-ranks wide
  edges and under-ranks single lanes. This is the finding recorded in
  [[spatial-congestion-heatmap-with-plot-net-dump]], now quantified.
- `speedRelative` is relative to the *posted speed*, so its confounder is the **speed limit**.
  Mean rank shift `occupancy → speedRelative`: 8.9 m/s −12.3, 13.9 −10.9, 22.2 **+21.0**,
  27.8 **+40.1**. One Broadway edge moved from occupancy rank 14 to speedRelative rank
  **118 of 118**.

On this network every top candidate was 2-lane, so density and occupancy nearly agreed and
**`speedRelative` was the metric that broke — the opposite of the previously recorded case.**
The generalizable rule is not "density bad" but *ask what the metric is normalized by, and
whether that quantity varies across the network*.

Scheme failure modes (worst-class membership of 118 edges):

| scheme | members | failure mode |
|---|---|---|
| Jenks (natural breaks) | 3 | data-derived breaks are incomparable across frames — per-frame classification in an animation shows colour changes that are *reclassification, not traffic* |
| equal-interval | 4 | one outlier stretches the range and empties the middle classes |
| log | 7 | compresses exactly the high end a congestion map is about — pushed the ground truth out of the worst class entirely |
| **quantile** | **23 (19 %)** | paints 1/N worst **by construction, even on an empty network** — buried the true bottleneck among 22 equally-red edges |

**Defensible default**: colour by `occupancy` or `laneDensity`; use **fixed, absolute,
externally-anchored breaks** (the only choice that makes time slices comparable, and
mandatory for animation); prefer Jenks to quantile if the breaks must be data-derived; and
publish metric and breaks in the legend *and* the file metadata.

## Animation fidelity: where the sampling period aliases

Sweeping `--device.fcd.period` and measuring shockwave speeds as they would be read off the
rendered frames, against ground truth from a 0.1 s FCD (equal to the simulation step):

| period | FCD MB | stopping-wave err | discharge-wave err | cycles resolvable | wave travel/frame |
|---|---|---|---|---|---|
| 0.5 s | 45.13 | −1.7 % | +1.5 % | 13/13 | 0.2 veh |
| **1 s** | **22.56** | −2.5 % | **+2.4 %** | 12/13 | 0.5 veh |
| 2 s | 11.28 | −0.6 % | −6.0 % | 10/13 | 1.0 veh |
| 5 s | 4.51 | −8.7 % | **+18.7 %** | 9/13 | 1.9 veh |
| 10 s | 2.25 | +13.1 % | +5.7 % | **4/13** | **4.4 veh** |

**≤1 s faithful, 2 s the ceiling, 5 s misleading, 10 s broken.** Judge aliasing by
*resolvability* and per-frame travel, not by an averaged error: the 10 s row's median
discharge error looks acceptable at +5.7 %, but the wave is unmeasurable in **69 %** of green
onsets and the front jumps 4.4 vehicle lengths per frame — a teleport, not a wave.

**The asymmetry that matters**: the slow queue-envelope wave (−0.176 m/s) is essentially
immune to sampling period (within 13 % even at 10 s), while the fast stop/discharge waves
(−1.55 / −3.46 m/s) alias badly. So **a sampling period chosen by watching a congestion map
will be far too coarse for an animation of the same scenario** — the two artifacts have
different sampling requirements from the same run. This is the practical, output-side
counterpart of the discretization sensitivity in
[[kinematic-wave-theory-validity-across-car-following-models]].

**Measurement trap**: tracking a wave front by *discarding* frames where it did not move
biases the fit hard toward fast waves — measured −3.46 → **−12.19 m/s**. Use a running
minimum and keep every frame.

Headless rendering (matplotlib Agg, pre-rasterised static background, blit only the vehicles,
raw frames piped to ffmpeg) cost **11.55 ms/frame** at 1280×720 — 52.4 s for a 3 600-frame
video.

## The `sumo-gui` screenshot route

Needed only for SUMO's own rendering (lane borders, link decals, sublane geometry). Measured:

- **`traci.start()` races the GUI's window/GL creation** → `FatalTraCIError: Connection closed
  by SUMO`. Spawn `sumo-gui --remote-port P`, sleep ~6 s, then `traci.init(port=P)`.
- **`gui.screenshot` captures the GL canvas, not the window, and it is not fully composited**:
  a requested 1280 × 720 produced a **1270 × 534** PNG with the left ~27 % solid black, with
  nothing in the API reporting it.
- **Viewsettings colour-mode ids are positional and version-dependent**: `laneEdgeMode="17"`
  written expecting "by allowed speed" rendered as "given length / geometrical length" in
  1.27.1, and the `<colorScheme name=…>` child did not override it. Verify against the
  rendered legend.
- **It does not require an X11 `DISPLAY`** on macOS — the FOX toolkit uses the Cocoa backend
  there, verified with `env -u DISPLAY`. The dependency is a windowing/GL *toolkit*, genuine
  on a headless Linux server (Xvfb) and absent on macOS. Test the negative before asserting a
  display dependency.

## Practical notes

- **Two `<edgeData>` collectors must not share an additional file.** The element's own `file=`
  wins over `--edgedata-output` and resolves relative to the additional file's directory, so a
  second run silently overwrites the first's output — see [[sumo-output-files]].
- **`xml.etree.iterparse`: clear only the element you are handling.** Clearing non-target
  elements wipes children before the parent's `end` event fires, silently producing empty
  results.
- **`osmGet.py` expands the requested bbox** (a 1.23 × 1.11 km request yielded 1.61 × 1.48 km) —
  read the resulting `convBoundary`.
- **A `--` sequence is illegal in an XML comment**, so documenting a CLI flag inside an
  additional file makes SUMO refuse to load it.
- **Restrict FCD** with `--fcd-output.filter-edges.input-file`; at 0.1 s an unfiltered network
  easily reaches hundreds of MB (225 MB for one corridor-hour here).
