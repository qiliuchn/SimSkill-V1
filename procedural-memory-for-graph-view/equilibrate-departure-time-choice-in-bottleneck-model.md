---
name: equilibrate-departure-time-choice-in-bottleneck-model
description: Use this skill when the user wants to model a Vickrey-style morning-commute bottleneck in SUMO with ENDOGENOUS departure time — travellers trading queueing delay against schedule (early/late arrival) delay, converging to a departure-time user equilibrium — as opposed to every other demand skill in memory, which treats departure time as fixed and only optimizes route choice. Covers measuring a genuinely constant-rate bottleneck server, an outer iteration loop that shifts departure times toward lower generalized cost, why naive day-to-day adjustment dynamics can fail to converge for this equilibrium (unlike route-choice DUE), a two-part empirical equilibrium verification (cost-equality plus real probe vehicles testing unused slots), and constructing/testing a time-varying congestion toll against zero-toll and flat-toll controls. Trigger on mentions of departure-time choice, schedule delay, Vickrey bottleneck, peak spreading, or time-varying congestion pricing.
related_skills:
  - compute-dynamic-user-equilibrium
  - construct-and-verify-braess-paradox
  - equilibrate-endogenous-mode-choice-with-transit-supply-feedback
  - model-cordon-tolling-with-generalized-cost-surcharge
  - compare-zipper-vs-default-merge-at-lane-drop
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[construct-and-verify-braess-paradox]]"
  - "[[equilibrate-endogenous-mode-choice-with-transit-supply-feedback]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[compare-zipper-vs-default-merge-at-lane-drop]]"
  - "[[quantify-sumo-run-to-run-variability]]"
related_pages:
  - "[[vickrey-bottleneck-departure-time-equilibrium]]"
---

# Equilibrate Departure-Time Choice in a Bottleneck Model

Models the classic Vickrey (1969) morning-commute bottleneck problem in SUMO: a fixed population of travellers, each with a desired arrival time, choosing WHEN to depart (not which route) to trade off queueing delay against schedule (early/late) delay, converging to a departure-time user equilibrium — a genuinely different equilibrium concept from every other skill in memory, all of which treat departure time as exogenous and only equilibrate route choice.

## Measuring a genuinely constant-rate bottleneck server

Before anything else, measure the bottleneck's discharge capacity from a real saturated run (per-interval speed/occupancy criteria, not assumed) — the analytical Vickrey comparison later depends on this measured value, not a nominal one. **The junction type at the lane drop matters more than usual here**: a `priority`-type merge can let discharge rate drift with queue state (yielding behavior changes as approach density changes), which corrupts the constant-service-rate assumption the whole analytical framework depends on. A `zipper`-type merge gives a much more constant discharge rate across queue states — prioritize discharge-rate *stability* over raw discharge *magnitude* when choosing the merge type for this kind of analytical-comparison scenario (a genuinely useful design decision, though document it with an actual before/after measurement kept as raw data — don't rely on memory of an informal comparison, which won't survive independent review).

## The outer iteration loop: departure time, not route, is the shift variable

Structure the outer loop like `compute-dynamic-user-equilibrium`'s `duaIterate` pattern — simulate, read realized outcomes, compute generalized cost, shift a fraction of the population toward lower-cost choices, repeat — but shift **departure time** (rewriting `<vehicle depart=...>` between runs) instead of route. Use a standard generalized cost `alpha*TT + beta*max(0, t*-arrival) + gamma*max(0, arrival-t*)` with `beta < alpha < gamma` (steepest penalty for lateness, shallower for earliness, both valued relative to travel time). Include real `departDelay` (origin-insertion queueing) in the travel-time term, per `compute-dynamic-user-equilibrium`'s established discipline of using total experienced cost, not just router-visible cost.

## Verified, transferable finding: this equilibrium can be a REPELLING fixed point of naive adjustment

