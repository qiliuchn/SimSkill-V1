---
name: design-transit-service-plan-under-a-bus-hour-budget
description: Use this skill when the SERVICE PLAN itself is the decision - which bus routes exist, what structure they form, and how a fixed pot of bus-hours is split among them - rather than the input. This is the Transit Network Design and Frequency Setting Problem, and it is categorically different from every other transit skill in memory, all of which take routes and headways as given. Covers a reusable ServicePlan object compiled to a runnable SUMO scenario, bus-hour budget accounting from MEASURED round-trip cycle times (with a layover rule and the verified finding that ceil(C/h) under-counts the real fleet), equal-bus-hour comparison of coverage vs trunk-and-feeder vs frequent-grid structures, frequency allocation by the classical square-root rule against a simulation-in-the-loop optimizer, and the coverage/ridership/distributional-incidence post-processing. Trigger on mentions of transit network design, TNDFSP, frequency setting, service plan, route structure, trunk-and-feeder vs coverage, span-and-frequency tradeoff, bus-hours or operating budget, square-root rule, service allocation across lines, ridership vs coverage, or "what service should the agency buy."
---

# Design a Transit Service Plan Under a Bus-Hour Budget

Chooses the *route structure* and the *frequency allocation* of a bus network so
that total passenger generalized time is minimised subject to a fixed operating
budget. Every other transit skill in memory — `simulate-multimodal-transit`,
`build-gtfs-transit-scenario`, `design-bus-stop-placement-type-and-spacing`,
`implement-transit-signal-priority`, `demonstrate-and-control-bus-bunching` —
takes the service plan as an *input* and asks how it performs. Here it is the
output.

This is the transit counterpart of
`solve-budget-constrained-network-design-problem`, and the comparison is
instructive rather than decorative: road projects there were **sub-additive**,
transit line-frequency projects here are strongly **super-additive** (see H4
below). Do not assume the road result transfers.

- **Outer loop**: search over route structures, then over integer bus
  allocations across lines subject to `sum(N_l) = B`.
- **Inner loop**: compile the plan to SUMO, route persons with `duarouter`,
  simulate, and score measured passenger generalized time from `<personinfo>`.

## Represent the plan, and derive headway rather than setting it

A `ServicePlan` is a set of `Line`s, each a node sequence over the network plus
an **integer bus allocation** `N_l`. Headway is *derived*, `h_l = C_l / N_l`,
where `C_l` is the measured round-trip cycle time. Allocating buses rather than
headways is what makes the budget constraint linear and exactly satisfiable
(`sum(N_l) = B`); allocating headways forces a rounding step that silently
breaks the equal-budget control.

`scripts/tspcore.py` holds the network build, zone/OD system, demand generation,
the `Line`/`ServicePlan` classes, stop placement, the timetable compiler, the
SUMO runner, the `<personinfo>` stage decomposition and the budget module.
`scripts/plans.py` holds three reference structures; `scripts/alloc.py` holds the
allocators.

## Calibrate the timetable from an UNCONGESTED run, or congestion vanishes

**This is the trap that will silently invalidate the entire study.** SUMO departs
a stop at `max(arrival + duration, until)`. If the published `until=` timetable
is even slightly generous, every bus becomes schedule-adherent and **traffic
delay disappears from the measured cycle time entirely**.

Verified: a timetable built from a guessed 7.2 m/s bus speed gave a measured
round-trip cycle of **1216 s with 10,827 background cars and 1216 s with none** —
bit-identical. After rebuilding the timetable from an *uncongested buses-only*
run (measured 9.1-10.1 m/s per line), the same plan gave **1010 s uncongested vs
1169 s congested, +15.7%**, and per-line inflation of 12.1-21.2%.

So: run buses alone first, measure per-line running speed, publish the timetable
from *that*, and only then load the background traffic. `scripts/s4_reference.py`
does this as a fixed point. Always assert that congested and uncongested cycle
times differ before believing any congestion result.

## Budget from measured cycle times, and expect ceil(C/h) to under-count

Measure `C_l` from simulation output (dwell + traffic delay included), add a
layover, then `N_l = ceil(C_l / h_l)` and cost in bus-hours. With a service span
of exactly one hour, 1 bus = 1 bus-hour, which keeps the arithmetic legible.

Layover rule (state it once, apply it everywhere):

```
layover_l = max(0.10 * mean_cycle, 120 s, p90_cycle - mean_cycle)
C_l       = mean_cycle + layover_l
```

