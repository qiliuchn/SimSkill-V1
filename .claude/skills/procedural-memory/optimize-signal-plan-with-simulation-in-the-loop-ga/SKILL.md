---
name: optimize-signal-plan-with-simulation-in-the-loop-ga
description: Use this skill when the user wants to optimize a coordinated FIXED-TIME signal plan (cycle length, per-intersection green splits, and per-intersection offsets, jointly) via a genetic algorithm or other population-based metaheuristic using repeated full SUMO simulations as the fitness function — a global black-box search over the whole plan, as opposed to analytic per-intersection timing (tlsCycleAdaptation/Webster), heuristic offset-only coordination (tlsCoordinator), or online adaptive/RL control (actuated, NEMA, max-pressure, Q-learning). Covers encoding the plan as a genome, a decoder that enforces yellow clearance and minimum green while writing valid tlLogic, a fitness function with an incomplete-vehicle penalty, benchmarking subprocess-per-eval vs libsumo before committing to a full GA run, and honestly comparing against a real tlsCycleAdaptation+tlsCoordinator baseline including the case where the baseline wins. Trigger on mentions of genetic algorithm signal optimization, GA traffic signals, simulation-in-the-loop optimization, metaheuristic signal timing, or TRANSYT-style joint cycle/split/offset optimization.
---

# Optimize Signal Plan with Simulation-in-the-Loop GA

A genetic algorithm (or similar population-based metaheuristic) that treats an entire coordinated fixed-time signal plan — cycle length, every intersection's green split, every intersection's offset — as a single search space, using a full SUMO simulation run as the fitness evaluation. This is a fundamentally different optimization paradigm from every other signal-control skill in memory: it's a *global joint* search via repeated black-box simulation, not a per-intersection analytic formula (`optimize-signals-by-tlscycleadaptation`), a heuristic offset pass (`optimize-signals-by-tlscoordinator`), or a live reactive/RL controller.

## Genome encoding and decoding

Encode the plan as a flat vector: one shared cycle length `C`, one main-green split fraction per intersection, one offset per intersection. The decoder (`scripts/ga_common.py`) must:
- **Enforce minimum green and fixed yellow clearance in code**, not just by convention — clamp a genome's split so neither movement group falls below a minimum green time, recomputing the effective cycle after clamping so offset arithmetic stays exact.
- **Auto-detect each junction's main-vs-side green phase** from the compiled network's own connection data (which links originate from the "main" edges) rather than hard-coding phase indices — this makes the decoder reusable across junctions without per-junction special-casing.
- **Write offsets to SUMO's real `tlLogic` `offset` attribute** — verify this is a genuine mechanism change, not a no-op, by checking the compiled program actually differs.

A genome that would produce a degenerate signal plan should be *penalized in fitness*, not allowed to crash the evaluation — clamp to valid bounds in the decoder itself.

## Fitness function

```python
def fitness(genome, workdir):
    write_tls_add(genome, add_file)          # decode genome -> tlLogic .add.xml
    run_sim(add_file, trip_out)              # full SUMO run, fixed demand + seed
    m = parse_tripinfo(trip_out)
    incomplete = max(0, N_VEH - m["n"])      # vehicles that never completed
    return m["total_timeLoss"] + PENALTY * incomplete
```

Use **identical demand and seed for every single evaluation** during the search — it makes the comparison across genomes fair and the objective deterministic. Penalize incomplete/teleported vehicles heavily so a degenerate plan (e.g. gridlock) scores worse than a merely suboptimal one, rather than looking artificially good because fewer vehicles' delay got counted.

> **Correction — an earlier version of this skill called the fixed seed "non-negotiable" and stopped there. That is wrong as a reporting protocol, and measurably so.** A fixed seed makes the *search* well-posed but makes the resulting objective an estimate on one sample. Measured on a 5-signal arterial at 77% of capacity, 300 evaluations, 40 held-out seeds
> ([[simulation-based-optimization-under-noise-and-seed-overfitting]]): the plan this protocol produced looked **10.0% better** than a zero-search `tlsCycleAdaptation`+`tlsCoordinator` baseline in-sample, and was **1.8% worse** out-of-sample. The seed-overfitting gap was **−5.33%**, negative in 3 of 3 repeats on different frozen seeds, and the GA beat the zero-run baseline in only 1 of 3. Which seed you happen to freeze moved true plan quality by **7.48%**.
>
> Keep the fixed seed for the search. **Then re-score the final incumbent on ≥30 held-out seeds and report that number**, never the in-sample optimum — it costs ~10% of the budget. And carry the zero-search analytic baseline through to the held-out comparison, because it may win. See `optimize-under-simulation-noise-with-a-fixed-budget`.

