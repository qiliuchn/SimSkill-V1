---
summary: SUMO's route-choice methods, verified against measured duarouter output rather than documentation — logit is exact plain MNL and only activates on an existing multi-route alternatives file (a fresh duarouter call is always deterministic); --logit.beta/--logit.gamma implement a genuine but imperfect C-Logit overlap correction, while Gawron is exactly overlap-blind (bit-identical 1/3 splits regardless of path overlap) and severely history-dependent at tied costs; an externally-computed, untuned Path-Size Logit beat SUMO's own calibrated C-Logit by roughly half the residual error; logit's documented non-convergence near equilibrium was diagnosed to a measured auto-theta-blows-up-as-costs-converge mechanism and partially fixed via explicit theta plus --weight-memory; and a real engineering decision's benefit was shown to flip SIGN, not just magnitude, between an all-or-nothing and a converged Gawron equilibrium.
keywords:
  - route-choice-model
  - IIA-problem
  - path-overlap
  - C-Logit
  - path-size-logit
  - route-set-generation
  - logit-non-convergence
created: 2026-08-07T10:44:36
last_updated: 2026-08-07T10:44:36
sources:
  - "[[episodic-memory/2026-08-07_10-40-09/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_10-40-09/attempts/attempt-1/critic-agent-feedback.md]]"
related_pages:
  - "[[braess-paradox-in-sumo]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[duarouter]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[information-penetration-and-congestible-routing]]"
related_skills:
  - specify-route-choice-models-and-generate-route-sets
  - construct-and-verify-braess-paradox
  - compute-dynamic-user-equilibrium
  - convert-trips-to-routes
  - create-grid-network
related_skills_for_graph_view:
  - "[[specify-route-choice-models-and-generate-route-sets]]"
  - "[[construct-and-verify-braess-paradox]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[convert-trips-to-routes]]"
  - "[[create-grid-network]]"
---

# Route Choice Model Verification, Overlap, and Route-Set Effects

Every equilibrium and assignment finding in memory implicitly rests on a route-choice model (almost always Gawron, the default) and a route set (whatever `--max-alternatives` produced) — neither of which had ever been verified from measured output. This page holds that verification, closing an open negative result `[[braess-paradox-in-sumo]]` had recorded (logit disagreeing with Gawron in direction at one demand level, never converging at two others). See `specify-route-choice-models-and-generate-route-sets` for the full methodology.

## The route-choice flag is inert on a fresh routing call

`--route-choice-method`/`--logit.*` only do anything once `duarouter` is handed an *existing* multi-route alternatives file to redistribute probability over — a fresh call against plain trips always collapses to a single, deterministic route regardless of the flag. This is exactly the mechanism `duaIterate.py` exploits (feeding its own accumulated alternatives file back in each iteration); a one-shot `duarouter` invocation will not produce a probabilistic split on its own.

## Logit is verified plain MNL with a genuine, imperfect C-Logit correction

Fitting recovered route probabilities against closed forms confirmed SUMO's `logit` is exact Multinomial Logit, P_i ∝ exp(−θ·c_i), with θ applied directly and no internal cost rescaling — a real scale-sensitivity pitfall, since a 10× rescale of route costs at fixed θ can push a moderate three-way split to a near-deterministic one. `--logit.beta`/`--logit.gamma` were confirmed to implement a genuine C-Logit commonality-factor term (structurally verified: either parameter at zero exactly zeroes the correction, and the correction's magnitude peaks at low γ and decays as γ grows, matching the closed form).

## Gawron is exactly overlap-blind; logit's correction is real but has a bounded residual error

On an independently-verified overlap testbed (Daganzo-Sheffi loop-hole network, ground truth from a from-scratch Monte-Carlo probit model — never taken from SUMO output), **Gawron produced the identical 1/3:1/3:1/3 split at every tested overlap fraction**, with zero response to path overlap — it only ever sees a route's scalar total cost, structurally incapable of the IIA correction real route-overlap requires. Plain MNL (logit with β=0) shows the identical blindness. **Calibrated C-Logit responds correctly in direction and shape** as overlap grows and can be tuned to closely match the ground truth's asymptotic behavior, but even calibrated it leaves a genuine, bounded residual error of a few percentage points at intermediate overlap — tuning alone does not eliminate it. A standalone, **untuned** Path-Size Logit implementation beat SUMO's own calibrated C-Logit by roughly half that residual error, and was confirmed (via realized route shares from simulation output, not the input file) to be genuinely honored when supplied to `sumo` directly as a `.rou.alt.xml`/`routeDistribution`.

