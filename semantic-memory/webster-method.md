---
summary: Webster's method (1958) computes an intersection's delay-minimizing signal cycle length and green splits from measured saturation flow rate and lost time; verified in SUMO by measuring these parameters directly from real stop-line discharge data (not assumed), the method's cycle-length prediction landed within a fraction of a second of a brute-force simulated optimum near critical saturation, but SUMO's default vehicles discharge ~15-22% faster than the textbook/tool-default assumption, and the formula itself diverges or becomes undefined exactly where saturation approaches or exceeds capacity, while simulated delay remains well-behaved throughout that range.
keywords:
  - webster-method
  - saturation-flow-rate
  - startup-lost-time
  - critical-flow-ratio
  - signal-cycle-optimization
  - discharge-headway
created: 2026-07-31T10:30:00
last_updated: 2026-08-07T01:30:23
sources:
  - "[[episodic-memory/2026-07-31_11-15-00/outputs/FINDINGS.md]]"
  - "[[episodic-memory/2026-07-31_11-15-00/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[actuated-traffic-signals]]"
  - "[[heavy-vehicle-passenger-car-equivalent-in-sumo]]"
  - "[[actuated-signal-detector-design-and-fault-tolerance]]"
  - "[[roundabout-capacity-law-and-demand-metering]]"
  - "[[signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff]]"
  - "[[sumo-time-discretization]]"
  - "[[hcm-control-delay-vs-sumo-delay-metrics]]"
  - "[[mutcd-signal-warrants-and-the-demand-vs-served-volume-trap]]"
  - "[[one-lane-two-way-alternating-flow-and-shared-lane-representation]]"
  - "[[intersection-air-quality-hot-spot-analysis]]"
  - "[[coordinated-adaptive-signal-control-detector-bias-and-transition-cost]]"
related_skills:
  - measure-saturation-flow-and-validate-webster-method
  - optimize-signals-by-tlscycleadaptation
  - create-single-intersection
  - measure-heavy-vehicle-passenger-car-equivalent
  - design-actuated-signal-detector-placement-and-fault-tolerance
  - measure-roundabout-capacity-and-implement-metering
  - implement-scats-style-coordinated-adaptive-signal-control
  - design-signal-change-and-clearance-intervals
  - control-one-lane-two-way-alternating-flow-through-a-work-zone
  - analyze-intersection-air-quality-hot-spots-from-microsimulation
related_skills_for_graph_view:
  - "[[measure-saturation-flow-and-validate-webster-method]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[create-single-intersection]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[design-actuated-signal-detector-placement-and-fault-tolerance]]"
  - "[[measure-roundabout-capacity-and-implement-metering]]"
  - "[[implement-scats-style-coordinated-adaptive-signal-control]]"
  - "[[design-signal-change-and-clearance-intervals]]"
  - "[[control-one-lane-two-way-alternating-flow-through-a-work-zone]]"
  - "[[analyze-intersection-air-quality-hot-spots-from-microsimulation]]"
---

# Webster's Method

