#!/usr/bin/env python3
"""STEP 4 -- simulation-in-the-loop CALIBRATION of the influential car-following
parameters, comparing TWO search strategies on the identical objective, budget
accounting and CRN seed.

Optimiser A : generational GA with elitism + tournament selection + BLX-alpha
              crossover + gaussian mutation.  Population-parallel (8 workers).
              (encoding/elitism/convergence-logging conventions reused from
               `optimize-signal-plan-with-simulation-in-the-loop-ga`)
Optimiser B : MULTISTART Nelder-Mead (Latin-hypercube starts, bound-reflected).
              Each restart is serial, restarts run in parallel.  Multistart is
              also what produces the candidate pool used for the H3
              equifinality test.

Objective   : weighted RMSN over the 5 FD features vs the empirical target
              vector (cf_common.TARGETS), one CRN seed for every evaluation.

Usage: calibrate.py <model> [tag] [--targets synthetic.json] [--features f1,f2]
"""
import os, sys, json, time, math, random
import numpy as np
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import OUT, TARGETS, PARAM_SPACE, params_for, full_params, RUNS
from evalpool import evaluate, unit_to_params, params_to_unit, _one, key_of

SEED = 42
NPROC = int(os.environ.get("CF_NPROC", "8"))

# ---- reduced (INFLUENTIAL) parameter sets, chosen from the Morris screening --
# Rule: keep a parameter if mu*_obj >= 25% of the largest mu*_obj, OR if it is
# the dominant, near-linear (mu == mu*, small sigma) control of a single target
# feature that nothing else controls monotonically.  speedFactor is retained by
# the second clause (it is the only non-cancelling control on v_free).
INFLUENTIAL = {
    "Krauss": ["tau", "decel", "minGap", "apparentDecel", "sigma", "length",
               "speedFactor"],
    "IDM":    ["tau", "minGap", "decel", "accel", "length", "delta",
               "speedFactor"],
}
FIXED_AT_DEFAULT = {
    "Krauss": ["accel", "speedDev", "emergencyDecel"],
    "IDM":    ["speedDev"],
}


def make_eval(model, names, seed, targets, log):
    def f(units):
        plist = [unit_to_params(model, u, names=names) for u in units]
        res = evaluate(model, plist, seed=seed, targets=targets, nproc=NPROC)
        for u, p, r in zip(units, plist, res):
            log.append(dict(u=[float(x) for x in u],
                            p={k: float(v) for k, v in p.items()},
                            obj=r["obj"], ok=r["ok"],
                            feat=r.get("feat")))
        return [r["obj"] for r in res]
    return f


# ------------------------------------------------------------------ GA -------
def run_ga(model, names, targets, pop=24, gens=18, seed=SEED, rng_seed=7):
    rng = np.random.default_rng(rng_seed)
    k = len(names)
    log = []
    ev = make_eval(model, names, seed, targets, log)
    X = rng.random((pop, k))
    F = ev(list(X))
    hist = []
    n_eval = pop
    t0 = time.time()
    for g in range(gens):
        order = np.argsort(F)
        X, F = X[order], [F[i] for i in order]
        hist.append(dict(gen=g, best=float(F[0]), mean=float(np.mean(F)),
                         n_eval=n_eval, t=time.time() - t0))
        elite = 2
        newX = [X[i].copy() for i in range(elite)]
        while len(newX) < pop:
            def tour():
                c = rng.integers(0, pop, 3)
                return X[min(c, key=lambda i: F[i])]
            a, b = tour(), tour()
            al = 0.4
            lo = np.minimum(a, b) - al * np.abs(a - b)
            hi = np.maximum(a, b) + al * np.abs(a - b)
            child = rng.uniform(lo, hi)
            m = rng.random(k) < 0.25
            child[m] += rng.normal(0, 0.15, int(m.sum()))
            newX.append(np.clip(child, 0.0, 1.0))
        X = np.array(newX[:pop])
        F = ev(list(X)); n_eval += pop
    order = np.argsort(F)
    X, F = X[order], [F[i] for i in order]
    hist.append(dict(gen=gens, best=float(F[0]), mean=float(np.mean(F)),
                     n_eval=n_eval, t=time.time() - t0))
    return dict(best_u=[float(x) for x in X[0]], best_obj=float(F[0]),
                n_eval=n_eval, wall_s=time.time() - t0, history=hist, log=log)


