---
name: optimize-signals-by-tlscycleadaptation
description: Use this skill when the user wants to optimize existing traffic-light cycle lengths and green-time splits for a SUMO network against a given demand, using Webster's equation — as opposed to designing signal timing from scratch or using RL/actuated control. Covers tlsCycleAdaptation.py. Trigger on mentions of tlsCycleAdaptation, Webster's method/equation, signal cycle optimization, green split optimization, or "optimize my traffic lights for this demand."
---

# Optimize Signals (tlsCycleAdaptation.py)

Computes optimized cycle lengths and green-phase durations for every signalized intersection in a network, using Webster's equation applied independently at each intersection against one hour of the given traffic demand. Reference: https://sumo.dlr.de/docs/Tools/tls.html#tlscycleadaptationpy and the script source at https://github.com/eclipse-sumo/sumo/blob/main/tools/tlsCycleAdaptation.py

## Required input: routed vehicles, not trips or flows (important)

`tlsCycleAdaptation.py` needs a route file containing `<vehicle>` elements with `<route>` children — **not** `<trip>` or `<flow>` elements, and vehicles with `depart="triggered"` are silently skipped. This means:

- Output straight from `generate-random-trips` (a `.trips.xml`, or a `--route-file` output that's still trip-shaped) generally isn't sufficient on its own.
- Run it through `convert-trips-to-routes` (duarouter) first to get a proper `.rou.xml` of routed `<vehicle>`/`<route>` pairs, then feed that here.
- Same applies to `convert-od-matrix-to-trips` output — route it with duarouter before this step.

## Locating the tool

`tlsCycleAdaptation.py` lives at `$SUMO_HOME/tools/tlsCycleAdaptation.py` — same location family as `randomTrips.py`/`osmGet.py`/`osmBuild.py`, **not** next to the `sumo`/`netconvert` binaries.

```bash
echo $SUMO_HOME
ls "$SUMO_HOME/tools/tlsCycleAdaptation.py"
```

`scripts/optimize_signals.py` resolves this automatically and fails with a clear message if `SUMO_HOME` isn't set or the tool isn't found there.

## Quick usage

```bash
# Basic: optimize every signalized intersection against the given demand
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml

# Explicit begin time for the 1-hour demand window (recommended — see below)
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml -b 3600

# Keep each intersection's existing cycle length, only re-split the green times
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --existing-cycle

# Force all intersections to share one (the largest computed) cycle length — needed before coordinating offsets
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --unified-cycle

# Cap cycle length and inspect the critical flow ratios driving the result
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --max-cycle 90 --restrict-cyclelength --write-critical-flows --verbose

# Skip specific intersections (comma-separated tls ids)
python scripts/optimize_signals.py -n net.net.xml -r routes.rou.xml -o tlsAdaptation.add.xml --skip cluster_12_34,tls_5
```

Then load the result into `run-simulation`:
```bash
sumo -n net.net.xml -r routes.rou.xml -a tlsAdaptation.add.xml
```

## Script options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n, --net-file` | input `.net.xml` (required) | — |
| `-r, --route-files` | routed demand file(s), comma-separated (required) | — |
| `-o, --output-file` | output additional file with the new `tlLogic` definitions | `tlsAdaptation.add.xml` |
| `-b, --begin` | start of the 1-hour demand window used for the calculation | first vehicle's departure time |
| `-y, --yellow-time` | yellow phase duration (s) | 4 |
| `-a, --all-red` | all-red time per cycle (s) | 0 |
| `-l, --lost-time` | start-up/clearance lost time per phase (s) | 4 |
| `-g, --min-green` | minimum green time for a phase with no traffic | 4 |
| `--green-filter-time` | ignore phases with green time below this (s) when computing critical flows | 0 |
| `--min-cycle` / `--max-cycle` | bounds on the computed cycle length (s) | 20 / 120 |
| `-e, --existing-cycle` | keep each intersection's current cycle length; only re-split green times | off |
| `-u, --unified-cycle` | use the largest computed cycle length as the cycle for *every* intersection | off |
| `-R, --restrict-cyclelength` | hard-cap the cycle at `--max-cycle` even if minimum green times would push it over | off |
| `-H, --saturation-headway` | seconds/vehicle used to derive lane capacity (default implies 1800 veh/lane/hour) | 2 |
| `-p, --program` | program id to assign to the new `tlLogic` (old program stays loadable alongside it) | `a` |
| `--skip` | comma-separated tls ids to leave untouched | — |
| `--write-critical-flows` | print the critical flow ratio per phase per intersection | off |
| `--sorted` | assume the route file is departure-time-sorted (stops reading once past the window, faster on large files) | off |
| `-v, --verbose` | print progress and intermediate values | off |
| `--extra <ARG>` | any other raw `tlsCycleAdaptation.py` flag not wrapped above, can be repeated. If the value itself looks like a flag (starts with `--`), use `--extra="--the-flag"` (with `=`) — otherwise argparse misreads it as a separate option rather than `--extra`'s value | — |
| `--dry-run` | print the command without running it (this wrapper's own flag, not upstream's) | off |

## Choosing `--begin`

Webster's equation here only ever looks at **one hour** of demand starting at `--begin`. If not given, it defaults to the first vehicle's departure time — which is rarely the peak. For a realistic result:
- If demand has an obvious peak period, pass `-b` at the start of it explicitly.
- If the route file's total span is under an hour, flows are automatically scaled up proportionally to an hourly rate.
- If the span is over an hour and no `--begin` is given, the script tries to auto-detect the busiest 1-hour window — but explicit is safer than relying on that heuristic, especially with unusual demand shapes.

## What this does and doesn't do

- **Optimizes cycle length and green splits per intersection independently.** It does not coordinate signal offsets across intersections — a network of well-optimized-in-isolation intersections can still perform poorly together if their cycles aren't synchronized. SUMO's `tlsCoordinator.py` handles offset coordination separately (not covered by this skill) and generally wants all intersections to already share a common cycle length, which is exactly what `--unified-cycle` here produces.
- **Static, not adaptive/actuated.** The output is a fixed-time plan sized to one hour of demand — it won't respond to real-time fluctuations the way an actuated controller or an RL policy would. It's a reasonable fixed-time baseline to compare an actuated/RL approach against, or a starting point before hand-tuning.
- **Only touches intersections that have both a `tlLogic` and nonzero flow through them** in the given route file — an isolated or unused signal is left alone.

## Gotchas

- **Trips/flows are not accepted, and `triggered` departures are silently dropped** — see "Required input" above. If the output additional file comes back essentially unchanged or the tool warns about parsing nothing, this is the first thing to check.
- **Right-turn-on-red / shared lanes**: if through and right-turn traffic share a phase but can't actually share a lane in the network (no dedicated shared lane), capacity for the through movement gets overestimated. The docs recommend making the rightmost lane a shared through/right lane if this applies.
- **`--saturation-headway` (default 2s ≈ 1800 veh/lane/hour) may be too optimistic for short block spacing** (e.g. dense urban grids with ~500m intersection spacing) — consider raising it for such networks.
- **The default is not just a rough approximation — it can be substantially wrong even for SUMO's own default vehicles.** Verified directly: SUMO's default passenger vType discharges at ~2191 veh/h/lane at a real stop line (measured from raw detector data, see `measure-saturation-flow-and-validate-webster-method`), 21.7% above the `-H 2` default's 1800 assumption. Using the default produced a plan costing 16-26% more simulated delay than one computed from the measured headway, and in one case wrongly triggered the tool's own `sum(y)>=1` oversaturation fallback on a network that was genuinely undersaturated. Measure the real saturation headway for the vType(s) actually in the scenario and pass it via `-H` rather than accepting the default, especially for any non-default vehicle configuration.
- **If critical flow ratios sum to ≥ 1** (oversaturated), the script falls back to `--max-cycle` as the "optimal" cycle and prints a warning — this is a sign the demand exceeds what any fixed-time plan can serve well at that intersection, not a bug.
- **Re-running with the same `--output-file` overwrites it silently.**
- **This only affects existing `tlLogic`-controlled junctions.** For a network with no traffic lights yet (e.g. all-`priority` junctions), there's nothing here to optimize — set junction/TLS type first via the relevant network-generation skill (`create-grid-network`'s `--junction-type`/`--tls-guess`, `create-single-intersection`'s `--junction-type traffic_light`, or `load-osm-network`'s `--tls.guess` netconvert option) or `netconvert --tls.guess` on the existing network.

## Related

- `measure-saturation-flow-and-validate-webster-method` — measures this tool's `-H`/`-l` capacity assumptions directly from raw stop-line detector data instead of trusting the defaults, and validates Webster's underlying equation against brute-force simulation.
- [[webster-method]] — the theory this tool implements, including where its analytical formula breaks down and the verified default-assumption mismatch.
- `design-arterial-signal-progression-and-verify-bandwidth` — uses this tool's `--unified-cycle` flag as the required prerequisite for any multi-signal bandwidth calculation, and found the bandwidth-optimal cycle length differs from the delay-optimal one this tool's Webster sizing targets.
