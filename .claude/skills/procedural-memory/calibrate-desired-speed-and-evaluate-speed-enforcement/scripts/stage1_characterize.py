#!/usr/bin/env python3
"""STAGE 1 - characterise SUMO's desired-speed (speedFactor) machinery EMPIRICALLY.

Every claim here is measured from simulation output, never from documentation:

 (a) how the three speedFactor syntaxes map to the realised per-vehicle factor
     - normc(mu,sigma,min,max)
     - scalar speedFactor + speedDev
     - the --default.speeddev global
 (b) whether normc's truncation bounds CLIP (atoms at the bounds) or
     RENORMALISE (smooth truncated normal) - tested with tight bounds
 (c) whether a vehicle actually attains speedFactor x limit on a free link,
     and where vType maxSpeed / accel / speedFactorPremature interfere
 (d) whether speedFactor is drawn once per vehicle or resampled over time

Writes outputs/stage1/*.json + the raw per-vehicle CSVs the numbers come from.
"""
import argparse
import csv
import json
import math
import os
import subprocess
import sys

sys.path.append(os.path.join(os.environ.get('SUMO_HOME', '/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO'), 'tools'))
import traci  # noqa: E402

import build_network as bn  # noqa: E402

SUMO = 'sumo'


def probe_run(label, outdir, net, vtype_spec, extra_cli=None, depart_speed='desired',
              n_target=1500, vph=3000, seed=1, track_time_series=False, sim_end=4000,
              sample_only=False):
    """Run a short sim; record each vehicle's realised speedFactor, maxSpeed,
    allowed speed and its max realised speed on the free corridor.

    sample_only=True removes each vehicle immediately after its speedFactor is
    read - used for the pure distribution probes (a)/(b), where only the sampled
    factor matters and letting 3000 vehicles traverse 4.8 km would be wasted work.
    """
    os.makedirs(outdir, exist_ok=True)
    rou = os.path.join(outdir, f'{label}.rou.xml')
    eb = ' '.join(['e_in'] + [f'e{i:02d}' for i in range(bn.N_SEG)] + ['e_out'])
    x = ['<routes>']
    x.append(f'    <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6" '
             f'decel="4.5" sigma="0.5" tau="1.0" {vtype_spec}/>')
    x.append(f'    <route id="rEB" edges="{eb}"/>')
    x.append(f'    <flow id="eb" type="car" route="rEB" begin="0" end="{int(n_target/vph*3600)}" '
             f'vehsPerHour="{vph}" departLane="free" departSpeed="{depart_speed}"/>')
    x.append('</routes>')
    open(rou, 'w').write('\n'.join(x) + '\n')

    cmd = [SUMO, '-n', net, '-r', rou, '--seed', str(seed), '--step-length', '1.0',
           '--no-step-log', 'true', '--time-to-teleport', '300',
           '--end', str(sim_end), '--start', '--quit-on-end']
    if extra_cli:
        cmd += extra_cli
    traci.start(cmd, label=label)
    c = traci.getConnection(label)

    rec = {}
    ts = {}   # vehicle -> list of (t, speedFactor) for the resampling test
    t = 0.0
    while c.simulation.getMinExpectedNumber() > 0:
        c.simulationStep()
        t = c.simulation.getTime()
        for v in c.simulation.getDepartedIDList():
            rec[v] = {
                'id': v,
                'speedFactor': c.vehicle.getSpeedFactor(v),
                'maxSpeed': c.vehicle.getMaxSpeed(v),
                'allowedSpeed_depart': c.vehicle.getAllowedSpeed(v),
                'speed_depart': c.vehicle.getSpeed(v),
                'vmax_realised': 0.0,
                't_depart': t,
                't_reach_desired': None,
            }
            if sample_only:
                c.vehicle.remove(v)
        if sample_only:
            continue
        for v in c.vehicle.getIDList():
            if v not in rec:
                continue
            sp = c.vehicle.getSpeed(v)
            if sp > rec[v]['vmax_realised']:
                rec[v]['vmax_realised'] = sp
            des = min(rec[v]['maxSpeed'], rec[v]['speedFactor'] * c.vehicle.getAllowedSpeed(v))
            if rec[v]['t_reach_desired'] is None and sp >= des - 0.01:
                rec[v]['t_reach_desired'] = t - rec[v]['t_depart']
            if track_time_series and len(ts) < 5 and v not in ts:
                ts[v] = []
            if track_time_series and v in ts and len(ts[v]) < 60:
                ts[v].append((t, c.vehicle.getSpeedFactor(v)))
    c.close()

    csvf = os.path.join(outdir, f'{label}_vehicles.csv')
    with open(csvf, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(next(iter(rec.values())).keys()))
        w.writeheader()
        for v in rec.values():
            w.writerow(v)
    return rec, ts, csvf


