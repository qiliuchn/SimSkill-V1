"""
Countermeasure before/after with a published-CMF cross-check, plus the
matched-pair "operational blindness" test.

Both comparisons are paired on the seed family (Common Random Numbers): the
treated variant reuses the parent site's demand definition and the identical
seed list, so the paired difference removes the shared arrival-process noise.
Per `quantify-sumo-run-to-run-variability`, CRN is NOT assumed to help -- the
paired correlation and the realised variance-reduction factor are measured and
reported for every metric.

Cross-check logic
-----------------
  simulated ratio  = mean(after) / mean(before)   for a conflict category
  CMF              = published crash ratio for the SAME treatment and the
                     TYPE-MATCHED crash category
  disagreement     = simulated ratio / CMF, and the CMF's own 95% interval
                     where the source publishes a standard error.
"""
import argparse
import csv
import json
import math
import os
import statistics as st
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hsm

METRICS = ["conflicts", "conf_crossing", "conf_rear_end", "conf_merge",
           "severe_ttc", "severe_ttc_crossing", "conf_rate_mev",
           "crossing_rate_mev", "rear_end_rate_mev",
           "mean_timeloss", "mean_waiting", "mean_duration", "entering"]


def load(csv_path):
    by = {}
    for r in csv.DictReader(open(csv_path)):
        by.setdefault(r["site"], {})[int(r["seed"])] = r
    return by


