"""Doubly-constrained gravity model with Furness / IPF balancing.

T_ij = a_i * P_i * b_j * A_j * f(c_ij)

Deterrence functions:
  exponential  f(c) = exp(-beta * c)
  gamma        f(c) = c^(-alpha) * exp(-beta * c)      ("combined" / Tanner function)
  power        f(c) = c^(-beta)

Furness iterates a_i and b_j until row and column sums match the margins.  The
convergence check is on the *achieved* margins, not on the multipliers, and the
achieved max relative margin error is returned so it can be asserted, not assumed.
"""
import numpy as np


def deterrence(C, kind, beta, alpha=0.0):
    C = np.maximum(C, 1e-9)
    if kind == "exp":
        return np.exp(-beta * C)
    if kind == "gamma":
        return np.power(C, -alpha) * np.exp(-beta * C)
    if kind == "power":
        return np.power(C, -beta)
    raise ValueError(kind)


def furness(P, A, F, tol=1e-8, max_iter=2000):
    """Doubly-constrained IPF. Returns (T, info)."""
    P = np.asarray(P, float)
    A = np.asarray(A, float)
    assert abs(P.sum() - A.sum()) < 1e-6 * max(P.sum(), 1.0), "margins not balanced"
    n, m = len(P), len(A)
    a = np.ones(n)
    b = np.ones(m)
    hist = []
    for it in range(1, max_iter + 1):
        # row step
        T = (a[:, None] * P[:, None]) * (b[None, :] * A[None, :]) * F
        rs = T.sum(1)
        a = np.where(rs > 0, a * P / np.maximum(rs, 1e-300), a)
        T = (a[:, None] * P[:, None]) * (b[None, :] * A[None, :]) * F
        cs = T.sum(0)
        b = np.where(cs > 0, b * A / np.maximum(cs, 1e-300), b)
        T = (a[:, None] * P[:, None]) * (b[None, :] * A[None, :]) * F
        err = max(
            np.abs(T.sum(1) - P).max() / P.mean(),
            np.abs(T.sum(0) - A).max() / A.mean(),
        )
        hist.append(err)
        if err < tol:
            break
    info = {
        "iterations": it,
        "max_rel_margin_error": float(err),
        "converged": bool(err < tol),
        "tol": tol,
        "history": [float(h) for h in hist],
    }
    return T, info


def mean_trip_cost(T, C):
    return float((T * C).sum() / T.sum())


def calibrate_beta(P, A, C, target, kind="exp", alpha=0.0, cost_for_target=None,
                   lo=1e-4, hi=5.0, tol=1e-6, max_iter=80):
    """Bisect beta so that the mean of `cost_for_target` (default C) over T hits `target`.

    Mean trip cost is monotonically decreasing in beta, so bisection is safe.
    """
    Ct = C if cost_for_target is None else cost_for_target
    trace = []

    def mtl(beta):
        F = deterrence(C, kind, beta, alpha)
        T, info = furness(P, A, F)
        v = mean_trip_cost(T, Ct)
        trace.append((float(beta), float(v), info["iterations"], info["max_rel_margin_error"]))
        return v, T, info

    v_lo, _, _ = mtl(lo)
    v_hi, _, _ = mtl(hi)
    if not (v_hi <= target <= v_lo):
        raise ValueError("target %.4f outside achievable range [%.4f, %.4f]" % (target, v_hi, v_lo))
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        v, T, info = mtl(mid)
        if abs(v - target) < tol * max(1.0, abs(target)):
            break
        if v > target:
            lo = mid
        else:
            hi = mid
    return mid, T, info, v, trace
