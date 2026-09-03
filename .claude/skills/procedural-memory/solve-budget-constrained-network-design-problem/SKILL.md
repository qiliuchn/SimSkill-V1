---
name: solve-budget-constrained-network-design-problem
description: Use this skill when the user wants to CHOOSE which road-capacity projects to build from a candidate list under a budget - the discrete Network Design Problem (DNDP) - rather than evaluate one design. Covers the bilevel structure (outer combinatorial project-selection search, inner duaIterate user-equilibrium evaluation), building a congestible testbed with a verified candidate project set, the horizon-censored full-demand TSTT objective, budgeting the evaluation count before launching, exhaustive enumeration to obtain a TRUE optimum for validating a GA against, the two practitioner greedy baselines (worst-v/c ranking and isolated-BCR ranking), the pairwise project-interaction matrix, budget-benefit frontier concavity, and capacity-paradox (project-makes-things-worse) replication. Trigger on mentions of network design problem, DNDP, project selection, capacity expansion portfolio, which projects to build, budget-constrained road investment, project bundling/interaction, or "does the benefit-cost ranking pick the right set."
---

# Solve a Budget-Constrained Discrete Network Design Problem

Chooses a *set* of road-capacity projects under a budget so that user-equilibrium
total system travel time is minimised. This is a **bilevel** problem and is
categorically different from every other appraisal skill in memory:
`appraise-project-alternatives-with-benefit-cost-analysis` compares a handful of
*mutually exclusive* alternatives one at a time, while this skill searches a
combinatorial space of *simultaneously fundable* projects whose benefits are
**not additive** — the whole point is that the set matters, not the ranking.

- **Outer loop**: search over 2^N project subsets subject to a budget.
- **Inner loop**: for each subset, rebuild the network and compute a dynamic
  user equilibrium with `duaIterate.py` on the *same* OD demand and seed
  (`compute-dynamic-user-equilibrium`), then score it.

## Build the testbed, and verify every project is a real mechanism change

Hand-write plain XML nodes/edges (per `create-single-intersection` /
`create-grid-network`) so a "project" is a one-line edit: `numLanes+1` on a named
edge pair, or a new edge pair. Then **diff the COMPILED `net.xml`**, not the
source: per-edge lane counts, the edge-id set, and total lane-metres, for each
project alone against do-nothing. A project that silently no-ops must be caught
here.

**Verified, and it is not a formality: a lane-addition project in SUMO is never a
pure capacity change.** `netconvert` regenerates the `tlLogic` program at *both*
endpoint junctions when an approach's lane count changes (link indices shift, so
the phase state strings change). In the verified testbed **all 10 projects,
including every lane addition, changed exactly 2 of the 16 signal programs.** The
measured "benefit" of a lane addition is therefore a *bundle* of extra capacity
plus an incidental retiming. Report this explicitly — it is a real property of
how SUMO compiles networks, not a modelling choice you can opt out of, and the
only clean alternative is to freeze the signal programs by writing them yourself
as an additional file for every design.

## Load the network to genuine congestion — measure the knee, and calibrate v/c

Sweep total demand and find the **peak of the served-flow-vs-demand curve**
(`quantify-sumo-run-to-run-variability`); that peak is capacity, not the flow at
the heaviest loading tested.

**Do not assume a textbook saturation flow when converting flows to v/c.**
Calibrate it from the run: `s_hat = peak_flow / (numLanes x g/C)` per signalised
edge, with `g/C` read out of the compiled `tlLogic`, then take a high quantile
over edges that are actually saturated. In the verified testbed the calibrated
effective saturation flow was **1595 veh/h/lane (p95 of 55 samples; median 1247)**
against the textbook 1900. The consequence is not cosmetic: at the measured
capacity knee the assumed value reported mean v/c **0.66** on the twelve most
loaded corridors — i.e. it claimed the network was comfortably undersaturated at
exactly the demand where served flow **peaked and began to fall** (7686 veh/h at
4000 vehicles, dropping to 7598 / 7518 / 6698 at 4500 / 5000 / 6000). The
calibrated value put the same point at mean v/c **0.922 on the top-4 corridors**
(0.885 top-6, max 1.025), which is the regime the study actually needs.

