#!/usr/bin/env python3
"""STAGE 3 supplements - three things the main table cannot show:

1. HARD-BRAKING LOCATION AUDIT. 98.7% of the limit-40 arm's hard-braking events
   sit in the first 200 m of the corridor, where the posted limit steps 50->40
   at the study boundary. That is an artifact of where the sign was placed, not
   a property of a limit reduction, so hard braking is re-reported both raw and
   with the entry bin (x<200 m) excluded.

2. HEAD-TO-HEAD point vs section at the SAME compliance, paired on seeds - the
   comparison that shows the two treatments are indistinguishable AT THE CAMERA
   but far apart corridor-wide.

3. ACTUATOR ARTIFACT. setMaxSpeed vs setSpeedFactor at identical compliance:
   deceleration severity, hard-braking counts and near-camera SSM conflicts.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import analysis as A  # noqa: E402

CAMERA = 2000.0
ENTRY = 200.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', default='1,2,3,4,5,6,7,8')
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(',')]
    arms = ['baseline', 'limit40', 'point_p40', 'point_p70', 'point_p95',
            'section_p40', 'section_p70', 'section_p95', 'point_p95_maxspeed']

    meta = {arm: {s: json.load(open(os.path.join(a.root, arm, f'seed{s}', 'run_meta.json')))
                  for s in seeds} for arm in arms}
    met = {arm: {s: json.load(open(os.path.join(a.root, arm, f'seed{s}', 'metrics.json')))
                 for s in seeds} for arm in arms}
    R = {}

    # ---- 1. hard braking with / without the corridor-entry bin --------------
    hb = {}
    for arm in arms:
        raw = [len(meta[arm][s]['hard_brakes']) for s in seeds]
        ex = [len([h for h in meta[arm][s]['hard_brakes'] if h['x'] >= ENTRY]) for s in seeds]
        infront = [len([h for h in meta[arm][s]['hard_brakes'] if h['x'] < ENTRY]) for s in seeds]
        acc = [h['a'] for s in seeds for h in meta[arm][s]['hard_brakes']]
        hb[arm] = {'raw_mean': A.mean(raw), 'excl_entry_mean': A.mean(ex),
                   'in_entry_bin_mean': A.mean(infront),
                   'frac_in_entry_bin': (A.mean(infront) / A.mean(raw)) if A.mean(raw) else 0.0,
                   'min_decel_ms2': min(acc) if acc else None,
                   'mean_decel_ms2': A.mean(acc) if acc else None,
                   'n_total_all_seeds': sum(raw)}
    for arm in arms:
        if arm == 'baseline':
            continue
        d = [len([h for h in meta[arm][s]['hard_brakes'] if h['x'] >= ENTRY])
             - len([h for h in meta['baseline'][s]['hard_brakes'] if h['x'] >= ENTRY])
             for s in seeds]
        hb[arm]['paired_diff_vs_baseline_excl_entry'] = A.paired_ci(d)
    R['hard_braking_location_audit'] = hb

    # ---- 2. point vs section head-to-head, paired --------------------------
    KEYS = [('det.2000.mean_kmh', 'At-camera E1 time-mean speed (km/h)'),
            ('corridor_space_mean_kmh', 'Corridor space-mean speed (km/h)'),
            ('frac_vkm_over_limit', 'Frac veh-km over limit'),
            ('frac_vkm_over_limit_plus10', 'Frac veh-km over limit+10'),
            ('corridor_speed_var_kmh2', 'Corridor speed variance'),
            ('mean_duration_s', 'Mean EB duration (s)')]

    def gv(arm, s, key):
        m = met[arm][s]
        if key.startswith('det.'):
            _, p, f = key.split('.')
            return m['detectors'][p][f]
        return m[key]

    h2h = {}
    for p in ('40', '70', '95'):
        pa, sa = f'point_p{p}', f'section_p{p}'
        row = {}
        for key, lab in KEYS:
            d = [gv(sa, s, key) - gv(pa, s, key) for s in seeds]
            ci = A.paired_ci(d)
            row[lab] = {'point_mean': A.mean([gv(pa, s, key) for s in seeds]),
                        'section_mean': A.mean([gv(sa, s, key) for s in seeds]),
                        'section_minus_point': ci['mean'], 'ci_lo': ci['lo'],
                        'ci_hi': ci['hi'], 'significant_95': ci['significant_95']}
        h2h[f'p{p}'] = row
    R['point_vs_section_head_to_head'] = h2h

    # ---- 3. actuator artifact ---------------------------------------------
    act = {}
    for key, lab in [('hard_brakes_corridor', 'hard-braking events'),
                     ('hard_brakes_near_camera', 'hard-braking near camera'),
                     ('ssm.near_camera_all', 'SSM episodes near camera'),
                     ('ssm.n_conflict_episodes', 'SSM episodes corridor'),
                     ('det.2000.mean_kmh', 'at-camera E1 mean km/h'),
                     ('corridor_space_mean_kmh', 'corridor space-mean km/h')]:
        def g(arm, s):
            m = met[arm][s]
            if key.startswith('ssm.'):
                return m['ssm'][key[4:]]
            if key.startswith('det.'):
                _, p, f = key.split('.')
                return m['detectors'][p][f]
            return m[key]
        d = [g('point_p95_maxspeed', s) - g('point_p95', s) for s in seeds]
        ci = A.paired_ci(d)
        act[lab] = {'setSpeedFactor': A.mean([g('point_p95', s) for s in seeds]),
                    'setMaxSpeed': A.mean([g('point_p95_maxspeed', s) for s in seeds]),
                    'diff': ci['mean'], 'ci_lo': ci['lo'], 'ci_hi': ci['hi'],
                    'significant_95': ci['significant_95']}
    act['min_decel_setSpeedFactor_ms2'] = hb['point_p95']['min_decel_ms2']
    act['min_decel_setMaxSpeed_ms2'] = hb['point_p95_maxspeed']['min_decel_ms2']
    act['mean_decel_setSpeedFactor_ms2'] = hb['point_p95']['mean_decel_ms2']
    act['mean_decel_setMaxSpeed_ms2'] = hb['point_p95_maxspeed']['mean_decel_ms2']
    R['actuator_artifact'] = act

    # ---- 4. overstatement ratio: at-camera vs corridor-wide Nilsson --------
    nil = json.load(open(os.path.join(os.path.dirname(a.out), 'nilsson.json')))
    ov = {}
    for r in nil['rows']:
        ov.setdefault(r['arm'], {})[r['location']] = r
    R['overstatement_ratio'] = {}
    for arm, locs in ov.items():
        c = locs['at_camera_E1_timemean']['nilsson_injury_pct']
        w = locs['corridor_wide_spacemean']['nilsson_injury_pct']
        cf = locs['at_camera_E1_timemean']['nilsson_fatal_pct']
        wf = locs['corridor_wide_spacemean']['nilsson_fatal_pct']
        R['overstatement_ratio'][arm] = {
            'injury_at_camera_pct': c, 'injury_corridor_pct': w,
            'injury_overstatement_x': c / w if w else None,
            'fatal_at_camera_pct': cf, 'fatal_corridor_pct': wf,
            'fatal_overstatement_x': cf / wf if wf else None}

    json.dump(R, open(a.out, 'w'), indent=2)
    print(json.dumps(R['hard_braking_location_audit'], indent=1)[:1200])
    print(json.dumps(R['overstatement_ratio'], indent=1))
    print(json.dumps(R['actuator_artifact'], indent=1))


if __name__ == '__main__':
    main()
