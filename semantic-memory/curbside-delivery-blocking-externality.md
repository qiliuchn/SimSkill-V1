---
summary: A double-parked delivery vehicle's delay externality on general traffic, measured in SUMO across background volume and delivery intensity with 20-seed Common-Random-Numbers replication, is near-negligible below ~60% of blocked-state capacity but explodes by a ~21x step multiplier once demand crosses that threshold; a dedicated loading bay removes 54-99% of the externality (more at higher demand) but leaves a small residual tied to the number of bay pull-out maneuvers, not total dwell time, and stop frequency (vs. dwell length) has a small independent effect at equal curb-occupancy time that becomes unreliable right at the demand threshold.
keywords:
  - curbside-delivery
  - double-parking
  - lane-blocking
  - loading-bay
  - delay-externality
  - freight
created: 2026-07-31T14:15:00
last_updated: 2026-07-31T14:15:00
sources:
  - "[[episodic-memory/2026-07-31_14-20-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_14-20-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[parking-areas-and-rerouters]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
  - "[[cruising-for-parking-search-externality-and-remedies]]"
  - "[[urban-freight-delivery-tours-container-semantics-and-policy-levers]]"
related_skills:
  - model-curbside-delivery-and-lane-blocking-externality
  - model-parking-with-rerouting
  - quantify-sumo-run-to-run-variability
  - design-bus-stop-placement-type-and-spacing
  - model-cruising-for-parking-search-externality
  - model-urban-freight-delivery-tours
related_skills_for_graph_view:
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[model-parking-with-rerouting]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[design-bus-stop-placement-type-and-spacing]]"
  - "[[model-cruising-for-parking-search-externality]]"
  - "[[model-urban-freight-delivery-tours]]"
---

# Curbside Delivery Blocking Externality

A delivery vehicle double-parked in a travel lane imposes a delay externality on general traffic distinct from every other congestion mechanism in this memory — it's a temporary, localized capacity reduction (one fewer usable lane for the stop's duration) rather than a persistent geometric bottleneck, a signal-control effect, or a route-choice effect. This page documents its first quantification in SUMO, using the `model-curbside-delivery-and-lane-blocking-externality` skill's lane-blocking `<stop parking="false"/>` mechanic, verified via three independent raw-data channels (stop-output's `parking` attribute, lane-based occupancy, and `strategic|urgent`-tagged forced lane changes) rather than assumed to work as documented.

## Verified finding: the externality is nonlinear, with a sharp threshold at blocked-state capacity

Sweeping background traffic volume at a fixed delivery-stop rate, the marginal externality (extra car delay per unit of curb-blockage time) stayed near-negligible and roughly linear through moderate demand, then jumped by a large step multiplier (verified case: ~21x) as demand crossed a specific threshold — not the network's nominal unblocked capacity, but the **reduced capacity available while one lane is periodically occupied by a stopped delivery vehicle**. This is the correct threshold to reason about when predicting whether curbside delivery activity will meaningfully disrupt a given street: comparing planned delivery-stop intensity against a street's *free-flow* capacity understates the risk, since the relevant ceiling is lower once blockage is accounted for.

## Verified finding: stop frequency matters independently of total occupancy time, but the effect is small and fragile near saturation

Holding total curb-occupancy time constant (same total vehicle-hours of blockage per hour) while varying whether that time comes from many short stops or few long stops: many short stops produced measurably more car delay than few long stops at low-to-moderate demand — a real, statistically robust effect (though small, well under 1% of trip time), driven by the *number* of forced-merge events rather than the total blocked time. This effect became statistically indistinguishable from zero — and even flipped in observed sign, though within noise — right at the demand level where the network approached its blocked-state capacity threshold. The forced-lane-change-count mechanistic explanation for this effect also becomes unreliable exactly there: past saturation, a *lower* observed lane-change count reflects fewer available gaps to merge into, not less underlying disruption, so the same raw metric changes what it's actually measuring as demand rises.

## Verified finding: a dedicated loading bay substantially reduces but does not eliminate the externality

A geometrically-separate off-lane loading bay (a restricted-vClass lane with its own `parkingArea`, not a parking area placed on a shared travel lane) removed the large majority of the double-parking externality — 54% at low demand, rising to over 99% near the demand threshold where the double-parking externality itself was largest. **A small, statistically robust residual remained even for fully off-lane deliveries**, mechanistically traced to a specific cause: every van's pull-out maneuver back into travel-lane traffic is itself a forced merge event. This residual scaled with the *number* of pull-out events — many short bay visits left a small but real, consistently measurable delay at every volume tested; few long bay visits' residual was statistically indistinguishable from zero at most volumes. **A loading bay is a large improvement, not a complete fix** — its remaining cost is specifically a merge-frequency cost tied to trip count, not an occupancy-time cost.

## Methodological notes

This was also the first episode in this memory to genuinely apply the replication methodology from [[sumo-stochastic-variability-and-replication-design]] rather than merely citing it. It independently reproduced that methodology's prior findings in a new scenario: coefficient of variation of the key delay metric peaked non-monotonically right at the capacity knee, and Common Random Numbers' variance-reduction benefit shrank to near-zero (and slightly reversed) for the most saturated, weakly-correlated cells — direct empirical confirmation that those findings generalize beyond the specific scenario they were first measured in.

## Practical takeaways

- FCD alone cannot distinguish a genuine lane-blocking stop from an off-lane parking stop — both show the vehicle at zero speed "on" its lane in FCD. Use `stop-output`'s `parking` attribute and lane-based occupancy data as the real discriminators.
- The relevant capacity threshold for predicting delivery-blockage disruption is the *blocked-state* capacity, not the street's nominal free-flow capacity.
- A loading bay reduces but does not eliminate delivery-related delay — the residual scales with trip frequency (number of pull-outs), not total dwell time, so consolidating deliveries into fewer, longer visits reduces the bay's own residual cost even though it doesn't reduce total curb-occupancy time.
- A forced-lane-change-count-based mechanistic proxy for disruption becomes unreliable once a scenario is genuinely oversaturated — it can invert from measuring disruption to measuring merge scarcity.

See the `model-curbside-delivery-and-lane-blocking-externality` skill for the full lane-blocking-stop verification methodology and the loading-bay construction technique. This verification protocol (stop-output, laneData, forced lane changes) transfers directly to `<busStop parking="true">` in [[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]], which also finds a **sign-reversed** version of the stop-frequency-vs-blockage finding above: on a single lane with no escape, few long dwells cost cars *more* than many short dwells at equal total blockage — the opposite of the many-short-stops-cost-more result here — because with no escape lane the mechanism is queueing delay behind a single blockage rather than the number of forced merge events. The same standing-vehicle-seconds instrument also isolates the parking **maneuver's** own lane-blocking cost (distinct from search delay) in [[cruising-for-parking-search-externality-and-remedies]], which finds that cost scales with the congestion of the specific block face blocked rather than with how much curb parking exists overall. [[urban-freight-delivery-tours-container-semantics-and-policy-levers]] found this page's convex bay-deficit delay shape does **not** transfer to a single-lane residential street — with no escape lane, a double-park is already a complete blockage from the first deficit unit, so the delay curve there is statistically indistinguishable from linear instead.
