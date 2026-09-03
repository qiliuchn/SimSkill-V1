---
summary: The budget-constrained discrete Network Design Problem was solved exactly on a congested 4x4 SUMO grid with 10 candidate projects — a GA validated against the enumerated global optimum recovered it at every one of 5 budget levels, while both standard practitioner heuristics failed badly (rank-by-worst-v/c funded a capacity-paradox project and produced a portfolio 107.6% short of the optimum and worse than doing nothing; rank-by-isolated-BCR fell 10.9-37.0% short), because project benefits are radically non-additive (median pairwise interaction 41.0% of the sum of individual benefits, max 411.9%, 40 of 45 pairs above 10%), the budget-benefit frontier is non-concave at its first increment, and two projects — including a deliberately-placed shortcut — raise equilibrium TSTT by 4.3% and 5.6% replicated across 10 CRN seeds.
keywords:
  - network-design-problem
  - dndp
  - project-interaction
  - capacity-paradox
  - benefit-cost-ranking
  - combinatorial-optimization
  - duaIterate-convergence
created: 2026-08-05T01:00:00
last_updated: 2026-08-07T09:15:07
sources:
  - "[[episodic-memory/2026-08-05_01-00-00/outputs/tables.md]]"
  - "[[episodic-memory/2026-08-05_01-00-00/outputs/decision_diagnostics.json]]"
  - "[[episodic-memory/2026-08-05_01-00-00/outputs/results_table.csv]]"
  - "[[episodic-memory/2026-08-05_01-00-00/outputs/paradox_replication_summary.json]]"
  - "[[episodic-memory/2026-08-05_01-00-00/outputs/warmstart_validation.csv]]"
related_pages:
  - "[[dynamic-user-equilibrium-and-wardrop]]"
  - "[[braess-paradox-in-sumo]]"
  - "[[transport-economic-appraisal-from-microsimulation]]"
  - "[[network-link-criticality-and-proxy-validation]]"
  - "[[simulation-in-the-loop-ga-signal-optimization]]"
  - "[[sumo-stochastic-variability-and-replication-design]]"
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
  - "[[marouter-macroscopic-assignment]]"
  - "[[integrated-corridor-management-factorial-interaction-findings]]"
related_skills:
  - solve-budget-constrained-network-design-problem
  - compute-dynamic-user-equilibrium
  - appraise-project-alternatives-with-benefit-cost-analysis
  - construct-and-verify-braess-paradox
  - scan-network-link-criticality-and-vulnerability
  - optimize-signal-plan-with-simulation-in-the-loop-ga
  - quantify-sumo-run-to-run-variability
  - evaluate-integrated-corridor-management-with-factorial-interaction-design
related_skills_for_graph_view:
  - "[[solve-budget-constrained-network-design-problem]]"
  - "[[compute-dynamic-user-equilibrium]]"
  - "[[appraise-project-alternatives-with-benefit-cost-analysis]]"
  - "[[construct-and-verify-braess-paradox]]"
  - "[[scan-network-link-criticality-and-vulnerability]]"
  - "[[optimize-signal-plan-with-simulation-in-the-loop-ga]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[evaluate-integrated-corridor-management-with-factorial-interaction-design]]"
---

# Discrete Network Design and Project Interaction

The **discrete Network Design Problem (DNDP)** asks which subset of candidate
road-capacity projects to build under a budget so that user-equilibrium total
system travel time is minimised. It is a **bilevel** problem — an outer
combinatorial search over 2^N project subsets, an inner user-equilibrium
evaluation per subset — and it is categorically different from the
mutually-exclusive-alternatives appraisal in
[[transport-economic-appraisal-from-microsimulation]]: there the question is
"which of these do we build", here it is "which *set*", and the set matters
because benefits do not add.

## The testbed

4x4 signalised grid, 500 m spacing, 16 `traffic_light` junctions plus 8 external
gate nodes; 64 directed edges (48 grid + 16 gate-access), 41,590.4 lane-metres,
16 `tlLogic` programs. Deliberately asymmetric base capacity: 12 of the 48 grid
directed edges are 2-lane (a row-j=2 east-west arterial and a column-i=2
north-south arterial), the remaining 36 are 1-lane. Fixed OD matrix over 48
gate-to-gate pairs, **4000 vehicles over 1800 s (8000 veh/h loading rate)**, one
demand realisation (seed 20260805) reused for every design. Ten candidate
projects: seven `numLanes+1` lane additions (3.0 MU each), two new diagonal
links (8.5 MU each) and one deliberately-placed 2-lane 70 km/h "shortcut"
diagonal (14.1 MU) as a Braess candidate.

## Verified: calibrate the effective saturation flow, don't assume it

