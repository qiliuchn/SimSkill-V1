---
name: operate-reversible-tidal-flow-lane
description: Use this skill when the user wants a REVERSIBLE lane in SUMO — tidal-flow, contraflow, or counterflow operation where a lane's direction of travel changes during the run (AM/PM peak lane reversal on an arterial, bridge, or tunnel) — as opposed to a lane that is merely opened/closed to one direction (hard shoulder running) or restricted to a vClass (bus/HOV lanes). Covers the three candidate SUMO encodings and why only one survives testing, the geometrically-coincident opposing-lane trick (spreadType=center plus --geometry.avoid-overlap false), a real changeover procedure with a cascading clearance sweep instead of an instantaneous permission flip, the two independent zero-head-on verification instruments needed because SUMO's SSM device is blind to this hazard, and how to find the directional-demand asymmetry at which reversal actually pays once both directions and the changeover dead time are charged. Trigger on mentions of reversible lane, tidal flow, contraflow, counterflow, lane reversal, changeover, movable barrier, zipper lane, or "should this corridor reverse a lane in the peak."
related_skills:
  - implement-dynamic-hard-shoulder-running
  - model-vclass-lane-permissions
  - simulate-incident-rerouting
  - analyze-intersection-safety-with-ssm
  - quantify-sumo-run-to-run-variability
  - validate-congested-scenario-results-against-teleport-artifacts
  - switch-signal-plans-by-time-of-day-with-waut
  - design-actuated-signal-detector-placement-and-fault-tolerance
related_skills_for_graph_view:
  - "[[implement-dynamic-hard-shoulder-running]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[simulate-incident-rerouting]]"
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
  - "[[switch-signal-plans-by-time-of-day-with-waut]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
related_pages:
  - "[[reversible-lane-encoding-and-changeover-safety]]"
---

# Operate a Reversible (Tidal-Flow) Lane

Builds and operates a lane whose **direction of travel changes during the simulation**, and decides from measured output whether reversing it is worth doing. SUMO has no "reverse this edge" primitive, so the first job is choosing a representation — and the choice is not free: two of the three obvious encodings fail in ways that silently corrupt results.

This is distinct from `implement-dynamic-hard-shoulder-running` (a lane opened/closed to *one* direction; there is no opposing direction to interlock against) and from `model-vclass-lane-permissions` (static, build-time restrictions).

## Encoding: declare every physical lane in BOTH directions, compile it all open

**The accepted encoding.** Give every directional edge of the facility `numLanes` equal to the **full physical cross-section** (6 lanes for a 6-lane road, in *both* the eastbound and westbound edge), `spreadType="center"`, no explicit `shape`, and compile every lane OPEN. Physical lane *k* then has two SUMO identities:

```
EB edge lane i   <->   WB edge lane (N-1-i)      # N = physical lanes
```

Gate them at t=0 and thereafter with `traci.lane.setAllowed`, maintaining the invariant that **exactly one of each pair is passable at any instant**. Permanently-directional lanes are simply pairs whose gating never changes. `scripts/common.py` holds the mapping (`lane_id`, `assignment`, `CONFIGS`); `scripts/build_network.py` builds the net.

**Pass `--geometry.avoid-overlap false` to netconvert.** It defaults to *on* and shoves opposing edges apart, which destroys the coincidence: without it the two representations of a "physical" lane ended up 6.4-19.2 m apart. With it off, all six lane pairs verified at **exactly 0.000 m lateral offset** (`scripts/verify_geometry.py`). That coincidence is what makes the head-on check below a direct geometric observation instead of an inference.

**Do not try to place lanes with an explicit edge `shape`.** netconvert normalises an explicit shape back onto the node line — a flat shape offset laterally from the node line came back rotated or snapped (verified: `shape="10,-3.2 990,-3.2"` compiled to `10.00,0.00 990.00,0.00`). Lateral placement must come from `spreadType` + lane count, not from geometry you write yourself.

**Compile OPEN and gate at t=0** — the `implement-dynamic-hard-shoulder-running` rule, and this skill extends it with a new negative result: **reopening the internal junction connector lanes as well does NOT repair a net compiled closed.** See the rejection evidence below.

## The two rejected encodings, with their measured failure modes

Run the comparison yourself with `scripts/rep_experiment.py`; the numbers below are what it produced on a 3 km six-lane corridor.

