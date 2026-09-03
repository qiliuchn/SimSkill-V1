---
name: compare-unsignalized-intersection-control-types
description: Use this skill when the user wants to compare SUMO's UNSIGNALIZED intersection junction-control types — right_before_left (uncontrolled yield-to-right), priority (two-way stop control, TWSC), allway_stop (all-way stop, AWSC) — against each other or against a signalized baseline, to find where each control mode saturates and a signal becomes warranted. As opposed to every other signal-control skill in memory, which assumes a traffic light already exists — these are first-class netconvert junction types set on the node, entirely distinct from any tlLogic. Covers building one shared network geometry compiled into multiple junction-type variants (with major-road priority baked into the edge file for the TWSC case), verifying right-of-way from the compiled net's foe/response matrix, the loaded-vs-inserted-vs-arrived distinction for genuine throughput/failure measurement, and — critically — the collinear opposing-left-turn SSM measurement artifact that can silently invalidate a naive safety comparison. Trigger on mentions of unsignalized intersection, two-way stop, TWSC, all-way stop, AWSC, right_before_left, or signal warrant.
---

# Compare Unsignalized Intersection Control Types

Compares SUMO's unsignalized junction-control types (`right_before_left`, `priority`/TWSC, `allway_stop`/AWSC) against each other and against a signalized baseline, completing the HCM intersection-control hierarchy (TWSC → AWSC → signal → roundabout, see `create-roundabout-network`) that every other signal-control skill in memory assumes starts with a traffic light already in place.

## One shared geometry, multiple junction-type variants

Build ONE plain-XML network geometry and compile it into multiple `.net.xml` variants that differ only in the center junction's `type` attribute:

```xml
<node id="center" x="0" y="0" type="right_before_left"/>  <!-- or priority / allway_stop / traffic_light -->
```

**For the TWSC (`priority`) case, bake the major-road-vs-minor-road priority into the shared edge file itself** (`priority="3"` on E-W edges, `priority="1"` on N-S edges) — this is safe to include in every variant's edge file, since `right_before_left`, `allway_stop`, and `traffic_light` all ignore edge priority entirely, only the `priority` junction type consults it. This keeps geometry genuinely identical across every variant while still giving the TWSC variant its major-road right-of-way. See `scripts/build_networks.py` for the full working 4-variant compiler.

## Verify right-of-way from the compiled net, not from your intent

**Don't assume setting edge priority produced the intended yield behavior — read the compiled net's `<request response=".." foes=".."/>` bitstrings and connection `state` characters directly.** For a genuine TWSC: minor-road connections should carry state `m` (minor-street yield), major-road through/right connections should carry state `M` with an all-zero response bitstring (yielding to nobody), and the minor-road connections' response bits should point exactly at the opposing major-road movements. See `scripts/verify_networks.py` for the decoding logic. This directly reuses `create-roundabout-network`'s established lesson: verify right-of-way from the compiled net's actual data, never from the source XML's apparent intent alone.

## Loaded vs. inserted vs. arrived: measuring genuine throughput failure

