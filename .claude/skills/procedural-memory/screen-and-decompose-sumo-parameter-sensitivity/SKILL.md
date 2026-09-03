---
name: screen-and-decompose-sumo-parameter-sensitivity
description: Use this skill when the user wants to know which SUMO input parameters actually matter — a formal global sensitivity analysis (Morris elementary-effects screening plus a genuine Sobol/variance-based follow-up), rather than a one-factor-at-a-time sweep, to decide what's worth calibrating versus fixing at defaults. Covers reusing this project's existing Morris trajectory sampler across a factor set spanning multiple SUMO subsystems (car-following, lane-changing, junction/driver behavior, fleet composition, demand, signal timing), gating factor significance against a formally-measured stochastic noise floor, computing real first-order and second-order Sobol indices to detect parameter interactions an OAT sweep would miss, and comparing rankings between an undersaturated and an oversaturated demand regime. Also documents a critical, easy-to-hit gotcha — sweeping car-following tau below the simulation step length silently produces collisions resolved by teleport, contaminating an entire screening design — and a Sobol numerical-conditioning trap. Trigger on mentions of global sensitivity analysis, Morris screening, Sobol indices, elementary effects, parameter screening, or "which SUMO parameters matter."
---

# Screen and Decompose SUMO Parameter Sensitivity

**Sweeping car-following `tau` below the simulation step length silently
produces genuine collisions resolved by teleport, and can contaminate an
entire sensitivity design without any error or warning.** Verified on a
3-intersection signalized arterial, 13 factors spanning 6 SUMO subsystems,
two demand regimes, ~4300 valid SUMO runs (plus ~2960 further runs across
three separate discarded/buggy passes, an honest cost of two real
methodological bugs caught mid-study).

## The critical gotcha: `tau` below step length contaminates a design silently

A first screening pass swept car-following `tau` down to 0.7 s at the
default 1.0 s simulation step length. **100% of the design points where
`tau` fell below the step length were contaminated by genuine Krauss
collisions**, silently resolved via SUMO's default teleport-on-collision
behavior (thousands of collisions in some individual runs). Verified from
both directions: sweeping `tau` at a fixed step length (0.70 s → 1.00 s)
took the collision count from thousands to exactly zero; independently,
sweeping the step length at a fixed `tau = 0.70` s did the same in
reverse. **Any factor range that lets `tau` fall below `--step-length`
must either raise the lower `tau` bound to at least the step length, or
reduce the step length to match — check collision counts explicitly for
every design point near this boundary, since nothing else signals the
failure.** The contaminated design was discarded (archived, not deleted)
and the entire screen re-run clean.

## Establish the noise floor before screening anything

Run the unperturbed baseline with a genuinely large seed count (24 in
this study) per demand regime and record each MOE's mean and standard
deviation. This is the formal statistical yardstick every factor effect
gets compared against — an elementary-effect noise floor of
`sqrt(2) · (seed_sd / mean) / sqrt(n_seed) / Δ` (where Δ is the Morris
step size), with a factor's mu\* required to exceed **2×** that floor to
be called statistically detectable. Not every MOE is usable this way:
one guard metric (teleport count) had **zero seed-to-seed standard
deviation at baseline** in the undersaturated regime — a degenerate MOE
with no defined noise floor, correctly excluded from screening rather
than forced through the gate.

## Reuse the project's existing Morris sampler — don't reimplement it

This project already has a verified Morris elementary-effects trajectory
sampler, built for car-following-parameter calibration and already reused
once for lane-changing-parameter calibration. **Import and call it
directly** (retargeting only its factor count and RNG) rather than
writing a new one — Morris trajectory generation is well-established,
mechanical code with no scenario-specific content, and reimplementing it
adds risk without adding value.

## Screening across subsystems reveals a strict ranking, and one clean negative result

Across 13 factors spanning car-following, lane-changing, junction/driver
behavior, fleet composition, demand, and — genuinely new relative to any
prior calibration work in this project — **signal-timing parameters**
(cycle length, cross-street green fraction): the top-ranked factors by
mu\* on mean time loss per km were **signal timing and demand scale**,
not car-following or lane-changing parameters, in both demand regimes
(cycle length and cross-street green fraction ranked 1st–2nd in the
undersaturated regime; cycle length, driver-imperfection `sigma`, and
demand scale dominated in the oversaturated regime). **`jmTimegapMinor`
(a junction time-gap parameter) is statistically detectable above the
noise floor on one primary-MOE cell (undersaturated regime, time loss per
km, mu\*/noise ≈ 2.9) but its practical leverage there is under 1% of the
metric's range — small enough that it is still recommended for fixing at
its default value, not because its effect is indistinguishable from
noise, but because a real, detectable effect can still be too small to be
worth the cost of calibrating.** Don't conflate "statistically
detectable" with "practically worth calibrating" — report both a
significance gate and a leverage/effect-size threshold, and expect
factors that pass one but not the other.

