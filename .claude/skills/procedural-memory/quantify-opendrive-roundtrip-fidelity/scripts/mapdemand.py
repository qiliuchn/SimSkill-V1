#!/usr/bin/env python3
"""
mapdemand.py -- build a geometric edge-ID map between two SUMO nets whose IDs do
NOT correspond (e.g. an OpenDRIVE round trip), and rewrite a .trips.xml through it.

Why: after `netconvert --opendrive-files`, every edge/junction gets a fresh numeric
id, so "run the same demand on both networks" is impossible by id.  Two ways out:
  (A) regenerate randomTrips with the same seed on the round-trip net -- but the
      edge SET differs, so the sampled OD pairs are different journeys and only
      aggregate statistics are comparable;
  (B) match edges geometrically and TRANSLATE the trip file, so both nets get the
      *same geographic* OD pairs.
This implements (B), which is the stronger comparison, and reports the mapping
success rate so any unmapped demand is visible rather than silently dropped.

Matching reuses netdiff.py's matcher: mutual-nearest (midpoint, heading) pairing
after a robust residual-translation estimate.

Usage:
  python mapdemand.py --orig A.net.xml --rt B.net.xml --map edgemap.json
  python mapdemand.py --orig A.net.xml --rt B.net.xml --trips t.trips.xml --out t_rt.trips.xml
"""
import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdiff  # noqa: E402


def build_map(orig, rt, edge_tol=25.0, angle_tol=35.0, junc_tol=25.0):
    A, B = netdiff.Net(orig), netdiff.Net(rt)
    tx, ty = netdiff.est_translation(A.junc_xy(), B.junc_xy(), junc_tol)
    fa, fb = A.edge_feat(), B.edge_feat()
    fb = [((p[0] + tx, p[1] + ty), h) if p else (None, None) for p, h in fb]
    at = math.radians(angle_tol)

    def cost(i, k):
        pa, ha = fa[i]
        pb, hb = fb[k]
        if pa is None or pb is None:
            return None
        d = math.dist(pa, pb)
        if d > edge_tol:
            return None
        dh = abs((ha - hb + math.pi) % (2 * math.pi) - math.pi)
        if dh > at:
            return None
        return d + 5.0 * dh
    m = netdiff.greedy_match(cost, len(fa), len(fb), edge_tol + 5 * at)
    emap = {A.edges[i]["id"]: B.edges[k]["id"] for i, k, _ in m}
    return emap, {"orig_edges": len(fa), "rt_edges": len(fb), "mapped": len(m),
                  "map_rate": round(len(m) / max(1, len(fa)), 4),
                  "translation": [round(tx, 3), round(ty, 3)]}


def rewrite(trips, out, emap):
    tree = ET.parse(trips)
    root = tree.getroot()
    kept = dropped = 0
    for t in list(root):
        if t.tag not in ("trip", "vehicle", "flow"):
            continue
        f, to = t.get("from"), t.get("to")
        if f in emap and to in emap:
            t.set("from", emap[f])
            t.set("to", emap[to])
            if t.get("via"):
                v = [emap[e] for e in t.get("via").split() if e in emap]
                t.set("via", " ".join(v))
            kept += 1
        else:
            root.remove(t)
            dropped += 1
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    return {"kept": kept, "dropped": dropped}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--rt", required=True)
    ap.add_argument("--map")
    ap.add_argument("--trips")
    ap.add_argument("--out")
    ap.add_argument("--edge-tol", type=float, default=25.0)
    a = ap.parse_args()
    emap, info = build_map(a.orig, a.rt, a.edge_tol)
    if a.map:
        json.dump({"info": info, "map": emap}, open(a.map, "w"), indent=1)
    if a.trips:
        info["rewrite"] = rewrite(a.trips, a.out, emap)
    print(json.dumps(info))
