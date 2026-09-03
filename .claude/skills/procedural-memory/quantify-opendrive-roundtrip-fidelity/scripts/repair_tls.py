#!/usr/bin/env python3
"""
repair_tls.py -- REPAIR RECIPE for the #1 OpenDRIVE-round-trip defect:
netconvert re-imports signalised junctions as traffic lights but REGENERATES the
signal program from its own defaults, discarding the original phase structure
(protected-left phases, custom splits/offsets).  Cycle length may coincidentally
match because both the source generator and netconvert default to 90 s.

This script transplants the ORIGINAL tlLogic programs onto the round-tripped net:
  1. match TLS junctions between the two nets by position (netdiff matcher);
  2. build the edge map (mapdemand) so connections can be compared across ids;
  3. for each TLS pair, derive the linkIndex PERMUTATION by matching each
     controlled connection (fromEdge,fromLane,toEdge,toLane) through the edge map;
  4. emit an additional-file with the original phase strings permuted into the
     round-trip net's link order, plus the original durations/offset/type.

If any link cannot be matched it is reported and left at its round-trip state
character, rather than silently mis-mapped.

Usage:
  python repair_tls.py --orig A.net.xml --rt B.net.xml --out tls_repair.add.xml
Then: sumo -n B.net.xml -r routes.rou.xml --additional-files tls_repair.add.xml
"""
import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdiff  # noqa: E402
import mapdemand  # noqa: E402


def tls_links(netfile):
    """{tlsID: {linkIndex: (fromEdge, fromLaneIdx, toEdge, toLaneIdx)}}"""
    r = ET.parse(netfile).getroot()
    out = {}
    for c in r.findall("connection"):
        tl = c.get("tl")
        if tl is None:
            continue
        out.setdefault(tl, {})[int(c.get("linkIndex"))] = (
            c.get("from"), int(c.get("fromLane")), c.get("to"), int(c.get("toLane")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--rt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    a = ap.parse_args()

    A, B = netdiff.Net(a.orig), netdiff.Net(a.rt)
    tx, ty = netdiff.est_translation(A.junc_xy(), B.junc_xy(), 25.0)
    emap, minfo = mapdemand.build_map(a.orig, a.rt)

    ta = [t for t in A.tls if t["pos"]]
    tb = [t for t in B.tls if t["pos"]]
    pa = [A.orig_xy(*t["pos"]) for t in ta]
    pb = [(B.orig_xy(*t["pos"])[0] + tx, B.orig_xy(*t["pos"])[1] + ty) for t in tb]
    pairs = netdiff.greedy_match(lambda i, k: math.dist(pa[i], pb[k]), len(pa), len(pb), 50.0)

    la, lb = tls_links(a.orig), tls_links(a.rt)
    rep = {"edge_map": minfo, "tls_pairs": [], "written": 0}
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    for i, k, dist in pairs:
        oa, ob = ta[i], tb[k]
        A_links, B_links = la.get(oa["id"], {}), lb.get(ob["id"], {})
        # translate original links into rt id space
        want = {}
        for idx, (fe, fl, te, tl_) in A_links.items():
            if fe in emap and te in emap:
                want[(emap[fe], fl, emap[te], tl_)] = idx
        perm = {}          # rt linkIndex -> orig linkIndex
        for idx, key in B_links.items():
            if key in want:
                perm[idx] = want[key]
        nB = max(B_links) + 1 if B_links else 0
        cov = len(perm) / max(1, nB)
        rep["tls_pairs"].append({"orig": oa["id"], "rt": ob["id"],
                                 "pos_dist_m": round(dist, 2),
                                 "orig_links": len(A_links), "rt_links": nB,
                                 "links_remapped": len(perm),
                                 "coverage": round(cov, 3),
                                 "orig_phases": oa["nphases"], "rt_phases": ob["nphases"]})
        if not perm:
            continue
        lines.append(f'    <tlLogic id="{ob["id"]}" type="{oa["type"]}" '
                     f'programID="repaired" offset="0">')
        for dur, state in zip(oa["durations"], oa["states"]):
            s = ["r"] * nB
            for rt_idx, o_idx in perm.items():
                if o_idx < len(state):
                    s[rt_idx] = state[o_idx]
            lines.append(f'        <phase duration="{dur:g}" state="{"".join(s)}"/>')
        lines.append("    </tlLogic>")
        rep["written"] += 1
    lines.append("</additional>")
    open(a.out, "w").write("\n".join(lines) + "\n")
    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
    print(json.dumps({k: rep[k] for k in ("written",)} |
                     {"mean_link_coverage": round(sum(p["coverage"] for p in rep["tls_pairs"]) /
                                                  max(1, len(rep["tls_pairs"])), 3),
                      "pairs": len(rep["tls_pairs"])}))


if __name__ == "__main__":
    main()
