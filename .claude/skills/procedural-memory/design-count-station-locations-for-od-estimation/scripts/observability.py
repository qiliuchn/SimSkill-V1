"""Observability accounting for an OD-estimation sensor design.

Answer this BEFORE running any placement strategy, because it usually reframes the
question. The point is not "how many sensors do I need for full observability" — on a
real network the answer is normally "more independent link equations than the network
can physically supply." The useful question is *which* identifiable directions your
budget buys.

Verify `P` first (`verify_P`). Everything downstream — every strategy, every score —
is conditional on `P` being a faithful linear model of the assignment, and a `P` that
does not reproduce the assigned flows silently invalidates the whole study.
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ODME_SCRIPTS = os.environ.get(
    "ODME_SCRIPTS",
    os.path.abspath(os.path.join(_HERE, "..", "..", "estimate-od-matrix-with-odme", "scripts")),
)
if ODME_SCRIPTS not in sys.path:
    sys.path.insert(0, ODME_SCRIPTS)
from odme_core import count_fit                                        # noqa: E402


def verify_P(P, x_true, realised_counts, tol_geh=5.0):
    """Check `P @ x_true` against the REALISED assignment, one row per router seed.

    State the tolerance before you look. GEH < 5 on every candidate link is the bar used
    in the reference study (achieved: max GEH 2.27, %RMSN 4.9-6.0 across three router
    seeds). Also report the seed-to-seed spread of `realised_counts` itself — that is
    the irreducible assignment noise, and no count fit tighter than it is meaningful.

    A `P` that fails here is usually a routing problem, not a linear-algebra problem:
    the most common cause is OD pairs that silently routed few or no trips. Check for
    that explicitly rather than accepting a warning line in router output.
    """
    R = np.atleast_2d(np.asarray(realised_counts, float))
    v = P @ np.asarray(x_true, float)
    per = []
    for i in range(R.shape[0]):
        fit = count_fit(v, R[i])
        per.append(dict(realisation=i, rmsn_pct=fit["rmsn_pct"], geh_mean=fit["geh_mean"],
                        geh_max=fit["geh_max"], geh_lt5_pct=fit["geh_lt5_pct"],
                        passes=bool(fit["geh_max"] < tol_geh)))
    spread = []
    for i in range(R.shape[0]):
        for j in range(i + 1, R.shape[0]):
            f = count_fit(R[i], R[j])
            spread.append(f["rmsn_pct"])
    return dict(per_realisation=per,
                all_pass=all(p["passes"] for p in per),
                assignment_noise_rmsn_pct=float(np.mean(spread)) if spread else None)


def observability_report(P, selectable=None, rtol=1e-10):
    """Rank / null-space accounting for the whole candidate set and for the selectable
    subset.

    Interpretation, and the reason this function exists: `n_od_cells` independent rows
    are needed to identify the matrix from counts alone. If `rank_all` < `n_od_cells`,
    **full OD observability is unachievable at ANY budget on this network** — that is
    the honest headline, and it means every design is a choice of which identifiable
    subspace to buy, not a step toward identification. On the reference 6x6 grid: 182 OD
    cells, 123 candidate links, rank(P) saturating at 94.

    `cond_rowspace` (largest over smallest nonzero singular value) matters as much as
    the rank: a nominally full-rank design with a condition number in the thousands is
    identified in name only.
    """
    P = np.asarray(P, float)
    M, K = P.shape
    sv = np.linalg.svd(P, compute_uv=False)
    tol = sv.max() * max(M, K) * np.finfo(float).eps if sv.size else 0.0
    nz = sv[sv > max(tol, rtol * (sv.max() if sv.size else 1.0))]
    out = dict(n_candidate_links=M, n_od_cells=K, rank_all=int(len(nz)),
               null_space_dim=int(K - len(nz)),
               min_links_for_full_observability=K,
               full_observability_achievable=bool(len(nz) >= K),
               cond_rowspace=float(nz.max() / nz.min()) if len(nz) else float("inf"))
    if selectable is not None:
        Ps = P[list(selectable)]
        svs = np.linalg.svd(Ps, compute_uv=False)
        tols = svs.max() * max(Ps.shape) * np.finfo(float).eps if svs.size else 0.0
        out["n_selectable"] = len(list(selectable))
        out["rank_selectable"] = int((svs > max(tols, rtol * svs.max())).sum())
    return out


def rank_vs_budget(P, order, budgets=None):
    """rank(P[first N of order]) for each budget — how fast a placement order actually
    buys independent equations. `rank(N) == N` means every station so far added a new
    equation; where it saturates is where extra stations stop being informative in the
    linear-algebra sense (though they still reduce variance)."""
    order = list(order)
    budgets = budgets or list(range(1, len(order) + 1))
    out = {}
    for n in budgets:
        sub = P[order[:n]]
        sv = np.linalg.svd(sub, compute_uv=False)
        tol = sv.max() * max(sub.shape) * np.finfo(float).eps if sv.size else 0.0
        out[n] = int((sv > tol).sum())
    return out


def identifiable_share(P, sel, x_true=None):
    """Share of the OD vector's variation that the selected rows can see at all.

    Projects onto the row space of `P[sel]`. If `x_true` is given, returns how much of
    the truth lies in the observable subspace versus the null space — the quantity that
    explains why a perfect count fit can leave most of the OD error untouched. This is
    the design-time version of `estimate-od-matrix-with-odme`'s equifinality diagnostic.
    """
    Ps = np.asarray(P, float)[list(sel)]
    U, sv, Vt = np.linalg.svd(Ps, full_matrices=False)
    tol = sv.max() * max(Ps.shape) * np.finfo(float).eps if sv.size else 0.0
    r = int((sv > tol).sum())
    V = Vt[:r]
    out = dict(rank=r, n_od_cells=Ps.shape[1], null_space_dim=int(Ps.shape[1] - r))
    if x_true is not None:
        x = np.asarray(x_true, float)
        obs = V.T @ (V @ x)
        out["observable_norm_share_pct"] = float(
            100.0 * np.linalg.norm(obs) / max(np.linalg.norm(x), 1e-12))
        out["null_norm_share_pct"] = float(
            100.0 * np.linalg.norm(x - obs) / max(np.linalg.norm(x), 1e-12))
    return out
