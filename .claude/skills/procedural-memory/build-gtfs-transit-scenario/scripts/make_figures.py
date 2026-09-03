#!/usr/bin/env python
"""Figures for the GTFS-transit scenario study.

  fig_deviation_vs_stop_sequence.png : schedule deviation growth along the route,
                                       one series per background-car-demand level,
                                       mean +/- 95% CI over the 8 CRN seeds
  fig_pt_time_space.png              : PT time-space diagram (published timetable vs
                                       simulated) for one line, free-flow vs congested
  fig_import_attrition_map.png       : which published stops survived the import
  fig_ontime_and_headway_vs_demand.png : on-time performance and headway CV vs demand
"""
import argparse
import glob
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
from scipy import stats                  # noqa: E402

# categorical slots 1..4 of the validated reference palette (light mode)
C = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#4a3aa7']
INK = '#1c1c1c'
MUTED = '#6b6b6b'
GRID = '#dcdcdc'

plt.rcParams.update({
    'figure.dpi': 130, 'savefig.dpi': 130, 'font.size': 9,
    'axes.edgecolor': GRID, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.titlesize': 10,
    'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
    'axes.spines.top': False, 'axes.spines.right': False, 'legend.frameon': False,
})


def haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def tci(v):
    v = np.asarray([x for x in v if x is not None], dtype=float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else np.nan, 0.0)
    m = v.mean()
    h = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v))
    return float(m), float(h)


def fig_dev_vs_seq(metrics_dir, rates, out):
    """Deviation growth along the route, split by whether gtfs2pt had to --repair
    that line's route (lines 14 and 9) or imported it cleanly (lines 15 and 75)."""
    groups = [('14:0', 'line 14 westbound - route needed --repair (detour factor 1.82)'),
              ('15:0', 'line 15 westbound - clean import (detour factor 1.03)')]
    fig, axes = plt.subplots(1, 2, figsize=(9.8, 3.9), sharey=True)
    for ax, (line, title) in zip(axes, groups):
        for i, rt in enumerate(rates):
            per_seq = defaultdict(list)
            for p in glob.glob(os.path.join(metrics_dir, 'gtfs_rel_r%d_s*.json' % rt)):
                d = json.load(open(p))
                for k, v in d.get('dev_by_seq_by_line', {}).get(line, {}).items():
                    per_seq[int(k)].append(v)
            xs = sorted(k for k in per_seq if len(per_seq[k]) >= 3)
            if not xs:
                continue
            ms, hs = zip(*[tci(per_seq[k]) for k in xs])
            ms, hs = np.array(ms), np.array(hs)
            lab = '0 (free-flow control)' if rt == 0 else '%d veh/h' % rt
            ax.plot(xs, ms, color=C[i], lw=2, label=lab)
            ax.fill_between(xs, ms - hs, ms + hs, color=C[i], alpha=0.16, lw=0)
            ax.annotate(lab.split(' ')[0], (xs[-1], ms[-1]), xytext=(4, 0),
                        textcoords='offset points', color=C[i], fontsize=8, va='center')
        ax.axhline(0, color=MUTED, lw=1, ls=':')
        ax.set_xlabel('published stop sequence along the trip')
        ax.set_title(title, loc='left')
    axes[0].set_ylabel('schedule deviation (s)\nactual arrival - published arrival')
    axes[0].legend(title='background car demand', loc='upper left', fontsize=8,
                   title_fontsize=8)
    fig.suptitle('Schedule deviation grows along the route - and a repaired route '
                 'loses most of its time before congestion is added', x=0.01, ha='left', size=10)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('wrote', out)


def fig_time_space(runs, truth, line_trips, out, rates=(0, 3600)):
    """distance-along-route vs time, published (grey dashed) vs simulated (colored)"""
    # cumulative distance of each stop of the reference trip
    ref = line_trips[0]
    seq = truth['trips'][ref]['stops']
    dist = {seq[0]['stop_id']: 0.0}
    cum = 0.0
    for i in range(1, len(seq)):
        A = truth['stops'][seq[i - 1]['stop_id']]
        B = truth['stops'][seq[i]['stop_id']]
        cum += haversine(A['lon'], A['lat'], B['lon'], B['lat'])
        dist[seq[i]['stop_id']] = cum

    fig, axes = plt.subplots(1, len(rates), figsize=(9.6, 3.9), sharey=True)
    for ax, rt in zip(np.atleast_1d(axes), rates):
        d = os.path.join(runs, 'gtfs_rel_r%d_s1' % rt)
        by_veh = defaultdict(list)
        if os.path.exists(os.path.join(d, 'stopinfo.xml')):
            for si in ET.parse(os.path.join(d, 'stopinfo.xml')).getroot().iter('stopinfo'):
                if si.get('type') != 'bus':
                    continue
                trip = si.get('id').split('.')[0]
                if trip not in line_trips:
                    continue
                gid = si.get('busStop')[5:]
                if gid in dist:
                    by_veh[si.get('id')].append((float(si.get('started')) / 3600., dist[gid] / 1000.))
        # published timetable
        for k, t in enumerate(line_trips):
            pts = [(s['arr'] / 3600., dist[s['stop_id']] / 1000.)
                   for s in truth['trips'][t]['stops'] if s['stop_id'] in dist]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=MUTED, lw=1.1, ls='--',
                    label='published timetable' if k == 0 else None, zorder=1)
        for k, (vid, pts) in enumerate(sorted(by_veh.items())):
            pts.sort()
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=C[0], lw=2,
                    marker='o', ms=3.2, label='simulated' if k == 0 else None, zorder=2)
        ax.set_xlabel('time of day (h)')
        ax.set_title('%s' % ('free-flow (0 veh/h)' if rt == 0 else '%d veh/h background cars' % rt),
                     loc='left')
    np.atleast_1d(axes)[0].set_ylabel('distance along route (km)')
    np.atleast_1d(axes)[0].legend(loc='lower right', fontsize=8)
    fig.suptitle('PT time-space diagram, TriMet line 14 westbound (seed 1): '
                 'simulated trajectories vs the published timetable', x=0.01, ha='left', size=10)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('wrote', out)


