#!/usr/bin/env python3
"""
Full replication design driver.

  alternatives : A (do-nothing, stale uncoordinated fixed-time plan on the base net)
                 B (retimed + coordinated, base net)
                 C (retimed + coordinated, left-turn-bay net at J2/J3)
  years        : growth exponents k = 0, 10, 20 (opening, mid, horizon)
                 demand scale = OPENING_SCALE * (1+g)^k
  seeds        : SEEDS, used as BOTH the demand-generation seed and the sumo seed,
                 and shared across all alternatives -> Common Random Numbers.
                 The mid year is simulated (not interpolated) purely so the
                 linear-interpolation assumption can be validated against it.

Signal plans are designed against a SEPARATE demand realisation (PLAN_SEED) so no
alternative is tuned to the exact realisation it is scored on.
"""
import argparse
import itertools
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))

OPENING_SCALE = 0.70       # ~72% of alternative A's measured served capacity
GROWTH = 0.015
YEARS = [0, 10, 20]
SEEDS = [1, 2, 3, 4, 5, 6]
PLAN_SEED = 91
STALE_YEARS = 8            # A's plan was last retimed 8 years before opening
T0, T1, END = 1800.0, 5400.0, 14400.0

NET = {'A': 'outputs/net_base/corridor_base.net.xml',
       'B': 'outputs/net_base/corridor_base.net.xml',
       'C': 'outputs/net_bay/corridor_bay.net.xml'}
VT = 'outputs/demand/vtypes.add.xml'


def sh(cmd, quiet=True):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-5000:])
        raise SystemExit('FAILED: ' + ' '.join(str(c) for c in cmd))
    if not quiet:
        print(r.stdout.strip())
    return r.stdout


def scale(k):
    return OPENING_SCALE * (1 + GROWTH) ** k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default='work/batch')
    ap.add_argument('--measures', default='outputs/measures')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--stage', choices=['plans', 'runs', 'all'], default='all')
    args = ap.parse_args()
    os.chdir(ROOT)
    os.makedirs(args.work, exist_ok=True)
    os.makedirs(args.measures, exist_ok=True)
    S = HERE

    # ---------------- demand ----------------
    trips = {}
    for k in YEARS:
        for s in SEEDS:
            f = f'{args.work}/trips_y{k}_s{s}.trips.xml'
            trips[(k, s)] = f
            if not os.path.exists(f):
                sh([sys.executable, f'{S}/build_demand.py', '--seed', s,
                    '--growth', f'{scale(k):.6f}', '--out', f])
    # plan-design demand (separate realisation)
    plan_trips = {}
    for k in YEARS:
        f = f'{args.work}/plan_y{k}.trips.xml'
        plan_trips[k] = f
        if not os.path.exists(f):
            sh([sys.executable, f'{S}/build_demand.py', '--seed', PLAN_SEED,
                '--growth', f'{scale(k):.6f}', '--out', f])
    stale_trips = f'{args.work}/plan_stale.trips.xml'
    if not os.path.exists(stale_trips):
        sh([sys.executable, f'{S}/build_demand.py', '--seed', PLAN_SEED,
            '--growth', f'{OPENING_SCALE / (1 + GROWTH) ** STALE_YEARS:.6f}',
            '--out', stale_trips])

    # ---------------- signal plans ----------------
    plans = {}
    if args.stage in ('plans', 'all'):
        print('--- building signal plans ---')
        # A: stale, uncoordinated, base net, one plan for every year
        rou = f'{args.work}/plan_stale.rou.xml'
        sh(['duarouter', '-n', NET['A'], '-r', stale_trips, '-a', VT, '-o', rou,
            '--seed', 1, '--no-step-log', '--no-warnings'])
        sh([sys.executable, f'{S}/make_plans.py', '--net', NET['A'], '--routes', rou,
            '--out-prefix', f'{args.work}/planA', '--mode', 'stale', '--begin', T0])
        planA = f'{args.work}/planA_cycles.add.xml'
        for k in YEARS:
            plans[('A', k)] = planA
        # B and C: retimed + coordinated per year, on their own network
        for alt in ('B', 'C'):
            for k in YEARS:
                rou = f'{args.work}/plan_{alt}_y{k}.rou.xml'
                sh(['duarouter', '-n', NET[alt], '-r', plan_trips[k], '-a', VT,
                    '-o', rou, '--seed', 1, '--no-step-log', '--no-warnings'])
                pre = f'{args.work}/plan{alt}_y{k}'
                sh([sys.executable, f'{S}/make_plans.py', '--net', NET[alt],
                    '--routes', rou, '--out-prefix', pre, '--mode', 'retimed',
                    '--begin', T0])
                plans[(alt, k)] = f'{pre}_cycles.add.xml,{pre}_offsets.add.xml'
        print('    plans built')
    else:
        planA = f'{args.work}/planA_cycles.add.xml'
        for k in YEARS:
            plans[('A', k)] = planA
        for alt in ('B', 'C'):
            for k in YEARS:
                pre = f'{args.work}/plan{alt}_y{k}'
                plans[(alt, k)] = f'{pre}_cycles.add.xml,{pre}_offsets.add.xml'

    if args.stage == 'plans':
        return

    # ---------------- runs ----------------
    jobs = []
    for alt, k, s in itertools.product(('A', 'B', 'C'), YEARS, SEEDS):
        out = f'{args.measures}/alt{alt}_y{k}_s{s}.json'
        if os.path.exists(out):
            continue
        jobs.append([sys.executable, f'{S}/run_case.py',
                     '--net', NET[alt], '--trips', trips[(k, s)], '--vtypes', VT,
                     '--plans', plans[(alt, k)], '--seed', s,
                     '--label', f'alt{alt}_y{k}_s{s}', '--work-dir', f'{args.work}/runs',
                     '--out-json', out, '--t0', T0, '--t1', T1, '--end', END, '--ssm'])
    print(f'--- {len(jobs)} runs to execute on {args.jobs} workers ---')

    done = [0]

    def go(c):
        r = subprocess.run([str(x) for x in c], capture_output=True, text=True)
        done[0] += 1
        tag = c[c.index('--label') + 1]
        print(f'[{done[0]}/{len(jobs)}] {r.stdout.strip() or tag + " FAILED"}',
              flush=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr[-2500:])
        return r.returncode

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        rcs = list(ex.map(go, jobs))
    bad = sum(1 for r in rcs if r != 0)
    print(f'--- finished, {bad} failures ---')


if __name__ == '__main__':
    main()
