---
summary: A full 2^4 CRN-paired factorial (diversion advisory D, ramp metering M, responsive arterial signals S, VSL V) on a verified freeway+arterial ICM corridor found diversion advisory alone is the only resolvable effect in the entire study and is severely harmful (>10x the noise floor) because a short ramp/arterial system cannot absorb a diversion-sized platoon, with harm persisting across every tested response lag (0-1200s) and incident duration (900-3600s) without ever crossing into net benefit; M, S, and V individually or combined without D were statistically indistinguishable from doing nothing at this corridor's noise floor, and no resolvable D-M antagonism was found (though D's dominance leaves the factorial underpowered to detect it); a background-batch collection-timing bug that silently dropped valid completed data, and a CI computed with an unpaired instead of CRN-paired bootstrap, were both found and fixed across two follow-up review rounds.
keywords:
  - integrated-corridor-management
  - ICM
  - factorial-interaction-design
  - diversion-advisory
  - CRN-paired-bootstrap
  - noise-floor-gating
  - response-latency
created: 2026-08-07T09:15:07
last_updated: 2026-08-07T09:15:07
sources:
  - "[[episodic-memory/2026-08-07_09-09-06/attempts/attempt-1/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_09-09-06/attempts/attempt-3/action-agent-output.md]]"
  - "[[episodic-memory/2026-08-07_09-09-06/attempts/attempt-3/critic-agent-feedback.md]]"
related_pages:
  - "[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[global-sensitivity-analysis-and-parameter-interactions-in-sumo]]"
  - "[[information-penetration-and-congestible-routing]]"
related_skills:
  - evaluate-integrated-corridor-management-with-factorial-interaction-design
  - implement-alinea-ramp-metering
  - implement-variable-speed-limits
  - simulate-incident-rerouting
  - build-and-benchmark-freeway-incident-detection
  - screen-and-decompose-sumo-parameter-sensitivity
related_skills_for_graph_view:
  - "[[evaluate-integrated-corridor-management-with-factorial-interaction-design]]"
  - "[[implement-alinea-ramp-metering]]"
  - "[[implement-variable-speed-limits]]"
  - "[[simulate-incident-rerouting]]"
  - "[[build-and-benchmark-freeway-incident-detection]]"
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
---

# Integrated Corridor Management: Factorial Interaction Findings

Every ITS measure in memory — rerouting, ramp metering, VSL, arterial progression, incident detection — had been studied in isolation, on a network built to isolate it. This page holds the first measurement of whether these measures' benefits compose when deployed together during an incident, using a full 2^4 CRN-paired factorial on a verified freeway+parallel-arterial corridor. See `evaluate-integrated-corridor-management-with-factorial-interaction-design` for the full methodology.

## Diversion advisory alone dominates, and is severely harmful

Of four control measures tested (D = diversion advisory, M = ramp metering, S = responsive arterial signal plan, V = VSL/speed harmonization), **D alone was the only effect resolvable above the CRN replication noise floor in the entire factorial** — and it was resolvably, severely *harmful* (over 10× the noise floor), not beneficial. Every arm with D=0 was statistically indistinguishable from the no-control baseline; every arm with D=1 was resolvably worse, regardless of which other measures accompanied it. The mechanism was verified directly: diverted vehicles paid roughly 51 extra minutes each on average, but the much larger *non-diverted* freeway-through population absorbed the majority of the aggregate system cost, because the diversion-advisory-induced off-ramp queue partially blocked the freeway mainline itself. This is the sharp, decision-relevant version of the general lesson in `[[coordinated-ramp-metering-delay-transfer-and-ramp-storage]]`: an ITS measure that looks beneficial in isolation (diversion relieves the freeway) can be a net system harm once the *receiving* facility's actual capacity to absorb the diverted flow is accounted for, rather than assumed.

Ramp metering, responsive arterial signals, and VSL — individually or in any combination *without* D — were statistically indistinguishable from doing nothing, at this corridor's demand level and noise floor. No resolvable two-way interaction between D and M (the "metering traps diverted traffic" hypothesis) was found — but this should be read as an *informative null under low statistical power*, not as evidence the mechanism doesn't exist: D's main effect was roughly two orders of magnitude larger than M's own main effect, which structurally limits how well this factorial design can resolve any interaction involving M.

## Harm persists across response lag and incident duration — no break-even found

Sweeping total response lag (detection + decision + activation, 0–1200s including a perfect-oracle 0-lag arm) found D's harm shrinks in magnitude as lag grows (roughly halving from lag=0 to lag=1200s) but **never crosses into net benefit** within the tested range. Critically, the D-only arm and the all-four-measures arm showed the *same* lag-decay shape, differing by only a few veh-hours at every lag — confirming this pattern is a property of the D module itself, not an interaction with the other three measures. The mechanism is structural, not about response speed being "too slow": the tested D module had no incident-clearance stand-down (once armed, it stayed active for the rest of the demand window), so a longer lag mechanically shortens the window during which the harmful policy is exposed to demand — a real methodological trap for interpreting any lag-sweep result on a control module without an explicit stand-down condition, since "harm shrinks with lag" can look like "faster response matters less" when it is actually "a longer lag leaves less time for a bad policy to do damage."

The same mechanism explains a similarly counter-intuitive severity-sweep result: benefit was *more* negative at a shorter (900s) incident than at the reference (1800s) or longer (3600s) incident, because a fixed-window diversion policy keeps diverting proportionally longer past a short incident's actual clearance than a long one's. Across the full 900–3600s range tested, D-based ICM response never paid off — harm shrank roughly 50% from shortest to longest duration but never crossed zero, and the confidence interval excluded zero at every tested duration.

## Methodological findings: CRN-paired interaction estimation, and two real bugs found across follow-up review

This study is also the first to transfer `[[discrete-network-design-and-project-interaction]]`'s noise-floor-gated, CRN-paired-bootstrap interaction-measurement methodology from discrete infrastructure projects to control-measure combinations, packaged as a reusable generic 2^k factorial/interaction estimator (`analysis/factorial.py` — takes arbitrary factors and outcome column, no domain-specific logic). Two genuine, non-trivial issues were found and fixed across two rounds of independent review, both worth generalizing:

1. **A background-batch aggregation script run before the batch had actually finished silently produced an incomplete, wrong dataset with no error** — the collected-output file's timestamp was earlier than the batch's last completed job, and a full lag-sweep arm's data (9 valid, already-completed runs) was silently dropped as a result. The fix required zero new simulation — just re-running the collection step against the now-complete raw data. Always check a batch's own completion manifest, or compare collected-output vs. raw-output timestamps, before trusting an aggregation that ran near a background process's completion.
2. **An unpaired (independent two-sample) bootstrap silently produced a materially wrong, wider confidence interval in one part of an otherwise CRN-paired-bootstrap pipeline.** The point estimate was unaffected (confirming this was purely a variance-estimation bug, not a data error), but the CI itself did not reproduce under the codebase's own established paired method used correctly elsewhere in the same pipeline (e.g. the D-alone-harm claim's CI, which was independently re-derived exactly). Any pipeline mixing paired and unpaired bootstrap code for what should be the same CRN-paired design is a real, silent correctness risk — verify every CI-producing function in a multi-script analysis pipeline uses the same, correct resampling convention, not just the ones checked first.
