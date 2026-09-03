---
name: build-diamond-interchange-with-signal-offset-spillback
description: Use this skill when the user wants to model a grade-separated freeway interchange (e.g. a diamond interchange) in SUMO with two closely-spaced signalized ramp-terminal intersections, and study how the OFFSET between those two signals governs whether the short internal arterial link between them spills back and blocks the upstream terminal — as opposed to arterial green-wave coordination (optimize-signals-by-tlscoordinator) between widely-spaced signals with ample link storage. Covers grade-separated network authoring (z-coordinates plus no shared node at the crossing point, verified from the compiled net's connection list), building both ramp terminals as genuine tlLogic-controlled signals with a short internal link, E2-based spillback instrumentation, and the discipline of reconciling a metric's aggregation definition consistently across every document that reports it. Trigger on mentions of diamond interchange, ramp terminal, internal link spillback, closely-spaced signals, or grade-separated interchange.
related_skills:
  - optimize-signals-by-tlscoordinator
  - compare-unsignalized-intersection-control-types
  - create-single-intersection
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[compare-unsignalized-intersection-control-types]]"
  - "[[create-single-intersection]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
related_pages:
  - "[[diamond-interchange-signal-offset-and-spillback]]"
---

# Build Diamond Interchange with Signal-Offset Spillback

Models a grade-separated freeway interchange (a conventional diamond interchange: freeway passing under/over an arterial, with off- and on-ramps terminating at two closely-spaced signalized intersections on the arterial) to study how the offset between the two ramp-terminal signals governs spillback on the short internal arterial link between them — a distinct coordination problem from arterial green-wave coordination between widely-spaced signals with generous link storage (see `optimize-signals-by-tlscoordinator`).

## Grade-separated network authoring

Give the freeway and arterial genuinely distinct `z`-coordinates, and ensure **no shared node exists at their crossing point** — the freeway and arterial only connect via ramp edges at the two terminal junctions, never directly:

```xml
<!-- Arterial at z=6, freeway at z=0, no shared crossing node -->
<node id="W" x="-55" y="0" z="6.0" type="traffic_light"/>  <!-- west ramp terminal -->
<node id="E" x="55"  y="0" z="6.0" type="traffic_light"/>  <!-- east ramp terminal -->
<node id="ff_s" x="0" y="-150" z="0.0" type="priority"/>   <!-- freeway junction, well clear of the arterial -->
```

**Verify grade separation from the compiled net's connection list, not just the absence of a junction** — confirm zero `<connection>` elements link any freeway-mainline edge directly to any arterial edge; every freeway↔arterial interaction must route through a ramp edge.

## Two closely-spaced signalized terminals, one short internal link

Both ramp terminals are genuine `type="traffic_light"` junctions with their own `tlLogic`, spaced close enough (e.g. ~110m) that the arterial link between them has very limited vehicle storage (verify the compiled internal link's actual length). Give each terminal dedicated left-turn connections for ramp-to-arterial and arterial-to-on-ramp movements (see `scripts/example_diamond.con.xml` for a full worked 2-terminal, 4-ramp example).

## Isolating offset as the sole causal variable

Build two (or more) scenarios using the identical cycle length and phase structure at both terminals, varying **only** one terminal's offset — a well-coordinated offset (tuned so the internal-link platoon discharges before it can fill the short internal storage) versus a poorly-coordinated one (e.g. roughly half a cycle off). Keep demand and seed identical across scenarios so any difference is attributable purely to signal timing.

## Instrumenting for spillback: E2 detector spanning the full internal link

Place an E2 lane-area detector covering the *entire* internal link's length so occupancy and jam length are directly observable building up toward the upstream terminal — this is the core evidence for spillback, not an inference from aggregate delay alone.

## Reconcile a metric's definition across every document that reports it

**If a metric (e.g. "spillback fraction") can be computed multiple valid ways — per-lane samples vs. worst-of-both-lanes-per-timestep — pick ONE authoritative definition and cite it identically, with an unambiguous label, in every document that reports it** (comparison table, findings summary, analysis script comments). Verified failure mode: a narrative citing one definition and a shipped CSV citing another for an identically-named metric reads as an inconsistency even when both numbers are individually correct — this is a real, avoidable defect, not a stylistic nicety. For a spillback fraction specifically, "worst-of-both-lanes-per-timestep" is the more physically meaningful choice, since a queue filling *either* lane of a two-lane internal link is sufficient to block the upstream junction.

## Verified findings

On a real diamond interchange with a ~100m internal link: a well-coordinated offset kept the link's occupancy around 30% with near-full-jam conditions about a quarter of the time, while a poorly-coordinated offset (half a cycle off) raised occupancy to over 40% with near-full-jam conditions nearly half the time — a genuine, substantially more frequent spillback condition. This translated into measurable throughput and delay costs: dozens of fewer vehicles served, some vehicles never even inserted due to upstream congestion, and roughly a 28% increase in mean intersection delay — all attributable purely to the offset, since demand, seed, and cycle length were held identical.

## Gotchas

- **Grade separation must be verified from the compiled net's connections**, not assumed from distinct z-coordinates or the absence of an explicit shared junction alone.
- **A metric with multiple valid aggregation definitions must be reconciled to one, clearly labeled, and cited identically everywhere** — an unreconciled discrepancy between a narrative and a shipped table looks like a correctness bug even if both numbers are individually valid.
- **Every deliverable explicitly listed in a task must be materialized as an actual file** — embedding a "findings summary" only inside an agent's own output JSON does not satisfy a requirement for a standalone findings file.
- **Use `loaded`/`inserted`/`arrived` (not just `inserted`/`arrived`)** for genuine throughput/failure measurement, per the lesson established in `compare-unsignalized-intersection-control-types` — a mode that appears to have zero incomplete trips can still be refusing to insert vehicles at a jammed source.

## Related

- `optimize-signals-by-tlscoordinator` — the underlying offset-coordination mechanic, here applied to a tighter, spillback-critical short-link case rather than a widely-spaced arterial green wave.
- `compare-unsignalized-intersection-control-types` — the compiled-net-verification and loaded/inserted/arrived throughput-measurement lessons this skill directly reuses.
- `create-single-intersection` — general single-junction plain-XML authoring background.
- [[diamond-interchange-signal-offset-and-spillback]] — the underlying grade-separation and spillback mechanics, and the verified findings.
- `design-arterial-signal-progression-and-verify-bandwidth` — reuses this skill's offset-sign-convention verification and spillback-instrumentation methodology (E2 detector spanning a full link) at arterial scale, finding that a green wave's own platooning mechanism can deliver a compact burst into limited downstream storage and reverse coordination's benefit at a measurable demand threshold.