Webster's method (Webster, 1958) is the classic closed-form procedure for computing a signalized intersection's delay-minimizing cycle length and green-time splits from each approach's demand flow, the intersection's saturation flow rate, and its lost time per phase. It underlies `optimize-signals-by-tlscycleadaptation` (SUMO's `tlsCycleAdaptation.py`), but that tool consumes saturation flow and lost time as **user-supplied assumptions** (`-H`/`-l` flags, defaulting to a 2s saturation headway and 4s lost time) rather than measuring them — this page documents what happens when those assumptions are checked against SUMO's actual emergent discharge behavior, measured directly from stop-line detector data. See `measure-saturation-flow-and-validate-webster-method` for the full measurement and validation workflow.

## The equations

```
y_i = q_i / s                        (critical flow ratio for phase i: demand / saturation flow)
L   = sum_i (l1 + l2_i)              (total lost time per cycle: startup lost time + clearance)
Y   = sum_i y_i                      (sum of critical flow ratios across phases)
C_opt = (1.5*L + 5) / (1 - Y)        (optimal cycle length; undefined/negative if Y >= 1)
g_eff,i = (C - L) * y_i / Y          (effective green time allocated to phase i)
d(C) = C*(1-lam)^2/(2*(1-lam*x)) + x^2/(2*q*(1-x)) - 0.65*(C/q^2)^(1/3) * x^(2+5*lam)
        with lam = g_eff/C, x = q/(lam*s)
```

`s` (saturation flow rate) and `l1` (startup lost time) are the two parameters the whole theory rests on, and are exactly the two SUMO never measures for itself — every consumer of Webster's equation in SUMO's toolchain (including `tlsCycleAdaptation.py`) treats them as inputs to be assumed or configured.

## Verified finding: saturation flow and lost time are emergent, not fixed constants

Measuring discharge headway directly from per-vehicle stop-line crossing timestamps under a permanently oversaturated standing queue, across six car-following parameterizations on an identical network and signal:

- **Measured saturation flow spanned 1766-2457 veh/h/lane (a 39% range)** from car-following parameters alone — "1900 veh/h/lane" (the common textbook figure) is not a property of the intersection geometry; it is a property of the vType loaded onto it.
- **`tau` (driver reaction/headway time) sets the saturation headway almost 1:1** (`dh_s/dtau ≈ 0.9-1.0`), consistent with the equilibrium relation `h_s = tau + (length+minGap)/v_d` — but only when `v_d` is the vehicles' **emergent discharge speed at the stop line** (found to be ~80% of the posted speed limit), not the speed limit itself.
- **`accel` is cleanly separable from `tau`/geometry**: it barely moves the saturation headway but strongly shifts startup lost time (from near-zero up to +1.7s in one verified comparison) — acceleration capability sets *how quickly the queue reaches its steady discharge rate*, not the steady rate itself.
- **SUMO's default vehicle's measured startup lost time was effectively zero (slightly negative)** — well below the ~2s field-practice assumption most signal-timing guidance uses.
- **The classic textbook headway-decay shape (monotone decay to a flat asymptote) is not guaranteed.** SUMO's Krauss model can produce headways that dip *below* the eventual asymptote at low queue positions (an emergent acceleration-wave/platoon-dispersion effect: the discharging platoon crosses the stop line below the speed limit, with crossing speed rising as the platoon spreads out) before climbing back — meaning "the saturation headway" is a real asymptotic property but the approach to it is not the smooth textbook curve.

## Verified finding: a tool's default capacity assumption can be substantially wrong

`tlsCycleAdaptation.py`'s default `-H 2` (2s saturation headway ≈ 1800 veh/h/lane) was checked against SUMO's own measured default-vehicle discharge rate (2191 veh/h/lane) — a **21.7% mismatch**. Running the tool with its default assumption on the same network/demand produced a signal plan costing **16-26% more simulated delay** than the plan computed from the actually-measured saturation flow, and in one case wrongly triggered the tool's own oversaturation fallback (`sum(y)≥1` → falls back to max cycle length) on a network that was genuinely undersaturated by the true parameters. **The tool's arithmetic is correct for the capacity it's told to assume** — this is not a bug in the tool, but a reminder that Webster-based tools are only as good as their saturation-flow input, and that input should be measured for the actual vType mix in use rather than accepted at a textbook or tool default, especially for any non-default vehicle configuration.

**Re-qualification (2026-08-04 time-discretization audit, see [[sumo-time-discretization]]): the 21.7%/16-26% figures above were measured at `--step-length 0.1` with `actionStepLength` left tied to it — i.e. every driver was given a 0.1-second reaction time, not the ~1s a real driver has.** Re-measured with `actionStepLength` pinned at a plausible 1.0s (8 CRN seeds, independent rebuild of the testbed): SUMO's default vehicles discharge at **1890 veh/h/lane**, only **5.0%** off the tool's 1800 default, not 21.7%. A 5% mismatch would not plausibly trigger the oversaturation fallback or cost 16-26% delay — those consequences are themselves an artifact of the same reaction-time confound. **The underlying methodological lesson is unaffected: measure saturation flow for the vType actually in use, don't accept a tool default.** What changes is the *size* of the error correctly attributable to the tool's default, which is convention-dependent and was previously overstated by roughly 4-5x. The measured startup lost time is even more convention-sensitive: 0.09s at SUMO's plain defaults (`dt=1s`, Euler) vs 1.62s once reaction time is properly pinned at a fine step length — a ~1.5s lost time simply cannot be resolved by a 1-second step at all, so any startup-lost-time figure measured at `dt=1s` should not be trusted as a measurement.

## Verified finding: the prediction is accurate near critical saturation, and breaks down exactly where theory predicts

Comparing Webster's predicted optimal cycle length and delay curve (computed from measured parameters) against a brute-force simulated cycle-length sweep at three saturation levels:

- **Near critical saturation (Y≈0.85), Webster's C_opt landed within a fraction of a second of the true simulated-optimal cycle length**, at only ~1% excess delay if run at the exact (non-grid) predicted value — a strong practical result, given real measured inputs.
- **Simulated delay sits systematically offset from Webster's prediction** by a roughly constant amount at every cycle length — expected, since a typical simulated delay proxy (e.g. `tripinfo`'s `timeLoss`) includes acceleration/deceleration loss that Webster's pure stopped-delay model excludes.
- **As any individual phase's degree of saturation `x` approaches 1, Webster's formula diverges toward its own predicted delay far exceeding what simulation actually shows** — simulated delay stays bounded because it's measured over a finite demand period, while the formula's `x²/(2q(1-x))` term has no such bound.
- **Once the network-wide critical-flow sum `Y≥1`, Webster's cycle-length formula returns an undefined or negative result and its delay formula is undefined everywhere** — while the simulation continues to produce a well-behaved, finite, monotone-then-flattening delay curve across the same cycle-length range. The qualitative advice the formula's structure implies (favor a longer cycle under oversaturation to amortize lost time) can still hold even where the formula's own output is meaningless.
- **The flatness of the delay-minimizing optimum is saturation-dependent and can run opposite to the common assumption that "Webster's optimum is flat."** In one verified sweep, the undersaturated case had a sharp relative optimum (a narrow band of cycle lengths within 5% of the minimum), while near-critical and oversaturated cases had a comfortably wide flat band. Don't assume the optimum is forgiving without checking — it can invert with the saturation level.
- **The near-critical accuracy above is not universal.** A separate 4-leg intersection at Y≈0.70 ([[intersection-air-quality-hot-spot-analysis]]) found Webster's C_opt (162.9 s) was 14% longer than the true brute-force-swept optimum (140 s), costing roughly 8-10% excess delay if run at Webster's exact predicted value — a materially worse result than the ~1% excess found near Y≈0.85 above. Verify Webster's accuracy against a brute-force sweep for the specific geometry and saturation level in use rather than assuming the near-critical result generalizes.

