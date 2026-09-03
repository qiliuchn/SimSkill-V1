"""Parallel batch runner: each replication gets its OWN run directory (so no two
workers can overwrite each other's tripinfo/summary output)."""
import os
from concurrent.futures import ProcessPoolExecutor

import dt_scenario as S

WORK = os.environ.get(
    "DT_WORK",
    "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_20-30-00/attempts/attempt-1/runs")


def _one(job):
    tag, net, n_total, p, seed, feedback, rule_kw = job
    rd = os.path.join(WORK, tag)
    r = S.simulate(rd, net, n_total, p, seed, feedback=feedback, **rule_kw)
    r["tag"] = tag
    r["run_dir"] = rd
    return r


def run_batch(jobs, workers=8):
    if workers <= 1 or len(jobs) == 1:
        return [_one(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        return list(ex.map(_one, jobs))


def mean_ci(xs):
    """mean and half-width of a 95% t-CI."""
    import statistics
    xs = [x for x in xs if x == x]
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    sd = statistics.stdev(xs)
    tcrit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
             8: 2.365, 9: 2.306, 10: 2.262}.get(n, 1.96)
    return m, tcrit * sd / (n ** 0.5)


def eval_point(net, n_total, p, seeds, feedback=True, tagbase="pt", rule_kw=None,
               workers=8):
    """Run `len(seeds)` replications of one (net, N, p) point under Common Random
    Numbers and return the replication-averaged costs plus CI half-widths."""
    rule_kw = rule_kw or {}
    jobs = [(f"{tagbase}_s{sd}", net, n_total, p, sd, feedback, rule_kw) for sd in seeds]
    res = run_batch(jobs, workers=workers)
    out = {}
    for k in ("car_cost", "transit_cost", "transit_wait", "transit_ivt", "car_duration",
              "car_departdelay", "gap", "person_hours"):
        m, h = mean_ci([r[k] for r in res])
        out[k] = m
        out[k + "_ci"] = h
    out["headway"] = res[0]["headway"]
    out["headway_realised"] = res[0]["headway_realised"]
    out["n_car"] = res[0]["n_car"]
    out["n_transit"] = res[0]["n_transit"]
    out["n_buses_sched"] = res[0]["n_buses_sched"]
    out["n_car_arrived"] = sum(r["n_car_arrived"] for r in res) / len(res)
    out["n_transit_arrived"] = sum(r["n_transit_arrived"] for r in res) / len(res)
    out["n_person_no_ride"] = sum(r["n_person_no_ride"] for r in res)
    out["p_car"] = p
    out["n_total"] = n_total
    out["feedback"] = feedback
    out["net"] = os.path.basename(net)
    out["reps"] = len(seeds)
    out["_runs"] = res
    return out
