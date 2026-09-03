#!/usr/bin/env python3
"""STAGE 2/3 batch: 9 arms x N seeds, Common Random Numbers across arms.

Arms (all share the identical calibrated driver population, demand and seeds):
  baseline              no enforcement
  limit40               posted 50 -> 40 km/h, no enforcement
  point_p40/70/95       point speed camera at x=2000, compliant fraction p
  section_p40/70/95     2 km section (average-speed) enforcement, x in [1000,3000]
  point_p95_maxspeed    identical to point_p95 but actuated with
                        traci.vehicle.setMaxSpeed instead of setSpeedFactor
                        (actuator-artifact control arm)

CRN: the same seed list is used in every arm. The seed drives departure times,
lane choice and the per-vehicle speedFactor draw; the compliance draw is keyed
on (seed, vehicle id) only, so a given vehicle has the same u in every arm and
the compliant sets are nested across p. verify_crn.py checks this held.

After each run the raw directory is reduced to metrics.json + profile.csv, and
the bulky raw files are gzipped in place (traj.csv.gz kept only for the first
seed of each arm, to bound disk while keeping one fully auditable raw run/arm).
"""
import argparse
import concurrent.futures as cf
import gzip
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ARMS = [
    ('baseline',           dict(mode='baseline', p=0.0)),
    ('limit40',            dict(mode='limit40',  p=0.0)),
    ('point_p40',          dict(mode='point',    p=0.40)),
    ('point_p70',          dict(mode='point',    p=0.70)),
    ('point_p95',          dict(mode='point',    p=0.95)),
    ('section_p40',        dict(mode='section',  p=0.40)),
    ('section_p70',        dict(mode='section',  p=0.70)),
    ('section_p95',        dict(mode='section',  p=0.95)),
    ('point_p95_maxspeed', dict(mode='point',    p=0.95, actuator='maxspeed')),
]


def one(args):
    arm, cfg, seed, a, keep_traj = args
    outdir = os.path.join(a.root, arm, f'seed{seed}')
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, os.path.join(HERE, 'run_scenario.py'),
           '--net', a.net, '--outdir', outdir, '--seed', str(seed),
           '--mu', str(a.mu), '--sigma', str(a.sigma), '--vph', str(a.vph),
           '--end', str(a.end), '--demand-end', str(a.demand_end),
           '--step-length', '0.5', '--mode', cfg['mode'], '--p', str(cfg['p'])]
    if 'actuator' in cfg:
        cmd += ['--actuator', cfg['actuator']]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return (arm, seed, 'RUNFAIL', r.stdout[-2000:] + r.stderr[-2000:])
    r2 = subprocess.run([sys.executable, os.path.join(HERE, 'compute_metrics.py'),
                         '--rundir', outdir], capture_output=True, text=True)
    if r2.returncode != 0:
        return (arm, seed, 'METRICFAIL', r2.stdout[-2000:] + r2.stderr[-2000:])
    # shrink: gzip the bulky XML, drop FCD except for the audit seed
    for f in ('e1_instant.xml', 'summary.xml', 'tripinfo.xml', 'ssm.xml'):
        p = os.path.join(outdir, f)
        if os.path.exists(p):
            with open(p, 'rb') as fi, gzip.open(p + '.gz', 'wb') as fo:
                shutil.copyfileobj(fi, fo)
            os.remove(p)
    if not keep_traj:
        os.remove(os.path.join(outdir, 'traj.csv.gz'))
    return (arm, seed, 'OK', r2.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--root', required=True)
    ap.add_argument('--mu', type=float, default=1.175628)
    ap.add_argument('--sigma', type=float, default=0.175172)
    ap.add_argument('--vph', type=float, default=1200.0)
    ap.add_argument('--end', type=float, default=3600.0)
    ap.add_argument('--demand-end', type=float, default=1800.0)
    ap.add_argument('--seeds', default='1,2,3,4,5,6,7,8')
    ap.add_argument('--jobs', type=int, default=6)
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(',')]
    jobs = [(arm, cfg, s, a, s == seeds[0]) for arm, cfg in ARMS for s in seeds]
    print(f'{len(jobs)} runs, {a.jobs} workers')
    fails = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for arm, seed, status, msg in ex.map(one, jobs):
            print(f'[{status}] {arm} seed{seed} {msg[:160]}')
            if status != 'OK':
                fails.append((arm, seed, status, msg))
    json.dump({'arms': [x[0] for x in ARMS], 'seeds': seeds,
               'mu': a.mu, 'sigma': a.sigma, 'vph': a.vph,
               'failures': fails},
              open(os.path.join(a.root, 'batch_manifest.json'), 'w'), indent=2)
    print('failures:', len(fails))


if __name__ == '__main__':
    main()
