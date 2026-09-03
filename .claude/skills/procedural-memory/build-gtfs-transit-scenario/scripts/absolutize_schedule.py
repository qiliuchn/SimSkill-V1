#!/usr/bin/env python
"""Rehydrate the ABSOLUTE published timetable into a gtfs2pt route file.

gtfs2pt.py writes one shared <route> per distinct stop sequence, with each
<stop until="..."> expressed RELATIVE to that route's first stop (writeRoute()
subtracts the first stop's time as an offset), and one <vehicle depart="..."/>
per GTFS trip referencing it.  SUMO interprets <stop until> as an ABSOLUTE
simulation time, so for a bus departing at 25430 s every until value (0..1200)
already lies in the past and is silently ignored: the published timetable
survives only in the vehicle's depart time, and every dwell collapses to
--duration seconds.

This script emits an equivalent route file in which each GTFS trip becomes its
own <vehicle> with an inline <route> and per-stop ABSOLUTE until values taken
from the feed's stop_times, so SUMO actually holds an early bus to schedule.
Departure times are copied unchanged from the gtfs2pt output so the two
variants stay paired (Common Random Numbers).
"""
import argparse
import json
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--routes', required=True)
    ap.add_argument('--truth', required=True)
    ap.add_argument('--duration', type=float, default=10.)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    truth = json.load(open(a.truth))
    root = ET.parse(a.routes).getroot()
    routes = {r.get('id'): (r.get('edges'),
                            [(s.get('busStop'), float(s.get('until'))) for s in r.iter('stop')])
              for r in root.iter('route')}
    vehicles = [(v.get('id'), v.get('route'), v.get('type'), float(v.get('depart')), v.get('line'))
                for v in root.iter('vehicle')]

    n_abs, n_fallback = 0, 0
    with open(a.out, 'w') as f:
        f.write('<routes>\n    <vType id="bus" vClass="bus"/>\n')
        for vid, rid, vtype, depart, line in vehicles:
            trip = vid.split('.')[0]
            edges, stops = routes[rid]
            f.write('    <vehicle id="%s" type="%s" depart="%.1f" line="%s">\n'
                    '        <route edges="%s"/>\n' % (vid, vtype or 'bus', depart, line, edges))
            sched = None
            if trip in truth['trips']:
                sched = {s['stop_id']: s for s in truth['trips'][trip]['stops']}
            for bsid, rel in stops:
                gid = bsid[5:] if bsid.startswith('gtfs_') else bsid
                if sched and gid in sched and sched[gid]['dep'] is not None:
                    until = sched[gid]['dep']
                    n_abs += 1
                else:                       # not traceable -> keep relative offset
                    until = depart + rel
                    n_fallback += 1
                f.write('        <stop busStop="%s" duration="%.0f" until="%.0f"/>\n'
                        % (bsid, a.duration, until))
            f.write('    </vehicle>\n')
        f.write('</routes>\n')
    print('wrote %s: %d vehicles, %d stops with absolute published until, %d fallback'
          % (a.out, len(vehicles), n_abs, n_fallback))


if __name__ == '__main__':
    main()
