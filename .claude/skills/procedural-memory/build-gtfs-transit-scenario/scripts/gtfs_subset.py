#!/usr/bin/env python
"""Build a schema-valid GTFS subset zip from a real published feed.

Subsetting is purely a SELECTION of real published records (no values are invented):
 - keep only the chosen route_ids
 - keep only trips whose service_id is active on --date
 - clip each trip's stop sequence to its maximal contiguous run of stops inside the
   network bbox (shrunk by --inset degrees so buses aren't clipped exactly at the fringe)
 - keep only trips whose first retained departure lies in [--start,--end)
 - stop_sequence is renumbered 1..n (GTFS only requires it to be increasing);
   all arrival_time / departure_time / stop lat-lon values are the published ones.

Writes the subset zip plus a JSON ground-truth file of the published timetable.

Usage:
  python gtfs_subset.py --feed DIR --date 20260805 --routes 14,15,9,75 \
      --bbox W,S,E,N --start 25200 --end 28800 --out-zip x.zip --out-truth truth.json
"""
import argparse
import csv
import datetime
import json
import os
import sys
import zipfile
from collections import defaultdict

csv.field_size_limit(10 ** 7)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        rd = csv.DictReader(f)
        fields = rd.fieldnames
        rows = list(rd)
    return fields, rows


def hhmmss(s):
    if not s:
        return None
    p = s.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])


