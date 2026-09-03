---
summary: tlsCoordinator.py computes traffic-light offsets so vehicles on common routes hit consecutive green lights (a green wave), by pairing and merging intersections that share travel paths in a routed demand file.
keywords:
  - tlsCoordinator
  - offset-coordination
  - green-wave
  - signal-progression
  - arterial-coordination
created: 2026-07-21T14:00:00
last_updated: 2026-07-23T19:50:37
sources:
  - "[[raw-materials/tls - SUMO Documentation.md]]"
  - https://sumo.dlr.de/docs/Tools/tls.html
  - "[[raw-materials/sumotoolstlsCoordinator.py at main.md]]"
  - https://github.com/eclipse-sumo/sumo/blob/main/tools/tlsCoordinator.py
related_pages:
  - "[[tlscycleadaptation]]"
  - "[[duarouter]]"
  - "[[sumo-command-line]]"
  - "[[actuated-traffic-signals]]"
  - "[[sumo-plotting-tools]]"
  - "[[nema-dual-ring-controller]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - optimize-signals-by-tlscoordinator
  - optimize-signals-by-tlscycleadaptation
  - control-signals-with-actuated-tls
  - visualize-trajectories-and-timeseries
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[control-signals-with-actuated-tls]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
---

# tlsCoordinator

`tlsCoordinator.py` (in `$SUMO_HOME/tools/`) computes traffic-light **offsets** — when each intersection's cycle starts relative to the others — so platoons of vehicles following common routes hit consecutive green lights instead of stopping at every intersection ("green wave"). This optimizes a different axis than [[tlscycleadaptation]]: that tool sizes each intersection's cycle length and green splits in isolation; this one staggers already-timed cycles to work together.

## How it works

For every pair of consecutive signalized intersections that appear together in any route in the given demand file, the script computes the ideal offset between them from travel time and each signal's existing first-green timing, weighted by how many vehicles use that pair and by road priority. Pairs that end up linked — directly, or transitively through shared routes — are merged into a coordinated set with consistent relative offsets; intersections with no common route between them are left untouched regardless of physical proximity.

## Prerequisite: uniform cycle lengths

Offset coordination only stays meaningful if the intersections being coordinated already share the same cycle length — otherwise the offsets drift out of sync after one cycle. The documented recommendation is to run [[tlscycleadaptation]] first with `--unified-cycle` so every signal shares the largest computed cycle, then coordinate offsets on top of that.

## Usage

```bash
python tlsCoordinator.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml
python tlsCoordinator.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml -a cycles.add.xml
```

`-a`/`--additional-file` substitutes replacement `tlLogic` programs (e.g. `tlsCycleAdaptation.py`'s own output) to coordinate instead of the network's original programs — it replaces, it does not merge with, the network's own definitions.

## Required input

Like [[tlscycleadaptation]], this needs actual `<route>` data (resolved edge sequences, e.g. from [[duarouter]]) to know which intersection pairs vehicles pass through together and how much traffic uses each pair — a raw trips/flows file doesn't carry this. Note `-r`/`--route-file` here takes exactly **one** file, unlike `tlsCycleAdaptation.py`'s comma-separated `-r`/`--route-files`.

## Other options

- `-i`/`--ignore-priority`: ignore road priority when deciding which TLS pairs get coordinated first (otherwise higher-priority-road pairs win in conflicts)
- `--speed-factor <FLOAT>`: assumed average vehicle speed as a fraction of each edge's speed limit, used to estimate inter-intersection travel time (default 0.8)
- `-e`/`--evaluate`: after writing offsets, actually run `sumo` with the result and print duration/travel-time statistics
- `-v`/`--verbose`: print the pairing/merging decisions as they're made

## Output can be offset-only, without phases (verified in SUMO 1.27.1)

`tlsCoordinator.py`'s output additional file can contain `<tlLogic ... offset="..."/>` entries with **no `<phase>` children at all**, referencing the same `programID` as an existing phase-defining program (e.g. the network's own, or the unified-cycle output from [[tlscycleadaptation]]) rather than a new, fully self-contained program. If a downstream step tries to load this offsets-only output *and* the phase-defining program as two separate additional files with the same `tlLogic` id + `programID`, that can produce a duplicate/conflicting definition — merge the offsets into the phase program (copy the phases in, just update `offset`) into one additional file per scenario instead of loading both side by side. See [[sumo-plotting-tools]] for a worked example of building a coordinated-vs-uncoordinated comparison this way.

## Scope

Coordinates offsets only — no effect on cycle length or green splits (see [[tlscycleadaptation]] for that), and produces a static, one-demand-snapshot fixed-time result, not an adaptive controller. For a controller that reacts to real-time traffic instead of a plan computed once from historical demand, see [[actuated-traffic-signals]].
