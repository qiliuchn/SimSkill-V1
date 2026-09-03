#!/usr/bin/env python3
"""Shared parsers/statistics for the speed-enforcement study.

Everything downstream reads ONLY raw SUMO output through these functions:
  e1.xml          aggregated E1 induction-loop intervals (speed, harmonicMeanSpeed)
  e1_instant.xml  per-vehicle E1 spot-speed records (instantInductionLoop)
  traj.csv.gz     per-step TraCI floating-car data (t, id, x, v, a)
  tripinfo.xml    per-vehicle trip records
  summary.xml     per-step network state (running, teleports)
  ssm.xml         SSM device conflict log
"""
import gzip
import math
import os
import xml.etree.ElementTree as ET


def xopen(path):
    """Open an XML output file, transparently handling a .gz sibling."""
    if os.path.exists(path):
        return open(path, 'rb')
    if os.path.exists(path + '.gz'):
        return gzip.open(path + '.gz', 'rb')
    raise FileNotFoundError(path)

LIMIT_MS = 13.89          # compiled posted limit
LIMIT_KMH = LIMIT_MS * 3.6


# ----------------------------------------------------------------- statistics
def mean(v):
    return sum(v) / len(v) if v else float('nan')


def sd(v):
    if len(v) < 2:
        return float('nan')
    m = mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def pctl(v, p):
    if not v:
        return float('nan')
    s = sorted(v)
    k = p * (len(s) - 1)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def harmonic(v):
    v = [x for x in v if x > 1e-6]
    return len(v) / sum(1.0 / x for x in v) if v else float('nan')


# Student-t 0.975 quantiles for small df (avoids a scipy dependency)
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
         14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
         20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000}


def t975(df):
    if df in _T975:
        return _T975[df]
    keys = sorted(_T975)
    for k in keys:
        if df < k:
            return _T975[k]
    return 1.96


def paired_ci(diffs):
    """Mean paired difference with a 95% t confidence interval and a paired t-test."""
    n = len(diffs)
    m = mean(diffs)
    s = sd(diffs)
    if n < 2 or s == 0 or math.isnan(s):
        return {'n': n, 'mean': m, 'sd': s, 'lo': m, 'hi': m, 't': float('nan'),
                'significant_95': False}
    hw = t975(n - 1) * s / math.sqrt(n)
    return {'n': n, 'mean': m, 'sd': s, 'lo': m - hw, 'hi': m + hw,
            't': m / (s / math.sqrt(n)),
            'significant_95': (m - hw) * (m + hw) > 0}


# -------------------------------------------------------------------- parsers
def parse_e1_agg(path, det_prefix=None):
    """Aggregated E1 intervals -> list of dicts."""
    out = []
    for _, el in ET.iterparse(xopen(path), events=('end',)):
        if el.tag != 'interval':
            continue
        d = el.attrib
        if det_prefix and not d['id'].startswith(det_prefix):
            el.clear(); continue
        out.append({'id': d['id'], 'begin': float(d['begin']), 'end': float(d['end']),
                    'n': int(d['nVehContrib']), 'flow': float(d['flow']),
                    'speed': float(d['speed']),
                    'hspeed': float(d['harmonicMeanSpeed']),
                    'occ': float(d['occupancy'])})
        el.clear()
    return out


def parse_e1_instant(path, pos=None):
    """Per-vehicle E1 spot speeds. Returns {detector_pos: [(vehID, speed_ms)]}.

    Only state="enter" records are used: one record per vehicle per crossing.
    """
    out = {}
    for _, el in ET.iterparse(xopen(path), events=('end',)):
        if el.tag != 'instantOut':
            continue
        d = el.attrib
        if d.get('state') != 'enter':
            el.clear(); continue
        # id form: e1i_<pos>_<lane>
        parts = d['id'].split('_')
        p = int(parts[1])
        if pos is None or p == pos:
            out.setdefault(p, []).append((d['vehID'], float(d['speed'])))
        el.clear()
    return out


