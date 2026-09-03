#!/usr/bin/env python3
"""ID-based structural comparison of two SUMO .net.xml files.

Used both as (a) the lossless-control check for the plain-XML round trip and
(b) the per-fix verification that an intended edit is actually present in the
compiled net. IDs are stable here (unlike the OpenDRIVE case) because we never
leave the SUMO plain-XML representation, so ID matching is valid and far
sharper than geometric matching -- but we assert that assumption explicitly by
reporting id-set deltas first.

Usage: python3 netcmp.py A.net.xml B.net.xml [--quiet]
"""
import sys, collections
import xml.etree.ElementTree as ET


def load(p):
    r = ET.parse(p).getroot()
    edges = {}
    for e in r.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        edges[e.get("id")] = dict(
            nlanes=len(lanes),
            speed=round(float(lanes[0].get("speed")), 3) if lanes else None,
            length=round(float(lanes[0].get("length")), 3) if lanes else None,
            frm=e.get("from"), to=e.get("to"), name=e.get("name"), prio=e.get("priority"),
        )
    junctions = {}
    for j in r.findall("junction"):
        if j.get("type") == "internal":
            continue
        junctions[j.get("id")] = dict(type=j.get("type"), x=j.get("x"), y=j.get("y"),
                                      inc=len(j.get("incLanes", "").split()),
                                      nreq=len(j.findall("request")))
    conns = {}
    for c in r.findall("connection"):
        if c.get("from", "").startswith(":"):
            continue
        k = (c.get("from"), c.get("fromLane"), c.get("to"), c.get("toLane"))
        conns[k] = dict(dir=c.get("dir"), state=c.get("state"), tl=c.get("tl"),
                        li=c.get("linkIndex"))
    tls = {}
    for t in r.findall("tlLogic"):
        ph = [(p.get("duration"), p.get("state")) for p in t.findall("phase")]
        tls[t.get("id")] = dict(type=t.get("type"), phases=ph,
                                cycle=sum(float(d) for d, _ in ph),
                                nlinks=len(ph[0][1]) if ph else 0)
    return edges, junctions, conns, tls


def cmp_dicts(a, b, label, keys=None, verbose=True):
    ka, kb = set(a), set(b)
    only_a, only_b = sorted(ka - kb), sorted(kb - ka)
    changed = []
    for k in ka & kb:
        if a[k] != b[k]:
            diff = {f: (a[k][f], b[k][f]) for f in a[k] if a[k][f] != b[k][f]} if isinstance(a[k], dict) else (a[k], b[k])
            changed.append((k, diff))
    print(f"  {label}: A={len(a)} B={len(b)}  removed={len(only_a)} added={len(only_b)} changed={len(changed)}")
    if verbose:
        for x in only_a[:8]: print(f"      - {x}")
        if len(only_a) > 8: print(f"      ... {len(only_a)-8} more removed")
        for x in only_b[:8]: print(f"      + {x}")
        if len(only_b) > 8: print(f"      ... {len(only_b)-8} more added")
        for k, d in changed[:8]: print(f"      ~ {k}: {d}")
        if len(changed) > 8: print(f"      ... {len(changed)-8} more changed")
    return dict(removed=only_a, added=only_b, changed=changed)


def main():
    A, B = sys.argv[1], sys.argv[2]
    verbose = "--quiet" not in sys.argv
    ea, ja, ca, ta = load(A)
    eb, jb, cb, tb = load(B)
    print(f"COMPARE  A={A}\n         B={B}")
    r = {}
    r["edges"] = cmp_dicts(ea, eb, "edges", verbose=verbose)
    r["junctions"] = cmp_dicts(ja, jb, "junctions", verbose=verbose)
    r["connections"] = cmp_dicts(ca, cb, "connections", verbose=verbose)
    r["tls"] = cmp_dicts(ta, tb, "tlLogic", verbose=verbose)
    identical = all(not (v["removed"] or v["added"] or v["changed"]) for v in r.values())
    print(f"  => {'IDENTICAL' if identical else 'DIFFERENT'}")
    return r


if __name__ == "__main__":
    main()
