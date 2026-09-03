---
name: compare-one-way-vs-two-way-street-grid-conversion
description: Use this skill when the user wants to compare a one-way-pair street conversion against a two-way baseline in SUMO — measuring whether one-way conversion improves or degrades network performance, and at what demand level the answer changes. Covers hand-authoring one-way-pair grid networks (netgenerate cannot express asymmetric one-way lane allocation), a fair-comparison lane-count control versus a deliberately unfair naive conversion, route-circuity decomposition into through-trip vs. local-access components, signal-coordination bandwidth analysis for one-way vs. two-way arterials, and two SUMO implementation gotchas (tlLogic offset sign convention, FCD edge-filter file format). Trigger on mentions of one-way street conversion, one-way pair, grid topology comparison, or arterial progression bandwidth.
related_skills:
  - create-grid-network
  - create-single-intersection
  - optimize-signals-by-tlscoordinator
  - compute-dynamic-user-equilibrium
  - quantify-sumo-run-to-run-variability
  - analyze-intersection-safety-with-ssm
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[create-single-intersection]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
related_pages:
  - "[[one-way-vs-two-way-grid-performance-crossover]]"
---

# Compare One-Way vs. Two-Way Street Grid Conversion

Measures whether converting a two-way street grid to alternating one-way pairs improves or degrades network performance in SUMO, as a function of demand level — the first skill in memory to treat street-system-level topology (as opposed to a single junction's geometry, or a signal-control policy) as the treatment variable.

## Building the variants: hand-author, don't use netgenerate directly

`netgenerate --grid` produces symmetric bidirectional edges and cannot express an asymmetric one-way-pair lane allocation. Hand-author `.nod.xml`/`.edg.xml` (and a `.netccfg`) for all variants instead, following the `create-single-intersection`/plain-XML pattern scaled to a full grid.

## The fair-comparison control is the single most consequential design decision

Build **three** variants, not two:
1. **Two-way baseline** — standard bidirectional streets.
2. **Fair one-way** — alternating one-way pairs, with total lane-km held **exactly equal** to the two-way baseline (a one-way street carries all its lanes in one direction, so it needs more lanes per direction than a two-way street's per-direction count to match total capacity).
3. **Naive one-way** — a deliberately unfair conversion that simply drops the "wrong-direction" lanes, roughly halving total capacity.

**Verify the lane-km equality directly from the compiled network files** (sum lane length × lane count across all edges), not from a design intention — this is exactly the kind of claim worth computing and checking, not asserting. **The naive variant's outcome demonstrates why the control matters**: verified in one test, the naive (halved-capacity) conversion collapsed into gridlock at a demand level where the fair conversion performed well — using the naive variant's result alone would have produced a starkly different, misleading conclusion about one-way conversion in general. Report both, explicitly contrasting them, rather than only reporting the fair comparison.

**Verify one-way enforcement genuinely holds** in the compiled network (zero bidirectional segments where one-way is intended, and the specific "wrong-direction" edges from the two-way variant are structurally absent) — don't just trust the source XML matches intent.

## Route circuity: decompose it, don't report one number

Measure the ratio of driven route distance between the one-way and two-way variants for identical origin-destination demand, but **decompose it into through-trip and local-access components** rather than reporting one aggregate figure:

- **Through-trips** (traversing the full grid corner-to-corner) can have circuity **exactly 1.0** under an alternating one-way pattern — a Manhattan-grid path length is invariant to which streets carry which direction, as long as a valid path of the same total length exists in both directions somewhere in the grid.
- **Local-access trips** (shorter, more localized origin-destination pairs) bear the entire circuity penalty — a locally-desired direct path may simply not exist one-way, forcing a real detour.

**Verified finding**: in one test, through-trip circuity was essentially exactly 1.0 (matching to five decimal places), while local-access circuity carried a real ~20% penalty, yielding an aggregate ~9% overall penalty once the demand mix (through vs. local) was accounted for. Reporting only the aggregate number obscures that the penalty is concentrated entirely in one trip type — decompose it.

## Signal coordination: reconcile the geometric and simulated pictures

After giving both variants the same uniform cycle length (a prerequisite for `tlsCoordinator`, see that skill), compute both a **geometric** progression bandwidth (from signal offsets, cycle length, and travel-time-between-signals — see `scripts/bandwidth.py`) and a **simulated** stops/delay result from actually running the coordinated network.

**Verified finding these two pictures can look inconsistent until reconciled properly**: the network-wide theoretical bandwidth total can come out essentially equal between one-way and two-way variants (both able to progress two of the four directional flows independently), while the simulated stops/delay result strongly favors one-way — because the constraint bites **per-street**, not network-wide: on a given two-way street, one direction gets a real green-wave band while the other gets essentially zero, whereas a one-way street's entire capacity serves one direction's progression exclusively. Look at both the aggregate and the per-street/per-direction breakdown before concluding the two topologies are "equally good" or "equally bad" at progression.

**Don't assume the textbook "two-way sacrifices one direction" story without checking.** In one verified test, `tlsCoordinator`'s computed offsets did *not* produce one favored and one sacrificed direction on the two-way arterial — instead, both directions landed at a similar, moderately-degraded stops/delay level (a symmetric compromise), with the directional difference statistically indistinguishable from zero. The real bandwidth penalty was still there, just distributed differently than the classic textbook framing suggests. Compute the actual per-direction paired difference (not a folded/absolute-value statistic, which distorts the confidence interval) before asserting an asymmetry does or doesn't exist.

## Testing robustness under live rerouting

If a rerouting device or reactive route-choice mechanism is part of the scenario, test whether the demand-crossover point shifts substantially when it's enabled versus a purely static-route comparison. **A large shift is a genuine finding worth flagging as an open question, not smoothing over** — it may reflect real behavioral adaptation, or it may reflect reactive-rerouting instability rather than a stable equilibrium; disclose which interpretation is better supported (or that it's unresolved) rather than picking one.

## Gotchas

- **`netgenerate --grid` cannot express asymmetric one-way lane allocation** — hand-author plain XML for any one-way-pair topology.
- **A "naive" halved-capacity one-way conversion can produce a starkly different, misleading conclusion** compared to a fair equal-lane-km conversion — always build and report both, don't assume the naive version is a reasonable simplification.
- **Verify lane-km equality and one-way enforcement directly from the compiled network**, not from source-XML intent alone.
- **Route circuity should be decomposed by trip type (through vs. local-access)**, not reported as one aggregate number — the penalty is typically concentrated entirely in local-access trips, with through-trip circuity potentially exactly 1.0 in a regular grid.
- **A network-wide geometric bandwidth calculation can look misleadingly similar between two topologies** while the per-street/per-direction breakdown reveals the real, asymmetric constraint — check both levels.
- **Don't assume `tlsCoordinator` sacrifices one direction on a two-way street** — verify the actual per-direction outcome; it may produce a symmetric compromise instead, and computing the directional difference as a folded (absolute-value) statistic rather than a direct paired difference will distort the resulting confidence interval.
- **SUMO's `tlLogic` offset semantics are `(t - offset) mod cycle`, not `(t + offset) mod cycle`** — verified directly against TraCI (an offset of 122.2s on a 90s cycle put green onset at t=78s, matching the subtraction form). Getting this sign backwards silently produces zero computed progression bandwidth and mis-placed green bands on every time-space diagram — verify the sign against actual TraCI-observed green-onset timing before trusting any bandwidth/offset calculation.
- **`--fcd-output.filter-edges.input-file` requires a netedit *selection* file format** (`edge:<ID>` per line), not an `<edgeData edges="..."/>`-style additional file — passing the wrong format is accepted with **no error or warning** and silently discards most or all of the intended output (verified: an 8-edge filter in the wrong format silently dropped 2 of 8 edges; a single-edge filter in the wrong format produced zero output records). Always verify the resulting FCD output actually contains the expected edges/vehicle count before trusting a filtered FCD analysis.

## Related

- `create-grid-network` / `create-single-intersection` — the network-building techniques (netgenerate for the two-way baseline shape, plain-XML hand-authoring for the one-way variants) this skill's networks are built from.
- `optimize-signals-by-tlscoordinator` — the offset-coordination tool this skill applies to both topologies; the uniform-cycle-length prerequisite and singular `-r` flag apply identically here.
- `compute-dynamic-user-equilibrium` — relevant if route assignment needs to be genuinely re-optimized per variant (direct paths are illegal in a one-way network, so routes must adapt) rather than using a fixed/abstract demand resolved independently per network.
- `quantify-sumo-run-to-run-variability` — the replication/CRN methodology this skill's demand sweep applies.
- `analyze-intersection-safety-with-ssm` — used for this skill's surrogate-safety comparison; the mixed result (fewer crossing conflicts, more rear-end/merging conflicts) is a reminder not to assume fewer intersection conflict points automatically means safer overall.
- [[one-way-vs-two-way-grid-performance-crossover]] — the verified crossover, circuity-decomposition, coordination-bandwidth, and mixed-safety findings.
- `evaluate-neighborhood-traffic-calming-and-cut-through-displacement` — reuses this skill's hand-authored one-way-cell construction and naive-vs-fair conversion distinction as one of six traffic-calming intervention variants, and its through-vs-local-access circuity decomposition as the model for that skill's resident-vs-through-traffic equity metric.
- `design-arterial-signal-progression-and-verify-bandwidth` — generalizes this skill's `bandwidth.py`/`timespace.py` scripts into an exact interval-algebra two-way bandwidth calculator with resonance/lead-lag/dispersion/spillback analysis, and reuses the FCD edge-filter-file-format gotcha this skill documents.