## Inner loop: duaIterate reaches a LIMIT CYCLE on a congested network, not a fixed point

This is the single most important finding in this skill, and it silently corrupts
the whole study if missed. On the verified congested grid a 25-iteration cold
start showed the relative gap fall from **0.478 (iteration 1) to a floor of
0.081-0.110 by iteration 12**, and then oscillate inside that band for the
remaining 13 iterations without ever going lower, with mean in-network trip
duration wandering over **532.5-570.1 s (a 6.8% band)** across iterations 12-24
and adjacent-iteration changes as large as **+4.7% / -4.9%**. `duaIterate` does not
converge to a point here — it converges to a band. The same oscillation was
documented by `scan-network-link-criticality-and-vulnerability`; this skill
quantifies its consequence for scoring.

Consequences to build into the protocol:

1. **Score a TAIL AVERAGE, never a single final iteration.** The objective is the
   mean over the last 4 iterations' own simulations; report the tail standard
   deviation with every evaluation. Single-final-iteration scoring carries noise
   of the same order as the project benefits being measured — verified directly:
   the do-nothing design's four tail iterations scored 2,463,583 / 2,563,939 /
   2,487,411 / 2,532,851 veh-s, a **4.00% spread within one evaluation**, which is
   larger than the entire measured benefit of **5 of the 10 candidate projects**.
   Across all 229 evaluations the within-evaluation tail SD had a median of
   **1.42% of TSTT**.
2. **Declare an achievable gap criterion from the trace, not from a textbook.**
   A 0.01 relative-gap target is unreachable on this class of network. Fix the
   criterion after running the trace (here: `rel_gap_tail_mean <= 0.15` and
   tail travel-time spread `<= 0.08`), record the achieved value for **every**
   evaluation, and flag rather than silently keep any design that misses it.
3. **Iterating past the floor buys nothing.** Iteration 13 was as converged as
   iteration 24, so the iteration budget is set by where the trace flattens.
4. **Every duaIterate iteration is already a full simulation of record.** Pass
   `sumo--seed <s>` and `sumo--tripinfo-output.write-unfinished true` and score
   the iteration's own `NNN/tripinfo_NNN.xml` + `NNN/summary_NNN.xml` instead of
   re-simulating the converged route file — it removes a redundant run per tail
   iteration (~25% of evaluation cost) and guarantees the scored run *is* the
   equilibrium run.

## Do NOT warm-start the equilibrium from the do-nothing solution

The obvious way to afford thousands of evaluations is to restart `duaIterate`
from the converged do-nothing route file (`-r base_equilibrium.rou.xml`) with a
short iteration budget. **Verified: this fails, and it fails with a direction of
bias that would have produced a wrong answer.** Warm start (8 iterations) vs cold
start (20 iterations) on 15 designs:

- mean |difference| in TSTT **6.06%**, worst **15.35%**;
- pairwise rank agreement only **81.9%** (Kendall tau 0.638) — the search would
  have optimised a differently-ordered objective;
- warm-start relative gaps were **systematically worse** (0.092-0.184 vs
  0.041-0.111 cold), i.e. it is not converging to the same equilibrium at all;
- **the bias is largest exactly for new-link projects** (N2 +15.4%, NB +11.7%,
  N1 +5.9% TSTT vs cold) because those need the most re-routing away from the
  do-nothing route set, while lane-widening designs were within ~2-6%.

The speed-up was only 2.02x for that price. **Cold-start every evaluation, and
solve the affordability problem by shrinking the search set instead.**

## Budget the evaluations before launching, then shrink the SET, not the protocol

Benchmark one evaluation and multiply. Here: ~6.1 s per duaIterate iteration
single-threaded, 14 iterations -> ~85 s CPU per evaluation; at ~5x effective
parallelism on 10 cores that is **~17 s of wall clock per design**, so a full
2^10 = 1024 enumeration is ~5 hours and was not affordable.

The correct reduction is to enumerate **every budget-feasible subset exactly**,
plus every singleton and pair (for the interaction matrix), plus a documented
uniform random sample of the infeasible remainder. This costs almost nothing in
rigour, because:

