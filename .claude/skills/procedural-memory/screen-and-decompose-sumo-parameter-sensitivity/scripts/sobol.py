#!/usr/bin/env python3
"""STEP 5a -- GENUINE VARIANCE-BASED (SOBOL') SENSITIVITY ANALYSIS of the
top-screened factors, with FIRST-ORDER, TOTAL-ORDER and SECOND-ORDER
(interaction) indices.

"Sobol" appears as an unimplemented keyword in
`calibrate-car-following-parameters-against-field-targets`; nothing in memory
had ever actually computed a Sobol index on a SUMO model.  This script does.

Design: SALTELLI cross-sampling.
  * A, B  : two N x k matrices, the two halves of a SCRAMBLED SOBOL' SEQUENCE
            of dimension 2k (scipy.stats.qmc.Sobol -- no SALib in this env,
            so the sampler is written here from the primitive scipy QMC engine).
  * AB_i  : A with column i replaced by B's column i
  * BA_i  : B with column i replaced by A's column i
  -> N*(2k+2) model evaluations, which is what SECOND-ORDER indices require.

Estimators (Saltelli et al. 2010; Jansen 1999; Saltelli 2002):
  S_i   = mean_m[ B_m * (AB_i,m - A_m) ] / V          (first order)
  ST_i  = 0.5 * mean_m[ (A_m - AB_i,m)^2 ] / V        (total order, Jansen)
  V_ij  = mean_m[ BA_i,m * AB_j,m - A_m * B_m ] / V   (closed second order)
  S_ij  = V_ij - S_i - S_j                            (pure interaction)

V is the variance of the pooled A,B responses.  Bootstrap CIs (resampling the
N rows) are reported for every index.

Every evaluation is the mean over NSEED common-random-number seeds, so the
seed-noise contribution to V is reduced by 1/NSEED; the residual noise share of
V is reported explicitly from the STEP-2 noise floor.

Usage: sobol.py <regime> [N_base] [n_seeds] [n_factors]
"""
import os, sys, json, math, itertools
import numpy as np
from scipy.stats import qmc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gsa_common as G

REGIME = sys.argv[1] if len(sys.argv) > 1 else "over"
NBASE = int(sys.argv[2]) if len(sys.argv) > 2 else 64
NSEED = int(sys.argv[3]) if len(sys.argv) > 3 else 2
NFAC = int(sys.argv[4]) if len(sys.argv) > 4 else 4
SEEDS = tuple(1001 + 13 * i for i in range(NSEED))
MOES = ["arrived", "timeloss_per_km", "queue_mean_m", "queue_max_m", "co2_kg"]
NBOOT = 2000


def pick_factors():
    """Top-NFAC factors by rank-aggregation of mu* across the four primary MOEs
    in the SAME regime, taken from STEP 3's saved table (not re-derived)."""
    M = json.load(open(os.path.join(G.TBL, "morris.json")))
    t = M["regimes"][REGIME]["table"]
    score = {n: 0.0 for n in G.NAMES}
    for m in ["arrived", "timeloss_per_km", "queue_mean_m", "co2_kg"]:
        rows = t[m]
        for rank, r in enumerate(rows):
            score[r["factor"]] += rank            # lower = more influential
    order = sorted(G.NAMES, key=lambda n: score[n])
    return order[:NFAC], {n: score[n] for n in order}


def saltelli(k, N, seed=20260806):
    eng = qmc.Sobol(d=2 * k, scramble=True, seed=seed)
    X = eng.random(N)
    A, B = X[:, :k], X[:, k:]
    AB = {}
    BA = {}
    for i in range(k):
        M = A.copy(); M[:, i] = B[:, i]; AB[i] = M
        M = B.copy(); M[:, i] = A[:, i]; BA[i] = M
    return A, B, AB, BA


