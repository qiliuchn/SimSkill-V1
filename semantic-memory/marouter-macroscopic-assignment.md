---
summary: marouter performs macroscopic, capacity-constrained traffic assignment from a TAZ/OD matrix without a microsimulation in the loop, with real-behavior gotchas (UE falls back to stochastic SUE, no CLI BPR alpha/beta — capacity comes from the network's road-class/lane-count), and a verified finding that its UE-predicted equilibrium can diverge substantially from true microscopic equilibrium when its built-in capacity reference undershoots real per-lane saturation flow.
keywords:
  - marouter
  - macroscopic-assignment
  - traffic-assignment
  - capacity-constrained
  - volume-delay-function
  - stochastic-user-equilibrium
created: 2026-07-26T09:30:00
last_updated: 2026-08-06T21:24:14
sources:
  - "[[episodic-memory/2026-07-26_09-15-45/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-26_09-15-45/attempts/attempt-1/critic-agent-feedback.json]]"
  - https://sumo.dlr.de/docs/marouter.html
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[od2trips]]"
  - "[[duarouter]]"
  - "[[multi-resolution-modeling-buffer-sizing-and-boundary-handoff]]"
related_skills:
  - assign-traffic-with-marouter
  - compute-dynamic-user-equilibrium
  - convert-od-matrix-to-trips
  - extract-subnetwork-scenario-with-boundary-demand
related_skills_for_graph_view:
  - "[[assign-traffic-with-marouter]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[convert-od-matrix-to-trips]]"
  - "[[extract-subnetwork-scenario-with-boundary-demand]]"
---

# marouter Macroscopic Assignment

`marouter` performs macroscopic, capacity-constrained traffic assignment: given a TAZ/OD matrix ([[od2trips]]'s input format), it computes equilibrium route flows analytically — no microsimulation runs. This is the classic "four-step transportation-planning model" assignment stage, methodologically distinct from [[dynamic-user-equilibrium-and-wardrop]]'s `duaIterate.py`, which iterates real simulation-in-the-loop to reach dynamic equilibrium.

## Assignment methods — real behavior, not just documented names

- **All-or-nothing**: no distinct flag; achieved via `--assignment-method incremental --max-iterations 1` — a single step assigns 100% of each OD pair's demand to its cheapest free-flow route with no capacity feedback.
- **Incremental**: `--assignment-method incremental` with the default multi-step iteration count — loads demand progressively, updating costs between increments.
- **UE**: `--assignment-method UE` **does not necessarily compute deterministic user equilibrium** — verified in one SUMO version, it emits an explicit warning ("Deterministic user equilibrium ('UE') is not implemented yet, using stochastic method ('SUE')") and silently substitutes stochastic UE. Always check `marouter`'s actual stdout for this warning rather than assuming the requested method ran as named.

## Capacity model: built-in, not BPR-parameterized

`marouter` has no CLI-exposed BPR alpha/beta flags. Capacity-constrained cost restraint uses SUMO's **built-in road-class/lane-count-derived volume-delay function** — capacity is inferred from the network's own edge properties, not set via a separate tunable parameter. The realized reference capacity for a given edge is inspectable via `--netload-output`'s `flowCapacityRatio` attribute (realized flow ÷ marouter's internal capacity reference), which is the way to confirm what capacity value was actually used, rather than assuming a textbook default.

## Output format

`marouter`'s route output is a `.rou.xml` `<flow>` element containing a `<routeDistribution>` of alternative routes, each with a `probability` (assigned flow share) and `cost` (assigned travel time under that assignment method).

## Macroscopic prediction can diverge from true microscopic equilibrium

**A macroscopic assignment result is not automatically validated just because it "ran" — it should be checked against microsimulation before being trusted as a real equilibrium prediction.** In one verified case, `marouter`'s UE/SUE-predicted split across two parallel routes (a low-capacity-but-fast route and a high-capacity-but-slower route) did *not* survive contact with microsimulation: the macro model predicted near-equalized travel times, but the actual microsimulation showed the fast route consistently ~10% faster than the slow route at the predicted split — and a genuine split-sweep across multiple splits in microsimulation showed the fast route remained faster at every tested split well beyond marouter's assigned capacity reference for it, meaning the true microscopic equilibrium skews substantially more toward the fast route than marouter predicted.

The diagnosed root cause: `marouter`'s built-in capacity reference for that road class (verified at 800 veh/h/lane via `flowCapacityRatio`) sat well below the route's true microscopic saturation flow (not fully reached even at 1150 veh/h on one lane in the sweep) — so the macro model, believing the route was closer to saturated than it actually was, over-diverted traffic away from it relative to what microsimulation would genuinely produce. Edge-based macroscopic costs also can't see junction/turn/insertion-delay effects that a microsimulation adds on top of pure link travel time. What *did* hold across macro and micro: the qualitative direction of the correction (diverting flow toward the alternate route lowers total system travel time in both the macro cost function and the actual microsimulation) and the absence of over-saturation on either route in the validated microsimulation run.

## Practical implication

Treat a `marouter` assignment result as a fast, capacity-aware *rough estimate* useful for identifying which routes carry meaningful flow and the qualitative direction equilibrium pushes traffic — not as a precise prediction of realized travel times or exact route shares, unless validated against microsimulation for the specific network's actual capacity characteristics. When the two diverge, the mismatch is itself informative: it points to where the macro capacity model's assumptions don't match the network's real microscopic behavior.

See the `assign-traffic-with-marouter` skill for the full build/run/validate workflow and bundled comparison script.
