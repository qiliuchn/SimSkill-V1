#!/usr/bin/env python3
"""Verify every claim about the six compiled networks FROM THE .net.xml FILES."""
import os
import sys
import json
import collections

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.abspath(os.path.join(HERE, "..", "net"))
ANA = os.path.abspath(os.path.join(HERE, "..", "analysis"))
os.makedirs(ANA, exist_ok=True)

VARIANTS = list("ABCDEF")
sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
FILTERED = set(sets["FILTERED"])
ONEWAY_REMOVED = set(sets["ONEWAY_REMOVED"])
DIVERTERS = dict(x.split(":") for x in sets["DIVERTERS"])


def cls(eid):
    if eid[:2] in ("IH", "IV"):
        return "interior_street"
    if eid[0] == "K":
        return "access_connector"
    if eid.startswith("RG"):
        return "ring_arterial"
    if eid.startswith("EX"):
        return "external_stub"
    return "other"


report = {}
for v in VARIANTS:
    net = sumolib.net.readNet(os.path.join(NET, "%s.net.xml" % v), withConnections=True)
    r = {}
    byclass = collections.defaultdict(lambda: collections.Counter())
    lanekm = collections.Counter()
    for e in net.getEdges():
        if e.getFunction():          # skip internal
            continue
        c = cls(e.getID())
        byclass[c]["n"] += 1
        byclass[c]["speed_%.3f" % e.getSpeed()] += 1
        byclass[c]["lanes_%d" % e.getLaneNumber()] += 1
        byclass[c]["prio_%d" % e.getPriority()] += 1
        lanekm[c] += e.getLength() * e.getLaneNumber() / 1000.0
    r["edge_classes"] = {k: dict(x) for k, x in byclass.items()}
    r["lane_km"] = {k: round(x, 3) for k, x in lanekm.items()}
    r["lane_km_total"] = round(sum(lanekm.values()), 3)

    # junction types
    jt = collections.Counter()
    for n in net.getNodes():
        jt[n.getType()] += 1
    r["junction_types"] = dict(jt)
    r["tls_ids"] = sorted(t.getID() for t in net.getTrafficLights())

    # ---- filtered-edge permissions (from the compiled net) ----
    perm = {}
    for eid in sorted(FILTERED):
        e = net.getEdge(eid) if net.hasEdge(eid) else None
        if e is None:
            perm[eid] = "ABSENT"
        else:
            perm[eid] = sorted(e.getLane(0).getPermissions())
    r["filtered_edge_permissions"] = perm
    r["passenger_allowed_on_filtered"] = sorted(
        k for k, val in perm.items() if val != "ABSENT" and "passenger" in val)

    # ---- one-way removal ----
    r["oneway_removed_still_present"] = sorted(e for e in ONEWAY_REMOVED if net.hasEdge(e))
    r["n_interior_directed_edges"] = sum(1 for e in net.getEdges()
                                         if not e.getFunction() and cls(e.getID()) == "interior_street")

    # ---- diverter connection prohibitions ----
    banned_present, allowed_present = [], []
    for jid, kind in DIVERTERS.items():
        node = net.getNode(jid)
        i, j = int(jid[1]), int(jid[2])
        for e in node.getIncoming():
            if e.getFunction():
                continue
            for out in node.getOutgoing():
                if out.getFunction():
                    continue
                has = any(c.getTo() == out for l in e.getLanes() for c in l.getOutgoing())
                key = "%s|%s->%s" % (jid, e.getID(), out.getID())
                if has:
                    allowed_present.append(key)
    r["diverter_junctions"] = sorted(DIVERTERS)
    r["diverter_movements_present"] = sorted(allowed_present)
    r["n_diverter_movements_present"] = len(allowed_present)

    # ---- connectivity: passenger reachability among all non-internal edges ----
    def reach(vclass):
        edges = [e for e in net.getEdges() if not e.getFunction()
                 and any(l.allows(vclass) for l in e.getLanes())]
        idx = {e: k for k, e in enumerate(edges)}
        # forward BFS from external inbound stubs
        import collections as C
        seeds = [e for e in edges if e.getID().startswith("EX") and e.getID().endswith("I")]
        seen = set(seeds)
        q = C.deque(seeds)
        while q:
            e = q.popleft()
            for l in e.getLanes():
                for c in l.getOutgoing():
                    t = c.getTo().getEdge() if hasattr(c.getTo(), "getEdge") else c.getTo()
                    if t in idx and t not in seen:
                        seen.add(t)
                        q.append(t)
        # backward BFS to external outbound stubs
        rev = C.defaultdict(list)
        for e in edges:
            for l in e.getLanes():
                for c in l.getOutgoing():
                    t = c.getTo()
                    if t in idx:
                        rev[t].append(e)
        sinks = [e for e in edges if e.getID().startswith("EX") and e.getID().endswith("O")]
        seen2 = set(sinks)
        q = C.deque(sinks)
        while q:
            e = q.popleft()
            for p in rev[e]:
                if p not in seen2:
                    seen2.add(p)
                    q.append(p)
        both = seen & seen2
        return len(edges), len(both), sorted(e.getID() for e in edges if e not in both)

    for vc in ("passenger", "emergency"):
        n_e, n_ok, bad = reach(vc)
        r["reach_%s" % vc] = dict(n_edges=n_e, n_connected=n_ok, unreachable=bad[:20],
                                  n_unreachable=len(bad))
    report[v] = r

json.dump(report, open(os.path.join(ANA, "network_verification.json"), "w"), indent=1)

# ------------------------------------------------------------------ print ----
for v in VARIANTS:
    r = report[v]
    print("=" * 70)
    print("VARIANT %s" % v)
    for c in ("interior_street", "access_connector", "ring_arterial", "external_stub"):
        d = r["edge_classes"].get(c, {})
        sp = sorted(k for k in d if k.startswith("speed_"))
        ln = sorted(k for k in d if k.startswith("lanes_"))
        pr = sorted(k for k in d if k.startswith("prio_"))
        print("  %-17s n=%-4d %s %s %s  lane-km=%.2f"
              % (c, d.get("n", 0), sp, ln, pr, r["lane_km"].get(c, 0)))
    print("  junction types: %s ; %d TLS: %s" % (r["junction_types"], len(r["tls_ids"]), r["tls_ids"]))
    print("  filtered edges w/ passenger allowed: %s" % r["passenger_allowed_on_filtered"])
    print("  oneway-removed edges still present: %d" % len(r["oneway_removed_still_present"]))
    print("  interior directed edges: %d" % r["n_interior_directed_edges"])
    print("  diverter movements present at the 8 diverter junctions: %d"
          % r["n_diverter_movements_present"])
    print("  passenger reach: %s" % r["reach_passenger"])
    print("  emergency reach: %s" % r["reach_emergency"])