Feasibility and rounding rule: `N_l >= ceil(C_l / h_max)` from the policy headway
cap, `N_l <= floor(C_l / h_min)` from the minimum-headway floor, remainder
distributed by largest remainder so `sum(N_l)` is exactly `B`. **Report an
infeasible budget, do not repair it** — the feasibility boundary is itself a
finding (see H2).

**Verify the accounting independently** by counting distinct bus vehicles
concurrently in service (`scripts/s16_budget_audit.py`), and expect a shortfall:
at a nominal 24 bus-hours the realised peak fleet measured **25.33 / 24.83 /
24.83** for coverage / trunk-and-feeder / frequent-grid, a **+3.5 to +5.6%
over-run**. The standard formula is built on the *mean* cycle while the upper
tail puts an extra bus on the road (trunk line: mean 1182.4 s, p90 1387.7 s, max
1471.2 s). A p90-sized layover narrows but does not close this. The over-run
being *comparable across plans* is what keeps an equal-budget comparison fair —
check that, and report both the nominal and realised measure.

## Verify the SUMO mechanisms before any analysis

Do not take these from documentation. See
[[intermodal-transfer-and-person-stage-semantics-in-sumo]] for the full measured
account; `scripts/s3_mechanisms.py` reproduces all four. In brief:

- **duarouter applies NO transfer penalty and NO minimum connection buffer.** A
  zero-second connection is accepted as a valid plan. Handle transfers entirely
  in post-processing with an explicit generalized-cost weight, and run a
  sensitivity over the penalty (0-1200 s).
- **Person stages are fully separable** and reconcile to `personinfo@duration`
  with 0.0 s error. `<ride depart=...>` is the *boarding* time, so
  `ride@duration` excludes wait, and `personinfo@traveltime = duration - sum(ride.waitingTime)`.
- **The router is schedule-aware and frequency changes route choice**, not just
  realised wait — but through concrete next-departure times, not an aggregate
  frequency term.
- **Incomplete travellers are reported but easily dropped.** A stranded person
  still gets a `<personinfo>` with `duration="-1"` and a leg with
  `vehicle="NULL"` but a *real* `waitingTime`.

## Score with completed-vs-censored dual accounting — it can flip the winner

Weight the stages explicitly (a defensible default: access/egress walk, wait,
transfer walk and transfer wait at 2.0x, in-vehicle at 1.0x, plus a fixed
transfer penalty of ~300 s). Then report **two** totals: completed-only, and
censored-inclusive with still-travelling passengers charged their realised stages
as a lower bound.

**This is not a formality — it reversed the headline.** At equal budget the
frequent grid beat coverage by 12.54 pax-h on completed-only (resolvable, floor
11.24), and *lost* by 4.70 pax-h on censored-inclusive (t = -1.19, below the
floor), because the frequent grid strands 18.5 travellers per run against
coverage's 7.5. A plan that abandons the periphery looks good precisely by
dropping the people it fails.

## Compare structures at equal bus-hours, not equal route-km

Build at least three structurally different plans — coverage (many direct
low-frequency routes), trunk-and-feeder (high-frequency trunk plus feeders
forcing transfers), frequent grid (few routes, high frequency) — and hold
`sum(N_l) = B` identical, in the spirit of the equal-lane-km control in
`compare-one-way-vs-two-way-street-grid-conversion`. `scripts/s5_compare.py`.

Measured at 24 bus-hours, 6 CRN seeds: frequent grid 596.29, coverage 608.83,
trunk-and-feeder 636.80 pax-h; ridership 909.7 / 948.5 / 918.7. **The winner
depends on the metric**, so report generalized time and ridership separately, and
explain the mechanism through the stage decomposition rather than the total —
here the frequent grid buys wait (143.7 s vs 213.9 s) and in-vehicle time by
paying a 554.5 s access walk, 193 s more than coverage.

**Trunk-and-feeder lost at every transfer penalty tested including zero.** Do not
assume it wins at high demand density; verify.

## Allocate frequency: the square-root rule is a strong baseline

Minimising `sum(Q_l / (2 f_l))` subject to `sum(f_l C_l) = B` gives
`f_l ∝ sqrt(Q_l / C_l)`, hence **fleet share `N_l ∝ sqrt(Q_l * C_l)`**. Apply the
policy headway cap as a lower bound on `N_l` and the minimum headway as an upper
bound. `scripts/alloc.py`.

