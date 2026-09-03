---
summary: tlsCycleAdaptation.py resizes each intersection's cycle length and green-phase splits independently using Webster's equation applied to one hour of routed demand, producing a static fixed-time signal plan.
keywords:
  - tlsCycleAdaptation
  - Webster-method
  - cycle-length
  - green-split
  - critical-flow
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T16:11:52
sources:
  - "[[raw-materials/tls - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/Tools/tls.html
  - "[[raw-materials/sumotoolstlsCycleAdaptation.py at main.md]]"
  - https://github.com/eclipse-sumo/sumo/blob/main/tools/tlsCycleAdaptation.py
related_pages:
  - "[[tlscoordinator]]"
  - "[[duarouter]]"
  - "[[sumo-command-line]]"
  - "[[actuated-traffic-signals]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - control-signals-with-actuated-tls
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
---

# tlsCycleAdaptation

`tlsCycleAdaptation.py` (in `$SUMO_HOME/tools/`) computes optimized cycle lengths and green-phase durations for every signalized intersection in a network, applying **Webster's equation** independently per intersection against one hour of the given demand. This differs from [[tlscoordinator]], which doesn't touch cycle timing at all but instead synchronizes already-timed intersections' start offsets.

## Required input: routed vehicles, not trips or flows

The script needs a route file of `<vehicle>` elements with `<route>` children — not `<trip>`/`<flow>` elements — and silently skips `depart="triggered"` vehicles. Output from `randomTrips.py` or `od2trips` generally isn't sufficient directly; route it with [[duarouter]] first.

## Usage

```bash
python tlsCycleAdaptation.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml
python tlsCycleAdaptation.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml -b 3600 --unified-cycle
```

`-r`/`--route-files` accepts a **comma-separated list** (unlike `tlsCoordinator.py`'s single-file `-r`/`--route-file`).

## Choosing `--begin`

The calculation only ever looks at one hour of demand starting at `-b`/`--begin`. If omitted, it defaults to the first vehicle's departure time — rarely the actual peak. If the route file spans less than an hour, flows are scaled up proportionally; if it spans more and no `--begin` is given, the script tries to auto-detect the busiest hour, but explicit is safer for unusual demand shapes.

## Key options

- `-e`/`--existing-cycle`: keep each intersection's current cycle length, only re-split green times
- `-u`/`--unified-cycle`: use the largest computed cycle length for **every** intersection — the prerequisite step before [[tlscoordinator]]
- `-R`/`--restrict-cyclelength`: hard-cap the cycle at `--max-cycle` even if minimum green times would push it over
- `--min-cycle`/`--max-cycle`: bounds on computed cycle length (default 20/120 s)
- `-y`/`--yellow-time`, `-a`/`--all-red`, `-l`/`--lost-time`, `-g`/`--min-green`: timing parameters feeding the Webster calculation
- `-H`/`--saturation-headway`: seconds/vehicle used to derive per-lane capacity (default 2 s ≈ 1800 veh/lane/hour) — may be too optimistic for closely-spaced urban intersections
- `--skip <ids>`: leave specific intersections untouched
- `--write-critical-flows`: print the critical flow ratio driving each phase's result

## Interpreting results

If an intersection's summed critical flow ratios reach or exceed 1 (oversaturated), the script falls back to `--max-cycle` as its "optimal" answer and warns — a sign the demand exceeds what any fixed-time plan can serve well there, not a bug in the tool.

## Scope

Optimizes cycle length and green splits per intersection in isolation — no cross-intersection offset coordination (that's [[tlscoordinator]]) — and produces a static plan sized to one hour of demand, not an adaptive controller. For a controller that reacts to real-time traffic instead of a plan computed once from historical demand, see [[actuated-traffic-signals]].
