"""Count-station / sensor PLACEMENT strategies for OD estimation.

Every strategy here returns a **nested order** — a permutation of the candidate-link
index set, where the design at budget N is simply the first N entries. Nested designs
are what make "the marginal value of the Nth sensor" a well-posed question and let one
greedy run serve every budget at once, following
`solve-budget-constrained-network-design-problem`'s greedy discipline.

THE TRUTH BARRIER
-----------------
Every DEPLOYABLE strategy in this module sees only:
  * `P`         — the assignment-proportion matrix (built from the network plus a
                  reference demand, i.e. from the model, never from the truth)
  * `seed_vec`  — the analyst's prior matrix
  * the candidate-link list
This module therefore never imports a ground-truth module, and that is the point: keep
it that way so a `grep` can *prove* the deployable strategies could not have peeked.
The oracle lives in `score_designs.py` alongside the scoring code, physically separated
from the deployable strategies for exactly this reason.

Import path: this module needs `estimate-od-matrix-with-odme`'s bundled `run_odme`
for the reference GLS/SPSA solvers. Set `ODME_SCRIPTS` (env var) or let the default
sibling-skill path resolve.
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

COVER_TOL = 0.02      # a station "covers" pair k if it intercepts >2% of its flow


# ============================================================ the estimator
def estimate(P, c_obs, sel, seed_vec, w_seed=0.1, w_count=1.0):
    """The workhorse ODME solve: `estimate-od-matrix-with-odme`'s bi-level objective
    (count fit + seed deviation) solved through the normal equations.

    Two reasons this, and not the skill's `odme_lsq`, is the workhorse for a design
    sweep — both learned the hard way:
      * ~50x faster (1 ms vs 10 ms). A placement study runs ~1e5 solves; at
        `lsq_linear` speed the exhaustive-enumeration and local-search arms are
        unaffordable.
      * `scipy.optimize.lsq_linear` raised `LinAlgError: SVD did not converge in
        Linear Least Squares` (inside its own `np.linalg.lstsq` warm start) on a
        handful of low-rank two-sensor designs. A design sweep visits thousands of
        rank-deficient row subsets, so this is not an edge case here — it is the
        normal case. The ridge `w_seed*diag(1/max(s,1))` makes the normal-equation
        matrix strictly positive definite, so this solve is unconditionally well posed.

    Always cross-check against the skill's solver once via `verify_solvers` before
    trusting a sweep — agreement to ~1e-15 relative L2 is what you should see.
    """
    Ps = P[sel]
    dc = w_count / np.maximum(c_obs[sel], 1.0)
    ds = w_seed / np.maximum(seed_vec, 1.0)
    A = (Ps * dc[:, None]).T @ Ps
    A[np.diag_indices_from(A)] += ds
    b = Ps.T @ (dc * c_obs[sel]) + ds * seed_vec
    x = np.linalg.solve(A, b)
    if x.min() < -1e-9:
        # Active-set projection onto x>=0. Each sub-solve is well posed because A is
        # strictly positive definite. Do NOT fall back to lsq_linear here — it is the
        # solver whose SVD failure motivated this one.
        free = np.ones(len(x), bool)
        for _ in range(40):
            x = np.zeros(len(free))
            idx = np.where(free)[0]
            x[idx] = np.linalg.solve(A[np.ix_(idx, idx)], b[idx])
            bad = idx[x[idx] < -1e-12]
            if not len(bad):
                break
            free[bad] = False
    x = np.maximum(x, 0.0)
    v = Ps @ x
    fc = float(np.sum((v - c_obs[sel]) ** 2 / np.maximum(c_obs[sel], 1.0)))
    fs = float(np.sum((x - seed_vec) ** 2 / np.maximum(seed_vec, 1.0)))
    return x, dict(F=w_count * fc + w_seed * fs, F_count=fc, F_seed=fs,
                   solver="normal_equations")


def estimate_ref(P, c_obs, sel, seed_vec, w_seed=0.1, w_count=1.0):
    """Reference estimator: the ODME skill's own bound-constrained GLS solver."""
    from run_odme import odme_lsq
    return odme_lsq(P[sel], c_obs[sel], seed_vec, w_count, w_seed)