## Benchmark before committing to the full run

A GA needs hundreds of fitness evaluations (population × generations). **Benchmark actual per-evaluation wall time on a handful of runs before committing to a full population/generation budget** — `libsumo` (in-process, no socket overhead) is much faster than a `sumo` subprocess per evaluation when available; if `libsumo` isn't installed, a subprocess-per-eval approach is acceptable but must be benchmarked first (verified: ~0.36s/eval via subprocess was fast enough for population 20 × 15 generations in this skill's test). Don't assume speed — measure it.

## Baseline: use the REAL tools, not an approximation

Build the comparison baseline by actually running `optimize-signals-by-tlscycleadaptation` (Webster cycle/splits) and `optimize-signals-by-tlscoordinator` (offsets) on the identical network and demand — not a hand-computed approximation of what they'd produce. Evaluate the baseline with the exact same fitness function (same demand, seed, objective computation) used for the GA population, so the comparison is genuinely fair.

## Critical: match the GA's search-space bounds to the baseline's, or the comparison isn't fair

**Verified finding: a GA can lose to an analytic baseline purely because its search-space bounds were narrower than the baseline's, even when the GA converges correctly and the baseline is genuinely worse-informed about the true optimum's location.** On an undersaturated corridor, a real analytic Webster baseline found an optimal 20s cycle — but a GA search space bounded to the *literal example range in the task description* (40-120s) couldn't reach that optimum and finished 7.7% behind the baseline despite converging cleanly. Relaxing the GA's cycle bound to match the baseline tool's own defaults produced a GA that then beat the baseline by 6.3-7.7%. **When comparing a metaheuristic against an analytic baseline, always check whether their search spaces are actually comparable** — an "e.g." range in a task description is not necessarily the correct bound for a fair comparison, and reporting an unfavorable result faithfully (rather than silently only running the favorable configuration) is the correct, honest way to surface this.

## Verifying convergence and the green-wave signature

Log best-so-far and generation-mean objective every generation to a CSV; the best-so-far column must be non-increasing by construction (elitism) — verify this directly from the raw CSV rather than trusting a convergence plot alone. Check the final best genome's offsets for a recognizable green-wave pattern: the ideal relative offset between adjacent intersections is `(intersection_spacing / cruise_speed) mod cycle_length` — a genuinely converged GA optimizing a corridor with a dominant through movement should discover offsets close to this value without being told to look for one.

## Gotchas

- **Enforce minimum green/yellow in the decoder itself**, not just hope the GA avoids invalid genomes — clamp, don't crash.
- **Use identical demand and seed for every evaluation** during the search, GA population and baseline alike — otherwise the comparison is confounded. **But never report the in-sample optimum**: re-score the final plan on ≥30 held-out seeds (see the correction above). The in-sample number overstated this skill's own result by ~12 percentage points.
- **Check that each decision variable is resolvable above the noise floor before optimizing it.** On a 400 m-spacing arterial the entire effect of all 5 offset variables was 4.58% of the objective — *below* the 9.25% difference a single-seed comparison can resolve. A GP surrogate independently discovered this by pinning its offset length-scale to the upper bound. Optimizing a dimension whose whole effect is smaller than your noise floor is wasted budget.
- **Benchmark per-evaluation runtime before committing to a full population×generation budget** — don't assume subprocess overhead is negligible.
- **Match search-space bounds to the baseline's before concluding the GA "lost" or "won"** — a narrower bound can make a correctly-converging GA look worse than an analytic method that simply had more room to find the true optimum.
- **Build the baseline from the real tools**, not a hand-approximation — check for genuine tool-provenance evidence (e.g. generator headers) in the baseline's output files.

## Related

- `optimize-under-simulation-noise-with-a-fixed-budget` — the successor protocol: noise floor first, hard evaluation budget, held-out validation, and a GP-surrogate optimizer that reached a better plan than this skill's GA in one third of the runs.
- `optimize-signals-by-tlscycleadaptation`, `optimize-signals-by-tlscoordinator` — the analytic/heuristic baseline this skill's GA is compared against. Note it beat this skill's GA out-of-sample at zero simulation cost.
- `switch-signal-plans-by-time-of-day-with-waut` — background on multiple `tlLogic` programs per junction and program-ID mechanics.
- `implement-maxpressure-traci-controller`, `control-signals-with-actuated-tls` — the online-reactive alternatives to this skill's offline metaheuristic approach.
- [[simulation-in-the-loop-ga-signal-optimization]] — the underlying GA-vs-analytic-baseline mechanics and the verified search-space-bound finding.
