---
name: publish-georeferenced-and-animated-results
description: Use this skill to turn a SUMO run into a real deliverable — GIS-ready GeoJSON layers in WGS84 lon/lat that open in QGIS/kepler.gl/ogrinfo, a time-animated MP4/GIF of the traffic, or a self-contained single-file HTML map viewer — instead of leaving results as numbers in SUMO's anonymous local coordinate frame or as a static PNG. Covers inverting SUMO's local XY back to lon/lat via the `<location>` element and sumolib (and why a round-trip residual proves nothing, so you must validate against the source OSM nodes), what to do when the network has no projection at all, RFC 7946 conformance and coordinate-precision choice, `polyconvert` for building/landuse context polygons, headless frame rendering from `--fcd-output` piped to ffmpeg, and the automated `sumo-gui` screenshot route. Also quantifies two ways a map lies: which per-edge metric you color by changes which edge reads as worst (every metric imports a confounder from whatever normalizes it), and too coarse an FCD sampling period aliases shockwaves into something visually false. Trigger on GeoJSON, georeference, lon/lat, WGS84, EPSG, QGIS, kepler.gl, GIS export, shapefile, web map, map layer, `convertXY2LonLat`, `polyconvert`, animation, MP4, GIF, video, time slider, `gui.screenshot`, viewsettings, or "put these results on a map".
---

# Publish Georeferenced and Animated Results

Takes a finished SUMO run and produces the artifacts someone else can actually open: a
layered GeoJSON set in real-world coordinates, an animation, and a standalone HTML
viewer. Two of the three headline questions here are *fidelity* questions — whether the
map and the animation tell the truth — not plumbing.

`visualize-network-congestion-heatmap` and `visualize-trajectories-and-timeseries` render
*images* from SUMO's shipped plotters. This skill is the step past that: georeferenced
**data** other tools consume, plus animation, plus the measurement of when each lies.

## Scripts

`scripts/sumo_geo.py` — the reusable core (stdlib + `sumolib`; no geopandas/shapely
needed):

- `read_location(net)` → the `<location>` attributes plus `has_projection`. **Call this
  first**, always (see below).
- `validate_against_osm(net, osm)` → the discriminating georeferencing check, in metres.
- `roundtrip_residual(net, points)` → the self-consistent check that proves nothing.
- `write_geojson(path, features, precision=6, metadata=…)` → RFC 7946 writer.
- `local_enu_metadata(loc, assumed_lonlat=None)` → the honest fallback for unprojected nets.
- `validate_rfc7946(path)` → `(errors, n_positions)`.

```bash
python3 scripts/sumo_geo.py net.net.xml source.osm.xml   # prints projection + OSM error stats
```

Verified on a 402-edge Oakland import: `matched: 190, max_m: 0.0097, rms_m: 0.0052`, and
0 errors over 34 687 positions across 7 layers.

A complete worked implementation (OSM import, 7 layers, classification study, FCD sweep,
headless renderer, GUI probe, single-file viewer) is in
`episodic-memory/2026-08-11_19-40-15/attempts/attempt-1/scripts/`.

## The transform, and why the obvious validation is worthless

```
(x_local, y_local) = proj(lon, lat) + netOffset
(lon, lat)         = proj⁻¹(x_local − netOffset.x, y_local − netOffset.y)
```

`netOffset` is a pure translation in **projected metres** — no rotation, no scale. Both it
and `projParameter` live in the net's `<location>` element. `sumolib`'s
`net.convertXY2LonLat` / `convertLonLat2XY` implement exactly this.

**A round-trip XY → lon/lat → XY residual proves nothing.** Measured: 2.873e−09 m max over
2 000 points — and a deliberately broken transform (applying `netOffset` twice) round-trips
just as perfectly while sitting **4 209 729 m** from the truth. The round trip only tests
that two functions are inverses of each other, which they are even when both are wrong.

**Validate against the source `.osm` instead.** SUMO keeps OSM node ids as junction ids for
junctions it did not synthesise, so the join is exact. Measured over **190 junctions**: max
**0.0097 m**, RMS **0.0052 m** — below the ~0.011 m quantum of OSM's own 7-decimal
coordinates, i.e. the transform contributes essentially nothing to the error. Report the
match count too; a check with 3 joins is not evidence.

