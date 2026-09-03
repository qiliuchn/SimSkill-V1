#!/usr/bin/env python3
"""Validity checks on the replication batch, run BEFORE any appraisal number is
believed. Checks, in order of how badly each would invalidate the study:

 1. CRN integrity  - the analysed trip set must be IDENTICAL across alternatives
                     for a given (year, seed); if it is not, alternatives are being
                     scored on different demand.
 2. Teleports      - a teleport is SUMO discarding a stuck vehicle; any nonzero
                     count means the delay measures understate reality.
 3. Collisions     - cross-checked against BOTH summary/collisions and the
                     --collision-output record count, because SSM encounter
                     type 111 is NOT a real collision (verified project gotcha).
 4. Insertion backlog - vehicles loaded but never inserted never get measured,
                     which makes a congested alternative look artificially good.
 5. Replication adequacy - coefficient of variation per alternative-year, and
                     whether the seed-to-seed spread is bimodal (gridlock/not),
                     which a mean +- CI would misrepresent.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np


def main(d):
    runs = defaultdict(dict)
    for f in sorted(glob.glob(os.path.join(d, 'alt*_y*_s*.json'))):
        m = re.match(r'alt([ABC])_y(\d+)_s(\d+)\.json', os.path.basename(f))
        runs[(m.group(1), int(m.group(2)))][int(m.group(3))] = json.load(open(f))

    fails = []
    print('=== 1. CRN integrity: identical analysed trip set across alternatives ===')
    years = sorted({k for (_, k) in runs})
    for k in years:
        for s in sorted(runs[('A', k)]):
            n = {a: runs[(a, k)][s]['n_veh'] for a in 'ABC' if s in runs[(a, k)]}
            ok = len(set(n.values())) == 1
            if not ok:
                fails.append(f'CRN mismatch y{k} s{s}: {n}')
            print(f'  y{k:>2} s{s}: n_veh {n}  {"OK" if ok else "<-- MISMATCH"}')

    print('\n=== 2-4. teleports / collisions / insertion backlog ===')
    for (a, k) in sorted(runs):
        tel = [r['teleports'] for r in runs[(a, k)].values()]
        col = [r['collisions'] for r in runs[(a, k)].values()]
        crec = [r.get('collision_records', 0) for r in runs[(a, k)].values()]
        nod = [r['never_departed'] for r in runs[(a, k)].values()]
        t111 = [r.get('conf_type111', 0) for r in runs[(a, k)].values()]
        bad = sum(tel) or sum(col) or sum(crec) or sum(nod)
        if bad:
            fails.append(f'validity {a} y{k}: tel={sum(tel)} col={sum(col)} '
                         f'colrec={sum(crec)} neverDeparted={sum(nod)}')
        print(f'  {a} y{k:>2}: teleports={sum(tel):3d}  summary.collisions={sum(col):3d}  '
              f'collision-output records={sum(crec):3d}  never-departed={sum(nod):3d}  '
              f'| SSM type-111 encounters={sum(t111):5d} '
              f'{"(NOT real collisions - known gotcha)" if sum(t111) and not sum(col) else ""}')

    print('\n=== 5. replication adequacy (CV across seeds) ===')
    print(f'  {"case":>8} {"n":>2} {"mean VHT":>10} {"sd":>7} {"CV%":>6} '
          f'{"mean TL":>9} {"CV%":>6} {"min/max VHT ratio":>18}')
    for (a, k) in sorted(runs):
        v = np.array([r['vht_total_h'] for r in runs[(a, k)].values()])
        tl = np.array([r['timeloss_total_h'] for r in runs[(a, k)].values()])
        cv = v.std(ddof=1) / v.mean() * 100
        cvt = tl.std(ddof=1) / tl.mean() * 100
        ratio = v.max() / v.min()
        flag = '  <-- possible bimodality' if ratio > 1.5 else ''
        print(f'  {a} y{k:>2} {len(v):>3} {v.mean():>10.1f} {v.std(ddof=1):>7.2f} '
              f'{cv:>6.2f} {tl.mean():>9.1f} {cvt:>6.2f} {ratio:>18.3f}{flag}')

    print('\n=== 6. paired differences (CRN) vs unpaired spread ===')
    for k in years:
        for a, b in (('B', 'A'), ('C', 'A'), ('C', 'B')):
            seeds = sorted(set(runs[(a, k)]) & set(runs[(b, k)]))
            d1 = np.array([runs[(b, k)][s]['vht_total_h'] - runs[(a, k)][s]['vht_total_h']
                           for s in seeds])
            pooled = np.std([runs[(b, k)][s]['vht_total_h'] for s in seeds], ddof=1)
            print(f'  y{k:>2} {b}->{a}: mean dVHT={d1.mean():8.2f} h  sd(paired)={d1.std(ddof=1):6.3f}  '
                  f'sd(single-arm)={pooled:6.3f}  variance-reduction={pooled**2/max(d1.var(ddof=1),1e-12):7.1f}x')

    print('\n' + ('ALL VALIDITY CHECKS PASSED' if not fails
                  else 'FAILURES:\n  ' + '\n  '.join(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
