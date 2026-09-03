---
summary: SUMO has no reversible-lane primitive; the only encoding that survives testing declares the full physical cross-section on BOTH directional edges (spreadType=center plus netconvert --geometry.avoid-overlap false, which makes opposing lane pairs exactly coincident) and gates them with traci.lane.setAllowed, while overlapping-opposing-edge and rerouter/closingLaneReroute encodings fail concretely. The changeover must be a cascading clearance sweep, whose duration tracks residual queue rather than lane length because SUMO's lane-change model evicts vehicles laterally off a newly-disallowed lane; SUMO's SSM device is provably blind to the resulting head-on hazard, so a custom co-occupancy scan with a broken positive control is mandatory.
keywords:
  - reversible-lane
  - tidal-flow
  - contraflow
  - lane-reversal
  - changeover-clearance
  - setAllowed
  - geometry-avoid-overlap
  - head-on-conflict
created: 2026-08-04T17:00:00
last_updated: 2026-08-04T17:00:00
sources:
  - "[[episodic-memory/2026-08-04_17-00-00/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/geometry_verification.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/representation_experiment.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/changeover_verification.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/clearance_study.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/study_summary.json]]"
  - "[[episodic-memory/2026-08-04_17-00-00/outputs/analysis/changeover_throughput_cost.json]]"
related_pages:
  - "[[dynamic-hard-shoulder-running-with-traci-lane-permissions]]"
  - "[[vehicle-class-lane-permissions]]"
  - "[[incident-rerouting-and-closures]]"
  - "[[surrogate-safety-measures]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[managed-lanes-empty-lane-paradox-and-person-throughput]]"
related_skills:
  - operate-reversible-tidal-flow-lane
  - implement-dynamic-hard-shoulder-running
  - model-vclass-lane-permissions
  - simulate-incident-rerouting
  - analyze-intersection-safety-with-ssm
  - switch-signal-plans-by-time-of-day-with-waut
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[operate-reversible-tidal-flow-lane]]"
  - "[[implement-dynamic-hard-shoulder-running]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[simulate-incident-rerouting]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[switch-signal-plans-by-time-of-day-with-waut]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
---

# Reversible-Lane Encoding and Changeover Safety

A **reversible** (tidal-flow, contraflow) lane changes its direction of travel during operation. SUMO has no primitive for this: an edge is directional and its lanes belong to it permanently. Every reversible-lane study therefore starts with a representation choice, and that choice is load-bearing — two of the three obvious encodings fail in ways that quietly invalidate results rather than erroring.

This page is the reversible-lane counterpart to [[dynamic-hard-shoulder-running-with-traci-lane-permissions]], which covers the one-directional case (a lane opened or closed to a single direction). The extra thing a reversal has, and hard-shoulder running does not, is an **opposing direction** — hence a mutual-exclusion invariant that SUMO will neither enforce nor detect on your behalf.

## The accepted encoding: full cross-section declared in both directions

Declare **every physical lane on both directional edges**, so physical lane *k* has two SUMO identities:

```
EB edge lane i   <->   WB edge lane (N-1-i)          # N physical lanes
```

Use `spreadType="center"` with **no explicit `shape`** and compile every lane open; gate them with `traci.lane.setAllowed`, holding the invariant that exactly one identity of each pair is passable at any instant. Lanes that never reverse are simply pairs whose gating is fixed at t=0.

Two netconvert facts make this work:

- **`--geometry.avoid-overlap` defaults to ON and must be turned off.** It modifies edge geometry to keep opposing edges apart; left on, the two identities of a "physical" lane compiled 6.4-19.2 m apart. With `--geometry.avoid-overlap false`, all six lane pairs of a 6-lane corridor verified at **exactly 0.000 m** lateral offset (EB lanes at y = -8.0/-4.8/-1.6/+1.6/+4.8/+8.0; WB lanes at the same six values in reverse index order).
- **An explicit edge `shape` cannot be used to place lanes laterally.** netconvert normalises the shape back onto the node line: a flat shape written at y = -3.2 between nodes on y = 0 compiled to y = 0, and a longer one came back sheared. Lateral placement comes from `spreadType` and lane count only.

