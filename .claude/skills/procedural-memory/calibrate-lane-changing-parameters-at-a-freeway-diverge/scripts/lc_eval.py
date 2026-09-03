#!/usr/bin/env python3
"""Parallel evaluation pool for LC2013 parameter vectors.

One evaluation = one full diverge run -> raw SUMO output -> feature vector ->
weighted objective, averaged over `seeds` Common-Random-Number replications.
The SAME seed list is used for every candidate (CRN), so objective differences
between candidates are attributable to the parameters rather than to simulation
noise (see [[sumo-stochastic-variability-and-replication-design]] and the
`quantify-sumo-run-to-run-variability` skill).

Structure mirrors `calibrate-car-following-parameters-against-field-targets`'s
scripts/evalpool.py (same cache-key / ProcessPoolExecutor / failure-penalty
design); only the inner simulation and feature extractor are LC-specific.
"""
import os, sys, json, hashlib, shutil, multiprocessing
from concurrent.futures import ProcessPoolExecutor
# macOS defaults to the "spawn" start method, which re-imports the driver module
# in every worker and crashes any script without an __main__ guard.  Every job
# here is a self-contained subprocess call, so "fork" is both safe and cheaper.
MPCTX = multiprocessing.get_context("fork")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L

NPROC = int(os.environ.get("LC_NPROC", "9"))
FAIL_OBJ = 3.0
_CACHE = {}


def key_of(p, seed, ctx):
    s = str(seed) + "|" + json.dumps(ctx, sort_keys=True) + "|" + "|".join(
        "%s=%.6f" % (k, p[k]) for k in sorted(p))
    return hashlib.md5(s.encode()).hexdigest()[:16]


def _one(job):
    p, seed, tag, ctx, want_profiles, keep = job
    wd = os.path.join(L.RUNS, "pool", tag)
    # keys prefixed with "_" configure the OBJECTIVE, the rest configure the RUN
    okw = {k[1:]: v for k, v in ctx.items() if k.startswith("_")}
    rkw = {k: v for k, v in ctx.items() if not k.startswith("_")}
    if "target_lane" in okw and okw["target_lane"] is not None:
        okw["target_lane"] = {int(k): float(v)
                              for k, v in okw["target_lane"].items()}
    try:
        r = L.run_scenario(wd, p, seed=seed, **rkw)
        if r.returncode != 0:
            return tag, dict(ok=False, obj=FAIL_OBJ,
                             err="sumo rc=%d %s" % (r.returncode, r.stderr[-300:]))
        t0 = rkw.get("t0", L.WARMUP); t1 = rkw.get("t1", L.T_END_MEAS)
        f = L.extract_features(wd, t0, t1, want_profiles=want_profiles)
        o = L.objective(f, **okw)
        res = dict(ok=True, obj=o["obj"], rmsn_lane=o["rmsn_lane"],
                   geh=o["geh"], geh_max=o["geh_max"], e_dlc=o["e_dlc"],
                   e_p85=o["e_p85"], e_fail=o["e_fail"],
                   share=[f["share_ld"].get(i, float("nan")) for i in range(3)],
                   share_e1=[f["share_e1"].get(i, float("nan")) for i in range(3)],
                   dlc=f["dlc"], coop_rate=f["coop_rate"], strat_rate=f["strat_rate"],
                   p85=f["p85"], p50=f["p50"], p15=f["p15"],
                   fail_frac=f["fail_frac"], n_failed=f["n_failed"],
                   n_cohort=f["n_cohort"], n_nochange=f["n_nochange"],
                   flow=f["flow_station_vph"], reason_counts=f["reason_counts"],
                   reason_counts_B=f["reason_counts_B"],
                   teleports=f["teleports"], tel_wrong=f["teleports_wrong_lane"],
                   collisions=f["collisions"], not_inserted=f["not_inserted"],
                   depart_delay=f["depart_delay"], ramp_entered=f["ramp_entered"],
                   E_entered=f["E_entered"], veh_B=f["veh_B"],
                   running_end=f["running_end"], ended_total=f["ended_total"],
                   halting_end=f["halting_end"], loaded=f["loaded"],
                   inserted=f["inserted"],
                   ex_lane0_station=f["exiter_lane0_at_station"],
                   th_lane0_station=f["through_lane0_at_station"], wd=wd)
        if want_profiles:
            res["d_last_sorted"] = f["d_last_sorted"]
            res["arrive_curve"] = f["arrive_curve"]
        if not keep:
            shutil.rmtree(wd, ignore_errors=True)
        return tag, res
    except Exception as e:
        return tag, dict(ok=False, obj=FAIL_OBJ, err=repr(e))


def evaluate_runs(plist, seeds=(11,), ctx=None, nproc=None, cache=True,
                  want_profiles=False, keep=False):
    """plist: list of param dicts. Returns list (len(plist)) of dicts with the
    per-seed results and the CRN mean objective."""
    ctx = dict(ctx or {})
    jobs, idx = [], {}
    flat = [None] * (len(plist) * len(seeds))
    for i, p in enumerate(plist):
        for j, s in enumerate(seeds):
            k = key_of(p, s, ctx)
            n = i * len(seeds) + j
            if cache and k in _CACHE:
                flat[n] = _CACHE[k]
                continue
            idx.setdefault(k, []).append(n)
            if len(idx[k]) == 1:
                jobs.append((p, s, k, ctx, want_profiles, keep))
    if jobs:
        with ProcessPoolExecutor(max_workers=nproc or NPROC, mp_context=MPCTX) as ex:
            for tag, res in ex.map(_one, jobs):
                if cache:
                    _CACHE[tag] = res
                for n in idx[tag]:
                    flat[n] = res
    out = []
    for i in range(len(plist)):
        reps = flat[i * len(seeds):(i + 1) * len(seeds)]
        ok = [r for r in reps if r.get("ok")]
        if not ok:
            out.append(dict(ok=False, obj=FAIL_OBJ, reps=reps))
            continue
        def mean(k):
            v = [r[k] for r in ok if r.get(k) is not None and r[k] == r[k]]
            return sum(v) / len(v) if v else float("nan")
        agg = dict(ok=True, n_ok=len(ok), n_rep=len(reps), reps=reps)
        for k in ("obj", "rmsn_lane", "geh_max", "dlc", "coop_rate", "strat_rate",
                  "p85", "p50", "p15", "fail_frac", "flow", "teleports",
                  "collisions", "not_inserted", "depart_delay", "n_cohort",
                  "n_nochange", "e_dlc", "e_p85", "e_fail", "tel_wrong",
                  "ramp_entered", "E_entered", "veh_B", "ex_lane0_station",
                  "th_lane0_station", "running_end", "ended_total",
                  "halting_end", "loaded", "inserted"):
            agg[k] = mean(k)
        agg["share"] = [sum(r["share"][i] for r in ok) / len(ok) for i in range(3)]
        agg["geh"] = [sum(r["geh"][i] for r in ok) / len(ok) for i in range(3)]
        out.append(agg)
    return out


def evaluate(plist, seeds=(11,), ctx=None, **kw):
    return evaluate_runs(plist, seeds=seeds, ctx=ctx, **kw)
