---
name: implement-mfd-based-perimeter-gating
description: Use this skill when the user wants NETWORK-LEVEL inflow control in SUMO — deliberately holding vehicles outside a congested region (a "core") by throttling perimeter signal green time, based on the region's measured macroscopic fundamental diagram (MFD) accumulation, as opposed to intersection-level or corridor-level signal control. Covers programmatically deriving a core region and gate set from a compiled grid network, generating fixed-route demand with rerouting disabled to isolate the gating effect, building a TraCI perimeter-gating feedback controller, and verifying the mechanism with a non-binding negative control and a full set-point sweep. Trigger on mentions of perimeter gating, MFD-based control, network-level metering, gridlock prevention, core accumulation control, or Daganzo-style two-region control.
related_skills:
  - create-grid-network
  - build-macroscopic-fundamental-diagram
  - implement-maxpressure-traci-controller
  - implement-alinea-ramp-metering
  - analyze-simulation-outputs
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[create-grid-network]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[analyze-simulation-outputs]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[mfd-based-perimeter-gating]]"
---

# Implement MFD-Based Perimeter Gating

Implements **network-level** inflow control: a feedback controller that measures a congested region's accumulation (vehicles present) and throttles the green time of signals at its perimeter to keep inflow from pushing it past its critical accumulation — as opposed to every other signal-control skill in memory (`implement-maxpressure-traci-controller`, `control-signals-with-actuated-tls`, `implement-alinea-ramp-metering`), which all optimize an intersection's or a single ramp's own local performance. This is SimSkill's first use of the macroscopic fundamental diagram (see [[macroscopic-fundamental-diagram]]) as an **active control variable** rather than a purely descriptive measurement, and its first genuinely network-level (not corridor- or intersection-level) control scenario.

## Building a fully-signalized grid

Use `create-grid-network`'s `netgenerate --grid` wrapper, but pass `-j traffic_light` (or `--default-junction-type traffic_light`) **directly** — `--tls.guess` alone is documented to leave 0 junctions signalized on a perfectly uniform grid, since its heuristic looks for locally "important" junctions that don't stand out on a regular lattice. A 7x7 junction grid (49 signals) with ~180m spacing and a static 4-phase program per junction is large enough to have a genuine interior "far from the boundary" and small enough to simulate a full sweep of seeds/set-points in reasonable time.

## Deriving the core and gate set from the compiled network — never hand-pick junction IDs

Parse `grid.net.xml` (`scripts/identify_core_gate.py`) rather than naming junctions by hand:
1. Collect the signalized junctions' coordinates.
2. Take the middle `k` unique x-values and middle `k` unique y-values of the lattice (e.g. `k=3` on a 7-wide grid gives a 3x3 inner core) — their cartesian product is the **core junction set**.
3. **Core edges**: edges with both endpoints in the core.
4. **Gate edges**: edges whose `to` is a core junction and `from` is not — these carry inflow into the core.
5. **Gate junctions**: the `from` junctions of the gate edges — these are the signals to control.

This generalizes to any grid size and re-derives correctly if the network changes, unlike hardcoding junction names.

**Gate links, not just gate edges, must be derived at runtime.** At each gate junction, call `traci.trafficlight.getControlledLinks(tls)` and select every controlled link whose *outgoing* edge is a gate edge — at a typical grid junction this is multiple links (a through movement plus turns) that are commonly split across **more than one green phase**. A naive "shorten the one phase that looks like the through movement" approach misses whichever gate inflow is served by the other phase; always derive per-junction gate-link sets programmatically and confirm what fraction of the cycle's green time they collectively receive (e.g. `g0` seconds of the full cycle) before designing the control law around it.

## Fixed-route demand — disable rerouting or the gating effect is confounded

Generate a time-varying loading profile (ramp-up / sustained peak / ramp-down) concentrated so a genuine fraction of trips are core-destined or through-core, pre-compute routes **once** with `duarouter`, and reuse them verbatim across every run — no `<rerouter>` element, no `--device.rerouting.*` option. If rerouting is left on, vehicles can detour around a closing gate, which mixes route-choice effects into what should be a pure signal-timing comparison. **Re-derive each vehicle's trip class (e.g. core-destined / through / outside) from its realized route**, not from the demand generator's intent — a vehicle nominally aimed at the core can end up classified differently once duarouter actually routes it. Verify rerouting was genuinely inert after the fact by diffing every vehicle's `vehroute-output` edge sequence against its planned `duarouter` route — zero deviations confirms the isolation held.

