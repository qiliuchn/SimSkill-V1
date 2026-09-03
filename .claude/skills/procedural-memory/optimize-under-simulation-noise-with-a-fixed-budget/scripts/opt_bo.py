#!/usr/bin/env python3
"""STEP 4 (c): surrogate / Bayesian optimization under the same hard 300-run budget.

scikit-learn is not installed, so the Gaussian process is hand-rolled in
numpy/scipy: Matern-5/2 kernel with three grouped length-scales, a nugget for
simulation noise, Cholesky solves via scipy.linalg.cho_factor/cho_solve, and
hyperparameters fitted by maximising the (profiled) log marginal likelihood.

Two trend/mean functions -- the whole point of the analytical-metamodel question:
  const   : universal kriging basis H = [1]                (constant prior mean)
  webster : universal kriging basis H = [1, D_webster(x)]  (analytic delay trend)

Feature map handles the fact that offsets are PERIODIC, not monotone, in the
cycle ([[arterial-signal-progression-resonance-bandwidth-and-delay]]):
  z = [C/120, 5 scaled splits, cos(2*pi*o_i/effC_i), sin(2*pi*o_i/effC_i) x5]

Acquisition: Expected Improvement against the best posterior mean at an evaluated
point (the noisy-EI incumbent), maximised by multi-start random search.

usage: opt_bo.py const|webster
"""
import csv
import json
import os
import sys

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.spatial.distance import cdist
from scipy.stats import norm, qmc

import evalpool as EP
import sim_common as S
import webster_trend as WT

HERE = os.path.dirname(os.path.abspath(__file__))
MODE = sys.argv[1] if len(sys.argv) > 1 else "const"
BUDGET = int(os.environ.get("SIMOPT_BUDGET", "300"))
N_INIT = 40
SEARCH_SEED = 200          # the SAME frozen seed as GA-single: isolates SEARCH strategy
CKPT = 20
RNG = np.random.default_rng(12345)

LO = np.array(S.LO)
HI = np.array(S.HI)
NDIM = S.NDIM
K = len(S.TLS)


# ---------------------------------------------------------------- feature map
def features(X):
    X = np.atleast_2d(np.asarray(X, float))
    out = np.zeros((X.shape[0], 1 + K + 2 * K))
    for r, x in enumerate(X):
        C, plans, splits, offs = S.decode(S.to_genome(list(x)))
        out[r, 0] = C / 120.0
        out[r, 1:1 + K] = (np.array(splits) - S.SPLIT_MIN) / (S.SPLIT_MAX - S.SPLIT_MIN)
        for i, (tl, off, ph, effC) in enumerate(plans):
            th = 2 * np.pi * off / effC
            out[r, 1 + K + 2 * i] = np.cos(th)
            out[r, 1 + K + 2 * i + 1] = np.sin(th)
    return out


GROUP = np.array([0] + [1] * K + [2] * (2 * K))     # length-scale group per feature


def basis(X):
    X = np.atleast_2d(np.asarray(X, float))
    ones = np.ones((X.shape[0], 1))
    if MODE == "const":
        return ones
    d = np.array([WT.analytic_total_delay(x) for x in X]).reshape(-1, 1)
    return np.hstack([ones, d / 1e5])


# ---------------------------------------------------------------- GP machinery
def matern52(Z1, Z2, ls):
    w = ls[GROUP]
    D = cdist(Z1 / w, Z2 / w)
    a = np.sqrt(5.0) * D
    return (1.0 + a + a * a / 3.0) * np.exp(-a)


def nll(theta, Z, y, H):
    ls = np.exp(theta[:3])
    sf2 = np.exp(theta[3])
    sn2 = np.exp(theta[4])
    n = len(y)
    Kmat = sf2 * matern52(Z, Z, ls) + (sn2 + 1e-8) * np.eye(n)
    try:
        cf = cho_factor(Kmat, lower=True)
    except Exception:
        return 1e10
    Ki_y = cho_solve(cf, y)
    Ki_H = cho_solve(cf, H)
    A = H.T @ Ki_H
    try:
        beta = np.linalg.solve(A, H.T @ Ki_y)
    except np.linalg.LinAlgError:
        return 1e10
    r = y - H @ beta
    Ki_r = cho_solve(cf, r)
    logdet = 2.0 * np.sum(np.log(np.diag(cf[0])))
    sign, logdetA = np.linalg.slogdet(A)
    if sign <= 0:
        return 1e10
    return 0.5 * (r @ Ki_r) + 0.5 * logdet + 0.5 * logdetA      # REML


