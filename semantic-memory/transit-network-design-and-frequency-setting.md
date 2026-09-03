---
summary: The Transit Network Design and Frequency Setting Problem solved on a congested 6x6 SUMO grid at equal bus-hours — the classical square-root rule beat a 125-evaluation simulation-in-the-loop optimizer out-of-sample (635.39 vs 655.79 pax-h), transit line-frequency projects are strongly SUPER-additive (interaction up to 77% of the sum of singles, opposite in sign to the road NDP), the structure crossover is a feasibility boundary rather than a preference reversal, and completed-only versus censored-inclusive accounting reverses which service plan wins.
keywords:
  - transit-network-design
  - frequency-setting
  - service-plan
  - bus-hour-budget
  - square-root-rule
  - trunk-and-feeder
  - ridership-vs-coverage
  - mohring-effect
created: 2026-09-01T10:21:28
last_updated: 2026-09-01T10:21:28
sources:
  - "[[episodic-memory/2026-09-01_10-21-28/summary.md]]"
related_pages:
  - "[[intermodal-transfer-and-person-stage-semantics-in-sumo]]"
  - "[[public-transport-and-intermodal-routing]]"
  - "[[discrete-network-design-and-project-interaction]]"
  - "[[simulation-based-optimization-under-noise-and-seed-overfitting]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[downs-thomson-paradox-and-mode-choice-equilibrium]]"
  - "[[accessibility-measurement-and-transport-equity]]"
  - "[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]"
related_skills:
  - design-transit-service-plan-under-a-bus-hour-budget
  - solve-budget-constrained-network-design-problem
  - optimize-under-simulation-noise-with-a-fixed-budget
  - evaluate-multimodal-accessibility-and-equity
  - demonstrate-and-control-bus-bunching
related_skills_for_graph_view:
  - "[[design-transit-service-plan-under-a-bus-hour-budget]]"
  - "[[solve-budget-constrained-network-design-problem]]"
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[evaluate-multimodal-accessibility-and-equity]]"
  - "[[demonstrate-and-control-bus-bunching]]"
---

# Transit Network Design and Frequency Setting

The supply-design half of transit planning: *which routes should exist, and how
should a fixed pot of bus-hours be split among them?* Every operations-side
question — bunching, priority, capacity, stop design — takes the answer to this
as an input. The results below come from a 6x6 grid (4.0 km across, sidewalks and
crossings, 9 zones with a CBD and four low-density corners, 974 transit-market
persons against 10,827 car trips producing a mean 39% timeLoss), 469 SUMO runs,
with every claim tested against a measured noise floor. Method in
`design-transit-service-plan-under-a-bus-hour-budget`.

## Budget in buses, not headways — and expect the fleet formula to under-count

Allocating an integer bus count `N_l` per line and *deriving* headway
`h_l = C_l / N_l` from the measured round-trip cycle keeps the budget constraint
linear and exactly satisfiable. Allocating headways instead forces a rounding
step that breaks the equal-budget control.

`N_l = ceil(C_l / h_l)` is the textbook fleet formula and it **systematically
under-counts**. Audited against distinct buses concurrently in service at a
nominal 24 bus-hours: realised **25.33 / 24.83 / 24.83** for coverage /
trunk-and-feeder / frequent-grid — a **+3.5 to +5.6% over-run**. The formula is
built on the *mean* cycle while the distribution's upper tail puts an extra bus
on the road (trunk line: mean 1182.4 s, p90 1387.7 s, max 1471.2 s). A
p90-sized layover narrows it without closing it. What makes an equal-budget
comparison still fair is that the over-run is *comparable across structures* —
verify that rather than assuming it.

Measuring `C_l` at all requires escaping the binding-timetable trap in
[[intermodal-transfer-and-person-stage-semantics-in-sumo]]: a generous `until=`
makes buses schedule-adherent and erases congestion from the cycle entirely.

## The winner depends on the accounting convention, not just the metric

Three structures at exactly 24 bus-hours, 6 CRN seeds, generalized time weighting
walk/wait/transfer at 2.0x, in-vehicle at 1.0x, plus a 300 s transfer penalty:

| plan | GC total (pax-h) | riders | walk-only | incomplete | xfers/rider |
|---|---|---|---|---|---|
| frequent grid | **596.29** | 909.7 | 45.8 | 18.5 | 0.538 |
| coverage | 608.83 | **948.5** | 18.0 | 7.5 | 0.717 |
| trunk-and-feeder | 636.80 | 918.7 | 35.0 | 20.3 | 0.808 |