## The route set is part of the model specification

Different route-set generation methods (k-shortest-paths, link-penalty, `duarouter`'s own accumulated pool, Monte-Carlo weight perturbation) cover substantially different fractions of the routes actually used in a long, converged run on the same network — verified to range from well under half to well over three-quarters across methods on an identical OD pair. Before attributing an assignment difference to the choice *model*, check whether the candidate route *set* itself is driving it. When isolating the route-set effect (choice model held fixed, only the set varied), establish the CRN replication noise floor first — at moderate sample sizes, seed-to-seed sampling noise in route shares can be large enough to make a clean separation from a genuine route-set effect statistically impossible, and this should be reported honestly as inconclusive rather than forced into a directional claim.

## Diagnosing and fixing logit's non-convergence near equilibrium

The open failure this page closes: `duaIterate.py --logit` (or bare `--logit`, which defaults to auto-θ) oscillating near-all-or-nothing or disagreeing with Gawron in the direction of an effect. **Root cause, measured directly**: SUMO's default auto-θ scales as approximately a constant divided by the spread of competing route costs, verified constant across a several-thousand-fold range of spreads. Since Wardrop equilibrium is by definition the state where competing route costs converge (spread → 0), auto-θ mechanically explodes exactly as an iterative search approaches its own goal, forcing pathological near-deterministic reassignment at the worst possible moment. A naive fix (just picking one fixed θ) is insufficient on its own — because logit is exactly memoryless (verified: recomputes identically from the same costs regardless of prior state, unlike Gawron which is strongly history-dependent), a fixed θ with no other damping trades the blow-up for a different failure: near-100% route churn every iteration, converging to the wrong split.

**Working recipe**: explicit fixed θ combined with `duaIterate.py --weight-memory` (which smooths edge weights across iterations, externally supplying the damping logit structurally lacks). Verified over dozens of real iterations to restore genuine, monotonically-decaying route-change fractions rather than oscillation, on both a simple network (clean convergence to a fixed point) and a genuine Braess-paradox topology (convergent behavior restored, though converging measurably more slowly than Gawron — verify actual convergence within your iteration budget rather than assuming the recipe guarantees it in a fixed number of steps). This diagnosis and fix should be read as a genuine advance on the open failure recorded in `[[braess-paradox-in-sumo]]`, not a complete resolution — the fixed recipe was not confirmed to reach Gawron's exact converged split within the tested iteration budget on the harder topology.

## Route-choice regime can flip an engineering decision's sign

Verified directly on a real "build this link or not" decision: an all-or-nothing assignment recommended building it (a clear, CRN-replicated positive benefit), while a properly converged Gawron dynamic user equilibrium on the identical network and demand recommended against building it (a genuine Braess-paradox-style harm) — the recommendation's **sign flipped completely**, not merely its magnitude, between assignment regimes. Any project- or intervention-benefit claim computed under a single route-choice assumption — especially all-or-nothing, the cheapest and most common default for a quick check — should be treated as provisional until checked against at least one genuinely converged, stochastic alternative.

## Caveat for existing memory findings

`[[braess-paradox-in-sumo]]`'s magnitudes (the ~39%/38% helped/hurt figures, Price of Anarchy 1.43) rest on Gawron with default settings — a model now shown to be exactly overlap-blind and capable of severe history-lock at tied costs. These should be read as "the Gawron-consistent equilibrium," not "the unique equilibrium." Any other memory finding that used bare `duaIterate --logit` (default auto-θ, no `--weight-memory`) to confirm or refute a Gawron-based result should carry the same caveat — a disagreement between the two models is not on its own evidence that logit is simply broken; check the auto-θ and weight-memory settings first.
