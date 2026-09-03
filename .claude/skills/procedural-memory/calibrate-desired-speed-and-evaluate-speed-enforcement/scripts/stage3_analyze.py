#!/usr/bin/env python3
"""STAGE 3 - reduce the 9-arm x 8-seed batch to the study's headline numbers.

Produces (all under --outdir):
  results_table.csv / .md    exposure, variance, safety, mobility per arm
  paired_vs_baseline.csv     CRN-paired differences vs baseline, 95% t CIs
  spatial_profile.csv        seed-averaged 50 m speed profile per arm
  kangaroo.json              halo distances + overshoot for the point camera
  nilsson.csv/.json          expected injury/fatal crash change, at-camera vs
                             corridor-wide, Nilsson and Elvik exponents
  validity.json              teleports / completion / collision accounting
  plots/*.png
"""
import argparse
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import analysis as A  # noqa: E402

CAMERA = 2000.0
BIN = 50.0
ARM_ORDER = ['baseline', 'limit40', 'point_p40', 'point_p70', 'point_p95',
             'section_p40', 'section_p70', 'section_p95', 'point_p95_maxspeed']
LABEL = {'baseline': 'Baseline (50 km/h, no enforcement)',
         'limit40': 'Posted 50->40 km/h, unenforced',
         'point_p40': 'Point camera, p=0.40', 'point_p70': 'Point camera, p=0.70',
         'point_p95': 'Point camera, p=0.95',
         'section_p40': 'Section (2 km), p=0.40', 'section_p70': 'Section (2 km), p=0.70',
         'section_p95': 'Section (2 km), p=0.95',
         'point_p95_maxspeed': 'Point camera p=0.95, setMaxSpeed actuator'}

# Nilsson (2004) power model exponents, and Elvik (2009) revised exponents.
# These are LITERATURE values applied to simulated speed changes - they are not
# estimated from this simulation.
EXPONENTS = {'nilsson_injury': 2.0, 'nilsson_fatal': 4.0,
             'elvik_slight': 1.5, 'elvik_serious': 3.0, 'elvik_fatal': 4.5}


def load(root):
    runs = {}
    for arm in os.listdir(root):
        ad = os.path.join(root, arm)
        if not os.path.isdir(ad):
            continue
        for sd in os.listdir(ad):
            f = os.path.join(ad, sd, 'metrics.json')
            if os.path.exists(f):
                runs.setdefault(arm, {})[int(sd.replace('seed', ''))] = json.load(open(f))
    return runs


def load_profiles(root, arm, seeds):
    """Seed-averaged 50 m profile. Bins are averaged across seeds weighted by
    sample count (so a bin is the pooled speed mean, not a mean of means)."""
    acc = {}
    for s in seeds:
        f = os.path.join(root, arm, f'seed{s}', 'profile.csv')
        if not os.path.exists(f):
            continue
        for r in csv.DictReader(open(f)):
            x = float(r['x_mid']); n = int(r['n'])
            if n == 0:
                continue
            a = acc.setdefault(x, {'n': 0, 'sum': 0.0, 'p85': [], 'seeds': 0})
            a['n'] += n
            a['sum'] += float(r['mean_kmh']) * n
            a['p85'].append(float(r['p85_kmh']))
            a['seeds'] += 1
    return {x: {'mean_kmh': a['sum'] / a['n'], 'p85_kmh': A.mean(a['p85']),
                'n': a['n'], 'n_seeds': a['seeds']} for x, a in acc.items()}


def per_seed_profiles(root, arm, seeds):
    out = {}
    for s in seeds:
        f = os.path.join(root, arm, f'seed{s}', 'profile.csv')
        if os.path.exists(f):
            out[s] = {float(r['x_mid']): (float(r['mean_kmh']), int(r['n']))
                      for r in csv.DictReader(open(f)) if int(r['n']) > 0}
    return out


