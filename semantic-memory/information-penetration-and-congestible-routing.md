---
summary: Sweeping SUMO's rerouting-device market penetration during a mid-simulation incident confirms real-time traffic information behaves as a congestible good — private benefit to informed drivers decays and reverses past moderate penetration as uninformed drivers free-ride, and network-wide benefit is genuinely non-monotonic (though full penetration still beats none); a static-split reference sweep cleanly decomposed the full-penetration shortfall as a pure timing/herding failure versus a mid-penetration under-diversion failure, and the intuitive "smoothing route-weight updates reduces herding" hypothesis was honestly refuted — smoothing increased oscillation amplitude and worsened outcomes at every penetration level tested.
keywords:
  - information-penetration
  - congestible-good
  - rerouting-device
  - market-penetration
  - herding
  - route-choice-oscillation
created: 2026-07-31T18:00:00
last_updated: 2026-07-31T18:00:00
sources:
  - "[[episodic-memory/2026-07-31_17-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_17-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[incident-rerouting-and-closures]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[cruising-for-parking-search-externality-and-remedies]]"
  - "[[effort-based-routing-and-eco-routing]]"
related_skills:
  - sweep-rerouting-device-market-penetration
  - simulate-incident-rerouting
  - compute-dynamic-user-equilibrium
  - model-cruising-for-parking-search-externality
related_skills_for_graph_view:
  - "[[sweep-rerouting-device-market-penetration]]"
  - "[[simulate-incident-rerouting]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[model-cruising-for-parking-search-externality]]"
---

# Information Penetration and Congestible Routing

Every prior rerouting-related episode in this memory equipped either 0% or 100% of vehicles with SUMO's real-time rerouting device — treating live traffic information as a binary switch rather than a variable with its own market-penetration dynamics. This page documents the first sweep of rerouting-device penetration as a treatment variable, testing whether real-time traffic information behaves as a **congestible good**: valuable to a lone informed driver, with diminishing or even negative returns as more drivers share it — the same theoretical pattern documented for cooperative car-following in [[av-penetration-and-carfollowing-model-mechanism]], here in the route-choice rather than car-following domain.

## Verified finding: private benefit to being informed decays and reverses

Sweeping `--device.rerouting.probability` during a mid-simulation incident and reporting equipped vs. unequipped vehicle travel time separately (verified via a vType-tag-to-tripinfo-device-attribute cross-check with zero mismatches): at low penetration, informed drivers gained substantially over uninformed ones. As penetration rose, informed-driver travel time stayed roughly flat while uninformed-driver travel time *fell* — uninformed drivers increasingly free-ride on the informed minority's diversion, since a vehicle that happens to be assigned the now-less-congested route benefits without needing any information itself. **Past a moderate penetration threshold, being equipped was measurably worse than not being equipped** — the private value of information went negative exactly as the congestible-good hypothesis predicts.

## Verified finding: system-wide benefit is genuinely non-monotonic

Network-wide mean travel time, swept across penetration levels, fell sharply from zero penetration to a mid-range optimum, then rose again toward full penetration — both legs of this curve were statistically significant, not just a flattening diminishing-returns shape. **Full penetration still substantially outperformed zero penetration** — the honest framing is that the congestible-good effect costs part of the *achievable* benefit at the extremes, not that full information provision is actively harmful compared to no information at all.

## Verified finding: a clean decomposition into timing failures vs. allocation failures

A static-split reference sweep (forcing a fixed, non-reactive fraction of vehicles onto the alternate route at several levels, independent of any live device) let the study separate *why* a given penetration level underperformed:

- **At full penetration**, the reactive system's realized average route split was statistically indistinguishable from the system-optimal static split — yet travel time was still measurably worse. This is a pure **timing** failure: the average allocation was right, but the process of getting there (synchronized, herd-like reaction to the incident) cost real time that an instantaneously-correct split wouldn't.
- **At a mid-range penetration level**, by contrast, the reactive system matched a *worse* static split than optimal — an **allocation** failure (under-diversion), not a timing one.

**The same shortfall in aggregate outcome can have different underlying causes at different penetration levels** — a static-split reference sweep is a general, reusable technique for telling these apart in any reactive-vs-optimal-control comparison.

## Verified, honestly-reported negative result: smoothing does not reduce herding

The intuitive fix for herding — smoothing (slowing) the route-weight update rate so the system reacts less aggressively to noisy recent travel times — was tested directly and **refuted**: smoothed adaptation did reduce the *rate* of route-split flip-flopping (as expected), but *increased* the overall oscillation *amplitude*, because the split would latch at an extreme value for an extended period before crashing back, rather than making frequent small corrections. Smoothed adaptation produced worse average travel time than fast adaptation at every penetration level tested. Fast (noisy) adaptation additionally diverted a nontrivial fraction of traffic onto a strictly-worse route *before* the incident even began — pure noise-chasing — while smoothed adaptation showed essentially zero pre-incident spurious diversion, illustrating a genuine trade-off rather than a simple "smoothing is better" or "smoothing is worse" story.

## Practical takeaways

- Report travel time separately for informed/equipped and uninformed/unequipped subgroups whenever studying partial technology adoption — network-wide averages can hide a private-benefit reversal entirely.
- Verify a claimed information-penetration effect is genuinely non-monotonic (both legs statistically significant), not just an artifact of noise near a diminishing-returns plateau.
- Use a static-split (or otherwise non-reactive, offline-optimized) reference to decompose a reactive system's underperformance into "wrong average behavior" vs. "right average behavior, wrong timing" — the same aggregate shortfall can have different causes at different operating points.
- Measure both oscillation amplitude and flip-flop rate when studying herding — a damping intervention can reduce one while increasing the other, and a plausible-sounding mitigation ("just smooth the update rate") is not guaranteed to actually help the outcome that matters.
- Report an equilibrium-reference computation's failure to converge honestly rather than treating its output as a trustworthy target — a time-varying (incident) scenario can genuinely prevent `duaIterate` from settling within a reasonable iteration budget.

See the `sweep-rerouting-device-market-penetration` skill for the full subgroup-attribution, timing-decomposition, and oscillation-measurement methodology. The same congestible-good/herding mechanism was independently reproduced in the parking-guidance domain by [[cruising-for-parking-search-externality-and-remedies]], which additionally isolated the failure as a **coordination** problem (multiple informed drivers converging on the same reported-free space) rather than an information-processing one — a reservation-aware guidance variant restored the benefit at full penetration where naive nearest-free-space guidance inverted into net harm.
