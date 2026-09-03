#!/usr/bin/env python3
"""STEP 2 + STEP 3 -- measure the noise floor BEFORE optimizing anything, and the
CRN variance-reduction factor.

Step 2: four fixed candidate plans (good / good-perturbed / mediocre / poor)
        evaluated on 40 independent characterization seeds each.
        -> mean, SD, 95% CI, and the minimum objective difference that is
           statistically RESOLVABLE at n = 1, 3, 5, 10 replications.

Step 3: Var(f(x1,s) - f(x2,s)) under CRN (same seed both plans) vs independent
        seeds, over 30+ pairs, for three plan pairs including a NEAR pair --
        the comparison an optimizer actually has to make.

Method from `quantify-sumo-run-to-run-variability` /
[[sumo-stochastic-variability-and-replication-design]].
"""
import json
import os

import numpy as np
from scipy import stats

import evalpool as EP
import sim_common as S

HERE = os.path.dirname(os.path.abspath(__file__))

# --- seed books.  DISJOINT by construction; held-out seeds (900+) appear nowhere here.
CRN_SEEDS = list(range(100, 140))          # 40 seeds, used for BOTH plans -> paired/CRN
IND_SEEDS = list(range(140, 180))          # 40 further seeds, used to build independent pairs

# --- four fixed candidate plans (11-vector: C, 5 splits, 5 offsets)
#  spacing 400 m at 13.89 m/s * ~0.85 => ~34 s progression step
PLANS = {
    "good":     [26.0, 0.56, 0.56, 0.56, 0.56, 0.56, 0.0, 8.0, 16.0, 24.0, 32.0],
    "good2":    [26.0, 0.58, 0.54, 0.57, 0.55, 0.56, 0.0, 9.0, 15.0, 25.0, 31.0],
    "mediocre": [60.0, 0.50, 0.50, 0.50, 0.50, 0.50, 0.0, 0.0, 0.0, 0.0, 0.0],
    "poor":     [110.0, 0.30, 0.30, 0.30, 0.30, 0.30, 0.0, 55.0, 10.0, 70.0, 20.0],
}


def ci95(a):
    a = np.asarray(a, float)
    n = len(a)
    sd = a.std(ddof=1)
    h = stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n)
    return a.mean(), sd, h, (a.mean() - h, a.mean() + h)


