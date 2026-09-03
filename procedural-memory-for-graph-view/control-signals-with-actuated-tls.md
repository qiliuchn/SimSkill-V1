---
name: control-signals-with-actuated-tls
description: Use this skill when the user wants SUMO's native, runtime-adaptive traffic-light control — gap-based actuated (type="actuated") or delay-based (type="delay_based") signals — as opposed to a static fixed-time plan (Webster/coordinator) or an external TraCI/RL control loop. Covers generating or converting a network to use actuated/delay_based TLS types, the induction-loop detector model behind them (including when SUMO auto-generates detectors), key parameters (min-dur, max-dur, max-gap, detector-gap), and comparing actuated control against a fixed-time baseline across demand levels. Trigger on mentions of actuated traffic lights, delay_based signals, adaptive/responsive signal control, gap-out detection, or "traffic lights that react to traffic."
related_skills:
  - create-grid-network
  - load-osm-network
  - generate-random-trips
  - convert-trips-to-routes
  - run-simulation
  - analyze-simulation-outputs
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - optimize-signals-by-qlearning
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - implement-reservation-based-autonomous-intersection-management
  - design-signal-change-and-clearance-intervals
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[load-osm-network]]"
  - "[[generate-random-trips]]"
  - "[[convert-trips-to-routes]]"
  - "[[run-simulation]]"
  - "[[analyze-simulation-outputs]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[optimize-signals-by-qlearning]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[implement-reservation-based-autonomous-intersection-management]]"
  - "[[design-signal-change-and-clearance-intervals]]"
related_pages:
  - "[[actuated-traffic-signals]]"
---

# Control Signals with Actuated/Delay-Based TLS

Configures and evaluates SUMO's **built-in, runtime-adaptive** traffic-light logic — `type="actuated"` (gap-based: extends green while vehicles keep arriving within a gap threshold) and `type="delay_based"` (extends green based on accumulated vehicle delay rather than raw gaps) — as distinct from every other signal-control skill in memory: `optimize-signals-by-tlscycleadaptation` and `optimize-signals-by-tlscoordinator` both compute a **static** plan offline from historical demand, and `optimize-signals-by-qlearning` drives signals via an **external** TraCI loop. Actuated/delay_based logic instead reacts to real-time detector data *inside* SUMO itself, with no external controller needed.

## Setting the TLS type

The simplest path is to set it at network-generation time. `netgenerate` (and `netconvert`) expose `--tls.default-type <STR>`, which applies to every junction with an otherwise-unspecified TLS type:

```bash
netgenerate --grid ... -j traffic_light --tls.default-type actuated -o grid_actuated.net.xml
netgenerate --grid ... -j traffic_light --tls.default-type delay_based -o grid_delay.net.xml
```

No separate `netconvert` pass is required — `netgenerate` itself understands this option (verified via `netgenerate --help`; don't assume it's `netconvert`-only without checking, since network-generation option surfaces vary). The resulting `<tlLogic type="actuated" ...>`/`<tlLogic type="delay_based" ...>` elements automatically get `minDur`/`maxDur` attributes added to their green `<phase>` entries — everything else about the phase structure (states, yellow phases, cycle-length-as-generated) is unchanged from the static case, which is exactly what makes a fixed-time-vs-actuated comparison on the same network topology straightforward: build the same network 2-3 times with only `--tls.default-type` varying, and every other geometry/phase-state detail stays identical.

