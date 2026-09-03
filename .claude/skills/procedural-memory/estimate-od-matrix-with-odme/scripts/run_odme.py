#!/usr/bin/env python3
"""Adjust a seed OD matrix so the assigned link flows reproduce observed counts.

Bi-level objective (stated explicitly, both terms chi-square normalised):

    F(x) = w_c * SUM_l [ (v_l(x) - c_l)^2 / max(c_l,1) ]
         + w_s * SUM_k [ (x_k    - s_k)^2 / max(s_k,1) ]      subject to x >= 0

Two optimisers over the same objective:
  --method lsq    lower level is v = P x, so F is a bound-constrained linear least
                  squares problem -> exact solve via scipy.optimize.lsq_linear.
  --method spsa   derivative-free simultaneous perturbation over log-multipliers
                  x = s * exp(theta); needs only an objective oracle, so it also
                  works when the lower level is a full simulation.

Always reports the null-space diagnostic: how many degrees of freedom the counts
cannot see, and therefore how much of the answer is inherited from the seed.

Usage:
  python run_odme.py --p P.npz --counts edgedata.out.xml --seed-matrix seed.od \
      --out estimated.od --w-seed 0.1 [--method lsq|spsa] [--truth-matrix truth.od]
  python run_odme.py ... --w-seed-sweep 1e-4,0.01,0.1,1,10
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy.optimize import lsq_linear

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odme_core import (read_od, write_od, read_counts_file, count_fit, od_recovery, rmsn)


# ---------------------------------------------------------------- objective
def objective(x, P, c, s, w_c=1.0, w_s=1.0, v=None):
    v = P @ x if v is None else v
    fc = float(np.sum((v - c) ** 2 / np.maximum(c, 1.0)))
    fs = float(np.sum((x - s) ** 2 / np.maximum(s, 1.0)))
    return w_c * fc + w_s * fs, fc, fs


# ---------------------------------------------------------------- algorithm A
def odme_lsq(P, c, s, w_c=1.0, w_s=1.0, max_iter=500):
    """Bound-constrained generalised least squares. Exact, one solve, no tuning."""
    wc = np.sqrt(w_c / np.maximum(c, 1.0))
    ws = np.sqrt(w_s / np.maximum(s, 1.0))
    A = np.vstack([wc[:, None] * P, np.diag(ws)])
    b = np.concatenate([wc * c, ws * s])
    r = lsq_linear(A, b, bounds=(0.0, np.inf), max_iter=max_iter, tol=1e-12)
    x = np.maximum(r.x, 0.0)
    F, fc, fs = objective(x, P, c, s, w_c, w_s)
    return x, dict(status=int(r.status), nit=int(r.nit), F=F, F_count=fc, F_seed=fs)


# ---------------------------------------------------------------- algorithm B
def odme_spsa(eval_flow, c, s, w_c=1.0, w_s=1.0, n_iter=300, a=0.4, c_pert=0.08,
              A_frac=0.1, alpha=0.602, gamma=0.101, seed=0, verbose=False,
              track=False, step_max=0.05, theta_max=1.5):
    """SPSA over log-multipliers, x = s * exp(theta).

    `eval_flow(x)` -> link flow vector.  Pass a simulation wrapper here to put the
    real microsimulation in the loop; pass `lambda x: P @ x` for the linear model.
    """
    rng = np.random.default_rng(seed)
    theta = np.zeros(len(s))
    A = A_frac * n_iter
    hist, n_eval = [], [0]

    def F(th):
        n_eval[0] += 1
        x = s * np.exp(th)
        return objective(x, None, c, s, w_c, w_s, v=eval_flow(x))[0]

    best = (F(theta), theta.copy()) if track else (float("inf"), theta.copy())
    for k in range(n_iter):
        ak = a / (k + 1 + A) ** alpha
        ck = c_pert / (k + 1) ** gamma
        delta = rng.choice([-1.0, 1.0], size=len(s))
        fp, fm = F(theta + ck * delta), F(theta - ck * delta)
        ghat = (fp - fm) / (2.0 * ck) * (1.0 / delta)
        # RMS-normalise then clip. The raw SPSA gradient is (fp-fm)/(2*ck): with
        # ck ~ 0.1 and F in the thousands it is O(1e3), which pins theta at its clip
        # and blows the candidate matrix up to ~20x the seed -- in a simulation loop
        # every later evaluation then gridlocks and takes minutes. This is the single
        # most important practical detail in getting SPSA-based ODME to run at all.
        step = np.clip(ak * ghat / (np.sqrt(np.mean(ghat ** 2)) + 1e-12), -step_max, step_max)
        theta = np.clip(theta - step, -theta_max, theta_max)
        fk = F(theta) if track else 0.5 * (fp + fm)
        if fk < best[0] or not track:
            best = (fk, theta.copy())
        hist.append(round(fk, 2))
        if verbose and k % 10 == 0:
            print("  spsa %4d  F=%.1f" % (k, fk), flush=True)
    return s * np.exp(best[1]), dict(F=best[0], n_evals=n_eval[0], history=hist)


# ---------------------------------------------------------------- diagnostics
def nullspace_report(P, s, x, truth=None, rcond=1e-10):
    """Split errors into what the counts can see (row space of P) and what they cannot.

    For an unregularised least-squares ODME the null-space component of the seed
    error passes through UNCHANGED. That is the precise meaning of 'inherited from
    the seed rather than learned from the counts'.
    """
    U, sv, Vt = np.linalg.svd(P, full_matrices=False)
    keep = sv > sv.max() * rcond
    V = Vt[keep].T

    def split(e):
        row = V @ (V.T @ e)
        return float(np.linalg.norm(row)), float(np.linalg.norm(e - row))

    mv_r, mv_n = split(x - s)
    out = dict(rank=int(keep.sum()), nullspace_dim=int(P.shape[1] - keep.sum()),
               unknowns=int(P.shape[1]), equations=int(P.shape[0]),
               adjustment_in_rowspace=round(mv_r, 2),
               adjustment_in_nullspace=round(mv_n, 2))
    if truth is not None:
        sr, sn = split(s - truth)
        er, en = split(x - truth)
        out.update(seed_err_rowspace=round(sr, 2), seed_err_nullspace=round(sn, 2),
                   est_err_rowspace=round(er, 2), est_err_nullspace=round(en, 2),
                   seed_err_share_invisible_pct=round(100 * sn / np.hypot(sr, sn), 1),
                   nullspace_err_retained_pct=round(100 * en / sn, 1) if sn > 0 else None,
                   rowspace_err_removed_pct=round(100 * (1 - er / sr), 1) if sr > 0 else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--p", required=True, help="P.npz from build_assignment_matrix.py")
    ap.add_argument("--counts", required=True, help="edgeData XML or `edge,count` CSV")
    ap.add_argument("--counts-attr", default="entered")
    ap.add_argument("--seed-matrix", required=True)
    ap.add_argument("--out", default="estimated.od")
    ap.add_argument("--method", choices=["lsq", "spsa"], default="lsq")
    ap.add_argument("--w-count", type=float, default=1.0)
    ap.add_argument("--w-seed", type=float, default=0.1)
    ap.add_argument("--w-seed-sweep", help="comma-separated w_seed values to tabulate instead")
    ap.add_argument("--spsa-iters", type=int, default=300)
    ap.add_argument("--truth-matrix", help="ground truth, for OD-recovery reporting (validation only)")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    z = np.load(a.p, allow_pickle=True)
    P, edges = z["P"], [str(e) for e in z["edges"]]
    pairs, s, header = read_od(a.seed_matrix)
    _, c = read_counts_file(a.counts, edges, a.counts_attr)
    truth = read_od(a.truth_matrix)[1] if a.truth_matrix else None

    if P.shape != (len(edges), len(pairs)):
        raise SystemExit("P shape %s does not match %d counted links x %d OD pairs"
                         % (P.shape, len(edges), len(pairs)))

    def solve(w_s):
        if a.method == "lsq":
            return odme_lsq(P, c, s, a.w_count, w_s)
        return odme_spsa(lambda x: P @ x, c, s, a.w_count, w_s, n_iter=a.spsa_iters)

    report = dict(method=a.method, n_counted_links=len(edges), n_od_pairs=len(pairs),
                  w_count=a.w_count, seed_matrix=a.seed_matrix, counts=a.counts,
                  seed_count_fit=count_fit(P @ s, c), rows=[])

    weights = ([float(w) for w in a.w_seed_sweep.split(",")] if a.w_seed_sweep else [a.w_seed])
    best = None
    for w_s in weights:
        x, info = solve(w_s)
        row = dict(w_seed=w_s, F=round(info["F"], 3),
                   count_fit=count_fit(P @ x, c),
                   nullspace=nullspace_report(P, s, x, truth),
                   total_demand=round(float(x.sum()), 1))
        if truth is not None:
            row["od_recovery"] = od_recovery(pairs, x, truth)
            row["seed_od_cell_rmsn_pct"] = round(rmsn(s, truth), 3)
        report["rows"].append(row)
        if w_s == a.w_seed or best is None:
            best = x

    write_od(a.out, pairs, best, header, "ODME estimate (w_seed=%g, method=%s)" % (a.w_seed, a.method))
    report["output_matrix"] = a.out
    if a.report:
        with open(a.report, "w") as f:
            json.dump(report, f, indent=2)

    ns = report["rows"][0]["nullspace"]
    print("counted links %d | OD pairs %d | rank(P) %d | null space %d"
          % (ns["equations"], ns["unknowns"], ns["rank"], ns["nullspace_dim"]))
    print("seed count fit: RMSN %.2f%%  GEH<5 %.1f%%"
          % (report["seed_count_fit"]["rmsn_pct"], report["seed_count_fit"]["geh_lt5_pct"]))
    hdr = "%-10s %10s %9s %11s" % ("w_seed", "RMSN %", "GEH<5 %", "total")
    if truth is not None:
        hdr += " %10s %12s %11s" % ("OD RMSN %", "tot err %", "null kept %")
    print(hdr)
    for r in report["rows"]:
        line = "%-10g %10.2f %9.1f %11.0f" % (r["w_seed"], r["count_fit"]["rmsn_pct"],
                                              r["count_fit"]["geh_lt5_pct"], r["total_demand"])
        if truth is not None:
            line += " %10.2f %12.2f %11s" % (r["od_recovery"]["cell_rmsn_pct"],
                                             r["od_recovery"]["total_demand_err_pct"],
                                             r["nullspace"]["nullspace_err_retained_pct"])
        print(line)
    if ns["nullspace_dim"] > 0:
        print("\nNOTE: %d of %d OD degrees of freedom are invisible to these counts. "
              "A good count fit does NOT imply a recovered matrix -- run "
              "check_equifinality.py before using the result for anything OD-specific."
              % (ns["nullspace_dim"], ns["unknowns"]))


if __name__ == "__main__":
    main()
