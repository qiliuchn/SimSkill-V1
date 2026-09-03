#!/usr/bin/env python3
"""
Quantify the appraisal error caused by simulating ONLY the opening and horizon
years and interpolating the annual benefit stream linearly between them.

Runs the identical appraisal twice: once on all three simulated demand levels
(k = 0, 10, 20, piecewise-linear) and once with the mid point withheld (k = 0, 20,
single straight line). The mid point is then a genuine out-of-sample test of the
interpolation assumption, not a curve-fit.
"""
import csv
import os
import shutil
import subprocess
import sys
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))


def run(measures, out):
    subprocess.run([sys.executable, os.path.join(HERE, 'appraise.py'),
                    '--measures-dir', measures, '--out-dir', out],
                   capture_output=True, text=True, check=True)
    return json.load(open(os.path.join(out, 'appraisal_results.json')))


def main():
    measures, workdir, outcsv = sys.argv[1], sys.argv[2], sys.argv[3]
    two = os.path.join(workdir, 'measures_2pt')
    shutil.rmtree(two, ignore_errors=True)
    os.makedirs(two)
    for f in glob.glob(os.path.join(measures, '*.json')):
        if '_y10_' not in os.path.basename(f):
            shutil.copy(f, two)

    a = run(measures, os.path.join(workdir, 'out_3pt'))
    b = run(two, os.path.join(workdir, 'out_2pt'))

    rows = []
    for alt in ('B', 'C'):
        for m in ('pv_benefits', 'pv_costs', 'npv', 'bcr'):
            x, y = a['central'][alt][m], b['central'][alt][m]
            rows.append(dict(quantity=f'{alt}: {m}', three_point=x, two_point=y,
                             error_pct=100 * (y - x) / abs(x) if x else ''))
    for m in ('delta_pv_benefits', 'incremental_bcr'):
        x, y = a['central']['incremental'][m], b['central']['incremental'][m]
        rows.append(dict(quantity=f'C vs B incremental: {m}', three_point=x,
                         two_point=y, error_pct=100 * (y - x) / abs(x)))
    ic = {r['alt']: r for r in a['interpolation_check']}
    for alt in ('B', 'C'):
        rows.append(dict(
            quantity=f'{alt}: mid-year (k=10) hourly benefit, USD/peak-hour',
            three_point=ic[alt]['simulated_hourly_benefit'],
            two_point=ic[alt]['linear_predicted_hourly_benefit'],
            error_pct=ic[alt]['error_pct']))

    with open(outcsv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['quantity', 'three_point', 'two_point',
                                          'error_pct'])
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"  {r['quantity']:<52} {r['three_point']:>14,.2f} "
              f"{r['two_point']:>14,.2f} {r['error_pct']:>9.1f}%")


if __name__ == '__main__':
    main()
