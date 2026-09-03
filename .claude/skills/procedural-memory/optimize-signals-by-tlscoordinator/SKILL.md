---
name: optimize-signals-by-tlscoordinator
description: Use this skill when the user wants to coordinate (synchronize) traffic-light offsets across multiple intersections in a SUMO network so a platoon of vehicles can travel through several signals without stopping ("green wave"), as opposed to optimizing a single intersection's cycle/green-split in isolation. Covers tlsCoordinator.py. Trigger on mentions of tlsCoordinator, signal offset coordination, green wave, arterial progression/coordination, or synchronizing traffic lights along a corridor.
---

# Optimize Signals (tlsCoordinator.py)

Computes traffic-light **offsets** (when each intersection's cycle starts, relative to the others) so that platoons of vehicles traveling common routes hit consecutive green lights — a "green wave" — rather than stopping at every intersection. This is a different axis of optimization from `optimize-signals-by-tlscycleadaptation`: that skill sizes each intersection's cycle length and phase splits *in isolation*; this one takes existing (ideally already-uniform) cycles and staggers their start times so they work together along common travel paths. Reference: https://sumo.dlr.de/docs/Tools/tls.html#tlscoordinatorpy and the script source at https://github.com/eclipse-sumo/sumo/blob/main/tools/tlsCoordinator.py

## How it works, briefly

For every pair of consecutive traffic-light-controlled intersections that appear together in any route, the script computes the ideal offset between them based on travel time and existing green-phase timing, weighted by how many vehicles use that pair and by road priority. Intersections that end up linked (directly or transitively, through shared routes) get merged into a coordinated set with consistent relative offsets; unconnected intersections are left alone.

## Prerequisite: uniform cycle lengths (important)

Per the SUMO docs, this tool works best when **every traffic light in the network already shares the same cycle length** — coordinating offsets between intersections with different cycle lengths doesn't stay synchronized for long. In practice this means running `optimize-signals-by-tlscycleadaptation` first with `--unified-cycle`, then feeding its output here via `-a`:

```bash
# 1. Get every intersection onto the same cycle length
python <skill-dir>/optimize-signals-by-tlscycleadaptation/scripts/optimize_signals.py \
    -n net.net.xml -r routes.rou.xml -o cycles.add.xml --unified-cycle

# 2. Coordinate offsets, using those unified-cycle programs instead of the network's originals
python <skill-dir>/scripts/coordinate_signals.py \
    -n net.net.xml -r routes.rou.xml -o offsets.add.xml -a cycles.add.xml
```

Both additional files then load together into `run-simulation`:
```bash
sumo -n net.net.xml -r routes.rou.xml -a cycles.add.xml,offsets.add.xml
```

## Required input: routes, not trips or flows (same constraint as tlsCycleAdaptation)

Like its sibling tool, `tlsCoordinator.py` needs actual `<route>` data (with resolved edge sequences) to know which pairs of intersections vehicles actually pass through together and how much traffic uses each pair — a raw `.trips.xml` doesn't have this. Route it with `convert-trips-to-routes` (duarouter) first if it isn't already a `.rou.xml`.

**One difference from `tlsCycleAdaptation.py` worth flagging**: this tool takes a single route file via `-r/--route-file` (singular, one file only), whereas `tlsCycleAdaptation.py` takes `-r/--route-files` (plural, comma-separated). Passing a comma-separated list here will not work the way it does for the cycle-adaptation skill.

## Locating the tool

`tlsCoordinator.py` lives at `$SUMO_HOME/tools/tlsCoordinator.py` — same location family as `tlsCycleAdaptation.py`/`randomTrips.py`, **not** next to the `sumo`/`netconvert` binaries.

```bash
echo $SUMO_HOME
ls "$SUMO_HOME/tools/tlsCoordinator.py"
```

`scripts/coordinate_signals.py` resolves this automatically and fails with a clear message if `SUMO_HOME` isn't set or the tool isn't found there.

## Quick usage

```bash
# Basic: coordinate offsets using the network's existing tlLogic programs
python <skill-dir>/scripts/coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml

# Coordinate using replacement programs (e.g. from tlsCycleAdaptation --unified-cycle) instead of the network's own
python <skill-dir>/scripts/coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml -a cycles.add.xml

# Ignore road priority when deciding which TLS pairs to coordinate first
python <skill-dir>/scripts/coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --ignore-priority

# Assume vehicles travel at 90% of the speed limit rather than the 80% default
python <skill-dir>/scripts/coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --speed-factor 0.9

# Also run the resulting scenario through sumo and print duration statistics
python <skill-dir>/scripts/coordinate_signals.py -n net.net.xml -r routes.rou.xml -o offsets.add.xml --evaluate --verbose
```

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n, --net-file` | input `.net.xml` (required) | — |
| `-r, --route-file` | routed demand file — **singular, one file only** (required) | — |
| `-o, --output-file` | output additional file with the computed `tlLogic` offsets | `tlsOffsets.add.xml` |
| `-a, --additional-file` | replacement `tlLogic` programs to coordinate instead of the network's own (e.g. `tlsCycleAdaptation.py` output) | — |
| `-i, --ignore-priority` | ignore road priority when sorting which TLS pairs get coordinated first (otherwise higher-priority roads' pairs win when in conflict) | off |
| `--speed-factor` | assumed average vehicle speed as a fraction of each edge's speed limit, used for travel-time estimates between intersections | 0.8 |
| `-e, --evaluate` | after writing the offsets, actually run `sumo` with the result and print duration/travel-time statistics (requires `sumo` findable on `$PATH` or `$SUMO_HOME/bin`) | off |
| `-v, --verbose` | print the pairing/merging decisions as they're made | off |
| `--extra <ARG>` | any other raw `tlsCoordinator.py` flag not wrapped above, can be repeated. If the value itself starts with `--`, use `--extra="--the-flag"` (with `=`) so argparse doesn't misread it as a separate option | — |
| `--dry-run` | print the command without running it (this wrapper's own flag, not upstream's) | off |

## What this does and doesn't do

- **Coordinates offsets only** — it doesn't touch cycle length or green-phase durations. If those also need optimizing, run `optimize-signals-by-tlscycleadaptation` first (with `--unified-cycle`, per the prerequisite above) and pass its output in via `-a`.
- **Prioritizes the busiest/highest-priority pairs.** When an intersection would need to satisfy conflicting offset requirements toward two different neighbors (e.g. it's a hub for two different coordinated corridors), the pair with higher road priority and/or more vehicles wins; the loser is either merged in with a compromise offset or left out of that particular coordinated set.
- **Only coordinates intersections that share travel paths in the given route file.** Two signalized intersections with no common route between them in the demand data are never linked, regardless of physical proximity.
- **Static offsets for one demand snapshot** — like `tlsCycleAdaptation.py`, this produces a fixed-time plan sized to the given routes; it doesn't adapt over time.

## Gotchas

- **`-r` takes exactly one file here**, unlike the plural `-r/--route-files` in `tlsCycleAdaptation.py` — don't reuse a comma-separated multi-file argument from that skill without checking.
- **Mismatched cycle lengths undermine the whole point.** Coordinating offsets between intersections whose cycles aren't already synchronized will produce offsets that only stay valid for one cycle before drifting — see the Prerequisite section.
- **`--evaluate` actually launches `sumo`** as a subprocess (not just this wrapper script) — make sure `sumo` is reachable (on `$PATH` or in `$SUMO_HOME/bin`) if using this flag, same binary-location caveat as the network-generation skills.
- **The `-a` additional file is a *substitute* for the network's programs during coordination, not merged with them** — if the network's own `tlLogic` definitions should be coordinated as-is, omit `-a` entirely rather than pointing it at the network file itself.
- **Re-running with the same `--output-file` overwrites it silently.**
- **This only affects existing `tlLogic`-controlled junctions with common routes through them** — same starting-condition requirement as `optimize-signals-by-tlscycleadaptation`.
- **SUMO's `tlLogic` offset semantics are `(t - offset) mod cycle`, not `(t + offset) mod cycle`** — verified directly against TraCI (an offset of 122.2s on a 90s cycle put green onset at t=78s, matching the subtraction form). Getting this sign backwards when hand-computing or verifying an expected green-wave band produces a mis-placed band and can make correctly-computed offsets look like they produce zero bandwidth.

## Related

- `compare-one-way-vs-two-way-street-grid-conversion` — applies this tool to two different grid topologies and finds the progression-bandwidth constraint binds per-street, not network-wide-aggregate — a network can show similar total geometric bandwidth across topologies while the per-street/per-direction breakdown tells a very different story.
- `design-arterial-signal-progression-and-verify-bandwidth` — treats this tool's output as one of three offset sets to compare (alongside an analytic maximum-bandwidth plan and a delay-optimized plan), and found this tool's offsets can achieve zero analytic bandwidth while still nearly matching delay-optimal performance — bandwidth and delay are correlated but not interchangeable.
