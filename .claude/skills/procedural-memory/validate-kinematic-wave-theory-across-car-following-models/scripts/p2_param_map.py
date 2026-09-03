#!/usr/bin/env python3
"""PART 2 - ANALYTIC PARAMETER MAPPING.

Tests the closed-form kinematic-wave predictions against measured ring FDs:
    k_j   = 1000 / (length + minGap)              [veh/km]
    w     = (length + minGap) / tau               [m/s]
    q_max = v_f / (v_f*tau + length + minGap)*3600[veh/h]
    k_c   = q_max / v_f
by sweeping tau, minGap, length and sigma one factor at a time.

The density grid is expressed as a FRACTION of each variant's own analytic jam
density, so every variant is sampled over the same relative range of its FD
(otherwise a long-vehicle variant would be jammed before the grid even starts).
"""
import os, sys, json, argparse
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ring_lib as R
from p1_fit import fit_model, agg

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(OUT, 'net', 'ring1000.net.xml')
L, N_EDGES, END, WARMUP, STEP = 1000.0, 20, 1500.0, 750.0, 0.5
SEEDS = [42, 43]
VF_NOM = 30.0

FRACS = [0.04, 0.08, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.28,
         0.32, 0.40, 0.50, 0.60, 0.75, 0.90]

BASE = dict(length=5.0, minGap=2.5, tau=1.0, sigma=0.5)

VARIANTS = []
for t in (0.5, 0.8, 1.0, 1.5, 2.0):
    VARIANTS.append(('tau', t, dict(BASE, tau=t)))
for g in (1.0, 2.5, 4.0, 6.0):
    VARIANTS.append(('minGap', g, dict(BASE, minGap=g)))
for ln in (4.0, 5.0, 7.5, 12.0):
    VARIANTS.append(('length', ln, dict(BASE, length=ln)))
for s in (0.0, 0.2, 0.5, 0.8):
    VARIANTS.append(('sigma', s, dict(BASE, sigma=s)))

MODELS = ['Krauss', 'IDM', 'EIDM']       # models parameterised by tau/minGap/length


