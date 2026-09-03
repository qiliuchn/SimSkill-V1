"""
Conflict-to-crash transfer function: fit, cross-validate, and state its limits.

Fits  ln(N_true) = b0 + b1 * ln(conflict measure)  across the site inventory,
by ordinary least squares, with leave-one-out cross-validation and a
leave-one-CONTROL-TYPE-out test (the harder, more honest generalisation test:
can a function fitted on signalized sites predict stop-controlled sites?).

Reports R^2, LOO-R^2, RMSE in log space, and a 95% PREDICTION interval
(not a confidence interval on the mean) since the policy question is
"what crash frequency does this site have", not "what is the mean trend".

Also fits the naive proportional model  N_true = alpha * conflicts  (one free
parameter, the "conflicts per crash" factor that a benefit-cost analysis
actually needs) and reports how far that single factor varies across sites --
which is the quantity that determines whether the factor can be treated as a
constant at all.
"""
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def ols(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, p = X.shape
    dof = n - p
    s2 = float(resid @ resid / dof)
    XtXi = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(XtXi) * s2)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    ss_res = float(resid @ resid)
    return dict(beta=beta, se=se, s2=s2, dof=dof, XtXi=XtXi,
                r2=1 - ss_res / ss_tot,
                r2_adj=1 - (ss_res / dof) / (ss_tot / (n - 1)),
                rmse=math.sqrt(ss_res / n))