Assuming the textbook 1900 veh/h/lane reported mean v/c of only **0.66** on the
twelve most-loaded corridors *at the demand where served flow peaked* — i.e. it
claimed the network was comfortably undersaturated exactly at its capacity knee.
Calibrating `s_hat = peak_flow / (numLanes x g/C)` with `g/C` read out of the
compiled `tlLogic` over saturated grid edges gave **1595 veh/h/lane** (p95 of 55
samples; median 1247, p90 1491). With the calibrated value the selected loading
sits at mean v/c **0.922 on the top-4 corridors** (0.885 top-6, 0.850 top-8,
max 1.025).

The knee itself was located as the peak of the served-flow-vs-demand curve:
summed peak flow over the 12 most-loaded grid edges rose to **7686 veh/h at 4000
vehicles** and then fell (7598 / 7518 / 6698 at 4500 / 5000 / 6000).

## Verified: duaIterate reaches a limit cycle, not a fixed point

A 25-iteration cold-start trace showed the relative gap falling 0.478 -> a floor
of **0.081-0.110 by iteration 12**, then oscillating inside that band for the
remaining 13 iterations without ever going lower, with mean in-network trip
duration wandering over **532.5-570.1 s** across iterations 12-24 (a 6.8% band)
and adjacent-iteration changes as large as +4.7% / -4.9%. Iteration 13 was as
converged as iteration 24.

Within a *single* do-nothing evaluation the four tail iterations scored TSTT of
2,463,583 / 2,563,939 / 2,487,411 / 2,532,851 veh-s — a **4.00% spread**, larger
than the entire measured benefit of 5 of the 10 candidate projects. Across the
229 evaluations the within-evaluation tail SD had a median of **1.42% of TSTT**.
**A single final-iteration TSTT is therefore not a usable objective on a
congested network; the objective must be a tail average and the spread must be
reported.** A 1%-relative-gap target is simply unreachable here — the criterion
has to be read off a trace.

## Verified negative result: never warm-start the equilibrium from do-nothing

Restarting `duaIterate` from the converged do-nothing route file with a short
iteration budget is the obvious way to afford a large design search. Measured on
15 designs, warm start (8 iterations) vs cold start (20 iterations):

- mean |TSTT difference| **6.06%**, worst **15.35%**;
- pairwise rank agreement only **81.9%** (Kendall tau 0.638) — the search would
  have been optimising a differently-ordered objective;
- warm relative gaps **systematically worse** (0.092-0.184 vs 0.041-0.111 cold),
  so it is not reaching the same equilibrium at all;
- **the bias is largest for exactly the projects a DNDP most needs to judge** —
  the three new-link projects came out +15.4% / +11.7% / +5.9% worse under warm
  start, against -6.3% to +6.1% for lane widenings, because a new link needs the
  most re-routing away from the do-nothing route set.

The speed-up was only **2.02x**. Cold-start every evaluation and buy
affordability by shrinking the *design set* instead.

## Verified: a lane addition in SUMO is never a pure capacity change

Diffing the compiled `net.xml` per project against do-nothing: all 10 projects
were real mechanism changes (no no-ops), adding 913.6-2582.3 lane-metres — but
**every one, including every pure lane widening, changed exactly 2 of the 16
`tlLogic` programs**, because `netconvert` regenerates the signal program at both
endpoint junctions when an approach's lane count changes. Every measured
lane-addition benefit bundles capacity with an incidental retiming.

## Verified: benefits are radically non-additive

10x10 interaction matrix `I(i,j) = B(i+j) - B(i) - B(j)` from real paired
equilibrium runs (45 extra evaluations). As a share of `|B(i)| + |B(j)|`:
**median 41.0%, p90 110.9%, max 411.9%, and 40 of 45 pairs above 10%.** Among
pairs where *both* projects were individually beneficial, **every** interaction
was positive (complementary, +1.2% to +97.4%); every substitutive cell was
created by a project that was individually harmful.

**Complementary example, and the mechanism.** The two consecutive links of one
corridor meeting at junction n11 scored **-9,934** (L1) and **+156,549** (L2)
veh-s alone but **+369,527** together — `I = +222,912`, +133.9%. Per-edge v/c
shows why: in do-nothing the binding link on that corridor is `n21_n11` at
v/c 0.889. Widening **either one alone relocates the constraint onto junction
n11's other approaches** — L1 alone drives `n10_n11` from 0.540 to 0.744 and
`n11_n12` from 0.470 to 0.750; L2 alone drives them to 0.732 and 0.642. Built
together, the whole through-corridor widens, and those approaches fall back to
0.674 and 0.629 while the network's worst link `n00_n10` drops from 0.997 to
0.781.

