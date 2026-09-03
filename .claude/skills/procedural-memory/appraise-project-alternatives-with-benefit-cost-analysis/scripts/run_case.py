#!/usr/bin/env python3
"""Run one (alternative, year, seed) case end to end and emit its measures JSON.

Steps: route the (already-generated) trips on this alternative's network with
duarouter, run sumo with the alternative's signal-plan additional files, extract
measures over the analysis window, then DELETE the bulky raw outputs (the SSM log
alone is ~70 MB per run) keeping only the measures JSON + a small run log.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract_measures as EM  # noqa: E402


def sh(cmd, log):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    with open(log, 'a') as f:
        f.write('$ ' + ' '.join(str(c) for c in cmd) + '\n')
        f.write(r.stdout[-4000:] + '\n' + r.stderr[-8000:] + '\n')
    if r.returncode != 0:
        raise SystemExit(f'FAILED ({r.returncode}): {" ".join(str(c) for c in cmd)}\n'
                         f'{r.stderr[-3000:]}')
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--trips', required=True)
    ap.add_argument('--vtypes', required=True)
    ap.add_argument('--plans', default='', help='comma-separated additional files')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--t0', type=float, default=1800.0)
    ap.add_argument('--t1', type=float, default=5400.0)
    ap.add_argument('--end', type=float, default=14400.0)
    ap.add_argument('--ssm', action='store_true')
    ap.add_argument('--keep', action='store_true')
    args = ap.parse_args()

    wd = os.path.join(args.work_dir, args.label)
    os.makedirs(wd, exist_ok=True)
    log = os.path.join(wd, 'run.log')
    open(log, 'w').close()

    rou = os.path.join(wd, 'routes.rou.xml')
    sh(['duarouter', '-n', args.net, '-r', args.trips, '-a', args.vtypes,
        '-o', rou, '--seed', args.seed, '--no-step-log', '--no-warnings'], log)

    trip, summ = os.path.join(wd, 'tripinfo.xml'), os.path.join(wd, 'summary.xml')
    coll = os.path.join(wd, 'collisions.xml')
    ssm = os.path.join(wd, 'ssm.xml') if args.ssm else None
    cmd = ['sumo', '-n', args.net, '-r', rou, '--begin', 0, '--end', args.end,
           '--seed', args.seed, '--time-to-teleport', 300,
           '--tripinfo-output', trip, '--summary-output', summ,
           '--collision-output', coll,
           '--device.emissions.probability', 1.0,
           '--no-step-log', '--no-warnings',
           '--summary-output.period', 10]
    if args.plans:
        cmd += ['-a', args.plans]
    # ALWAYS give the SSM device an explicit output file. `--device.ssm.probability
    # 0.0` does NOT switch off a device that a vType enabled via
    # <param key="has.ssm.device" value="true"/> -- verified directly: with the
    # param set and probability 0.0, SUMO still ran the device and, with no
    # --device.ssm.file, wrote ONE ssm_<vehID>.xml PER VEHICLE into the current
    # working directory (162 stray files from a 302-vehicle run). Pointing the
    # device at a single throwaway file keeps the cwd clean.
    cmd += ['--device.ssm.file', ssm or os.path.join(wd, 'ssm_discard.xml')]
    sh(cmd, log)

    r = {'label': args.label}
    r.update(EM.parse_tripinfo(trip, args.t0, args.t1))
    r.update(EM.parse_summary(summ))
    r.update(EM.parse_ssm(ssm, args.t0, args.t1))
    r['ssm_enabled'] = bool(ssm)
    r['n_veh'] = r['n_car'] + r['n_truck']
    r['vht_total_h'] = r['vht_car_h'] + r['vht_truck_h']
    r['vkt_total_km'] = r['vkt_car_km'] + r['vkt_truck_km']
    r['timeloss_total_h'] = r['timeloss_car_h'] + r['timeloss_truck_h']
    r['fuel_l'] = r['fuel_mg'] / 1e6 / 0.74
    r['co2_t'] = r['co2_mg'] / 1e9
    r['nox_kg'] = r['nox_mg'] / 1e6
    r['pmx_kg'] = r['pmx_mg'] / 1e6
    r['never_departed'] = r['loaded'] - r['inserted']
    # count real collisions independently of the SSM type-111 code
    r['collision_records'] = 0
    if os.path.exists(coll):
        with open(coll) as f:
            r['collision_records'] = f.read().count('<collision ')

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, 'w') as f:
        json.dump(r, f, indent=1)
    if not args.keep:
        shutil.move(log, os.path.join(args.work_dir, args.label + '.log'))
        shutil.rmtree(wd, ignore_errors=True)
    print(f'{args.label}: veh={r["n_veh"]} VHT={r["vht_total_h"]:.1f}h '
          f'TL={r["timeloss_total_h"]:.1f}h tel={r["teleports"]} '
          f'coll={r["collisions"]}/{r["collision_records"]} nodep={r["never_departed"]}')


if __name__ == '__main__':
    main()