**`incomplete = inserted − arrived` (only counting vehicles that entered the network but never finished) badly undercounts true failed demand at high congestion** — it misses vehicles that were generated but never even *inserted* because their source edge was too jammed to accept them (visible as `loaded > inserted` in `summary.xml`'s per-step data, already present without extra instrumentation). Verified: this undercount reached 10-12x at the highest demand tier in a real study. Always compute:

```python
never_inserted = loaded - inserted
incomplete_true = loaded - arrived   # the metric that actually answers "how much demand failed?"
```

A control mode's apparent "0 teleports, 0 incomplete" can be an illusion if it's simply refusing to insert vehicles at the source rather than genuinely serving them — check `loaded` vs `inserted` before crediting a mode with superior throughput.

## The collinear opposing-left-turn SSM artifact

**SUMO's SSM device can flag a spurious `type="111"` ("collision") encounter between two opposing left-turning vehicles that occupy the same collinear internal-lane crossing geometry, with `minTTC`/`PET` values of exactly 0.00 or `NA` — a degenerate computation, not a genuine near-miss.** Verified: in a real 32-run comparison, literally every single `type=111` flag across every run traced to this exact artifact (opposing E-left/W-left and opposing N-left/S-left pairs), and blindly counting them as "severe conflicts" produced a completely inverted, non-genuine safety narrative. Always:

1. Classify every flagged conflict by the actual vehicle-movement pair that triggered it (trace vehicle route IDs back to origin/turn).
2. Treat any `type=111` flag with `TTC`/`PET` ≈ 0 or `NA` from a same-axis opposing-left pair as an artifact and exclude it from the safety comparison — don't just count encounter-type codes blindly.
3. Build the genuine safety signal from crossing-type encounters (SSM types 10-17) with a finite, positive TTC below a real severity threshold (e.g. 1.5s), attributed by movement pair (e.g. minor-vs-major perpendicular crossing vs. same-axis permissive-left).

See `scripts/reanalyze_corrected.py` for the full classification and exclusion logic.

## Verified findings

Each unsignalized mode has a distinct delay-crossover demand level: `right_before_left` crosses over to favor a signal earliest (uncontrolled yield-to-right deadlocks under moderate load); TWSC holds out longer; AWSC can remain the lowest-delay mode across the entire tested range, never crossing over. Once the collinear-left-turn SSM artifact is correctly excluded, the genuine safety picture can differ substantially from a naive first pass — in one verified study, AWSC (not TWSC) showed the most genuine minor-major crossing near-misses, and the signal generally (though not universally, at every single demand level) showed the fewest at high demand. Correctly computing `loaded − arrived` revealed that a mode's apparent throughput superiority at high demand can partly reflect vehicles never being inserted rather than genuinely being served.

## Gotchas

- **Don't assume TWSC priority took effect from source XML alone** — verify the compiled net's request/response bitstrings directly.
- **`inserted − arrived` undercounts true failed demand** — always also check `loaded − inserted` (never-inserted vehicles) and use `loaded − arrived` for genuine incomplete-demand figures.
- **SSM `type=111` flags between opposing left-turn movements on collinear geometry can be a pure artifact** (TTC/PET ≈ 0/NA) — classify by movement pair and exclude before building any safety narrative; don't trust an encounter-type code count blindly.
- **Don't silently expand scope beyond what was requested** without disclosing it explicitly in the write-up — an unrequested wider demand sweep is fine if it answers a genuine open question (e.g. "does this mode ever cross over?"), but say so, and make sure verification depth scales with the added volume rather than concentrating defects in the unrequested tail.

## Related

- `create-single-intersection` — the base single-junction network shape this skill's shared geometry builds on.
- `create-roundabout-network` — the established "verify right-of-way from the compiled net, not intent" lesson this skill directly reuses for the TWSC case.
- `analyze-intersection-safety-with-ssm` — general SSM device configuration; this skill adds the collinear-left-turn-artifact-exclusion refinement.
- `analyze-simulation-outputs` — general tripinfo/summary comparison methodology.
- [[unsignalized-vs-signalized-intersection-control]] — the underlying verified delay-crossover, throughput-measurement, and SSM-artifact findings.
- `design-restricted-crossing-uturn-and-michigan-left-intersections` — reuses this skill's compiled-net foe/response-matrix verification and loaded-vs-inserted-vs-arrived discipline to verify banned movements and unsignalized median-U-turn yield relationships; also encounters the same collinear-movement SSM artifact class at a different (collinear-merge) geometry.
- `implement-reservation-based-autonomous-intersection-management` — reuses this skill's compiled-net foe-matrix decoding technique to derive the genuine reservation conflict set for a signal-free controller, extending the "verify right-of-way from the compiled net" discipline to a control paradigm with no signal or static priority rule at all.
