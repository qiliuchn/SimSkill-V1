#!/usr/bin/env python3
"""Parallel evaluation pool for FD-probe evaluations.

One evaluation = one full ring FD probe (15 density cells) -> FD feature vector
-> weighted-RMSN objective.  Every evaluation of a given (model, seed) uses the
IDENTICAL seed => Common Random Numbers across the whole search, which is what
makes objective differences between candidates attributable to the parameters
rather than to simulation noise (see [[sumo-stochastic-variability-and-replication-design]]).
"""
import os, sys, json, hashlib, shutil
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import (fd_probe, objective, full_params, PARAM_SPACE,
                       params_for, RUNS, TARGETS)

NPROC = int(os.environ.get("CF_NPROC", "8"))
_CACHE = {}


def key_of(model, p, seed):
    s = model + "|" + str(seed) + "|" + "|".join(
        "%s=%.6f" % (k, p[k]) for k in sorted(p))
    return hashlib.md5(s.encode()).hexdigest()[:16]


def _one(job):
    model, p, seed, tag, targets, extra = job
    try:
        feat, cells = fd_probe(tag, model, p, seed=seed,
                               root=os.path.join(RUNS, "pool"))
        if feat is None:
            return tag, dict(ok=False, obj=3.0, feat=None,
                             err="fewer than 5 usable cells")
        o = objective(feat, targets=targets)
        return tag, dict(ok=True, obj=o["obj"], rmsn=o["rmsn"], feat=feat,
                         parts={k: v["rel_err"] for k, v in o["parts"].items()},
                         within={k: v["within_tol"] for k, v in o["parts"].items()},
                         geh_qmax=o["geh_qmax"])
    except Exception as e:
        return tag, dict(ok=False, obj=3.0, feat=None, err=repr(e))


def evaluate(model, plist, seed=42, targets=None, nproc=None, cache=True):
    """plist: list of full parameter dicts. Returns list of result dicts."""
    targets = targets or TARGETS
    jobs, out, idx = [], [None] * len(plist), {}
    for i, p in enumerate(plist):
        k = key_of(model, p, seed)
        if cache and k in _CACHE:
            out[i] = _CACHE[k]
            continue
        idx.setdefault(k, []).append(i)
        if len(idx[k]) == 1:
            jobs.append((model, p, seed, k, targets, None))
    if jobs:
        with ProcessPoolExecutor(max_workers=nproc or NPROC) as ex:
            for tag, res in ex.map(_one, jobs):
                if cache:
                    _CACHE[tag] = res
                for i in idx[tag]:
                    out[i] = res
    return out


def unit_to_params(model, u, fixed=None, names=None):
    """u: vector in [0,1]^k over `names` (default = all params of the model)."""
    names = names or params_for(model)
    p = full_params(model, fixed or {})
    for name, x in zip(names, u):
        lo, hi, _, _ = PARAM_SPACE[name]
        p[name] = lo + float(x) * (hi - lo)
    return p


def params_to_unit(model, p, names=None):
    names = names or params_for(model)
    return [(p[n] - PARAM_SPACE[n][0]) / (PARAM_SPACE[n][1] - PARAM_SPACE[n][0])
            for n in names]