Run the allocation study on a structure whose lines span a wide demand range
(here 10:1, trunk 704.3 vs feeder 61.7 unlinked boardings) — on a near-uniform
structure every allocator returns nearly the same answer and the comparison is
uninformative.

## Budget the search, and expect it to lose to the analytic rule

Follow `optimize-under-simulation-noise-with-a-fixed-budget` without exception:
noise floor **before** optimizing, a resolvable-difference table, a hard
evaluation counter, and held-out re-scoring on disjoint seeds.

Measured here: pooled sigma **9.93 pax-h (1.55%)**, minimum resolvable difference
**27.52 pax-h at n=1**. A 125-evaluation greedy-plus-local-search optimizer
scored **638.33 in-sample (best of all arms) and 655.79 held-out (worst of all
arms)**, while the zero-search square-root rule scored 641.63 in-sample and
**635.39 held-out**. Only the searchers had negative seed-overfitting gaps, so
this is selection bias, not an easy/hard-seed artifact. The trace shows the
cause directly: **3 of 15 greedy "improvement" steps actually worsened the
objective** (+2.19, +11.57, +7.35 pax-h), because candidates were separated by
~5-15 pax-h while the n=1 resolvable difference was 27.52.

**Do not run a search whose step size is below the noise floor.** Either raise
replications per design point until the floor drops under the candidate spacing,
or use the analytic rule and spend the compute on verification instead.

### CRN can be NEGATIVE here — check, do not assume

Changing the bus allocation changes the number and identity of bus vehicles, so
SUMO consumes its `--seed` stream in a different order and the random numbers are
not actually *common* between two designs. Measured rho across six design pairs:
**+0.138, -0.028, -0.078, -0.271, -0.299, -0.450 — four of six negative.** This
is the opposite of the +0.279 / 1.38x variance reduction that
`optimize-under-simulation-noise-with-a-fixed-budget` measured for signal plans,
where the vehicle set is identical across designs. **CRN's benefit is contingent
on the design change leaving the vehicle population untouched.** Measure rho
before claiming a variance reduction.

### Decompose the analytic-rule gap into its candidate causes

`scripts/s13_gap.py`. Measured total gap -16.411 pax-h (-2.51%, resolvable at
n=12 against a floor of 7.945), of which:

- **congestion-dependent cycle time: exactly 0.000.** Feeding the rule free-flow
  instead of measured congested cycles returned the *identical integer
  allocation*, because congestion inflates every line similarly (12.1-21.2%) and
  the rule sees only ratios. An honest null, and a useful one — it means the
  rule's blindness to congestion costs nothing here.
- **transfer structure: +0.936 ± 2.772**, below the floor.
- **remainder: essentially 100% search noise.**

## Hypotheses worth testing on a new instance

Verified results on the reference instance, all with the noise floor applied:

- **H1 Mohring / economies of scale — CONFIRMED.** Per-passenger generalized cost
  is convex in budget (all second differences positive) and the budget-benefit
  frontier concave (all negative); marginal benefit falls monotonically
  15.225 -> 1.932 pax-h per bus-hour over B = 11 -> 42. **Unlike the road NDP,
  there is no non-concave first increment.** `scripts/s8_h1_frontier.py`.
- **H2 Crossover is a FEASIBILITY boundary, not a preference reversal.** There was
  no transfer-penalty crossover at which trunk-and-feeder overtook direct
  service — it was last at every value including zero. The clean crossover is on
  the budget axis: at B=12 coverage is *infeasible* (8 routes need 13 buses to
  meet the headway cap) and the frequent grid wins; at B=40 the frequent grid is
  *infeasible* (4 routes cannot absorb 40 buses above the headway floor) and
  coverage wins. On the density axis the winner moved from frequent-grid at 0.5x
  to coverage at 1.0x and 2.0x — **opposite** to the textbook expectation that
  density favours concentration. `scripts/s14_crossover.py`.
- **H3 Congestion inflates the fleet but not the allocation.** Mixed traffic cost
  2 extra buses out of 24 (~8%) to hold the same headways, yet the square-root
  rule returned the identical vector from free-flow and congested cycles.
  Spending 4 of 24 bus-hours on a bus lane moved generalized time the *wrong* way
  (+5.34 pax-h, below the n=3 floor of 15.89) while costing car users **+46%
  timeLoss, 230 -> 337 s**. The lane worked on its own terms (in-vehicle
  412.2 -> 392.1 s at the same fleet) and still did not pay.
  `scripts/s9_h3_congestion.py`.
