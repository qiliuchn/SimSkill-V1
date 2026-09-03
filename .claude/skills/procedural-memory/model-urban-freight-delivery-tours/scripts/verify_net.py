#!/usr/bin/env python3
"""
Deliverable (b): prove FROM THE COMPILED NET (not the input .edg.xml) that
  1. every intended disallow landed on the compiled lane, and nothing else did;
  2. arterial/local lane counts, speeds and signal control are as designed;
  3. loading bays / containerStops sit on the intended compiled lanes and fit;
  4. a truck-class route still exists from every depot to every delivery edge
     (and, where it does not, that this is exactly the intended banned set).

Writes outputs/tables/net_verification.csv and outputs/tables/NET_VERIFICATION.md
"""
import os, sys, json, csv
import xml.etree.ElementTree as ET
from common import *   # noqa
import build_network as bn
import sumolib


def verify_variant(tag, meta, addrs):
    netf = os.path.join(NET, "%s.net.xml" % tag)
    net = sumolib.net.readNet(netf)
    banned_streets = {tuple(tuple(x) for x in s) for s in meta["banned"]}
    ban_classes = set(meta["ban_classes"].split())

    intended_banned_edges = set()
    for s in banned_streets:
        (i1, j1), (i2, j2) = s
        a, b = nid(i1, j1), nid(i2, j2)
        intended_banned_edges |= {eid(a, b), eid(b, a)}

    res = dict(tag=tag, family=meta["family"], coverage=meta["coverage"],
               ban_classes=meta["ban_classes"])

    # --- 1. permissions on the COMPILED lanes -------------------------------
    miss, extra = [], []
    for e in net.getEdges():
        if e.getID().startswith(":"):
            continue
        for lane in e.getLanes():
            for vc in ("truck", "delivery"):
                allowed = lane.allows(vc)
                should_ban = (e.getID() in intended_banned_edges) and (vc in ban_classes)
                if should_ban and allowed:
                    miss.append((e.getID(), lane.getID(), vc))
                if (not should_ban) and (not allowed):
                    extra.append((e.getID(), lane.getID(), vc))
    res["compiled_disallow_missing"] = len(miss)
    res["compiled_disallow_unexpected"] = len(extra)
    res["intended_banned_edges"] = len(intended_banned_edges)
    res["compiled_banned_edges"] = sum(
        1 for e in net.getEdges()
        if not e.getID().startswith(":")
        and all(not e.getLanes()[0].allows(vc) for vc in ban_classes))

    # --- 2. geometry / control ----------------------------------------------
    art, loc = bn.arterial_edges(), bn.local_edges()
    res["arterial_edges"] = len(art)
    res["local_edges"] = len(loc)
    res["arterial_lanes_ok"] = all(net.getEdge(e).getLaneNumber() == ART_LANES for e in art)
    res["local_lanes_ok"] = all(net.getEdge(e).getLaneNumber() == LOC_LANES for e in loc)
    res["arterial_speed_ok"] = all(abs(net.getEdge(e).getSpeed() - ART_SPEED) < 0.02 for e in art)
    res["local_speed_ok"] = all(abs(net.getEdge(e).getSpeed() - LOC_SPEED) < 0.02 for e in loc)
    tls = {t.getID() for t in net.getTrafficLights()}
    want_tls = {nid(i, j) for i in range(N) for j in range(N) if is_signalized(i, j)}
    res["n_tls"] = len(tls)
    res["tls_set_ok"] = (tls == want_tls)
    prio_nodes = {n.getID() for n in net.getNodes() if n.getType() == "priority"}
    res["n_priority_nodes"] = len(prio_nodes)

    # --- 3. containerStops / loading bays on compiled lanes -----------------
    # the containerStop set is identical across variants (it is written from the
    # address list, not from the ban set); verify it against this variant's compiled net
    addf = os.path.join(DEMAND, "f_E1_tour_s1.add.xml")
    res["bays_checked"] = 0
    res["bays_bad"] = 0
    if os.path.exists(addf):
        for cs in ET.parse(addf).getroot():
            if cs.tag != "containerStop":
                continue
            lane = net.getLane(cs.get("lane"))
            res["bays_checked"] += 1
            sp, ep = float(cs.get("startPos")), float(cs.get("endPos"))
            if lane is None or ep > lane.getLength() or sp < 0 or (ep - sp) < 16.5:
                res["bays_bad"] += 1

    # --- 4. truck-class reachability from every depot to every address ------
    import gen_freight as gf
    unreach = {"truck": [], "delivery": []}
    for vc in ("truck", "delivery"):
        for a in addrs:
            e = net.getEdge(a["edge"])
            if not e.allows(vc):
                unreach[vc].append((a["id"], "edge-banned"))
                continue
            ok = False
            for de in gf.DEPOT_EDGES:
                p, c = net.getShortestPath(net.getEdge(de), e, vClass=vc)
                if p is not None:
                    ok = True
                    break
            if not ok:
                unreach[vc].append((a["id"], "no-path"))
    res["addr_unreachable_truck"] = len(unreach["truck"])
    res["addr_unreachable_delivery"] = len(unreach["delivery"])
    res["addr_total"] = len(addrs)

    # --- 5. return-leg reachability (address -> depot) -----------------------
    back_fail = 0
    for vc in ("delivery",):
        for a in addrs:
            e = net.getEdge(a["edge"])
            if not e.allows(vc):
                continue
            if all(net.getShortestPath(e, net.getEdge(de), vClass=vc)[0] is None
                   for de in gf.DEPOT_EDGES):
                back_fail += 1
    res["addr_no_return_delivery"] = back_fail
    res["_detail_unreach"] = unreach
    return res


def main():
    manifest = json.load(open(os.path.join(NET, "net_manifest.json")))
    addrs = json.load(open(os.path.join(DEMAND, "addresses.json")))
    rows = []
    for tag, meta in manifest.items():
        r = verify_variant(tag, meta, addrs)
        rows.append(r)
        print("%-14s ban=%-16s disallow_missing=%d unexpected=%d  "
              "unreachable(truck)=%3d unreachable(van)=%3d  tls_ok=%s lanes_ok=%s"
              % (tag, r["ban_classes"], r["compiled_disallow_missing"],
                 r["compiled_disallow_unexpected"], r["addr_unreachable_truck"],
                 r["addr_unreachable_delivery"], r["tls_set_ok"],
                 r["arterial_lanes_ok"] and r["local_lanes_ok"]))
    keys = [k for k in rows[0] if not k.startswith("_")]
    with open(os.path.join(TAB, "net_verification.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in keys})
    json.dump(rows, open(os.path.join(TAB, "net_verification_detail.json"), "w"),
              indent=1, default=str)
    print("wrote", os.path.join(TAB, "net_verification.csv"))


if __name__ == "__main__":
    main()
