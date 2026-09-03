"""
Replication design for the conflict measure: noise floor and required n.

Method is the one in `quantify-sumo-run-to-run-variability`:
  * report the coefficient of variation of the metric across replications, per
    site, rather than assuming a single value for the whole jurisdiction;
  * required n from  n = (t_{n-1,0.975} * s / d)^2, solved by iteration on the
    t-quantile, with the degenerate n<2 case handled explicitly rather than
    trusted to a fixed number of fixed-point steps;
  * report the NOISE FLOOR -- the smallest difference in the metric that a given
    n can resolve -- as the minimum detectable difference (MDD) of a paired
    (Common Random Numbers) comparison, since all treatment comparisons in this
    study reuse one seed family.

In this scenario the only stochastic source is the simulation seed, which drives
Poisson arrival times (period="exp(rate)") and driver dispersion (sigma=0.5,
speedDev=0.1).  The demand-generation seed of `randomTrips.py` does not apply:
demand here is a fixed set of <flow> rates, so there is no route-sampling seed.
"""
import argparse
import csv
import json
import math
import os
import statistics as st
import sys

from scipy import stats

METRICS = ["conflicts", "conf_crossing", "conf_rear_end", "severe_ttc",
           "conf_rate_mev", "crossing_rate_mev", "mean_timeloss"]


def required_n(s, mean, rel_halfwidth=0.05, n_pilot=12):
    """n = (t_{n-1,.975} s / d)^2 with d = rel_halfwidth * mean."""
    if mean is None or mean <= 0 or s <= 0:
        return 2
    d = rel_halfwidth * mean
    n = max(2, n_pilot)
    for _ in range(200):
        t = stats.t.ppf(0.975, max(n - 1, 1))
        n_new = max(2, int(math.ceil((t * s / d) ** 2)))
        if n_new == n:
            break
        n = n_new
    return n


def mdd_paired(sd_diff, n, alpha=0.05, power=0.80):
    """Minimum detectable difference of a paired t-test at n pairs."""
    if n < 2 or sd_diff <= 0:
        return None
    t_a = stats.t.ppf(1 - alpha / 2, n - 1)
    t_b = stats.t.ppf(power, n - 1)
    return (t_a + t_b) * sd_diff / math.sqrt(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-csv", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--rel-halfwidth", type=float, default=0.05)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.metrics_csv)))
    by_site = {}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)

    out, summary = [], {}
    for site in sorted(by_site):
        rs = by_site[site]
        n = len(rs)
        rec = dict(site=site, n_replications=n)
        for m in METRICS:
            vals = [float(r[m]) for r in rs if r[m] not in ("", "None")]
            if len(vals) < 2:
                continue
            mu, sd = st.mean(vals), st.stdev(vals)
            cv = sd / mu if mu else float("nan")
            rec["%s_mean" % m] = round(mu, 4)
            rec["%s_sd" % m] = round(sd, 4)
            rec["%s_cv" % m] = round(cv, 5)
            rec["%s_req_n" % m] = required_n(sd, mu, a.rel_halfwidth, n)
            # noise floor if we compare two INDEPENDENT arms with n reps each
            # (conservative; a CRN-paired comparison does better, quantified
            #  separately in the countermeasure analysis)
            sd_diff = sd * math.sqrt(2.0)
            mdd = mdd_paired(sd_diff, n)
            rec["%s_mdd_abs" % m] = round(mdd, 4) if mdd else None
            rec["%s_mdd_pct" % m] = round(100.0 * mdd / mu, 3) if (mdd and mu) else None
        out.append(rec)

    with open(a.out_csv, "w", newline="") as f:
        keys = sorted({k for r in out for k in r})
        keys = ["site", "n_replications"] + [k for k in keys if k not in ("site", "n_replications")]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)

    for m in METRICS:
        cvs = [r["%s_cv" % m] for r in out if "%s_cv" % m in r]
        reqs = [r["%s_req_n" % m] for r in out if "%s_req_n" % m in r]
        mdds = [r["%s_mdd_pct" % m] for r in out if r.get("%s_mdd_pct" % m) is not None]
        summary[m] = dict(cv_min=min(cvs), cv_median=st.median(cvs), cv_max=max(cvs),
                          req_n_min=min(reqs), req_n_median=st.median(reqs), req_n_max=max(reqs),
                          mdd_pct_min=min(mdds), mdd_pct_median=st.median(mdds),
                          mdd_pct_max=max(mdds),
                          rel_halfwidth_target=a.rel_halfwidth,
                          n_used=out[0]["n_replications"])
    json.dump(summary, open(a.out_json, "w"), indent=2)

    print("%-20s %8s %8s %8s %7s %7s %7s %9s" %
          ("metric", "cv_min", "cv_med", "cv_max", "n_min", "n_med", "n_max", "mdd%_med"))
    for m, s in summary.items():
        print("%-20s %8.4f %8.4f %8.4f %7d %7.1f %7d %9.2f" %
              (m, s["cv_min"], s["cv_median"], s["cv_max"], s["req_n_min"],
               s["req_n_median"], s["req_n_max"], s["mdd_pct_median"]))
    print("\nwrote %s and %s" % (a.out_csv, a.out_json))


if __name__ == "__main__":
    main()