def main(cache=None):
    out = {}

    # ---------------- Step 2: noise floor on the CRN seed book -------------
    raw = {}
    for name, x in PLANS.items():
        if cache:
            res = [(o, {"incomplete": 0}) for o in cache["raw_crn_seedbook"][name]]
        else:
            res = EP.eval_many([(x, s) for s in CRN_SEEDS])
        raw[name] = [r[0] for r in res]
        inc = [r[1]["incomplete"] for r in res]
        m, sd, h, (lo, hi) = ci95(raw[name])
        out.setdefault("plans", {})[name] = {
            "x": x, "n": len(CRN_SEEDS), "mean": m, "sd": sd, "cv_pct": 100 * sd / m,
            "ci95_halfwidth": h, "ci95": [lo, hi],
            "min": float(np.min(raw[name])), "max": float(np.max(raw[name])),
            "mean_incomplete": float(np.mean(inc)),
        }
        print(f"{name:9s} mean={m:10.1f}  sd={sd:8.1f} ({100*sd/m:5.2f}%)  "
              f"95%CI=[{lo:.1f},{hi:.1f}]  range=[{min(raw[name]):.0f},{max(raw[name]):.0f}]")

    # ---------------- Step 2b: independent seed book (needed for step 3) ---
    raw_ind = {}
    for name, x in PLANS.items():
        if cache:
            raw_ind[name] = list(cache["raw_ind_seedbook"][name])
        else:
            raw_ind[name] = [r[0] for r in EP.eval_many([(x, s) for s in IND_SEEDS])]

    # ---------------- resolvable-difference thresholds ---------------------
    # sigma pooled over the four plans (they bracket the operating range)
    sds = np.array([out["plans"][k]["sd"] for k in PLANS])
    sigma_pool = float(np.sqrt((sds ** 2).mean()))
    # LOCAL sigma: pooled over the two near-optimal plans only.  This is the sigma
    # that actually governs whether an optimizer's winning margin is real, because
    # optimizers compare candidates near the optimum, not against a "poor" plan
    # whose SD is 3x larger.  Reporting only the globally-pooled sigma would
    # overstate the threshold by ~1.9x.
    sigma_local = float(np.sqrt(np.mean([out["plans"]["good"]["sd"] ** 2,
                                         out["plans"]["good2"]["sd"] ** 2])))
    mean_pool = float(np.mean([out["plans"][k]["mean"] for k in PLANS]))
    best_mean = float(out["plans"]["good"]["mean"])

    thresholds = {}
    for n in (1, 3, 5, 10):
        # two-sample, INDEPENDENT seeds, n reps each, sigma known from 40 reps
        mdd_ind = 1.96 * sigma_pool * np.sqrt(2.0 / n)
        mdd_loc = 1.96 * sigma_local * np.sqrt(2.0 / n)
        thresholds[n] = {
            "mdd_independent_abs": mdd_ind,
            "mdd_independent_pct_of_good": 100 * mdd_ind / best_mean,
            "mdd_local_independent_abs": mdd_loc,
            "mdd_local_independent_pct_of_good": 100 * mdd_loc / best_mean,
        }
    out["sigma_pooled"] = sigma_pool
    out["sigma_local_near_optimum"] = sigma_local
    out["mean_pooled"] = mean_pool
    out["good_mean"] = best_mean
    out["resolvable"] = thresholds
    print(f"\npooled sigma (all 4 plans) = {sigma_pool:.1f}")
    print(f"LOCAL sigma (near-optimal plans only) = {sigma_local:.1f}  "
          f"(good-plan mean = {best_mean:.1f})")
    for n in (1, 3, 5, 10):
        t = thresholds[n]
        print(f"  n={n:2d}: min resolvable diff, independent seeds -- "
              f"global {t['mdd_independent_abs']:9.1f} ({t['mdd_independent_pct_of_good']:5.2f}%)   "
              f"LOCAL {t['mdd_local_independent_abs']:9.1f} ({t['mdd_local_independent_pct_of_good']:5.2f}%)")

    # ---------------- Step 3: CRN vs independent --------------------------
    pairs = [("good", "mediocre"), ("good", "poor"), ("good", "good2")]
    crn = {}
    for a, b in pairs:
        fa = np.array(raw[a]);  fb = np.array(raw[b])
        d_crn = fa - fb                                   # same seed for both -> CRN
        # independent design: plan a on CRN_SEEDS, plan b on the DISJOINT IND_SEEDS
        fb_i = np.array(raw_ind[b])
        d_ind = fa - fb_i
        rho = float(np.corrcoef(fa, fb)[0, 1])
        v_crn = float(d_crn.var(ddof=1))
        v_ind = float(d_ind.var(ddof=1))
        v_ind_analytic = float(fa.var(ddof=1) + fb.var(ddof=1))
        vrf = v_ind / v_crn
        vrf_an = v_ind_analytic / v_crn
        # replications needed to resolve the true |mean diff| at 95%/normal approx
        true_diff = abs(fa.mean() - fb.mean())
        n_crn = (1.96 ** 2) * v_crn / max(true_diff ** 2, 1e-9)
        n_ind = (1.96 ** 2) * v_ind / max(true_diff ** 2, 1e-9)
        crn[f"{a}_vs_{b}"] = {
            "n_pairs": len(CRN_SEEDS), "rho_paired": rho,
            "mean_diff": float(fa.mean() - fb.mean()),
            "var_diff_CRN": v_crn, "var_diff_independent_empirical": v_ind,
            "var_diff_independent_analytic": v_ind_analytic,
            "VRF_empirical": vrf, "VRF_analytic": vrf_an,
            "sd_diff_CRN": float(np.sqrt(v_crn)),
            "sd_diff_independent": float(np.sqrt(v_ind)),
            "reps_needed_CRN": n_crn, "reps_needed_independent": n_ind,
            "mdd_CRN_n1": 1.96 * float(np.sqrt(v_crn)),
            "mdd_ind_n1": 1.96 * float(np.sqrt(v_ind)),
        }
        print(f"\nCRN pair {a} vs {b}: rho={rho:+.3f}  meanDiff={fa.mean()-fb.mean():+10.1f}")
        print(f"   Var(diff) CRN         = {v_crn:12.1f}  (sd {np.sqrt(v_crn):8.1f})")
        print(f"   Var(diff) independent = {v_ind:12.1f}  (sd {np.sqrt(v_ind):8.1f})  [analytic {v_ind_analytic:12.1f}]")
        print(f"   variance-reduction factor = {vrf:.2f}x empirical / {vrf_an:.2f}x analytic  "
              f"-> {'CRN HELPED' if vrf > 1 else 'CRN HURT'}")
    out["crn"] = crn

    # paired/CRN resolvable thresholds using the NEAR pair's paired SD
    sd_d_near = crn["good_vs_good2"]["sd_diff_CRN"]
    sd_d_ind_near = crn["good_vs_good2"]["sd_diff_independent"]
    for n in (1, 3, 5, 10):
        out["resolvable"][n]["mdd_CRN_paired_abs"] = 1.96 * sd_d_near / np.sqrt(n)
        out["resolvable"][n]["mdd_CRN_paired_pct_of_good"] = \
            100 * 1.96 * sd_d_near / np.sqrt(n) / best_mean
        out["resolvable"][n]["mdd_indpair_near_abs"] = 1.96 * sd_d_ind_near / np.sqrt(n)

    out["raw_crn_seedbook"] = {k: list(map(float, v)) for k, v in raw.items()}
    out["raw_ind_seedbook"] = {k: list(map(float, v)) for k, v in raw_ind.items()}
    out["CRN_SEEDS"] = CRN_SEEDS
    out["IND_SEEDS"] = IND_SEEDS
    json.dump(out, open(os.path.join(HERE, "results_noise_floor.json"), "w"), indent=2)

    # per-evaluation CSV log
    with open(os.path.join(HERE, "log_noise_floor.csv"), "w") as f:
        f.write("plan,seedbook,seed,objective\n")
        for k, v in raw.items():
            for s, o in zip(CRN_SEEDS, v):
                f.write(f"{k},crn,{s},{o:.2f}\n")
        for k, v in raw_ind.items():
            for s, o in zip(IND_SEEDS, v):
                f.write(f"{k},ind,{s},{o:.2f}\n")
    print("\nwrote results_noise_floor.json + log_noise_floor.csv")


if __name__ == "__main__":
    import sys
    c = None
    if "--from-cache" in sys.argv:
        c = json.load(open(os.path.join(HERE, "results_noise_floor.json")))
    main(c)
