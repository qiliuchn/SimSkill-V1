#!/usr/bin/env python3
"""STAGE 2 - verify what an UNENFORCED posted-limit reduction actually does to
the speed distribution in SUMO, and quantify how far that is from the field
evidence on unenforced limit changes.

Because SUMO's desired speed is speedFactor x posted_limit (multiplicative),
lowering the sign from 50 to 40 km/h must rescale the WHOLE realised
free-flow distribution by 40/50 = 0.8: mean, SD and every percentile shrink by
the same factor, and the FRACTION of drivers exceeding the posted limit is
invariant. That last quantity is the crisp diagnostic - a real unenforced limit
reduction raises the violation rate sharply; a multiplicative model cannot.

Measured from e1_instant.xml (per-vehicle E1 spot speeds) at x=600 and x=2000,
paired over the 8 CRN seeds. A two-sample KS statistic between the baseline
speeds and the rescaled (v/0.8) limit-40 speeds tests the "exact proportional
rescaling" hypothesis on the whole distribution, not just two moments.
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import analysis as A  # noqa: E402

SCALE = 40.0 / 50.0
LIM_BASE = A.LIMIT_MS              # 13.89 m/s  (posted 50)
LIM_RED = 40.0 / 3.6               # 11.111 m/s (posted 40)


def ks2(x, y):
    x = sorted(x); y = sorted(y)
    nx, ny = len(x), len(y)
    i = j = 0
    d = 0.0
    while i < nx and j < ny:
        if x[i] <= y[j]:
            i += 1
        else:
            j += 1
        d = max(d, abs(i / nx - j / ny))
    en = math.sqrt(nx * ny / (nx + ny))
    return d, 1.36 / en


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', default='1,2,3,4,5,6,7,8')
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(',')]
    res = {'scale_expected': SCALE, 'detectors': {}}

    for det in (600, 2000):
        per_seed = []
        pool_b, pool_r = [], []
        for s in seeds:
            b = A.spot_speeds_at(os.path.join(a.root, 'baseline', f'seed{s}',
                                              'e1_instant.xml'), det)
            r = A.spot_speeds_at(os.path.join(a.root, 'limit40', f'seed{s}',
                                              'e1_instant.xml'), det)
            pool_b += b; pool_r += r
            per_seed.append({
                'seed': s, 'n_base': len(b), 'n_red': len(r),
                'mean_ratio': A.mean(r) / A.mean(b),
                'sd_ratio': A.sd(r) / A.sd(b),
                'p85_ratio': A.pctl(r, 0.85) / A.pctl(b, 0.85),
                'cv_base': A.sd(b) / A.mean(b), 'cv_red': A.sd(r) / A.mean(r),
                'frac_over_own_limit_base': sum(1 for v in b if v > LIM_BASE) / len(b),
                'frac_over_own_limit_red': sum(1 for v in r if v > LIM_RED) / len(r),
                'frac_over_own_limit_plus10_base':
                    sum(1 for v in b if v > LIM_BASE + 10 / 3.6) / len(b),
                'frac_over_own_limit_plus10_red':
                    sum(1 for v in r if v > LIM_RED + 10 / 3.6) / len(r),
            })
        d, crit = ks2(pool_b, [v / SCALE for v in pool_r])
        res['detectors'][str(det)] = {
            'per_seed': per_seed,
            'mean_ratio': A.paired_ci([p['mean_ratio'] for p in per_seed]),
            'sd_ratio': A.paired_ci([p['sd_ratio'] for p in per_seed]),
            'p85_ratio': A.paired_ci([p['p85_ratio'] for p in per_seed]),
            'cv_base_mean': A.mean([p['cv_base'] for p in per_seed]),
            'cv_red_mean': A.mean([p['cv_red'] for p in per_seed]),
            'violation_rate_base': A.mean([p['frac_over_own_limit_base'] for p in per_seed]),
            'violation_rate_red': A.mean([p['frac_over_own_limit_red'] for p in per_seed]),
            'violation_rate_diff_ci': A.paired_ci(
                [p['frac_over_own_limit_red'] - p['frac_over_own_limit_base'] for p in per_seed]),
            'violation10_base': A.mean([p['frac_over_own_limit_plus10_base'] for p in per_seed]),
            'violation10_red': A.mean([p['frac_over_own_limit_plus10_red'] for p in per_seed]),
            'ks_baseline_vs_rescaled_limit40': d,
            'ks_crit_5pct': crit,
            'ks_rejects_exact_rescaling': d > crit,
            'n_pooled_base': len(pool_b), 'n_pooled_red': len(pool_r),
            'pooled_mean_base_kmh': A.mean(pool_b) * 3.6,
            'pooled_mean_red_kmh': A.mean(pool_r) * 3.6,
            'pooled_sd_base_kmh': A.sd(pool_b) * 3.6,
            'pooled_sd_red_kmh': A.sd(pool_r) * 3.6,
        }
        r_ = res['detectors'][str(det)]
        print(f"x={det}: mean ratio {r_['mean_ratio']['mean']:.5f} "
              f"[{r_['mean_ratio']['lo']:.5f},{r_['mean_ratio']['hi']:.5f}] "
              f"sd ratio {r_['sd_ratio']['mean']:.5f}  "
              f"violation {r_['violation_rate_base']:.4f} -> {r_['violation_rate_red']:.4f}  "
              f"KS {d:.4f} (crit {crit:.4f})")
    json.dump(res, open(a.out, 'w'), indent=2)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