## Instrumenting accumulation and production

Every step (or a short aggregation interval), sum over core edges via TraCI subscriptions:
- **Accumulation** `n(t) = sum_e getLastStepVehicleNumber(e)` — vehicles currently on core edges.
- **Production** `sum_e n_e * v_e * dt` (veh·m, report as veh·km/h per interval) — the core's actual throughput-of-work.

Cross-validate the TraCI-derived accumulation against SUMO's own core-restricted `edgeData` output (`sum sampledSeconds / interval`) — they should agree closely (a few percent). An E3 cordon detector (entries on gate edges, exits on core-outbound edges) is a useful supplementary check but is **biased low on `vehicleSum`/travel-time statistics if a large fraction of trips end inside the cordon and never cross an exit point** — treat E3 as a cross-check, not the primary instrument, in that situation.

## Establishing the ungated baseline — must show genuine overshoot and collapse

Before building any controller, verify the ungated network actually produces a supercritical core: run several seeds ungated, bin (accumulation, production) points into intervals (discarding an initial warm-up), and find the critical accumulation `n_crit` as the center of the bin with highest mean production. A meaningful gating study needs the baseline's peak accumulation to clearly exceed `n_crit` (verified case: 2.1x) with a **measured production collapse** on the congested branch (verified case: ~85%) — if the ungated core never goes supercritical, gating has nothing to prevent (see the Gotchas section below for what happens if you gate anyway).

**Quantify hysteresis by pooling multiple seeds, not from a single run.** Split each run at its own accumulation peak into loading/unloading branches and compare production at matching accumulation levels — a single run's loop is typically too noisy to be convincing on its own; pooling several seeds' loading and unloading points into common bins reveals a clear, one-directional (clockwise: loading always delivers more production than unloading at the same accumulation) gap.

## The gating controller

```
g_gate(k) = clip( g0 - K*(n(k) - n_set), g_min, g0 )
```

Evaluated every control interval (e.g. 60s) from the interval-mean core accumulation. `g0` is the gate links' total green time in the baseline cycle; `g_max` is pinned to `g0` so the controller can only ever **restrict**, never extend, inflow relative to baseline.

Apply it as a **ratio** `r = g_gate/g0`, uniformly reducing every phase in which gate links are green by that same ratio, followed by the network's own real clearance-yellow duration, then red for the remainder — never jump directly between green states (the same discipline as `implement-maxpressure-traci-controller`: derive the phase/link mapping from `getControlledLinks`, and route every phase change through the compiled program's own yellow phase). Design points that matter:

- **Only into-core (gate) links change color.** Every movement *leaving* the core, and every non-gate movement at the gate junction, keeps its programmed color untouched — gating must never be able to back traffic up *inside* the core.
- **Cycle length and phase order are unchanged** — no coordination side effects, no ad-hoc phase insertion.
- **Use a ratio applied uniformly across all phases serving gate links, not a per-cycle green "budget" consumed first-come-first-served.** A budget approach serves whichever movement's phase comes first in the cycle at full green until the budget runs low — if the dominant inflow happens to be served by an early phase, it stays essentially unthrottled while a minor movement absorbs the whole restriction. The ratio form throttles every gate-serving phase proportionally regardless of cycle position.
- **At `r=1` the controller must be provably inert** — the emitted signal-state sequence should be byte-for-byte identical to the static baseline program. This is what makes a non-binding negative control (a set-point so high the gate never engages) a real proof the mechanism only acts when it binds, not just an assumption.

## Verifying the mechanism: sweep + negative control, not a single before/after

