"""
Continuous vertical-queue (point-queue) surrogate + a direct EQUILIBRIUM SOLVER.

Why a solver rather than a day-to-day dynamic: this project verified experimentally (see
FINDINGS.md, "the equilibrium is a repelling fixed point") that the Vickrey departure-time
equilibrium is UNSTABLE under naive iterative day-to-day adjustment -- started exactly at the
closed-form equilibrium, a proportional-swap / best-response dynamic drifts away from it,
because a queue's externality runs strictly forward in time. So the equilibrium is found by
minimising an explicit equilibrium GAP FUNCTION instead of by iterating a response map.

Equilibrium (Wardrop-type) conditions on departure slots:
    used slots      -> equal generalized cost
    unused slots    -> cost not lower than that common level
Gap function:
    G(n) = sum_k (n_k/N) * ((c_k - cbar)/cbar)^2   +   w_hinge * sum_k (max(0, cbar-c_k)/cbar)^2
G(n) = 0 exactly at an equilibrium. Minimising G needs no assumption about the SHAPE of the
solution and works for any toll profile and any schedule-delay function.

The queue itself is the textbook deterministic vertical queue at the MEASURED capacity s and
MEASURED free-flow time Tf; every SUMO effect it omits is absorbed by an additive per-slot
correction learned from real SUMO runs in the outer loop (equilibrate_hybrid.py).
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *

DT = 1.0
T0 = SLOT0 - 200.0
T1 = SLOT0 + NSLOT * SLOT + 1200.0
TGRID = np.arange(T0, T1, DT)


def queue_delay_curve(n, s, tf):
    """Vertical-queue delay experienced by a vehicle REACHING THE BOTTLENECK at each time.

    n is a (real-valued) per-departure-slot count vector. Departures inside a slot are
    uniform, so the arrival rate at the bottleneck is the departure rate shifted by tf.
    Q(t+dt) = max(0, Q(t) + (inflow - s)*dt) ;  delay(t) = Q(t)/s.
    """
    st = slot_starts()
    inflow = np.zeros(len(TGRID))
    idx = np.clip(((st + tf - T0) / DT).astype(int), 0, len(TGRID) - 1)
    per_step = np.asarray(n, float) / (SLOT / DT)
    span = int(SLOT / DT)
    for j in range(span):
        np.add.at(inflow, np.minimum(idx + j, len(TGRID) - 1), per_step)
    net = (inflow - s) * DT
    Q = np.maximum.accumulate(np.concatenate([[0.0], np.cumsum(net)]))[1:] - np.cumsum(net)
    # the recursion Q_t = max(0, Q_{t-1} + net_t) equals cumsum(net) - running min(0, cumsum)
    cs = np.cumsum(net)
    Q = cs - np.minimum.accumulate(np.minimum(cs, 0.0))
    return np.maximum(Q, 0.0) / s


def slot_cost(n, s, tf, toll, corr, beta=BETA, gamma=GAMMA, alpha=ALPHA, t_star=T_STAR):
    """Generalized cost of departing in each slot, given the aggregate profile n."""
    d = queue_delay_curve(n, s, tf)
    mid = slot_starts() + SLOT / 2.0
    i = np.clip(((mid + tf - T0) / DT).astype(int), 0, len(TGRID) - 1)
    q = d[i]
    a = mid + tf + q
    return (alpha * (tf + q) + beta * np.maximum(0.0, t_star - a)
            + gamma * np.maximum(0.0, a - t_star) + np.asarray(toll) + np.asarray(corr)), q, a


def gap_function(n, s, tf, toll, corr, beta=BETA, gamma=GAMMA, w_hinge=1.0, N=N_COMMUTERS):
    c, q, a = slot_cost(n, s, tf, toll, corr, beta, gamma)
    w = np.maximum(n, 0.0)
    if w.sum() <= 0:
        return 1e9
    cbar = float(np.average(c, weights=w))
    g1 = float(np.sum(w / w.sum() * ((c - cbar) / cbar) ** 2))
    g2 = float(np.sum(np.maximum(0.0, (cbar - c) / cbar) ** 2))
    return g1 + w_hinge * g2


def solve_equilibrium(s, tf, toll, corr, N=N_COMMUTERS, beta=BETA, gamma=GAMMA,
                      x0=None, restarts=3, maxiter=1200, w_hinge=1.0, seed=0):
    """Minimise the gap function over the simplex via a softmax parameterisation."""
    from scipy.optimize import minimize
    st = slot_starts()
    rng = np.random.default_rng(seed)

    def unpack(x):
        z = x - x.max()
        e = np.exp(z)
        return N * e / e.sum()

    def obj(x):
        return gap_function(unpack(x), s, tf, toll, corr, beta, gamma, w_hinge, N)

    starts = []
    if x0 is not None:
        starts.append(np.asarray(x0, float))
    base = np.where((st >= 2000) & (st < 4200), 0.0, -6.0)
    starts.append(base)
    for r in range(restarts):
        starts.append(base + rng.normal(0, 1.5, NSLOT))
    best, bestf = None, np.inf
    for x in starts:
        res = minimize(obj, x, method="L-BFGS-B",
                       options=dict(maxiter=maxiter, maxfun=200000, ftol=1e-14, gtol=1e-12))
        if res.fun < bestf:
            bestf, best = res.fun, res.x
    n = unpack(best)
    c, q, a = slot_cost(n, s, tf, toll, corr, beta, gamma)
    keep = n > 0.05
    cbar = float(np.average(c, weights=n))
    info = dict(gap_function=float(bestf), mean_cost=cbar,
                cost_gap_rel=float((c[keep].max() - c[keep].min()) / cbar),
                cost_sd_rel=float(np.sqrt(np.average((c[keep] - cbar) ** 2,
                                                     weights=n[keep])) / cbar),
                n_support=int(keep.sum()),
                min_cost_all_slots=float(c.min()),
                x=best.tolist())
    return n, c, q, info


if __name__ == "__main__":
    import json
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    s, tf = cap["capacity_vps"], cap["free_flow"]["tf_mean"]
    z = np.zeros(NSLOT)
    an = vickrey_analytic(N_COMMUTERS, s, tf)
    print("analytic  : t_s=%.0f t_e=%.0f meanCost=%.1f Tmax=%.0f"
          % (an["t_first_depart"], an["t_last_depart"],
             an["excess_cost_per_traveller"] + tf, an["max_queue_delay"]))
    n, c, q, info = solve_equilibrium(s, tf, z, z)
    st = slot_starts()
    u = np.where(n > 0.05)[0]
    print("solver    : meanCost=%.1f gap=%.5f sd=%.5f G=%.3e support=%d win=[%d..%d] maxQ=%.0f"
          % (info["mean_cost"], info["cost_gap_rel"], info["cost_sd_rel"],
             info["gap_function"], info["n_support"], st[u[0]], st[u[-1]] + SLOT, q.max()))
    print("  rate profile (veh/h) every 4 slots:")
    for k in u[::4]:
        print("    t=%5.0f  n=%5.2f  rate=%6.0f  cost=%7.1f  Q=%6.1f" %
              (st[k], n[k], n[k] / SLOT * 3600, c[k], q[k]))
