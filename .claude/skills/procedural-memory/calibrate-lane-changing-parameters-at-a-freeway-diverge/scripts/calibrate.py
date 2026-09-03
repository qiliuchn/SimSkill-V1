#!/usr/bin/env python3
"""STEP 4 -- simulation-in-the-loop CALIBRATION of the surviving LC2013
parameters against the weighted per-lane-flow + spatial-mandatory-LC objective.

Two optimisers on an identical objective, identical CRN seed list and identical
budget accounting (the discipline of
`calibrate-car-following-parameters-against-field-targets`):
  ga : generational GA (elitism, tournament selection, BLX-alpha) -- population
       parallel, saturates all cores.
  ps : multistart compass/pattern search advanced LOCK-STEP across restarts so
       every restart's trial points go into one parallel batch.  One restart is
       seeded at the SUMO defaults, so the optimiser is never worse-informed
       than the uncalibrated model it must beat.

Every evaluated candidate is appended to calib_evals.jsonl -- that log is the
candidate pool the equifinality / identifiability analysis needs.

Usage: calibrate.py <arm: ga|ps|both> [free-param list, comma separated]
"""
import os, sys, json, math, random, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

NSEED = int(os.environ.get("LC_CAL_SEEDS", "3"))
SEEDS = tuple(1000 + 7 * i for i in range(NSEED))
EVLOG = os.path.join(L.TBL, "calib_evals.jsonl")


def make_p(free, u, base=None):
    p = dict(base or L.LC_DEFAULTS)
    for n, x in zip(free, u):
        lo, hi, _ = L.PARAM_SPACE[n]
        p[n] = lo + max(0.0, min(1.0, float(x))) * (hi - lo)
    return p


def batch(free, ulist, base, tag, ctx=None, log=True):
    plist = [make_p(free, u, base) for u in ulist]
    res = evaluate_runs(plist, seeds=SEEDS, ctx=ctx)
    if log:
        with open(EVLOG, "a") as f:
            for u, p, r in zip(ulist, plist, res):
                f.write(json.dumps(dict(
                    tag=tag, u=[float(x) for x in u],
                    params={k: p[k] for k in free},
                    obj=r["obj"], ok=r.get("ok", False),
                    rmsn_lane=r.get("rmsn_lane"), geh=r.get("geh"),
                    geh_max=r.get("geh_max"), share=r.get("share"),
                    dlc=r.get("dlc"), p85=r.get("p85"), p50=r.get("p50"),
                    fail_frac=r.get("fail_frac"), strat_rate=r.get("strat_rate"),
                    coop_rate=r.get("coop_rate"), flow=r.get("flow"),
                    teleports=r.get("teleports"), collisions=r.get("collisions"),
                    n_rep=NSEED)) + "\n")
    return res


# --------------------------------------------------------------------------
def run_ga(free, base, pop=20, gens=18, seed=7, ctx=None):
    rng = random.Random(seed)
    k = len(free)
    P = [[rng.random() for _ in range(k)] for _ in range(pop)]
    P[0] = L.params_to_unit(L.full_params(), free)          # SUMO defaults
    hist, best, bestu, nev = [], float("inf"), None, 0
    for g in range(gens):
        res = batch(free, P, base, "ga_g%d" % g, ctx)
        nev += len(P)
        sc = [r["obj"] for r in res]
        order = sorted(range(pop), key=lambda i: sc[i])
        if sc[order[0]] < best:
            best = sc[order[0]]; bestu = list(P[order[0]])
        hist.append(dict(gen=g, best_so_far=best, gen_best=sc[order[0]],
                         gen_mean=sum(sc) / len(sc), n_eval=nev))
        print("  [ga] gen %2d  best_so_far=%.5f  gen_best=%.5f  gen_mean=%.5f"
              % (g, best, sc[order[0]], sum(sc) / len(sc)))
        if g == gens - 1:
            break
        elite = [list(P[i]) for i in order[:3]]
        new = elite
        while len(new) < pop:
            def tour():
                a, b = rng.randrange(pop), rng.randrange(pop)
                return P[a] if sc[a] < sc[b] else P[b]
            x, y = tour(), tour()
            alpha = 0.3
            ch = []
            for i in range(k):
                lo, hi = min(x[i], y[i]), max(x[i], y[i])
                d = hi - lo
                ch.append(min(1.0, max(0.0, rng.uniform(lo - alpha * d,
                                                        hi + alpha * d))))
            for i in range(k):
                if rng.random() < 0.15:
                    ch[i] = min(1.0, max(0.0, ch[i] + rng.gauss(0, 0.12)))
            new.append(ch)
        P = new
    return dict(best_obj=best, best_u=bestu, hist=hist, n_eval=nev)


