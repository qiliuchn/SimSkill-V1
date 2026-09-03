#!/usr/bin/env python3
"""Verify the compiled bay network: compiled bay lengths, lane counts, and that the
exclusive left-turn lane is genuinely left-only (structural lane-isolation check
per the `design-left-turn-storage-bay-length` skill's warning that authored bay
length != compiled bay length and that lane isolation must not be assumed)."""
import sys
import xml.etree.ElementTree as ET

def load(net):
    t = ET.parse(net)
    r = t.getroot()
    edges = {}
    for e in r.findall('edge'):
        if e.get('function') == 'internal':
            continue
        lanes = [(l.get('id'), float(l.get('length'))) for l in e.findall('lane')]
        edges[e.get('id')] = dict(frm=e.get('from'), to=e.get('to'), lanes=lanes)
    conns = []
    for c in r.findall('connection'):
        if c.get('from', '').startswith(':'):
            continue
        conns.append((c.get('from'), c.get('to'), int(c.get('fromLane')),
                      int(c.get('toLane')), c.get('tl'), c.get('linkIndex'),
                      c.get('dir')))
    return edges, conns

def main():
    base_net, bay_net = sys.argv[1], sys.argv[2]
    be, bc = load(base_net)
    ye, yc = load(bay_net)
    print(f'base: {len(be)} normal edges | bay: {len(ye)} normal edges')

    print('\n--- compiled bay edges (authored length 90.0 m) ---')
    for eid, d in sorted(ye.items()):
        if eid.endswith('_bay'):
            L = d['lanes'][0][1]
            print(f'  {eid:20s} lanes={len(d["lanes"])} compiled_len={L:7.2f} m '
                  f'(authored 90.00, delta {L-90.0:+.2f})')

    print('\n--- total approach length preserved? (upstream + bay vs base edge) ---')
    ok = True
    for eid in sorted(ye):
        if not eid.endswith('_bay'):
            continue
        up = eid[:-4]
        tot = ye[up]['lanes'][0][1] + ye[eid]['lanes'][0][1]
        # base variant is split at the SAME points, so compare up+bay to up+bay
        ref = (be[up]['lanes'][0][1] + be[eid]['lanes'][0][1]) if eid in be \
            else (be[up]['lanes'][0][1] if up in be else float('nan'))
        d = tot - ref
        flag = '' if abs(d) < 1.0 else '  <-- MISMATCH'
        if abs(d) >= 1.0:
            ok = False
        print(f'  {up:16s} base={ref:7.2f}  bay-variant up+bay={tot:7.2f}  delta={d:+.2f}{flag}')
    print(f'  total-approach-length preserved: {ok}')

    print('\n--- lane isolation at bay junctions (turn direction served per lane) ---')
    bad = 0
    for eid in sorted(ye):
        if not eid.endswith('_bay'):
            continue
        nl = len(ye[eid]['lanes'])
        per_lane = {}
        for (f, t, fl, tl, tls, li, dr) in yc:
            if f == eid:
                per_lane.setdefault(fl, []).append((t, dr))
        for l in range(nl):
            movs = per_lane.get(l, [])
            dirs = sorted({d for _, d in movs})
            tag = ''
            if l == nl - 1:
                # exclusive left bay lane -> must serve ONLY left ('l' or 'L')
                if dirs != ['l'] and dirs != ['L']:
                    tag = '  <-- NOT LEFT-EXCLUSIVE'
                    bad += 1
            else:
                if 'l' in dirs or 'L' in dirs:
                    tag = '  <-- through/right lane serves a LEFT movement'
                    bad += 1
            print(f'  {eid:20s} lane{l}: {[(t, d) for t, d in movs]}{tag}')
    print(f'  lane-isolation violations: {bad}')

    print('\n--- base variant: do lefts share a through lane at J2/J3? (contrast check) ---')
    for eid in ['J1_J2', 'J3_J2', 'N2_J2', 'S2_J2', 'J2_J3', 'J4_J3']:
        if eid not in be:
            continue
        per_lane = {}
        for (f, t, fl, tl, tls, li, dr) in bc:
            if f == eid:
                per_lane.setdefault(fl, []).append(dr)
        print(f'  {eid:10s} ' + ' | '.join(f'lane{l}:{sorted(set(v))}'
                                            for l, v in sorted(per_lane.items())))

    print('\n--- signalised junctions ---')
    for net, name in ((base_net, 'base'), (bay_net, 'bay')):
        r = ET.parse(net).getroot()
        tls = [t.get('id') for t in r.findall('tlLogic')]
        phases = {t.get('id'): len(t.findall('phase')) for t in r.findall('tlLogic')}
        cyc = {t.get('id'): sum(float(p.get('duration')) for p in t.findall('phase'))
               for t in r.findall('tlLogic')}
        print(f'  {name}: tls={tls}')
        print(f'        phases={phases}')
        print(f'        default cycle={ {k: round(v) for k, v in cyc.items()} }')
    return 0 if bad == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
