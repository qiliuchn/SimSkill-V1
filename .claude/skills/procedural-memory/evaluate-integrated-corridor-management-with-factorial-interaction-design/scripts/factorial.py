#!/usr/bin/env python3
"""
Reusable 2^k factorial / interaction estimator (sub-goal 8 artifact: written
to be reusable for any future 2^k policy comparison, not just this corridor).

Given per-arm-per-seed observations of a scalar response Y, where each arm is
identified by k binary factor settings, estimate:
  - the grand mean and each factor's main effect (via OLS on +-1-coded
    factors and their pairwise products -- the classical 2^k regression form)
  - all C(k,2) two-way interaction effects
  - a CRN-paired bootstrap 95% CI for every effect (resampling whole SEEDS,
    not individual arm-seed rows, which is what a CRN design's pairing
    requires)
  - a "resolvable" gate: an effect is reported resolvable only if its CI
    excludes zero AND its magnitude exceeds 2x a supplied noise floor.

Pure numpy + stdlib (no pandas dependency). Input is a list of dict rows:
    {"seed": 1, "D": 0, "M": 1, "S": 0, "V": 1, "y": 1234.5}
"""
import itertools

import numpy as np


def _rows_to_arrays(rows, factors, y_col):
    seeds = np.array([r["seed"] for r in rows])
    Y = np.array([r[y_col] for r in rows], dtype=float)
    F = {f: np.array([r[f] for r in rows], dtype=float) for f in factors}
    return seeds, Y, F


def build_design_matrix(rows, factors):
    n = len(rows)
    cols = {"I": np.ones(n)}
    for f in factors:
        cols[f] = np.array([2 * r[f] - 1 for r in rows], dtype=float)  # {0,1}->{-1,+1}
    for f1, f2 in itertools.combinations(factors, 2):
        cols[f"{f1}:{f2}"] = cols[f1] * cols[f2]
    names = list(cols.keys())
    X = np.column_stack([cols[n_] for n_ in names])
    return X, names


def fit_effects(rows, factors, y_col="y"):
    X, names = build_design_matrix(rows, factors)
    y = np.array([r[y_col] for r in rows], dtype=float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return dict(zip(names, beta)), (X, names)


def crn_paired_bootstrap_ci(rows, factors, y_col="y", n_boot=2000, seed=0, alpha=0.05):
    """Resample whole seeds with replacement (preserving each seed's full set
    of arm outcomes -- the CRN pairing), refit, and report a percentile CI
    per term."""
    rng = np.random.default_rng(seed)
    seeds = sorted({r["seed"] for r in rows})
    ns = len(seeds)
    by_seed = {s: [r for r in rows if r["seed"] == s] for s in seeds}
    term_names = None
    boot_coefs = []
    for _ in range(n_boot):
        chosen = rng.choice(seeds, size=ns, replace=True)
        boot_rows = []
        for s in chosen:
            boot_rows.extend(by_seed[s])
        coefs, _ = fit_effects(boot_rows, factors, y_col)
        if term_names is None:
            term_names = list(coefs.keys())
        boot_coefs.append([coefs[t] for t in term_names])
    arr = np.array(boot_coefs)
    lo = np.percentile(arr, 100 * alpha / 2, axis=0)
    hi = np.percentile(arr, 100 * (1 - alpha / 2), axis=0)
    return dict(zip(term_names, zip(lo.tolist(), hi.tolist())))


def analyze(rows, factors, y_col="y", noise_floor=None, n_boot=2000, seed=0):
    """rows: list of dicts, one per (arm, seed), each with 0/1 factor columns
    and the response in y_col. Returns {"grand_mean":..., "effects":[...]}."""
    point, _ = fit_effects(rows, factors, y_col)
    cis = crn_paired_bootstrap_ci(rows, factors, y_col, n_boot=n_boot, seed=seed)
    out = []
    for term, eff in point.items():
        if term == "I":
            continue
        lo, hi = cis[term]
        significant = not (lo <= 0 <= hi)
        resolvable = significant and (noise_floor is None or abs(eff) > 2 * noise_floor)
        kind = "main" if ":" not in term else "interaction"
        out.append(dict(term=term, kind=kind, effect=float(eff), ci_lo=float(lo), ci_hi=float(hi),
                         significant=bool(significant), resolvable=bool(resolvable)))
    out.sort(key=lambda r: (r["kind"], -abs(r["effect"])))
    return dict(grand_mean=float(point["I"]), effects=out)


def additivity_check(rows, factors, y_col="y"):
    """Classical sub-additivity test for claim (i): compare the measured
    combined-arm (all factors=1) delta from do-nothing against the sum of
    each single-factor main-effect delta."""
    def mean_where(pred):
        vals = [r[y_col] for r in rows if pred(r)]
        return sum(vals) / len(vals) if vals else None

    base = mean_where(lambda r: all(r[f] == 0 for f in factors))
    combined = mean_where(lambda r: all(r[f] == 1 for f in factors))
    combined_delta = combined - base
    singles_sum = 0.0
    singles = {}
    for f in factors:
        on = mean_where(lambda r, f=f: r[f] == 1 and all(r[g] == 0 for g in factors if g != f))
        delta = on - base
        singles[f] = delta
        singles_sum += delta
    return dict(base=base, combined=combined, combined_delta=combined_delta,
                single_deltas=singles, sum_of_individual_deltas=singles_sum,
                sub_additive=(abs(combined_delta) < abs(singles_sum)) if singles_sum * combined_delta > 0 else None,
                ratio_combined_over_sum=(combined_delta / singles_sum) if singles_sum != 0 else None)