**Cross-checking against SUMO's own `--fcd-output.geo` needs both precision flags raised.**
At defaults the C++ and Python paths appear to disagree by **7.1 cm** — that is entirely
`--precision.geo 6` (≈0.11 m of latitude) compounded by `--precision 2` quantising local
x/y to 1 cm. With `--precision 10 --precision.geo 12` they agree to **6.75e−08 m**. Don't
chase this phantom.

## When the network has no projection

Check `projParameter` **first**. A synthetic `netgenerate` network has
`projParameter="!"`, and `sumolib` then raises:

```
RuntimeError: Network does not provide geo-projection or pyproj not installed.
```

Good news: no silent identity transform, no fabricated lon/lat. Bad news: that message
**conflates a missing projection with a missing dependency**, so an operator who reads it
literally may go install pyproj for an hour. `read_location()` distinguishes them.

The honest fallback is to publish **local ENU metres** and say so — never fake lon/lat.
RFC 7946 forbids a `crs` member (lon/lat WGS84 is mandatory and implicit), so declare the
frame in a top-level `metadata` foreign member, which is legal. If the operator supplies
an anchor point, record it as `declared_by: user/publisher, NOT derived from the network`,
and note the tangent-plane cost such an anchor implies: measured **max 11.38 m, RMS
7.93 m** over a 1.6 × 1.5 km extent.

## GeoJSON: conformance and precision

Emit lon/lat, **x = longitude first** — the single most common GeoJSON bug. Validate with
a real reader (`ogrinfo -ro -al -so`, or `ogr2ogr -f GPKG` to prove round-tripping); GDAL
is the same driver QGIS uses. And **validate a known-bad file too** — a validator that has
never rejected anything is not evidence. The bundled validator returns 0 errors on 34 687
good positions and 2 238 on a copy with lat/lon swapped and a `crs` member injected.

**Precision: use 6 decimals.** Measured sweep against a 12-decimal reference:

| decimals | layer-set kB | size vs 7 dp | max err m | vertices collapsed |
|---|---|---|---|---|
| 7 | 2 760.3 | 100.0 % | 0.0070 | 0 |
| **6** | **2 692.8** | **97.6 %** | **0.0691** | **0** |
| 5 | 2 610.8 | 94.6 % | 0.6987 | **53** |
| 4 | 2 383.4 | 86.3 % | 6.9602 | **572** |

6 dp is the last precision with **zero vertex collapse**, and below it there is nothing to
gain: **coordinate precision is a poor compression lever** — even 4 dp is only 13.7 %
smaller, because property values and JSON punctuation dominate, not coordinates. If a
layer set is too big, split intervals into separate files or normalise geometry out of the
per-interval layer; do not degrade coordinates.

Make the results layer **time-enabled** by carrying `interval_begin`/`interval_end` on every
feature (one feature per edge per interval), which is what drives a QGIS Temporal Controller
or an HTML slider.

**`polyconvert` recipe for context polygons** (buildings/landuse/water):

```bash
polyconvert --osm-files osm.xml --net-file net.xml \
  --type-file $SUMO_HOME/data/typemap/osmPolyconvert.typ.xml \
  --osm.keep-full-type -o out.poly.xml
```

The `--net-file` is what supplies the projection and offset — without it the polygons land
in a different frame from the network.

## How much a congestion map can lie

Two separable effects, and only one of them is the one people worry about.

**The metric moves the ranking; the classification scheme cannot.** Every scheme partitions
a single monotone value axis, so an edge's *rank* is scheme-invariant by construction.
Measured on 118 edges against a numerically-established ground-truth bottleneck:

| metric | GT rank | in worst class? (equal / quantile / Jenks / log) |
|---|---|---|
| `density`, `laneDensity` | **1** | YES / YES / YES / YES |
| `occupancy` | 2 | YES / YES / YES / YES |
| `speedRelative` | **10** | YES / YES / YES / **NO** |

**Every metric imports a confounder from whatever normalizes it**, and which one bites
depends on the network:

