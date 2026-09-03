#!/usr/bin/env python3
"""What did netconvert's --keep-edges.in-boundary cut actually change?

Compares the parent network against a cut network, restricted to the edges the
cut kept, and reports:
  * edge / lane / junction / connection / tlLogic counts
  * edge attributes that changed on SURVIVING edges (speed, lanes, length,
    priority, type, allow/disallow)
  * connections lost on surviving edges (dangling connections at the cut face)
  * traffic lights: dropped entirely, demoted to non-tls junctions, and
    tlLogic phase-state strings whose width shrank (orphan phase states)
  * whether the boundary test is "any point inside" or "fully inside"
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402


def load(path):
    net = sumolib.net.readNet(path)
    root = ET.parse(path).getroot()
    edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges[e.get("id")] = {
            "priority": e.get("priority"), "type": e.get("type"),
            "from": e.get("from"), "to": e.get("to"),
            "nlanes": len(e.findall("lane")),
            "speeds": [l.get("speed") for l in e.findall("lane")],
            "lengths": [l.get("length") for l in e.findall("lane")],
            "allow": [l.get("allow") for l in e.findall("lane")],
            "disallow": [l.get("disallow") for l in e.findall("lane")],
        }
    conns = set()
    conn_tl = {}
    for c in root.findall("connection"):
        k = (c.get("from"), c.get("fromLane"), c.get("to"), c.get("toLane"))
        conns.add(k)
        if c.get("tl"):
            conn_tl[k] = (c.get("tl"), c.get("linkIndex"))
    tls = {}
    for t in root.findall("tlLogic"):
        ph = [p.get("state") for p in t.findall("phase")]
        tls[t.get("id")] = {"n": len(ph), "w": len(ph[0]) if ph else 0,
                            "states": ph, "type": t.get("type"),
                            "prog": t.get("programID")}
    junc = {}
    for j in root.findall("junction"):
        if j.get("type") == "internal":
            continue
        junc[j.get("id")] = j.get("type")
    return net, edges, conns, conn_tl, tls, junc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True)
    ap.add_argument("--cut", required=True)
    ap.add_argument("--box", required=True)
    args = ap.parse_args()
    x0, y0, x1, y1 = [float(v) for v in args.box.split(",")]

    pnet, pe, pc, ptl_c, ptls, pj = load(args.parent)
    cnet, ce, cc, ctl_c, ctls, cj = load(args.cut)

    kept = set(ce)
    print("### counts")
    print("  parent: %d edges, %d lanes, %d junctions, %d connections, %d tlLogic"
          % (len(pe), sum(v["nlanes"] for v in pe.values()), len(pj), len(pc),
             len(ptls)))
    print("  cut   : %d edges, %d lanes, %d junctions, %d connections, %d tlLogic"
          % (len(ce), sum(v["nlanes"] for v in ce.values()), len(cj), len(cc),
             len(ctls)))
    print("  kept %d/%d edges (%.1f%%)" % (len(kept), len(pe),
                                           100.0 * len(kept) / len(pe)))
    novel = kept - set(pe)
    print("  edges present in cut but NOT in parent: %d %s"
          % (len(novel), sorted(novel)[:5]))

    # --- boundary semantics -------------------------------------------------
    fully, partly, outside = 0, 0, 0
    for eid in kept:
        shp = pnet.getEdge(eid).getShape()
        ins = [x0 <= x <= x1 and y0 <= y <= y1 for x, y in shp]
        if all(ins):
            fully += 1
        elif any(ins):
            partly += 1
        else:
            outside += 1
    print("\n### boundary semantics of --keep-edges.in-boundary")
    print("  kept edges fully inside box      : %d" % fully)
    print("  kept edges only partly inside box: %d" % partly)
    print("  kept edges with NO point in box  : %d" % outside)
    dropped_but_touching = sum(
        1 for eid in set(pe) - kept
        if any(x0 <= x <= x1 and y0 <= y <= y1
               for x, y in pnet.getEdge(eid).getShape()))
    print("  DROPPED edges that still touch the box: %d" % dropped_but_touching)

    # --- attribute drift on surviving edges --------------------------------
    drift = {k: 0 for k in ("nlanes", "speeds", "lengths", "priority", "type",
                            "allow", "disallow", "from", "to")}
    examples = {}
    for eid in kept:
        if eid not in pe:
            continue
        for k in drift:
            if pe[eid][k] != ce[eid][k]:
                drift[k] += 1
                examples.setdefault(k, (eid, pe[eid][k], ce[eid][k]))
    print("\n### attribute drift on surviving edges (n=%d)" % len(kept & set(pe)))
    for k, v in drift.items():
        ex = examples.get(k)
        print("  %-9s changed on %4d edges%s" % (
            k, v, ("   e.g. %s: %s -> %s" % ex) if ex else ""))

    # --- connections --------------------------------------------------------
    surviving_conns = set(k for k in pc if k[0] in kept and k[2] in kept)
    lost = surviving_conns - cc
    added = cc - pc
    dangling = set(k for k in pc if k[0] in kept and k[2] not in kept)
    print("\n### connections")
    print("  parent connections between surviving edges: %d" % len(surviving_conns))
    print("  of those, missing from the cut network    : %d" % len(lost))
    print("  connections in cut not present in parent  : %d" % len(added))
    print("  DANGLING: parent connections from a surviving edge to a dropped "
          "edge (silently deleted): %d" % len(dangling))

    # --- traffic lights -----------------------------------------------------
    dropped_tls = set(ptls) - set(ctls)
    kept_tls = set(ptls) & set(ctls)
    shrunk = [(t, ptls[t]["w"], ctls[t]["w"]) for t in kept_tls
              if ptls[t]["w"] != ctls[t]["w"]]
    phasecount = [(t, ptls[t]["n"], ctls[t]["n"]) for t in kept_tls
                  if ptls[t]["n"] != ctls[t]["n"]]
    typechg = [(t, ptls[t]["type"], ctls[t]["type"]) for t in kept_tls
               if ptls[t]["type"] != ctls[t]["type"]]
    demoted = [j for j in cj if j in pj and pj[j] == "traffic_light"
               and cj[j] != "traffic_light"]
    print("\n### traffic lights")
    print("  parent tlLogic: %d, cut tlLogic: %d, dropped entirely: %d"
          % (len(ptls), len(ctls), len(dropped_tls)))
    print("  surviving TLS whose phase-state WIDTH changed (links added/removed"
          " -> phases rewritten): %d" % len(shrunk))
    for t, a, b in shrunk[:8]:
        print("      %s  state width %d -> %d" % (t, a, b))
    print("  surviving TLS whose PHASE COUNT changed: %d %s"
          % (len(phasecount), phasecount[:5]))
    print("  surviving TLS whose type changed: %d %s" % (len(typechg), typechg[:5]))
    print("  junctions that were traffic_light in parent but are NOT in cut "
          "(demoted, still present): %d %s" % (len(demoted), demoted[:5]))
    # all-red / never-green phases in the cut
    allred = 0
    for t, d in ctls.items():
        for s in d["states"]:
            if "G" not in s and "g" not in s:
                allred += 1
    print("  cut phases with no green at all (orphan/all-red phases): %d" % allred)
    pallred = sum(1 for t, d in ptls.items() if t in ctls
                  for s in d["states"] if "G" not in s and "g" not in s)
    print("  same TLS in parent, phases with no green: %d" % pallred)


if __name__ == "__main__":
    main()
