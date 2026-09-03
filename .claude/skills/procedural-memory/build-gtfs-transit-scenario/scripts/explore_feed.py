#!/usr/bin/env python
"""Explore a real GTFS feed: which bus routes serve the SUMO network's geographic bbox
on a given service date, and how many trips/stops each contributes.

Usage:
  python explore_feed.py --feed <dir> --date 20260805 --bbox W,S,E,N --out <json>
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

csv.field_size_limit(10 ** 7)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            yield row


def services_on(feed, date):
    dow = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    import datetime
    d = datetime.datetime.strptime(date, '%Y%m%d').date()
    key = dow[d.weekday()]
    active = set()
    for r in load_csv(os.path.join(feed, 'calendar.txt')):
        if r[key] == '1' and r['start_date'] <= date <= r['end_date']:
            active.add(r['service_id'])
    cd = os.path.join(feed, 'calendar_dates.txt')
    if os.path.exists(cd):
        for r in load_csv(cd):
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
    ap.add_argument('--bbox', required=True, help='W,S,E,N in lon/lat')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    W, S, E, N = [float(x) for x in a.bbox.split(',')]

    active = services_on(a.feed, a.date)
    print('active services on %s: %d' % (a.date, len(active)), file=sys.stderr)

    stops_in = {}
    n_stops_total = 0
    for r in load_csv(os.path.join(a.feed, 'stops.txt')):
        n_stops_total += 1
        try:
            lon, lat = float(r['stop_lon']), float(r['stop_lat'])
        except (ValueError, KeyError):
            continue
        if W <= lon <= E and S <= lat <= N:
            stops_in[r['stop_id']] = (lon, lat, r.get('stop_name', ''))
    print('stops in feed: %d, inside bbox: %d' % (n_stops_total, len(stops_in)), file=sys.stderr)

    routes = {r['route_id']: r for r in load_csv(os.path.join(a.feed, 'routes.txt'))}
    trip_route = {}
    trip_service = {}
    trip_dir = {}
    for r in load_csv(os.path.join(a.feed, 'trips.txt')):
        trip_route[r['trip_id']] = r['route_id']
        trip_service[r['trip_id']] = r['service_id']
        trip_dir[r['trip_id']] = r.get('direction_id', '')

    # stream stop_times, count in-bbox stops per trip (only for active-service trips)
    per_trip_in = defaultdict(int)
    per_trip_total = defaultdict(int)
    per_trip_first_dep = {}
    with open(os.path.join(a.feed, 'stop_times.txt'), newline='', encoding='utf-8-sig') as f:
        rd = csv.DictReader(f)
        for row in rd:
            tid = row['trip_id']
            if trip_service.get(tid) not in active:
                continue
            per_trip_total[tid] += 1
            if row['stop_id'] in stops_in:
                per_trip_in[tid] += 1
                dep = row.get('departure_time') or row.get('arrival_time')
                if tid not in per_trip_first_dep and dep:
                    per_trip_first_dep[tid] = dep

    per_route = defaultdict(lambda: {'trips': 0, 'trips_ge3': 0, 'in_stops': set(), 'max_in': 0})
    for tid, cnt in per_trip_in.items():
        rid = trip_route[tid]
        d = per_route[rid]
        d['trips'] += 1
        if cnt >= 3:
            d['trips_ge3'] += 1
        d['max_in'] = max(d['max_in'], cnt)

    rows = []
    for rid, d in per_route.items():
        r = routes.get(rid, {})
        rows.append({
            'route_id': rid,
            'short': r.get('route_short_name', ''),
            'long': r.get('route_long_name', ''),
            'type': r.get('route_type', ''),
            'trips_touching_bbox': d['trips'],
            'trips_with_ge3_bbox_stops': d['trips_ge3'],
            'max_bbox_stops_on_a_trip': d['max_in'],
        })
    rows.sort(key=lambda x: -x['trips_with_ge3_bbox_stops'])
    out = {'date': a.date, 'bbox': a.bbox, 'n_active_services': len(active),
           'n_stops_feed': n_stops_total, 'n_stops_in_bbox': len(stops_in), 'routes': rows}
    with open(a.out, 'w') as f:
        json.dump(out, f, indent=1)
    for r in rows[:20]:
        print(r, file=sys.stderr)


if __name__ == '__main__':
    main()