def stats(vals):
    vals = sorted(vals)
    n = len(vals)
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    def q(p):
        k = p * (n - 1)
        lo = int(math.floor(k)); hi = min(lo + 1, n - 1)
        return vals[lo] + (k - lo) * (vals[hi] - vals[lo])
    return {'n': n, 'mean': m, 'sd': sd, 'min': vals[0], 'max': vals[-1],
            'p15': q(0.15), 'p50': q(0.50), 'p85': q(0.85)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    R = {}

    # ---------- (a) three syntaxes ----------
    cases = [
        ('A1_normc_default', 'speedFactor="normc(1.0,0.1,0.2,2.0)"', None),
        ('A2_scalar_only', 'speedFactor="1.2"', None),
        ('A3_scalar_plus_speeddev', 'speedFactor="1.2" speedDev="0.15"', None),
        ('A4_scalar_plus_globaldev', 'speedFactor="1.2"', ['--default.speeddev', '0.25']),
        ('A5_no_speedfactor_globaldev', '', ['--default.speeddev', '0.25']),
        ('A6_no_speedfactor_nothing', '', None),
        ('A7_speeddev_zero', 'speedFactor="1.2" speedDev="0"', None),
    ]
    R['a_syntax'] = {}
    for label, spec, cli in cases:
        rec, _, csvf = probe_run(label, a.outdir, a.net, spec, extra_cli=cli,
                                 n_target=3000, vph=7200, sample_only=True)
        sf = [r['speedFactor'] for r in rec.values()]
        R['a_syntax'][label] = {'vtype_spec': spec or '(none)',
                                'cli': ' '.join(cli) if cli else '(none)',
                                'csv': os.path.basename(csvf),
                                'speedFactor': stats(sf)}
        print(label, R['a_syntax'][label]['speedFactor'])

    # ---------- (b) truncation: clip or renormalise? ----------
    # Tight bounds at +/- 0.5 sigma. If SUMO CLIPS, ~62% of the mass lands exactly
    # on the two bounds (atoms). If it RENORMALISES (resample/truncated normal),
    # there are no atoms and the empirical CDF matches a truncated normal.
    R['b_truncation'] = {}
    for label, mu, sg, lo, hi in [('B1_tight', 1.0, 0.20, 0.90, 1.10),
                                  ('B2_asym', 1.0, 0.20, 0.95, 1.40)]:
        spec = f'speedFactor="normc({mu},{sg},{lo},{hi})"'
        rec, _, csvf = probe_run(label, a.outdir, a.net, spec, n_target=8000, vph=7200,
                                 sample_only=True)
        sf = [r['speedFactor'] for r in rec.values()]
        n = len(sf)
        at_lo = sum(1 for v in sf if abs(v - lo) < 1e-6)
        at_hi = sum(1 for v in sf if abs(v - hi) < 1e-6)
        # nominal (untruncated) normal probabilities outside the bounds
        Phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
        p_lo = Phi((lo - mu) / sg)
        p_hi = 1 - Phi((hi - mu) / sg)
        # KS statistic of the sample vs the RENORMALISED truncated normal
        Fl, Fh = Phi((lo - mu) / sg), Phi((hi - mu) / sg)
        s = sorted(sf)
        ks_trunc = max(max(abs((i + 1) / n - (Phi((v - mu) / sg) - Fl) / (Fh - Fl)),
                           abs(i / n - (Phi((v - mu) / sg) - Fl) / (Fh - Fl)))
                       for i, v in enumerate(s))
        # KS vs the CLIPPED distribution (atoms at bounds) -- evaluated on interior only
        ks_clip = max(max(abs((i + 1) / n - Phi((v - mu) / sg)),
                          abs(i / n - Phi((v - mu) / sg)))
                      for i, v in enumerate(s))
        R['b_truncation'][label] = {
            'spec': spec, 'csv': os.path.basename(csvf), 'n': n,
            'nominal_mass_below_min': p_lo, 'nominal_mass_above_max': p_hi,
            'observed_frac_exactly_at_min': at_lo / n,
            'observed_frac_exactly_at_max': at_hi / n,
            'ks_vs_renormalised_truncnorm': ks_trunc,
            'ks_vs_clipped_normal': ks_clip,
            'ks_crit_5pct': 1.36 / math.sqrt(n),
            'sample': stats(sf),
            'truncnorm_theory_mean': mu + sg * (
                (math.exp(-0.5 * ((lo - mu) / sg) ** 2) - math.exp(-0.5 * ((hi - mu) / sg) ** 2))
                / math.sqrt(2 * math.pi) / (Fh - Fl)),
        }
        print(label, json.dumps(R['b_truncation'][label], indent=1)[:400])

    # ---------- (c) does the vehicle attain speedFactor x limit? ----------
    R['c_attainment'] = {}
    for label, spec, dspeed, note in [
        ('C1_free_desiredstart', 'speedFactor="normc(1.15,0.15,0.5,2.0)"', 'desired',
         'light demand, departSpeed=desired'),
        ('C2_free_zerostart', 'speedFactor="normc(1.15,0.15,0.5,2.0)"', '0',
         'light demand, departSpeed=0 -> must accelerate up'),
        ('C3_maxspeed_capped', 'speedFactor="normc(1.15,0.15,0.5,2.0)" maxSpeed="14.5"',
         'desired', 'vType maxSpeed=14.5 m/s binds below speedFactor*limit for most drivers'),
        ('C4_premature', 'speedFactor="normc(1.15,0.15,0.5,2.0)" speedFactorPremature="0.5"',
         'desired', 'speedFactorPremature set but no <stop> on the route'),
    ]:
        rec, _, csvf = probe_run(label, a.outdir, a.net, spec, depart_speed=dspeed,
                                 n_target=600, vph=700)
        ratio = [r['vmax_realised'] / (r['speedFactor'] * bn.POSTED_MS) for r in rec.values()]
        des_cap = [r['vmax_realised'] / min(r['maxSpeed'], r['speedFactor'] * bn.POSTED_MS)
                   for r in rec.values()]
        tr = [r['t_reach_desired'] for r in rec.values() if r['t_reach_desired'] is not None]
        R['c_attainment'][label] = {
            'spec': spec, 'departSpeed': dspeed, 'note': note, 'csv': os.path.basename(csvf),
            'ratio_vmax_over_sf_times_limit': stats(ratio),
            'ratio_vmax_over_min(maxSpeed,sf*limit)': stats(des_cap),
            'frac_within_1pct_of_sf_times_limit': sum(1 for r in ratio if r >= 0.99) / len(ratio),
            'sec_to_reach_desired': stats(tr) if tr else None,
            'n_never_reached': len(rec) - len(tr),
        }
        print(label, R['c_attainment'][label]['ratio_vmax_over_sf_times_limit'],
              'within1%:', R['c_attainment'][label]['frac_within_1pct_of_sf_times_limit'])

    # ---------- (d) once per vehicle, or resampled? ----------
    rec, ts, csvf = probe_run('D1_resample', a.outdir, a.net,
                              'speedFactor="normc(1.15,0.15,0.5,2.0)"',
                              n_target=200, vph=700, track_time_series=True)
    R['d_resampling'] = {
        'csv': os.path.basename(csvf),
        'tracked_vehicles': {v: {'n_samples': len(s),
                                 'distinct_values': len(set(round(f, 12) for _, f in s)),
                                 'first': s[0][1], 'last': s[-1][1]}
                             for v, s in ts.items()},
    }
    print('d_resampling', json.dumps(R['d_resampling']['tracked_vehicles'], indent=1))

    with open(os.path.join(a.outdir, 'stage1_characterization.json'), 'w') as f:
        json.dump(R, f, indent=2)
    print('\nwrote', os.path.join(a.outdir, 'stage1_characterization.json'))


if __name__ == '__main__':
    main()
