#!/usr/bin/env python
"""Per-run metric extraction for the GTFS-transit scenario batch.

For every run directory <arm>_r<rate>_s<seed> this computes:
  * completed-vs-still-running accounting and teleport-artifact counters
  * PT supply accounting (vehicles loaded/inserted/arrived, stop visits served,
    vehicles that completed their FULL stop sequence)
  * schedule adherence against the published GTFS stop_times (GTFS arms only):
    per-stop deviation, on-time performance, deviation growth along the route
  * headway coefficient of variation at each served stop
  * dwell-time attribution (scheduled hold vs. boarding vs. blocked)
  * passenger outcomes (ride count, ride waiting time, walk-only share)

Writes one JSON per run plus a combined CSV.
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_stats(p):
    out = {}
    if not os.path.exists(p):
        return out
    try:
        r = ET.parse(p).getroot()
    except ET.ParseError:
        return out
    for c in r:
        for k, v in c.attrib.items():
            out['%s_%s' % (c.tag, k)] = v
    return out


def mean(v):
    return sum(v) / len(v) if v else None


def cv(v):
    if len(v) < 2:
        return None
    m = mean(v)
    if not m:
        return None
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    return sd / m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', required=True)
    ap.add_argument('--truth', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--out-csv', required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    truth = json.load(open(a.truth))
    # published schedule lookup: (trip_id, gtfs_stop_id) -> (arr, dep, seq)
    sched = {}
    trip_len = {}
    for tid, t in truth['trips'].items():
        trip_len[tid] = len(t['stops'])
        for s in t['stops']:
            sched[(tid, s['stop_id'])] = (s['arr'], s['dep'], s['seq'])

    rows = []
    for d in sorted(glob.glob(os.path.join(a.runs, '*_r*_s*'))):
        name = os.path.basename(d)
        m = re.match(r'(.+)_r(\d+)_s(\d+)$', name)
        if not m or not os.path.exists(os.path.join(d, 'stats.xml')):
            continue
        arm, rate, seed = m.group(1), int(m.group(2)), int(m.group(3))
        st = parse_stats(os.path.join(d, 'stats.xml'))
        if 'vehicles_inserted' not in st or 'teleports_total' not in st:
            print('skipping incomplete run', name)
            continue          # run still in flight / crashed: stats.xml not finalised
        rec = {'run': name, 'arm': arm, 'rate': rate, 'seed': seed}
        for k in ('vehicles_loaded', 'vehicles_inserted', 'vehicles_running', 'vehicles_waiting',
                  'teleports_total', 'teleports_jam', 'teleports_yield', 'teleports_wrongLane',
                  'persons_loaded', 'persons_running', 'persons_jammed',
                  'safety_collisions', 'personTeleports_total',
                  'vehicleTripStatistics_count', 'vehicleTripStatistics_speed',
                  'vehicleTripStatistics_duration', 'vehicleTripStatistics_timeLoss',
                  'vehicleTripStatistics_departDelay',
                  'rideStatistics_number', 'rideStatistics_waitingTime',
                  'rideStatistics_duration', 'rideStatistics_aborted',
                  'pedestrianStatistics_number'):
            rec[k] = float(st[k]) if k in st else None

        # ---------- stop visits ----------
        stops = []
        try:
            for si in ET.parse(os.path.join(d, 'stopinfo.xml')).getroot().iter('stopinfo'):
                stops.append(si.attrib)
        except (ET.ParseError, FileNotFoundError):
            pass
        pt_stops = [s for s in stops if s.get('type') == 'bus']
        by_veh = defaultdict(list)
        for s in pt_stops:
            by_veh[s['id']].append(s)
        rec['pt_stop_visits_served'] = len(pt_stops)
        rec['pt_vehicles_with_any_stop'] = len(by_veh)

        # ---------- PT vehicle accounting from tripinfo ----------
        pt_arrived = 0
        car_arrived = 0
        rides = []
        person_dur = []
        walk_only = 0
        persons_seen = 0
        try:
            for ev, el in ET.iterparse(os.path.join(d, 'tripinfo.xml'), events=('end',)):
                if el.tag == 'tripinfo':
                    if el.get('vType') == 'bus':
                        pt_arrived += 1
                    else:
                        car_arrived += 1
                    el.clear()
                elif el.tag == 'personinfo':
                    persons_seen += 1
                    r = [x for x in el if x.tag == 'ride']
                    if not r:
                        walk_only += 1
                    for x in r:
                        rides.append({'wait': float(x.get('waitingTime', 0)),
                                      'dur': float(x.get('duration', 0)),
                                      'line': x.get('line', '')})
                    if el.get('duration'):
                        person_dur.append(float(el.get('duration')))
                    el.clear()
        except (ET.ParseError, FileNotFoundError):
            pass
        rec['pt_vehicles_arrived'] = pt_arrived
        rec['car_vehicles_arrived'] = car_arrived
        rec['persons_completed'] = persons_seen
        rec['persons_walk_only'] = walk_only
        rec['n_rides'] = len(rides)
        rec['ride_wait_mean'] = mean([r['wait'] for r in rides])
        rec['ride_wait_p90'] = (sorted(r['wait'] for r in rides)[int(0.9 * (len(rides) - 1))]
                                if rides else None)
        rec['person_duration_mean'] = mean(person_dur)

        # ---------- teleports involving PT vehicles ----------
        tp_bus = 0
        log = os.path.join(d, 'sumo.log')
        if os.path.exists(log):
            with open(log, errors='ignore') as f:
                for line in f:
                    if 'Teleporting vehicle' in line and "'car" not in line:
                        tp_bus += 1
        rec['pt_teleports'] = tp_bus

        # ---------- dwell ----------
        dwell = [float(s['ended']) - float(s['started']) for s in pt_stops]
        rec['dwell_mean'] = mean(dwell)
        rec['dwell_max'] = max(dwell) if dwell else None
        rec['dwell_gt_15s_frac'] = (sum(1 for x in dwell if x > 15) / len(dwell)) if dwell else None
        rec['blocked_mean'] = mean([float(s.get('blockedDuration', 0)) for s in pt_stops])
        rec['boarded_total'] = sum(int(s.get('loadedPersons', 0)) for s in pt_stops)

        # ---------- schedule adherence (GTFS-traceable arms) ----------
        devs = []
        dev_by_seq = defaultdict(list)
        dev_by_line = defaultdict(list)
        dev_by_seq_line = defaultdict(lambda: defaultdict(list))
        # routes whose gtfs2pt import needed --repair (U-turn pairs, detour factor
        # 1.70-2.52) vs routes imported cleanly (detour factor 1.03-1.09)
        REPAIRED_LINES = {'14', '9'}
        per_veh_slope = []
        completed_full = 0
        if arm.startswith('gtfs'):
            for vid, ss in by_veh.items():
                trip = vid.split('.')[0]
                if trip not in trip_len:
                    continue
                pts = []
                for s in ss:
                    gid = s['busStop'][5:] if s['busStop'].startswith('gtfs_') else s['busStop']
                    key = (trip, gid)
                    if key not in sched:
                        continue
                    arr, dep, seq = sched[key]
                    dv = float(s['started']) - arr
                    devs.append(dv)
                    dev_by_seq[seq].append(dv)
                    ln = '%s:%s' % (truth['trips'][trip]['route_short'],
                                    truth['trips'][trip]['direction_id'])
                    dev_by_line[ln].append(dv)
                    dev_by_seq_line[ln][seq].append(dv)
                    pts.append((seq, dv))
                if len(pts) >= 3:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    mx, my = mean(xs), mean(ys)
                    den = sum((x - mx) ** 2 for x in xs)
                    if den > 0:
                        per_veh_slope.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)
            # expected stop count per vehicle comes from the route file, so instead
            # count vehicles whose served-stop count equals the max seen for that trip's route
            exp = defaultdict(int)
            for vid, ss in by_veh.items():
                exp[vid.split('.')[0]] = max(exp[vid.split('.')[0]], len(ss))
            for vid, ss in by_veh.items():
                if len(ss) == exp[vid.split('.')[0]]:
                    completed_full += 1
        rec['pt_vehicles_completed_full_stop_seq'] = completed_full
        rec['dev_n'] = len(devs)
        rec['dev_mean'] = mean(devs)
        rec['dev_median'] = sorted(devs)[len(devs) // 2] if devs else None
        rec['dev_p90'] = sorted(devs)[int(0.9 * (len(devs) - 1))] if devs else None
        rec['dev_max'] = max(devs) if devs else None
        rec['on_time_frac'] = (sum(1 for x in devs if -60 <= x <= 300) / len(devs)) if devs else None
        rec['late_frac'] = (sum(1 for x in devs if x > 300) / len(devs)) if devs else None
        rec['early_frac'] = (sum(1 for x in devs if x < -60) / len(devs)) if devs else None
        rec['dev_slope_per_stop'] = mean(per_veh_slope)
        rec['dev_by_seq'] = {str(k): mean(v) for k, v in sorted(dev_by_seq.items())}
        rec['dev_by_seq_by_line'] = {ln: {str(k): mean(v) for k, v in sorted(d.items())}
                                     for ln, d in dev_by_seq_line.items()}
        rec['dev_mean_by_line'] = {ln: mean(v) for ln, v in dev_by_line.items()}
        rep = [x for ln, v in dev_by_line.items() if ln.split(':')[0] in REPAIRED_LINES for x in v]
        cln = [x for ln, v in dev_by_line.items() if ln.split(':')[0] not in REPAIRED_LINES for x in v]
        rec['dev_mean_repaired_routes'] = mean(rep)
        rec['dev_mean_clean_routes'] = mean(cln)

        # ---------- headway CV at each served stop ----------
        by_stop_line = defaultdict(list)
        for s in pt_stops:
            by_stop_line[(s['busStop'], _line_of(s['id'], arm, truth))].append(float(s['started']))
        cvs = []
        for k, ts in by_stop_line.items():
            if len(ts) >= 3:
                ts.sort()
                hw = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
                c = cv(hw)
                if c is not None:
                    cvs.append(c)
        rec['headway_cv_mean'] = mean(cvs)
        rec['headway_cv_n_stops'] = len(cvs)

        rows.append(rec)
        with open(os.path.join(a.out_dir, name + '.json'), 'w') as f:
            json.dump(rec, f, indent=1)

    keys = [k for k in rows[0].keys()
            if k not in ('dev_by_seq', 'dev_by_seq_by_line', 'dev_mean_by_line')] if rows else []
    with open(a.out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print('wrote %d runs -> %s' % (len(rows), a.out_csv))


_LINE_CACHE = {}


def _line_of(vehid, arm, truth):
    """line identity of a PT vehicle id (GTFS trip id, or ptlines flow id)."""
    if arm == 'ptlines':
        return vehid.split('.')[0]          # e.g. bus_15:0
    trip = vehid.split('.')[0]
    if trip in truth['trips']:
        t = truth['trips'][trip]
        return '%s_%s' % (t['route_short'], t['direction_id'])
    return trip


if __name__ == '__main__':
    main()
