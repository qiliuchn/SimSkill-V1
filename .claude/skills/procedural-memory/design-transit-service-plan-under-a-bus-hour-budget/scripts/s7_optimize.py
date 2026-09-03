"""Stage 5: frequency allocation under the fixed bus-hour budget.

(a) analytic reference  -- the classical square-root rule (fleet share
    proportional to sqrt(Q_l * C_l)), plus equal and demand-proportional rules;
(b) simulation-in-the-loop optimizer -- a greedy marginal-benefit build from the
    minimum feasible allocation, followed by a pairwise 1-bus-transfer local
    search, under a HARD evaluation budget, then re-scored on held-out seeds.

Follows `optimize-under-simulation-noise-with-a-fixed-budget`:
  * noise floor measured first (s6_noise.py);
  * one replication per design point during search (buy designs, not reps);
  * the reported number is the HELD-OUT mean, and the seed-overfitting gap is
    reported for every arm including a zero-search baseline.
"""
import os, sys, json, math, random, statistics as st
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

BUDGET = int(os.environ.get("BUDGET", "24"))
STRUCT = os.environ.get("STRUCT", "trunkfeeder")
SEARCH_SEED = 7001                       # single frozen seed used during search
HELDOUT = list(range(301, 313))          # 12 held-out seeds, disjoint book
EVAL_CAP = int(os.environ.get("EVAL_CAP", "125"))
OUTJ = os.path.join(WORK, "stage5_optimize.json")


