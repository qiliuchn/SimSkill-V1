---
name: equilibrate-endogenous-mode-choice-with-transit-supply-feedback
description: Use this skill when the user wants to model ENDOGENOUS mode choice in SUMO between driving and a parallel transit line, where transit service frequency responds to ridership (the Mohring effect) — as opposed to every other multimodal skill in memory, which treats transit frequency as fixed and mode split as a pure output. Covers building a car-inaccessible dedicated transit right-of-way, an explicit ridership-driven headway rule, an outer mode-split equilibrium loop with a scan-classify-bisect solver (needed because this equilibrium can have multiple roots, some unstable), a feedback-on/feedback-off mechanism control, perturbation-based stability testing, and testing the Downs-Thomson paradox (road expansion making everyone worse off). Trigger on mentions of Downs-Thomson paradox, mode choice equilibrium, transit ridership feedback, Mohring effect, or endogenous transit frequency.
related_skills:
  - simulate-multimodal-transit
  - model-vclass-lane-permissions
  - equilibrate-departure-time-choice-in-bottleneck-model
  - compute-dynamic-user-equilibrium
  - construct-and-verify-braess-paradox
  - model-capacity-constrained-transit-passenger-loading
related_skills_for_graph_view:
  - "[[simulate-multimodal-transit]]"
  - "[[model-vclass-lane-permissions]]"
  - "[[equilibrate-departure-time-choice-in-bottleneck-model]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[construct-and-verify-braess-paradox]]"
  - "[[model-capacity-constrained-transit-passenger-loading]]"
related_pages:
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[transit-capacity-passenger-loading-and-pass-up-dynamics]]"
---

# Equilibrate Endogenous Mode Choice with Transit Supply Feedback

Models a mode-choice equilibrium between driving and a parallel transit line where transit service frequency **responds to ridership** — the Mohring effect — completing this memory's trio of classical traveller-choice-dimension equilibria alongside route choice (`construct-and-verify-braess-paradox`) and departure-time choice (`equilibrate-departure-time-choice-in-bottleneck-model`). Every other multimodal skill in memory (`simulate-multimodal-transit`) treats transit frequency as a fixed input and mode split as a pure output; this skill makes frequency endogenous.

## Building a genuinely car-inaccessible transit right-of-way

Give the transit line's edges `allow="bus"` (or the relevant vClass) on their lanes, following `model-vclass-lane-permissions`'s technique. **Verify this on the compiled network, not just the source XML**, and go further than a passive permission check: explicitly try to route a passenger vehicle over the restricted edges and confirm it hard-fails (SUMO reports "no valid route" / "no connection"), while a bus vehicle on the identical route succeeds. This is essential for a mode-choice equilibrium study, since the entire point is that transit running time must be insensitive to car volume — if a car can sneak onto the transit right-of-way even occasionally, the "insulated from road congestion" assumption the paradox depends on is compromised.

## The ridership-driven headway rule — state it explicitly and verify it

Define an explicit operator headway rule, e.g. `H = clamp(K / Q_transit, H_min, H_max)`, where `K` represents a fixed budget (vehicle-hours or revenue) the operator allocates in proportion to ridership. State every parameter explicitly in the write-up. **Verify realized headways match the rule's output at every equilibrium point**, by parsing the actual emitted schedule (`<stop busStop="..." until="..."/>` times) and comparing inter-departure intervals against what the rule should have produced for that iteration's ridership — don't just trust that the schedule-generation code implements the rule correctly.

**Don't verify realized rider wait against `H/2`.** This is only the *infinite-horizon* limit of expected wait for a Poisson-arrival rider — over a finite demand window, especially near the start/end of service, it can be a poor approximation (verified case: mean absolute error 66.7s using `H/2` vs. 2.9s using the correct method). The correct verification target is the **schedule-integrated expected wait**: `E[W] = (1/T) * integral_0^T (next_departure(t) - t) dt`, computed directly from the emitted timetable. Always use this schedule-integrated form, not the steady-state `H/2` shortcut, when verifying against a finite-horizon simulation.

## The mode-split outer loop: a scan-classify-bisect solver, not naive MSA or single-point bisection

Structure the outer loop like `compute-dynamic-user-equilibrium`'s pattern (simulate → measure cost per mode → shift a fraction of the population → repeat), with an explicit convergence-gap metric (car cost minus transit cost) rather than a fixed iteration count. **But do not trust a single bisection over the full mode-share range `[0,1]`, and do not trust naive MSA alone as the precision solver.**

**Verified finding: the Mohring feedback can create a second, unstable equilibrium.** With feedback active, the cost-gap function of mode share can be genuinely non-monotone, producing two roots — one stable, one unstable (a measurable "transit death spiral" tipping point) — where the feedback-off (frozen-headway) version of the identical scenario has exactly one root. **A naive bisection that only checks the sign of the gap at the two endpoints of a search interval can converge to the wrong root, or wrongly report "no interior equilibrium exists," if it happens to bracket the unstable root or an endpoint beyond it.** The correct approach: scan the mode-share range on a grid, classify every sign change (a root is stable if the gap function crosses from positive-then-negative in the direction that represents "car becoming more expensive drives share back toward transit," unstable if the reverse), and bisect only within the bracket containing the *stable* root.

**Verified finding: naive MSA can be unreliable near a narrow-basin equilibrium.** Even when a scan-classify-bisect solver correctly finds the stable equilibrium, a simpler day-to-day MSA adjustment starting from a different initial mode share can overshoot a narrow basin of attraction and run to the wrong fixed point entirely (e.g. a car-only corner) instead of localizing on the true interior equilibrium. Use MSA as a robustness/comparison check, not as the primary solver, for any equilibrium concept where a supply-feedback loop (like ridership-to-frequency) creates the possibility of multiple or narrow-basin equilibria.