> **A GA whose decoder applies a budget-violation penalty can never return an
> infeasible design.** Exhaustively evaluating the feasible region therefore
> gives the *exact* budget-constrained global optimum the metaheuristic must be
> validated against, and the infeasible genomes the GA visits never need an
> equilibrium evaluation at all — which is also what a practitioner would do.

## Outer loop: enumerate for truth, then validate the metaheuristic against it

Run the GA (binary genome of length N, tournament selection, uniform crossover,
bit-flip mutation, elitism, budget penalty in the decoder) **many times with
different GA seeds** and report the distribution — how many seeds recover the
enumerated optimum, the median number of *distinct* designs evaluated, and the
optimality gap of the best and worst run. A single GA run against a known
optimum is an anecdote; 20 runs is a validation. This is the rare case where the
true optimum is known, so state the hit rate rather than "the GA converged."

**Verified: the GA passes, and the honest evaluation count is about half the
feasible space.** Population 20 x 30 generations recovered the exact enumerated
optimum at all five budget levels, with **20/20, 19/20, 20/20, 15/20 and 19/20**
individual seeds hitting it, and a median of **8 / 25 / 50 / 70 / 89 distinct
feasible designs simulated** against feasible-space sizes of **8 / 29 / 66 / 115
/ 179**. Report the *distinct feasible* count, not population x generations —
the latter overstates the simulation cost by an order of magnitude because most
genomes repeat or are penalised without ever being simulated.

## The two practitioner baselines, and why they are the point of the exercise

- **Rank-by-worst-v/c greedy**: score each project by the do-nothing-equilibrium
  v/c of the link(s) it improves (for a new link, the worst v/c on the existing
  path it would parallel — state the rule), fund in descending order while the
  budget allows.
