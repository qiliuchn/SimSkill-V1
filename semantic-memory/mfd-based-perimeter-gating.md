---
summary: MFD-based perimeter gating — throttling perimeter signal green time based on measured core accumulation — verified on a 7x7 signalized grid to cut mean travel time 44.7% and completions-by-fixed-horizon +36.4% (8/8 seeds) when the core is genuinely oversaturated, with benefit vanishing near the measured critical accumulation and reversing to a pure cost (0/4 seeds improved) when the core never goes supercritical; a non-binding negative control reproduced the ungated baseline byte-for-byte, and a quantified clockwise MFD hysteresis loop explains why slack set-points fail to recover once the core is congested.
keywords:
  - perimeter-gating
  - macroscopic-fundamental-diagram
  - network-level-control
  - core-accumulation
  - gridlock-prevention
  - hysteresis
  - two-region-control
created: 2026-07-31T09:30:00
last_updated: 2026-07-31T09:30:00
sources:
  - "[[episodic-memory/2026-07-31_10-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_10-30-00/outputs/verification.json]]"
related_pages:
  - "[[macroscopic-fundamental-diagram]]"
  - "[[ramp-metering-with-alinea]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
related_skills:
  - implement-mfd-based-perimeter-gating
  - build-macroscopic-fundamental-diagram
  - implement-maxpressure-traci-controller
  - create-grid-network
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[implement-mfd-based-perimeter-gating]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[implement-maxpressure-traci-controller]]"
  - "[[create-grid-network]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# MFD-Based Perimeter Gating

Perimeter gating is a **network-level** traffic-control strategy: rather than optimizing individual intersections, it treats a congested region ("core") as a single unit, measures its accumulation (vehicles present), and throttles inflow at the region's boundary to keep accumulation near the core's critical value — the accumulation at which the region's macroscopic fundamental diagram (MFD, see [[macroscopic-fundamental-diagram]]) produces maximum output. This page documents the first verified use of an MFD as an *active control variable* in this memory, as opposed to every prior MFD use, which was purely descriptive measurement.

## Verified finding: gating substantially helps an oversaturated core, and only there

On a 7x7 fully signalized grid (49 junctions) with a 3x3 inner core and demand engineered to drive the core well past its measured critical accumulation (`n_crit` = 150 veh, peak accumulation 312 veh — 2.1x critical — with production collapsing ~85% on the congested branch), a proportional perimeter-gating controller swept across 8 random seeds and 7 set-points:

- **Best set-point (n_set=20)**: mean travel time **-44.7%** (1403.8s → 776.6s, 8/8 seeds), completions by a fixed horizon **+36.4%**, teleports **-77.9%**, network clearance time **-27.7%** — all directionally unanimous across all 8 seeds.
- **Benefit degrades smoothly and vanishes near `n_crit`**: unanimous and large for set-points well below `n_crit`, mixed by set-point ≈0.8x `n_crit`, and statistically indistinguishable from doing nothing at set-point ≈`n_crit` (3/8 seeds "improved" — pure noise). A set-point above `n_crit` turned mildly *negative* on the mean.
- **Non-binding negative control** (a set-point so high the gate never engages) reproduced the ungated baseline **byte-for-byte** — identical accumulation time series and identical `tripinfo` records in every seed tested — proving the control mechanism is a genuine no-op when it doesn't bind, not merely similar by coincidence.
- **Nobody paid, in this regime**: core-destined, through, and even outside trips *all* improved (-53.5%, -43.1%, -19.1% travel time respectively), because the ungated case was network-wide gridlock whose spillback reached vehicles that never entered the core at all. The real, visible cost was a temporarily larger perimeter queue during the demand-loading phase (+140%), fully repaid later as the gated network drained faster overall.
- **Total work delivered inside the core was conserved** (routes were fixed, so the same total vehicle-km had to be driven either way) — gating changes *when* the core's capacity is used, concentrating it near the peak-production accumulation, not how much work exists.

## Verified null result: gating an undersaturated core is a pure cost

A supplementary experiment at lower demand, where the core's peak accumulation stayed below `n_crit` (121 vs 150 veh) and zero teleports occurred in any run: gating produced **0/4 seeds improved**, a uniform +4.4% travel-time cost across the aggressive set-point, with every trip class paying a little. **Perimeter gating has nothing to offer a core that was never going to become supercritical** — the mechanism is a prevention strategy for a specific failure mode, not a general-purpose intervention, and should not be assumed beneficial without first confirming the baseline genuinely overshoots critical accumulation.

## Why hysteresis explains the vanishing benefit near n_crit

Pooling loading and unloading branches across seeds of the ungated baseline revealed a clear clockwise hysteresis loop — at a given accumulation, the core reliably produces *less* output while unwinding a jam (mean gap +196 veh·km/h, widening to +527 in the most congested range) than it did while filling to that same level. This is why a slack gating set-point — one that only starts restricting inflow once the core is already past `n_crit` — fails to recover production: cutting inflow after the fact does not undo the hysteresis penalty already incurred. Gating must act **before** the core becomes supercritical to be effective, not react to it afterward.

## Practical takeaways

- Establish and quantify the ungated baseline's overshoot and hysteresis *before* designing a gating controller — a network that never goes supercritical has nothing for gating to fix.
- A proportional control law's realized best set-point is typically well below the measured `n_crit`, offset by roughly `(g0 - g_min)/K` (the accumulation range over which the controller transitions from unrestricted to fully restricted) — don't assume the set-point should simply equal `n_crit`.
- Verify the control mechanism is a genuine no-op when non-binding via byte-level comparison of raw output, not just similar summary statistics — this is what makes the causal claim ("gating, not something else, caused the improvement") solid.
- Report per-seed paired results (how many seeds improved, not just the mean), especially near a control's tipping point where variance is large enough to flip individual seeds' sign.
- Check the ungated baseline's teleport count — if it's large, some of gating's apparent benefit may be "fixing" the simulator's own gridlock-resolution mechanism rather than a purely physical throughput gain; report this honestly rather than treating raw travel time as a clean measurement. **This caveat has since been directly re-tested and resolved** (see [[teleport-artifacts-and-gridlock-resolution-validity]]): a matched-cohort teleport-free re-test of this page's -44.7% headline finding found it survives largely intact — roughly 86% genuine, roughly 14% attributable to teleport contamination of the ungated baseline. The original finding's direction and rough magnitude were correct.
- Measure throughput at fixed time horizons or via clearance time, not final arrival counts, when demand is finite — every configuration eventually serves all trips, so total arrivals don't discriminate between them.

See the `implement-mfd-based-perimeter-gating` skill for the full core/gate-derivation, fixed-route-demand, and TraCI-controller implementation workflow.
