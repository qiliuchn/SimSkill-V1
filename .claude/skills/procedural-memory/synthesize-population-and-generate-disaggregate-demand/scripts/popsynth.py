"""Reusable population synthesiser: IPF reweighting + TRS integerisation + fit metrics.

Deliberately generic: takes a seed sample (list of dicts), a category-mapping function per
control, and per-zone control totals.  The IPF loop follows the same
margin-error-not-multiplier-change convergence discipline as
`build-four-step-model-with-feedback-loop`'s `furness()` (see
[[four-step-model-feedback-loop-convergence]]) -- it returns the achieved margin error, not
just the multipliers, so callers can assert on the thing that actually matters.
"""
import numpy as np


# ---------------------------------------------------------------- IPF ------
def ipf_weights(cat_index, targets, controls, n_total, tol=1e-6, max_iter=500):
    """Iterative proportional fitting of household expansion weights.

    cat_index : dict control -> int array (len n_seed) giving each seed household's
                category index for that control
    targets   : dict control -> float array of control totals for this zone
    controls  : list of control names actually fitted
    n_total   : total households in the zone (weights are initialised to n_total/n_seed)

    Returns (w, history) where history is a list of max relative margin errors per
    iteration.
    """
    n_seed = len(next(iter(cat_index.values())))
    w = np.full(n_seed, float(n_total) / n_seed)
    hist = []
    for it in range(max_iter):
        for c in controls:
            idx, tgt = cat_index[c], np.asarray(targets[c], float)
            got = np.bincount(idx, weights=w, minlength=len(tgt))
            with np.errstate(divide="ignore", invalid="ignore"):
                fac = np.where(got > 0, tgt / np.where(got > 0, got, 1.0), 0.0)
            w = w * fac[idx]
        err = max_margin_error(cat_index, targets, controls, w)
        hist.append(err)
        if err < tol:
            break
    return w, hist


def max_margin_error(cat_index, targets, controls, w):
    e = 0.0
    for c in controls:
        idx, tgt = cat_index[c], np.asarray(targets[c], float)
        got = np.bincount(idx, weights=w, minlength=len(tgt))
        denom = np.where(tgt > 0, tgt, 1.0)
        e = max(e, float(np.max(np.abs(got - tgt) / denom)))
    return e


# ------------------------------------------------------- integerisation ----
def trs_integerize(w, rng, n_target=None):
    """Truncate-Replicate-Sample (Lovelace & Ballas 2013).

    floor() every weight (truncate), replicate each household that many times, then
    draw the residual households with probability proportional to the fractional part.
    """
    n = np.floor(w).astype(int)
    frac = w - n
    if n_target is None:
        n_target = int(round(w.sum()))
    deficit = n_target - int(n.sum())
    if deficit > 0:
        p = frac / frac.sum() if frac.sum() > 0 else np.full(len(w), 1.0 / len(w))
        pick = rng.choice(len(w), size=deficit, replace=True, p=p)
        for i in pick:
            n[i] += 1
    elif deficit < 0:
        cand = np.where(n > 0)[0]
        pick = rng.choice(cand, size=-deficit, replace=False)
        for i in pick:
            n[i] -= 1
    return n


def milp_integerize(w, cat_index, targets, controls, rng=None, jitter=0.10):
    """Margin-constrained CONTROLLED ROUNDING of the IPF weights (PopulationSim-style).

    Every household is rounded to either floor(w_h) or floor(w_h)+1 - never further -
    and the up/down choices are constrained so that every fitted control category hits
    its total exactly:

        n_h = floor(w_h) + x_h,   x_h in {0,1}
        sum_{h in category c} x_h == R_c := target_c - sum_{h in c} floor(w_h)

    R_c is always a non-negative integer because target_c is an integer count and the
    fractional weights already reproduce it exactly, so the program is well posed.  The
    objective min sum_h |n_h - w_h| reduces to min sum_h x_h (1 - 2 frac_h): a household
    whose weight has a fractional part above 0.5 prefers to round up.  `jitter`
    perturbs those costs so that different synthesis seeds pick different, equally
    good roundings - which is what makes the across-seed stability measurement
    meaningful.

    Why not plain TRS: TRS degenerates into multinomial sampling whenever most weights
    are below 1, re-injecting exactly the sampling noise the IPF fit had removed.  Why
    not an unrestricted L1/relative-L1 MILP: it is massively degenerate and free to
    move population onto whichever seed rows happen to satisfy the margins cheaply,
    which visibly distorts the unfitted margin and the income x vehicles joint.
    Bounding each household to its own two neighbouring integers removes both problems.
    """
    from scipy.optimize import milp, LinearConstraint, Bounds
    n_seed = len(w)
    base = np.floor(w).astype(int)
    frac = w - base
    cost = 1.0 - 2.0 * frac
    if rng is not None and jitter > 0:
        cost = cost + rng.normal(0.0, jitter, n_seed)
    rows, lo, hi = [], [], []
    for c in controls:
        idx, tgt = cat_index[c], np.asarray(targets[c], float)
        for k in range(len(tgt)):
            sel = (idx == k).astype(float)
            need = tgt[k] - float((base * (idx == k)).sum())
            rows.append(sel)
            lo.append(need)
            hi.append(need)
    con = LinearConstraint(np.array(rows), np.array(lo), np.array(hi))
    res = milp(c=cost, constraints=con, integrality=np.ones(n_seed),
               bounds=Bounds(np.zeros(n_seed), np.ones(n_seed)))
    if not res.success:
        raise RuntimeError(f"controlled-rounding MILP infeasible: {res.message}")
    return base + np.round(res.x).astype(int)


# ------------------------------------------------------------- metrics ----
def fit_metrics(observed, target):
    """TAE / SAE / SRMSE / chi-square for one control's category vector."""
    o = np.asarray(observed, float)
    t = np.asarray(target, float)
    tae = float(np.abs(o - t).sum())
    n = float(t.sum())
    sae = tae / n if n else float("nan")
    mean_t = t.mean()
    srmse = float(np.sqrt(((o - t) ** 2).mean()) / mean_t) if mean_t > 0 else float("nan")
    mask = t > 0
    chi2 = float((((o - t) ** 2)[mask] / t[mask]).sum())
    return {"TAE": tae, "SAE": sae, "SRMSE": srmse, "chi2": chi2,
            "df": int(mask.sum() - 1)}


def cramers_v(table):
    t = np.asarray(table, float)
    n = t.sum()
    if n <= 0:
        return float("nan")
    row = t.sum(1, keepdims=True)
    col = t.sum(0, keepdims=True)
    exp = row @ col / n
    mask = exp > 0
    chi2 = (((t - exp) ** 2)[mask] / exp[mask]).sum()
    r, c = t.shape
    return float(np.sqrt((chi2 / n) / max(min(r - 1, c - 1), 1)))


def table_srmse(observed, target):
    o = np.asarray(observed, float).ravel()
    t = np.asarray(target, float).ravel()
    m = t.mean()
    return float(np.sqrt(((o - t) ** 2).mean()) / m) if m > 0 else float("nan")
