#!/usr/bin/env python3
"""
Build the three alternatives' signal plans.

  A (do-nothing base) : a fixed-time Webster plan sized for the demand of
        --stale-years ago (i.e. opening demand / (1+g)^stale_years), NOT coordinated.
        This represents an existing plan that was last retimed years ago and is
        never touched again -- a more defensible do-nothing than netconvert's
        arbitrary default program, which would inflate the retiming benefit.
  B (operational)     : tlsCycleAdaptation --unified-cycle sized for THIS year's
        demand, plus tlsCoordinator offsets (green wave). Recomputed per analysis
        year, which is what the recurring retiming cost buys.
  C (capital)         : same treatment as B, but on the left-turn-bay network.

Uses the wrappers already in procedural memory:
  optimize-signals-by-tlscycleadaptation/scripts/optimize_signals.py
  optimize-signals-by-tlscoordinator/scripts/coordinate_signals.py
"""
import argparse
import os
import subprocess
import sys

PM = os.path.expanduser('~/Desktop/simskill/.claude/skills/procedural-memory')
CYC = os.path.join(PM, 'optimize-signals-by-tlscycleadaptation/scripts/optimize_signals.py')
COO = os.path.join(PM, 'optimize-signals-by-tlscoordinator/scripts/coordinate_signals.py')


def run(cmd):
    print('  $', ' '.join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f'failed: {cmd[0]}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--routes', required=True, help='routed .rou.xml for the target demand')
    ap.add_argument('--out-prefix', required=True)
    ap.add_argument('--mode', choices=['stale', 'retimed'], required=True)
    ap.add_argument('--begin', type=float, default=1800.0)
    ap.add_argument('--sat-headway', type=float, default=2.0)
    ap.add_argument('--max-cycle', type=float, default=120.0)
    args = ap.parse_args()

    cyc_out = f'{args.out_prefix}_cycles.add.xml'
    cmd = [sys.executable, CYC, '-n', args.net, '-r', args.routes, '-o', cyc_out,
           '-b', int(args.begin), '-H', args.sat_headway, '--max-cycle', int(args.max_cycle),
           '-y', 4, '-a', 2, '-l', 4]
    if args.mode == 'retimed':
        cmd.append('--unified-cycle')
    run(cmd)
    files = [cyc_out]

    if args.mode == 'retimed':
        off_out = f'{args.out_prefix}_offsets.add.xml'
        run([sys.executable, COO, '-n', args.net, '-r', args.routes,
             '-o', off_out, '-a', cyc_out])
        files.append(off_out)

    print('PLAN_FILES=' + ','.join(files))


if __name__ == '__main__':
    main()