**Substitutive example, and the mechanism.** The shortcut NB alone creates a new
**oversaturated** link: `n10_n11` goes from v/c 0.540 to **1.092**, because the
70 km/h diagonal attracts traffic that must reach its endpoint n11 through the
column-1 south approach. Adding L2 on top widens the link that *feeds* that same
oversaturated approach, pushing it to **1.123** and its upstream feeder
`n00_n10` from 0.853 to 0.940. The pair costs 231,599 veh-s more than the sum of
its parts (-53.7%). **The binding bottleneck had moved from a link to the access
to the new link's endpoint, so extra capacity upstream discharges straight into
it.**

## Verified: the capacity paradox is real and replicates

Of the 229 designs evaluated, **55 (24.0%) were worse than doing nothing, and 53
of those 55 (96.4%) contained at least one new link**. Replicating with 10
Common-Random-Numbers paired seeds, cold-started in both arms:

| project | mean paired ΔTSTT | Δ% | p (paired t) | p (Wilcoxon) | Cohen's dz | bootstrap 95% CI | seeds Δ>0 | verdict |
|---|---|---|---|---|---|---|---|---|
| N1 (new diagonal) | +114,799 | +4.33% | 0.0108 | 0.0273 | +1.012 | [+52,253, +183,929] | 7/10 | HARMFUL |
| NB (the shortcut) | +147,746 | +5.57% | 0.00049 | 0.00195 | +1.678 | [+96,176, +199,537] | 10/10 | HARMFUL |
| L1 (lane addition) | −90,795 | −3.42% | 0.0119 | 0.0059 | −0.994 | [−149,860, −44,156] | 1/10 | BENEFICIAL |
| L2 (positive control) | −286,196 | −10.79% | 2.1e-06 | 0.00195 | −3.367 | [−339,807, −240,362] | 0/10 | BENEFICIAL |

**Both new links survive replication as genuinely harmful** — this is Braess's
paradox generalised from a hand-built topology ([[braess-paradox-in-sumo]]) to a
*capacity project on a realistic grid*, and it is the first time in this memory a
single-run "closure/addition helps or hurts" candidate has survived the
replication protocol rather than being explained away as noise (contrast
[[network-link-criticality-and-proxy-validation]], where neither candidate
survived).

**And the discipline caught a false positive in the other direction**: at the
enumeration's single seed L1 looked *harmful* (−9,934 veh-s), but across 10
seeds it is significantly *beneficial* (−90,795, p = 0.012). A single-seed sign
on a small effect is not a finding.

## Verified: both practitioner heuristics get it wrong; the GA does not

Budgets in monetary units (MU); benefits in vehicle-seconds of horizon-censored
full-demand TSTT; NPV at VOT 20 USD/veh-h, 500 peak events/year, 4% discount
rate, 20-year horizon (annuity 13.59033), 1 MU = USD 1M.

| budget | enumerated optimum | GA | rank-by-worst-v/c | rank-by-isolated-BCR |
|---|---|---|---|---|
| 3 | L2, +156,549 (NPV +2.91) | same (20/20 seeds) | same | same |
| 6 | L1+L2, +369,527 (NPV +7.95) | same (19/20) | L2+L3, +242,052, **−34.5% benefit** | L2+L4, +297,792, **−19.4%** |
| 9 | L1+L2+L7, +561,495 (NPV +12.20) | same (20/20) | L2+L3+L7, +359,107, **−36.0%** | L2+L4+L6, +353,594, **−37.0%** |
| 12 | L1+L2+L4+L5, +741,823 (NPV +16.00) | same (15/20) | **L2+N1, −56,125 (NPV −13.62) — worse than do-nothing, −107.6%** | L2+L4+L5+L6, +549,867, **−25.9%** |
| 15 | L1+L2+L3+L5+L6, +810,740 (NPV +15.61) | same (19/20) | L2+L3+N1, +214,969 (NPV **−6.38**), **−73.5%** | L2+L3+L4+L5+L6, +722,605, **−10.9%** |

- **Rank-by-worst-v/c is dangerous, not merely suboptimal.** It scores the
  shortcut NB and the diagonal N1 highly precisely *because* they parallel the
  most-loaded corridors — and at budgets 12 and 15 it funds N1, a replicated
  paradox project, producing a **negative-NPV portfolio** and, at budget 12, a
  network **worse than doing nothing at all**.
- **Rank-by-isolated-BCR is safe in sign but loses 10.9-37.0% of the achievable
  benefit**, because it can never see complementarity: it never funds L1 (whose
  isolated BCR is −0.125) even though L1 is in the true optimum at every budget
  from 6 MU upward.