**`netconvert -s existing.net.xml --tls.default-type actuated -o converted.net.xml` does NOT convert an existing network's signals** — verified directly (build a network, confirm its `tlLogic` already has an explicit `type="static"`, then re-run with only `--tls.default-type actuated`: the type stays `static`, unchanged). `--tls.default-type` only fills in *unspecified* TLS types, and every `.net.xml` netconvert/netgenerate ever writes already has an explicit `type=` attribute on each `tlLogic` — so this pattern silently does nothing on any network that's already been through a netconvert/netgenerate pass (which is all of them). To actually change an existing network's TLS type, either **rebuild from the original source definition** (the `.nod.xml`/`.edg.xml` plain-XML for `create-single-intersection`-style networks, or the source `.osm.xml` for an OSM import — see `load-osm-network`) with the desired `--tls.default-type`, which also guarantees identical topology/geometry across variants since the rebuild is deterministic, or **hand-edit each `<tlLogic>` element's `type=` attribute** and add `minDur`/`maxDur` to its phases directly if rebuilding from source isn't practical.

## Detectors: usually nothing to add

**SUMO auto-generates the required induction-loop (E1) detectors internally for `actuated`/`delay_based` junctions when none are explicitly declared** — no `<inductionLoop>` additional file is needed for a basic setup (confirmed: a plain `.net.xml` with `type="actuated"`/`delay_based` produces genuinely adaptive behavior with zero detector-related warnings). Only reach for an explicit detector-defining additional file if the scenario needs non-default detector placement/parameters beyond what the auto-generated ones provide.

**To bind a CUSTOM (non-auto-generated) detector instead**, define it as a normal E1 `<inductionLoop>` in an additional file, then reference it on the `<tlLogic>` element itself via `<param key="<laneID>" value="<detID>"/>` — the key is the **lane ID itself**, not a `detector:`-prefixed form (verified directly, see `design-actuated-signal-detector-placement-and-fault-tolerance` for the full binding-verification protocol). A special value `NO_DETECTOR` disables actuation for that lane (falls back to `minDur`). Only E1 detectors are accepted — an E2 `laneAreaDetector` bound this way is a hard SUMO error. **An unrecognized `<param>` key is silently ignored, not rejected** — always verify a custom binding genuinely took effect via a behavior-changing manipulation (e.g. moving the detector to an implausible position and confirming the phase-duration trace changes), not just the absence of an error, given this project's documented precedent of a plausible-sounding config flag (`--tls.default-type` on an already-compiled net) silently doing nothing.

## Key parameters

| Parameter | Where it lives | Meaning | Typical default |
| --- | --- | --- | --- |
| `minDur` / `maxDur` | `<phase>` attribute | bounds on how short/long an actuated green phase can run | `netgenerate`/`netconvert` typically set `minDur=5`, `maxDur=50` automatically |
| `max-gap` | actuated-type param | if no vehicle is detected within this many seconds, the phase gaps out and ends | 3.0 s |
| `detector-gap` | actuated-type param | how far upstream of the stop line the auto-generated detector sits, expressed as seconds of travel time at the lane's speed (i.e. `detector-gap × speed` meters) | 2.0 s |
| `passing-time` | actuated-type param | assumed time for a detected vehicle to clear the detector, used in the gap calculation | 2.0 s |
| `minTimeLoss` | delay_based-type param | minimum per-vehicle time loss (vs. free-flow) counted toward the phase's accumulated-delay extension decision | 1.0 s |
| `detectorRange` | delay_based-type param | how far back along the lane delay is measured | whole lane by default |

These are all SUMO's own defaults unless overridden via `<param>` children on the `<tlLogic>` element — check https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#actuated_traffic_lights (and the delay_based section on the same page) for the full parameter list and override syntax if a scenario needs non-default tuning; don't assume tuned values without checking the actual XML.

## Comparing against a fixed-time baseline