**Rejected — separate opposing single-lane edges over the same geometry.** Two failures, both fatal:
- *The lane is unreachable.* Vehicles cannot lane-change between parallel **edges**. With the 2-lane permanent corridor driven to 4000 veh/h against a measured 2059 veh/h capacity (112 vehicles never completed), the parallel reversible edge carried **exactly 0 vehicles**. The extra capacity is only usable by vehicles whose *route* was pre-assigned to it — which is not what a reversible lane is.
- *Reversal invalidates committed routes.* Pre-assigning 25% of demand to the reversible edge and then reversing it at t=900 s made SUMO **abort the run**: `Error: Vehicle 'EB.1000' has no valid route. No connection between edge 'apW_in' and edge 'RL3_EB'. Quitting (on error).` With `--ignore-route-errors true` it survives but degrades: 28 teleports, all logged `waited too long (wrong lane)`, and 210 of 1063 vehicles never arriving.

**Rejected — `rerouter`/`closingLaneReroute`.** It *does* gate the lane (new entries during the closed interval: 1, versus 536 before and 746 after), but it cannot run a changeover:
- *No clearance handshake.* The closure begins at a scheduled instant with vehicles still on the lane; occupancy took **~240 s** to fall from 90 to 0 (t=600 → t=840) and the lane reopens at the interval end with no check at all.
- *The interval is not runtime-controllable.* `traci.rerouter` exposes only `getParameter`/`setParameter`. `setParameter(id,"begin","1800")` is **silently accepted and does nothing** (returns `None`; `getParameter("begin")` returns `''`) — the classic silently-ignored-parameter trap from `design-actuated-signal-detector-placement-and-fault-tolerance`. A demand-responsive policy is therefore impossible.
- It can only *close*, never *grant* the opposing direction, so it cannot enforce the mutual-exclusion invariant on its own.

**The compile-closed trap, quantified and extended.** A net compiled with the reversible lanes `allow="authority"` bakes that restriction into the **internal junction connector lanes** (verified structurally: 4 of 8 checked connectors carry `allow="authority"` in the closed build, 0 of 8 in the open build). Reopening the normal lanes at runtime leaves the lane usable only in fragments: end-to-end completion through the downstream junction collapsed to **6.7%** on the reopened lane versus 60.8% on the same lane in the compile-open build, with 208 vehicles still stuck at simulation end (1800 s after demand ended) and 74 never inserted. **Also calling `setAllowed` on the internal connector lanes does not fix it** (8.4% completion — statistically indistinguishable from 6.7%): the damage is in the load-time connectivity graph, not in the connector lanes' permission attributes.

## The changeover: a cascading sweep, not a permission flip

`scripts/reversible_controller.py` implements the transition as three stages per physical lane:

1. **Stop admitting** — close the losing direction's representation on the **upstream-most** facility edge only. New vehicles can no longer enter the lane at the facility entrance.
2. **Sweep** — cascade the closure downstream edge by edge: as soon as level *k* (a normal lane plus the internal connector it feeds) is verifiably empty, close level *k+1*. A closed level cannot be re-entered laterally, so the swept region only grows and the procedure always terminates.
3. **Grant** — only when *every* level of the losing direction is empty **and** the nominal dead time has elapsed, open the gaining direction's representation.

Closing the loser's lanes in one shot instead is wrong: it strands vehicles that are already on the lane at the far end of a closed junction connector.

## Measure the clearance time; do not assume it

**Two things about clearance are counter-intuitive and both were measured, not assumed** (`scripts/clearance_study.py`, 4 lane lengths x 4 residual-queue levels x 3 seeds = 48 runs, nominal dead time set to 0 so the number is the raw sweep time):

- **Clearance is essentially independent of lane length.** corr(clearance, lane length) = **0.09** across 1000-4500 m; corr(clearance, residual queue) = **0.647**. The naive `lane_length / free_flow_speed` heuristic is wrong in *both* directions — it over-predicts by ~4x on a 4500 m lane (measured/free-flow ratio 0.237) and under-predicts by ~2x on a 1000 m lane (ratio 1.995).
- **The mechanism is lateral escape, not drive-through.** `setAllowed` does not eject anyone, but SUMO's lane-change model actively pushes vehicles off a lane they are no longer permitted on: **79.5%** of the cohort present at sweep start left by changing lanes sideways, only 20.5% by driving off the downstream end. As demand rises the adjacent lanes fill and the lane-change share falls (98% -> 54%), which is exactly why clearance grows with residual queue.

