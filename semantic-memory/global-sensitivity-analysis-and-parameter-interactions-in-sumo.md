---
summary: A global sensitivity analysis of 13 SUMO parameters spanning 6 subsystems (car-following, lane-changing, junction/driver behavior, fleet composition, demand, signal timing) on a 3-intersection arterial found signal-timing and demand-scale factors dominate Morris elementary-effects rankings over car-following/lane-changing parameters in both an undersaturated and oversaturated regime, with regime-to-regime ranking agreement varying by metric (Spearman rho roughly 0.65-0.95, weakest on queue length); a genuine Sobol-computed second-order interaction between driver imperfection (sigma) and signal cycle length was found and confirmed on independent fresh seeds, something a one-factor-at-a-time sweep would structurally miss; and a critical gotcha was caught mid-study — sweeping car-following tau below the simulation step length silently produces teleport-resolved collisions that contaminate an entire screening design with no warning.
keywords:
  - global-sensitivity-analysis
  - morris-screening
  - sobol-indices
  - elementary-effects
  - parameter-interaction
  - factor-screening
  - noise-floor
created: 2026-08-06T08:00:00
last_updated: 2026-08-06T08:00:00
sources:
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/tau_step_collision_probe.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/noise_floor.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/morris.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/morris_tables.md]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/screening_analysis.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/recommendations.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/sobol_under.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/sobol_over.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/interaction_demo_under.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/e2_queue_attribute_trap.json]]"
  - "[[episodic-memory/2026-08-06_08-00-00/outputs/tables/budget.json]]"
related_pages:
  - "[[car-following-parameter-calibration-and-identifiability]]"
  - "[[lane-change-model-calibration-and-identifiability-at-a-diverge]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
related_skills:
  - screen-and-decompose-sumo-parameter-sensitivity
  - calibrate-car-following-parameters-against-field-targets
  - calibrate-lane-changing-parameters-at-a-freeway-diverge
  - quantify-sumo-run-to-run-variability
related_skills_for_graph_view:
  - "[[screen-and-decompose-sumo-parameter-sensitivity]]"
  - "[[calibrate-car-following-parameters-against-field-targets]]"
  - "[[calibrate-lane-changing-parameters-at-a-freeway-diverge]]"
  - "[[quantify-sumo-run-to-run-variability]]"
---

# Global Sensitivity Analysis and Parameter Interactions in SUMO

Every prior calibration skill in this memory picks which SUMO parameters
to tune by convention, using one-factor-at-a-time or Morris screening
scoped to a single subsystem (car-following, or separately
lane-changing). This page treats "which parameters matter" as a formal,
cross-subsystem question — Morris elementary-effects screening across 13
factors spanning 6 SUMO subsystems, gated against a measured noise floor,
followed by a genuine Sobol/variance-based analysis (previously only an
unimplemented keyword in this memory) — on a 3-intersection signalized
arterial under undersaturated and oversaturated demand.

## The critical gotcha: `tau` below step length silently contaminates a design

A first screening pass swept car-following `tau` down to 0.7 s at the
default 1.0 s simulation step length. Every design point where `tau`
fell below the step length was contaminated by genuine Krauss collisions,
silently resolved via SUMO's default teleport-on-collision behavior
(thousands of collisions in some individual runs). Verified from both
directions: sweeping `tau` at fixed step length took the collision count
from thousands to exactly zero at `tau = 1.0`; sweeping step length at
fixed `tau = 0.70` did the same in reverse. The contaminated design was
archived (not deleted) and the entire screen re-run clean. **Any factor
range letting `tau` fall below `--step-length` must raise the lower
bound or reduce the step length to match — check collision counts
explicitly near this boundary, since nothing else signals the failure.**

## Establish a formal noise floor before screening

Running the unperturbed baseline with 24 seeds per demand regime gave
each MOE a genuine mean and standard deviation, converted into an
elementary-effect noise floor that every factor's mu\* must clear by 2×
to be called statistically detectable. Not every MOE survives this
check: teleport count showed zero seed-to-seed variance at baseline in
the undersaturated regime — a degenerate metric correctly excluded from
screening rather than forced through the same gate.

## Signal timing and demand dominate over car-following/lane-changing parameters

Across all 13 factors, the top-ranked by Morris mu\* on mean time loss
per km were **signal timing and demand scale**, not car-following or
lane-changing parameters, in both demand regimes — cycle length and
cross-street green fraction ranked highest in the undersaturated regime;
cycle length, driver-imperfection `sigma`, and demand scale dominated in
the oversaturated regime. A junction time-gap parameter
(`jmTimegapMinor`) is statistically detectable above the noise floor on
one primary-MOE cell (undersaturated time loss per km, mu\*/noise ≈ 2.9)
but its practical leverage there is under 1% of the metric's range —
small enough to still recommend fixing it at default, not because its
effect is indistinguishable from noise but because a real, detectable
effect can be too small to be worth calibrating. **Report both a
significance gate and a leverage threshold — a factor can clear one and
fail the other.**