def estimate_spsa(P, c_obs, sel, seed_vec, w_seed=0.1, w_count=1.0, n_iter=1500):
    """Derivative-free arm, linear lower level."""
    from run_odme import odme_spsa
    Ps = P[sel]
    return odme_spsa(lambda x: Ps @ x, c_obs[sel], seed_vec, w_count, w_seed, n_iter=n_iter)


def estimate_spsa_sim(eval_flow, c_sel, seed_vec, w_seed=0.1, w_count=1.0, n_iter=100):
    """SPSA with an arbitrary lower level — pass a microsimulation wrapper as
    `eval_flow(x) -> link flows`. Use this to spot-check that the cheap linear solver
    is not what is producing your conclusion. Budget ~2 sim runs per iteration."""
    from run_odme import odme_spsa
    return odme_spsa(eval_flow, c_sel, seed_vec, w_count, w_seed, n_iter=n_iter)


def verify_solvers(P, c_obs, seed_vec, designs, w_seed=0.1):
    """Max relative difference between the fast solver and the skill's reference one.
    Run this on a handful of designs spanning small and large N before any sweep."""
    out = []
    for sel in designs:
        x1, _ = estimate(P, c_obs, sel, seed_vec, w_seed)
        try:
            x2, _ = estimate_ref(P, c_obs, sel, seed_vec, w_seed)
        except Exception as e:                                     # noqa: BLE001
            out.append(dict(n=len(sel), reference_solver_error=repr(e)))
            continue
        den = max(np.linalg.norm(x2), 1e-9)
        out.append(dict(n=len(sel), rel_l2_diff=float(np.linalg.norm(x1 - x2) / den),
                        max_abs_diff=float(np.abs(x1 - x2).max()),
                        min_x=float(x1.min())))
    return out


# ================================================== (a) the random null DISTRIBUTION
def random_orders(n_cand, n_draws=40, seed=1234):
    """Many draws, not one. A single random design is not a null — you need the
    distribution, because the honest question is whether a designed set beats the
    null's *best* draw, not merely its median. In the reference study the best of 40
    draws was competitive with every deployable strategy at several budgets."""
    rng = np.random.default_rng(seed)
    return [rng.permutation(n_cand).tolist() for _ in range(n_draws)]


# =============================================== (b) volume-greedy: the practitioner
def volume_order(P, seed_vec):
    """Rank links by *seed-predicted* volume (P @ seed). Deployable — an analyst has
    the seed and the model, not the truth.

    Treat this as the baseline to beat, not as a straw man. In the reference study no
    deployable "smart" criterion beat it by a resolvable margin at any budget."""
    return np.argsort(-(P @ seed_vec)).tolist()


def volume_order_from_counts(v_obs):
    """Rank by volume actually *measured* everywhere. Label this WEAKLY NON-DEPLOYABLE
    wherever it appears: it presupposes a pre-existing full count set, which is the
    very thing the design is supposed to buy. Useful only as a sensitivity arm."""
    return np.argsort(-np.asarray(v_obs)).tolist()