**This is the single most important methodological finding for anyone attempting this kind of model.** Unlike route-choice DUE (where MSA/Gawron-style day-to-day adjustment reliably converges), a departure-time equilibrium's natural adjustment dynamic can **diverge away from the true equilibrium even when started exactly at it**. The mechanism: a queue's externality runs strictly forward in time (a traveller who departs at time `t` imposes delay on everyone departing after `t`, and on nobody before `t`), making the cost Jacobian triangular and non-normal — a structural property that causes best-response-style or proportional-swap adjustment dynamics to rotate away from the fixed point rather than contract onto it. Verified: multiple adjustment schemes (all-or-nothing/low-temperature logit, local cost-gradient/"advection," proportional swap) all failed to converge in genuine SUMO-in-the-loop iteration, and shrinking the step size only delayed the divergence, never prevented it.

**Practical consequence**: don't assume `compute-dynamic-user-equilibrium`'s MSA playbook transfers to departure-time choice. Instead, solve an **equilibrium gap function** directly (minimize the deviation from the equal-cost condition across departure slots) using a fast analytical surrogate model (e.g. a point-queue/vertical-queue approximation using the measured capacity and free-flow time) as the inner solver, with a per-slot correction term learned via MSA against real SUMO cost measurements. This hybrid approach — solve the surrogate's structure, correct its residual against ground truth — converges where naive pure-simulation iteration does not.

## Verifying the equilibrium properly: two distinct tests, not one

1. **Cost equality across used slots**: the demand-weighted standard deviation of generalized cost across departure slots that carry nonzero traffic should be small. **Report both in-sample (from the same runs used to fit the equilibrium) and out-of-sample (independent re-measurement at fresh seeds) figures** — the out-of-sample number is the honest one, since in-sample tightness partly reflects fitted noise rather than a genuinely converged equilibrium.
2. **No unused slot is cheaper** (the second Wardrop-style condition): test this with **real probe vehicles** genuinely inserted into empty departure slots (small perturbations, e.g. under 1% of total demand, spread across many otherwise-unused slots) and measure their actual realized cost via a real SUMO run — don't just compute this analytically. A converged equilibrium should show every probed empty slot costing at least as much as the used-slot mean, with only noise-level exceptions.

## Comparing against closed-form Vickrey predictions — expect some metrics to match closely and others not

Verified pattern: **shape and timing metrics reproduced very closely** (peak duration ≈ N/s, first/last departure times, peak queue length, the fraction of travellers arriving early vs. late) — typically within 1% of the closed-form prediction. **Delay and cost *levels* reproduced less closely** (5-10% gaps are plausible) — attributable to real physical effects the point-queue analytical model omits: a small but real capacity-drop effect (discharge rate during the equilibrium peak can differ measurably, e.g. ~1%, from the deeply-saturated capacity-measurement rate), and more substantially, the queue being genuinely physical rather than a zero-space vertical queue (finite acceleration/deceleration, real storage length, imperfect FIFO ordering when multiple lanes feed a merge). **Quantify each contributing effect's share of the gap explicitly and verify each contribution's arithmetic against the same formula used for the main comparison** — a plausible-sounding explanation (e.g. "a small capacity difference gets amplified in the delay integral") needs to actually be recomputed and checked, not just asserted, since the direction and magnitude of such amplification effects can be non-obvious.

## Testing a time-varying toll: build it correctly, and don't assume the textbook neutrality result holds

The theoretically optimal time-varying toll tracks queueing delay as a function of **arrival** time, not departure time: `toll(t_depart) = alpha * Q_notoll(t_depart + free_flow_time)`, where `Q_notoll` is the no-toll equilibrium's queueing delay profile. **A common implementation bug**: using `Q_notoll(t_depart)` directly (indexing by departure rather than arrival time) shifts the toll's peak substantially earlier than it should be — verify the toll profile's timing against the theoretical peak location before trusting it.

