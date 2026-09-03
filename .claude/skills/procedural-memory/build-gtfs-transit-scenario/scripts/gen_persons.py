#!/usr/bin/env python
"""Generate intermodal person demand anchored on the imported transit corridors.

Plain randomTrips --persontrips on a 4x3 km network produces mostly walk-only
plans (origins/destinations unrelated to the transit corridors), which makes
transit wait time unmeasurable.  Here each person is sampled as an
origin/destination pair drawn near two busStops of the SAME imported line, at
least --min-stop-gap stops apart, so the trip is genuinely transit-plausible.
The same person file is reused across every scenario arm (Common Random Numbers).

Output: <person><personTrip from=.. to=.. modes="public"/></person>
SUMO resolves the intermodal plan internally at insertion time, so no duarouter
pass is needed and each arm's own transit supply is used.
"""
import argparse
import json
import math
import os
import random
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--net', required=True)
    ap.add_argument('--stops', required=True, help='busStop additional file')
    ap.add_argument('--routes', required=True, help='pt route file (for line membership)')
    ap.add_argument('--n', type=int, default=400)
    ap.add_argument('--begin', type=int, default=25200)
    ap.add_argument('--end', type=int, default=29400)
    ap.add_argument('--min-stop-gap', type=int, default=3)
    ap.add_argument('--radius', type=float, default=150.)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    net = sumolib.net.readNet(a.net)
    bs = {}
    for s in ET.parse(a.stops).getroot().iter('busStop'):
        lane = net.getLane(s.get('lane'))
        bs[s.get('id')] = lane.getEdge()

    # ordered stop sequence per pt route
    seqs = []
    for r in ET.parse(a.routes).getroot().iter('route'):
        ids = [s.get('busStop') for s in r.iter('stop') if s.get('busStop') in bs]
        if len(ids) > a.min_stop_gap:
            seqs.append(ids)
    assert seqs, 'no usable pt routes'

    def walk_edge_near(edge):
        """a pedestrian-usable edge within radius of the stop edge's midpoint"""
        shape = edge.getShape()
        x, y = shape[len(shape) // 2]
        cands = [e for e, d in net.getNeighboringEdges(x, y, a.radius)
                 if e.allows('pedestrian') and e.getID() != edge.getID()
                 and e.getFunction() == '']
        if not cands:
            return edge.getID() if edge.allows('pedestrian') else None
        return rng.choice(cands).getID()

    persons = []
    tries = 0
    while len(persons) < a.n and tries < a.n * 50:
        tries += 1
        seq = rng.choice(seqs)
        i = rng.randrange(0, len(seq) - a.min_stop_gap)
        j = rng.randrange(i + a.min_stop_gap, len(seq))
        fe = walk_edge_near(bs[seq[i]])
        te = walk_edge_near(bs[seq[j]])
        if not fe or not te or fe == te:
            continue
        depart = rng.uniform(a.begin, a.end)
        persons.append((depart, fe, te))
    persons.sort()

    with open(a.out, 'w') as f:
        f.write('<routes>\n')
        for k, (d, fe, te) in enumerate(persons):
            f.write('    <person id="p%d" depart="%.1f">\n'
                    '        <personTrip from="%s" to="%s" modes="public"/>\n'
                    '    </person>\n' % (k, d, fe, te))
        f.write('</routes>\n')
    print('wrote %d persons to %s' % (len(persons), a.out))


if __name__ == '__main__':
    main()