Exact geometric coincidence is not cosmetic — it is what turns the head-on check into a direct observation (two vehicles at the same `(x, y)` in `fcd-output`) rather than an inference from lane bookkeeping.

## Rejected encoding 1: overlapping opposing single-lane edges

Representing the reversible lane as a pair of opposing one-lane edges laid over the same geometry fails twice:

- **The lane is unreachable by ordinary traffic.** Vehicles change lanes within an edge, never between parallel *edges*. With the permanent 2-lane corridor loaded to 4000 veh/h against a measured 2059 veh/h capacity — genuinely oversaturated, 112 of 2000 vehicles never completing — the parallel reversible edge carried **exactly 0 vehicles** for the whole run. Its capacity is reachable only by demand pre-assigned to it in the route file, which is not what a reversible lane is.
- **Reversal invalidates already-committed routes, hard.** Pre-routing 25% of demand over the reversible edge and reversing it mid-run produced `Error: Vehicle 'EB.1000' has no valid route. No connection between edge 'apW_in' and edge 'RL3_EB'.` followed by `Quitting (on error)` — at exactly the reversal instant. Running the same case with `--ignore-route-errors true` survives but degrades badly: 28 teleports, every one logged with reason `waited too long (wrong lane)`, and 210 of 1063 vehicles never arriving.

## Rejected encoding 2: rerouter `closingLaneReroute`

`<closingLaneReroute disallow="all">` genuinely gates lane entry — new entries during a 600 s closed interval: **1**, versus 536 in the preceding period and 746 afterwards, with `traci.lane.getDisallowed` showing 33 vClasses barred during the interval and none outside it. It still cannot run a changeover:

- **No clearance handshake.** The closure starts at a scheduled instant with the lane occupied; occupancy fell from 90 vehicles to 0 over roughly **240 s** (t=600 → t=840) with nothing verifying it, and the lane reopens at the interval end unconditionally.
- **The interval is not runtime-controllable.** The `traci.rerouter` domain exposes only `getParameter`/`setParameter`. `setParameter(id, "begin", "1800")` **returns `None` and does nothing**, and `getParameter(id, "begin")` returns `''` — the same silently-ignored-parameter failure mode documented in [[actuated-signal-detector-design-and-fault-tolerance]]. Any demand-responsive policy is therefore impossible.
- It can only **close**, never **grant** the opposing direction, so it cannot maintain the mutual-exclusion invariant by itself.

`closingLaneReroute` remains the right tool for the incident/work-zone case it was designed for — see [[incident-rerouting-and-closures]].

## The compile-closed trap, quantified — and the fix that does not work

Compiling the reversible lane closed (`allow="authority"`) and reopening it at runtime is broken, extending [[dynamic-hard-shoulder-running-with-traci-lane-permissions]]'s finding with a direct structural check and a new negative result:

- **Structural**: in the compile-closed build, **4 of 8** checked internal junction connector lanes carry `allow="authority"`; in the compile-open build, **0 of 8** do. netconvert bakes the restriction into the connectors.
- **Behavioural**: reopening only the normal lanes at runtime dropped end-to-end completion through the downstream junction on the reopened lane to **6.7%**, against **60.8%** for the same lane in a compile-open net under identical demand; 208 vehicles were still stuck at simulation end (1800 s after demand ended) and 74 were never inserted, versus 2200/2200 arrived and 0 stuck in the compile-open build.
- **The obvious fix fails**: also calling `setAllowed` on the internal connector lanes gives **8.4%** completion — statistically indistinguishable from 6.7%. The damage is in SUMO's load-time connectivity/best-lanes graph, which is not rebuilt from runtime permission changes; it is not merely the connectors' permission attributes. **Compile open, gate at t=0.**

