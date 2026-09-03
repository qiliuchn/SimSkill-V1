---
summary: Braess's Paradox — adding a road link can make equilibrium travel time worse for every driver — was empirically reproduced in SUMO on a classic S-A-B-T topology with measured (not assumed) flow-dependent/flow-independent link costs; below a demand threshold of ~1641 veh/h the added link helped, above it the link hurt by up to 38%, and the effect faded again above ~3400 veh/h as the paradox-causing route's equilibrium share collapsed, with a Price of Anarchy of 1.43 at the worst demand level and an honest finding that the result depends on the route-choice model being able to reach a genuine equilibrium (Gawron did; logit did not).
keywords:
  - braess-paradox
  - price-of-anarchy
  - network-topology
  - selfish-routing
  - wardrop-equilibrium
  - dynamic-user-equilibrium
created: 2026-07-31T12:15:00
last_updated: 2026-08-07T10:44:36
sources:
  - "[[episodic-memory/2026-07-31_11-45-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_11-45-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[vickrey-bottleneck-departure-time-equilibrium]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[neighborhood-traffic-calming-displacement-and-evaporation]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[route-choice-model-verification-overlap-and-route-set-effects]]"
related_skills:
  - construct-and-verify-braess-paradox
  - compute-dynamic-user-equilibrium
  - scan-network-link-criticality-and-vulnerability
  - evaluate-neighborhood-traffic-calming-and-cut-through-displacement
  - specify-route-choice-models-and-generate-route-sets
related_skills_for_graph_view:
  - "[[construct-and-verify-braess-paradox]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[evaluate-neighborhood-traffic-calming-and-cut-through-displacement]]"
  - "[[specify-route-choice-models-and-generate-route-sets]]"
---

# Braess's Paradox in SUMO

Braess's Paradox is the classic result in network flow theory that adding a new link to a congested road network — even a fast, high-capacity one — can make equilibrium travel time **worse for every driver**, because selfish route choice (Wardrop equilibrium, see [[dynamic-user-equilibrium-and-wardrop]]) does not optimize total system cost, only each individual's own cost given everyone else's choices. This page documents its first empirical reproduction in this memory: a genuinely topology-driven counter-intuitive result, distinct from every other verified counter-intuitive finding in memory, which involve a control mechanism (e.g. perimeter gating, ramp metering) or a demand-shape effect rather than network structure interacting with selfish routing.

## Verified finding: the paradox reproduces, with a clean threshold and a fade-out

On the classic S-A-B-T diamond topology (two flow-dependent links whose travel time rises steeply with volume, two flow-independent links whose travel time stays near-constant, plus a nearly-costless cross link enabling a "zig-zag" route through both node classes), with dynamic user equilibrium computed via `duaIterate` and demand swept across 12 levels:

- **Below a demand threshold of ~1641 veh/h, adding the cross link helped** — equilibrium travel time fell by as much as 39% at low demand.
- **Above the threshold, the added link strictly hurt every driver** — equilibrium travel time rose by up to **38%** at the worst-affected demand level, despite the network having strictly more infrastructure than the no-link alternative.
- **The paradox faded again above ~3400 veh/h**, as the zig-zag route's equilibrium share collapsed from effectively 100% at low demand to near-zero (~0.1%) at the highest demand tested — consistent with the theoretical mechanism (once the flow-independent links alone are saturated, routing through the zig-zag no longer offers any advantage worth taking).
- **Wardrop's first principle held at every measured equilibrium**, checked on both in-network duration and total experienced time (including origin-insertion delay) — the two cost definitions agreed closely in this topology, unlike a prior verified case in a different network where they diverged; this should always be checked, not assumed, for any new topology.
- **Equilibrium costs matched a closed-form prediction** derived from the measured link-performance functions, providing an independent cross-check beyond internal consistency.

## Distinguishing genuine effect from artifacts

Two confounds were explicitly tested and largely ruled out:

- **Departure-ordering artifact**: re-simulating the converged equilibrium with departures cleanly interleaved across routes (instead of `duaIterate`'s actual emitted ordering) reduced the measured paradox only modestly — roughly one-ninth of the total effect was attributable to ordering, the rest was genuine route-choice-induced congestion.
- **Network-conflict artifact**: a naive lane-wiring at the topology's diverge junction initially created a hidden `netconvert`-resolved yielding conflict that artificially capped throughput in the middle of the demand range of interest — a silent, topology-invalidating bug, only caught by directly auditing the compiled network's junction request/foes matrix, not by inspecting the source XML alone.

## Verified finding: Price of Anarchy ≈ 1.43

At the worst-affected demand level, the selfish equilibrium's network-mean travel time was **43% worse** than the best coordinated route split found by a grid search over the zig-zag route's assignment probability. Notably, the true system optimum was **not** simply "forbid the zig-zag route entirely" — a small but nonzero zig-zag share (~10%, versus ~45% at the selfish equilibrium) performed better than zero, showing the zig-zag route isn't worthless, just badly over-used under selfish routing.

## Honest limitation: the result depends on the route-choice model reaching equilibrium at all

A robustness check comparing SUMO's two route-choice models (Gawron, the default, vs. logit) **failed** — logit disagreed with Gawron in the *direction* of the effect at one demand level, and never converged to a stable route split at two others even after sweeping its temperature parameter, oscillating between near-all-or-nothing assignments instead. This is reported as a genuine finding, not hidden: **a paradox demonstration implicitly assumes drivers behave as near-perfect, converged cost-minimizers**, and the magnitude reported here rests specifically on the route-choice model (Gawron) that actually reached a demonstrable equilibrium in this topology.

## Practical takeaways

- Measure link-performance functions from real simulation output (per-vehicle `--vehroute-output.exit-times`, not `edgeData`'s aggregated travel time) before claiming any cost-structure assumption — the two data sources can disagree by a few percent.
- Audit every diverge/merge junction's compiled request/foes matrix for hidden yield conflicts before trusting a synthetic topology — a lane-wiring mistake can silently cap throughput exactly where the interesting demand range is.
- Check Wardrop's principle on both in-network and total-experienced-time cost definitions for any new topology — don't assume a prior finding about their (dis)agreement transfers.
- Run a departure-ordering-artifact check before attributing the full effect to route choice.
- A two-endpoint Price-of-Anarchy comparison likely understates the gap to true system optimum — grid-search intermediate coordinated splits.
- Test route-choice-model robustness explicitly, and report a failure to converge or a directional disagreement as a real finding rather than discarding the alternate model's run.

See the `construct-and-verify-braess-paradox` skill for the full topology-construction, measurement, and verification workflow.
