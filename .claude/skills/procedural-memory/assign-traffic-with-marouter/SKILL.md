---
name: assign-traffic-with-marouter
description: Use this skill when the user wants to perform macroscopic, capacity-constrained traffic assignment in SUMO using marouter — computing equilibrium route flows from a TAZ/OD matrix analytically, without a microsimulation in the loop. Covers TAZ/OD input setup, marouter's real assignment methods (all-or-nothing via incremental with one iteration, incremental, and UE which actually falls back to stochastic UE/SUE), its built-in road-class/lane-count capacity model (no CLI BPR alpha/beta), route-alternatives/netload output parsing, and — critically — validating a macroscopic assignment prediction against actual microsimulation rather than trusting it in isolation. Trigger on mentions of marouter, macroscopic assignment, static traffic assignment, or capacity-constrained route choice.
---

# Assign Traffic with marouter

Performs macroscopic, capacity-constrained traffic assignment using `marouter` — SUMO's analytical route-choice tool, computing equilibrium flows from a TAZ/OD matrix without ever running a microsimulation. This is SimSkill's macroscopic counterpart to `compute-dynamic-user-equilibrium`'s `duaIterate.py` (simulation-in-the-loop dynamic equilibrium): `marouter` is the classic "four-step model" assignment stage, fast but working from an abstracted capacity model rather than real vehicle dynamics.

## TAZ and OD input

`marouter` takes the same TAZ/OD-matrix inputs as `od2trips` (see `convert-od-matrix-to-trips`): a `<tazs>` file defining origin/destination districts and their source/sink edges, and an O-format or `tazRelation` OD matrix.

```bash
marouter -n net.xml -d od/districts.taz.xml -Z od/demand.od \
    --assignment-method incremental --max-iterations 1 -o out/aon.rou.xml --netload-output out/aon_netload.xml
```

## Assignment methods — verify real behavior, don't assume documented semantics

- **All-or-nothing**: not a distinct named method — achieved via `--assignment-method incremental --max-iterations 1` (a single incremental step dumps 100% of demand onto each OD pair's single cheapest route at free-flow cost, with no capacity feedback).
- **Incremental**: `--assignment-method incremental` with the default (multi-step) iteration count — loads demand in increments, updating edge costs between increments, progressively spreading flow as costs rise.
- **UE**: `--assignment-method UE` — **verify this actually implements what's requested.** In at least one SUMO version, `marouter` does *not* implement deterministic user equilibrium; it emits an explicit warning ("Deterministic user equilibrium ('UE') is not implemented yet, using stochastic method ('SUE')") and falls back to stochastic UE instead. Check `marouter`'s actual stdout for this warning before assuming a deterministic-UE result.

## Capacity model: no CLI BPR alpha/beta

`marouter --help` has no `--bpr-alpha`/`--bpr-beta`-style flags. Capacity-constrained cost restraint instead uses SUMO's **built-in road-class/lane-count-derived volume-delay function** — capacity is inferred from the network's edge properties (lane count, speed, road type), not set by hand-tunable BPR parameters. Confirm the actual reference capacity `marouter` used for a given edge via `--netload-output`'s `flowCapacityRatio` attribute (realized flow ÷ marouter's reference capacity for that edge) rather than assuming a textbook BPR default.

## Parsing route-alternatives and netload output

`marouter`'s primary output is a `.rou.xml` with a `<flow>` containing a `<routeDistribution>` of alternative routes, each carrying `probability` (its assigned flow share) and `cost` (its assigned travel time under that method). `scripts/compare_marouter_methods.py` classifies each route by a marker edge id (works for any two-or-more-route network without hand-editing per scenario) and tabulates flow/cost/cost-gap across multiple method runs side by side:

```bash
python scripts/compare_marouter_methods.py \
    --out-dir marouter_out --run "all-or-nothing=aon" --run "incremental=incremental" --run "UE/SUE=ue" \
    --route-markers "short:SHORT,long_a:LONG" --out-json split_summary.json
```

## Validate the macroscopic prediction against microsimulation — don't trust it in isolation

**A macroscopic assignment's predicted equilibrium is not guaranteed to match what a microsimulation of the same demand actually produces**, because the macro capacity model is an abstraction that can diverge from real microscopic saturation behavior. Load the assigned routes into an actual `sumo` run of the same OD demand and check whether the realized in-network travel times on the used routes are genuinely close (consistent with the macro equilibrium claim) — don't report a macroscopic UE result as validated without this step.

In one verified case, `marouter`'s UE/SUE-predicted split did **not** survive contact with microsimulation: the macro model predicted near-equalized travel times across two routes, but the actual microsimulation showed one route consistently ~10% faster than the other at every tested split up to well beyond the macro capacity reference — because `marouter`'s built-in capacity reference for that road class sat well below the route's true microscopic saturation flow, causing the macro model to over-divert traffic relative to what microsimulation would actually produce. A capacity mismatch like this is a genuine, reportable finding, not evidence the task failed — sweep several splits in microsimulation (not just the macro-predicted one) to characterize how far off the macro prediction actually is, and identify the likely cause (capacity-reference mismatch, or junction/insertion delay effects the edge-based macro cost can't see).

## Gotchas

- **`marouter --assignment-method UE` may silently (well, with a warning, not silently — but easy to miss) fall back to stochastic UE** rather than computing deterministic equilibrium — check the actual stdout warning.
- **There's no BPR alpha/beta to tune** — capacity restraint is governed by the network's own road-class/lane-count properties, inspectable via `--netload-output`'s `flowCapacityRatio`, not by a separate volume-delay-function parameter.
- **A macroscopic UE prediction can diverge substantially from true microscopic equilibrium** if the macro capacity reference doesn't match real per-lane saturation flow — always validate in microsimulation before treating a `marouter` UE result as ground truth for anything beyond a rough, capacity-aware estimate.

## Related

- `compute-dynamic-user-equilibrium` — SimSkill's simulation-in-the-loop dynamic equilibrium skill (`duaIterate.py`); contrast against `marouter`'s purely analytical, microsimulation-free assignment.
- `convert-od-matrix-to-trips` (`od2trips`) — the TAZ/OD-matrix input format `marouter` shares.
- `run-simulation`, `analyze-simulation-outputs` — general run/analysis skills this one specializes for the macro-vs-micro validation comparison.
- [[marouter-macroscopic-assignment]] — the underlying `marouter` mechanics, the real-behavior gotchas, and the verified macro-vs-micro divergence finding.