def pred_interval(fit, x_row, alpha=0.05):
    """95% prediction interval half-width for a new observation at x_row."""
    t = stats.t.ppf(1 - alpha / 2, fit["dof"])
    lev = float(x_row @ fit["XtXi"] @ x_row)
    return t * math.sqrt(fit["s2"] * (1.0 + lev))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-table", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--predictor", default="sim_conf_rate_mev")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    rows = list(csv.DictReader(open(a.site_table)))
    sites = [r["site"] for r in rows]
    ctrl = [r["control"] for r in rows]
    y_tot = np.log(np.array([float(r["n_true"]) for r in rows]))
    y_ang = np.log(np.array([float(r["n_true_angle"]) for r in rows]))
    n_true = np.array([float(r["n_true"]) for r in rows])
    n_ang = np.array([float(r["n_true_angle"]) for r in rows])

    specs = [
        ("total ~ conflict_rate", "sim_conf_rate_mev", y_tot, n_true),
        ("total ~ conflict_freq", "sim_conflicts", y_tot, n_true),
        ("total ~ severe_conflict_rate", "sim_severe_ttc_rate_mev", y_tot, n_true),
        ("angle ~ crossing_conflict_rate", "sim_crossing_rate_mev", y_ang, n_ang),
        ("angle ~ crossing_conflict_freq", "sim_conf_crossing", y_ang, n_ang),
    ]

    out, per_site = [], []
    for label, pred, y, y_lin in specs:
        x = np.log(np.array([max(float(r[pred]), 1e-9) for r in rows]))
        X = np.column_stack([np.ones_like(x), x])
        fit = ols(X, y)

        # leave-one-out
        loo_err = []
        for i in range(len(y)):
            m = np.ones(len(y), bool); m[i] = False
            f = ols(X[m], y[m])
            loo_err.append(y[i] - float(X[i] @ f["beta"]))
        loo_err = np.array(loo_err)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        loo_r2 = 1 - float(loo_err @ loo_err) / ss_tot
        loo_rmse = math.sqrt(float(loo_err @ loo_err) / len(y))

        # leave-one-CONTROL-TYPE-out
        lcto = {}
        for c in sorted(set(ctrl)):
            m = np.array([cc != c for cc in ctrl])
            if m.sum() < 4 or (~m).sum() < 1:
                continue
            f = ols(X[m], y[m])
            e = y[~m] - X[~m] @ f["beta"]
            lcto[c] = dict(n_held_out=int((~m).sum()),
                           rmse_log=round(float(np.sqrt((e * e).mean())), 4),
                           mean_bias_log=round(float(e.mean()), 4),
                           median_ratio=round(float(np.exp(np.median(e))), 4))

        pi = [pred_interval(fit, X[i]) for i in range(len(y))]
        out.append(dict(model=label, predictor=pred, n=len(y),
                        b0=round(float(fit["beta"][0]), 4),
                        b0_se=round(float(fit["se"][0]), 4),
                        b1=round(float(fit["beta"][1]), 4),
                        b1_se=round(float(fit["se"][1]), 4),
                        b1_t=round(float(fit["beta"][1] / fit["se"][1]), 3),
                        b1_p=round(float(2 * (1 - stats.t.cdf(abs(fit["beta"][1] / fit["se"][1]),
                                                              fit["dof"]))), 6),
                        r2=round(fit["r2"], 4), r2_adj=round(fit["r2_adj"], 4),
                        loo_r2=round(loo_r2, 4),
                        rmse_log=round(fit["rmse"], 4), loo_rmse_log=round(loo_rmse, 4),
                        pred_interval_halfwidth_log_median=round(float(np.median(pi)), 4),
                        pred_interval_multiplicative=round(float(np.exp(np.median(pi))), 3),
                        leave_one_control_type_out=json.dumps(lcto)))

        if pred == a.predictor:
            for i, s in enumerate(sites):
                fitted = float(X[i] @ fit["beta"])
                per_site.append(dict(site=s, control=ctrl[i],
                                     predictor_value=round(float(np.exp(x[i])), 2),
                                     n_true=round(float(y_lin[i]), 4),
                                     fitted=round(math.exp(fitted), 4),
                                     ratio_fitted_over_true=round(math.exp(fitted) / y_lin[i], 4),
                                     pi95_lo=round(math.exp(fitted - pi[i]), 4),
                                     pi95_hi=round(math.exp(fitted + pi[i]), 4)))

    # ---- naive single-factor "conflicts per crash" -------------------------
    conf = np.array([float(r["sim_conflicts"]) for r in rows])
    cross = np.array([float(r["sim_conf_crossing"]) for r in rows])
    # conflicts observed in ONE peak hour; scale to a year of equivalent peak
    # hours to make the factor interpretable.  ASSUMED: 500 equivalent peak
    # hours/year and 25% of crashes occurring in them -- the same stated
    # assumption set used by `appraise-project-alternatives-with-benefit-cost-analysis`.
    PEAK_HOURS = 500.0
    PEAK_SHARE = 0.25
    factor_tot = (conf * PEAK_HOURS) / (n_true * PEAK_SHARE)
    factor_ang = (cross * PEAK_HOURS) / (n_ang * PEAK_SHARE)
    fac = dict(peak_hours_per_year=PEAK_HOURS, peak_share_of_crashes=PEAK_SHARE,
               total_min=float(factor_tot.min()), total_max=float(factor_tot.max()),
               total_median=float(np.median(factor_tot)),
               total_spread_ratio=float(factor_tot.max() / factor_tot.min()),
               angle_min=float(factor_ang.min()), angle_max=float(factor_ang.max()),
               angle_median=float(np.median(factor_ang)),
               angle_spread_ratio=float(factor_ang.max() / factor_ang.min()))
    fac["by_site"] = {s: round(float(v), 0) for s, v in zip(sites, factor_tot)}
    fac["by_control_median"] = {c: round(float(np.median(factor_tot[[i for i in range(len(sites))
                                                                    if ctrl[i] == c]])), 0)
                                for c in sorted(set(ctrl))}

    with open(os.path.join(a.out_dir, "transfer_function_models.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    with open(os.path.join(a.out_dir, "transfer_function_per_site.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_site[0].keys()))
        w.writeheader(); w.writerows(per_site)
    json.dump(fac, open(os.path.join(a.out_dir, "conflicts_per_crash_factor.json"), "w"), indent=2)

    print("%-34s %8s %8s %8s %10s %12s" % ("model", "b1", "R2", "LOO-R2", "rmse_log", "PI x/÷"))
    for r in out:
        print("%-34s %8.3f %8.3f %8.3f %10.3f %12.2f" %
              (r["model"], r["b1"], r["r2"], r["loo_r2"], r["rmse_log"],
               r["pred_interval_multiplicative"]))
    print("\nconflicts-per-crash factor: median %.0f, range %.0f..%.0f (%.1fx spread)" %
          (fac["total_median"], fac["total_min"], fac["total_max"], fac["total_spread_ratio"]))
    print("by control type:", fac["by_control_median"])
    for r in out:
        print("\n%s leave-one-control-type-out: %s" % (r["model"], r["leave_one_control_type_out"]))


if __name__ == "__main__":
    main()