def fig_attrition_map(attr, truth, out):
    lost = {s['stop_id'] for s in attr['systematic_loss']['lost_unique_stops']} \
        if isinstance(attr['systematic_loss']['lost_unique_stops'][0], dict) \
        else set(attr['systematic_loss']['lost_unique_stops'])
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    kx = [truth['stops'][s]['lon'] for s in truth['stops'] if s not in lost]
    ky = [truth['stops'][s]['lat'] for s in truth['stops'] if s not in lost]
    lx = [truth['stops'][s]['lon'] for s in lost]
    ly = [truth['stops'][s]['lat'] for s in lost]
    ax.scatter(kx, ky, s=18, color=C[0], label='imported (%d)' % len(kx), zorder=2,
               edgecolor='white', linewidth=0.5)
    ax.scatter(lx, ly, s=40, color=C[1], marker='X', label='lost in import (%d)' % len(lx),
               zorder=3, edgecolor='white', linewidth=0.5)
    W, S, E, N = attr_bbox(truth)
    ax.plot([W, E, E, W, W], [S, S, N, N, S], color=MUTED, lw=1, ls=':')
    ax.set_xlabel('longitude')
    ax.set_ylabel('latitude')
    ax.set_title('Import loss is concentrated in a ~200 m band at the network fringe\n'
                 'dotted box = clipping bbox used to build the GTFS subset', loc='left')
    ax.legend(loc='lower left', fontsize=8)
    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('wrote', out)


def attr_bbox(truth):
    return truth['bbox_used']


def fig_ontime_headway(csv_rows, out):
    arms = ['gtfs_rel', 'ptlines']
    labels = {'gtfs_rel': 'GTFS schedule (gtfs2pt)', 'ptlines': 'OSM headway flows (ptlines2flows)'}
    rates = sorted({int(r['rate']) for r in csv_rows})
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    panels = [('on_time_frac', 'on-time performance\n(-60 s .. +300 s vs published)', True),
              ('headway_cv_mean', 'headway coefficient of variation\nat served stops', False),
              ('ride_wait_mean', 'mean passenger wait for a ride (s)', False)]
    for ax, (metric, ylab, only_gtfs) in zip(axes, panels):
        for i, arm in enumerate(arms):
            if only_gtfs and arm != 'gtfs_rel':
                continue
            ms, hs, xs = [], [], []
            for rt in rates:
                v = [r[metric] for r in csv_rows
                     if r['arm'] == arm and int(r['rate']) == rt and r[metric] is not None]
                if not v:
                    continue
                m, h = tci(v)
                xs.append(rt)
                ms.append(m)
                hs.append(h)
            if not xs:
                continue
            ax.errorbar(xs, ms, yerr=hs, color=C[i], lw=2, marker='o', ms=5, capsize=3,
                        label=labels[arm])
        ax.set_xlabel('background car demand (veh/h)')
        ax.set_ylabel(ylab)
    axes[0].set_title('Timetable feasibility collapses with demand', loc='left')
    axes[1].set_title('Bunching', loc='left')
    axes[2].set_title('Passenger wait', loc='left')
    axes[1].legend(fontsize=8, loc='upper left')
    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('wrote', out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', required=True)
    ap.add_argument('--metrics', required=True)
    ap.add_argument('--csv', required=True)
    ap.add_argument('--truth', required=True)
    ap.add_argument('--attrition', required=True)
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    truth = json.load(open(a.truth))
    attr = json.load(open(a.attrition))
    import csv as _csv
    rows = []
    for r in _csv.DictReader(open(a.csv)):
        for k, v in list(r.items()):
            if k not in ('run', 'arm'):
                r[k] = float(v) if v not in ('', 'None') else None
        rows.append(r)
    rates = sorted({int(r['rate']) for r in rows})

    fig_dev_vs_seq(a.metrics, rates, os.path.join(a.out_dir, 'fig_deviation_vs_stop_sequence.png'))
    line14 = sorted([t for t, v in truth['trips'].items()
                     if v['route_short'] == '14' and v['direction_id'] == '0'])
    fig_time_space(a.runs, truth, line14, os.path.join(a.out_dir, 'fig_pt_time_space.png'),
                   rates=(rates[0], rates[-1]))
    fig_attrition_map(attr, truth, os.path.join(a.out_dir, 'fig_import_attrition_map.png'))
    fig_ontime_headway(rows, os.path.join(a.out_dir, 'fig_ontime_and_headway_vs_demand.png'))


if __name__ == '__main__':
    main()