def load_traj(path, eb_only=True):
    """Per-step TraCI FCD. Returns list of (t, id, x, v, a)."""
    rows = []
    with gzip.open(path, 'rt') as f:
        next(f)
        for line in f:
            t, vid, x, v, a = line.rstrip('\n').split(',')
            if eb_only and not vid.startswith('eb'):
                continue
            rows.append((float(t), vid, float(x), float(v), float(a)))
    return rows


def parse_tripinfo(path):
    out = []
    for _, el in ET.iterparse(xopen(path), events=('end',)):
        if el.tag != 'tripinfo':
            continue
        d = el.attrib
        out.append({'id': d['id'], 'depart': float(d['depart']),
                    'arrival': float(d['arrival']), 'duration': float(d['duration']),
                    'routeLength': float(d['routeLength']),
                    'timeLoss': float(d['timeLoss']),
                    'waitingTime': float(d['waitingTime']),
                    'speed': float(d.get('speedFactor', 'nan'))})
        el.clear()
    return out


def parse_summary_teleports(path):
    """summary's `teleports` is CUMULATIVE - read the LAST step, never sum."""
    last = 0
    last_running = 0
    for _, el in ET.iterparse(xopen(path), events=('end',)):
        if el.tag == 'step':
            last = int(el.attrib['teleports'])
            last_running = int(el.attrib['running'])
        el.clear()
    return last, last_running


def parse_ssm(path):
    """SSM conflicts -> list of dicts with minTTC / maxDRAC and their positions."""
    out = []
    for _, el in ET.iterparse(xopen(path), events=('end',)):
        if el.tag != 'conflict':
            continue
        rec = {'ego': el.attrib.get('ego'), 'foe': el.attrib.get('foe'),
               'begin': float(el.attrib['begin']), 'minTTC': None, 'maxDRAC': None,
               'ttc_pos': None, 'drac_pos': None, 'ttc_type': None}
        for ch in el:
            val = ch.attrib.get('value', 'NA')
            if val == 'NA':
                continue
            pos = ch.attrib.get('position', '')
            xy = None
            if pos and ',' in pos:
                xy = float(pos.split(',')[0])
            if ch.tag == 'minTTC':
                rec['minTTC'] = float(val); rec['ttc_pos'] = xy
                rec['ttc_type'] = ch.attrib.get('type')
            elif ch.tag == 'maxDRAC':
                rec['maxDRAC'] = float(val); rec['drac_pos'] = xy
        out.append(rec)
        el.clear()
    return out


# ------------------------------------------------------------- speed measures
def spot_speeds_at(instant_path, pos):
    """Per-vehicle spot speeds (m/s) recorded by the E1 loops at corridor x=pos,
    pooled over both lanes. This is the TIME-MEAN sample a real spot-speed study
    collects."""
    d = parse_e1_instant(instant_path, pos=pos)
    return [s for _, s in d.get(pos, [])]


def space_mean_over_segment(traj_rows, x0, x1, dt):
    """Edie's space-mean speed over segment [x0,x1]:
        total distance travelled / total time spent
      = arithmetic mean of speed over all (vehicle, timestep) samples,
    which is exactly the harmonic mean of individual traversal speeds when every
    vehicle traverses the whole segment. Both forms are returned for cross-check.
    """
    samples = [v for (t, vid, x, v, a) in traj_rows if x0 <= x <= x1]
    edie = mean(samples)                      # Sum(v*dt)/Sum(dt)
    # per-vehicle traversal speed over the segment
    per = {}
    for (t, vid, x, v, a) in traj_rows:
        if x0 <= x <= x1:
            r = per.setdefault(vid, [1e18, -1e18, 1e18, -1e18])
            r[0] = min(r[0], t); r[1] = max(r[1], t)
            r[2] = min(r[2], x); r[3] = max(r[3], x)
    trav = []
    for vid, (t0, t1, xa, xb) in per.items():
        if t1 > t0 and (xb - xa) > 0.8 * (x1 - x0):
            trav.append((xb - xa) / (t1 - t0))
    return {'edie_space_mean': edie,
            'harmonic_of_traversal_speeds': harmonic(trav),
            'arith_of_traversal_speeds': mean(trav),
            'n_samples': len(samples), 'n_traversals': len(trav),
            'sd_of_samples': sd(samples)}


def find_run_dirs(root):
    return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
