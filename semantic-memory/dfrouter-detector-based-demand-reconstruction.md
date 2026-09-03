---
summary: dfrouter reconstructs SUMO routes and flows purely from induction-loop detector measurements, classifying each detector as source/sink/between from network topology; its real input formats (detectorDefinition XML, minutes-based measurement CSV) differ from SUMO's other router tools, and it cannot recover a true OD matrix — verified to apply the same downstream route split uniformly across every origin reaching a shared diverge point, an inherent limitation of point-count-based demand estimation.
keywords:
  - dfrouter
  - detector-based-routing
  - source-sink-classification
  - demand-reconstruction
  - OD-non-identifiability
  - induction-loop
created: 2026-07-28T09:20:00
last_updated: 2026-08-05T00:00:00
sources:
  - "[[episodic-memory/2026-07-28_08-56-54/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_08-56-54/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/dfrouter.html
related_pages:
  - "[[geh-statistic]]"
  - "[[routesampler]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[od-matrix-estimation-and-underdetermination]]"
  - "[[field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap]]"
related_skills:
  - reconstruct-demand-with-dfrouter
  - calibrate-demand-with-routesampler
  - implement-alinea-ramp-metering
related_skills_for_graph_view:
  - "[[reconstruct-demand-with-dfrouter]]"
  - "[[calibrate-demand-with-routesampler]]"
  - "[[implement-alinea-ramp-metering]]"
---

# dfrouter: Detector-Based Demand Reconstruction

`dfrouter` is a compiled SUMO binary (`$SUMO_HOME/bin/dfrouter`, unlike the Python-script router tools `duarouter`/`jtrrouter`/`marouter`) that reconstructs vehicle routes and flows purely from induction-loop (E1) detector measurements on a highway-type network — no OD matrix, turning ratios, or candidate route pool required, only detector counts and the network's own geometry.

## Detector classification is derived from topology, not specified

`dfrouter` classifies every detector as **source** (no detectorized predecessor — a genuine network entry, whether the mainline start or an on-ramp), **sink** (no detectorized successor — mainline end or an off-ramp), or **between** (detectorized on both sides). This classification is entirely an *output*, written to the `--detector-output` file — the input `<detectorDefinition>` element takes no `type` attribute. For an unambiguous classification, use a network with no cross-traffic intersections (simple priority merge/diverge nodes only) and one detector per lane per entry/exit — a single-lane highway makes this trivial since each entry/exit has exactly one associated detector.

## Real input formats differ from other SUMO router tools

- **Detector-definition file**: `<detectorDefinition id=".." lane=".." pos=".."/>`, not `<detector>`.
- **Measurement file**: semicolon-separated CSV, header `Detector;Time;qPKW;qLKW;vPKW;vLKW` — **`Time` is in minutes, not seconds** (a raw E1 XML's `begin` attribute, which is in seconds, must be divided by 60). `qPKW`/`qLKW` are passenger/heavy-vehicle counts for that minute; `vPKW`/`vLKW` are mean speeds in km/h.

## Output load-order requirement

`dfrouter`'s two key outputs — `--routes-output` and `--emitters-output` — must both be loaded as `--additional-files` in a subsequent validation run, **with routes loading before or alongside emitters**, not via `--route-files`. The emitters file's `<vehicle>` elements reference `routeDistribution` ids that only resolve once the routes additional-file is already loaded into the same run.

## Verified finding: dfrouter cannot recover a true origin-destination matrix

**`dfrouter` applies the identical downstream route-split distribution to every distinct source that reaches a shared diverge point.** Verified directly on a network with a mainline entry and an on-ramp both feeding the same downstream off-ramp: both sources' `routeDistribution` blocks in `dfrouter`'s emitters output were byte-for-byte identical probability sets, despite representing physically distinct origins. Per-link flow reconstruction can nonetheless be extremely accurate (GEH well under 1 across all detectors in a verified test, aggregate GEH 0.09) — because link flows are exactly what detector counts constrain — but the underlying per-origin-destination matrix `dfrouter` implicitly assumes is redistributed uniformly across origins sharing a diverge point. This is a structural consequence of estimating demand from point counts alone (an aggregate flow-matching solution, not a genuine OD inverse), not a defect specific to this tool. Treat `dfrouter` output as link-flow-consistent, not as a recovered true OD matrix. [[od-matrix-estimation-and-underdetermination]] makes this same limitation precise for the zone-based case: even with an explicit TAZ structure and a seed matrix to regularize against, a controlled experiment found most of a matrix's degrees of freedom remain structurally invisible to link counts alone, so a perfect count fit still leaves the bulk of OD-level error unresolved.

## Validation methodology and a real near-miss to guard against

Validate reconstructed demand by running a fresh simulation from `dfrouter`'s output with the same E1 detectors as the original ground-truth run, then compute per-detector and aggregate GEH between measured and realized counts (target GEH < 5; see [[geh-statistic]]).

**A genuine near-miss surfaced during verification of this technique**: the ground-truth run's detector additional-file and the validation run's detector additional-file must define every detector at the identical lane and position. In one verified attempt, a ramp detector was repositioned in the ground-truth/dfrouter-input detector file partway through (to fix an unrelated insertion-collision issue) but the validation run's separate detector additional-file was never regenerated to match — a silent inconsistency that would invalidate the "same detectors in place" comparison without erroring, caught only by an independent line-by-line file diff. Numeric impact was negligible in that specific case, but this is exactly the kind of quiet methodology drift that undermines a validation's credibility if not explicitly checked. Generate both detector additional-files from one shared source (or diff them) rather than hand-maintaining two copies.

See the `reconstruct-demand-with-dfrouter` skill for the full network-design, input-conversion, execution, and validation workflow.