def main():
    speeds = H.load_json(H.SPEED_FILE)[STRUCT]
    cycles = H.load_json(H.CYCLE_FILE)[STRUCT]
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    lo, hi = A.bounds(cycles, ids)
    print(f"structure={STRUCT} budget={BUDGET} lo={lo} hi={hi}")

    # ---------------- analytic references -----------------------------------
    refs = {}
    b, ok, msg = A.sqrt_rule(BUDGET, cycles, demand, ids); refs["sqrt_rule"] = b
    b, ok, _ = A.equal_rule(BUDGET, cycles, ids);          refs["equal"] = b
    b, ok, _ = A.proportional_rule(BUDGET, cycles, demand, ids)
    refs["proportional"] = b
    for k, v in refs.items():
        print(f"  {k:14s} {v}")

    bud = H.Budget(EVAL_CAP, os.path.join(WORK, "optimizer_evals.csv"))
    cache = {}

    def score_batch(cands, seed=SEARCH_SEED):
        """Evaluate a batch of allocations in parallel, one replication each
        (buy designs, not replications).  The budget counter is taken BEFORE
        dispatch so the cap is enforced, not merely reported."""
        todo = [c for c in cands
                if (tuple(sorted(c.items())), seed) not in cache]
        room = EVAL_CAP - bud.n
        if len(todo) > room:
            todo = todo[:max(0, room)]
        if todo:
            bud.take(len(todo))
            jobs = [(STRUCT, c, seed, None, cycles, speeds,
                     "op_" + H.design_key(STRUCT, c), False) for c in todo]
            ms = H.evaluate_many(jobs, workers=min(8, len(jobs)))
            for c, m in zip(todo, ms):
                if "error" in m:
                    raise RuntimeError(m["tb"])
                v = H.gc_total(m)
                cache[(tuple(sorted(c.items())), seed)] = v
                bud.record("op_" + H.design_key(STRUCT, c), seed, v)
        return [cache.get((tuple(sorted(c.items())), seed)) for c in cands]

    def score(b, seed=SEARCH_SEED):
        return score_batch([b], seed)[0]

    # ---------------- phase 1: greedy marginal-benefit build ----------------
    cur = dict(lo)
    spare = BUDGET - sum(cur.values())
    print(f"\nphase 1 greedy build: {sum(cur.values())} minimum-feasible buses, "
          f"{spare} to allocate, cost <= {spare} x {len(ids)} = {spare*len(ids)} evals")
    trace = []
    for step in range(spare):
        # candidate restriction (documented): only the 5 lines with the longest
        # current headway are trial-evaluated at each greedy step.  A bus added
        # to an already-frequent line cannot plausibly beat one added to the
        # worst-served line, and the phase-2 local search repairs any mistake.
        elig = [l for l in ids if cur[l] + 1 <= hi[l]]
        elig.sort(key=lambda l: -(cycles[l] / cur[l]))
        elig = elig[:5]
        cands, labs = [], []
        for l in elig:
            t = dict(cur); t[l] += 1
            cands.append(t); labs.append(l)
        vs = score_batch(cands)
        i = min(range(len(vs)), key=lambda k: (vs[k] is None, vs[k]))
        cur = cands[i]
        trace.append(dict(step=step, added=labs[i], objective=vs[i], alloc=dict(cur)))
        print(f"  +1 bus -> {labs[i]:5s}  obj {vs[i]/3600:9.2f} pax-h   {cur}")
    greedy = dict(cur)
    greedy_v = score(greedy)

    # ---------------- phase 2: pairwise 1-bus transfer local search ---------
    print(f"\nphase 2 steepest-descent local search on 1-bus transfers "
          f"(evals used {bud.n}/{EVAL_CAP})")
    best_v = greedy_v
    swaps = []
    for rnd in range(4):
        moves = [(i, j) for i in ids for j in ids
                 if i != j and cur[i] - 1 >= lo[i] and cur[j] + 1 <= hi[j]]
        cands, labs = [], []
        for i, j in moves:
            t = dict(cur); t[i] -= 1; t[j] += 1
            cands.append(t); labs.append((i, j))
        if not cands or bud.n >= EVAL_CAP:
            break
        try:
            vs = score_batch(cands)
        except RuntimeError as e:
            print("  ", e); break
        pairs = [(v, k) for k, v in enumerate(vs) if v is not None]
        if not pairs:
            break
        v, k = min(pairs)
        if v < best_v - 1e-9:
            swaps.append(dict(round=rnd, frm=labs[k][0], to=labs[k][1],
                              before=best_v, after=v))
            print(f"  round {rnd}: move 1 bus {labs[k][0]} -> {labs[k][1]}: "
                  f"{best_v/3600:.2f} -> {v/3600:.2f} pax-h")
            cur, best_v = cands[k], v
        else:
            print(f"  round {rnd}: no improving 1-bus transfer "
                  f"(best neighbour {v/3600:.2f} vs incumbent {best_v/3600:.2f})")
            break
    opt = dict(cur)
    print(f"  optimizer incumbent {opt}  in-sample {best_v/3600:.2f} pax-h "
          f"(evals used {bud.n}/{EVAL_CAP})")

    # ---------------- held-out validation -----------------------------------
    arms = dict(refs); arms["greedy_opt"] = greedy; arms["optimizer"] = opt
    # score the ZERO-SEARCH baselines at the search seed too, so every arm has an
    # in-sample number and the seed-overfitting gap can be reported for the
    # control as well as the searchers.  These are NOT charged to the search
    # budget -- they are not search evaluations.
    need = [b for b in arms.values()
            if (tuple(sorted(b.items())), SEARCH_SEED) not in cache]
    if need:
        ms = H.evaluate_many([(STRUCT, c, SEARCH_SEED, None, cycles, speeds,
                               "base_" + H.design_key(STRUCT, c), False)
                              for c in need], workers=min(6, len(need)))
        for c, m in zip(need, ms):
            if "error" not in m:
                cache[(tuple(sorted(c.items())), SEARCH_SEED)] = H.gc_total(m)
    jobs, keys = [], []
    for an, b in arms.items():
        for s in HELDOUT:
            jobs.append((STRUCT, b, s, None, cycles, speeds, f"hv_{STRUCT}_{an}", False))
            keys.append((an, s))
    print(f"\nheld-out validation: {len(jobs)} runs on {len(HELDOUT)} seeds")
    res = H.evaluate_many(jobs, workers=8)
    ho = {}
    for (an, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        ho.setdefault(an, {})[s] = dict(gc=H.gc_total(m), riders=m["n_riders"],
                                        transfers=m["n_transfers"],
                                        incomplete=m["n_incomplete"],
                                        cycles=m["cycles_C"],
                                        maxconc=m["max_concurrent_total"],
                                        boardings=m["boardings"])
    out = dict(structure=STRUCT, budget=BUDGET, allocations=arms,
               search_seed=SEARCH_SEED, heldout_seeds=HELDOUT,
               eval_budget=EVAL_CAP, evals_used=bud.n,
               greedy_trace=trace, swaps=swaps, in_sample={})
    print("\n%-14s %14s %14s %14s %10s" % ("arm", "in-sample", "held-out mean",
                                           "held-out sd", "overfit gap"))
    for an, b in arms.items():
        vs = [v["gc"] for v in ho[an].values()]
        ins = cache.get((tuple(sorted(b.items())), SEARCH_SEED))
        out["in_sample"][an] = ins
        gap = (ins - st.mean(vs)) / st.mean(vs) * 100 if ins else None
        print("%-14s %14.2f %14.2f %14.3f %9s" % (
            an, (ins or 0)/3600, st.mean(vs)/3600, st.pstdev(vs)/3600,
            f"{gap:+.2f}%" if gap is not None else "n/a"))
    out["heldout"] = {an: {str(s): v for s, v in d.items()} for an, d in ho.items()}
    out["heldout_stats"] = {an: dict(mean=st.mean([v["gc"] for v in d.values()]),
                                     sd=st.pstdev([v["gc"] for v in d.values()]),
                                     riders=st.mean([v["riders"] for v in d.values()]),
                                     transfers=st.mean([v["transfers"] for v in d.values()]),
                                     incomplete=st.mean([v["incomplete"] for v in d.values()]))
                           for an, d in ho.items()}
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
