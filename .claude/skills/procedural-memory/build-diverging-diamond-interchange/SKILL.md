---
name: build-diverging-diamond-interchange
description: Use this skill when the user wants to model a DIVERGING DIAMOND INTERCHANGE (DDI) in SUMO — the unconventional grade-separated interchange where the two directions of the surface arterial cross over between two ramp-terminal signals so that arterial-to-freeway left turns become geometrically unopposed — and/or compare it against a conventional diamond interchange baseline, as an extension of build-diamond-interchange-with-signal-offset-spillback. Covers authoring two interchange designs that share identical node/connection topology but differ only in the crossover edges' geometry, verifying the resulting unopposed-vs-opposed left-turn foe matrix directly from the compiled net, the resulting signal-phase-count reduction, and the completed-vs-still-running trip-counting discipline required for a genuine throughput comparison. Trigger on mentions of diverging diamond interchange, DDI, crossover interchange, or unopposed left turn.
---

# Build Diverging Diamond Interchange

Models a Diverging Diamond Interchange (DDI) — where the arterial's two directions cross over between two closely-spaced ramp-terminal signals, making arterial-to-freeway left turns geometrically unopposed — against a conventional diamond interchange baseline. Extends `build-diamond-interchange-with-signal-offset-spillback`'s grade-separated dual-terminal construction with crossover geometry.

## Sharing topology, varying only the crossover geometry

**Author both designs with identical nodes, ramps, freeway, and connection list — the only difference between DDI and conventional should be the shape (side) of the two internal arterial edges between the terminals.** This isolates the crossover as the sole causal variable:

```xml
<!-- DDI: internal edges swap sides between terminals -->
<edge id="I_EB" from="W" to="E" shape="-55,0 -45,6.0 45,6.0 55,0" .../>
<edge id="I_WB" from="E" to="W" shape="55,0 45,-6.0 -45,-6.0 -55,0" .../>

<!-- Conventional: same edges, shape NOT crossed -->
<edge id="I_EB" from="W" to="E" shape="-55,0 -45,-6.0 45,-6.0 55,0" .../>
<edge id="I_WB" from="E" to="W" shape="55,0 45,6.0 -45,6.0 -55,0" .../>
```

Because the edges swap sides in one design but not the other, the *same* left-turn connection at each terminal ends up crossing the opposing through movement in the conventional design but not in the DDI — netconvert computes genuinely different compiled foe matrices from this geometry difference alone, with the connection list itself unchanged.

## Verifying the unopposed-left signature from the compiled net

**Don't trust the crossover geometry's visual appearance — verify unopposed lefts directly from the compiled net's `<request response=".." foes=".."/>` bitstrings**, per the discipline established in `compare-unsignalized-intersection-control-types`. Identify each terminal's arterial-to-on-ramp left-turn link index, then check whether the opposing arterial-through link's index appears in that left turn's foe set:

- **DDI**: the left-turn link's foe set should NOT include the opposing-through link — genuinely unopposed.
- **Conventional**: the equivalent left-turn link's foe set SHOULD include the opposing-through link — genuinely opposed, requiring protection.

## Signal design: fewer phases for the DDI

Because DDI lefts are unopposed, each terminal needs only a simple two-phase signal (each arterial direction gets a phase, no protected-left interval needed) — versus a conventional diamond's typical three-phase plan (through, protected left, and off-ramp/side movements). Use the programmatic tlLogic state-string generation technique from `compare-left-turn-signal-treatments` (keyed on each net's own link-index mapping) to avoid G/g/r case-drift bugs when authoring the two different phase plans, and keep the cycle length identical across both designs so the comparison isolates geometry, not signal timing.

## Genuine throughput comparison requires filtering completed vs. still-running trips

**If your simulation uses `--tripinfo-output.write-unfinished true` (to preserve data for vehicles still in the network at the cutoff), every vehicle produces a `<tripinfo>` record — including ones that never actually arrived, marked `arrival="-1.00"`.** Counting every record as "arrived" without checking this attribute silently inflates completion figures and can hide a real, meaningfully different completion-rate gap between two scenarios. Always filter: `arrival >= 0` means genuinely completed; `arrival == -1` means still running/incomplete at the simulation cutoff. Report both counts separately, for the overall population and any specific movement of interest (e.g. heavy left-turn demand).

## Verified findings

On a real DDI-vs-conventional comparison under identical heavy left-turn demand: the DDI's left turns were genuinely unopposed in the compiled foe matrix (conventional's genuinely opposed), the DDI ran a 2-phase signal versus the conventional's 3-phase plan at the same cycle length, and the DDI achieved roughly an 80% reduction in heavy-left-turn delay alongside a substantially higher completed left-turn throughput (92% vs. 67% of heavy-left demand actually completing within the simulation window) — a case where correctly filtering completed-vs-still-running trips revealed an even larger DDI advantage than an initial naive "arrived count" comparison suggested.

## Gotchas

- **Vary only the crossover edges' geometry between the two designs** — keep everything else (nodes, connections, lane counts, terminal spacing) identical so the comparison isolates the crossover as the sole causal variable.
- **Verify unopposed/opposed lefts from the compiled net's foe bitstrings directly** — don't assume the crossover geometry produces the intended conflict structure just because it looks right visually.
- **`--tripinfo-output.write-unfinished true` produces records for vehicles that never arrived** (`arrival="-1.00"`) — always filter on this attribute before computing completion/throughput figures, or risk a silently inflated or falsely-tied result.
- **Diagnose an initial-demand gridlock's true cause before assuming the signals are the bottleneck** — a shared upstream merge (e.g. an on-ramp acceleration lane) can be the actual binding constraint in both designs equally, masking the signal-level comparison you actually want to make.

## Related

- `build-diamond-interchange-with-signal-offset-spillback` — the grade-separated, dual-signalized-terminal construction pattern this skill directly extends.
- `compare-left-turn-signal-treatments` — the programmatic tlLogic state-string generation technique and left-turn-specific delay extraction methodology.
- `compare-unsignalized-intersection-control-types` — the compiled-net foe/response-matrix verification discipline this skill's core novel claim relies on.
- [[diverging-diamond-interchange-unopposed-lefts]] — the underlying unopposed-left mechanics and the verified delay/throughput findings.
- `design-restricted-crossing-uturn-and-michigan-left-intersections` — reuses this skill's shared-topology-vary-one-thing pattern and compiled-net foe-matrix verification for an at-grade (rather than grade-separated) alternative intersection family.
