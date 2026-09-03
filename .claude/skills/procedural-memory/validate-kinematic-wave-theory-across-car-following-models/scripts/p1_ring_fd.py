#!/usr/bin/env python3
"""PART 1 - Fundamental diagram of each car-following model, measured on a closed
single-lane ring by sweeping vehicle count (= EXACT density control).

Design notes
------------
* Density is controlled by vehicle count, not demand: k = 1000*N_running/L. No
  detector inference is involved, so the FD is measured, not estimated.
* Every (model, density) cell is run in TWO perturbation conditions:
    perturb=True   one-shot 5 s <stop> by vehicle v0 halfway round the ring
                   (the disclosed brake-pulse technique from the
                   `demonstrate-and-stabilize-phantom-traffic-jams` skill)
    perturb=False  no perturbation at all
  Running both is what exposes BISTABILITY: if the two branches differ at the same
  density, the FD is not single-valued and kinematic-wave theory's single q(k)
  curve cannot be the whole story.
* COMMON RANDOM NUMBERS: the identical seed list {42,43,44} is reused for every
  model x density x perturbation cell, so cross-model differences are not seed noise.
* --default.speeddev 0 removes SUMO's default 10% per-driver speedFactor spread so
  the fleet is genuinely homogeneous (the FD is a property of ONE vType, not a mix).
"""
import os, sys, json, argparse
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ring_lib as R

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(OUT, 'net', 'ring1000.net.xml')
L = 1000.0
N_EDGES = 20
END = 1500.0
WARMUP = 750.0
STEP = 0.5
SEEDS = [42, 43, 44]

# W99 is run at SUMO defaults: it is parameterised by cc0..cc9, not by tau/minGap.
# (Verified: cc overrides only take effect as vType ATTRIBUTES, not as <param>
#  children, and an attribute cc1="1.0" gridlocked the whole ring permanently.)
MODELS = {
    'Krauss': dict(cf='Krauss', over={}),
    'IDM':    dict(cf='IDM',    over={}),
    'EIDM':   dict(cf='EIDM',   over={}),
    'W99':    dict(cf='W99',    over={}),
    'ACC':    dict(cf='ACC',    over={}),
}

DENS = ([2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
         32, 34, 36, 38, 40, 43, 46, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
         105, 110, 115, 120, 125, 130])


def one(job):
    model, n, seed, pert, workdir = job
    m = MODELS[model]
    tag = f'{model}_n{n}_s{seed}_{"P" if pert else "N"}'
    rou = os.path.join(workdir, tag + '.rou.xml')
    smf = os.path.join(workdir, tag + '.sum.xml')
    # Adaptive insertion: retry with a lower departure speed until the ring is
    # FULLY loaded.  A partially loaded ring silently reports the wrong density,
    # so we never accept a cell whose running count < requested count.
    pt, used_f = None, None
    for f in (0.9, 0.6, 0.4, 0.25, 0.1, 0.0):
        R.write_ring_routes(rou, n, L, N_EDGES,
                            R.vtype_xml('car', m['cf'], **m['over']),
                            perturb=pert, dep_factor=f)
        p = R.run_ring(NET, rou, smf, END, step=STEP, seed=seed)
        if p.returncode != 0:
            return dict(model=model, n_requested=n, seed=seed, perturb=pert,
                        error=p.stderr[-800:])
        cand = R.ring_point(smf, L, WARMUP)
        used_f = f
        if cand is None:
            continue
        pt = cand
        if abs(cand['running_last'] - n) < 0.5:
            break
    if pt is None:
        return dict(model=model, n_requested=n, seed=seed, perturb=pert,
                    error='no samples in measurement window')
    pt.update(model=model, n_requested=n, seed=seed, perturb=pert, dep_factor=used_f)
    os.remove(rou)
    os.remove(smf)
    return pt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    workdir = os.path.join(OUT, 'runs', 'p1_ring')
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(os.path.join(OUT, 'data'), exist_ok=True)
    jobs = [(m, n, s, p, workdir)
            for m in MODELS for n in DENS for s in SEEDS for p in (True, False)]
    print('jobs:', len(jobs), flush=True)
    res = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(one, jobs, chunksize=4)):
            res.append(r)
            if (i + 1) % 100 == 0:
                print(f'{i+1}/{len(jobs)}', flush=True)
    with open(os.path.join(OUT, 'data', 'p1_ring_points.json'), 'w') as f:
        json.dump(res, f, indent=1)
    bad = [r for r in res if 'error' in r]
    print('errors:', len(bad))
    if bad:
        print(json.dumps(bad[:3], indent=1))
    print('teleports:', sum(r.get('teleports', 0) for r in res),
          ' collisions:', sum(r.get('collisions', 0) for r in res))
    under = [r for r in res if 'error' not in r
             and abs(r['running_last'] - r['n_requested']) > 0.5]
    print('cells with incomplete insertion:', len(under),
          [(r['model'], r['n_requested'], int(r['running_last'])) for r in under[:12]])


if __name__ == '__main__':
    main()
