---
summary: SUMO's teleport-based gridlock-resolution mechanism is a genuine, quantifiable confound in congested-scenario results — a single numerical --time-to-teleport setting swung mean travel time 2.7x and network speed 2.9x at fixed demand and seeds, teleport-free subsetting narrows but does not eliminate the effect, and disabling teleporting entirely can produce the MOST misleading result of all via survivorship censoring of a permanently deadlocked network; a matched-cohort re-test of a prior perimeter-gating episode's published benefit found it survives largely intact (~86% genuine, ~14% teleport contamination), resolving that episode's previously open validity caveat.
keywords:
  - time-to-teleport
  - gridlock-resolution
  - survivorship-censoring
  - keep-clear
  - simulation-validity
  - congested-network-methodology
created: 2026-08-01T02:10:00
last_updated: 2026-08-07T09:15:07
sources:
  - "[[episodic-memory/2026-08-01_01-32-22/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_01-32-22/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[mfd-based-perimeter-gating]]"
  - "[[sumo-output-files]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[travel-time-reliability-metrics-in-sumo]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
  - "[[traffic-state-estimation-sensor-bias-and-sensing-tradeoffs]]"
  - "[[integrated-corridor-management-factorial-interaction-findings]]"
  - "[[imported-network-defect-classes-and-traffic-impact]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
  - "[[pedestrian-flow-theory-and-striping-model-artifacts]]"
related_skills:
  - validate-congested-scenario-results-against-teleport-artifacts
  - implement-mfd-based-perimeter-gating
  - quantify-sumo-run-to-run-variability
  - measure-travel-time-reliability-with-simulated-days
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - scan-network-link-criticality-and-vulnerability
  - design-restricted-crossing-uturn-and-michigan-left-intersections
  - emulate-and-evaluate-partial-sensor-traffic-state-estimation
  - validate-kinematic-wave-theory-across-car-following-models
  - characterize-pedestrian-flow-and-striping-model-artifacts
  - evaluate-integrated-corridor-management-with-factorial-interaction-design
related_skills_for_graph_view:
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[implement-mfd-based-perimeter-gating]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[measure-travel-time-reliability-with-simulated-days]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
  - "[[emulate-and-evaluate-partial-sensor-traffic-state-estimation]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
  - "[[evaluate-integrated-corridor-management-with-factorial-interaction-design]]"
---

# Teleport Artifacts and Gridlock-Resolution Validity

SUMO's `--time-to-teleport` setting silently determines how much of a congested-scenario's measured performance reflects genuine traffic physics versus the simulator's own intervention to resolve gridlock. This page documents the first systematic study of teleporting itself as a methodological confound, directly resolving a previously open validity question flagged on [[mfd-based-perimeter-gating]] about whether that episode's published benefit was partly an artifact of the same mechanism.

## Verified finding: a single numerical setting can dominate a congested-scenario result

Sweeping `--time-to-teleport` across several values at fixed oversaturated demand and fixed random seeds — changing nothing else about the scenario — moved mean trip duration by 2.7x and mean network speed by 2.9x. This is a purely mechanical effect of one configuration parameter, not measurement noise; directional agreement across replicate seeds was strong (though not perfectly unanimous at the extreme high end of the tested range — verify per-seed agreement explicitly rather than assuming it, since it can weaken near a congestion knee). **Any congested-scenario comparison that doesn't control or report `--time-to-teleport` consistently across compared conditions is not comparing traffic physics — it may substantially be comparing simulator settings.**

## Verified, important finding: disabling teleporting can produce the MOST misleading result, not the safest one

The intuitive assumption is that `--time-to-teleport -1` (teleporting fully disabled) is the safest, most physically-faithful choice for a congested scenario, since it removes the artificial intervention entirely. **This is dangerously wrong when the network genuinely deadlocks.** `tripinfo` only records vehicles that actually complete their trip — if the network permanently gridlocks with teleporting disabled (verified directly: running vehicle count freezes at a specific timestamp, zero arrivals and zero speed for the remainder of the run), the reported mean travel time is computed only over the lucky minority of vehicles that finished *before* lockup. This survivorship-censored mean can look *better* than a functioning-but-congested network that used teleporting to keep flowing (badly, but flowing) — because the deadlocked network's terrible outcomes for the majority of stuck vehicles never enter the average at all. **Always check for a permanent running-count freeze before trusting a `ttt=-1` travel-time result.**

## Verified finding: teleport-free subsetting narrows but does not eliminate the artifact

Restricting analysis to only vehicles that were never teleported does not remove the dependence on `--time-to-teleport` — in a verified test, even the teleport-free-vehicle subset's mean travel time varied by more than 3x across different teleport settings, at fixed demand and seeds. The mechanism: teleporting changes the *entire network's* traffic state (freeing capacity, dissolving a blocking jam) for every vehicle, not just the one teleported — so a "teleport-free" subset is a narrower, but not clean, version of the same confound.

## Verified finding: junction keep-clear behavior has a non-monotone effect on congestion

Permitting vehicles to block a junction box (rather than SUMO's default keep-clear-enforced behavior) is a genuine, verifiable physical mechanism, not merely a configuration abstraction — confirmed both structurally (compiled network connection attributes) and behaviorally (dramatically more vehicle-time spent standing inside junction-box internal edges). Its effect on network performance is **non-monotone in demand severity**: at moderate oversaturation, permitting box-blocking can genuinely help (letting more vehicles queue where they're actually going, reducing reliance on teleport-based rescue); at severe oversaturation, the same setting becomes catastrophic, as box-blocking compounds across adjacent junctions into true, severe gridlock. Neither "box-blocking is always bad" nor "more flexibility always helps" holds universally — the sign of the effect depends on how severely oversaturated the network already is.

## Verified resolution: the perimeter-gating episode's open caveat

Re-testing [[mfd-based-perimeter-gating]]'s published -44.7% travel-time improvement using a methodologically correct **matched-cohort teleport-free comparison** (the shared population of vehicles that were teleport-free in *both* the gated and ungated arms — not each arm's own independently-filtered subset, which would compare different populations and bias the result) found the benefit **survives, only modestly inflated**: roughly 86% of the originally-published effect was genuine physical throughput gain, and roughly 14% was attributable to teleport-related contamination of the ungated baseline. **The original finding's direction and rough magnitude were correct; the caveat was worth raising and worth checking, and checking it confirmed rather than overturned the conclusion.** Separately, re-running the same comparison with teleporting fully disabled caused the result's sign to *reverse* — a direct demonstration of the survivorship-censoring danger above, not evidence the gating intervention doesn't work.

## Practical takeaways

- Report `--time-to-teleport` explicitly and hold it constant across every arm of a comparison — it is not a neutral technical setting.
- Never trust a `ttt=-1` travel-time result without first checking the running-vehicle-count time series for a permanent freeze.
- Teleport-free subsetting reduces but does not eliminate teleport sensitivity — don't treat it as a clean control.
- When re-testing a prior finding's teleport sensitivity, use the matched common cohort (vehicles teleport-free in both arms of the comparison), not each arm's own independently-filtered subset.
- Report the teleport-affected share of completed trips alongside any travel-time metric from an oversaturated scenario — a share above roughly 2% should be treated as a caveat requiring disclosure, not ignored.
- Check junction keep-clear behavior's effect at the specific demand level of interest — its sign can flip between moderate and severe oversaturation.

See the `validate-congested-scenario-results-against-teleport-artifacts` skill for the full teleport-sweep methodology, the matched-cohort re-test technique, and the concrete decision rule for reporting congested-scenario results.
