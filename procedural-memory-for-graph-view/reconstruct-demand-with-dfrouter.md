---
name: reconstruct-demand-with-dfrouter
description: Use this skill when the user wants to reconstruct SUMO traffic demand (routes and flows) directly from induction-loop detector measurements on a highway-type network — SUMO's dfrouter tool — as opposed to an OD matrix (od2trips), turning ratios (jtrrouter), random sampling (randomTrips), or a candidate-route pool matched to counts (routeSampler). Covers building an unambiguous junction-free network for detector classification, dfrouter's real input file formats (detectorDefinition XML, minutes-based measurement CSV), its source/sink/in-between detector classification, running dfrouter itself, and validating the reconstructed demand against ground truth via the GEH statistic. Trigger on mentions of dfrouter, detector-based demand reconstruction, reconstructing routes from loop-detector counts, or induction-loop-derived traffic demand.
related_skills:
  - calibrate-demand-with-routesampler
  - implement-alinea-ramp-metering
  - build-macroscopic-fundamental-diagram
related_skills_for_graph_view:
  - "[[calibrate-demand-with-routesampler]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[build-macroscopic-fundamental-diagram]]"
related_pages:
  - "[[geh-statistic]]"
  - "[[dfrouter-detector-based-demand-reconstruction]]"
---

# Reconstruct Demand with dfrouter

`dfrouter` ($SUMO_HOME/bin/dfrouter — a compiled binary, not a Python script like `duarouter`/`jtrrouter`/`marouter`) reconstructs vehicle routes and flows purely from induction-loop (E1) detector measurements on a highway-type network. It classifies every detector as a **source** (traffic enters here, no detectorized predecessor), **sink** (traffic exits here, no detectorized successor), or **between** (detectorized both up- and downstream), then synthesizes routes and per-detector emission flows that reproduce the measured counts.

## Network design: junction-free and single-lane for unambiguous classification

`dfrouter` works best — and this skill's verified network uses — a highway topology with **no cross-traffic intersections**, only simple priority merge (on-ramp) and diverge (off-ramp) nodes. **Use a single lane per edge** so every entry/exit point maps to exactly one detector with an unambiguous split — a multi-lane highway would need per-lane detector coverage and lane-level classification, adding complexity without changing the core mechanic. Every mainline segment between ramps, plus every ramp itself, needs its own E1 detector for `dfrouter` to correctly classify the network's topology from the measurement data alone.

## Real input file formats

**Detector-definition file** — element is `<detectorDefinition>`, NOT `<detector>`, and takes no `type` attribute on input (classification is dfrouter's *output*, not something you specify):

```xml
<detectors>
    <detectorDefinition id="det_m0" lane="m0_0" pos="400"/>
    <detectorDefinition id="det_on1" lane="on1_0" pos="30"/>
    ...
</detectors>
```

**Measurement file** — semicolon-separated, and **`Time` is in MINUTES, not seconds**:

```
Detector;Time;qPKW;qLKW;vPKW;vLKW
det_m0;0;7;0;95.4;0
det_m0;1;8;0;94.1;0
...
```
(`qPKW`/`qLKW` = passenger/heavy-vehicle counts in that minute; `vPKW`/`vLKW` = mean speed in km/h.) See `scripts/make_dfrouter_inputs.py` for converting raw E1 XML interval output (seconds-based `begin`, m/s speed) into this format.

## Running dfrouter

```bash
dfrouter --net-file hw.net.xml --detector-files detectors.det.xml --measure-files flows.txt \
    --routes-output df_routes.xml --emitters-output df_emitters.xml --detector-output df_dettype.xml \
    --highway-mode
```

Produces three outputs: the classified-detector file (`df_dettype.xml`, each detector tagged `type="source"/"sink"/"between"`), a routes file, and an emitters/flow file containing individual `<vehicle>` elements with a `departPos` at the source detector and route-distribution references reflecting the measured diverge splits.

**Load order matters for the validation run**: `df_routes.xml` must be loaded as an `--additional-files` entry alongside `df_emitters.xml` (both before any detector additional-file) — the emitters' `routeDistribution` references only resolve once the routes additional is already loaded. Loading routes via `--route-files` instead does not work.

## Verifying classification against network geometry

Cross-check `df_dettype.xml`'s classification directly against your network's actual topology before trusting it: every detector with no detectorized predecessor (mainline entry, every on-ramp) should classify `source`; every detector with no detectorized successor (mainline exit, every off-ramp) should classify `sink`; everything else should classify `between`.

## Validating the reconstruction: GEH, not just eyeballing

Run a fresh simulation driven by `df_routes.xml`+`df_emitters.xml` with the **same E1 detectors** as the ground-truth run, then compare measured vs. realized per-detector counts via the GEH statistic (see [[geh-statistic]]; target GEH < 5 per detector). See `scripts/compare_geh.py` for computing per-detector and aggregate GEH directly from the two raw E1 XML outputs, plus off-ramp split-fidelity reporting.

**Critical gotcha (a real near-miss from this skill's own verification): the ground-truth and validation runs' detector additional-files must define every detector at the identical lane/pos.** A detector moved in one file but not regenerated in the other silently invalidates the "same detectors in place" comparison without erroring — the run will complete and produce plausible-looking numbers regardless. Diff the two `.add.xml` files (or generate both from one shared source) before trusting a GEH comparison.

## Verified finding: dfrouter cannot recover a true OD matrix from point counts alone

**dfrouter applies the same downstream route-split distribution to every source reaching a given diverge point, even when those sources are physically distinct.** Verified directly: two distinct sources (a mainline entry and an on-ramp entry, both upstream of the same off-ramp) received byte-for-byte identical `routeDistribution` probability sets in dfrouter's own output. Per-link flows reconstruct essentially exactly (GEH well under 1 in a verified test), but the underlying per-origin-destination matrix is redistributed uniformly across origins — this is an inherent limitation of point-count-based demand estimation (an aggregate flow-matching solution, not a true OD inverse), not a `dfrouter` defect. Don't treat `dfrouter` output as a real per-OD demand matrix; treat it as a link-flow-consistent aggregate.

## Gotchas

- **`dfrouter` is a compiled binary** ($SUMO_HOME/bin), not a `tools/` Python script — check `dfrouter --help` directly rather than assuming syntax from the other router tools.
- **Measurement file `Time` is in minutes, not seconds** — a raw E1 XML's `begin` (seconds) must be divided by 60.
- **Input element is `<detectorDefinition>` with no `type` attribute** — classification is output-only, found in `df_dettype.xml`.
- **`df_routes.xml` and `df_emitters.xml` must load together as additionals, before any detector additional** — not via `--route-files`.
- **Ground-truth and validation detector files must define identical lane/pos for every detector id** — verify this explicitly; a silent mismatch doesn't error, it just quietly invalidates the comparison.
- **dfrouter's reconstructed splits are uniform across origins at a shared diverge point** — don't mistake its output for a genuine per-OD matrix.

## Related

- `calibrate-demand-with-routesampler`, [[geh-statistic]] — the closest structural precedent (validating reconstructed/calibrated demand against observed counts via GEH), for a different demand-calibration mechanism (route-pool scaling vs. this skill's flow reconstruction).
- `implement-alinea-ramp-metering` — the hand-authored motorway plain-XML + on-ramp geometry pattern this skill's network construction reuses.
- `build-macroscopic-fundamental-diagram` — E1 induction-loop detector definition/interpretation as a standalone measurement instrument.
- [[dfrouter-detector-based-demand-reconstruction]] — the underlying `dfrouter` mechanics, format gotchas, and the verified OD-non-identifiability finding.
