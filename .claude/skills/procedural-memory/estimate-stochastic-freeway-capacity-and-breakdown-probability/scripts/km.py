#!/usr/bin/env python3
"""Kaplan-Meier product-limit estimation of the capacity distribution from censored
observations, plus censored-sample maximum-likelihood fits (Weibull + log-normal).

Convention (Brilon et al. 2005, "Reliability of Freeway Traffic Flow"):
    an interval carrying flow q that is followed by a BREAKDOWN gives an UNCENSORED
    capacity observation c = q (event=1); an interval carrying flow q that stays
    fluid gives a RIGHT-CENSORED observation c > q (event=0).
    F_c(q) = P(capacity <= q) = P(breakdown at flow q).
"""
import numpy as np
from scipy import optimize, special, stats


# ---------------------------------------------------------------- Kaplan-Meier
def kaplan_meier(q, event):
    """Product-limit estimate of F_c(q) = P(C <= q).
    Risk set at q_i = {j : q_j >= q_i}. Returns (qi, F, se_F, n_risk, n_event)."""
    q = np.asarray(q, float)
    event = np.asarray(event, int)
    uq = np.unique(q[event == 1])
    S = 1.0
    var_acc = 0.0
    out_q, out_F, out_se, out_k, out_d = [], [], [], [], []
    for qi in uq:
        k = int(np.sum(q >= qi))
        d = int(np.sum((q == qi) & (event == 1)))
        if k <= 0:
            continue
        S *= (k - d) / k
        if k > d:
            var_acc += d / (k * (k - d))
        se_S = S * np.sqrt(var_acc)
        out_q.append(qi); out_F.append(1 - S); out_se.append(se_S)
        out_k.append(k); out_d.append(d)
    return (np.array(out_q), np.array(out_F), np.array(out_se),
            np.array(out_k), np.array(out_d))


def km_loglog_ci(qi, F, se_S, alpha=0.05):
    """Log-log transformed pointwise CI for F (better small-sample behaviour than plain)."""
    S = 1 - F
    z = stats.norm.ppf(1 - alpha / 2)
    lo, hi = np.empty_like(S), np.empty_like(S)
    for i, (s, se) in enumerate(zip(S, se_S)):
        if s <= 0 or s >= 1:
            lo[i], hi[i] = (0.0 if s <= 0 else s), (1.0 if s >= 1 else s)
            continue
        theta = np.exp(z * se / (s * np.log(s)))
        a, b = s ** (1 / theta), s ** theta
        lo[i], hi[i] = min(a, b), max(a, b)
    return 1 - hi, 1 - lo          # CI on F


# ---------------------------------------------------------------- parametric MLE
def _weibull_nll(p, q, event):
    k, lam = np.exp(p)
    z = q / lam
    ll = np.sum(event * (np.log(k) - np.log(lam) + (k - 1) * np.log(z))) - np.sum(z ** k)
    return -ll


def weibull_mle(q, event):
    q = np.asarray(q, float); event = np.asarray(event, int)
    x0 = np.array([np.log(5.0), np.log(np.mean(q))])
    r = optimize.minimize(_weibull_nll, x0, args=(q, event), method="Nelder-Mead",
                          options=dict(maxiter=20000, xatol=1e-10, fatol=1e-10))
    k, lam = np.exp(r.x)
    return dict(model="weibull", shape_k=float(k), scale_lambda=float(lam),
                nll=float(r.fun), n_par=2,
                mean=float(lam * special.gamma(1 + 1 / k)),
                sd=float(lam * np.sqrt(special.gamma(1 + 2 / k) - special.gamma(1 + 1 / k) ** 2)),
                cv_pct=float(100 * np.sqrt(special.gamma(1 + 2 / k) /
                                           special.gamma(1 + 1 / k) ** 2 - 1)))


def weibull_q_at_p(fit, p):
    return fit["scale_lambda"] * (-np.log(1 - p)) ** (1 / fit["shape_k"])


def weibull_cdf(fit, q):
    return 1 - np.exp(-(np.asarray(q, float) / fit["scale_lambda"]) ** fit["shape_k"])


def _lognorm_nll(p, q, event):
    mu, sig = p[0], np.exp(p[1])
    z = (np.log(q) - mu) / sig
    logf = -np.log(q * sig * np.sqrt(2 * np.pi)) - 0.5 * z ** 2
    logS = stats.norm.logsf(z)
    return -(np.sum(event * logf) + np.sum((1 - event) * logS))