**Expect your assumed dead time to be too short.** With a plausible 60 s nominal dead time, **43 of 48 runs (90%)** needed longer; measured clearance ranged 43-181 s, median 81 s. Report the measured distribution, and treat the nominal dead time as a floor the sweep may overrun — never as the changeover duration.

## Verifying the changeover — and why the SSM device cannot do it

**SUMO's SSM device is blind to this hazard.** The two directional representations of a physical lane are different *edges*, so SUMO never relates them no matter how exactly their geometry coincides. Verified on a deliberately broken run in which 65 vehicles were still on the lane when it was granted to the opposing direction and vehicles literally drove through each other: the SSM device logged **0 conflicts between opposing-direction vehicles and 0 type-111 collisions**, while reporting ~24.4-24.8 k ordinary rear-end/crossing conflicts in *every* arm, safe and broken alike (24 395 / 24 698 / 24 792 — the safe and broken arms are indistinguishable on that metric). Do not accept "SSM shows no head-on conflicts" as evidence of anything.

Use **two independent instruments plus a positive control** (`scripts/run_verification.py`):

1. **Live TraCI occupancy scan** at the instant permissions flip — must be exactly 0 on every lane id of both directional representations, including the internal connectors.
2. **Offline geometric scan of `fcd-output`** (`scripts/verify_headon_fcd.py`) — shares no code with (1); looks for two vehicles from opposing directions on the same physical lane and computes their longitudinal gap and closing TTC. Restrict with `--device.fcd.begin` and `--fcd-output.filter-edges.input-file` or the file becomes unmanageable.
3. **A deliberately broken positive control** — an instantaneous flip with no sweep. Without it a "zero conflicts" result is vacuous.

Verified outcome: swept arm 0 exposed timesteps in both instruments; broken arm **92 exposed timesteps and 2 969 overlapping pair-samples, identical in both instruments**, minimum longitudinal gap **-3768.3 m** (i.e. clean pass-through), minimum lateral separation **0.000 m**. Also run a `dead_time=0` swept arm: it still passes (clearance 41 s, 0 occupancy at grant), proving the safety comes from the **sweep**, not from an arbitrary dead-time constant.

## Policy comparison and the break-even question

Three policies (`scripts/run_study.py`): **A** static, **B** fixed time-of-day schedule, **C** demand-responsive from E2 directional occupancy with two-sided hysteresis and a minimum dwell time.

- **Calibrate C's thresholds against the corridor's own measured occupancy range** (`analysis/policyC_threshold_calibration.json` pattern), not against plausible-sounding numbers — same discipline as `implement-dynamic-hard-shoulder-running`'s "threshold above peak occupancy makes the controller a permanent no-op".
- **Score both directions.** Total person-hours of delay summed over the favoured *and* the sacrificed direction, computed censoring-robustly (charge unfinished and never-inserted vehicles), per `validate-congested-scenario-results-against-teleport-artifacts`. Scoring only the peak direction makes reversal look free.
- **Charge the dead time two ways**: a capacity-based upper bound (`clearance_s x measured per-lane capacity`) and a direct CRN-matched measurement of arrivals inside the changeover windows. On a full day these differed by ~7x (79.0 forgone lane-entries upper bound vs 11.6 arrivals actually lost), because the direction losing the lane is usually undersaturated when the changeover happens — report both, and do not present the upper bound as the loss.
- **Use Common Random Numbers**: generate explicit-vehicle route files with departure times drawn in Python (`scripts/gen_demand.py`), so all policies at a given (split, seed) see a byte-identical demand realisation, and report **paired** differences with paired-t CIs.
- **Measure capacity first** (`scripts/measure_capacity.py`), as the peak of the served-flow-vs-demand curve, so you can place the demand levels where reversal is genuinely marginal. Verified here: 1032 veh/h per open lane, near-perfectly linear in lane count (2/3/4 lanes -> 2059/3113/4128 veh/h).

## Verified results — what the answer actually looked like

3 km six-lane corridor, 90 s cycle, corridor g/C = 0.533, fixed 4600 veh/h total, 5 CRN-matched seeds per cell.

**Break-even at a 60.6% / 39.4% directional split** (the demand-responsive policy gives 60.7%), bracketed by significant cells either side. Paired B−A person-hours of corridor delay: **+205.15** at 50/50, **+53.99** at 55/45, **+2.93** at 60/40, **−23.65** at 65/35, **−127.18** at 70/30, **−789.12** at 85/15 — every one significant at 95%.