1. Build 2-3 networks identical except for `--tls.default-type` (static/actuated/delay_based).
2. Generate demand once per scenario condition you care about (e.g. multiple demand levels via `generate-random-trips --insertion-rate`), and **reuse the exact same routed route file across every TLS-type variant at a given demand level** — the comparison is only valid if the routes are identical, only the signal logic differs.
3. Run each (network, demand-level) combination with `run-simulation`, emitting tripinfo/summary/edgeData as usual.
4. Use `scripts/compare_tls_controllers.py` to build a controller × demand-level comparison table with a %-vs-baseline column:
   ```bash
   python scripts/compare_tls_controllers.py \
       --run "fixed:low=runs/low_fixed/tripinfo.xml,runs/low_fixed/summary.xml" \
       --run "actuated:low=runs/low_actuated/tripinfo.xml,runs/low_actuated/summary.xml" \
       --run "delay_based:low=runs/low_delay/tripinfo.xml,runs/low_delay/summary.xml" \
       --baseline fixed --out-dir comparison/
   ```
   This is a separate script from `analyze-simulation-outputs` rather than an extension of it — that skill's %-change column is defined for exactly 2 runs, and a controller × demand-level grid with a chosen baseline column is a different comparison shape worth keeping distinct (see that skill's own docs on why it deliberately doesn't guess a reference run for 3+ runs).

## What to expect from the results

- Both actuated types typically **beat a static fixed-time plan substantially** on mean waiting time and time loss (tens of percent to nearly an order of magnitude, in a verified run: -82% to -97% mean waiting time), with no throughput penalty — because a fixed cycle wastes green time on phases with no traffic, while actuated/delay_based logic gives green time only where and when it's needed.
- **`delay_based` tends to outperform gap-based `actuated`** across the board, since it optimizes directly for accumulated delay rather than the more indirect gap-detection heuristic.
- **The relative benefit is largest under light/variable demand and narrows as demand rises** — as intersections fill up, there's less "wasted" fixed-time green to reclaim, and delay accumulates faster than actuation can shed it. This erosion trend is the expected qualitative signature of actuated control; don't be surprised to see the %-improvement shrink (not vanish) from low to high demand rather than staying constant.
- A network with high reserve capacity (e.g. a small single-lane grid with multiple parallel routes) may never actually saturate even at a "high" demand level (0 teleports, no gridlock) — that's a property of the network's capacity margin, not evidence the comparison is wrong. If a truly oversaturated regime is needed to see where the actuated advantage fully disappears, use a more capacity-constrained network (fewer lanes/parallel paths, or a bottleneck) rather than just raising demand further on a high-capacity grid.

## Related

- `create-grid-network` (or any network skill) for the base topology; its own gotchas note `--tls.guess` is unreliable for signalizing a uniform grid — use `-j traffic_light` explicitly regardless of TLS type.
- `load-osm-network` — a real (non-synthetic) network is another place this skill applies; verified to work the same way (rebuild from the source `.osm.xml` with the desired `--tls.default-type` for each variant) and confirmed the actuated-beats-fixed-time finding generalizes beyond synthetic grids.
- `generate-random-trips` + `convert-trips-to-routes` for demand at each level; `run-simulation` for execution.
- `analyze-simulation-outputs` for parsing tripinfo/summary/edgeData into the base per-run metrics this skill's comparison script builds on.
- `optimize-signals-by-tlscycleadaptation` / `optimize-signals-by-tlscoordinator` / `optimize-signals-by-qlearning` — the other signal-control approaches in memory; useful baselines/contrasts, not overlapping with this skill's runtime-adaptive, no-external-controller approach.
- [[actuated-traffic-signals]] — the underlying SUMO concepts (detector model, parameter reference, load-dependence characterization) this skill's workflow is built on.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — extends this skill from the auto-generated-detector default to custom detector placement, gap tolerance tuning, and detector fault tolerance; the full binding-verification protocol and the verified detector-placement/fault findings live there.
- `implement-reservation-based-autonomous-intersection-management` — the native-actuated baseline this skill's controller is compared against in a signal-free reservation-based-control study; found actuated control beats AIM decisively at high demand, the reverse of AIM's low-demand advantage.
- `design-signal-change-and-clearance-intervals` — uses this skill's hand-authored `tlLogic` state-string technique to author explicit yellow and all-red phases, treating the change/clearance interval (usually a hardcoded default here) as its own design object.
