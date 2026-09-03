#!/usr/bin/env python3
"""Thread-pool wrapper around sim_common.fitness (each eval is its own `sumo`
subprocess, so threads are the right primitive) + a global, auditable counter of
how many SUMO runs have been consumed.  Every optimizer draws from the same
counter class so the "exactly 300 evaluations" budget is enforced, not assumed."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import sim_common as S

NWORK = int(os.environ.get("SIMOPT_WORKERS", "9"))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
os.makedirs(WORK, exist_ok=True)


class Budget:
    """Hard budget on SUMO evaluations. Raises when exhausted."""

    def __init__(self, limit, name="?"):
        self.limit = limit
        self.name = name
        self.used = 0
        self._lock = threading.Lock()

    def take(self, k=1):
        with self._lock:
            if self.used + k > self.limit:
                raise BudgetExhausted(f"{self.name}: budget {self.limit} exhausted "
                                      f"(used {self.used}, asked {k})")
            self.used += k
            return self.used

    def remaining(self):
        return self.limit - self.used


class BudgetExhausted(RuntimeError):
    pass


def eval_one(x, seed, budget=None):
    if budget is not None:
        budget.take(1)
    obj, m = S.fitness_vec(x, WORK, seed)
    return obj, m


def eval_many(jobs, budget=None, workers=NWORK):
    """jobs: list of (x_vector, seed). Returns list of (obj, metrics) in order."""
    if budget is not None:
        budget.take(len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(S.fitness_vec, x, WORK, s) for x, s in jobs]
        return [f.result() for f in futs]


def eval_addfile_many(jobs, workers=NWORK):
    """jobs: list of (add_file, seed) -- for the analytic baseline plan."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(S.fitness_addfile, a, WORK, s) for a, s in jobs]
        return [f.result() for f in futs]
