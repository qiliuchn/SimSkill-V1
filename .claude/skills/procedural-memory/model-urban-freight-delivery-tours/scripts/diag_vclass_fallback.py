#!/usr/bin/env python3
"""
Diagnostic for the vClass-fallback bug in gen_freight.plan_tours (attempt-2 fix).

For every E2 network variant, classify every delivery address under
  (a) the OLD logic  -- pick vc = truck if the address edge permits truck, else
                        delivery; if THAT vc has no depot->addr or addr->depot path,
                        mark the address unservable and never retry;
  (b) the NEW logic  -- try each vClass the address edge permits, in preference
                        order (truck, delivery), and accept the first one with a
                        finite ROUND TRIP depot->addr->depot at the SAME depot.

Prints the addresses that OLD calls unservable but NEW rescues, and independently
re-verifies each rescue with sumolib round-trip routing.
"""
import os, sys, json, math
from common import *   # noqa
import sumolib
import gen_freight as gf

NETS = ["d_%s_%d" % (f, c) for f in ("strict", "hgv") for c in (0, 25, 50, 75, 100)]
ADDRS = json.load(open(os.path.join(DEMAND, "addresses.json")))


def roundtrip(net, e, vc):
    """(best_depot_or_None, any_inbound_path)."""
    best, bestc, any_in = None, float("inf"), False
    for k, de in enumerate(gf.DEPOT_EDGES):
        p1, c1 = net.getShortestPath(net.getEdge(de), e, vClass=vc)
        if p1 is None:
            continue
        any_in = True
        p2, c2 = net.getShortestPath(e, net.getEdge(de), vClass=vc)
        if p2 is None:
            continue
        if c1 < bestc:
            best, bestc = k, c1
    return best, any_in


def old_logic(net, a):
    e = net.getEdge(a["edge"])
    vc = "truck" if e.allows("truck") else ("delivery" if e.allows("delivery") else None)
    if vc is None:
        return None, "banned"
    din, dout = [], []
    for de in gf.DEPOT_EDGES:
        p, c = net.getShortestPath(net.getEdge(de), e, vClass=vc)
        din.append(c if p is not None else float("inf"))
        p2, c2 = net.getShortestPath(e, net.getEdge(de), vClass=vc)
        dout.append(c2 if p2 is not None else float("inf"))
    if not math.isfinite(min(din)):
        return None, "no-path"
    if not math.isfinite(min(dout)):
        return None, "trap"
    return vc, None


def new_logic(net, a):
    e = net.getEdge(a["edge"])
    cands = [vc for vc in ("truck", "delivery") if e.allows(vc)]
    if not cands:
        return None, "banned", None
    any_in = False
    for vc in cands:
        k, ai = roundtrip(net, e, vc)
        any_in = any_in or ai
        if k is not None:
            return vc, None, k
    return None, ("trap" if any_in else "no-path"), None


def main():
    summary = {}
    for tag in NETS:
        net = sumolib.net.readNet(os.path.join(NET, "%s.net.xml" % tag))
        old_fail, new_fail, rescued = {}, {}, []
        for a in ADDRS:
            vo, fo = old_logic(net, a)
            vn, fn, k = new_logic(net, a)
            if vo is None:
                old_fail[a["id"]] = fo
            if vn is None:
                new_fail[a["id"]] = fn
            elif vo is None:
                rescued.append((a["id"], a["edge"], fo, vn, k, a["parcels"]))
        # independent re-verification of every rescue
        bad = []
        for aid, edge, fo, vn, k, par in rescued:
            e = net.getEdge(edge)
            de = net.getEdge(gf.DEPOT_EDGES[k])
            p1, _ = net.getShortestPath(de, e, vClass=vn)
            p2, _ = net.getShortestPath(e, de, vClass=vn)
            if p1 is None or p2 is None:
                bad.append(aid)
        summary[tag] = dict(
            old_unservable=len(old_fail), new_unservable=len(new_fail),
            rescued=len(rescued), rescued_parcels=sum(r[5] for r in rescued),
            rescue_verify_failures=bad,
            old_counts={k2: sum(1 for v in old_fail.values() if v == k2)
                        for k2 in ("banned", "no-path", "trap")},
            new_counts={k2: sum(1 for v in new_fail.values() if v == k2)
                        for k2 in ("banned", "no-path", "trap")},
            rescued_ids=[r[0] for r in rescued])
        s = summary[tag]
        print("%-14s old_unserv=%3d %s  ->  new_unserv=%3d %s   rescued=%2d (%d parcels) "
              "verify_fail=%d"
              % (tag, s["old_unservable"], s["old_counts"], s["new_unservable"],
                 s["new_counts"], s["rescued"], s["rescued_parcels"],
                 len(s["rescue_verify_failures"])))
    tot = sorted({i for t in ("d_hgv_25", "d_hgv_50", "d_hgv_75")
                  for i in summary[t]["rescued_ids"]})
    print("\nDISTINCT addresses rescued across hgv 25/50/75: %d" % len(tot))
    print("  union of per-arm rescues (with multiplicity): %d"
          % sum(summary[t]["rescued"] for t in ("d_hgv_25", "d_hgv_50", "d_hgv_75")))
    json.dump(summary, open(os.path.join(TAB, "vclass_fallback_diagnostic.json"), "w"), indent=1)
    print("wrote", os.path.join(TAB, "vclass_fallback_diagnostic.json"))


if __name__ == "__main__":
    main()