Run every configuration (ungated baseline, the non-binding negative control, and every swept set-point) across **multiple random seeds** with everything else — network, demand, routes, seed-independent structure — held identical. Report paired per-seed deltas (how many of N seeds improved), not just the mean, since variance near the tipping point (set-points close to `n_crit`) can be large enough to flip the sign on individual seeds. The negative control should reproduce the baseline's raw output (accumulation time series, `tripinfo` records) essentially exactly in every seed — verify this directly (e.g. diff the CSV columns and tripinfo fields row-for-row) rather than just checking the summary metrics look similar.

## Gotchas

- **`--tls.guess` leaves a uniform grid unsignalized** — pass `-j traffic_light` directly.
- **Gate links split across multiple phases** — derive per-junction gate-link-to-phase mapping from `getControlledLinks`, don't assume one phase covers all inflow.
- **Leaving rerouting enabled confounds the gating effect with route choice** — disable it explicitly and verify zero route deviations after the fact.
- **A "budget consumed first-come-first-served" throttling scheme under-restricts whichever movement's phase comes first in the cycle** — use a uniform per-phase ratio instead.
- **The best-performing set-point is typically well below the measured `n_crit`**, not equal to it — with a proportional control law and a fixed measurement interval, the gate only reaches its floor once accumulation is `n_set + (g0-g_min)/K` above the set-point, so the set-point that *realizes* a peak accumulation near `n_crit` is offset below it by that amount. This is a property of the specific control law's saturation dynamics, not a general rule — recompute the offset for a different gain or interval rather than assuming the same gap.
- **A slack set-point (close to or above `n_crit`) provides negligible or even negative benefit** — the gate only starts restricting once the core is already on the congested branch, and (because of hysteresis) production does not recover there simply by cutting inflow. Gating is a **prevention**, not a **cure**, mechanism.
- **Removing the green-time floor (`g_min`) can expose a starvation regime** the normal swept set-points may not reach — driving accumulation below `n_crit` also reduces production and can raise travel time relative to the best (non-zero-floor) configuration, even though it's still far better than ungated.
- **Gating an ungated-but-undersaturated core (peak accumulation never exceeds `n_crit`) is verified to be a pure cost with no seeds improved** — always check whether the baseline is genuinely supercritical before expecting any benefit; don't apply this control to a network that was never going to gridlock.
- **A large teleport count in the ungated baseline is a real confound** — if the baseline relies on SUMO's own gridlock-resolution teleporting to avoid outright deadlock, some of gating's apparent benefit is "fixing" a simulator-internal mechanism, not purely a physical-throughput gain. Report teleport counts for every configuration and note this explicitly rather than treating the baseline's raw travel-time number as a clean physical measurement.
- **Total completions over the full simulation horizon do not discriminate between configurations if demand is finite** — every configuration eventually serves all trips. Measure throughput at fixed time horizons (e.g. completions by t=X) or via network clearance time, not final arrival counts.

## Related

- `create-grid-network` — the `netgenerate --grid` network-building step this skill's network is built from.
- `build-macroscopic-fundamental-diagram` / [[macroscopic-fundamental-diagram]] — the point/corridor-level flow-density-speed MFD; this skill instead measures a network-region's accumulation-production MFD and uses it as an active control variable rather than a passive measurement.
- `implement-maxpressure-traci-controller` — the general TraCI closed-loop signal-control pattern (phase-to-movement mapping via `getControlledLinks`, minimum-green enforcement, yellow-transition discipline) this skill's controller follows, applied to green-time throttling rather than phase selection.
- `implement-alinea-ramp-metering` / [[ramp-metering-with-alinea]] — an analogous feedback-metering-via-signal-timing precedent at ramp scale; both skills share the lesson that the throttled side's real cost hides in insertion/queuing delay, not just in-network waiting time.
- `analyze-simulation-outputs` — general tripinfo/summary/edgeData parsing conventions this skill's comparison follows.
- [[mfd-based-perimeter-gating]] — the verified set-point sweep, hysteresis quantification, who-pays analysis, and the undersaturated-core null result.
- `validate-congested-scenario-results-against-teleport-artifacts` — directly re-tested this skill's headline gating benefit under a matched-cohort teleport-free comparison and confirmed it survives largely intact; if reporting a gated-vs-ungated comparison on a genuinely oversaturated network, check that skill's decision rule for what must be co-reported.
