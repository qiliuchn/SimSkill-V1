---
summary: "The Downs-Thomson paradox — expanding road capacity on a corridor with a parallel transit alternative can make equilibrium cost worse for every traveller — was cleanly confirmed in SUMO via an endogenous mode-choice equilibrium with a ridership-driven transit headway rule (the Mohring effect): doubling a bottleneck's capacity raised equilibrium door-to-door cost 97% by starving transit ridership and stretching headway, a feedback-on/feedback-off control isolated the ridership-to-frequency feedback as the cause (frozen headway made the same expansion statistically neutral), a demand sweep showed the paradox is a genuine regime rather than a knife-edge result, and the feedback loop was found to create a second, unstable equilibrium with a narrow one-sided basin of attraction that naive day-to-day adjustment could jump."
keywords:
  - Downs-Thomson-paradox
  - mode-choice-equilibrium
  - Mohring-effect
  - transit-ridership-feedback
  - multiple-equilibria
  - equilibrium-stability
created: 2026-08-01T00:10:00
last_updated: 2026-08-05T04:00:00
sources:
  - "[[episodic-memory/2026-07-31_20-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_20-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[braess-paradox-in-sumo]]"
  - "[[vickrey-bottleneck-departure-time-equilibrium]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[accessibility-measurement-and-transport-equity]]"
related_skills:
  - equilibrate-endogenous-mode-choice-with-transit-supply-feedback
  - simulate-multimodal-transit
  - equilibrate-departure-time-choice-in-bottleneck-model
  - construct-and-verify-braess-paradox
related_skills_for_graph_view:
  - "[[equilibrate-endogenous-mode-choice-with-transit-supply-feedback]]"
  - "[[simulate-multimodal-transit]]"
  - "[[equilibrate-departure-time-choice-in-bottleneck-model]]"
  - "[[construct-and-verify-braess-paradox]]"
---

# Downs-Thomson Paradox and Mode-Choice Equilibrium

This memory now contains a genuine trio of classical traveller-choice-dimension equilibria: route choice ([[braess-paradox-in-sumo]]), departure-time choice ([[vickrey-bottleneck-departure-time-equilibrium]]), and — documented here for the first time — **mode choice**, where travellers choose between driving and a parallel transit line whose service frequency responds endogenously to ridership (the Mohring effect). This page documents the first verified reproduction of the **Downs-Thomson paradox**: road capacity expansion that makes equilibrium travel cost worse for *every* traveller, car users included.

## Verified finding: the paradox is real, and its mechanism is confirmed by a control

Doubling a corridor's road bottleneck capacity — with an unchanged, physically separate, verified car-inaccessible transit right-of-way alongside it — raised the equilibrium door-to-door generalized cost for every traveller by 97%. The mechanism: the road expansion induced a large mode shift toward cars (equilibrium car share roughly tripling), which starved transit ridership by roughly two-thirds, which (via an explicit ridership-driven operator headway rule, `H = clamp(K/Q_transit, H_min, H_max)`) stretched transit headway to nearly triple its original value — making transit substantially worse for the shrinking minority still using it, while the road itself became congested enough that the "improved" capacity was fully absorbed by the induced demand. **A decisive mechanism control confirmed the cause**: repeating the identical road expansion with headway frozen at a constant value (no ridership feedback) made the same expansion statistically neutral — cleanly isolating the ridership-to-frequency feedback loop, not some other confound of the capacity change, as what produces the paradox. A separate ceteris-paribus check (mode share held fixed at its pre-expansion value) confirmed the road expansion was a genuine, substantial engineering improvement in isolation — the paradox arises entirely from the behavioral/supply-feedback response, not from the capacity change itself being harmful.

## Verified finding: the paradox is a demand-dependent regime, not a knife-edge result

Sweeping total demand across several levels found the paradox **absent** at low demand (both road-capacity variants collapse to a car-only equilibrium — there is no sustained transit ridership left to starve, since none existed in the first place at that demand level) and **present**, non-monotonically, across a range of moderate-to-high demand. The specific threshold between these regimes was a genuine crossing point in the swept data, confirming the paradox is a property of demand relative to the transit line's viability threshold, not an artifact tuned to one specific calibration.

## Verified, genuinely novel discovery: the feedback creates a second, unstable equilibrium

Beyond confirming the expected paradox, this work uncovered an unanticipated structural property of the ridership-frequency feedback loop: **the mode-share cost-gap function can be non-monotone when the feedback is active, producing two equilibria — one stable, one unstable** (a measurable "transit death spiral" tipping point) — where the identical scenario with the feedback disabled has only one equilibrium. A solver that only checks the sign of the cost gap at the two endpoints of a search range can converge to the wrong root, or wrongly conclude no interior equilibrium exists, if it happens to bracket the unstable root. **The correct approach scans the full mode-share range, classifies every sign change as stable or unstable, and solves only within the stable root's bracket.**

## Verified finding: the higher-capacity equilibrium has a narrow, one-sided basin of attraction

Perturbation testing (nudging mode share away from a found equilibrium and re-simulating) found the lower-capacity equilibrium stable from both directions with large restoring forces, but the higher-capacity equilibrium **stable only from one side** — a push toward more transit use restored it, but a push toward more car use escaped its basin entirely, because the unstable second root sat close by in mode-share space. **Naive day-to-day adjustment (MSA-style) starting from certain initial conditions was shown to actually overshoot this narrow basin and converge to the wrong fixed point** (a car-only corner) instead of the true interior equilibrium — a milder echo of the departure-time equilibrium instability documented in [[vickrey-bottleneck-departure-time-equilibrium]], now found in a structurally different (mode-choice, ridership-feedback) equilibrium concept.

## Practical takeaways

- A supply-feedback loop (ridership affecting frequency, frequency affecting ridership) can create multiple equilibria, including unstable ones — don't assume a single-bisection or naive-MSA solver will find the right one, or even recognize that more than one exists.
- Always run a mechanism control (freezing the specific feedback under study) rather than relying on a single before/after comparison — it's what turns "we observed a paradox" into "we know what causes it."
- Verify any equilibrium's stability via perturbation, not just its zero-gap condition — an equilibrium can be stable from one side and unstable from the other.
- Sweep the relevant demand/parameter range to check whether a paradox is a genuine regime or a fitted knife-edge result.
- When modeling a transit line's realized rider wait, verify against the schedule-integrated expected wait, not the steady-state `H/2` approximation, over a finite demand window.

See the `equilibrate-endogenous-mode-choice-with-transit-supply-feedback` skill for the full car-inaccessible-right-of-way verification, headway-rule construction, scan-classify-bisect solver, and mechanism-control methodology.