- `density` is per *edge*, so its confounder is **lane count**. Mean rank shift
  `density → occupancy`: 1-lane **+23.8**, 2-lane −6.0, 3-lane **−25.7** — it over-ranks
  wide edges and under-ranks single lanes.
- `speedRelative` is relative to the *posted speed*, so its confounder is the **speed
  limit**. Mean rank shift `occupancy → speedRelative`: 8.9 m/s −12.3, 13.9 −10.9,
  22.2 **+21.0**, 27.8 **+40.1**. One Broadway edge went from occupancy rank 14 to
  speedRelative rank **118 of 118**.

On the network measured here every top candidate was 2-lane, so density and occupancy
nearly agreed and **`speedRelative` was the metric that broke** — the opposite of the case
recorded in [[spatial-congestion-heatmap-with-plot-net-dump]]. Same mechanism, different
confounder. Don't memorise "density bad"; ask what the metric is normalized by.

**What the scheme changes is dilution** — how many edges share the top colour (of 118):

| scheme | worst-class members | failure mode |
|---|---|---|
| Jenks | 3 | data-derived breaks are incomparable across frames — per-frame classification in an animation shows colour changes that are *reclassification, not traffic* |
| equal-interval | 4 | one outlier stretches the range and empties the middle classes |
| log | 7 | compresses exactly the high end a congestion map is about — pushed the ground truth out of the worst class |
| **quantile** | **23 (19 %)** | paints 1/N worst **by construction, even on an empty network** — buried the true bottleneck among 22 equally-red edges |

**Default:** color by `occupancy` or `laneDensity` (never raw `density`, never
`speedRelative` alone); use **fixed, absolute, externally-anchored breaks** (e.g. occupancy
0/10/25/40/60/100 %) — the only choice that makes time slices comparable, and *mandatory*
for animation; prefer Jenks to quantile if data-derived is unavoidable; and publish the
metric and breaks in both the legend and the file metadata.

Establish the ground-truth worst edge **numerically, before drawing anything**, and judge
the map against it — that is `visualize-network-congestion-heatmap`'s discipline and it is
what makes any of the above measurable rather than aesthetic.

## Animation: the sampling period at which it stops being true

Render **headless** from `--fcd-output` (matplotlib Agg with a pre-rasterised static
background, blitting only the vehicles, raw frames piped straight into ffmpeg). Measured
cost: **11.55 ms/frame median** at 1280×720, 52.4 s for a 3 600-frame video.

Then pick the FCD period by measurement, not habit. Sweeping `--device.fcd.period` against
shockwave speeds read off the frames as an analyst would, with ground truth from a 0.1 s
FCD (= the simulation step):

| period | FCD MB | stopping-wave err | discharge-wave err | cycles resolvable | wave travel per frame |
|---|---|---|---|---|---|
| 0.5 s | 45.13 | −1.7 % | +1.5 % | 13/13 | 0.2 veh |
| **1 s** | **22.56** | −2.5 % | **+2.4 %** | 12/13 | 0.5 veh |
| 2 s | 11.28 | −0.6 % | −6.0 % | 10/13 | 1.0 veh |
| 5 s | 4.51 | −8.7 % | **+18.7 %** | 9/13 | 1.9 veh |
| 10 s | 2.25 | +13.1 % | +5.7 % | **4/13** | **4.4 veh** |

**≤1 s faithful, 2 s the ceiling, 5 s misleading, 10 s broken. Default to 1 s.** Note the
10 s row: its median discharge error looks fine at +5.7 %, but the wave is unmeasurable in
**69 % of green onsets** and the front jumps 4.4 vehicle lengths per frame — a teleport,
not a wave. Judge aliasing by resolvability and per-frame travel, not by an error averaged
over the cases that survived.

**The asymmetry that matters:** the slow queue-envelope wave (−0.176 m/s) is essentially
immune to sampling period (within 13 % even at 10 s) while the fast stop/discharge waves
alias badly. So **a sampling period chosen by watching a congestion map will be far too
coarse for an animation of the same scenario.** The two artifacts have different
requirements from the same run.

Restrict FCD with `--fcd-output.filter-edges.input-file` — at 0.1 s an unfiltered network
easily produces hundreds of MB.

