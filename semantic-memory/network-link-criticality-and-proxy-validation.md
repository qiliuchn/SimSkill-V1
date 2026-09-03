---
summary: A network-wide link-criticality scan in SUMO (24 links closed individually, 2 adaptation regimes, 2 demand levels) found cheap planning proxies (betweenness centrality, VHT, volume) are moderate-to-strong overall predictors of criticality but poor selectors of the single worst link; a mandatory vehicle-disappearance validity check proved load-bearing, reversing the study's own headline correlation finding by revealing that a naive completed-trips-only metric let the most catastrophic closures look like improvements; rigorous 12-seed replication found no genuine Braess-like (closure-helps) link among two promising single-run candidates; and closure severity was found non-monotone at high demand, with a partial capacity reduction on one link causing substantially worse degradation than fully closing it.
keywords:
  - network-criticality
  - link-vulnerability
  - betweenness-centrality
  - robustness-index
  - vehicle-disappearance
  - severity-monotonicity
created: 2026-08-01T15:20:00
last_updated: 2026-08-05T03:20:00
sources:
  - "[[episodic-memory/2026-08-01_14-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_14-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[braess-paradox-in-sumo]]"
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[four-step-model-feedback-loop-convergence]]"
  - "[[discrete-network-design-and-project-interaction]]"
related_skills:
  - scan-network-link-criticality-and-vulnerability
  - simulate-incident-rerouting
  - compute-dynamic-user-equilibrium
  - construct-and-verify-braess-paradox
related_skills_for_graph_view:
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[simulate-incident-rerouting]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[construct-and-verify-braess-paradox]]"
---

# Network Link Criticality and Proxy Validation

Every prior closure/disruption study in this memory ([[incident-rerouting-and-closures]]) examines one link at a time in isolation. This page documents the first network-wide, systematic link-criticality scan — closing every link in a network one at a time and measuring which closure hurts the network most — using the `scan-network-link-criticality-and-vulnerability` skill's methodology, including a rigorous test of whether cheap planning proxies can predict criticality without expensive simulation.

## Verified finding: cheap proxies are screens, not selectors

Testing whether baseline link volume, baseline vehicle-hours-traveled (VHT), and topological betweenness centrality (computed once, from the undisrupted baseline network) predict true simulated criticality: travel-time-weighted betweenness was the best-correlating proxy, VHT next, raw volume weaker still, and **unweighted (pure hop-count) betweenness had no predictive signal at all** — a reminder that a purely topological measure, ignoring actual travel time/congestion, is not a useful traffic-criticality proxy on its own. Volume-to-capacity ratio could even *invert* (become negatively correlated with true criticality) at high demand.

**Critically, even the best proxy's moderately strong overall rank correlation did not translate into reliable identification of the single worst link.** The busiest link in the network was, in every tested condition, ranked well outside the true top few most-critical links, and the proxy's own top-5 list overlapped the genuine top-5 critical-link list by only a couple of links in most conditions. **The correct, nuanced conclusion: cheap proxies are a legitimate way to prioritize which links deserve expensive simulation-based analysis (a screening tool), but "close the busiest link" is not a reliable way to identify the actual worst-case vulnerability (not a selector).**

## Verified finding: the vehicle-disappearance validity check is load-bearing, not cosmetic

A closure can make network performance look **better** under a naive completed-trips-only delay metric purely because the vehicles most affected by the closure never complete their trip within the simulation horizon — their catastrophic experience never enters the average. This was verified to be a severe, real effect at high demand: several closure configurations showed an apparent *improvement* under the naive metric while a horizon-censored full-demand accounting (charging every scheduled vehicle, including those that never finished, an appropriate penalty) showed the closure was in fact substantially worse — differences of tens to well over a hundred percent between the naive and valid readings for the same closure. **This censoring effect was severe enough to completely reverse the study's own headline finding**: the correlation between betweenness centrality and true criticality flipped from a clear positive relationship to statistically indistinguishable from zero when computed against the naive (uncensored) metric instead of the valid one. A strict accounting identity (`arrived + still-running + never-inserted + unroutable = total demand`) is a cheap, essential sanity check that should be verified for every run in any closure/degradation study.

## Verified, honest negative result: no genuine Braess-like link found

Two links showed an apparent single-run improvement upon closure (a Braess-paradox-like signature — see [[braess-paradox-in-sumo]] for the underlying phenomenon in a route-choice context). Applying rigorous replication (paired Common-Random-Numbers seeds, proper statistical testing) — the same discipline established for confirming Braess's Paradox itself — found **neither candidate survived as genuinely beneficial**: one turned out to be significantly *harmful* once properly replicated (the single-run apparent improvement was noise, not signal), and the other was genuinely neutral/redundant (a statistically insignificant near-zero effect, i.e. a link the network doesn't structurally need, not a link whose removal actively helps). This is reported as an honest negative result — a real Braess-like link may exist in some network, but this particular grid, at these demand levels, did not contain one strong enough to survive replication.

## Verified finding: the criticality ranking is demand- and regime-dependent

Comparing the criticality ranking across different demand levels and adaptation regimes (reactive vs. re-equilibrated) found only moderate rank correlation between conditions, and the top-5 most-critical-links list overlapped only partially across conditions. **A criticality ranking computed at one demand level or under one adaptation assumption should not be assumed to transfer to a different demand level or adaptation regime** — the ranking is a property of the specific operating condition, not a fixed structural property of the network alone.

## Verified finding: closure severity is not guaranteed to be monotone

Comparing full closure against a partial capacity reduction (a lane drop) on the same links found the two were largely rank-consistent (monotone) at moderate demand but diverged at high demand — including one genuinely counter-intuitive case where a **partial** restriction caused substantially **worse** degradation than a **full** closure of the same link. The mechanism: a full closure forces all affected traffic to divert coherently onto an alternative route, while a partial restriction can split flow in a way that creates worse localized congestion (contention for the remaining reduced capacity) than simply removing the option entirely. Don't assume increasing a treatment's severity always monotonically increases its damage.

## Practical takeaways

- Use betweenness centrality (travel-time-weighted, not pure hop-count) or VHT as a cheap screening tool to prioritize which links merit full simulation-based criticality analysis — but don't trust the proxy alone to identify the single worst-case link.
- Always verify a strict vehicle-accounting identity and use a horizon-censored, full-demand delay metric in any closure/degradation study — a naive completed-trips-only average can make the worst closures look like improvements.
- Never report a single-run "this closure helps" result as a genuine Braess-like finding without rigorous paired replication.
- Don't assume a criticality ranking transfers across demand levels or adaptation-regime assumptions.
- Don't assume increasing the severity of a disruption (e.g. partial vs. full closure) monotonically increases its damage — verify the severity-response shape explicitly.

See the `scan-network-link-criticality-and-vulnerability` skill for the full scan, validity-check, proxy-correlation, and Braess-replication methodology.