## The changeover must be a cascading sweep

A safe transition is three stages per physical lane: (1) stop admitting — close the losing direction's identity on the **upstream-most** facility edge only; (2) sweep — cascade the closure downstream edge by edge, closing level *k+1* only once level *k* (normal lane plus the internal connector it feeds) is verifiably empty; (3) grant — open the gaining direction only when every level is empty. Because a closed level cannot be re-entered laterally, the swept region only grows and the procedure terminates.

Closing every level at once instead strands vehicles that are already past a junction on a now-closed connector.

## Clearance time tracks residual queue, not lane length

Measured across 4 lane lengths (1000-4500 m) x 4 westbound demand levels x 3 seeds, with the nominal dead time set to 0 so the number is the raw sweep time:

- **corr(clearance, lane length) = 0.09**; **corr(clearance, residual queue) = 0.647**.
- The naive `lane_length / free_flow_speed` heuristic is wrong in both directions: the measured/free-flow ratio ranged **0.237** (4500 m, light queue — over-predicts by ~4x) to **1.995** (1000 m, heavy queue — under-predicts by ~2x).
- **Mechanism: lateral eviction, not drive-through.** `setAllowed` does not eject anyone, but SUMO's lane-change model actively pushes vehicles off a lane they may no longer use: **79.5%** of the cohort present at sweep start left by changing lanes sideways, only 20.5% by driving off the downstream end. The lane-change share falls from 98% to 54% as demand rises and adjacent lanes fill — which is precisely why clearance grows with residual queue. This qualifies [[dynamic-hard-shoulder-running-with-traci-lane-permissions]]'s "expect no instant lane-clear on close": the lane does not clear instantly, but it clears far faster than free-flow traversal implies, and by a different mechanism.
- **A plausible nominal dead time will usually be too short**: with 60 s assumed, **43 of 48 runs (90%)** needed longer; measured clearance ranged 43-181 s, median 81 s.

## SUMO's SSM device is blind to the head-on hazard

The two identities of a reversible lane belong to different SUMO **edges**, so SUMO never relates them however exactly their geometry coincides. On a deliberately broken run where 65 vehicles were still on the lane when it was granted to the opposing direction and vehicles drove clean through each other, the SSM device (see [[surrogate-safety-measures]]) logged **0 conflicts between opposing-direction vehicles and 0 type-111 collisions**, while reporting 24 792 ordinary rear-end/crossing conflicts — against 24 395 and 24 698 in the two *safe* arms. **The metric is not merely insensitive; the safe and unsafe arms are indistinguishable on it.**

The hazard must therefore be measured with a custom longitudinal co-occupancy scan, and that scan needs a positive control to have any evidential value. Verified with two instruments sharing no code (a live TraCI lane scan and an offline `fcd-output` geometric scan):

| arm | exposed timesteps | overlapping pair-samples | min longitudinal gap | occupancy at grant |
|---|---|---|---|---|
| swept, 60 s dead time | 0 / 0 | 0 / 0 | n/a | 0 |
| swept, 0 s dead time | 0 / 0 | 0 / 0 | n/a | 0 |
| instantaneous flip (broken) | 92 / 92 | 2 969 / 2 969 | **-3768.3 m** | 65 |

(values shown as *live scan / FCD scan* — the two instruments agreed exactly). Minimum lateral separation in the broken arm was **0.000 m**: the opposing vehicles were on the same pavement. The `dead_time=0` arm passing shows the safety comes from the **sweep**, not from an arbitrary dead-time constant.

## Charging the changeover honestly