def get(m, key):
    if key.startswith('ssm.'):
        return m['ssm'][key[4:]]
    if key.startswith('det.'):
        _, pos, fld = key.split('.')
        return m['detectors'][pos][fld]
    return m[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    os.makedirs(os.path.join(a.outdir, 'plots'), exist_ok=True)
    runs = load(a.root)
    arms = [x for x in ARM_ORDER if x in runs]
    seeds = sorted(set.intersection(*[set(runs[x]) for x in arms]))
    print('arms', arms, 'seeds', seeds)

    # ------------------------------------------------ validity accounting
    val = {'seeds': seeds, 'per_arm': {}}
    for arm in arms:
        v = {k: [get(runs[arm][s], k) for s in seeds] for k in
             ('teleports_summary_last', 'teleports_traci_cumulative', 'running_at_end',
              'summary_running_last', 'collisions', 'n_eb_departed', 'n_eb_tripinfo',
              'throughput_eb')}
        val['per_arm'][arm] = {
            'teleports_total': sum(v['teleports_summary_last']),
            'teleports_traci_total': sum(v['teleports_traci_cumulative']),
            'running_at_end_total': sum(v['running_at_end']),
            'collisions_total': sum(v['collisions']),
            'eb_departed_total': sum(v['n_eb_departed']),
            'eb_completed_total': sum(v['n_eb_tripinfo']),
            'all_completed': sum(v['n_eb_departed']) == sum(v['n_eb_tripinfo']),
        }
    json.dump(val, open(os.path.join(a.outdir, 'validity.json'), 'w'), indent=2)

    # ------------------------------------------------ results table
    METRICS = [
        ('corridor_space_mean_kmh', 'Corridor space-mean speed (km/h)'),
        ('corridor_speed_sd_kmh', 'Corridor speed SD (km/h)'),
        ('corridor_speed_var_kmh2', 'Corridor speed variance (km/h)^2'),
        ('det.2000.mean_kmh', 'At-camera E1 time-mean speed (km/h)'),
        ('det.2000.p85_kmh', 'At-camera E1 85th pct (km/h)'),
        ('det.600.mean_kmh', 'Upstream (x=600) E1 time-mean (km/h)'),
        ('frac_vkm_over_limit', 'Frac veh-km over posted limit'),
        ('frac_vkm_over_limit_plus10', 'Frac veh-km over limit+10 km/h'),
        ('vkm_over_limit', 'Veh-km over limit (per run)'),
        ('hard_brakes_corridor', 'Hard-braking events (a<=-3 m/s^2)'),
        ('hard_brakes_near_camera', 'Hard-braking within +/-300 m of camera'),
        ('ssm.n_conflict_episodes', 'SSM conflict episodes (TTC<5 or DRAC>1.5)'),
        ('ssm.near_camera_all', 'SSM conflict episodes near camera'),
        ('ssm.drac_gt_1_5', 'SSM episodes with maxDRAC>1.5'),
        ('mean_duration_s', 'Mean EB trip duration (s)'),
        ('mean_timeloss_s', 'Mean EB timeLoss (s) [confounded for limit40]'),
        ('throughput_eb', 'EB trips completed'),
    ]
    rows = []
    for key, lab in METRICS:
        r = {'metric': lab, 'key': key}
        for arm in arms:
            vals = [get(runs[arm][s], key) for s in seeds]
            r[arm] = A.mean(vals)
            r[arm + '_sd'] = A.sd(vals)
        rows.append(r)
    with open(os.path.join(a.outdir, 'results_table.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['metric', 'key'] +
                           [c for arm in arms for c in (arm, arm + '_sd')])
        w.writeheader(); w.writerows(rows)

    with open(os.path.join(a.outdir, 'results_table.md'), 'w') as fh:
        fh.write('| Metric | ' + ' | '.join(arms) + ' |\n')
        fh.write('|---|' + '---|' * len(arms) + '\n')
        for r in rows:
            fh.write('| ' + r['metric'] + ' | ' +
                     ' | '.join(f"{r[arm]:.4g}" for arm in arms) + ' |\n')

    # ------------------------------------------------ paired differences
    pr = []
    for key, lab in METRICS:
        base = [get(runs['baseline'][s], key) for s in seeds]
        for arm in arms:
            if arm == 'baseline':
                continue
            tr = [get(runs[arm][s], key) for s in seeds]
            d = [t - b for t, b in zip(tr, base)]
            ci = A.paired_ci(d)
            pr.append({'metric': lab, 'key': key, 'arm': arm,
                       'baseline_mean': A.mean(base), 'arm_mean': A.mean(tr),
                       'diff_mean': ci['mean'], 'ci_lo': ci['lo'], 'ci_hi': ci['hi'],
                       'pct_change': 100.0 * ci['mean'] / A.mean(base) if A.mean(base) else float('nan'),
                       't': ci['t'], 'significant_95': ci['significant_95'], 'n_seeds': ci['n']})
    with open(os.path.join(a.outdir, 'paired_vs_baseline.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(pr[0].keys())); w.writeheader(); w.writerows(pr)

    # ------------------------------------------------ spatial profiles
    profs = {arm: load_profiles(a.root, arm, seeds) for arm in arms}
    xs = sorted(profs['baseline'])
    with open(os.path.join(a.outdir, 'spatial_profile.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['x_mid'] + [f'{arm}_{k}' for arm in arms for k in ('mean_kmh', 'p85_kmh')])
        for x in xs:
            w.writerow([x] + [f"{profs[arm][x][k]:.4f}" if x in profs[arm] else ''
                              for arm in arms for k in ('mean_kmh', 'p85_kmh')])

    # ------------------------------------------------ kangaroo effect
    kang = {}
    base_ps = per_seed_profiles(a.root, 'baseline', seeds)
    for arm in arms:
        if arm == 'baseline':
            continue
        arm_ps = per_seed_profiles(a.root, arm, seeds)
        diff = {}      # x -> seed-averaged (treatment - baseline) km/h, paired
        dci = {}
        for x in xs:
            d = [arm_ps[s][x][0] - base_ps[s][x][0] for s in seeds
                 if x in arm_ps.get(s, {}) and x in base_ps.get(s, {})]
            if d:
                diff[x] = A.mean(d)
                dci[x] = A.paired_ci(d)
        # halo: contiguous run of bins around the camera with diff < -1 km/h
        below = sorted(x for x in diff if diff[x] < -1.0)
        up = down = None
        if below:
            # walk outward from the bin nearest the camera
            near = min(diff, key=lambda x: abs(x - CAMERA))
            if diff.get(near, 0) < -1.0:
                lo = near
                while lo - BIN in diff and diff[lo - BIN] < -1.0:
                    lo -= BIN
                hi = near
                while hi + BIN in diff and diff[hi + BIN] < -1.0:
                    hi += BIN
                up = CAMERA - (lo - BIN / 2)
                down = (hi + BIN / 2) - CAMERA
        dn = {x: v for x, v in diff.items() if x > CAMERA}
        over_x = max(dn, key=lambda x: dn[x]) if dn else None
        kang[arm] = {
            'halo_upstream_m': up, 'halo_downstream_m': down,
            'halo_total_m': (up + down) if (up is not None and down is not None) else None,
            'min_diff_kmh': min(diff.values()), 'min_diff_x': min(diff, key=lambda x: diff[x]),
            'max_downstream_overshoot_kmh': dn[over_x] if over_x else None,
            'max_downstream_overshoot_x': over_x,
            'diff_at_camera_kmh': diff[min(diff, key=lambda x: abs(x - CAMERA))],
            'diff_at_camera_ci': dci[min(diff, key=lambda x: abs(x - CAMERA))],
            'diff_profile_kmh': {str(x): round(diff[x], 4) for x in sorted(diff)},
        }
    json.dump(kang, open(os.path.join(a.outdir, 'kangaroo.json'), 'w'), indent=2)

    # ------------------------------------------------ Nilsson power model
    nil = []
    for arm in arms:
        if arm == 'baseline':
            continue
        for loc, key in [('at_camera_E1_timemean', 'det.2000.mean_kmh'),
                         ('corridor_wide_spacemean', 'corridor_space_mean_kmh'),
                         ('upstream_only_E1_x600', 'det.600.mean_kmh')]:
            ratios = [get(runs[arm][s], key) / get(runs['baseline'][s], key) for s in seeds]
            row = {'arm': arm, 'location': loc, 'speed_key': key,
                   'v0_kmh': A.mean([get(runs['baseline'][s], key) for s in seeds]),
                   'v1_kmh': A.mean([get(runs[arm][s], key) for s in seeds]),
                   'speed_ratio_mean': A.mean(ratios)}
            for name, e in EXPONENTS.items():
                pct = [100.0 * (r ** e - 1.0) for r in ratios]
                ci = A.paired_ci(pct)
                row[f'{name}_pct'] = ci['mean']
                row[f'{name}_lo'] = ci['lo']
                row[f'{name}_hi'] = ci['hi']
            nil.append(row)
    with open(os.path.join(a.outdir, 'nilsson.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(nil[0].keys())); w.writeheader(); w.writerows(nil)
    json.dump({'exponents': EXPONENTS, 'rows': nil},
              open(os.path.join(a.outdir, 'nilsson.json'), 'w'), indent=2)

    # ------------------------------------------------ plots
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib missing - skipping plots')
        return

    C = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']   # validated categorical slots 1-4
    GRID = '#e3e2df'; INK = '#0b0b0b'; INK2 = '#52514e'

    def panel(ax, armlist, field, title, ylab):
        for i, arm in enumerate(armlist):
            ys = [profs[arm][x][field] for x in xs]
            ax.plot(xs, ys, lw=2, color=C[i], label=LABEL[arm], zorder=3)
        ax.axvline(CAMERA, color=INK2, lw=1, ls=':', zorder=1)
        ax.axhline(A.LIMIT_KMH, color=INK2, lw=1, ls='--', zorder=1)
        ax.set_title(title, fontsize=10, color=INK, loc='left')
        ax.set_xlabel('Distance along corridor (m)', fontsize=8, color=INK2)
        ax.set_ylabel(ylab, fontsize=8, color=INK2)
        ax.grid(True, color=GRID, lw=0.6, zorder=0)
        ax.set_axisbelow(True)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        ax.tick_params(labelsize=7, colors=INK2)
        ax.legend(fontsize=7, frameon=False, loc='lower left', ncol=2)
        ax.set_xlim(0, 4000)

    for field, ylab, fn in [('mean_kmh', 'Mean speed (km/h)', 'spatial_profile_mean.png'),
                            ('p85_kmh', '85th-pct speed (km/h)', 'spatial_profile_p85.png')]:
        fig, axes = plt.subplots(2, 1, figsize=(9, 7.5), sharex=True)
        panel(axes[0], ['baseline', 'limit40', 'point_p40', 'point_p95'], field,
              f'Point speed camera at x=2000 m - {ylab.lower()} vs distance (50 m bins, 8 seeds)', ylab)
        panel(axes[1], ['baseline', 'limit40', 'section_p40', 'section_p95'], field,
              f'Section enforcement x=1000-3000 m - {ylab.lower()} vs distance', ylab)
        # shade each panel's OWN enforcement zone only
        axes[0].axvspan(1700, 2030, color='#2a78d6', alpha=0.07, zorder=0)
        axes[1].axvspan(1000, 3000, color='#2a78d6', alpha=0.07, zorder=0)
        fig.tight_layout()
        fig.savefig(os.path.join(a.outdir, 'plots', fn), dpi=150,
                    facecolor='#fcfcfb')
        plt.close(fig)

    # difference-from-baseline profile (the kangaroo plot)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for i, arm in enumerate(['limit40', 'point_p40', 'point_p95', 'section_p95']):
        d = kang[arm]['diff_profile_kmh']
        ax.plot([float(x) for x in d], list(d.values()), lw=2, color=C[i], label=LABEL[arm])
    ax.axhline(0, color=INK2, lw=1)
    ax.axhline(-1.0, color=INK2, lw=0.8, ls='--')
    ax.axvline(CAMERA, color=INK2, lw=1, ls=':')
    ax.set_title('Speed change vs baseline by 50 m bin - the point camera halo and its downstream overshoot',
                 fontsize=10, loc='left', color=INK)
    ax.set_xlabel('Distance along corridor (m)', fontsize=8, color=INK2)
    ax.set_ylabel('Mean speed change (km/h)', fontsize=8, color=INK2)
    ax.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    ax.tick_params(labelsize=7, colors=INK2)
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(a.outdir, 'plots', 'speed_change_profile.png'), dpi=150,
                facecolor='#fcfcfb')
    plt.close(fig)
    print('wrote analysis to', a.outdir)


if __name__ == '__main__':
    main()