- **Rank-by-isolated-BCR greedy**: appraise every project *alone* against
  do-nothing, compute BCR from monetised TSTT savings (`econ` layer of
  `appraise-project-alternatives-with-benefit-cost-analysis`: VOT, events/year,
  discount rate, horizon, every parameter's provenance labelled), fund in
  descending BCR while the budget allows.

Both are exactly what an agency does. Report each one's TSTT gap and NPV gap
against the enumerated optimum at every budget level.

**Verified: worst-v/c ranking is dangerous, isolated-BCR ranking is merely
expensive.** Worst-v/c scores a new link highly precisely *because* it parallels
the most-loaded corridor, so it funded a replicated capacity-paradox project and
produced portfolios **107.6% and 73.5% short** of the optimum at budgets 12 and
15 — with **negative NPV (−13.62 and −6.38 MU)**, and at budget 12 a network
**worse than doing nothing at all** (−56,125 veh-s of benefit). Isolated-BCR kept
the right sign but lost **10.9-37.0%** of achievable benefit at every budget
above the smallest, because it can never fund a project whose standalone BCR is
negative — here the project with isolated BCR **−0.125** appears in the true
optimum at every budget from 6 MU upward.

## Claim 1: build the interaction matrix from real equilibrium runs

`I(i,j) = B(i+j) - B(i) - B(j)` with `B(S) = TSTT(do-nothing) - TSTT(S)`, from
actual paired runs — N(N-1)/2 extra equilibrium evaluations. **Report `I` as a
percentage of `|B(i)| + |B(j)|`**, not in raw seconds, or the reader cannot tell
whether additivity is a tolerable approximation. Explain at least one clearly
complementary and one clearly substitutive pair **in terms of where the binding
bottleneck moves** — read it off the per-edge v/c of the two single-project
equilibria versus the pair's, not from the aggregate number.

Compare every interaction against the **evaluation noise floor** (re-evaluate a
few designs under the identical protocol with different seeds); an interaction
smaller than ~2 sigma is not interpretable, and on an oscillating congested
equilibrium sigma is not small.

**Verified: additivity was not merely imperfect, it was useless.** Over the 45
pairs the median |I| was **41.0%** of `|B(i)|+|B(j)|`, the 90th percentile
**110.9%**, the maximum **411.9%**, and **40 of 45 pairs exceeded 10%**. Two
projects that are individually near-worthless can be jointly transformative: on
the verified testbed the two consecutive links of one corridor scored
**-9,934** and **+156,549** veh-s alone but **+369,527** together
(`I = +222,912`, +133.9%) — widening either one alone simply relocates the
binding bottleneck onto the other. Conversely two projects that are each
*harmful* compounded rather than cancelled (`I = -265,232`, -55.8%). Notably,
among pairs where **both** projects were individually beneficial, every single
interaction was positive (complementary, +1.2% to +97.4%) — the substitutive
cells were all created by a harmful project.

## Claim 2: capacity paradox — replicate before believing, and report the null honestly

A single project whose construction *increases* equilibrium TSTT is Braess's
paradox generalised to a capacity project. Screen it from the singleton runs,
then apply the replication discipline `construct-and-verify-braess-paradox` and
`scan-network-link-criticality-and-vulnerability` established: **>= 10 CRN paired
seeds, cold-started in both arms, paired t-test + Wilcoxon + Cohen's dz +
bootstrap CI on the paired difference, plus a positive control** (the
largest-benefit project) run through the identical test to show it can detect a
real effect at that replication count. If nothing survives, report the tightest
null — the smallest benefit / closest to zero — rather than manufacturing a
paradox.

Cold-start both arms specifically: a warm start from the do-nothing equilibrium
biases *against* the project arm (see above) and would manufacture a fake
paradox.

**Verified, in both directions.** Two projects survived replication as genuinely
harmful — a new diagonal at **+114,799 veh-s (+4.33%), p = 0.011 (paired t),
0.027 (Wilcoxon), dz = 1.012, bootstrap CI [+52,253, +183,929], 7/10 seeds
positive**, and the deliberately-placed shortcut at **+147,746 (+5.57%),
p = 0.00049, dz = 1.678, CI [+96,176, +199,537], 10/10 seeds positive**. Across
the whole search, **55 of 229 designs (24.0%) were worse than do-nothing, and 53
of those 55 (96.4%) contained at least one new link** — the paradox is a property
of the project *class*, not one unlucky alignment. **And the same discipline
caught a false positive going the other way**: one lane addition looked harmful
at the enumeration's single seed (−9,934 veh-s) but was significantly
*beneficial* across 10 seeds (−90,795, p = 0.012). A single-seed sign on a small
effect is not a finding, whichever way it points.

**Measure the seed-to-seed SD of the CRN-PAIRED difference and screen every
headline number against it.** Here it was **94,452 veh-s**, so single-seed
differences below ~189,000 veh-s are not robust to seed choice — which, applied
honestly, keeps the greedy shortfalls at two of five budget levels and only
**1 of the 45 individual interaction cells**. The distributional claim about
non-additivity is far better supported than any single cell, and saying so is
part of the result.

## Frontier concavity is the operationally important deliverable

Plot best-achievable benefit against budget over >= 5 budget levels and test
whether the marginal return on the last increment ever *increases*. A
**non-concave** frontier means an incremental budget increase is worthless until
a threshold is crossed — because a complementary pair only pays off when both
halves are funded. That is the finding a budget-setter actually needs, and it is
invisible to any additive appraisal.

**Include budget 0 (do-nothing) as a frontier point.** On the verified testbed
the non-concavity lives entirely in the *first* increment — marginal benefit went
**52,183 -> 70,993 veh-s per MU** from the first to the second 3 MU, because the
project that completes the complementary pair is worthless alone. A frontier
starting at the smallest non-zero budget cannot see this and reports a
comfortingly concave curve.

Also report **NPV per budget level, not just benefit**: here NPV peaked at budget
12 (+16.00 MU) and *fell* at 15 (+15.61 MU) even though TSTT kept improving — the
benefit-maximising budget and the value-maximising budget are different numbers.

## Report the accounting, not just the objective

Every evaluation must carry, and the write-up must state: the achieved relative
gap, the tail travel-time spread, the tail TSTT standard deviation, the
arrived / still-running / never-inserted / unroutable-discarded counts, the
teleport count, and whether the accounting identity balanced. On the verified
229-design enumeration the identity balanced on **229/229** runs, with **zero**
never-inserted, **zero** unroutable and **zero** still-running vehicles and at
most **3** teleports on any run — so the horizon-censoring channel was empty here
and the TSTT is a clean sum of completed door-to-door times. **That is a result
to be demonstrated, not assumed**: `scan-network-link-criticality-and-vulnerability`
found the same accounting reversing a headline finding when it was not checked.

## State the decision rule the numbers imply

The point of the exercise is a rule an agency can apply without re-running it.
Three diagnostics, any one of which triggers a full combinatorial search:

1. **Interaction magnitude** — sample pairs, compute `|I| / (|B(i)|+|B(j)|)`.
   Below ~10% additivity is tolerable, above ~25% it is unusable.
2. **A replicated capacity-paradox project** — if one exists, a ranking rule can
   actively fund harm, not merely rank suboptimally.
3. **Frontier non-concavity** — if the marginal return on budget ever increases,
   incremental funding logic is wrong.

Emit these as a machine-readable `decision_diagnostics.json` alongside the
results, with the measured value and the threshold, so the verdict is auditable.

## Gotchas

- **A lane addition is not a pure capacity change** — it regenerates the signal
  program at both endpoint junctions. Verify and disclose.
- **`duaIterate` oscillates rather than converging on a congested network** —
  tail-average the objective and declare a gap criterion measured from a trace.
- **Warm-starting the equilibrium from do-nothing is biased against new links**,
  by up to 15% TSTT, and degrades the relative gap — never buy evaluations that way.
- **Score from `duaIterate`'s own per-iteration `tripinfo`/`summary`** (with
  `sumo--tripinfo-output.write-unfinished true`) rather than re-simulating.