On completed-only generalized time the frequent grid wins by 12.54 pax-h against
a resolvable difference of 11.24 — real, but barely. On **censored-inclusive**
generalized time (still-travelling passengers charged their realised stages) the
ordering **flips**: coverage 619.48 vs frequent grid 624.18, t = -1.19, below the
floor. The frequent grid strands 18.5 travellers per run against coverage's 7.5,
so it looks good partly by dropping the people it fails. Coverage wins ridership
outright.

**A service plan that abandons part of the study area will flatter itself under
completed-only accounting.** Always report both.

Mechanism, from the stage decomposition (mean s per rider):

| plan | access+egress | initial wait | in-vehicle | transfer wait |
|---|---|---|---|---|
| coverage | **361.3** | 213.9 | 441.6 | 167.4 |
| trunk-and-feeder | 474.3 | 169.9 | 432.7 | 134.6 |
| frequent grid | 554.5 | **143.7** | **375.6** | **78.2** |

The frequent grid buys wait and in-vehicle time with a 193 s longer access walk.
Trunk-and-feeder loses on both counts — it inherits coverage's long access *and*
the highest transfer rate without buying enough trunk frequency to pay for them,
and it was **last at every transfer penalty tested including zero**. Do not
assume trunk-and-feeder wins at high density; on the density axis the winner
moved from frequent-grid at 0.5x to **coverage** at 1.0x and 2.0x, opposite to
the textbook expectation that density favours concentration.

## The structure crossover is a feasibility boundary

There is no transfer-penalty value at which trunk-and-feeder overtakes direct
service. The clean crossover is on the **budget axis**, and it is driven by
policy headway bounds rather than by preference:

| budget | winner | why |
|---|---|---|
| 12 bus-h | frequent grid | **coverage is infeasible** — 8 routes need 13 buses to meet the headway cap |
| 16-24 bus-h | frequent grid on GC, coverage on ridership | |
| 40 bus-h | coverage | **frequent grid is infeasible** — 4 routes cannot absorb 40 buses above the headway floor |

A coverage network cannot be operated *at all* below the budget at which every
route still meets its policy headway cap; a concentrated network runs out of
places to put buses above a certain budget. Report an infeasible budget as a
finding rather than repairing it.

## The square-root rule is hard to beat, and search can actively lose

Minimising `sum(Q_l / (2 f_l))` subject to `sum(f_l C_l) = B` gives
`f_l ∝ sqrt(Q_l / C_l)`, i.e. fleet share `N_l ∝ sqrt(Q_l * C_l)`.

Measured against a simulation-in-the-loop optimizer on a structure with a 10:1
line-demand range (noise floor: pooled sigma **9.93 pax-h / 1.55%**, minimum
resolvable difference **27.52 pax-h at n=1**):

| arm | in-sample | held-out (12 seeds) | seed-overfitting gap |
|---|---|---|---|
| **square-root rule** (0 evals) | 641.63 | **635.39** | +0.98% |
| proportional (0 evals) | 644.34 | 644.35 | -0.00% |
| greedy (75 evals) | 650.00 | 651.89 | -0.29% |
| equal (0 evals) | 655.49 | 654.96 | +0.08% |
| **optimizer (125 evals)** | **638.33** | **655.79** | **-2.66%** |

**125 evaluations of search produced the best in-sample plan and the worst
held-out plan.** Only the searchers have negative gaps, so this is selection
bias rather than an easy/hard-seed artifact — an independent replication of
[[simulation-based-optimization-under-noise-and-seed-overfitting]] in a new
domain. The cause is visible in the trace: **3 of 15 greedy "improvement" steps
worsened the objective** (+2.19, +11.57, +7.35 pax-h), because candidate designs
were separated by ~5-15 pax-h while the n=1 resolvable difference was 27.52. A
search whose step size sits below the noise floor is a random walk with extra
steps.

Decomposing the rule-versus-optimum gap (-16.411 pax-h, -2.51%, resolvable at
n=12): **congestion-dependent cycle time contributed exactly 0.000** — feeding
the rule free-flow instead of measured congested cycles returned the *identical
integer allocation*, because congestion inflates every line by a similar factor
(12.1-21.2%) and the rule sees only ratios. Transfer structure contributed
+0.936 ± 2.772, below the floor. Essentially **100% of the gap is search noise**,
so the rule's famous blindness to congestion cost nothing here.

### CRN's benefit is contingent on the vehicle set staying fixed

Changing a bus allocation changes the number and identity of bus vehicles, so
SUMO consumes its seed stream in a different order and the random numbers are not
actually *common*. Measured rho across six design pairs: **+0.138, -0.028,
-0.078, -0.271, -0.299, -0.450 — four of six negative.** This is the opposite of
the +0.279 / 1.38x reduction measured for signal plans, where every design shares
an identical vehicle population. Measure rho; never assume CRN helps.

