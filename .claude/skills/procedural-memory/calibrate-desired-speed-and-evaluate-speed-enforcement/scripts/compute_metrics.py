#!/usr/bin/env python3
"""Reduce ONE raw run directory to metrics.json + profile.csv.

Everything is computed from the raw files in that directory:
  traj.csv.gz     TraCI floating-car data (t, id, x, v, a), eastbound, 0.5 s
  e1_instant.xml  per-vehicle E1 spot speeds
  e1.xml          aggregated E1 intervals
  ssm.xml         SSM conflict log
  tripinfo.xml    per-vehicle trips
  summary.xml     per-step running count + CUMULATIVE teleports
  run_meta.json   per-vehicle speedFactor / compliance flag / hard-brake log
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import analysis as A  # noqa: E402

CORR = 4000.0
BIN = 50.0
LIMIT = A.LIMIT_MS               # 13.89 m/s
LIMIT_P10 = LIMIT + 10.0 / 3.6   # posted + 10 km/h
CAMERA = 2000.0
DT = 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rundir', required=True)
    a = ap.parse_args()
    d = a.rundir
    meta = json.load(open(os.path.join(d, 'run_meta.json')))

    # ---------------- spatial profile + exposure, from FCD ----------------
    traj = A.load_traj(os.path.join(d, 'traj.csv.gz'))
    nb = int(CORR / BIN)
    bins = [[] for _ in range(nb)]
    vkm = vkm_over = vkm_over10 = 0.0
    allv = []
    for (t, vid, x, v, ac) in traj:
        if not (0.0 <= x < CORR):
            continue
        bins[int(x / BIN)].append(v)
        dist = v * DT
        vkm += dist
        if v > LIMIT:
            vkm_over += dist
        if v > LIMIT_P10:
            vkm_over10 += dist
        allv.append(v)

    prof = []
    for i in range(nb):
        b = bins[i]
        prof.append({'x_mid': i * BIN + BIN / 2, 'n': len(b),
                     'mean_kmh': A.mean(b) * 3.6 if b else float('nan'),
                     'p85_kmh': A.pctl(b, 0.85) * 3.6 if b else float('nan'),
                     'sd_kmh': A.sd(b) * 3.6 if len(b) > 1 else float('nan')})
    with open(os.path.join(d, 'profile.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(prof[0].keys()))
        w.writeheader()
        w.writerows(prof)

    # ---------------- hard braking, from the FCD acceleration channel ------
    hb = meta['hard_brakes']
    hb_cam = [h for h in hb if abs(h['x'] - CAMERA) <= 300.0]

    # ---------------- SSM conflicts ----------------------------------------
    conf = A.parse_ssm(os.path.join(d, 'ssm.xml'))
    # SUMO logs every encounter TWICE (once per ego, roles swapped). De-duplicate
    # to unordered-pair episodes before counting.
    seen = set()
    uniq = []
    for c in conf:
        k = (frozenset((c['ego'], c['foe'])), round(c['begin'], 1))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    def cnt(pred):
        return sum(1 for c in uniq if pred(c))

    def near(c, w=300.0):
        p = c['ttc_pos'] if c['ttc_pos'] is not None else c['drac_pos']
        return p is not None and abs(p - CAMERA) <= w

    ssm = {
        'n_conflict_records_raw': len(conf),
        'n_conflict_episodes': len(uniq),
        'ttc_lt_3': cnt(lambda c: c['minTTC'] is not None and c['minTTC'] < 3.0),
        'ttc_lt_1_5': cnt(lambda c: c['minTTC'] is not None and c['minTTC'] < 1.5),
        'drac_gt_3': cnt(lambda c: c['maxDRAC'] is not None and c['maxDRAC'] > 3.0),
        'drac_gt_1_5': cnt(lambda c: c['maxDRAC'] is not None and c['maxDRAC'] > 1.5),
        'near_camera_all': cnt(near),
        'near_camera_ttc_lt_3': cnt(lambda c: near(c) and c['minTTC'] is not None and c['minTTC'] < 3.0),
        'near_camera_drac_gt_1_5': cnt(lambda c: near(c) and c['maxDRAC'] is not None and c['maxDRAC'] > 1.5),
        'min_ttc_overall': min([c['minTTC'] for c in uniq if c['minTTC'] is not None], default=None),
        'max_drac_overall': max([c['maxDRAC'] for c in uniq if c['maxDRAC'] is not None], default=None),
    }

    # ---------------- mobility, from tripinfo ------------------------------
    trips = [t for t in A.parse_tripinfo(os.path.join(d, 'tripinfo.xml'))
             if t['id'].startswith('eb')]
    dur = [t['duration'] for t in trips]
    tl = [t['timeLoss'] for t in trips]

    # ---------------- detector spot speeds ---------------------------------
    inst = A.parse_e1_instant(os.path.join(d, 'e1_instant.xml'))
    det = {}
    for p, recs in inst.items():
        sp = [s for _, s in recs]
        det[str(p)] = {'n': len(sp), 'mean_kmh': A.mean(sp) * 3.6,
                       'p85_kmh': A.pctl(sp, 0.85) * 3.6, 'sd_kmh': A.sd(sp) * 3.6,
                       'frac_over_limit': sum(1 for s in sp if s > LIMIT) / len(sp)}

    tp, running_last = A.parse_summary_teleports(os.path.join(d, 'summary.xml'))
    ncoll = sum(1 for _ in A.ET.iterparse(A.xopen(os.path.join(d, 'collisions.xml')),
                                          events=('end',)) if _[1].tag == 'collision')

    m = {
        'run': os.path.basename(d), 'mode': meta['args']['mode'],
        'p': meta['args']['p'], 'seed': meta['args']['seed'],
        'actuator': meta['args']['actuator'],
        'n_eb': meta['n_eb'], 'n_eb_compliant': meta['n_eb_compliant'],
        'n_capped_events': meta['n_capped_events'],
        # validity
        'teleports_summary_last': tp, 'teleports_traci_cumulative': meta['teleports_live_cumulative'],
        'running_at_end': meta['running_at_end'], 'summary_running_last': running_last,
        'collisions': ncoll,
        'n_eb_tripinfo': len(trips), 'n_eb_departed': meta['n_eb'],
        # exposure
        'vkm_total': vkm / 1000.0,
        'vkm_over_limit': vkm_over / 1000.0,
        'vkm_over_limit_plus10': vkm_over10 / 1000.0,
        'frac_vkm_over_limit': vkm_over / vkm,
        'frac_vkm_over_limit_plus10': vkm_over10 / vkm,
        # speed
        'corridor_space_mean_kmh': A.mean(allv) * 3.6,
        'corridor_speed_sd_kmh': A.sd(allv) * 3.6,
        'corridor_speed_var_kmh2': A.sd(allv) ** 2 * 3.6 ** 2,
        'corridor_p85_kmh': A.pctl(allv, 0.85) * 3.6,
        'n_fcd_samples': len(allv),
        # safety
        'hard_brakes_corridor': len(hb),
        'hard_brakes_near_camera': len(hb_cam),
        'hard_brakes_per_1000vkm': len(hb) / (vkm / 1000.0) * 1000.0,
        'ssm': ssm,
        # mobility
        'mean_duration_s': A.mean(dur), 'mean_timeloss_s': A.mean(tl),
        'throughput_eb': len(trips),
        'detectors': det,
    }
    json.dump(m, open(os.path.join(d, 'metrics.json'), 'w'), indent=2)
    print(json.dumps({k: v for k, v in m.items()
                      if k in ('run', 'corridor_space_mean_kmh', 'frac_vkm_over_limit',
                               'hard_brakes_corridor', 'mean_duration_s')}))


if __name__ == '__main__':
    main()