- **Use a horizon-censored full-demand TSTT** charging arrived, still-running,
  never-inserted and unroutable vehicles alike, and assert
  `arrived + running + not_inserted + discarded == scheduled` on every run
  (`scan-network-link-criticality-and-vulnerability`).
- **Don't assume a textbook saturation flow** when reporting v/c — calibrate it
  from `flow / (lanes x g/C)` on saturated edges.
- **Don't report an interaction or a benefit smaller than ~2x the evaluation's
  own seed-to-seed standard deviation** — measure that standard deviation.
- **A penalised GA decoder never returns an infeasible design**, so enumerating
  only the budget-feasible region still yields the exact optimum for validation.

## Related

- `compute-dynamic-user-equilibrium` — the `duaIterate.py` inner loop, its
  convergence-trace conventions and the dual-cost Wardrop check.
- `appraise-project-alternatives-with-benefit-cost-analysis` — the monetisation /
  discounting / parameter-provenance layer this skill's NPV column reuses, and
  the mutually-exclusive counterpart to this skill's combinatorial problem.
- `construct-and-verify-braess-paradox` — the paradox mechanism and the
  replicate-before-reporting discipline this skill's capacity-paradox test applies
  to a *capacity project* rather than a hand-built topology.
- `scan-network-link-criticality-and-vulnerability` — the horizon-censored
  full-demand accounting identity, and the prior observation that re-equilibration
  oscillates on congested networks that this skill quantifies and works around.
- `optimize-signal-plan-with-simulation-in-the-loop-ga` — the simulation-in-the-loop
  GA machinery (genome, decoder, benchmark-before-committing discipline), here
  applied to a binary/combinatorial rather than continuous search space, and for
  the first time validated against a *known* global optimum.
- `quantify-sumo-run-to-run-variability` — the capacity-knee measurement and the
  CRN/replication design this skill's demand calibration and paradox test use.
- `create-grid-network` / `create-single-intersection` — the plain-XML network
  construction the candidate project set is built on.
- [[discrete-network-design-and-project-interaction]] — the verified enumerated-vs-GA-vs-greedy
  results, interaction magnitudes, capacity-paradox replication and the decision rule.
- [[dynamic-user-equilibrium-and-wardrop]], [[braess-paradox-in-sumo]],
  [[transport-economic-appraisal-from-microsimulation]] — the underlying theory.