def run_ps(free, base, nstart=4, iters=14, seed=13, ctx=None):
    """Multistart compass search, advanced LOCK-STEP so all restarts' trial
    points are evaluated in one parallel batch per iteration."""
    rng = random.Random(seed)
    k = len(free)
    X = [L.params_to_unit(L.full_params(), free)]           # defaults
    X += [[rng.random() for _ in range(k)] for _ in range(nstart - 1)]
    step = [0.35] * nstart
    res0 = batch(free, X, base, "ps_init", ctx)
    F = [r["obj"] for r in res0]
    nev = nstart
    hist = []
    for it in range(iters):
        trials, own = [], []
        for s in range(nstart):
            if step[s] < 0.015:
                continue
            for i in range(k):
                for sg in (+1, -1):
                    u = list(X[s]); u[i] = min(1.0, max(0.0, u[i] + sg * step[s]))
                    if abs(u[i] - X[s][i]) < 1e-9:
                        continue
                    trials.append(u); own.append(s)
        if not trials:
            break
        res = batch(free, trials, base, "ps_it%d" % it, ctx)
        nev += len(trials)
        improved = [False] * nstart
        for u, s, r in zip(trials, own, res):
            if r["obj"] < F[s] - 1e-9:
                F[s] = r["obj"]; X[s] = u; improved[s] = True
        for s in range(nstart):
            if not improved[s]:
                step[s] *= 0.5
        b = min(F)
        hist.append(dict(it=it, best_so_far=b, n_eval=nev,
                         steps=list(step), F=list(F)))
        print("  [ps] it %2d  best=%.5f  n_eval=%d  steps=%s"
              % (it, b, nev, ["%.3f" % s for s in step]))
        if all(s < 0.015 for s in step):
            break
    i = min(range(nstart), key=lambda s: F[s])
    return dict(best_obj=F[i], best_u=X[i], all_F=F, all_X=X, hist=hist,
                n_eval=nev)


def main():
    arm = sys.argv[1] if len(sys.argv) > 1 else "both"
    free = (sys.argv[2].split(",") if len(sys.argv) > 2
            else list(L.LC_NAMES))
    base = dict(L.LC_DEFAULTS)
    print("free parameters:", free)
    print("CRN seeds:", SEEDS)
    out = {"free": free, "seeds": list(SEEDS)}
    t = time.time()
    if arm in ("ga", "both"):
        print("\n=== GA ===")
        out["ga"] = run_ga(free, base)
    if arm in ("ps", "both"):
        print("\n=== multistart pattern search ===")
        out["ps"] = run_ps(free, base)
    out["wall_s"] = time.time() - t

    cands = []
    for a in ("ga", "ps"):
        if a in out:
            cands.append((out[a]["best_obj"], out[a]["best_u"], a))
    cands.sort()
    bo, bu, ba = cands[0]
    bp = make_p(free, bu, base)
    out["best_arm"] = ba
    out["best_params"] = bp
    out["best_obj_search"] = bo

    # --- honest re-evaluation of the reported best with MANY seeds ---------
    BIG = tuple(2000 + 13 * i for i in range(12))
    rb = evaluate_runs([bp, L.full_params()], seeds=BIG)
    out["best_reeval_12seed"] = {k: v for k, v in rb[0].items() if k != "reps"}
    out["default_reeval_12seed"] = {k: v for k, v in rb[1].items() if k != "reps"}
    print("\nbest arm=%s  search obj=%.5f  ->  12-seed obj=%.5f"
          % (ba, bo, rb[0]["obj"]))
    print("default 12-seed obj=%.5f" % rb[1]["obj"])
    print("best params:", json.dumps(bp, indent=2))
    json.dump(out, open(os.path.join(L.TBL, "calibration.json"), "w"),
              indent=2, default=str)
    print("wrote", os.path.join(L.TBL, "calibration.json"),
          " wall=%.0fs" % out["wall_s"])


if __name__ == "__main__":
    main()