def services_on(feed, date):
    dow = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    d = datetime.datetime.strptime(date, '%Y%m%d').date()
    key = dow[d.weekday()]
    active = set()
    _, cal = load_csv(os.path.join(feed, 'calendar.txt'))
    for r in cal:
        if r[key] == '1' and r['start_date'] <= date <= r['end_date']:
            active.add(r['service_id'])
    p = os.path.join(feed, 'calendar_dates.txt')
    if os.path.exists(p):
        _, cd = load_csv(p)
        for r in cd:
            if r['date'] == date:
                if r['exception_type'] == '1':
                    active.add(r['service_id'])
                elif r['exception_type'] == '2':
                    active.discard(r['service_id'])
    return active


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', required=True)
    ap.add_argument('--date', required=True)
    ap.add_argument('--routes', required=True)
    ap.add_argument('--bbox', required=True)
    ap.add_argument('--inset', type=float, default=0.0012)
    ap.add_argument('--start', type=int, default=25200)
    ap.add_argument('--end', type=int, default=28800)
    ap.add_argument('--min-stops', type=int, default=4)
    ap.add_argument('--out-zip', required=True)
    ap.add_argument('--out-truth', required=True)
    a = ap.parse_args()

    W, S, E, N = [float(x) for x in a.bbox.split(',')]
    W += a.inset
    E -= a.inset
    S += a.inset
    N -= a.inset
    keep_routes = set(a.routes.split(','))
    active = services_on(a.feed, a.date)

    stop_f, stop_rows = load_csv(os.path.join(a.feed, 'stops.txt'))
    stops = {r['stop_id']: r for r in stop_rows}
    inside = {sid for sid, r in stops.items()
              if r['stop_lon'] and W <= float(r['stop_lon']) <= E and S <= float(r['stop_lat']) <= N}

    route_f, route_rows = load_csv(os.path.join(a.feed, 'routes.txt'))
    routes = {r['route_id']: r for r in route_rows if r['route_id'] in keep_routes}
    assert routes, 'no matching routes'

    trip_f, trip_rows = load_csv(os.path.join(a.feed, 'trips.txt'))
    trips = {r['trip_id']: r for r in trip_rows
             if r['route_id'] in keep_routes and r['service_id'] in active}
    print('candidate trips (route+service filter): %d' % len(trips), file=sys.stderr)

    # stream stop_times for candidate trips
    st_by_trip = defaultdict(list)
    with open(os.path.join(a.feed, 'stop_times.txt'), newline='', encoding='utf-8-sig') as f:
        rd = csv.DictReader(f)
        st_fields = rd.fieldnames
        for row in rd:
            if row['trip_id'] in trips:
                st_by_trip[row['trip_id']].append(row)

    kept_st = {}
    stats = {'candidate_trips': len(trips), 'dropped_no_contiguous_run': 0,
             'dropped_too_few_stops': 0, 'dropped_outside_time_window': 0}
    for tid, rows in st_by_trip.items():
        rows.sort(key=lambda r: int(r['stop_sequence']))
        # maximal contiguous run of in-bbox stops
        best, cur = [], []
        for r in rows:
            if r['stop_id'] in inside:
                cur.append(r)
            else:
                if len(cur) > len(best):
                    best = cur
                cur = []
        if len(cur) > len(best):
            best = cur
        if not best:
            stats['dropped_no_contiguous_run'] += 1
            continue
        if len(best) < a.min_stops:
            stats['dropped_too_few_stops'] += 1
            continue
        t0 = hhmmss(best[0].get('departure_time') or best[0].get('arrival_time'))
        if t0 is None or not (a.start <= t0 < a.end):
            stats['dropped_outside_time_window'] += 1
            continue
        kept_st[tid] = best

    print('kept trips: %d  %s' % (len(kept_st), stats), file=sys.stderr)

    # write subset
    used_stops = sorted({r['stop_id'] for rows in kept_st.values() for r in rows})
    used_shapes = {trips[t].get('shape_id') for t in kept_st if trips[t].get('shape_id')}
    used_agencies = {routes[trips[t]['route_id']].get('agency_id') for t in kept_st}

    def wr(z, name, fields, rows):
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
        z.writestr(name, buf.getvalue())

    ag_f, ag_rows = load_csv(os.path.join(a.feed, 'agency.txt'))
    cal_f, cal_rows = load_csv(os.path.join(a.feed, 'calendar.txt'))
    cd_f, cd_rows = load_csv(os.path.join(a.feed, 'calendar_dates.txt'))
    sh_f, sh_rows = load_csv(os.path.join(a.feed, 'shapes.txt'))

    used_services = {trips[t]['service_id'] for t in kept_st}
    out_st = []
    for tid, rows in kept_st.items():
        for i, r in enumerate(rows):
            r = dict(r)
            r['stop_sequence'] = str(i + 1)
            out_st.append(r)
    out_st.sort(key=lambda r: (r['trip_id'], int(r['stop_sequence'])))

    with zipfile.ZipFile(a.out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        wr(z, 'agency.txt', ag_f, [r for r in ag_rows if r.get('agency_id') in used_agencies])
        wr(z, 'stops.txt', stop_f, [stops[s] for s in used_stops])
        wr(z, 'routes.txt', route_f, [routes[r] for r in sorted(routes)])
        wr(z, 'trips.txt', trip_f, [trips[t] for t in sorted(kept_st)])
        wr(z, 'stop_times.txt', st_fields, out_st)
        wr(z, 'calendar.txt', cal_f, [r for r in cal_rows if r['service_id'] in used_services])
        wr(z, 'calendar_dates.txt', cd_f, [r for r in cd_rows if r['service_id'] in used_services])
        wr(z, 'shapes.txt', sh_f, [r for r in sh_rows if r['shape_id'] in used_shapes])

    truth = {'date': a.date, 'bbox_used': [W, S, E, N], 'window': [a.start, a.end],
             'subset_stats': stats, 'n_trips': len(kept_st), 'n_stops': len(used_stops),
             'routes': {rid: {'short': routes[rid].get('route_short_name'),
                              'long': routes[rid].get('route_long_name'),
                              'type': routes[rid].get('route_type')} for rid in routes},
             'stops': {s: {'lon': float(stops[s]['stop_lon']), 'lat': float(stops[s]['stop_lat']),
                           'name': stops[s].get('stop_name', '')} for s in used_stops},
             'trips': {}}
    for tid, rows in kept_st.items():
        truth['trips'][tid] = {
            'route_id': trips[tid]['route_id'],
            'route_short': routes[trips[tid]['route_id']].get('route_short_name'),
            'direction_id': trips[tid].get('direction_id', ''),
            'service_id': trips[tid]['service_id'],
            'shape_id': trips[tid].get('shape_id', ''),
            'stops': [{'seq': i + 1, 'stop_id': r['stop_id'],
                       'arr': hhmmss(r.get('arrival_time') or r.get('departure_time')),
                       'dep': hhmmss(r.get('departure_time') or r.get('arrival_time'))}
                      for i, r in enumerate(rows)]}
    with open(a.out_truth, 'w') as f:
        json.dump(truth, f, indent=1)
    print('wrote %s (%d trips, %d stops)' % (a.out_zip, len(kept_st), len(used_stops)), file=sys.stderr)


if __name__ == '__main__':
    main()