## Practical takeaways

- Measure saturation flow rate and startup lost time directly from stop-line detector data for the actual vType(s) in a scenario before trusting a Webster-based tool's default capacity assumption, particularly for any non-default vehicle configuration.
- Use a window-free estimator (regressing vehicles-discharged-per-cycle against green duration) as the primary saturation-flow measurement — it doesn't require assuming which queue positions are "saturated," unlike simple headway averaging.
- Don't assume monotone headway decay in SUMO — report windowed-estimator sensitivity or use the regression estimator.
- A Webster-computed cycle length can be highly accurate near critical saturation but should not be trusted at or beyond `Y≥1`, where the formula itself breaks down even though real (simulated) delay remains finite and well-behaved.
- Check whether the delay-minimizing cycle is actually flat before assuming a rough Webster estimate is "good enough" — flatness varies with saturation level and can be sharp under light demand.

See the `measure-saturation-flow-and-validate-webster-method` skill for the full measurement and validation implementation. Webster's cycle-length formula is about *design*; [[hcm-control-delay-vs-sumo-delay-metrics]] covers the companion *evaluation* question — reusing this page's measured saturation flow as an HCM Chapter 19 delay model's capacity input, and finding that HCM's classical "over-predicts oversaturated delay" reputation is substantially a measurement-scope artifact once whole-trip delay is used instead of a fixed upstream reference point.
