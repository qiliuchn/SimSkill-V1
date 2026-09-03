---
summary: SUMO's default truck vType's emergent Passenger-Car Equivalent (E_T) reproduces HCM's level-terrain reference (~1.5) on a freeway lane-drop bottleneck but falls well short (~1.16-1.18) at a signalized approach — two independently-verified measurement methods that genuinely disagree by 21-28% rather than converging; grade sensitivity is a near-total null result across all 11 of SUMO's built-in car-following models, since grade feeds only the emission/energy models, not longitudinal dynamics; and a pure-truck fleet gives a lower E_T than a mixed fleet does, showing HCM's linear-blend f_HV formula doesn't hold in SUMO because much of the effect comes from fleet heterogeneity itself, not the truck's intrinsic properties alone.
keywords:
  - passenger-car-equivalent
  - PCE
  - heavy-vehicle-factor
  - HCM
  - saturation-flow
  - freeway-capacity
created: 2026-08-01T01:15:00
last_updated: 2026-08-07T03:22:15
sources:
  - "[[episodic-memory/2026-08-01_09-30-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-08-01_09-30-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[webster-method]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[road-gradient-and-energy-consumption]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[urban-freight-delivery-tours-container-semantics-and-policy-levers]]"
  - "[[two-lane-highway-follower-density-and-passing-lane-effectiveness]]"
  - "[[grade-aware-heavy-vehicle-physics-and-climbing-lane-warrants]]"
  - "[[intersection-air-quality-hot-spot-analysis]]"
related_skills:
  - measure-heavy-vehicle-passenger-car-equivalent
  - measure-saturation-flow-and-validate-webster-method
  - build-macroscopic-fundamental-diagram
  - model-road-gradient-effects-on-energy
  - design-signal-change-and-clearance-intervals
  - model-urban-freight-delivery-tours
  - analyze-intersection-air-quality-hot-spots-from-microsimulation
  - model-grade-aware-heavy-vehicle-performance-and-climbing-lanes
related_skills_for_graph_view:
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[build-macroscopic-fundamental-diagram]]"
  - "[[model-road-gradient-effects-on-energy]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[model-urban-freight-delivery-tours]]"
  - "[[analyze-intersection-air-quality-hot-spots-from-microsimulation]]"
  - "[[model-grade-aware-heavy-vehicle-performance-and-climbing-lanes]]"
---

# Heavy-Vehicle Passenger-Car Equivalent (PCE/E_T) in SUMO

The Passenger-Car Equivalent (PCE, or E_T for trucks specifically) quantifies how many "equivalent passenger cars" one heavy vehicle consumes in terms of capacity impact — a foundational number in real-world capacity analysis (HCM cites roughly 1.5 on level terrain, escalating steeply on grades). This page documents the first empirical measurement of SUMO's own emergent E_T, using the `measure-heavy-vehicle-passenger-car-equivalent` skill's dual-testbed methodology.

## Verified finding: two independent measurement methods genuinely disagree

Measuring E_T at a signalized-approach saturation-headway rig and, independently, at a freeway lane-drop bottleneck, both with bottleneck-binding conditions positively verified from raw data: SUMO's **default** truck vType produced a freeway-measured E_T (1.41-1.50) close to HCM's level-terrain reference (~1.5), but a signal-measured E_T (1.16-1.18) far below it — a **21-28% gap between the two methods, with non-overlapping 95% confidence intervals**. This is reported as a genuine, real disagreement, not reconciled or averaged away — the two testbeds stress different physical mechanisms (see the decomposition finding below), so their disagreement is itself informative about *why* SUMO's truck behaves differently from the real-world reference in different contexts.

## Verified, near-total null result: road grade does not affect SUMO's longitudinal capacity dynamics