## Sensitivity rankings genuinely change with demand regime — but the reordering is metric-specific

Comparing Morris rankings between the two regimes (Spearman correlation
per MOE): agreement ranged from moderate to strong (roughly 0.65 to
0.95), strongest on network-wide throughput, weakest on queue-length
metrics — top-4-factor overlap between regimes was only 2 of 4 for both
mean and maximum queue length. Fleet composition (heavy-vehicle share)
entered the oversaturated regime's top-4 for CO2 emissions specifically
— not for either queue metric — so "heavy-vehicle share matters more
under congestion" needs to specify which output it matters *for*, not
treated as a blanket regime effect.

## Screening stability under a halved trajectory budget

Comparing the full 10-trajectory Morris screen against a nested
5-trajectory subsample: rank correlations ranged from strong to very
strong (roughly 0.75 to 0.99) and top-4 factor overlap ranged 2 to 4 of
4 depending on the metric — supporting a smaller trajectory count for a
first-pass screen in a similar setting, while showing the check should
be run per application rather than assumed.

## A genuine cross-subsystem interaction, confirmed on independent seeds

A real Sobol/Saltelli variance-based follow-up on the top screened
factors — the genuinely new contribution here — found a statistically
significant second-order interaction between **driver imperfection
(`sigma`) and signal cycle length** in the undersaturated regime, with a
confidence interval excluding zero simultaneously for throughput, time
loss per km, and mean queue length. This is a genuine cross-subsystem
interaction: a car-following parameter's effect depends on the
signal-timing setting it's evaluated under. Confirmed independently with
a replicated-factorial ANOVA and — critically — **re-confirmed on a
fresh batch of seeds never used in the original factorial**, where the
residual between the observed combined effect and an additive
one-factor-at-a-time prediction was large and highly significant. An OAT
sweep around a single baseline point would have missed this interaction
by construction, since it never jointly varies the two factors.

## Sobol implementation gotcha: standardize the response first

An initial variance-based computation on the raw-scale MOE produced a
nonsensical first-order index (a confidence interval extending outside
the valid [0, 1] range) — a numerical conditioning failure. Standardizing
the response before computing indices (matching standard Sobol-library
convention) fixed this to a well-behaved, properly-bounded estimate — an
affine-invariant re-scaling that doesn't change what's being measured.
Always check a computed first-order Sobol index actually falls in [0, 1]
before trusting it.

## A separate detector gotcha found along the way

An E2 detector's `jamLengthInMetersSum` output is a step-time integral,
not a length — it scaled roughly 5× simply from changing the detector's
aggregation period from 60 to 300 seconds at identical traffic
conditions. `meanMaxJamLengthInMeters` is genuinely aggregation-period-
invariant and is the correct choice for a true queue-length metric.

## Study scale, honestly accounted

The final valid pipeline totaled roughly 4,300 SUMO runs across the
noise-floor baseline, Morris screening, factorial/ANOVA cross-check,
Sobol/Saltelli analysis, and independent-seed interaction confirmation.
Two real methodological bugs were caught and fixed mid-study — the
tau/step-length collision contamination above and the Sobol
standardization issue — and a third Morris pass was separately aborted
partway through by a distinct infeasible-parameter-combination failure.
Together these discarded passes added a comparable amount of further
simulation work to the valid pipeline itself. Total measured wall-clock
time across the whole study session, including all debugging, was
roughly 170 minutes on 10 parallel workers — **this figure covers the
entire session including the discarded/buggy passes, not the valid
pipeline in isolation**; state this distinction explicitly whenever
reporting a global-sensitivity-analysis study's total cost.

## Gotchas

- Raise the lower bound on car-following `tau` to at least the
  simulation step length before sweeping it — check collision counts
  explicitly near this boundary.
- Report a formally-measured noise floor and gate every factor's effect
  against it; exclude any MOE with zero baseline seed variance.
- Report both statistical detectability and practical leverage
  separately — a factor can clear one threshold and fail the other.
- Run a trajectory-count convergence check per application; agreement
  varies meaningfully across output metrics even within one study.
- Standardize the response before computing Sobol indices; an
  out-of-[0,1] first-order index signals a conditioning failure.
- State clearly whether a reported study wall-clock figure covers only
  the final valid pipeline or the whole debugging session.

See `screen-and-decompose-sumo-parameter-sensitivity` for the full
noise-floor/Morris/Sobol workflow, and
`calibrate-car-following-parameters-against-field-targets` for the
Morris trajectory sampler this page's screening reuses directly.
