---
summary: Dynamic user equilibrium (DUE) is reached when no driver can switch to a faster route — Wardrop's first principle — computed in SUMO by iterating duarouter+sumo via duaIterate.py; a verified test found DUE genuinely equalizes router-visible in-network travel time between parallel routes, but can leave a real gap in total rider-experienced time (including origin-insertion delay) that the router cannot see, traceable to a departure-ordering artifact rather than a wrong route split.
keywords:
  - dynamic-user-equilibrium
  - duaIterate
  - Wardrop
  - traffic-assignment
  - route-choice
created: 2026-07-23T20:59:48
last_updated: 2026-08-07T10:44:36
sources:
  - "[[episodic-memory/2026-07-23_19-56-17/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-23_19-56-17/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[duarouter]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[sumo-output-files]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[braess-paradox-in-sumo]]"
  - "[[information-penetration-and-congestible-routing]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[one-way-vs-two-way-grid-performance-crossover]]"
  - "[[vickrey-bottleneck-departure-time-equilibrium]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[neighborhood-traffic-calming-displacement-and-evaporation]]"
  - "[[effort-based-routing-and-eco-routing]]"
  - "[[route-choice-model-verification-overlap-and-route-set-effects]]"
related_skills:
  - compute-dynamic-user-equilibrium
  - convert-trips-to-routes
  - create-single-intersection
  - implement-alinea-ramp-metering
  - construct-and-verify-braess-paradox
  - sweep-rerouting-device-market-penetration
  - compare-one-way-vs-two-way-street-grid-conversion
  - equilibrate-departure-time-choice-in-bottleneck-model
  - scan-network-link-criticality-and-vulnerability
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - specify-route-choice-models-and-generate-route-sets
related_skills_for_graph_view:
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[convert-trips-to-routes]]"
  - "[[create-single-intersection]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[construct-and-verify-braess-paradox]]"
  - "[[sweep-rerouting-device-market-penetration]]"
  - "[[compare-one-way-vs-two-way-street-grid-conversion]]"
  - "[[equilibrate-departure-time-choice-in-bottleneck-model]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[specify-route-choice-models-and-generate-route-sets]]"
---

# Dynamic User Equilibrium and Wardrop's Principle

**Dynamic User Equilibrium (DUE)** is the traffic-assignment condition where no driver could improve their own travel time by unilaterally switching to a different available route — **Wardrop's first principle**: at equilibrium, all routes actually *used* between a given origin-destination pair have approximately equal travel time, and any *unused* alternative would be at least as costly. This is fundamentally different from single-shot shortest-path routing (`duarouter` alone, see [[duarouter]]), which computes one route per vehicle against static free-flow weights and never revisits the choice even as congestion builds — that approach can dump 100% of demand onto the nominally-shortest path regardless of how badly it congests. DUE is also fundamentally *offline*: it converges a static route split before the simulation of record ever runs. Contrast with [[incident-rerouting-and-closures]], where the rerouting device adapts routes *live*, mid-simulation, in response to a disruption that wasn't known when demand was generated. Also contrast with [[marouter-macroscopic-assignment]], which computes an equilibrium-like route split purely analytically, with no simulation in the loop at all — a verified case found its capacity-constrained prediction can diverge substantially from the genuine microscopic equilibrium DUE's iterated approach converges to.

## Computing it: duaIterate.py

`duaIterate.py` (in `$SUMO_HOME/tools/assign/`, not the `tools/` root) iterates `duarouter` + `sumo`: route the demand, simulate it, derive updated edge-weight costs from the simulated (congested) travel times, re-route a fraction of vehicles toward cheaper alternatives (via the Gawron or logit route-choice model), and repeat until route choice stabilizes. Each iteration lands in its own numbered subdirectory (`000/`, `001/`, ...) with that iteration's routed demand and simulation output — parse these directly to build a convergence trace (mean travel time and the fraction of vehicles that changed routes, per iteration). A well-converging scenario shows the route-change fraction collapsing from roughly 50% at the first re-route to near-zero within a handful of iterations.

## Verifying Wardrop's principle properly: check two different costs

The critical, easy-to-miss methodological point: **`duaIterate`'s route choice is driven by an edgeData dump of per-edge travel times, which only measures vehicles already on an edge.** A vehicle still queued at the origin, waiting to be inserted into the simulation because a downstream bottleneck is oversaturated, accrues real delay (`departDelay` in `tripinfo`) that is completely invisible to this cost signal. This means Wardrop's principle should be tested on **two different definitions of cost**, and they can give different answers:

1. **In-network duration** (the router-visible cost) — this is what `duaIterate` actually equilibrates.
2. **Total experienced time** = in-network duration + `departDelay` — what a traveler actually experiences door-to-door.

In one verified test (a fast-but-capacity-limited "freeway" route vs. a slower-but-higher-capacity "arterial" route, oversaturating one-shot demand): at the computed DUE, in-network duration was 182.1s (freeway) vs. 184.3s (arterial) — a 1.2% gap, comfortably "approximately equal." But total experienced time was 218.3s vs. 204.3s — a **6.6% gap**, exceeding a reasonable 5% "approximately equal" threshold. Checking only the in-network number would have produced an overstated "Wardrop reached" conclusion; the honest answer was **reached for in-network cost, not for total experienced cost**.

## If a total-time gap remains: split error, or ordering artifact?

Don't assume a residual total-time gap means the equilibrium's route *split* is wrong. Test it: re-simulate the *same* converged route-choice fractions, but with vehicles' departure times cleanly **interleaved** across routes instead of using `duaIterate`'s actual emitted departure ordering. In the verified case, `duaIterate` had emitted short bursts of up to 9 consecutive same-route departures — enough to transiently exceed the capacity-limited route's insertion headroom and back up as departure delay for that burst, an effect invisible to the edge-weight router. Interleaving the same split evenly eliminated the departure delay entirely on both routes and *lowered* total network-wide travel time below `duaIterate`'s own converged result. **Conclusion: the route-choice fractions were correct; only the fine-grained timing of *when* each route's vehicles depart was suboptimal for total time** — a dimension `duaIterate` doesn't optimize at all, since it only ever adjusts *which* route a vehicle takes, never *when* it departs.

## Practical takeaways

- Engineer a genuine trade-off between routes when building a test scenario — one route fast-but-capacity-limited, one slower-but-higher-capacity — or there's no real route choice to observe.
- Use a `zipper`-type merge (not `priority`) where parallel routes rejoin, to avoid injecting spurious asymmetric congestion at the merge itself unrelated to either route's own capacity (see [[ramp-metering-with-alinea]] for the same lesson in a different context).
- Run both Gawron (the default) and logit route-choice models and confirm they converge to the same split, as a robustness check on the result.
- Always report both the in-network and total-time Wardrop checks side by side — never just one — and if they disagree, investigate whether it's a genuine assignment error or a departure-ordering artifact before drawing a conclusion.

See the `compute-dynamic-user-equilibrium` skill for the full workflow and a bundled dual-cost Wardrop-check script. [[effort-based-routing-and-eco-routing]] reuses this same iterative duarouter+sumo methodology (and cross-validates against `duaIterate.py` directly) but retargets `--weight-attribute` from travel time onto an emissions/fuel measure, finding the resulting equilibrium can be a strict Pareto improvement over the travel-time DUE precisely because DUE is not the system optimum.