Testing E_T sensitivity across verified 0-6% road grades (using z-coordinate elevation, confirmed from the compiled network) and **all 11 of SUMO's built-in car-following models** (Krauss, KraussOrig1, IDM, EIDM, ACC, CACC, W99, Wiedemann, PWagner2009, BKerner, Daniel1): measured E_T stayed essentially flat regardless of grade, and an independent single-vehicle probe found acceleration/speed trajectories were effectively identical across grades under every tested model (43 of 44 checked datapoints exactly identical, one differing by a negligible ~5e-6 relative amount, almost certainly a rounding artifact). `traci.vehicle.getSlope()` correctly reports the actual grade, so the elevation genuinely reaches the vehicle — **SUMO's default car-following models simply don't use grade in their longitudinal-dynamics equations.** Grade drives SUMO's emission/energy models (see [[road-gradient-and-energy-consumption]]) but not capacity or car-following behavior — HCM's real-world grade-driven E_T escalation is a phenomenon SUMO's default models cannot reproduce without an explicit grade-aware modification. **This same mechanism was independently re-confirmed in a later episode studying signal clearance intervals**: SUMO's measured stop/go decision boundary at a signalized approach barely moved across a swept grade range despite the ITE analytic formula predicting a large stopping-distance shift — see [[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]].

## Verified finding: different testbeds are driven by different vType parameters

Decomposing E_T via controlled single-parameter vType variants found the signal-approach effect was dominated by reaction/gap time (`tau`), with vehicle length a secondary factor and acceleration/max-speed contributing almost nothing; the freeway effect was instead dominated by acceleration and a speed-differential effect. The speed-differential effect existed specifically because SUMO's default truck `maxSpeed` happened to sit *above* the freeway's actual speed limit in the tested scenario — a parameter that appears inert can simply be non-binding at the specific road speed used, not truly irrelevant in general. Additivity of the individually-measured parameter effects (summed in headway-increment space) held almost exactly at the signal but was clearly sub-additive on the freeway — a genuine structural difference between the two mechanisms, not a modeling inconsistency to resolve.

## Verified, counter-intuitive finding: HCM's linear-blend formula is the wrong shape for SUMO

A **pure heavy-vehicle fleet** (100% trucks) measured a *lower* E_T than the value implied by a **mixed** fleet at moderate truck share. This means HCM's standard `f_HV = 1/(1 + P_HV*(E_T-1))` formula — which implicitly treats a truck's capacity impact as a fixed, fleet-composition-independent constant — does not correctly describe SUMO's behavior. A substantial share of the measured "truck effect" in a mixed fleet arises from **fleet heterogeneity itself** (cars and trucks having different equilibrium following gaps/speeds, creating extra friction from the mixing alone), an effect a homogeneous pure-truck fleet doesn't experience at all. Any SUMO-based E_T measurement should report a curve across truck-share levels, not a single number extrapolated from one measured share.

## Verified calibration procedure

A single-parameter calibration (adjusting `tau`, fit from a small trial sweep) was verified — via independent re-measurement at multiple truck shares, not just a fitted point prediction — to bring the signal-side E_T to an HCM-consistent target, with the target falling inside the re-measured confidence interval at every tested share. SUMO's own built-in `trailer` vClass was also found, untuned, to give a freeway E_T closer to HCM's higher combination-truck reference (~2.0) than the default `truck` vClass does.

## Practical takeaways

- Never trust a single E_T measurement method — measure via at least two independent approaches (e.g. signal saturation-headway and freeway discharge-capacity) and report disagreement honestly if it occurs, rather than picking whichever number looks more plausible.
- Don't assume SUMO's default car-following models reproduce real-world grade sensitivity for capacity — verify directly, since the default behavior may be a genuine null result.
- Decompose a measured capacity-impact effect by vType parameter before assuming which vehicle attribute is "responsible" — different scenarios (signal vs. freeway) can be driven by entirely different parameters.
- Check whether a real-world formula's structural assumptions (e.g. HCM's fleet-composition-independent E_T) actually hold in simulation before applying it to convert a measured mixed-fleet effect into a single reusable constant.
- Verify any vType calibration by independent re-measurement across the relevant operating range, not just by trusting a fitted interpolation.

See the `measure-heavy-vehicle-passenger-car-equivalent` skill for the full dual-testbed measurement, decomposition, and calibration methodology. [[urban-freight-delivery-tours-container-semantics-and-policy-levers]] applies this page's signalized-approach E_T measurement to test whether truck-route restrictions concentrating freight onto an arterial cause a detectable capacity loss for cars — confirming the PCE mechanism directly but finding it undetectable at realistic urban freight volumes (well below the freight-share threshold needed for a measurable capacity effect).
