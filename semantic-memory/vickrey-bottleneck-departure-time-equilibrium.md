---
summary: A verified SUMO implementation of the Vickrey morning-commute bottleneck model — the first departure-time (rather than route-choice) user equilibrium in this memory — found the equilibrium is a genuinely REPELLING fixed point under natural day-to-day adjustment dynamics (requiring a gap-function surrogate solver instead of standard MSA iteration), reproduced closed-form Vickrey timing/shape predictions to within 1% while delay/cost levels diverged 4-9% from physical-queue effects, and falsified the classic "time-varying tolling buys back exactly what it costs" result at measurable precision — the toll eliminated most queueing delay and preserved throughput but raised total generalized cost including the toll by several percent, while a flat equal-revenue toll left the queue intact, isolating time-variation (not toll magnitude) as the active ingredient.
keywords:
  - Vickrey-bottleneck
  - departure-time-choice
  - schedule-delay
  - peak-spreading
  - time-varying-tolling
  - congestion-pricing
created: 2026-07-31T22:55:00
last_updated: 2026-07-31T22:55:00
sources:
  - "[[episodic-memory/2026-07-31_19-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_19-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[cordon-tolling-and-e3-detectors]]"
  - "[[braess-paradox-in-sumo]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
related_skills:
  - equilibrate-departure-time-choice-in-bottleneck-model
  - compute-dynamic-user-equilibrium
  - model-cordon-tolling-with-generalized-cost-surcharge
  - equilibrate-endogenous-mode-choice-with-transit-supply-feedback
related_skills_for_graph_view:
  - "[[equilibrate-departure-time-choice-in-bottleneck-model]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[model-cordon-tolling-with-generalized-cost-surcharge]]"
  - "[[equilibrate-endogenous-mode-choice-with-transit-supply-feedback]]"
---

# Vickrey Bottleneck Departure-Time Equilibrium

Every route-choice equilibrium concept in this memory ([[dynamic-user-equilibrium-and-wardrop]], `compute-dynamic-user-equilibrium`) treats departure time as fixed and exogenous. This page documents the first **departure-time** equilibrium in this memory — the classic Vickrey (1969) morning-commute bottleneck model, where a fixed population of travellers with a common desired arrival time choose *when* to depart, trading queueing delay against schedule (early/late arrival) delay, implemented and verified in SUMO for the first time. See `equilibrate-departure-time-choice-in-bottleneck-model` for the full construction and equilibrium-solving methodology.

## Verified, transferable finding: the equilibrium is a repelling fixed point

Route-choice user equilibrium (Wardrop, computed via `duaIterate`'s MSA/Gawron-style day-to-day adjustment) reliably converges in this memory's prior experience. **The departure-time equilibrium does not share this property.** Starting a day-to-day adjustment dynamic exactly at the closed-form Vickrey equilibrium, multiple adjustment schemes (proportional swap, all-or-nothing/logit, local cost-gradient) all **diverged away** from it under genuine SUMO-in-the-loop iteration, and shrinking the adjustment step size only delayed the divergence rather than preventing it. The mechanism: a queue's externality runs strictly forward in time — a traveller departing at time `t` imposes delay on everyone departing after `t` and on nobody before `t` — making the cost sensitivity structure triangular and non-normal, a property that causes best-response-style dynamics to rotate away from a fixed point rather than contract toward it. **The practical consequence**: computing this equilibrium requires a different method than the MSA iteration that works for route choice — a gap-function solver (minimizing deviation from the equal-cost condition directly, using a fast analytical surrogate corrected against real SUMO measurements) succeeded where naive iterative adjustment did not.

## Verified finding: shape/timing predictions hold closely, delay/cost levels diverge more

Comparing the converged SUMO equilibrium against closed-form Vickrey analytical predictions (computed from the network's independently-measured bottleneck capacity and free-flow travel time): **peak duration, first/last departure times, peak queue length, and the fraction of travellers arriving early vs. late all matched within about 1%.** **Total and mean queueing delay, and total equilibrium cost, matched less closely (roughly 4-9% off)** — systematically *cheaper* in SUMO than the idealized theory predicts. Contributing factors, in rough order of importance: a modest real capacity-drop effect (discharge rate during the simulated equilibrium peak differs slightly, ~1%, from a deeply-saturated capacity-measurement run) and, more substantially, the queue being genuinely physical rather than the idealized theory's zero-space "vertical" queue — real vehicles decelerate/accelerate over finite distance, occupy real road length, and (when multiple lanes feed a single merge) don't maintain strict first-in-first-out order. **Shape and timing are robust to these physical effects; absolute delay/cost levels are more sensitive to them** — a useful general lesson for comparing any simulated queueing system against an idealized analytical model.

## Verified, falsified headline finding: time-varying tolling does not buy back exactly what it costs

The classic theoretical result is that an optimally-designed time-varying congestion toll (tracking the no-toll equilibrium's queueing-delay profile, shifted to account for travel time to the toll point) eliminates queueing entirely while leaving each traveller's **total** generalized cost (including the toll paid) unchanged — the toll is a transfer that exactly replaces deadweight queueing time with a monetary payment. **This was tested directly and falsified at measurable precision**: the time-varying toll substantially reduced queueing delay (verified: 80%+ reduction, with a refined iteration reaching over 95%) and genuinely preserved bottleneck throughput and physical capacity (discharge rate statistically unchanged across every toll condition — confirming the toll acted purely on perceived cost, never real capacity). But total generalized cost **including the toll paid** rose by a small but statistically significant amount (a few percent) rather than remaining flat — the toll charged somewhat more than it saved travellers in reduced queueing time. **A flat (time-invariant) toll of equal total revenue left the queue essentially intact** (and was, if anything, slightly worse than no toll at all) — cleanly isolating that it is the toll's **time-variation**, not its magnitude or revenue, that does the work of reducing queueing. The zero-toll condition, run through the identical mechanism as a negative control, reproduced the no-toll baseline exactly.

## Practical takeaways

- Don't assume a route-choice equilibrium's convergence method (MSA/Gawron-style day-to-day adjustment) transfers to a departure-time equilibrium — the forward-in-time queue externality structure is fundamentally different and can make the equilibrium a repelling, not attracting, fixed point of naive adjustment.
- Verify any departure-time (or similar forward-externality) equilibrium with two distinct tests: cost equality across used slots (report both in-sample and out-of-sample), and genuine probe-vehicle testing of unused slots — don't rely on cost-equality alone.
- Expect a simulated bottleneck's shape/timing metrics to match an idealized analytical model more closely than its absolute delay/cost levels — physical queue effects (finite space, imperfect FIFO, real acceleration) systematically bias level comparisons more than timing comparisons.
- Never assume a classical tolling-neutrality or similar textbook equilibrium result holds automatically in a genuinely simulated system — test it statistically and report the actual gap if it doesn't hold cleanly.
- Always pair a time-varying policy intervention with a flat/constant-magnitude control at equal total effect (e.g. equal revenue) to isolate whether time-variation itself, rather than the intervention's magnitude, is responsible for an observed effect.

See the `equilibrate-departure-time-choice-in-bottleneck-model` skill for the full bottleneck-construction, equilibrium-solving, and toll-testing methodology.