def paired(before, after, metric):
    seeds = sorted(set(before) & set(after))
    b = np.array([float(before[s][metric]) for s in seeds])
    a = np.array([float(after[s][metric]) for s in seeds])
    d = a - b
    n = len(seeds)
    res = dict(metric=metric, n_pairs=n,
               before_mean=float(b.mean()), before_sd=float(b.std(ddof=1)),
               after_mean=float(a.mean()), after_sd=float(a.std(ddof=1)),
               diff_mean=float(d.mean()), diff_sd=float(d.std(ddof=1)))
    res["ratio"] = res["after_mean"] / res["before_mean"] if res["before_mean"] else None
    res["pct_change"] = 100.0 * (res["ratio"] - 1.0) if res["ratio"] is not None else None
    t, p = stats.ttest_rel(a, b)
    res["paired_t"] = float(t)
    res["paired_p"] = float(p)
    tw, pw = stats.ttest_ind(a, b, equal_var=False)
    res["welch_t"] = float(tw)
    res["welch_p"] = float(pw)
    rho = float(np.corrcoef(b, a)[0, 1]) if n > 2 else float("nan")
    res["paired_corr"] = rho
    var_indep = b.var(ddof=1) + a.var(ddof=1)
    res["variance_reduction_factor"] = float(var_indep / d.var(ddof=1)) if d.var(ddof=1) > 0 else None
    hw = stats.t.ppf(0.975, n - 1) * d.std(ddof=1) / math.sqrt(n)
    res["diff_ci95_lo"] = float(d.mean() - hw)
    res["diff_ci95_hi"] = float(d.mean() + hw)
    res["ratio_ci95_lo"] = (res["before_mean"] + res["diff_ci95_lo"]) / res["before_mean"]
    res["ratio_ci95_hi"] = (res["before_mean"] + res["diff_ci95_hi"]) / res["before_mean"]
    # noise floor: minimum detectable difference of THIS paired design
    res["mdd_abs"] = float((stats.t.ppf(0.975, n - 1) + stats.t.ppf(0.80, n - 1))
                           * d.std(ddof=1) / math.sqrt(n))
    res["mdd_pct_of_before"] = 100.0 * res["mdd_abs"] / res["before_mean"] if res["before_mean"] else None
    res["effect_over_noise_floor"] = (abs(res["diff_mean"]) / res["mdd_abs"]
                                      if res["mdd_abs"] > 0 else None)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-csv", required=True)
    ap.add_argument("--var-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    base, var = load(a.base_csv), load(a.var_csv)
    allsites = dict(base)
    allsites.update(var)

    comparisons = [
        # (label, before_site, after_site, note)
        ("countermeasure_perm_to_protonly", "S06", "S06_prot",
         "worst-ranked signalized site: permissive -> protected-only major lefts"),
        ("countermeasure_perm_to_protperm", "S06", "S06_protperm",
         "same site: permissive -> protected/permissive major lefts"),
        ("phasing_triplet_perm_to_protperm", "S07", "S08",
         "matched-AADT triplet: permissive vs protected/permissive"),
        ("phasing_triplet_perm_to_protonly", "S07", "S09",
         "matched-AADT triplet: permissive vs protected-only"),
        ("matchedpair_cycle60_to_cycle140", "S19", "S20",
         "IDENTICAL SPF covariates incl. phasing; only the cycle length differs"),
        ("matchedpair_cycle60_to_cycle35", "S19", "S19_c35",
         "same, 35 s cycle"),
        ("matchedpair_cycle60_to_cycle100", "S19", "S19_c100",
         "same, 100 s cycle"),
    ]

    rows = []
    for label, b_id, a_id, note in comparisons:
        if b_id not in allsites or a_id not in allsites:
            print("skip", label)
            continue
        for m in METRICS:
            r = paired(allsites[b_id], allsites[a_id], m)
            r.update(comparison=label, before_site=b_id, after_site=a_id, note=note)
            rows.append(r)

    keys = ["comparison", "before_site", "after_site", "metric", "n_pairs",
            "before_mean", "before_sd", "after_mean", "after_sd", "diff_mean",
            "diff_sd", "ratio", "pct_change", "ratio_ci95_lo", "ratio_ci95_hi",
            "paired_t", "paired_p", "welch_p", "paired_corr",
            "variance_reduction_factor", "mdd_abs", "mdd_pct_of_before",
            "effect_over_noise_floor", "note"]
    with open(os.path.join(a.out_dir, "before_after_paired.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v)
                        for k, v in r.items() if k in keys})

    # ---------------- CMF cross-check ----------------
    def get(label, metric):
        for r in rows:
            if r["comparison"] == label and r["metric"] == metric:
                return r
        return None

    checks = []
    cmf_specs = [
        # comparison, sim_metric, crash category, CMF, SE, source
        ("countermeasure_perm_to_protonly", "conf_crossing", "angle / left-turn",
         hsm.CMF_ANGLE["prot"], None,
         "Hauer (2004) via FHWA-HRT-18-044 p.7: CMF ~0.30 for left-turn crashes; no SE published"),
        ("countermeasure_perm_to_protonly", "conf_rear_end", "rear-end",
         hsm.CMF_REAR_END["prot"], None,
         "ASSUMED equal to Srinivasan et al. protected/permissive value 1.075; no protected-only value found"),
        ("countermeasure_perm_to_protonly", "conflicts", "total",
         hsm.CMF_TOTAL["prot"], None,
         "Hauer (2004) via FHWA-HRT-18-044 p.7: CMF ~1.0 for non-left-turn crashes; no SE published"),
        ("countermeasure_perm_to_protperm", "conf_crossing", "angle / left-turn-opposing",
         hsm.CMF_ANGLE["protperm"], None,
         "Srinivasan et al. via FHWA-HRT-18-044 p.7: CMF 0.862 left-turn-opposing; no SE published"),
        ("countermeasure_perm_to_protperm", "conf_rear_end", "rear-end",
         hsm.CMF_REAR_END["protperm"], None,
         "Srinivasan et al. via FHWA-HRT-18-044 p.7: CMF 1.075 rear-end; no SE published"),
        ("countermeasure_perm_to_protperm", "conflicts", "total",
         hsm.CMF_TOTAL["protperm"], hsm.CMF_TOTAL_SE["protperm"],
         "FHWA-HRT-18-044 Table 35: veh-veh all severities CMF 1.023, SE 0.016 (not significant)"),
        ("phasing_triplet_perm_to_protperm", "conf_crossing", "angle / left-turn-opposing",
         hsm.CMF_ANGLE["protperm"], None, "as above"),
        ("phasing_triplet_perm_to_protperm", "conflicts", "total",
         hsm.CMF_TOTAL["protperm"], hsm.CMF_TOTAL_SE["protperm"], "as above"),
        ("phasing_triplet_perm_to_protonly", "conf_crossing", "angle / left-turn",
         hsm.CMF_ANGLE["prot"], None, "as above"),
        ("phasing_triplet_perm_to_protonly", "conflicts", "total",
         hsm.CMF_TOTAL["prot"], None, "as above"),
    ]
    for label, metric, cat, cmf, se, src in cmf_specs:
        r = get(label, metric)
        if not r:
            continue
        c = dict(comparison=label, sim_metric=metric, crash_category=cat,
                 sim_ratio=round(r["ratio"], 4),
                 sim_ratio_ci95_lo=round(r["ratio_ci95_lo"], 4),
                 sim_ratio_ci95_hi=round(r["ratio_ci95_hi"], 4),
                 sim_pct_change=round(r["pct_change"], 2),
                 published_cmf=cmf, published_cmf_se=se,
                 cmf_pct_change=round(100.0 * (cmf - 1.0), 2),
                 disagreement_ratio=round(r["ratio"] / cmf, 4),
                 cmf_in_sim_ci=bool(r["ratio_ci95_lo"] <= cmf <= r["ratio_ci95_hi"]),
                 paired_p=round(r["paired_p"], 6),
                 effect_over_noise_floor=round(r["effect_over_noise_floor"], 3),
                 cmf_source=src)
        if se:
            c["cmf_ci95_lo"] = round(cmf - 1.96 * se, 4)
            c["cmf_ci95_hi"] = round(cmf + 1.96 * se, 4)
        checks.append(c)

    with open(os.path.join(a.out_dir, "cmf_crosscheck.csv"), "w", newline="") as f:
        keys = sorted({k for c in checks for k in c})
        head = ["comparison", "sim_metric", "crash_category", "sim_ratio",
                "sim_ratio_ci95_lo", "sim_ratio_ci95_hi", "sim_pct_change",
                "published_cmf", "published_cmf_se", "cmf_ci95_lo", "cmf_ci95_hi",
                "cmf_pct_change", "disagreement_ratio", "cmf_in_sim_ci",
                "paired_p", "effect_over_noise_floor", "cmf_source"]
        head += [k for k in keys if k not in head]
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        w.writerows(checks)

    print("=== CMF cross-check ===")
    print("%-38s %-14s %8s %8s %10s %6s" %
          ("comparison", "sim metric", "sim", "CMF", "disagree", "p"))
    for c in checks:
        print("%-38s %-14s %8.3f %8.3f %10.2fx %6.4f" %
              (c["comparison"], c["sim_metric"], c["sim_ratio"], c["published_cmf"],
               c["disagreement_ratio"], c["paired_p"]))

    print("\n=== matched pair (identical SPF covariates) ===")
    for m in ("conflicts", "conf_crossing", "conf_rear_end", "conf_rate_mev", "mean_timeloss"):
        for label in ("matchedpair_cycle60_to_cycle35", "matchedpair_cycle60_to_cycle100",
                      "matchedpair_cycle60_to_cycle140"):
            r = get(label, m)
            if r:
                print("%-34s %-16s %9.1f -> %9.1f  %+7.2f%%  p=%.2g  effect/noisefloor=%.2f" %
                      (label, m, r["before_mean"], r["after_mean"], r["pct_change"],
                       r["paired_p"], r["effect_over_noise_floor"]))
    print("\nwrote", a.out_dir)


if __name__ == "__main__":
    main()