## Economies of scale hold cleanly, unlike the road case

Per-passenger generalized cost is **convex** in budget (all second differences
positive) and the budget-benefit frontier is **concave** (all negative), with
marginal benefit falling monotonically from **15.225 to 1.932 pax-h per
bus-hour** over B = 11 to 42. This is the Mohring effect, and **unlike
[[discrete-network-design-and-project-interaction]]'s road NDP there is no
non-concave first increment.** Mechanism: mean wait collapses 293.0 -> 109.2 s
while in-vehicle time *rises* 353.8 -> 472.8 s, as travellers who were walking
start riding.

## Line-frequency projects are SUPER-additive — the opposite sign to road projects

Treating "+1 bus-hour on line l" as a project and measuring pairwise
interactions on the three trunks:

| pair | pair benefit | sum of singles | interaction |
|---|---|---|---|
| tk1 + tk3 | 25.854 | 14.583 | **+11.271 (+77.3%)** |
| tk1 + tk2 | 21.398 | 15.797 | +5.601 (+35.5%) |
| tk2 + tk3 | 17.160 | 12.007 | +5.154 (+42.9%) |

Median |interaction| 5.601 against median |single| 6.610 — the interaction is
**85% as large as the main effect**. The mechanism is structural: connected
trunks share transfers, so raising two together shortens the *transfer* wait
between them as well as each line's own initial wait, a benefit neither project
delivers alone.

Road projects in [[discrete-network-design-and-project-interaction]] were
strongly **sub**-additive (adding capacity in two places partly relieves the same
congestion twice). Transit frequency projects are the mirror image. The shared
practical conclusion survives the sign flip: **an isolated per-line benefit-cost
ranking picks the wrong portfolio** — there it over-invested, here it will
systematically *under*-invest in trunk pairs.

## A bus lane did not pay for itself against frequency

Priced honestly at 4 of 24 bus-hours, a trunk bus lane moved passenger
generalized time the *wrong* way (647.17 -> 652.51 pax-h, +5.34 against an n=3
resolvable difference of 15.89, so indistinguishable from zero) while costing car
users **+46% timeLoss, 230 -> 337 s**. The lane worked on its own terms —
in-vehicle time fell 412.2 -> 392.1 s at the same fleet, ridership rose slightly —
but halving the trunk's car capacity to gain ~20 s of bus running time is a bad
trade at this budget.

Related: mixed traffic inflates the fleet needed to hold a given headway by
**2 buses out of 24 (~8%)**, a real operating cost, yet it does **not** change
the optimal allocation. The transit-priority alternative (TSP, see
[[transit-signal-priority]] and
[[bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction]]) was not
tested against frequency and remains open.

## Ridership versus coverage: a shallow frontier over a sharp distributional cost

Coverage = share of population within 400 m of a stop served at >= 4 buses/h.
Exchange rate **+1.3 to +1.7 riders per point of coverage** — the last 24 points
bought only 39 riders, so the aggregate frontier is real but shallow.

The distributional picture is not shallow at all. The frequent grid, best on the
aggregate, is **worst for every peripheral zone**: its coverage in the four
low-density corners is 0.000 / 0.000 / 0.020 / 0.000, it gives central zones the
cheapest trips in the study (1894-2032 s) and charges the worst-off corner
**3352 s, +40% versus the coverage plan's 2395 s**. Peripheral-versus-central
spread widens from 612 s under coverage to **1458 s** under the frequent grid.

By car-availability the frequent grid splits 2139 s (carless) vs 2499 s (car
owner riding transit) — but since car ownership is assigned as a *zone*
attribute, that split is an ecological estimator and therefore a **lower bound**
on the true disparity, per [[accessibility-measurement-and-transport-equity]].

**An aggregate generalized-time optimum will concentrate service and strand the
periphery.** Coverage-versus-ridership is a distributional choice that the
objective function makes silently unless incidence is reported alongside it.

## What this study did not settle

Car-versus-transit mode choice was exogenous (only walk-versus-ride was
endogenous), so ridership responds to service quality on one margin only —
making it endogenous per
[[downs-thomson-paradox-and-mode-choice-equilibrium]] would likely strengthen the
Mohring result. The optimizer ran on one route structure. Replication counts
(20 for the noise floor, 12 held-out, 3 for the hypothesis arms) sit below the
>= 30 recommended for this kind of comparison, though every claim was tested
against the explicit resolvable-difference table and the ones that fail are
labelled. Headway CV was compared at line-level means over 19 lines, not
per-passenger.
