#!/usr/bin/env python3
"""STAGE 1 - calibrate (mu, sigma) of the speedFactor distribution so that
free-flow SPOT speeds at the midblock E1 detector match the field targets
    mean = 56.0 km/h,  85th percentile = 64.0 km/h   on a 50 km/h posted road,
and quantify the TIME-MEAN vs SPACE-MEAN speed bias at that same location.

Fixed-point iteration on the two moments:
    mu    <- mu    * target_mean / measured_mean
    sigma <- sigma * (target_p85 - target_mean) / (measured_p85 - measured_mean)
(exact for a location-scale family; a few iterations absorb the small
car-following/insertion effects that make the mapping non-exact.)

Every measured quantity comes from raw output:
  measured spot mean/p85  <- e1_instant.xml per-vehicle records at x=600
  space-mean speed        <- traj.csv.gz FCD samples over x in [500, 700]
  generating distribution <- run_meta.json per-vehicle sampled speedFactor
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import analysis as A  # noqa: E402

DET = 600
SEG = (500.0, 700.0)      # midblock segment centred on the detector
TARGET_MEAN_KMH = 56.0
TARGET_P85_KMH = 64.0


def run(net, outdir, mu, sigma, seed, vph, end, demand_end, step_length):
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, os.path.join(HERE, 'run_scenario.py'),
           '--net', net, '--outdir', outdir, '--mode', 'baseline',
           '--seed', str(seed), '--mu', f'{mu:.6f}', '--sigma', f'{sigma:.6f}',
           '--vph', str(vph), '--end', str(end), '--demand-end', str(demand_end),
           '--step-length', str(step_length)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('run failed')
    return outdir


def measure(rundir, step_length):
    spot = A.spot_speeds_at(os.path.join(rundir, 'e1_instant.xml'), DET)
    traj = A.load_traj(os.path.join(rundir, 'traj.csv.gz'))
    sm = A.space_mean_over_segment(traj, SEG[0], SEG[1], step_length)
    meta = json.load(open(os.path.join(rundir, 'run_meta.json')))
    sf_eb = [f for v, f in meta['speed_factors'].items() if v.startswith('eb')]
    agg = A.parse_e1_agg(os.path.join(rundir, 'e1.xml'), det_prefix=f'e1_{DET}_')
    nsum = sum(a['n'] for a in agg)
    return {
        'spot': spot, 'space': sm, 'sf_eb': sf_eb,
        'e1_agg_speed_flowweighted': sum(a['speed'] * a['n'] for a in agg) / nsum,
        'e1_agg_hspeed_flowweighted': sum(a['hspeed'] * a['n'] for a in agg) / nsum,
        'e1_agg_n': nsum,
        'teleports': A.parse_summary_teleports(os.path.join(rundir, 'summary.xml')),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--mu0', type=float, default=1.12)
    ap.add_argument('--sigma0', type=float, default=0.154)
    ap.add_argument('--iters', type=int, default=4)
    ap.add_argument('--seeds', default='101,102,103')
    ap.add_argument('--vph', type=float, default=1200.0)
    ap.add_argument('--end', type=float, default=3600.0)
    ap.add_argument('--demand-end', type=float, default=1800.0)
    ap.add_argument('--step-length', type=float, default=0.5)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    seeds = [int(s) for s in a.seeds.split(',')]

    mu, sigma = a.mu0, a.sigma0
    history = []
    for it in range(a.iters):
        spot_all, sf_all = [], []
        sm_edie, sm_harm, sm_sd, e1s, e1h = [], [], [], [], []
        for sd_ in seeds:
            rd = os.path.join(a.workdir, f'cal_it{it}_s{sd_}')
            run(a.net, rd, mu, sigma, sd_, a.vph, a.end, a.demand_end, a.step_length)
            m = measure(rd, a.step_length)
            spot_all += m['spot']
            sf_all += m['sf_eb']
            sm_edie.append(m['space']['edie_space_mean'])
            sm_harm.append(m['space']['harmonic_of_traversal_speeds'])
            sm_sd.append(m['space']['sd_of_samples'])
            e1s.append(m['e1_agg_speed_flowweighted'])
            e1h.append(m['e1_agg_hspeed_flowweighted'])
        k = 3.6
        rec = {
            'iter': it, 'mu': mu, 'sigma': sigma,
            'n_spot': len(spot_all),
            'spot_mean_kmh': A.mean(spot_all) * k,
            'spot_p85_kmh': A.pctl(spot_all, 0.85) * k,
            'spot_sd_kmh': A.sd(spot_all) * k,
            'spot_p50_kmh': A.pctl(spot_all, 0.50) * k,
            'spot_p15_kmh': A.pctl(spot_all, 0.15) * k,
            'gen_sf_mean': A.mean(sf_all), 'gen_sf_sd': A.sd(sf_all),
            'gen_mean_kmh': A.mean(sf_all) * A.LIMIT_KMH,
            'gen_p85_kmh': A.pctl(sf_all, 0.85) * A.LIMIT_KMH,
            'space_mean_edie_kmh': A.mean(sm_edie) * k,
            'space_mean_harmonic_kmh': A.mean(sm_harm) * k,
            'space_sd_kmh': A.mean(sm_sd) * k,
            'e1_agg_arith_speed_kmh': A.mean(e1s) * k,
            'e1_agg_harmonic_speed_kmh': A.mean(e1h) * k,
        }
        history.append(rec)
        print(f"it{it} mu={mu:.5f} sigma={sigma:.5f} -> spot mean={rec['spot_mean_kmh']:.3f} "
              f"p85={rec['spot_p85_kmh']:.3f} sd={rec['spot_sd_kmh']:.3f}  "
              f"space(Edie)={rec['space_mean_edie_kmh']:.3f}")
        if it < a.iters - 1:
            mu *= TARGET_MEAN_KMH / rec['spot_mean_kmh']
            sigma *= (TARGET_P85_KMH - TARGET_MEAN_KMH) / (rec['spot_p85_kmh'] - rec['spot_mean_kmh'])

    best = min(history, key=lambda r: abs(r['spot_mean_kmh'] - TARGET_MEAN_KMH) / TARGET_MEAN_KMH
               + abs(r['spot_p85_kmh'] - TARGET_P85_KMH) / TARGET_P85_KMH)
    f = best
    bias = {
        'E1_time_mean_kmh': f['spot_mean_kmh'],
        'FCD_space_mean_Edie_kmh': f['space_mean_edie_kmh'],
        'FCD_space_mean_harmonic_of_traversals_kmh': f['space_mean_harmonic_kmh'],
        'generating_distribution_mean_kmh': f['gen_mean_kmh'],
        'E1_minus_space_kmh': f['spot_mean_kmh'] - f['space_mean_edie_kmh'],
        'E1_minus_generating_kmh': f['spot_mean_kmh'] - f['gen_mean_kmh'],
        'space_minus_generating_kmh': f['space_mean_edie_kmh'] - f['gen_mean_kmh'],
        'wardrop_prediction_TMS_minus_SMS_kmh': f['space_sd_kmh'] ** 2 / f['space_mean_edie_kmh'],
        'sumo_e1_field_speed_arith_kmh': f['e1_agg_arith_speed_kmh'],
        'sumo_e1_field_harmonicMeanSpeed_kmh': f['e1_agg_harmonic_speed_kmh'],
    }
    out = {'targets': {'mean_kmh': TARGET_MEAN_KMH, 'p85_kmh': TARGET_P85_KMH,
                       'posted_kmh': A.LIMIT_KMH},
           'detector_pos_m': DET, 'fcd_segment_m': SEG,
           'seeds': seeds, 'history': history,
           'fitted': {'mu': best['mu'], 'sigma': best['sigma'],
                      'speedFactor_spec': f"normc({best['mu']:.5f},{best['sigma']:.5f},0.2,2.0)"},
           'achieved': {'spot_mean_kmh': best['spot_mean_kmh'],
                        'spot_p85_kmh': best['spot_p85_kmh'],
                        'spot_sd_kmh': best['spot_sd_kmh'],
                        'spot_p50_kmh': best['spot_p50_kmh'],
                        'spot_p15_kmh': best['spot_p15_kmh'],
                        'n_spot_observations': best['n_spot'],
                        'err_mean_kmh': best['spot_mean_kmh'] - TARGET_MEAN_KMH,
                        'err_p85_kmh': best['spot_p85_kmh'] - TARGET_P85_KMH},
           'time_mean_vs_space_mean': bias}
    json.dump(out, open(os.path.join(a.outdir, 'calibration.json'), 'w'), indent=2)
    print(json.dumps({'fitted': out['fitted'], 'achieved': out['achieved'],
                      'bias': bias}, indent=2))


if __name__ == '__main__':
    main()
