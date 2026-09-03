#!/usr/bin/env python3
"""
Outer loop (a): exhaustively evaluate all 2^10 = 1024 project subsets at DUE.

Every subset is evaluated with the identical trip file, the identical warm-start
route file, identical duaIterate settings and identical simulation-of-record
seed (Common Random Numbers).  Results are appended to work/enum.jsonl so the
run is resumable.
"""
import os, sys, json, time, shutil, argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import write_trips, subset_cost, subset_from_mask, NPROJ
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "enum")
OUT = os.path.join(ROOT, "outputs")
JSONL = os.path.join(ROOT, "work", "enum.jsonl")
TRIPS = os.path.join(ROOT, "work", "trips_main.xml")
WARM = os.path.join(ROOT, "work", "base_equilibrium.rou.xml.gz")
_DEPARTS = None


def job(mask):
    global _DEPARTS
    if _DEPARTS is None:
        _DEPARTS = EV.parse_trip_departs(TRIPS)
    wd = os.path.join(WORK, "m%04d" % mask)
    shutil.rmtree(wd, ignore_errors=True)
    try:
        r = EV.score(mask, TRIPS, wd, seed=1, warm_routes=None,
                     last_step=EV.COLD_STEPS, departs=_DEPARTS)
        r["error"] = None
    except Exception as e:
        r = dict(mask=mask, error=repr(e)[:400])
    r["cost"] = subset_cost(mask)
    r["subset"] = subset_from_mask(mask)
    shutil.rmtree(wd, ignore_errors=True)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nveh", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--masks", default="all")
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(TRIPS):
        write_trips(a.nveh, TRIPS)

    done = set()
    if os.path.exists(JSONL):
        with open(JSONL) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("error") is None:
                        done.add(d["mask"])
                except Exception:
                    pass
    if a.masks == "all":
        universe = list(range(1 << NPROJ))
    elif a.masks == "planned":
        # Cold-starting each equilibrium costs ~85 s of CPU, so a full 1024-subset
        # enumeration is ~7.7 h of wall clock here.  The task's documented
        # fallback is used instead:
        #   (1) EVERY budget-feasible subset up to the largest budget level
        #       studied (cost <= MAX_BUDGET) -- this makes the budget-constrained
        #       optimum EXACT at every budget level, which is all the GA
        #       validation needs, since the GA's penalised decoder can never
        #       return an infeasible design;
        #   (2) every singleton and every pair (the interaction matrix), even the
        #       ones that are budget-infeasible;
        #   (3) a documented uniform random sample of the remaining subsets.
        import random as _r
        MAX_BUDGET = 15.0
        SAMPLE_N = 40
        SAMPLE_SEED = 424242
        core = {m for m in range(1 << NPROJ) if subset_cost(m) <= MAX_BUDGET}
        core |= {1 << k for k in range(NPROJ)}
        core |= {(1 << i) | (1 << j) for i in range(NPROJ) for j in range(i + 1, NPROJ)}
        core.add(0)
        rest = sorted(set(range(1 << NPROJ)) - core)
        sample = _r.Random(SAMPLE_SEED).sample(rest, min(SAMPLE_N, len(rest)))
        universe = sorted(core) + sorted(sample)
        with open(os.path.join(ROOT, "work", "enumeration_scope.json"), "w") as f:
            json.dump(dict(max_budget=MAX_BUDGET, n_feasible_core=len(core),
                           n_random_sample=len(sample), sample_seed=SAMPLE_SEED,
                           n_total_evaluated=len(universe),
                           n_full_space=1 << NPROJ,
                           random_sample_masks=sorted(sample)), f, indent=2)
        print("planned scope: %d budget-feasible/pairs/singletons + %d random "
              "sample = %d of 1024" % (len(core), len(sample), len(universe)))
    else:
        universe = [int(x) for x in a.masks.split(",")]
    # submit in increasing project count so the singletons and pairs (the
    # interaction matrix and the paradox screen) land first
    todo = sorted((m for m in universe if m not in done),
                  key=lambda m: (bin(m).count("1"), m))
    print("todo=%d (already done %d)" % (len(todo), len(done)), flush=True)
    t0 = time.time(); n = 0
    with open(JSONL, "a") as fh, ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(job, m): m for m in todo}
        for fu in as_completed(futs):
            r = fu.result()
            fh.write(json.dumps(r) + "\n"); fh.flush()
            n += 1
            if n % 25 == 0 or n == len(todo):
                el = time.time() - t0
                print("%d/%d  %.1f min elapsed, %.1f min remaining (%.2f s/eval wall)"
                      % (n, len(todo), el / 60, el / n * (len(todo) - n) / 60, el / n),
                      flush=True)
    print("DONE in %.1f min" % ((time.time() - t0) / 60))


if __name__ == "__main__":
    main()
