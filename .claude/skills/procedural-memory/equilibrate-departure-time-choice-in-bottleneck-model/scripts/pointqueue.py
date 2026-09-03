"""
A deterministic vertical-(point-)queue surrogate of the SUMO bottleneck, used ONLY as a
fast inner solver inside the outer loop. It is calibrated exclusively from independently
MEASURED quantities -- the discharge capacity `s` and the free-flow travel time `Tf` -- and
its accuracy against SUMO is reported, never assumed.

    arrival_j = max(depart_j + Tf, arrival_{j-1} + 1/s)      (FIFO, constant-rate server)

The outer loop (equilibrate_hybrid.py) corrects whatever this misses -- capacity drop at
the queue head, finite acceleration, vehicle length/storage, lane-changing -- with an
additive per-slot correction term learned from the real SUMO runs.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *


def simulate_point_queue(departs, s, tf):
    """departs: sorted array of departure times. Returns arrival times."""
    d = np.sort(np.asarray(departs, float))
    hw = 1.0 / s
    arr = np.empty_like(d)
    prev = -np.inf
    free = d + tf
    for j in range(len(d)):
        a = free[j] if free[j] > prev + hw else prev + hw
        arr[j] = a
        prev = a
    return arr


def slot_costs_pq(counts, s, tf, toll, correction, beta=BETA, gamma=GAMMA,
                  alpha=ALPHA, t_star=T_STAR):
    """Mean generalized cost per departure slot under the surrogate (+ learned correction)."""
    pairs = counts_to_departs(np.asarray(counts, int))
    if not pairs:
        return np.full(NSLOT, np.nan), np.zeros(NSLOT), np.zeros(NSLOT)
    t = np.array([p[0] for p in pairs])
    k = np.array([p[1] for p in pairs])
    a = simulate_point_queue(t, s, tf)
    q = a - t - tf
    cost = alpha * (a - t) + beta * np.maximum(0.0, t_star - a) \
        + gamma * np.maximum(0.0, a - t_star) + np.asarray(toll)[k]
    cnt = np.bincount(k, minlength=NSLOT).astype(float)
    csum = np.bincount(k, weights=cost, minlength=NSLOT)
    qsum = np.bincount(k, weights=q, minlength=NSLOT)
    mc = np.where(cnt > 0, csum / np.maximum(cnt, 1), np.nan) + np.asarray(correction)
    mq = np.where(cnt > 0, qsum / np.maximum(cnt, 1), np.nan)
    return mc, mq, cnt


def marginal_cost_all_slots(counts, s, tf, toll, correction, beta=BETA, gamma=GAMMA,
                            alpha=ALPHA, t_star=T_STAR):
    """Cost of a marginal traveller in EVERY slot: measured under the surrogate where the
    slot is used, and the exact no-queue counterfactual where it is not."""
    mc, mq, cnt = slot_costs_pq(counts, s, tf, toll, correction, beta, gamma, alpha, t_star)
    mid = slot_starts() + SLOT / 2.0
    used = np.where(cnt > 0)[0]
    if len(used):
        qh = np.interp(mid, mid[used], mq[used], left=0.0, right=0.0)
        qh[(mid < mid[used[0]]) | (mid > mid[used[-1]])] = 0.0
    else:
        qh = np.zeros(NSLOT)
    arr = mid + tf + qh
    cf = (alpha * (tf + qh) + beta * np.maximum(0.0, t_star - arr)
          + gamma * np.maximum(0.0, arr - t_star) + np.asarray(toll) + np.asarray(correction))
    return np.where(cnt > 0, mc, cf), mq, cnt


def swap_step(n, cost, phi, gain_pow=0.5, diffuse=0.03):
    n = np.asarray(n, float); tot = n.sum()
    w = n if n.sum() > 0 else np.ones_like(n)
    cbar = float(np.average(cost, weights=w))
    mad = float(np.average(np.abs(cost - cbar), weights=w))
    scale = max(2.0 * mad, 1e-9)
    excess = np.maximum(0.0, cost - cbar)
    deficit = np.maximum(0.0, cbar - cost)
    if excess.max() <= 0 or deficit.sum() <= 0:
        return n.copy()
    give = np.minimum(phi * n * np.minimum(1.0, excess / scale), n)
    moved = give.sum()
    gw = deficit ** gain_pow
    out = n - give + moved * (gw / gw.sum())
    if diffuse > 0:
        sm = np.copy(out)
        sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        out = (1 - diffuse) * out + diffuse * sm
    out = np.maximum(out, 0.0)
    return out / out.sum() * tot


def largest_remainder(x, total):
    x = np.maximum(np.asarray(x, float), 0.0)
    if x.sum() <= 0:
        x = np.ones_like(x)
    x = x * (total / x.sum())
    base = np.floor(x).astype(int)
    rem = int(total - base.sum())
    if rem > 0:
        base[np.argsort(-(x - base))[:rem]] += 1
    elif rem < 0:
        order = np.argsort(x - base)
        base[[i for i in order if base[i] > 0][:(-rem)]] -= 1
    return base


def equilibrate_surrogate(s, tf, toll, correction, N=N_COMMUTERS, iters=4000,
                          beta=BETA, gamma=GAMMA, init=None, phi=0.9, lam_exp=0.45,
                          verbose=False):
    """Solve the departure-time equilibrium of the SURROGATE to high precision."""
    st = slot_starts()
    n = (np.asarray(init, float).copy() if init is not None
         else largest_remainder(((st >= 2000) & (st < 4200)).astype(float), N).astype(float))
    for m in range(iters):
        counts = largest_remainder(n, N)
        cost, mq, cnt = marginal_cost_all_slots(counts, s, tf, toll, correction, beta, gamma)
        lam = 1.0 / (m + 1) ** lam_exp
        n = (1 - lam) * n + lam * swap_step(n, cost, phi)
    counts = largest_remainder(n, N)
    cost, mq, cnt = marginal_cost_all_slots(counts, s, tf, toll, correction, beta, gamma)
    u = np.where(cnt > 0)[0]
    cw = np.average(cost[u], weights=cnt[u])
    gap = (cost[u].max() - cost[u].min()) / cw
    sd = np.sqrt(np.average((cost[u] - cw) ** 2, weights=cnt[u])) / cw
    if verbose:
        print("   surrogate: used=%d meanCost=%.1f gap=%.4f sd=%.4f" % (len(u), cw, gap, sd))
    return counts, dict(mean_cost=float(cw), gap=float(gap), sd=float(sd),
                        n_used=int(len(u)), cost=cost.tolist(), cnt=cnt.tolist())


if __name__ == "__main__":
    import json
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    s, tf = cap["capacity_vps"], cap["free_flow"]["tf_mean"]
    an = vickrey_analytic(N_COMMUTERS, s, tf)
    print("analytic: t_s=%.0f t_e=%.0f meanCost=%.1f" %
          (an["t_first_depart"], an["t_last_depart"], an["excess_cost_per_traveller"] + tf))
    c, info = equilibrate_surrogate(s, tf, np.zeros(NSLOT), np.zeros(NSLOT), verbose=True)
    st = slot_starts(); u = np.where(c > 0)[0]
    print("   window [%d..%d] = %d s" % (st[u[0]], st[u[-1]] + SLOT, st[u[-1]] + SLOT - st[u[0]]))
