#!/usr/bin/env python3
"""QA check: signalized approaches where a LEFT turn shares its lane with a THROUGH
movement even though the approach has >=2 lanes -- i.e. netconvert's connection
guessing produced no exclusive left-turn lane. Restricted to edges inside the
largest strongly-connected component (elsewhere it is cosmetic: no routable traffic).
"""
import sys, os, collections, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patchlib as P

net = sys.argv[1]
r, edges, junc, conns, tls = P.load_net(net)
cn = P.connectivity(net)
core = set(cn["main_edges"])

by_edge = collections.defaultdict(list)
for c in conns:
    by_edge[c.get("from")].append(c)

rows = []
for eid, cs in by_edge.items():
    if eid not in core:
        continue
    e = edges[eid]
    nl = len(e.findall("lane"))
    if nl < 2:
        continue
    lanes = collections.defaultdict(set)
    tlctl = collections.defaultdict(set)
    for c in cs:
        lanes[int(c.get("fromLane"))].add(c.get("dir"))
        if c.get("tl"):
            tlctl[int(c.get("fromLane"))].add(c.get("tl"))
    # leftmost lane index = nl-1
    shared = [(l, sorted(d)) for l, d in lanes.items()
              if ("l" in d or "L" in d) and ("s" in d)]
    if not shared:
        continue
    tl = sorted(set().union(*tlctl.values())) if tlctl else []
    rows.append(dict(edge=eid, name=e.get("name"), nlanes=nl,
                     length=round(float(e.findall("lane")[0].get("length")), 1),
                     speed=round(float(e.findall("lane")[0].get("speed")), 2),
                     shared_lanes=shared, tl=tl,
                     to_junction=e.get("to"),
                     dests={c.get("to"): c.get("dir") for c in cs}))

rows.sort(key=lambda x: (-len(x["tl"]), -x["nlanes"], -x["length"]))
print(f"{len(rows)} core signalized/priority approaches with a through+left shared lane\n")
for x in rows[:12]:
    print(f"  {x['edge']:<18} {str(x['name'])[:22]:<24} lanes={x['nlanes']} len={x['length']:>6} "
          f"v={x['speed']:>5} tl={x['tl']} shared={x['shared_lanes']}")
    print(f"       dests: {x['dests']}")
json.dump(rows, open(sys.argv[2], "w"), indent=1) if len(sys.argv) > 2 else None
