#!/usr/bin/env python
"""Quantitative verification of a gtfs2pt import against the source GTFS feed.

Produces the import-attrition table:
  GTFS trips  -> PT vehicles in route file
  GTFS stop visits / unique stops -> busStops emitted -> stops actually reachable
plus a stop-position error distribution (busStop lane position vs published stop lat/lon),
a wrong-direction / wrong-edge diagnosis, and a route-distortion diagnosis
(U-turn pairs inserted by --repair, detour factor vs. the GTFS shape length).

Usage:
  python verify_import.py --net NET --truth truth.json --stops gtfsid_stops.add.xml \
      --routes gtfsid_pt_vehicles.rou.xml --gtfs-zip subset.zip --out out.json
"""
import argparse
import csv
import io
import json
import math
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa


def haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def lane_pos_xy(lane, pos):
    shape = lane.getShape()
    d = 0.0
    for i in range(len(shape) - 1):
        (x1, y1), (x2, y2) = shape[i], shape[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        if d + seg >= pos:
            f = (pos - d) / seg if seg > 0 else 0
            return (x1 + f * (x2 - x1), y1 + f * (y2 - y1)), (x2 - x1, y2 - y1)
        d += seg
    (x1, y1), (x2, y2) = shape[-2], shape[-1]
    return (x2, y2), (x2 - x1, y2 - y1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--truth', required=True)
    ap.add_argument('--stops', required=True)
    ap.add_argument('--routes', required=True)
    ap.add_argument('--gtfs-zip', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    net = sumolib.net.readNet(a.net)
    truth = json.load(open(a.truth))

    # ---- emitted busStops -------------------------------------------------
    stops_root = ET.parse(a.stops).getroot()
    emitted = {}
    for bs in stops_root.iter('busStop'):
        sid = bs.get('id')
        gid = sid[5:] if sid.startswith('gtfs_') else sid
        lane = net.getLane(bs.get('lane'))
        p = (float(bs.get('startPos')) + float(bs.get('endPos'))) / 2.0
        xy, dvec = lane_pos_xy(lane, p)
        lon, lat = net.convertXY2LonLat(*xy)
        emitted[gid] = {'busStop': sid, 'lane': bs.get('lane'),
                        'edge': lane.getEdge().getID(), 'pos': p,
                        'lon': lon, 'lat': lat, 'dir': dvec,
                        'name': bs.get('name', ''),
                        'n_access': len(list(bs.iter('access')))}

    # ---- routes / vehicles ------------------------------------------------
    rt_root = ET.parse(a.routes).getroot()
    routes = {}
    for r in rt_root.iter('route'):
        routes[r.get('id')] = {
            'edges': r.get('edges').split(),
            'stops': [(s.get('busStop'), float(s.get('until')), float(s.get('duration')))
                      for s in r.iter('stop')]}
    vehicles = []
    for v in rt_root.iter('vehicle'):
        vehicles.append({'id': v.get('id'), 'route': v.get('route'),
                         'depart': float(v.get('depart')), 'line': v.get('line')})

    # ---- GTFS shape lengths ----------------------------------------------
    z = zipfile.ZipFile(a.gtfs_zip)
    shapes = {}
    for row in csv.DictReader(io.TextIOWrapper(z.open('shapes.txt'), 'utf-8-sig')):
        shapes.setdefault(row['shape_id'], []).append(
            (int(row['shape_pt_sequence']), float(row['shape_pt_lon']), float(row['shape_pt_lat'])))

    # ---- per-trip attrition ----------------------------------------------
    per_trip = {}
    total_visits = 0
    total_kept = 0
    lost_stops = []
    for tid, t in truth['trips'].items():
        seq = [s['stop_id'] for s in t['stops']]
        total_visits += len(seq)
        rid = tid if tid in routes else None
        # vehicles referencing this trip id
        vids = [v for v in vehicles if v['id'].split('.')[0] == tid]
        if vids and rid is None:
            rid = vids[0]['route']
        kept = []
        if rid and rid in routes:
            got = {s[0][5:] if s[0].startswith('gtfs_') else s[0] for s in routes[rid]['stops']}
            kept = [s for s in seq if s in got]
        total_kept += len(kept)
        missing = [s for s in seq if s not in kept]
        for m in missing:
            lost_stops.append({'trip': tid, 'route_short': t['route_short'], 'stop_id': m,
                               'lon': truth['stops'][m]['lon'], 'lat': truth['stops'][m]['lat'],
                               'name': truth['stops'][m]['name']})
        per_trip[tid] = {'route_short': t['route_short'], 'dir': t['direction_id'],
                         'gtfs_stops': len(seq), 'kept_stops': len(kept),
                         'mapped_route': rid, 'n_vehicles': len(vids),
                         'missing': missing}

    # ---- position error ---------------------------------------------------
    pos_err = []
    dir_flags = []
    for gid, e in emitted.items():
        if gid not in truth['stops']:
            continue
        g = truth['stops'][gid]
        d = haversine(g['lon'], g['lat'], e['lon'], e['lat'])
        pos_err.append({'stop_id': gid, 'err_m': d, 'name': g['name'],
                        'edge': e['edge'], 'lane': e['lane']})
    pos_err.sort(key=lambda x: -x['err_m'])

    # ---- direction check: bearing of stop lane vs. bearing implied by the
    #      published stop sequence (prev->next stop) ------------------------
    for tid, t in truth['trips'].items():
        seq = t['stops']
        for i, s in enumerate(seq):
            gid = s['stop_id']
            if gid not in emitted:
                continue
            prev = seq[i - 1] if i > 0 else None
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            if prev is None and nxt is None:
                continue
            p0 = truth['stops'][prev['stop_id']] if prev else truth['stops'][gid]
            p1 = truth['stops'][nxt['stop_id']] if nxt else truth['stops'][gid]
            # convert to net XY for a metric bearing
            x0, y0 = net.convertLonLat2XY(p0['lon'], p0['lat'])
            x1, y1 = net.convertLonLat2XY(p1['lon'], p1['lat'])
            tv = (x1 - x0, y1 - y0)
            lv = emitted[gid]['dir']
            n1 = math.hypot(*tv)
            n2 = math.hypot(*lv)
            if n1 < 1 or n2 < 1e-6:
                continue
            cos = (tv[0] * lv[0] + tv[1] * lv[1]) / (n1 * n2)
            if cos < 0:
                dir_flags.append({'trip': tid, 'stop_id': gid, 'cos': cos,
                                  'name': emitted[gid]['name'], 'lane': emitted[gid]['lane']})
            break_ = None
    # de-duplicate direction flags by stop
    seen = set()
    dir_uniq = []
    for f in dir_flags:
        if f['stop_id'] in seen:
            continue
        seen.add(f['stop_id'])
        dir_uniq.append(f)

    # ---- route distortion --------------------------------------------------
    route_diag = {}
    for rid, r in routes.items():
        edges = r['edges']
        uturns = sum(1 for i in range(len(edges) - 1)
                     if edges[i + 1] == ('-' + edges[i]) or edges[i] == ('-' + edges[i + 1]))
        length = 0.0
        missing_edges = 0
        internal_len = 0.0
        for i, e in enumerate(edges):
            try:
                length += net.getEdge(e).getLength()
            except KeyError:
                missing_edges += 1
                continue
            # add the junction-internal connection length to the next edge:
            # a <route edges=...> list omits internal edges, so summing only the
            # named edges systematically UNDER-estimates the driven distance.
            if i + 1 < len(edges):
                try:
                    conns = net.getEdge(e).getConnections(net.getEdge(edges[i + 1]))
                except KeyError:
                    conns = []
                best = 0.0
                for c in conns:
                    vl = c.getViaLaneID()
                    if vl:
                        try:
                            best = max(best, net.getLane(vl).getLength())
                        except KeyError:
                            pass
                if best == 0.0:
                    # sumolib.readNet() omits internal edges by default, so fall back
                    # to the straight-line gap between the two edge shapes
                    try:
                        p0 = net.getEdge(e).getShape()[-1]
                        p1 = net.getEdge(edges[i + 1]).getShape()[0]
                        best = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                    except (KeyError, IndexError):
                        best = 0.0
                internal_len += best
        length += internal_len
        shp_len = None
        tid = rid
        if tid in truth['trips']:
            sid = truth['trips'][tid]['shape_id']
            if sid in shapes:
                pts = sorted(shapes[sid])
                # length only over the clipped stop span (approx: between first/last stop)
                shp_len = sum(haversine(pts[i][1], pts[i][2], pts[i + 1][1], pts[i + 1][2])
                              for i in range(len(pts) - 1))
        # straight-line span of retained stops as a scale-free reference
        got = [s[0][5:] if s[0].startswith('gtfs_') else s[0] for s in r['stops']]
        span = 0.0
        for i in range(len(got) - 1):
            if got[i] in truth['stops'] and got[i + 1] in truth['stops']:
                A, B = truth['stops'][got[i]], truth['stops'][got[i + 1]]
                span += haversine(A['lon'], A['lat'], B['lon'], B['lat'])
        route_diag[rid] = {'n_edges': len(edges), 'edges_not_in_net': missing_edges,
                           'internal_len_m': internal_len,
                           'uturn_pairs': uturns,
                           'route_len_m': length, 'stop_chain_len_m': span,
                           'full_shape_len_m': shp_len,
                           'detour_factor': (length / span) if span > 0 else None,
                           'n_stops': len(r['stops'])}

    # ---- is the loss systematic?  compare lost vs kept stops on
    #      (a) distance to the network fringe, (b) distance to the nearest
    #      bus-permitting lane ------------------------------------------------
    (nx0, ny0), (nx1, ny1) = net.getBBoxXY()

    def fringe_dist(lon, lat):
        x, y = net.convertLonLat2XY(lon, lat)
        return min(x - nx0, nx1 - x, y - ny0, ny1 - y)

    def nearest_bus_lane(lon, lat, r=200):
        x, y = net.convertLonLat2XY(lon, lat)
        best = None
        for e, d in net.getNeighboringEdges(x, y, r):
            if e.allows('bus'):
                if best is None or d < best[1]:
                    best = (e.getID(), d)
        return best

    lost_ids = {s['stop_id'] for s in lost_stops}
    lost_uniq = sorted(lost_ids - set(emitted.keys()))
    geom = {'lost': [], 'kept': []}
    for sid, g in truth['stops'].items():
        rec = {'stop_id': sid, 'name': g['name'], 'fringe_dist_m': fringe_dist(g['lon'], g['lat'])}
        nb = nearest_bus_lane(g['lon'], g['lat'])
        rec['nearest_bus_edge'] = nb[0] if nb else None
        rec['nearest_bus_dist_m'] = nb[1] if nb else None
        geom['lost' if sid in lost_uniq else 'kept'].append(rec)

    def summ(rows, key):
        v = sorted(r[key] for r in rows if r[key] is not None)
        if not v:
            return None
        return {'n': len(v), 'mean': sum(v) / len(v), 'median': v[len(v) // 2],
                'min': v[0], 'max': v[-1]}

    systematic = {
        'lost_unique_stops': lost_uniq,
        'fringe_dist_lost': summ(geom['lost'], 'fringe_dist_m'),
        'fringe_dist_kept': summ(geom['kept'], 'fringe_dist_m'),
        'nearest_bus_lane_dist_lost': summ(geom['lost'], 'nearest_bus_dist_m'),
        'nearest_bus_lane_dist_kept': summ(geom['kept'], 'nearest_bus_dist_m'),
        'lost_detail': geom['lost'],
        'lost_with_no_bus_lane_within_200m': sum(1 for r in geom['lost'] if r['nearest_bus_dist_m'] is None),
    }

    errs = [p['err_m'] for p in pos_err]
    errs_sorted = sorted(errs)

    def q(p):
        if not errs_sorted:
            return None
        k = min(len(errs_sorted) - 1, int(p * (len(errs_sorted) - 1)))
        return errs_sorted[k]

    out = {
        'counts': {
            'gtfs_trips': len(truth['trips']),
            'gtfs_stop_visits': total_visits,
            'gtfs_unique_stops': len(truth['stops']),
            'pt_vehicles_in_route_file': len(vehicles),
            'distinct_routes_in_route_file': len(routes),
            'busstops_emitted': len(emitted),
            'stop_visits_kept': total_kept,
            'stop_visits_lost': total_visits - total_kept,
            'unique_stops_lost': len(truth['stops']) - len(emitted),
            'busstops_with_access_element': sum(1 for e in emitted.values() if e['n_access']),
        },
        'attrition_rates': {
            'trip_loss_frac': 1 - len(vehicles) / len(truth['trips']),
            'stop_visit_loss_frac': (total_visits - total_kept) / total_visits,
            'unique_stop_loss_frac': (len(truth['stops']) - len(emitted)) / len(truth['stops']),
        },
        'position_error_m': {
            'n': len(errs), 'mean': sum(errs) / len(errs) if errs else None,
            'median': q(0.5), 'p90': q(0.9), 'p95': q(0.95), 'max': max(errs) if errs else None,
            'frac_gt_25m': sum(1 for e in errs if e > 25) / len(errs) if errs else None,
            'frac_gt_50m': sum(1 for e in errs if e > 50) / len(errs) if errs else None,
            'worst': pos_err[:15],
        },
        'wrong_direction_stops': dir_uniq,
        'systematic_loss': systematic,
        'route_diagnostics': route_diag,
        'per_trip': per_trip,
        'lost_stops': lost_stops,
    }
    with open(a.out, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out['counts'], indent=1))
    print(json.dumps(out['attrition_rates'], indent=1))
    print(json.dumps({k: v for k, v in out['position_error_m'].items() if k != 'worst'}, indent=1))
    print('wrong-direction stops:', len(dir_uniq))
    print('systematic:', json.dumps({k: v for k, v in systematic.items() if k != 'lost_detail'}, indent=1))
    for rid, d in route_diag.items():
        print(rid, d)


if __name__ == '__main__':
    main()