def lognormal_mle(q, event):
    q = np.asarray(q, float); event = np.asarray(event, int)
    x0 = np.array([np.mean(np.log(q)), np.log(0.15)])
    r = optimize.minimize(_lognorm_nll, x0, args=(q, event), method="Nelder-Mead",
                          options=dict(maxiter=20000, xatol=1e-10, fatol=1e-10))
    mu, sig = r.x[0], float(np.exp(r.x[1]))
    m = float(np.exp(mu + sig ** 2 / 2))
    sd = float(m * np.sqrt(np.exp(sig ** 2) - 1))
    return dict(model="lognormal", mu=float(mu), sigma=sig, nll=float(r.fun), n_par=2,
                mean=m, sd=sd, cv_pct=float(100 * sd / m))


def lognormal_q_at_p(fit, p):
    return float(np.exp(fit["mu"] + fit["sigma"] * stats.norm.ppf(p)))


def lognormal_cdf(fit, q):
    return stats.norm.cdf((np.log(np.asarray(q, float)) - fit["mu"]) / fit["sigma"])


def aic(fit, n_uncensored_plus_censored):
    return 2 * fit["n_par"] + 2 * fit["nll"]


# ---------------------------------------------------------------- cluster bootstrap
def cluster_bootstrap_weibull(q, event, cluster, n_boot=600, seed=12345, ps=(0.05, 0.10, 0.50)):
    """Resample whole DAYS (clusters), not intervals -- intervals within a day are
    strongly correlated, so an interval-level bootstrap would understate the CI."""
    rng = np.random.RandomState(seed)
    q = np.asarray(q, float); event = np.asarray(event, int)
    cl = np.asarray(cluster)
    uc = np.unique(cl)
    idx_by_c = {c: np.where(cl == c)[0] for c in uc}
    ks, lams, qps = [], [], {p: [] for p in ps}
    means = []
    for _ in range(n_boot):
        pick = rng.choice(uc, size=len(uc), replace=True)
        idx = np.concatenate([idx_by_c[c] for c in pick])
        if np.sum(event[idx]) < 3:
            continue
        try:
            f = weibull_mle(q[idx], event[idx])
        except Exception:
            continue
        if not np.isfinite(f["shape_k"]) or f["shape_k"] <= 0 or f["shape_k"] > 500:
            continue
        ks.append(f["shape_k"]); lams.append(f["scale_lambda"]); means.append(f["mean"])
        for p in ps:
            qps[p].append(weibull_q_at_p(f, p))
    out = dict(n_boot_ok=len(ks),
               shape_k_ci=[float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))],
               scale_ci=[float(np.percentile(lams, 2.5)), float(np.percentile(lams, 97.5))],
               mean_ci=[float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))])
    for p in ps:
        out[f"q_at_p{int(p*100):02d}_ci"] = [float(np.percentile(qps[p], 2.5)),
                                             float(np.percentile(qps[p], 97.5))]
    return out


def cluster_bootstrap_cdf_band(q, event, cluster, grid, n_boot=600, seed=999):
    """Pointwise 95% band on the fitted Weibull breakdown-probability curve."""
    rng = np.random.RandomState(seed)
    q = np.asarray(q, float); event = np.asarray(event, int); cl = np.asarray(cluster)
    uc = np.unique(cl); idx_by_c = {c: np.where(cl == c)[0] for c in uc}
    curves = []
    for _ in range(n_boot):
        pick = rng.choice(uc, size=len(uc), replace=True)
        idx = np.concatenate([idx_by_c[c] for c in pick])
        if np.sum(event[idx]) < 3:
            continue
        try:
            f = weibull_mle(q[idx], event[idx])
            curves.append(weibull_cdf(f, grid))
        except Exception:
            continue
    C = np.array(curves)
    return np.percentile(C, 2.5, axis=0), np.percentile(C, 97.5, axis=0)


# ---------------------------------------------------------------- counting noise
def poisson_counting_sd(q_vph, T_s):
    """SD contributed to a measured flow purely by Poisson arrival counting over T s.
    N ~ Poisson(qT/3600); q_hat = N*3600/T  =>  Var(q_hat) = q*3600/T."""
    return np.sqrt(np.asarray(q_vph, float) * 3600.0 / T_s)