## Sensitivity rankings genuinely change with demand regime — but the reordering is metric-specific, not universal

Comparing Morris rankings between the undersaturated and oversaturated
regimes (Spearman rank correlation of each factor's mu\* ranking, one
correlation per MOE): agreement ranged from moderate to strong across
different MOEs (roughly 0.65 to 0.95), with the strongest agreement on
network-wide throughput and the weakest on queue-length metrics —
**top-4-factor overlap between regimes was only 2 of 4 for both mean and
maximum queue length**, meaning the specific parameters worth calibrating
for a queue-focused study genuinely differ between demand levels tested.
Fleet composition (heavy-vehicle share) entered the oversaturated
regime's top-4 ranking for CO2 emissions specifically — **not** for
either queue metric — so a claim like "heavy-vehicle share becomes more
important under congestion" needs to specify which output metric it's
important *for*; it is not a blanket regime effect across every MOE.

## Screening is reasonably stable to halving the trajectory count, but check per application

Comparing the full screen (10 Morris trajectories) against a nested
5-trajectory subsample: rank correlations ranged from strong to very
strong (roughly 0.75 to 0.99 across MOE/regime combinations) and the
top-4 factor set overlapped 2 to 4 of 4 factors depending on the cell.
This supports using a smaller trajectory count for a first-pass screen
in a similar setting, but the variation across MOEs means this
convergence check should be run per-application rather than assumed.

## A genuine cross-subsystem interaction, confirmed on entirely independent seeds

Following up the top screened factors with a real Sobol/Saltelli
variance-based analysis (the genuinely new contribution here — a prior
calibration skill only used the term "Sobol" as an unimplemented keyword)
found a statistically significant second-order interaction between
**driver imperfection (`sigma`) and signal cycle length**, in the
undersaturated regime, across multiple MOEs simultaneously (throughput,
time loss per km, and mean queue length all showed a confidence interval
excluding zero for this specific pairwise index). **This is a genuine
cross-subsystem interaction — a car-following parameter's effect depends
on the signal-timing setting it's evaluated under, not just an additive
combination of each factor's own marginal effect.** Confirmed with an
independent replicated-factorial ANOVA and, critically, **re-confirmed on
a fresh batch of seeds never used in the original factorial** — the
residual between the observed combined effect and the effect an
additive, one-factor-at-a-time model would have predicted was large and
highly significant. **An OAT sweep around a single baseline point would
have missed this by construction**, since it never jointly varies the
two interacting factors.

## Sobol implementation gotcha: standardize the response before computing indices

An initial variance-based computation on the raw-scale MOE produced a
nonsensical first-order index (a confidence interval extending outside
the valid `[0, 1]` range a proper first-order Sobol index must occupy) —
a numerical conditioning failure, not a real result. Standardizing the
response (matching the convention standard Sobol-analysis libraries use
internally) before computing indices fixed this to a well-behaved,
properly-bounded estimate. **This is an affine-invariant re-scaling that
doesn't change what's being measured — always check that a computed
first-order Sobol index actually falls in `[0, 1]` before trusting it,
and standardize the response if it doesn't.**

## A separate detector gotcha found along the way

An E2 (lane-area) detector's `jamLengthInMetersSum` output attribute is a
**step-time integral**, not a length — it scaled by roughly 5× simply
from changing the detector's aggregation period from 60 to 300 seconds
at identical traffic conditions. `meanMaxJamLengthInMeters` (a
similarly-named attribute) is genuinely aggregation-period-invariant and
is the correct choice for a true queue-length metric. Confirm which of
two similarly-named E2 attributes you actually want before using either
as an MOE.

## Gotchas

- Raise the lower bound on car-following `tau` to at least the
  simulation step length (or reduce the step length to match) before
  sweeping it in any sensitivity design — check collision counts
  explicitly near this boundary.
- Report a formally-measured noise floor and gate every factor's effect
  against it; exclude any MOE with zero baseline seed variance rather
  than forcing it through the same gate.
- Report both statistical detectability (above the noise floor) and
  practical leverage (effect size relative to the metric's range) — a
  factor can clear one threshold and fail the other.
- A convergence check (e.g. halving the trajectory count) should be run
  per application; agreement varies meaningfully across different output
  metrics even within the same study.
- Standardize the response before computing Sobol indices; a first-order
  index outside `[0, 1]` signals a conditioning failure, not a real
  result.
- Total study wall-clock time, if measured from a project's full log
  timeline, will include time spent on any discarded/buggy passes along
  the way — state clearly whether a reported run-time figure covers only
  the final valid pipeline or the whole debugging session.

See `calibrate-car-following-parameters-against-field-targets` for the
Morris trajectory sampler this skill reuses directly, and
`calibrate-lane-changing-parameters-at-a-freeway-diverge` for the prior
precedent of reusing that same sampler across a different parameter set.