# ============================================= (c) classical rule-based (Yang & Zhou)
def yang_zhou_order(P, seed_vec, cover_tol=COVER_TOL):
    """Yang & Zhou-style rule composition, in their stated priority order:

      1. OD-COVERING        — intercept as many OD pairs as possible with >=1 station.
      2. MAXIMAL FLOW FRACTION — once covered, raise the *smallest* intercepted flow
                              fraction across pairs (a max-min rule), weighted by the
                              pair's prior flow.
      3. LINK INDEPENDENCE  — a station whose P-row is linearly dependent on the rows
                              already chosen adds no equation; skip it while any
                              independent candidate remains.
      (Their 4th rule, maximal flow *intercepting*, enters as the `seed_vec` tie-break
      weight inside rules 1-2.)

    Flow fraction of pair k under station set S is approximated as f_k(S) = max_{l in S}
    P[l,k] — the standard tractable surrogate for "share of pair k's trips seen at
    least once" given marginal traversal probabilities.

    Expect this to LOSE badly at small budgets. Measured, not asserted: it sat at the
    no-sensor error out to N=16 of 98 while volume-greedy was already at 64.6% — the
    covering rule spends its early stations on many cheap low-flow pairs, buying rows
    that carry almost no demand information."""
    M, K = P.shape
    order, remaining = [], set(range(M))
    f = np.zeros(K)                              # current flow fraction per pair
    Q = []                                       # orthonormal basis of chosen rows
    res2 = (P ** 2).sum(1).astype(float)         # squared residual row norms

    while remaining:
        indep = [l for l in remaining if res2[l] > 1e-12]
        pool = indep if indep else list(remaining)
        newcov, gain = {}, {}
        for l in pool:
            fl = np.maximum(f, P[l])
            newcov[l] = int(((f <= cover_tol) & (fl > cover_tol)).sum())
            # weight the flow-fraction gain by prior flow and by 1/(f+eps) so the
            # worst-covered pairs dominate -> max-min behaviour
            gain[l] = float(np.sum((fl - f) * seed_vec / (f + 0.05)))
        best = max(pool, key=lambda l: (newcov[l], gain[l]))
        order.append(best)
        remaining.discard(best)
        f = np.maximum(f, P[best])
        res2, Q = _deflate(P, best, Q, res2)
    return order


# ================================== (d) observability / information-maximizing design
def rank_growth_order(P):
    """Greedy column-rank growth: take the candidate whose P-row has the largest
    component orthogonal to the rows already selected (Gram-Schmidt). This is the
    uninformative-prior limit of the D-optimal rule below.

    Same warning as Yang & Zhou — it maximises the number of independent *equations*,
    which is not the same as reducing error in the cells that carry the demand. But see
    the robustness note in SKILL.md: this is the strategy that WINS when the seed is
    structurally wrong, which is when a designed sensor set matters most."""
    M = P.shape[0]
    Q, order, remaining = [], [], set(range(M))
    res2 = (P ** 2).sum(1).astype(float)
    while remaining:
        best = max(remaining, key=lambda l: res2[l])
        order.append(best)
        remaining.discard(best)
        res2, Q = _deflate(P, best, Q, res2)
    return order


def d_optimal_order(P, seed_vec, w_seed=0.1, weight_by_volume=True):
    """Bayesian D-optimal greedy on the ESTIMATOR's own information matrix

        M(S) = sum_{l in S} p_l p_l^T / max(v_l, 1)  +  w_seed * diag(1/max(s, 1))

    with v = P @ seed the seed-predicted volume. Adding row l raises log det M by
    log(1 + p_l' M^-1 p_l / max(v_l,1)), so the greedy step is exact, and
    Sherman-Morrison keeps it O(K^2) per candidate. Deployable — no truth anywhere.

    ** `weight_by_volume` is the single most consequential switch in this module. **
    The ODME objective weights count residuals by 1/max(c,1) (chi-square / Poisson
    variance), which makes a *LOW*-volume link the statistically more informative
    observation. So the volume weighting inverts D-optimality: it picks low-flow links
    first and lands at the no-sensor error, while `weight_by_volume=False`
    (homoscedastic) makes the same algorithm pick high-volume links and perform best of
    all deployable arms. The criterion is internally consistent with the estimator and
    still wrong for the goal. Run BOTH arms and report both; if you run only the
    variance-consistent one you will conclude, wrongly, that D-optimality fails."""
    v = np.maximum(P @ seed_vec, 1.0) if weight_by_volume else np.ones(P.shape[0])
    prior = w_seed / np.maximum(seed_vec, 1.0)
    Minv = np.diag(1.0 / prior)
    M = P.shape[0]
    order, gains, remaining = [], [], set(range(M))
    while remaining:
        cand = np.array(sorted(remaining))
        Pc = P[cand]
        quad = np.einsum("ij,jk,ik->i", Pc, Minv, Pc) / v[cand]
        g = np.log1p(np.maximum(quad, 0.0))
        j = int(np.argmax(g))
        l = int(cand[j])
        order.append(l)
        gains.append(float(g[j]))
        remaining.discard(l)
        Minv = _sherman(Minv, P[l] / np.sqrt(v[l]))
    return order, gains