## Testing equilibrium stability directly with perturbation

After finding a candidate equilibrium, don't assume it's stable just because it satisfies the equal-cost (zero-gap) condition — perturb the mode share by a modest amount in both directions (e.g. ±5, ±10 percentage points) and re-simulate to see whether the system's cost gap pushes it back toward the equilibrium (stable) or away from it (unstable). **Verified finding: an equilibrium can be stable from one side and unstable from the other** — a one-sided/narrow basin, where a push in one direction restores the equilibrium with a large, easily-significant restoring cost gap, while a push in the other direction escapes the basin (the gap continuing to push further away) because an unstable second root sits nearby. Report the restoring-gap magnitude alongside its confidence interval and check which specific perturbation directions are individually statistically significant, rather than a blanket claim about the whole perturbation test.

## The mechanism control: freeze the feedback, not just add a caveat

To attribute any observed paradox specifically to the ridership-to-frequency feedback (rather than some other confound of the road-capacity change), run the identical scenario with the headway **frozen at a constant value** (e.g. the value the rule would have produced at the baseline equilibrium) instead of letting it respond to ridership. **Verified finding**: with the feedback genuinely disabled, road capacity expansion that produced a large paradoxical cost increase with feedback active became statistically neutral (or even slightly beneficial) — cleanly isolating the feedback loop as the causal mechanism. Verify the frozen-headway condition genuinely used a constant value in the raw schedule data (not accidentally still applying the ridership rule) before trusting the control.

## The demand sweep: the paradox is a regime, not a knife-edge result

Sweep total demand across several levels and check whether the paradox switches on and off, rather than assuming it holds (or fails) at exactly one calibrated demand level. **Verified finding**: the paradox was absent at low demand (both road-capacity variants collapse to a car-only equilibrium — there's no transit ridership left to starve, since it was never sustained in the first place at that demand), present and non-monotone across a range of moderate-to-high demand, and the specific threshold between "absent" and "present" was a genuine crossing point in the data, not a fitted artifact. This is the same discipline as `compare-one-way-vs-two-way-street-grid-conversion`'s demand-crossover finding, applied to a mode-choice rather than a network-topology paradox.

## Gotchas

- **Verify a transit right-of-way's car-inaccessibility by attempting to route a car over it and confirming a hard failure**, not just by inspecting `allow`/`disallow` attributes passively.
- **Don't verify realized transit wait against `H/2`** — use the schedule-integrated expected-wait formula, which can differ substantially from the steady-state approximation over a finite demand window.
- **A single bisection over the full mode-share range can find the wrong equilibrium (or wrongly report none exists) if a supply-feedback loop creates a second, unstable root** — scan, classify every sign change, and bisect only within the stable root's bracket.
- **Naive MSA-style day-to-day adjustment is not a reliable primary solver for a supply-feedback equilibrium** — it can overshoot a narrow basin of attraction and converge to the wrong fixed point; use it only as a secondary robustness check.
- **An equilibrium found via a correct solver should still be perturbation-tested** — it can be stable from one side and unstable from the other (a one-sided/narrow basin), which a zero-gap check alone won't reveal.
- **Route-file elements out of departure-time order are silently dropped by SUMO** ("Route file should be sorted by departure time, ignoring '...'") with no error that stands out — interleave and sort all vehicle/person departures into one properly-ordered stream before feeding a combined multimodal demand file to `sumo`.
- **Car cost must include `departDelay`, not just in-network `duration`** — at a congested equilibrium, insertion/queueing delay outside the network can be the majority of a car traveller's real cost, and omitting it can hide most of the congestion effect a paradox depends on.

## Related

- `simulate-multimodal-transit` — the underlying transit-line/busStop/schedule and intermodal-routing mechanics this skill builds on, extended here from a fixed-frequency assumption to a ridership-responsive one.
- `model-vclass-lane-permissions` — the lane-restriction technique for building the car-inaccessible transit right-of-way.
- `equilibrate-departure-time-choice-in-bottleneck-model` — the sibling equilibrium-dimension skill (departure time instead of mode) that first found a naive adjustment dynamic can fail to converge for a forward/supply-feedback equilibrium; this skill's second-unstable-equilibrium and narrow-basin findings are a related, milder instance of the same general phenomenon.
- `compute-dynamic-user-equilibrium` — the general outer-iteration-loop and explicit-convergence-gap discipline this skill's mode-split solver follows.
- `construct-and-verify-braess-paradox` — the sibling route-choice paradox; together with this skill and the Vickrey departure-time skill, completes the classical trio of traveller-choice-dimension equilibria in this memory.
- `model-capacity-constrained-transit-passenger-loading` — this skill's scenario builder sets `personCapacity="4000"` deliberately, so transit supply is purely a *frequency* question and no rider is ever refused. That is the right simplification for isolating the ridership→headway feedback, but it means the Mohring effect here operates without the counter-pressure a full vehicle applies. Use that skill if capacity should bind; note its finding that a binding capacity truncates the dwell feedback loop, which is a second supply-side feedback this model does not represent.
- [[downs-thomson-paradox-and-mode-choice-equilibrium]] — the verified paradox confirmation, the demand-threshold regime, and the second-equilibrium/narrow-basin findings.
- [[transit-capacity-passenger-loading-and-pass-up-dynamics]] — what happens once `personCapacity` binds.
