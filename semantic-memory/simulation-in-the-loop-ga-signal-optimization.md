---
summary: A genetic algorithm can jointly optimize a coordinated fixed-time signal plan's cycle length, per-intersection green splits, and per-intersection offsets using repeated full SUMO simulations as the fitness function; verified to converge cleanly and discover a genuine green-wave offset pattern, but whether it beats an analytic tlsCycleAdaptation+tlsCoordinator baseline depends entirely on whether both share the same search-space bounds — a GA constrained to a narrower cycle range than the true optimum can lose to the analytic baseline even while converging correctly.
keywords:
  - genetic-algorithm
  - simulation-in-the-loop-optimization
  - signal-plan-optimization
  - metaheuristic
  - green-wave-offset
created: 2026-07-28T15:35:00
last_updated: 2026-08-11T23:15:00
sources:
  - "[[episodic-memory/2026-08-11_21-20-19/summary.md]]"
  - "[[episodic-memory/2026-07-28_15-09-38/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-28_15-09-38/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[simulation-based-optimization-under-noise-and-seed-overfitting]]"
  - "[[tlscycleadaptation]]"
  - "[[tlscoordinator]]"
  - "[[waut-time-of-day-signal-plan-switching]]"
  - "[[arterial-signal-progression-resonance-bandwidth-and-delay]]"
related_skills:
  - optimize-under-simulation-noise-with-a-fixed-budget
  - optimize-signal-plan-with-simulation-in-the-loop-ga
  - optimize-signals-by-tlscycleadaptation
  - optimize-signals-by-tlscoordinator
  - design-arterial-signal-progression-and-verify-bandwidth
related_skills_for_graph_view:
  - "[[optimize-under-simulation-noise-with-a-fixed-budget]]"
  - "[[optimize-signal-plan-with-simulation-in-the-loop-ga]]"
  - "[[optimize-signals-by-tlscycleadaptation]]"
  - "[[optimize-signals-by-tlscoordinator]]"
  - "[[design-arterial-signal-progression-and-verify-bandwidth]]"
---

# Simulation-in-the-Loop GA Signal Optimization

A genetic algorithm can optimize a coordinated fixed-time signal plan — a shared cycle length, a green-split fraction per intersection, and an offset per intersection, treated jointly as one genome — using a full SUMO simulation run as the fitness evaluation for each candidate. This is a global, black-box search over the entire plan, distinct from analytic per-intersection timing ([[tlscycleadaptation]], Webster's method) or heuristic offset-only coordination ([[tlscoordinator]]).

## Verified: the GA converges reliably and can discover a genuine green-wave

On a 3-intersection arterial corridor with a dominant through movement, a GA (population 20, 15 generations, tournament selection, blend crossover, Gaussian mutation, elitism) converged cleanly — best-so-far objective improved monotonically by roughly 38% from generation 0 to the final generation in repeated tests — and the final best genome's offsets closely matched the theoretically ideal green-wave progression value (`intersection_spacing / cruise_speed`, modulo the cycle length), discovered purely through fitness pressure without being explicitly told to optimize for a green wave.

## Critical finding: search-space bounds determine whether the GA beats an analytic baseline

**A GA constrained to a narrower search space than an analytic baseline's own effective range can lose to that baseline even while converging correctly** — this is not a failure of the metaheuristic, but a consequence of comparing two methods with unequal search freedom. Verified directly: on an undersaturated corridor, a real Webster-based baseline (`tlsCycleAdaptation` + `tlsCoordinator`) found an optimal 20-second cycle length. A GA whose cycle-length bound was set to a plausible-looking example range (40-120s) converged well internally but could never reach the true 20s optimum, and finished measurably worse than the baseline (7.7% higher total time loss) purely because of this artificial constraint. Relaxing the GA's cycle bound to match the baseline tool's own effective range let the GA reach and then exceed the baseline's performance (6-8% better on time loss and waiting time), converging to essentially the same solution quality as before but this time with access to the actual optimum.

**Practical implication**: before concluding a metaheuristic search "beat" or "lost to" an analytic/heuristic baseline, verify both methods had comparable access to the true optimum's location in parameter space. A plausible-sounding "e.g." bound suggested in a task description is not necessarily the correct bound for a fair head-to-head comparison — check what range the baseline method itself explores or would recommend, and either match it or explicitly disclose the mismatch as a caveat on the comparison's validity.

## Reporting both favorable and unfavorable results is the correct practice, not a flaw

When a search-space mismatch produces an unfavorable result for the method being showcased (here, the GA), the correct response is to report it faithfully alongside the corrected, favorable comparison — not to silently discard the unfavorable run. Doing so is directly verifiable after the fact (e.g. via file timestamps showing the unfavorable result existed before the favorable one was produced) and is exactly the kind of honest negative result that makes a comparison trustworthy.

See the `optimize-signal-plan-with-simulation-in-the-loop-ga` skill for the full genome-encoding, fitness-function, and baseline-comparison workflow.

## Correction: the fixed-seed optimum reported here is an in-sample number

This page's GA-vs-baseline comparison, like the skill's, was measured at a single frozen seed.
A later controlled study ([[simulation-based-optimization-under-noise-and-seed-overfitting]]) put that protocol on trial on a 5-signal arterial and
found the bias is large enough to reverse a conclusion: the single-seed GA's plan looked **10.0%
better** than a zero-search `tlsCycleAdaptation`+`tlsCoordinator` baseline in-sample and was
**1.8% worse** on 40 held-out seeds. The seed-overfitting gap was **-5.33%**, negative in 3 of 3
repeats on different frozen seeds, and the GA beat the zero-run baseline in only 1 of 3. Which
seed was frozen moved true plan quality by **7.48%**.

Keep the fixed seed for the search; it is what makes the objective deterministic and the genome
comparison fair. But **re-score the final plan on >=30 held-out seeds and report that number** --
it costs ~10% of the budget. On the same budget a GP surrogate with a Webster analytic trend
found a better plan in one third of the runs and never drifted out-of-sample, so a GA is not the
default choice for this problem shape.