**Reversal is a net loss at low asymmetry despite helping the peak direction.** At 50/50 the favoured direction improved 20.2% (68.84 → 54.94 person-hours) while the sacrificed direction worsened 317% (69.08 → 288.13), a **net 149% worsening**. The mechanism is a hard capacity threshold: 2300 veh/h against a 2-lane capacity of 2058.7 veh/h is v/c = 1.12. **Scoring only the peak direction would have called this a 20% win** — this is the single most important reason to score both directions.

**Full simulated day** (AM 75/25 eastbound peak, PM 25/75 peak, 5 seeds): static 3+3 **930.59 ± 64.11** person-hours; fixed schedule **312.00 ± 7.24** (−66.5%, paired −618.59 [−682.71, −554.48]); demand-responsive **344.06 ± 12.83** (−63.0%, paired −586.53). The responsive policy **trails** the fixed schedule (C−B = +32.06 [+12.82, +51.30], significant) on a day whose peaks the schedule already matches.

**But below break-even the responsive policy wins by not firing**: 0 changeovers at 50/50 and 55/45, making it identical to the baseline and beating the fixed schedule by 205.15 and 53.99 person-hours. Above break-even it trails by a widening margin (+12.82 at 75/25 to +57.62 at 85/15, all significant) purely from detection lag. **A fixed schedule's downside is unbounded; a responsive policy's is bounded by the do-nothing baseline.**

**Validity**: across 135 policy runs and 196 executed changeovers — 0 grants at non-zero occupancy, 0 head-on exposed timesteps, 0 teleports, 0 never-inserted and 0 unfinished corridor vehicles.

## Gotchas

- **`--geometry.avoid-overlap` defaults to ON and silently separates your coincident opposing lanes** — pass `false` explicitly and verify the compiled lane shapes.
- **netconvert normalises an explicit edge `shape` back onto the node line** — you cannot place lanes laterally by writing coordinates.
- **A net compiled with the reversible lane closed cannot be repaired at runtime, not even by also reopening the internal connector lanes** — compile open, gate at t=0.
- **`traci.rerouter.setParameter` is silently accepted and does nothing** — rerouter intervals are not runtime-controllable.
- **Parallel *edges* are not lane-changeable** — an "overlapping opposing edges" encoding produces an unreachable lane (measured: 0 vehicles) unless demand is pre-routed onto it, and reversal then aborts the run with a hard `no valid route` error.
- **SUMO's SSM device cannot see head-on exposure between coincident opposing edges** — a custom longitudinal co-occupancy scan is mandatory, and it needs a broken positive control to have any evidential value.
- **Clearance time tracks residual queue, not lane length** — and it routinely exceeds a plausible nominal dead time (90% of runs here).
- **A minimum dwell time bounds but does not eliminate switching** — one seed in five still performed an extra reversal pair 960 s apart against a 900 s dwell floor. Report the per-seed changeover count, not just the mean.

## Related

- `implement-dynamic-hard-shoulder-running` — the one-directional ancestor: same `setAllowed` mechanism and compile-open rule, but with no opposing direction, hence no mutual-exclusion invariant, no sweep, and no head-on hazard. This skill extends its compile-closed trap with the "reopening internal lanes doesn't help either" negative result and contradicts its "no instant lane-clear on close" note by showing the lane-change model does actively evict.
- `model-vclass-lane-permissions` — the static, build-time counterpart of the permission mechanism.
- `simulate-incident-rerouting` — where `closingLaneReroute` is the right tool; this skill documents why it is the wrong tool for a reversal.
- `analyze-intersection-safety-with-ssm` — the SSM device this skill tests and finds blind to head-on exposure across coincident opposing edges.
- `quantify-sumo-run-to-run-variability` — the CRN/paired-contrast and measure-capacity-as-the-peak-of-the-curve discipline applied here.
- `validate-congested-scenario-results-against-teleport-artifacts` — the censoring-robust delay accounting used to charge both directions honestly.
- `switch-signal-plans-by-time-of-day-with-waut` — the time-of-day scheduling analogue on the signal side; policy B is its lane-assignment counterpart.
- `design-actuated-signal-detector-placement-and-fault-tolerance` — the silently-ignored-parameter trap that `traci.rerouter.setParameter` reproduces exactly.
- [[reversible-lane-encoding-and-changeover-safety]] — the underlying encoding mechanics, verified failure modes, clearance-time law, SSM blindness, and the measured break-even asymmetry.
