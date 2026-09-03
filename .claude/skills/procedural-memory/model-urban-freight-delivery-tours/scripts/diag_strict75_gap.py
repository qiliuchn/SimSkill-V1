#!/usr/bin/env python3
"""
Reconcile verify_net.py's `addr_no_return_delivery` against gen_freight.py's
`fail_trap` count, for every net variant (the critic flagged strict_75: 13 vs 7).

The two quantities are NOT the same predicate:

  verify_net  addr_no_return_delivery
      = # addresses whose edge ALLOWS delivery and that have NO delivery return
        path to EITHER depot.  It says nothing about whether the address is
        reachable INBOUND in the first place.

  gen_freight fail_trap
      = # addresses that are reachable inbound from at least one depot but have
        no legal way back out.  `no-path` is tested FIRST and wins, so an address
        that is both unreachable inbound AND unable to return is counted as
        `no-path`, never as `trap`.

So the expected identity is
      addr_no_return_delivery == fail_trap + (# no-path addresses that also have
                                              no delivery return path)
"""
import os, sys, json, math
from common import *   # noqa
import sumolib
import gen_freight as gf

NETS = ["d_%s_%d" % (f, c) for f in ("strict", "hgv") for c in (0, 25, 50, 75, 100)]
ADDRS = json.load(open(os.path.join(DEMAND, "addresses.json")))

print("%-14s %8s %8s %8s %8s %8s  %s" %
      ("net", "banned", "no-path", "trap", "noRetDel", "trap+X", "identity holds"))
rows = {}
for tag in NETS:
    net = sumolib.net.readNet(os.path.join(NET, "%s.net.xml" % tag))
    banned = nopath = trap = 0
    noret_del = 0          # verify_net's predicate, recomputed here
    nopath_and_noret = 0
    for a in ADDRS:
        e = net.getEdge(a["edge"])
        # ---- verify_net predicate (delivery only, ignores inbound) ----------
        del_noret = False
        if e.allows("delivery"):
            if all(net.getShortestPath(e, net.getEdge(de), vClass="delivery")[0] is None
                   for de in gf.DEPOT_EDGES):
                del_noret = True
                noret_del += 1
        # ---- gen_freight classification (first feasible vClass) -------------
        cands = [vc for vc in ("truck", "delivery") if e.allows(vc)]
        if not cands:
            banned += 1
            continue
        ok, any_in = False, False
        for vc in cands:
            for de in gf.DEPOT_EDGES:
                p1, _ = net.getShortestPath(net.getEdge(de), e, vClass=vc)
                if p1 is None:
                    continue
                any_in = True
                p2, _ = net.getShortestPath(e, net.getEdge(de), vClass=vc)
                if p2 is not None:
                    ok = True
                    break
            if ok:
                break
        if ok:
            continue
        if any_in:
            trap += 1
        else:
            nopath += 1
            if del_noret:
                nopath_and_noret += 1
    holds = (noret_del == trap + nopath_and_noret)
    rows[tag] = dict(banned=banned, no_path=nopath, trap=trap,
                     addr_no_return_delivery=noret_del,
                     nopath_that_also_cannot_return=nopath_and_noret,
                     identity_holds=holds)
    print("%-14s %8d %8d %8d %8d %8d  %s"
          % (tag, banned, nopath, trap, noret_del, trap + nopath_and_noret, holds))
json.dump(rows, open(os.path.join(TAB, "strict75_reconciliation.json"), "w"), indent=1)
print("\nwrote", os.path.join(TAB, "strict75_reconciliation.json"))