- **H4 Line projects are strongly SUPER-additive** — the opposite sign to
  `solve-budget-constrained-network-design-problem`'s road projects. Pairwise
  interactions **+11.271 (+77.3% of the sum of singles), +5.601, +5.154**; median
  |interaction| 5.601 against median |single| 6.610, so interaction is 85% as
  large as the main effect. Mechanism: connected trunks share transfers, so
  raising two together shortens the *transfer* wait as well as each line's
  initial wait. **An isolated per-line BCR ranking will systematically
  under-invest in trunk pairs.** `scripts/s10_h4_interaction.py`.
- **H5 `E[wait] = (h/2)(1+CV^2)` is better than `h/2` but over-corrects.** Mean
  realised headway CV 0.315, and **CV rises sharply with frequency** — the three
  highest CVs were the three shortest headways (0.723 at h=214.5 s), exactly the
  regime an optimizer pushes toward. Mean |error| 24.2 s for `h/2` vs 19.3 s
  corrected; bias +1.1 s vs -17.8 s. `h/2` is unbiased on average only because
  it under-predicts by 20-55 s at short high-CV headways and over-predicts by
  40-70 s at long ones. **Score from realised simulated waits, never from a
  headway formula**, and the bias never enters the objective.
  `scripts/s11_post.py`, CV per `demonstrate-and-control-bus-bunching`.
- **H6 The ridership-coverage frontier is real but shallow, and hides a sharp
  distributional cost.** Exchange rate +1.3 to +1.7 riders per point of coverage
  (share of population within 400 m of a stop served at >= 4 buses/h); the last
  24 points of coverage bought 39 riders. The frequent grid was best on the
  aggregate and **worst for every peripheral zone**, charging the worst-off zone
  +40% versus the coverage plan while giving central zones the cheapest trips in
  the study; peripheral-vs-central spread widened from 612 s to 1458 s. Report
  incidence by zone *and* by car-availability group per
  `evaluate-multimodal-accessibility-and-equity` — and note that zone-attribute
  car ownership makes the group split an ecological estimator, hence a **lower
  bound** on the true disparity.

## Reproduce

```bash
cd scripts
python3 s1_build.py                      # network, zones, OD, person + car demand
python3 s3_mechanisms.py                 # MANDATORY mechanism verification
BUDGET=24 python3 s4_reference.py        # calibrate timetable, measure cycle times
BUDGET=24 python3 s5_compare.py          # equal-bus-hour structure comparison
python3 s18_significance.py              # every claim against the noise floor
python3 s16_budget_audit.py              # independent fleet count
STRUCT=trunkfeeder BUDGET=24 python3 s6_noise.py   # noise floor BEFORE optimizing
./run_rest.sh                            # optimizer, H1-H4, crossover, H5/H6, plots
python3 s19_tables.py                    # deliverable CSVs
```

`SUMO_HOME` must point at `<framework>/EclipseSUMO/share/sumo` (where `data/`
lives) while binaries resolve from `<framework>/EclipseSUMO/bin`; `tspcore.py`
sets this itself. Prepare each distinct design **serially** before fanning seeds
out to a parallel pool — two workers routing into the same
`persons.routed.rou.xml` produces `Error: input ended before all started tags
were ended`.

## Related

- Knowledge: [[transit-network-design-and-frequency-setting]],
  [[intermodal-transfer-and-person-stage-semantics-in-sumo]],
  [[public-transport-and-intermodal-routing]],
  [[simulation-based-optimization-under-noise-and-seed-overfitting]],
  [[discrete-network-design-and-project-interaction]],
  [[bus-bunching-and-forward-headway-holding]]
- Skills: `simulate-multimodal-transit` (scenario spine),
  `optimize-under-simulation-noise-with-a-fixed-budget` (search discipline),
  `solve-budget-constrained-network-design-problem` (road-side analogue),
  `demonstrate-and-control-bus-bunching` (headway CV),
  `evaluate-multimodal-accessibility-and-equity` (incidence),
  `equilibrate-endogenous-mode-choice-with-transit-supply-feedback` (make mode
  choice endogenous, which this skill deliberately does not),
  `implement-transit-signal-priority` (the untested alternative to a bus lane in H3)