class GP:
    def __init__(self, X, y):
        self.Z = features(X)
        self.ymu, self.ysd = float(np.mean(y)), float(np.std(y) + 1e-9)
        self.y = (np.asarray(y, float) - self.ymu) / self.ysd
        self.H = basis(X)
        best, bestf = None, np.inf
        starts = [np.log([0.5, 0.7, 0.9, 1.0, 0.05]),
                  np.log([1.5, 1.5, 1.5, 1.0, 0.02]),
                  np.log([0.25, 0.35, 0.5, 1.0, 0.15])]
        for s in starts:
            try:
                r = minimize(nll, s, args=(self.Z, self.y, self.H), method="L-BFGS-B",
                             bounds=[(np.log(0.05), np.log(20))] * 3 +
                                    [(np.log(1e-3), np.log(1e3)), (np.log(1e-4), np.log(10))],
                             options={"maxiter": 120})
                if r.fun < bestf:
                    bestf, best = r.fun, r.x
            except Exception:
                pass
        if best is None:
            best = starts[0]
        self.theta = best
        self.ls = np.exp(best[:3]); self.sf2 = np.exp(best[3]); self.sn2 = np.exp(best[4])
        n = len(self.y)
        Kmat = self.sf2 * matern52(self.Z, self.Z, self.ls) + (self.sn2 + 1e-8) * np.eye(n)
        self.cf = cho_factor(Kmat, lower=True)
        self.Ki_y = cho_solve(self.cf, self.y)
        self.Ki_H = cho_solve(self.cf, self.H)
        self.A = self.H.T @ self.Ki_H
        self.beta = np.linalg.solve(self.A, self.H.T @ self.Ki_y)
        self.Ki_r = cho_solve(self.cf, self.y - self.H @ self.beta)

    def predict(self, X):
        Zs = features(X)
        Hs = basis(X)
        Ks = self.sf2 * matern52(Zs, self.Z, self.ls)
        mu = Hs @ self.beta + Ks @ self.Ki_r
        v = self.sf2 - np.einsum("ij,ij->i", Ks, cho_solve(self.cf, Ks.T).T)
        U = Hs - Ks @ self.Ki_H                          # universal-kriging correction
        v = v + np.einsum("ij,ij->i", U, np.linalg.solve(self.A, U.T).T)
        v = np.maximum(v, 1e-12)
        return mu * self.ysd + self.ymu, np.sqrt(v) * self.ysd


def candidates(X_obs, best_x, n_rand=3000, n_loc=1200):
    C = RNG.uniform(LO, HI, size=(n_rand, NDIM))
    if best_x is not None:
        span = (HI - LO)
        for scale in (0.03, 0.10, 0.25):
            P = np.array(best_x) + RNG.normal(0, scale, size=(n_loc // 3, NDIM)) * span
            C = np.vstack([C, np.clip(P, LO, HI)])
    return C


def main():
    budget = EP.Budget(BUDGET, name=f"BO-{MODE}")
    logf = open(os.path.join(HERE, f"log_bo_{MODE}.csv"), "w", newline="")
    w = csv.writer(logf)
    w.writerow(["eval_index", "phase", "seed", "objective", "best_so_far", "x"])

    # ---- space-filling initial design (Sobol, scrambled) -- the DoE sampling idea
    #      from `screen-and-decompose-sumo-parameter-sensitivity`
    sob = qmc.Sobol(d=NDIM, scramble=True, seed=2024)
    X = qmc.scale(sob.random(N_INIT), LO, HI)
    budget.take(N_INIT)
    res = EP.eval_many([(list(x), SEARCH_SEED) for x in X])
    y = np.array([r[0] for r in res])

    incumbents, eval_idx = [], 0
    best_score, best_x = np.inf, None
    for i in range(N_INIT):
        eval_idx += 1
        if y[i] < best_score:
            best_score, best_x = float(y[i]), list(X[i])
        w.writerow([eval_idx, "init", SEARCH_SEED, f"{y[i]:.2f}", f"{best_score:.2f}",
                    json.dumps([round(v, 4) for v in X[i]])])
        if eval_idx % CKPT == 0:
            incumbents.append({"evals": eval_idx, "x": list(best_x), "in_sample_score": best_score})
    logf.flush()
    print(f"[bo-{MODE}] init done  best={best_score:.1f}")

    gp = GP(X, y)
    refit_every = 10
    while budget.remaining() > 0:
        budget.take(1)
        Cand = candidates(X, best_x)
        mu, sd = gp.predict(Cand)
        mu_obs, _ = gp.predict(X)
        inc = float(np.min(mu_obs))                       # noisy-EI incumbent
        z = (inc - mu) / sd
        ei = (inc - mu) * norm.cdf(z) + sd * norm.pdf(z)
        xn = Cand[int(np.argmax(ei))]
        obj, m = EP.eval_one(list(xn), SEARCH_SEED)
        X = np.vstack([X, xn]); y = np.append(y, obj)
        eval_idx += 1
        if obj < best_score:
            best_score, best_x = float(obj), list(xn)
        w.writerow([eval_idx, "bo", SEARCH_SEED, f"{obj:.2f}", f"{best_score:.2f}",
                    json.dumps([round(v, 4) for v in xn])])
        if eval_idx % CKPT == 0:
            incumbents.append({"evals": eval_idx, "x": list(best_x), "in_sample_score": best_score})
            logf.flush()
            print(f"[bo-{MODE}] evals={eval_idx:4d}  best={best_score:10.1f}  "
                  f"ls={np.round(gp.ls,3)} sn2={gp.sn2:.4f}")
        if len(y) % refit_every == 0:
            gp = GP(X, y)

    logf.close()
    C, plans, splits, offs = S.decode(S.to_genome(best_x))
    out = {"method": f"bo_{MODE}", "evals_used": budget.used, "budget": BUDGET,
           "reps_per_design": 1, "search_seeds": [SEARCH_SEED],
           "designs_evaluated": budget.used, "n_init": N_INIT,
           "best_x": best_x, "in_sample_score": best_score,
           "gp_lengthscales": list(map(float, gp.ls)),
           "gp_signal_var": float(gp.sf2), "gp_noise_var_normalised": float(gp.sn2),
           "gp_beta": list(map(float, gp.beta)),
           "decoded": {"cycle": round(C, 1), "eff_cycles": [p[3] for p in plans],
                       "main_green_fraction": [round(v, 3) for v in splits],
                       "offsets": offs,
                       "green_main_s": [p[2][0][1] for p in plans],
                       "green_side_s": [p[2][2][1] for p in plans]},
           "incumbents": incumbents}
    json.dump(out, open(os.path.join(HERE, f"best_bo_{MODE}.json"), "w"), indent=2)
    print(f"[bo-{MODE}] DONE evals={budget.used} best in-sample={best_score:.1f}")
    print(json.dumps(out["decoded"], indent=2))


if __name__ == "__main__":
    main()