# --------------------------------------------------- Nelder-Mead (1 restart) --
def _nm_worker(job):
    model, names, targets, seed, x0, maxfev = job
    log = []
    cache = {}

    def f(x):
        x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
        kk = tuple(np.round(x, 6))
        if kk in cache:
            return cache[kk]
        p = unit_to_params(model, x, names=names)
        _, r = _one((model, p, seed, key_of(model, p, seed), targets, None))
        cache[kk] = r["obj"]
        log.append(dict(u=[float(v) for v in x],
                        p={a: float(b) for a, b in p.items()},
                        obj=r["obj"], ok=r["ok"], feat=r.get("feat")))
        return r["obj"]

    from scipy.optimize import minimize
    res = minimize(f, np.asarray(x0, dtype=float), method="Nelder-Mead",
                   options=dict(maxfev=maxfev, xatol=1e-3, fatol=1e-4,
                                adaptive=True))
    return dict(best_u=[float(v) for v in np.clip(res.x, 0, 1)],
                best_obj=float(res.fun), n_eval=len(log), log=log)


def run_nm_multistart(model, names, targets, n_start=6, maxfev=110, seed=SEED,
                      rng_seed=11):
    rng = np.random.default_rng(rng_seed)
    k = len(names)
    # Latin hypercube starts (one of them = SUMO defaults, so the optimiser is
    # never worse-informed than the uncalibrated model it must beat)
    lh = (rng.permutation(np.tile(np.arange(n_start), (k, 1)).T).astype(float)
          + rng.random((n_start, k))) / n_start
    starts = [np.array(params_to_unit(model, full_params(model), names=names))]
    starts += [lh[i] for i in range(n_start - 1)]
    jobs = [(model, names, targets, seed, s, maxfev) for s in starts]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=min(NPROC, n_start)) as ex:
        outs = list(ex.map(_nm_worker, jobs))
    wall = time.time() - t0
    best = min(outs, key=lambda o: o["best_obj"])
    return dict(best_u=best["best_u"], best_obj=best["best_obj"],
                n_eval=sum(o["n_eval"] for o in outs), wall_s=wall,
                restarts=[dict(best_u=o["best_u"], best_obj=o["best_obj"],
                               n_eval=o["n_eval"]) for o in outs],
                log=[e for o in outs for e in o["log"]])


# ------------------------------------------------------------------ main -----
def main():
    model = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else "main"
    targets = TARGETS
    if "--targets" in sys.argv:
        targets = json.load(open(sys.argv[sys.argv.index("--targets") + 1]))
    names = INFLUENTIAL[model]
    print("[cal] %s/%s  free params: %s   fixed: %s"
          % (model, tag, names, FIXED_AT_DEFAULT[model]))

    ga = run_ga(model, names, targets)
    print("[cal] GA   best=%.5f  evals=%d  wall=%.1fs"
          % (ga["best_obj"], ga["n_eval"], ga["wall_s"]))
    nm = run_nm_multistart(model, names, targets)
    print("[cal] NMms best=%.5f  evals=%d  wall=%.1fs"
          % (nm["best_obj"], nm["n_eval"], nm["wall_s"]))

    out = dict(model=model, tag=tag, names=names,
               fixed=FIXED_AT_DEFAULT[model], seed=SEED,
               targets={k: v["target"] for k, v in targets.items()},
               ga={k: v for k, v in ga.items() if k != "log"},
               nm={k: v for k, v in nm.items() if k != "log"},
               ga_best_params=unit_to_params(model, ga["best_u"], names=names),
               nm_best_params=unit_to_params(model, nm["best_u"], names=names))
    p = os.path.join(OUT, "tables", "calib_%s_%s.json" % (model, tag))
    json.dump(out, open(p, "w"), indent=2, default=float)
    # full evaluation log kept separately (large) -- needed for H3 equifinality
    lp = os.path.join(OUT, "tables", "callog_%s_%s.json" % (model, tag))
    json.dump(dict(ga=ga["log"], nm=nm["log"]), open(lp, "w"), default=float)
    print("wrote", p, "and", lp)
    for who, b in (("GA", out["ga_best_params"]), ("NM", out["nm_best_params"])):
        print("  %s best params: %s" % (who, {k: round(v, 4) for k, v in b.items()}))


if __name__ == "__main__":
    main()
