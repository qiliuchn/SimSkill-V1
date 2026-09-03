#!/usr/bin/env python3
"""STEP 3 -- Morris elementary-effects GLOBAL SENSITIVITY SCREENING, done
BEFORE any optimisation, over the vType car-following parameter space.

Method: Morris (1991) with the Campolongo et al. (2007) mu* statistic.
  * p = 4 levels, Delta = p/(2(p-1)) = 2/3 in the unit hypercube
  * r trajectories, each of k+1 points, one coordinate moved per step
  * EE_i = (Y(x + Delta e_i) - Y(x)) / Delta        (Y already dimensionless)
  * mu*_i = mean |EE_i|  (overall influence, no cancellation)
    sigma_i = sd(EE_i)   (interaction / non-linearity)

Y is evaluated for EVERY FD feature separately (each normalised by its own
empirical target so the effects are comparable across features) AND for the
weighted-RMSN objective, so we can test H1's specific parameter->feature
mapping claims, not just an aggregate ranking.

Usage: morris.py <model> <r_trajectories>
"""
import os, sys, json, math, random
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import OUT, TARGETS, params_for, PARAM_SPACE
from evalpool import evaluate, unit_to_params

MODEL = sys.argv[1] if len(sys.argv) > 1 else "Krauss"
R = int(sys.argv[2]) if len(sys.argv) > 2 else 10
SEED = 42
P_LEVELS = 4
DELTA = P_LEVELS / (2.0 * (P_LEVELS - 1))    # 2/3

NAMES = params_for(MODEL)
K = len(NAMES)
rng = np.random.default_rng(20260803)

FEATS = ["v_free_kmh", "q_max", "k_crit", "k_jam", "w_kmh"]


def trajectory():
    """One Morris trajectory: k+1 points in [0,1]^k, one coord changed per step."""
    grid = np.arange(P_LEVELS) / (P_LEVELS - 1.0)          # 0,1/3,2/3,1
    base = rng.choice(grid[: P_LEVELS // 2] if P_LEVELS > 2 else grid, size=K)
    order = rng.permutation(K)
    signs = rng.choice([-1.0, 1.0], size=K)
    pts = [base.copy()]
    cur = base.copy()
    for j in order:
        step = DELTA * signs[j]
        nxt = cur[j] + step
        if nxt > 1.0 or nxt < 0.0:            # reflect to stay in the cube
            step = -step
            nxt = cur[j] + step
        cur = cur.copy(); cur[j] = min(max(nxt, 0.0), 1.0)
        pts.append(cur.copy())
    return np.array(pts), order, np.array(
        [pts[i + 1][order[i]] - pts[i][order[i]] for i in range(K)])


def main():
    trajs = [trajectory() for _ in range(R)]
    allpts, meta = [], []
    for t, (pts, order, steps) in enumerate(trajs):
        for i, u in enumerate(pts):
            allpts.append(u); meta.append((t, i))
    plist = [unit_to_params(MODEL, u, names=NAMES) for u in allpts]
    print("[morris] %s  k=%d params, r=%d trajectories, %d evaluations"
          % (MODEL, K, R, len(plist)))
    res = evaluate(MODEL, plist, seed=SEED)
    nfail = sum(1 for r in res if not r["ok"])
    print("[morris] failed evaluations: %d/%d" % (nfail, len(res)))

    # --- collect Y vectors ------------------------------------------------
    def Yvec(r):
        y = {"obj": r["obj"]}
        if r["ok"] and r["feat"]:
            for f in FEATS:
                v = r["feat"].get(f, float("nan"))
                y[f] = v / TARGETS[f]["target"] if v == v else float("nan")
        else:
            for f in FEATS:
                y[f] = float("nan")
        return y

    Y = [Yvec(r) for r in res]
    ee = {q: {n: [] for n in NAMES} for q in ["obj"] + FEATS}
    ptr = 0
    for t, (pts, order, steps) in enumerate(trajs):
        idx = list(range(ptr, ptr + K + 1)); ptr += K + 1
        for i in range(K):
            j = order[i]; d = steps[i]
            if abs(d) < 1e-9:
                continue
            for q in ["obj"] + FEATS:
                a, b = Y[idx[i]][q], Y[idx[i + 1]][q]
                if a == a and b == b:
                    ee[q][NAMES[j]].append((b - a) / d)

    table = {}
    for q in ["obj"] + FEATS:
        rows = []
        for n in NAMES:
            e = np.array(ee[q][n], dtype=float)
            if len(e) == 0:
                rows.append(dict(param=n, mu_star=float("nan"),
                                 mu=float("nan"), sigma=float("nan"), n=0))
                continue
            rows.append(dict(param=n, mu_star=float(np.mean(np.abs(e))),
                             mu=float(np.mean(e)), sigma=float(np.std(e, ddof=1))
                             if len(e) > 1 else 0.0, n=int(len(e))))
        rows.sort(key=lambda r: -(r["mu_star"] if r["mu_star"] == r["mu_star"] else -1))
        table[q] = rows

    outp = os.path.join(OUT, "tables", "morris_%s.json" % MODEL)
    json.dump(dict(model=MODEL, r=R, k=K, n_eval=len(plist), n_failed=nfail,
                   delta=DELTA, levels=P_LEVELS, table=table,
                   param_ranges={n: PARAM_SPACE[n][:3] for n in NAMES}),
              open(outp, "w"), indent=2)

    for q in ["obj"] + FEATS:
        print("\n--- %s : %s  (mu* = mean|EE|, sigma = sd(EE)) ---" % (MODEL, q))
        print("  %-16s %10s %10s %10s" % ("param", "mu*", "mu", "sigma"))
        for r in table[q]:
            print("  %-16s %10.4f %10.4f %10.4f" % (r["param"], r["mu_star"],
                                                    r["mu"], r["sigma"]))
    print("\nwrote", outp)


if __name__ == "__main__":
    main()
