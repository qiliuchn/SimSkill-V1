#!/usr/bin/env python
"""CRN-paired hypothesis tests over the transit-scenario batch.

H2  timetable infeasibility: schedule deviation grows with background car demand,
    faster than linearly, with a demand level past which on-time performance
    collapses (negative control: rate=0 free-flow feasibility reference).
H3  representation: GTFS schedule-based departures vs. ptlines2flows headway flows
    at equal mean frequency -> passenger wait time and headway CV.
H4  dwell/schedule source: schedule-holding (until from stop_times) vs. purely
    endogenous dwell (no until) -> adherence conclusion and dwell attribution.

All comparisons are seed-paired (Common Random Numbers): the same seed drives the
car-demand generation and the simulation in every arm.
"""
import argparse
import csv
import json
import math
from collections import defaultdict

import numpy as np
from scipy import stats


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if k in ('run', 'arm'):
                    continue
                r[k] = float(v) if v not in ('', 'None') else None
            rows.append(r)
    return rows


def ci(v, conf=0.95):
    v = [x for x in v if x is not None]
    n = len(v)
    if n < 2:
        return {'n': n, 'mean': v[0] if v else None, 'lo': None, 'hi': None, 'sd': None}
    m = float(np.mean(v))
    sd = float(np.std(v, ddof=1))
    h = stats.t.ppf(0.5 + conf / 2, n - 1) * sd / math.sqrt(n)
    return {'n': n, 'mean': m, 'sd': sd, 'lo': m - h, 'hi': m + h}