def main():
    facs, score = pick_factors()
    k = len(facs)
    print("[sobol] regime=%s  factors=%s  N=%d  -> N*(2k+2)=%d points x %d seeds "
          "= %d SUMO runs" % (REGIME, facs, NBASE, NBASE * (2 * k + 2), NSEED,
                              NBASE * (2 * k + 2) * NSEED))
    A, B, AB, BA = saltelli(k, NBASE)

    blocks = [("A", A), ("B", B)]
    for i in range(k):
        blocks.append(("AB%d" % i, AB[i]))
    for i in range(k):
        blocks.append(("BA%d" % i, BA[i]))

    plist, index = [], []
    for name, Mx in blocks:
        for row in Mx:
            p = dict(G.DEFAULTS)
            for f, x in zip(facs, row):
                lo, hi = G.SPACE[f]
                p[f] = lo + float(x) * (hi - lo)
            plist.append(p); index.append(name)
    res = G.evaluate(plist, REGIME, seeds=SEEDS)
    nfail = sum(1 for r in res if not r["ok"])
    print("[sobol] failed evaluations: %d/%d" % (nfail, len(res)))

    Y = {}
    ptr = 0
    for name, Mx in blocks:
        Y[name] = {m: np.array([res[ptr + j].get(m, np.nan)
                                for j in range(len(Mx))], dtype=float)
                   for m in MOES}
        ptr += len(Mx)

    NF = json.load(open(os.path.join(G.TBL, "noise_floor.json")))
    nfrows = {r["metric"]: r for r in NF["regimes"][REGIME]["rows"]}

    # ---- STANDARDISE Y before applying the estimators -------------------
    # NOT cosmetic.  The Saltelli first-order estimator  mean[B*(AB-A)]  is
    # applied to RAW outputs whose mean is orders of magnitude larger than
    # their spread (e.g. 'arrived' ~ 4700 +- 300), so the products carry an
    # enormous common term and the Monte-Carlo error swamps the signal: a
    # first pass without standardisation returned S1 = 0.60 for `sigma` with a
    # bootstrap 95% CI of [-0.96, 2.36].  SALib standardises Y over ALL
    # evaluations before analysing, and so do we.  ST (Jansen) is a difference
    # estimator and is much less affected, which is exactly what was observed.
    ALLY = {m: np.concatenate([Y[name][m] for name, _ in blocks]) for m in MOES}
    STD = {m: (float(np.nanmean(ALLY[m])), float(np.nanstd(ALLY[m]))) for m in MOES}
    Yz = {name: {m: (Y[name][m] - STD[m][0]) / STD[m][1] for m in MOES}
          for name, _ in blocks}
    Yraw = Y
    Y = Yz

    out = {}
    for m in MOES:
        ya, yb = Y["A"][m], Y["B"][m]
        pooled = np.concatenate([ya, yb])
        V = float(np.var(pooled, ddof=1))
        # noise share of V: variance of the CRN-mean of NSEED seeds
        sd_seed = nfrows[m]["sd"] / STD[m][1]      # in standardised units
        V_noise = (sd_seed ** 2) / NSEED
        rows = []
        for i, f in enumerate(facs):
            yab = Y["AB%d" % i][m]
            S1 = float(np.mean(yb * (yab - ya)) / V)
            ST = float(0.5 * np.mean((ya - yab) ** 2) / V)
            rows.append(dict(factor=f, S1=S1, ST=ST))
        # second order
        s2 = []
        for i, j in itertools.combinations(range(k), 2):
            ybai = Y["BA%d" % i][m]
            yabj = Y["AB%d" % j][m]
            Vij = float(np.mean(ybai * yabj - ya * yb) / V)
            Si = rows[i]["S1"]; Sj = rows[j]["S1"]
            s2.append(dict(pair=[facs[i], facs[j]], S2_closed=Vij,
                           S2=Vij - Si - Sj))

        # bootstrap over the N rows
        rng = np.random.default_rng(7)
        bs1 = {f: [] for f in facs}
        bst = {f: [] for f in facs}
        bs2 = {tuple(d["pair"]): [] for d in s2}
        for _ in range(NBOOT):
            idx = rng.integers(0, NBASE, NBASE)
            a, b = ya[idx], yb[idx]
            Vb = float(np.var(np.concatenate([a, b]), ddof=1))
            if Vb <= 0:
                continue
            s1v = {}
            for i, f in enumerate(facs):
                ab = Y["AB%d" % i][m][idx]
                v1 = float(np.mean(b * (ab - a)) / Vb)
                s1v[i] = v1
                bs1[f].append(v1)
                bst[f].append(float(0.5 * np.mean((a - ab) ** 2) / Vb))
            for i, j in itertools.combinations(range(k), 2):
                vij = float(np.mean(Y["BA%d" % i][m][idx] * Y["AB%d" % j][m][idx]
                                    - a * b) / Vb)
                bs2[(facs[i], facs[j])].append(vij - s1v[i] - s1v[j])

        def ci(v):
            v = np.array(v)
            return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
        for r in rows:
            r["S1_ci95"] = ci(bs1[r["factor"]])
            r["ST_ci95"] = ci(bst[r["factor"]])
            r["ST_minus_S1"] = r["ST"] - r["S1"]
        for d in s2:
            d["S2_ci95"] = ci(bs2[tuple(d["pair"])])
            d["significant"] = bool(d["S2_ci95"][0] > 0 or d["S2_ci95"][1] < 0)
        rows.sort(key=lambda r: -r["ST"])
        s2.sort(key=lambda d: -abs(d["S2"]))
        out[m] = dict(V=V, mean=float(np.mean(pooled)),
                      raw_mean=STD[m][0], raw_sd=STD[m][1],
                      standardised=True,
                      V_noise_estimate=V_noise,
                      noise_share_of_V=(V_noise / V if V > 0 else float("nan")),
                      sum_S1=float(sum(r["S1"] for r in rows)),
                      sum_ST=float(sum(r["ST"] for r in rows)),
                      first_total=rows, second_order=s2)

        print("\n--- SOBOL %s / %s   V=%.6g  sum(S1)=%.3f  sum(ST)=%.3f  "
              "noise share of V=%.4f ---"
              % (REGIME, m, V, out[m]["sum_S1"], out[m]["sum_ST"],
                 out[m]["noise_share_of_V"]))
        print("  %-16s %8s %18s %8s %18s %8s"
              % ("factor", "S1", "S1 95% CI", "ST", "ST 95% CI", "ST-S1"))
        for r in rows:
            print("  %-16s %8.4f [%7.4f,%7.4f] %8.4f [%7.4f,%7.4f] %8.4f"
                  % (r["factor"], r["S1"], r["S1_ci95"][0], r["S1_ci95"][1],
                     r["ST"], r["ST_ci95"][0], r["ST_ci95"][1], r["ST_minus_S1"]))
        print("  second order:")
        for d in s2:
            print("    %-32s S2=%8.4f  [%7.4f,%7.4f]  %s"
                  % (" x ".join(d["pair"]), d["S2"], d["S2_ci95"][0],
                     d["S2_ci95"][1], "SIGNIFICANT" if d["significant"] else "-"))

    # persist the raw model responses so the indices can be RE-DERIVED (by the
    # critic, or with a different estimator) without re-running SUMO
    json.dump(dict(regime=REGIME, factors=facs, N=NBASE, n_seeds=NSEED,
                   block_order=[name for name, _ in blocks],
                   unit_matrices={name: Mx.tolist() for name, Mx in blocks},
                   Y_raw={name: {m: Yraw[name][m].tolist() for m in MOES}
                          for name, _ in blocks}),
              open(os.path.join(G.TBL, "sobol_%s_rawY.json" % REGIME), "w"))

    path = os.path.join(G.TBL, "sobol_%s.json" % REGIME)
    json.dump(dict(regime=REGIME, factors=facs, N=NBASE, n_seeds=NSEED,
                   seeds=list(SEEDS), n_points=len(plist),
                   n_runs=len(plist) * NSEED, n_failed=nfail,
                   morris_rank_score=score, n_bootstrap=NBOOT,
                   factor_ranges={f: list(G.SPACE[f]) for f in facs},
                   fixed_at_default={n: G.DEFAULTS[n] for n in G.NAMES
                                     if n not in facs},
                   moes=out), open(path, "w"), indent=2)
    print("\nwrote", path)


if __name__ == "__main__":
    main()