def max_min_eig_order(P, seed_vec, w_seed=0.1, n_pool=25):
    """E-optimal flavour: maximise the smallest eigenvalue of the same information
    matrix. Restricted to the top `n_pool` D-optimal candidates per step because a full
    eigen-scan is O(M K^3). Included because E- and D-optimality can disagree, and a
    design study that reports one information criterion has not tested the *class*."""
    v = np.maximum(P @ seed_vec, 1.0)
    prior = w_seed / np.maximum(seed_vec, 1.0)
    Mmat = np.diag(prior)
    Minv = np.diag(1.0 / prior)
    order, remaining = [], set(range(P.shape[0]))
    while remaining:
        cand = np.array(sorted(remaining))
        Pc = P[cand]
        quad = np.einsum("ij,jk,ik->i", Pc, Minv, Pc) / v[cand]
        pool = cand[np.argsort(-quad)[:n_pool]]
        best, best_val = None, -np.inf
        for l in pool:
            A = Mmat + np.outer(P[l], P[l]) / v[l]
            val = float(np.linalg.eigvalsh(A)[0])
            if val > best_val:
                best, best_val = int(l), val
        order.append(best)
        remaining.discard(best)
        Mmat = Mmat + np.outer(P[best], P[best]) / v[best]
        Minv = _sherman(Minv, P[best] / np.sqrt(v[best]))
    return order


# ============================================================= greedy row selection
def greedy_dopt_rows(rows, ridge, k, base_rows=None):
    """Unweighted D-optimal selection of `k` rows from an arbitrary observation-row
    matrix, optionally on top of rows already bought (`base_rows`). This is what lets
    you design a MIXED portfolio: pass the counter rows as `base_rows` and the
    candidate subpath-reader rows as `rows`."""
    Minv = np.diag(1.0 / ridge)
    if base_rows is not None and len(base_rows):
        for r in base_rows:
            Minv = _sherman(Minv, np.asarray(r, float))
    chosen, remaining = [], set(range(rows.shape[0]))
    for _ in range(k):
        cand = np.array(sorted(remaining))
        q = np.einsum("ij,jk,ik->i", rows[cand], Minv, rows[cand])
        l = int(cand[int(np.argmax(q))])
        chosen.append(l)
        remaining.discard(l)
        Minv = _sherman(Minv, rows[l])
    return chosen


# ------------------------------------------------------------------------- internals
def _sherman(Minv, u):
    Mu = Minv @ u
    return Minv - np.outer(Mu, Mu) / (1.0 + u @ Mu)


def _deflate(P, chosen, Q, res2):
    """Gram-Schmidt one row out of the residual-norm bookkeeping."""
    r = P[chosen].astype(float).copy()
    for q in Q:
        r -= (q @ r) * q
    nr = np.linalg.norm(r)
    if nr > 1e-9:
        q = r / nr
        Q = Q + [q]
        res2 = np.maximum(res2 - (P @ q) ** 2, 0.0)
    return res2, Q


ALL_STRATEGIES = {
    "volume": "practitioner default; seed-predicted volume. THE baseline to beat.",
    "volume_meas": "measured volume. WEAKLY NON-DEPLOYABLE — needs a full count set.",
    "yang_zhou": "classical covering / max-min flow fraction / link independence.",
    "observability": "greedy column-rank growth (Gram-Schmidt).",
    "d_optimal": "Bayesian D-optimal on the chi-square-weighted information matrix.",
    "d_optimal_unw": "same, homoscedastic weighting. Best deployable arm in testing.",
    "max_min_eig": "E-optimal (max-min eigenvalue).",
    "random": "null DISTRIBUTION over many draws — report median AND best draw.",
    "oracle": "greedy on true OD error. NON-DEPLOYABLE upper bound; see score_designs.py.",
}