- **Score both directions.** Total person-hours of delay over the favoured *and* the sacrificed direction, computed censoring-robustly (unfinished and never-inserted vehicles charged), per [[teleport-artifacts-and-gridlock-resolution-validity]]. Scoring only the peak direction makes reversal look free, because reversal's entire cost lands on the minor direction.
- **Two dead-time accountings, and they differ a lot.** A capacity-based upper bound (`clearance_s x measured per-lane capacity`) gave **79.0** forgone lane-entries per simulated day; the direct CRN-matched measurement of corridor arrivals inside the changeover windows gave **11.6** — about **15%** of the bound, because the direction giving up the lane is usually undersaturated at the moment the changeover happens. Report both; do not present the upper bound as the loss.

## The break-even asymmetry, and the regime where reversal is a net loss

On a 3 km six-lane signalized corridor (90 s cycle, corridor g/C = 0.533; measured capacity **1032 veh/h per open lane**, 2/3/4 open lanes = **2058.7 / 3113.3 / 4128.0 veh/h**) at a fixed **4600 veh/h** total, with the directional split swept 50/50 to 85/15, 5 CRN-matched seeds per cell, scored on person-hours of delay across both directions:

| split | static 3+3 | fixed reversal | paired difference [95% CI] |
|---|---|---|---|
| 50/50 | 137.92 ± 4.54 | 343.07 ± 33.92 | **+205.15 [+175.08, +235.22]** |
| 55/45 | 140.09 ± 4.60 | 194.08 ± 29.14 | **+53.99 [+29.04, +78.95]** |
| 60/40 | 146.22 ± 7.28 | 149.15 ± 7.62 | **+2.93 [+0.29, +5.57]** |
| 65/35 | 165.68 ± 10.05 | 142.03 ± 3.75 | **−23.65 [−33.50, −13.80]** |
| 70/30 | 267.45 ± 48.32 | 140.27 ± 4.62 | **−127.18 [−171.78, −82.59]** |
| 85/15 | 958.32 ± 53.46 | 169.21 ± 6.07 | **−789.12 [−838.80, −739.44]** |

**Break-even at 60.6% / 39.4%** (interpolated across the paired contrast; the demand-responsive policy gives 60.7%), bracketed by two statistically significant cells on either side.

**There is a real demand regime in which reversal is a net loss even though the peak direction improves.** At 50/50 the reversal *improved* the favoured direction by 20.2% (68.84 → 54.94 person-hours) while degrading the sacrificed direction by 317% (69.08 → 288.13), a **net 149% worsening**. The mechanism is a hard capacity threshold rather than a smooth trade: 2300 veh/h against a 2-lane capacity of 2058.7 veh/h is v/c = 1.12, and an oversaturated direction accumulates delay far faster than an undersaturated one sheds it. Scoring only the peak direction — the natural mistake — would have reported this as a 20% win. Compare [[managed-lanes-empty-lane-paradox-and-person-throughput]], where the same "capacity taken from the general lanes must be charged" logic applies.

**Fixed schedule versus demand-responsive.** Below break-even the responsive policy wins decisively *by not firing*: 0 changeovers at 50/50 and 55/45, making it identical to the do-nothing baseline and beating the fixed schedule by 205.15 and 53.99 person-hours. Above break-even it trails the fixed schedule by a widening, statistically significant margin (+12.82 at 75/25, +22.73 at 80/20, +57.62 at 85/15) because it must observe the asymmetry for a confirmation window before acting, and reverts late for the same reason. On a full simulated day with matched AM/PM peaks the fixed schedule cut corridor delay 66.5% (930.59 → 312.00 person-hours) and the responsive policy 63.0% (→ 344.06), with the responsive policy significantly behind (+32.06 [+12.82, +51.30]). **The fixed schedule wins when the peak pattern is known and reliable; the responsive policy is the better choice when it is not, because its downside is bounded by the do-nothing baseline while the fixed schedule's is not.**

**Minimum dwell bounds flapping but does not eliminate it.** Four of five day-scenario seeds performed exactly 4 changeovers (structurally the same as the fixed schedule but ~830 s later); one seed performed 6, with an extra revert-and-return pair 960 s apart against a 900 s dwell floor. Report the per-seed changeover count, not the mean.