- **The GA (binary genome, tournament selection, uniform crossover, bit-flip
  mutation, elitism, budget-violation penalty in the decoder) recovered the exact
  enumerated optimum at every budget level**, with 15/20 to 20/20 individual
  seeds hitting it and a median of **8 / 25 / 50 / 70 / 89 distinct feasible
  designs simulated** against **8 / 29 / 66 / 115 / 179** feasible designs in the
  space — i.e. roughly half the feasible space at the larger budgets. Because a
  penalised decoder can never return an infeasible design, an infeasible genome
  never needs an equilibrium evaluation, which is also how a practitioner would
  run it.

## Verified: the budget-benefit frontier is non-concave — the operational finding

| budget | best subset | benefit (veh-s) | marginal benefit of the last 3 MU |
|---|---|---|---|
| 0 | (none) | 0 | — |
| 3 | L2 | 156,549 | 52,183 /MU |
| 6 | L1+L2 | 369,527 | **70,993 /MU (INCREASED)** |
| 9 | L1+L2+L7 | 561,495 | 63,990 /MU |
| 12 | L1+L2+L4+L5 | 741,823 | 60,109 /MU |
| 15 | L1+L2+L3+L5+L6 | 810,740 | 22,972 /MU |

The **second** 3 MU buys *more* than the first, because L1 is worthless alone and
only pays off bundled with L2. A budget-setter reasoning from diminishing returns
would underfund exactly the increment with the highest return. Separately,
**NPV peaks at budget 12 (+16.00 MU) and falls at 15 (+15.61 MU)** — the last
increment destroys value even though TSTT still improves.

## Honest limitations

- The enumeration used **one** seed (CRN across designs). The measured
  seed-to-seed SD of a CRN-paired difference is **94,452 veh-s**, so
  single-seed differences below ~189,000 veh-s are not robust to seed choice.
  Under that screen the greedy shortfalls at budgets 9 and 12 are robust; those
  at 6, and the isolated-BCR shortfall at 15, are not. Only **1 of the 45
  individual interaction cells** clears the corresponding (doubled) threshold —
  the *distributional* claim about non-additivity is far better supported than
  any single cell.
- 229 of the 1024 subsets were evaluated: every one of the 179 budget-feasible
  designs (making each per-budget optimum exact), all 10 singletons, all 45
  pairs, and a documented random sample of 40 of the rest. A full 1024
  enumeration was projected at ~5.9 h of wall clock and rejected.
- 200 of 229 evaluations met the pre-declared convergence criterion
  (`rel_gap_tail_mean <= 0.15` and tail spread `<= 0.08`); the rest are flagged
  in the results table. **One of the 29 flagged evaluations is itself a
  per-budget optimum**: the B=6 winner (L1+L2, both as the enumerated optimum
  and the GA's answer) has `rel_gap_tail_mean=0.124` (within threshold) but
  `tt_stab=0.084`, marginally over the 0.08 tail-spread bar. Flagging convergence
  does not make a result wrong on its own — this design's benefit (+369,527
  veh-s) is roughly 3.9x the measured seed-to-seed noise SD (94,452 veh-s), so
  it is very likely a genuine result — but it means the B=6 headline figure
  should be treated as provisional until re-run with a longer or looser
  criterion, and the self-check above ("none of them is a per-budget optimum")
  was itself wrong when first written and is corrected here.
- The accounting identity `arrived + running + not_inserted + discarded =
  scheduled` balanced on **229/229** runs, with zero never-inserted, zero
  unroutable and zero still-running vehicles and at most 3 teleports on any run —
  so the horizon-censoring channel that reversed a headline finding in
  [[network-link-criticality-and-proxy-validation]] was empty here. That is a
  demonstrated result, not an assumption.

## The decision rule for practitioners

Isolated-BCR ranking (and any additive appraisal of a project portfolio) is
defensible **only when all three diagnostics are clear**:

1. **Interaction magnitude.** Sample pairs and compute
   `|I(i,j)| / (|B(i)|+|B(j)|)`. Below ~10%, additivity is tolerable; above ~25%,
   it is unusable. Measured here: median **41.0%**, max **411.9%** — unusable.
2. **A capacity-paradox project.** If any single project has a *replicated*,
   significantly negative benefit, ranking heuristics can actively fund harm.
   Measured here: two, at +4.3% and +5.6% TSTT with dz = 1.01 and 1.68.
3. **Frontier concavity.** If the marginal return on budget ever *increases*,
   incremental funding decisions are wrong. Measured here: it increases at the
   first increment.

Any one of the three triggers a full combinatorial search. All three fired here,
and the cost of ignoring them was a **107.6% benefit shortfall and a negative
NPV** for the worst-v/c rule. When full enumeration is unaffordable, a penalised
GA is an adequate substitute — validated here against a known global optimum at
five budget levels — but a *ranking* heuristic is not.

See the `solve-budget-constrained-network-design-problem` skill for the full
testbed-construction, equilibrium-evaluation, search and verification workflow.
