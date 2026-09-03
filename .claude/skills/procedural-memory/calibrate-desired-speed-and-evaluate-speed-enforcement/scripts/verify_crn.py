#!/usr/bin/env python3
"""Verify Common Random Numbers actually held across arms.

For every seed, the driver population must be IDENTICAL in every arm:
  - the same set of vehicle ids departed
  - each vehicle sampled the same speedFactor
  - each vehicle got the same compliance draw, so the compliant sets are
    NESTED across p (p=0.40 subset of p=0.70 subset of p=0.95)

If SUMO's RNG stream were perturbed by the TraCI intervention, the speedFactor
map would drift between arms and every "paired" difference would be
contaminated. This is a check, not an assumption.
"""
import json
import os
import sys

root = sys.argv[1]
out = sys.argv[2]
arms = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
seeds = sorted({int(s.replace('seed', '')) for a in arms
                for s in os.listdir(os.path.join(root, a)) if s.startswith('seed')})

res = {'arms': arms, 'seeds': seeds, 'per_seed': {}, 'all_identical': True,
       'nesting_ok': True}
for sd in seeds:
    ref = None
    ref_arm = None
    status = {}
    comp = {}
    for a in arms:
        p = os.path.join(root, a, f'seed{sd}', 'run_meta.json')
        if not os.path.exists(p):
            continue
        m = json.load(open(p))
        sf = m['speed_factors']
        comp[a] = {v for v, c in m['compliant'].items() if c}
        if ref is None:
            ref, ref_arm = sf, a
            status[a] = 'reference'
            continue
        same_ids = set(sf) == set(ref)
        same_vals = same_ids and all(abs(sf[k] - ref[k]) < 1e-12 for k in sf)
        status[a] = {'same_vehicle_ids': same_ids, 'same_speedFactors': same_vals,
                     'n_vehicles': len(sf),
                     'n_differing': (0 if same_vals else
                                     sum(1 for k in sf if k in ref and abs(sf[k] - ref[k]) > 1e-12))}
        if not same_vals:
            res['all_identical'] = False
    # nesting of compliant sets
    nest = {}
    for fam in ('point', 'section'):
        s40 = comp.get(f'{fam}_p40'); s70 = comp.get(f'{fam}_p70'); s95 = comp.get(f'{fam}_p95')
        if s40 is not None and s70 is not None and s95 is not None:
            nest[fam] = {'n40': len(s40), 'n70': len(s70), 'n95': len(s95),
                         '40_in_70': s40 <= s70, '70_in_95': s70 <= s95}
            if not (s40 <= s70 and s70 <= s95):
                res['nesting_ok'] = False
    # point_p95 vs point_p95_maxspeed must have the SAME compliant set
    if 'point_p95' in comp and 'point_p95_maxspeed' in comp:
        nest['p95_vs_p95_maxspeed_same_set'] = comp['point_p95'] == comp['point_p95_maxspeed']
        if not nest['p95_vs_p95_maxspeed_same_set']:
            res['nesting_ok'] = False
    res['per_seed'][sd] = {'reference_arm': ref_arm, 'arms': status, 'nesting': nest}

json.dump(res, open(out, 'w'), indent=2)
print('all speedFactor maps identical across arms:', res['all_identical'])
print('compliant sets nested across p:', res['nesting_ok'])
print(json.dumps(res['per_seed'][seeds[0]]['nesting'], indent=1))