def paired(a, b, conf=0.95):
    """a, b are dicts seed -> value"""
    seeds = sorted(set(a) & set(b))
    da = [a[s] for s in seeds]
    db = [b[s] for s in seeds]
    d = [x - y for x, y in zip(da, db)]
    out = {'n_pairs': len(seeds), 'mean_a': float(np.mean(da)), 'mean_b': float(np.mean(db))}
    out['diff'] = ci(d, conf)
    if len(seeds) >= 2:
        t, p = stats.ttest_rel(da, db)
        out['t'] = float(t)
        out['p'] = float(p)
        try:
            w, pw = stats.wilcoxon(da, db)
            out['wilcoxon_p'] = float(pw)
        except ValueError:
            out['wilcoxon_p'] = None
        r = float(np.corrcoef(da, db)[0, 1]) if len(seeds) > 2 else None
        out['crn_pair_corr'] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    rows = load(a.csv)
    idx = defaultdict(dict)          # (arm, rate) -> seed -> row
    for r in rows:
        idx[(r['arm'], int(r['rate']))][int(r['seed'])] = r

    def get(arm, rate, metric):
        return {s: v[metric] for s, v in idx[(arm, rate)].items() if v.get(metric) is not None}

    res = {}
    arms = sorted({r['arm'] for r in rows})
    rates = sorted({int(r['rate']) for r in rows})
    res['design'] = {'arms': arms, 'rates': rates,
                     'seeds_per_cell': {str(k): len(v) for k, v in idx.items()}}

    # ---- validity / teleport artefact screen -------------------------------
    val = {}
    for arm in arms:
        for rt in rates:
            if (arm, rt) not in idx:
                continue
            cell = idx[(arm, rt)]
            tp = [v['teleports_total'] for v in cell.values()]
            ins = [v['vehicles_inserted'] for v in cell.values()]
            run = [v['vehicles_running'] for v in cell.values()]
            val['%s_r%d' % (arm, rt)] = {
                'teleports_mean': float(np.mean(tp)),
                'teleports_per_1000_inserted': float(np.mean([1000 * t / i if i else 0
                                                              for t, i in zip(tp, ins)])),
                'still_running_at_end_mean': float(np.mean(run)),
                'still_running_frac': float(np.mean([r / i if i else 0 for r, i in zip(run, ins)])),
                'pt_teleports_mean': float(np.mean([v['pt_teleports'] for v in cell.values()])),
                'persons_still_running_mean': float(np.mean([v['persons_running'] for v in cell.values()])),
                'persons_completed_mean': float(np.mean([v['persons_completed'] for v in cell.values()])),
                'pt_stop_visits_served_mean': float(np.mean([v['pt_stop_visits_served'] for v in cell.values()])),
                'pt_vehicles_arrived_mean': float(np.mean([v['pt_vehicles_arrived'] for v in cell.values()])),
            }
    res['validity'] = val

    # ---- H2: deviation growth vs demand (arm gtfs_rel) ---------------------
    h2 = {}
    base_arm = 'gtfs_rel'
    for metric in ('dev_mean', 'dev_p90', 'dev_max', 'on_time_frac', 'late_frac',
                   'dev_slope_per_stop', 'headway_cv_mean', 'ride_wait_mean',
                   'dwell_mean', 'vehicleTripStatistics_speed'):
        h2[metric] = {}
        for rt in rates:
            if (base_arm, rt) in idx:
                h2[metric]['r%d' % rt] = ci(list(get(base_arm, rt, metric).values()))
    # paired increments between consecutive demand levels
    inc = {}
    for i in range(len(rates) - 1):
        r0, r1 = rates[i], rates[i + 1]
        if (base_arm, r0) in idx and (base_arm, r1) in idx:
            inc['%d->%d' % (r0, r1)] = paired(get(base_arm, r1, 'dev_mean'),
                                              get(base_arm, r0, 'dev_mean'))
    h2['paired_increments_dev_mean'] = inc
    # super-linearity: are the increments themselves increasing?
    means = [h2['dev_mean']['r%d' % r]['mean'] for r in rates if 'r%d' % r in h2['dev_mean']]
    if len(means) >= 3:
        d1 = np.diff(means)
        h2['increment_sequence'] = [float(x) for x in d1]
        h2['increments_increasing'] = bool(np.all(np.diff(d1) > 0))
        # quadratic vs linear fit on demand
        x = np.array([r for r in rates if 'r%d' % r in h2['dev_mean']], dtype=float)
        y = np.array(means)
        lin = np.polyfit(x, y, 1)
        quad = np.polyfit(x, y, 2)
        rss_l = float(np.sum((y - np.polyval(lin, x)) ** 2))
        rss_q = float(np.sum((y - np.polyval(quad, x)) ** 2))
        h2['fit'] = {'linear_rss': rss_l, 'quadratic_rss': rss_q,
                     'quad_coeff': float(quad[0]),
                     'quadratic_better': rss_q < rss_l}
    res['H2'] = h2

    # ---- H3: gtfs schedule vs ptlines headway ------------------------------
    h3 = {}
    for rt in rates:
        if ('ptlines', rt) not in idx or (base_arm, rt) not in idx:
            continue
        cell = {}
        for metric in ('ride_wait_mean', 'ride_wait_p90', 'headway_cv_mean', 'n_rides',
                       'person_duration_mean', 'persons_walk_only', 'pt_stop_visits_served',
                       'dwell_mean'):
            A = get(base_arm, rt, metric)
            B = get('ptlines', rt, metric)
            if A and B:
                cell[metric] = paired(A, B)
        h3['r%d' % rt] = cell
    res['H3'] = h3

    # ---- H4: schedule-holding vs endogenous dwell --------------------------
    h4 = {}
    for rt in rates:
        if ('gtfs_nohold', rt) not in idx or (base_arm, rt) not in idx:
            continue
        cell = {}
        for metric in ('dev_mean', 'dev_p90', 'on_time_frac', 'late_frac', 'early_frac',
                       'dwell_mean', 'dwell_gt_15s_frac', 'headway_cv_mean',
                       'ride_wait_mean', 'n_rides'):
            A = get(base_arm, rt, metric)
            B = get('gtfs_nohold', rt, metric)
            if A and B:
                cell[metric] = paired(A, B)
        h4['r%d' % rt] = cell
    res['H4'] = h4

    # ---- gtfs_rel vs gtfs_abs (contract check: constant --duration offset) --
    chk = {}
    for rt in rates:
        if ('gtfs_abs', rt) in idx and (base_arm, rt) in idx:
            chk['r%d' % rt] = paired(get(base_arm, rt, 'dev_mean'), get('gtfs_abs', rt, 'dev_mean'))
    res['rel_vs_abs_offset'] = chk

    with open(a.out, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res['validity'], indent=1))
    print('H2 dev_mean:', json.dumps(res['H2']['dev_mean'], indent=1))
    print('H2 on_time:', json.dumps(res['H2']['on_time_frac'], indent=1))


if __name__ == '__main__':
    main()