def one(job):
    model, vname, vval, params, n, seed, workdir = job
    tag = f'{model}_{vname}{vval}_n{n}_s{seed}'
    rou = os.path.join(workdir, tag + '.rou.xml')
    smf = os.path.join(workdir, tag + '.sum.xml')
    vt = R.vtype_xml('car', model, **params)
    pt = None
    for f in (0.9, 0.6, 0.4, 0.25, 0.1, 0.0):
        R.write_ring_routes(rou, n, L, N_EDGES, vt, perturb=True, dep_factor=f)
        p = R.run_ring(NET, rou, smf, END, step=STEP, seed=seed)
        if p.returncode != 0:
            return dict(model=model, variant=vname, value=vval, n_requested=n,
                        seed=seed, error=p.stderr[-500:])
        cand = R.ring_point(smf, L, WARMUP)
        if cand is None:
            continue
        pt = cand
        if abs(cand['running_last'] - n) < 0.5:
            break
    for f in (rou, smf):
        if os.path.exists(f):
            os.remove(f)
    if pt is None:
        return dict(model=model, variant=vname, value=vval, n_requested=n,
                    seed=seed, error='no samples')
    pt.update(model=model, variant=vname, value=vval, n_requested=n, seed=seed,
              perturb=True, **{f'p_{k}': v for k, v in params.items()})
    return pt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--from-cache', action='store_true')
    a = ap.parse_args()
    wd = os.path.join(OUT, 'runs', 'p2_param')
    os.makedirs(wd, exist_ok=True)
    jobs = []
    for model in MODELS:
        for vname, vval, params in VARIANTS:
            if vname == 'sigma' and model != 'Krauss':
                continue          # sigma is a Krauss-specific dawdling parameter
            kj = 1000.0 / (params['length'] + params['minGap'])
            ns = sorted(set(max(2, round(fr * kj)) for fr in FRACS))
            for n in ns:
                for s in SEEDS:
                    jobs.append((model, vname, vval, params, n, s, wd))
    print('jobs:', len(jobs), flush=True)
    res = []
    if a.from_cache:
        res = json.load(open(os.path.join(OUT, 'data', 'p2_points.json')))
        jobs = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(one, jobs, chunksize=4)):
            res.append(r)
            if (i + 1) % 200 == 0:
                print(f'{i+1}/{len(jobs)}', flush=True)
    if not a.from_cache:
        json.dump(res, open(os.path.join(OUT, 'data', 'p2_points.json'), 'w'), indent=1)

    # --------- fit each variant and compare with the closed forms --------------
    rows = []
    for model in MODELS:
        for vname, vval, params in VARIANTS:
            if vname == 'sigma' and model != 'Krauss':
                continue
            sub = [p for p in res if 'error' not in p and p['model'] == model
                   and p['variant'] == vname and p['value'] == vval]
            if len(sub) < 6:
                continue
            cells = agg(sub, key=('model', 'n_requested'))
            f = fit_model(cells, veh_len=params['length'], min_gap=params['minGap'])
            s0 = params['length'] + params['minGap']
            pred = dict(k_jam=1000.0 / s0,
                        w_ms=s0 / params['tau'],
                        q_max=VF_NOM / (VF_NOM * params['tau'] + s0) * 3600,
                        v_free_ms=VF_NOM)
            pred['k_crit'] = pred['q_max'] / (pred['v_free_ms'] * 3.6)
            # capacity prediction using the MEASURED free speed (isolates tau)
            vfm = f['v_free_ms']
            pred['q_max_vfcorr'] = vfm / (vfm * params['tau'] + s0) * 3600
            err = lambda meas, p: 100.0 * (meas - p) / p if p else float('nan')
            rows.append(dict(
                model=model, variant=vname, value=vval, **{f'p_{k}': v for k, v in params.items()},
                meas_v_free_ms=f['v_free_ms'], meas_q_max=f['q_max'],
                meas_q_max_observed=f['q_max_observed'],
                meas_k_crit=f['k_crit'], meas_k_jam=f['k_jam_fit'],
                meas_k_jam_standstill=f['k_jam_standstill'], meas_w_ms=f['w_ms'],
                pred_v_free_ms=pred['v_free_ms'], pred_q_max=pred['q_max'],
                pred_q_max_vfcorr=pred['q_max_vfcorr'],
                pred_k_crit=pred['k_crit'], pred_k_jam=pred['k_jam'], pred_w_ms=pred['w_ms'],
                err_v_free_pct=err(f['v_free_ms'], pred['v_free_ms']),
                err_q_max_pct=err(f['q_max'], pred['q_max']),
                err_q_max_vfcorr_pct=err(f['q_max'], pred['q_max_vfcorr']),
                err_k_crit_pct=err(f['k_crit'], pred['k_crit']),
                err_k_jam_pct=err(f['k_jam_fit'], pred['k_jam']),
                err_w_pct=err(f['w_ms'], pred['w_ms']),
                r2_cong=f['r2_cong_branch'], r2_tri=f['r2_triangle_overall'],
                gridlock_artifact=f['gridlock_artifact']))
    json.dump(rows, open(os.path.join(OUT, 'data', 'p2_param_table.json'), 'w'), indent=1)

    hdr = (f'{"model":7s} {"factor":7s} {"val":>5s} | {"vf m/s":>7s}{"e%":>7s} | '
           f'{"kj":>7s}{"e%":>7s} | {"w m/s":>6s}{"e%":>7s} | {"qmax":>7s}{"e%":>7s}{"e%vf":>7s}')
    print('\n' + hdr); print('-' * len(hdr))
    for r in rows:
        print(f'{r["model"]:7s} {r["variant"]:7s} {r["value"]:5.2f} | '
              f'{r["meas_v_free_ms"]:7.2f}{r["err_v_free_pct"]:+7.1f} | '
              f'{r["meas_k_jam"]:7.1f}{r["err_k_jam_pct"]:+7.1f} | '
              f'{r["meas_w_ms"]:6.2f}{r["err_w_pct"]:+7.1f} | '
              f'{r["meas_q_max"]:7.0f}{r["err_q_max_pct"]:+7.1f}{r["err_q_max_vfcorr_pct"]:+7.1f}')
    print('\nerrors in sweep:', len([r for r in res if 'error' in r]))


if __name__ == '__main__':
    main()