**Verified finding: the toll reduced queueing substantially and preserved throughput/capacity (confirmed via discharge-rate invariance across toll conditions — the toll only changes perceived cost, never real capacity), but did NOT achieve the textbook "buys back exactly what it costs" result at the precision this study could measure.** Total generalized cost including the toll paid rose measurably (a few percent, statistically significant) rather than staying flat — the toll charged somewhat more than it saved travellers in reduced queueing time. **Report this honestly rather than assuming the classical result must hold** — it's a strong theoretical prediction from an idealized point-queue model, and a genuinely simulated bottleneck with physical queue effects, discretized departure slots, and finite-precision equilibrium convergence can plausibly miss it by a real, measurable margin.

**Essential controls**:
- **Zero-toll negative control**: running the toll mechanism at zero should reproduce the no-toll baseline exactly (bit-for-bit identical per-seed results) — this is the cleanest proof the toll mechanism only changes behavior when genuinely nonzero.
- **Flat (time-invariant) equal-revenue toll**: this should leave the queue largely intact (possibly even statistically *worse* than no toll) — cleanly isolating that it's the toll's time-*variation*, not its magnitude/revenue, that reduces queueing. If a flat toll accidentally reduces queueing as much as the time-varying toll, something in the toll construction is wrong.

## Gotchas

- **A `priority`-type lane drop's discharge rate can drift with queue state**, corrupting the constant-service-rate assumption an analytical bottleneck comparison depends on — use `zipper` for a more stable discharge rate, and verify the stability claim with actual retained measurements, not an informal comparison.
- **Naive day-to-day adjustment dynamics (MSA, proportional swap, logit) are not guaranteed to converge for a departure-time equilibrium**, even when started exactly at the true equilibrium — the forward-in-time queue externality makes this equilibrium concept structurally different from route-choice DUE. Use a gap-function/surrogate-corrected solver instead of assuming an MSA loop will work.
- **A toll must be indexed by arrival time, not departure time**, when it's meant to track queueing delay experienced by travellers — an easy-to-make sign/indexing error shifts the toll profile's peak substantially.
- **Don't assume the classical "toll buys back exactly what it costs" result holds in a genuinely simulated (non-idealized) bottleneck** — verify it explicitly with a statistical test on real per-traveller cost data, and report the actual gap if the idealized result doesn't hold.
- **Always run a flat-toll control alongside the time-varying toll** — this is what isolates whether time-variation specifically (not just charging money) is doing the queue-reduction work.

## Related

- `compute-dynamic-user-equilibrium` — the structural template for this skill's outer iteration loop (route choice instead of departure time); this skill found its MSA convergence discipline does NOT transfer directly to departure-time choice, requiring a different (gap-function/surrogate) solution method.
- `construct-and-verify-braess-paradox` — the sibling route-choice equilibrium/paradox skill; together with this skill and `equilibrate-endogenous-mode-choice-with-transit-supply-feedback`, completes the classical trio of traveller-choice-dimension equilibria in this memory (route, departure-time, and mode choice, respectively).
- `model-cordon-tolling-with-generalized-cost-surcharge` — the closest existing tolling precedent (spatial, flat-rate); this skill's toll is temporal and time-varying — a genuinely different mechanism (changing WHEN people travel, not WHERE).
- `compare-zipper-vs-default-merge-at-lane-drop` — the zipper-vs-priority merge-type comparison this skill's bottleneck-stability design choice draws on.
- `quantify-sumo-run-to-run-variability` — the replication/CRN methodology this skill's toll-vs-control comparison applies.
- [[vickrey-bottleneck-departure-time-equilibrium]] — the verified falsified-toll-neutrality finding, the repelling-equilibrium-dynamics finding, and the quantified analytical-vs-simulated gaps.
- `equilibrate-endogenous-mode-choice-with-transit-supply-feedback` — the sibling mode-choice equilibrium skill (a ridership-to-frequency supply feedback rather than a forward-in-time queue externality); found a related but distinct instability pattern — a second unstable equilibrium with a narrow one-sided basin, rather than universal divergence from the true equilibrium.