**Measurement trap:** when tracking a wave front, never enforce monotonicity by *discarding*
frames where the front did not move — that biases the fit hard toward fast waves (measured:
−3.46 → **−12.19 m/s**). Use a running minimum and keep every frame.

## The `sumo-gui` screenshot path (secondary)

Use it only when you need SUMO's *own* rendering (lane borders, link decals, sublane
geometry). Three measured gotchas:

- **`traci.start()` races the GUI's window/GL creation** and fails with
  `FatalTraCIError: Connection closed by SUMO`. Spawn `sumo-gui --remote-port P` yourself,
  sleep ~6 s, then `traci.init(port=P)` — reliable every time.
- **`gui.screenshot` captures the GL canvas, not the window, and it is not fully
  composited.** A requested `--window-size 1280,720` produced a **1270 × 534** PNG with the
  left ~27 % solid black. Nothing in the API reports this — open the file and look.
- **Viewsettings colour-mode ids are positional and version-dependent.**
  `<edges laneEdgeMode="17">` written expecting "by allowed speed" rendered in 1.27.1 as
  "given length / geometrical length", and the `<colorScheme name=…>` child did **not**
  override it. Verify against the rendered legend, not the index.

**On display dependency, test the negative before claiming one.** `sumo-gui`, TraCI and
`gui.screenshot` all work with **`DISPLAY` unset** on macOS, because the FOX toolkit uses
the Cocoa backend there — verified. The real dependency is a windowing/GL *toolkit*, which
on a headless Linux server is genuine (needs Xvfb) and on macOS is not. An earlier version
of this finding asserted a hard X11 dependency purely because `DISPLAY` happened to be set.

The headless path stays primary regardless: no toolkit at all, deterministic frame timing,
pixel buffer verifiable in-process, and re-renderable from stored FCD without re-simulating.

## Gotchas

- **Two `<edgeData>` collectors must not share an additional file.** An `<edgeData>`
  element's own `file=` attribute **wins over `--edgedata-output`** and resolves relative to
  the additional file's own directory — so a second run reusing the same `.add.xml`
  silently overwrites the first run's output. This bit here: a GUI probe destroyed the
  edgeData four downstream scripts read. Give every run its own copy. See
  [[sumo-output-files]].
- **`xml.etree.iterparse`: only `.clear()` the element you are handling.** Clearing
  non-target elements wipes children before the parent's `end` event fires, silently
  yielding empty results. This produced an empty arrivals table and zero PT stops before it
  was caught.
- **`osmGet.py` expands the requested bbox** — a 1.23 × 1.11 km request yielded a
  1.61 × 1.48 km network. Read the actual `convBoundary`, don't assume your bbox.
- **A `--` sequence is illegal inside an XML comment.** Documenting a CLI flag like
  `--edgedata-output` in an additional file's comment makes SUMO refuse to load it.
- **Dropping consecutive duplicate positions desynchronises vertex indices** between two
  exports, so a precision comparison must either keep duplicates (`--no-dedup`) or match on
  geometry rather than index. It also lets a polygon ring reverse when coarse rounding flips
  its signed area — measure precision error on line/point layers and report vertex collapse
  separately.
- Minor tool signatures: `osmBuild.py -n` needs `-n="…"` (argparse leading-dash) and rejects
  `--keep-edges.by-vclass` alongside `--vehicle-classes`; `randomTrips.py --validate` writes
  to `-r`, not `-o`; `numpy.ndarray.ptp` was removed in NumPy 2.0.

## Related

- [[georeferencing-sumo-output-and-cartographic-fidelity]] — the knowledge page behind this skill
- `visualize-network-congestion-heatmap` — renders the image; this skill exports the data
  and generalizes its metric-choice finding
- `visualize-trajectories-and-timeseries` — FCD handling and time-space diagrams; this skill
  adds the sampling-period fidelity limit for animation
- `load-osm-network` — produces the projected network georeferencing needs
- `analyze-simulation-outputs` — establishing the numeric ground truth before mapping
- [[spatial-congestion-heatmap-with-plot-net-dump]], [[sumo-output-files]], [[openstreetmap]],
  [[kinematic-wave-theory-validity-across-car-following-models]]
