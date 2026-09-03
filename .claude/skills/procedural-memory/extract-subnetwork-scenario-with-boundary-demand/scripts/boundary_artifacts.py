#!/usr/bin/env python3
"""Diagnose the systematic boundary artifacts of a cut SUMO sub-scenario.

Splits the cut network's edges into
  entry  -- edges where cutRoutes.py injects truncated vehicles (first edge of
            a route that was truncated, i.e. carries departSpeed/departLane)
  exit   -- last edge of a truncated route (vehicles vanish here)
  inner  -- everything else
and, for each class, compares parent vs cut mean speed, travel time, time loss
and waiting time.  Also locates the cut run's teleports relative to the
boundary and compares them with the parent's.
"""
import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET
import re

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402


def read_edgedata(path):
    iv = ET.parse(path).getroot().find("interval")
    out = {}
    for e in iv.findall("edge"):
        out[e.get("id")] = {k: (float(e.get(k)) if e.get(k) is not None else None)
                            for k in ("sampledSeconds", "speed", "traveltime",
                                      "timeLoss", "waitingTime", "departed",
                                      "arrived", "entered", "left")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut-net", required=True)
    ap.add_argument("--cut-routes", required=True)
    ap.add_argument("--cut-edgedata", required=True)
    ap.add_argument("--cut-log", required=True, help="sumo stderr of the cut run")
    ap.add_argument("--parent-edgedata", required=True)
    ap.add_argument("--parent-log", required=True)
    ap.add_argument("--parent-net", required=True)
    args = ap.parse_args()

    net = sumolib.net.readNet(args.cut_net)
    pnet = sumolib.net.readNet(args.parent_net)

    root = ET.parse(args.cut_routes).getroot()
    entry, exitset, allroute = set(), set(), set()
    n_trunc = n_whole = 0
    for v in root.findall("vehicle"):
        eds = v.find("route").get("edges").split()
        allroute.update(eds)
        if v.get("departSpeed") is not None:   # cutRoutes marks truncated veh
            entry.add(eds[0])
            exitset.add(eds[-1])
            n_trunc += 1
        else:
            n_whole += 1
    real = [e for e in net.getEdges() if e.getFunction() != "internal"]
    # topological cut face: an edge whose from-node has no incoming real edge is
    # a source of the sub-network (traffic can only appear there by injection);
    # symmetrically for sinks.
    src = set(e.getID() for e in real if not e.getFromNode().getIncoming())
    snk = set(e.getID() for e in real if not e.getToNode().getOutgoing())
    inner = allroute - entry - exitset
    print("cut routes: %d truncated (boundary-injected), %d entirely interior"
          % (n_trunc, n_whole))
    print("network has %d real edges; topological cut face: %d source edges, "
          "%d sink edges" % (len(real), len(src), len(snk)))
    print("route-derived: %d distinct injection edges, %d distinct last edges"
          % (len(entry), len(exitset)))
    print("injection edges that are topological sources: %d/%d"
          % (len(entry & src), len(entry)))

    # BFS hop distance from the INJECTION face.  Note the topological source set
    # (in-degree 0) badly under-counts the cut face: an edge that the parent fed
    # from outside the box usually still has other in-box predecessors, so it is
    # not a graph source even though it is where vehicles get injected.  The
    # route-derived injection set is the operationally correct cut face.
    seeds = entry & set(e.getID() for e in real)
    dist = {eid: 0 for eid in seeds}
    frontier = list(seeds)
    d = 0
    while frontier:
        d += 1
        nxt = []
        for eid in frontier:
            for o in net.getEdge(eid).getOutgoing():
                oid = o.getID()
                if oid not in dist:
                    dist[oid] = d
                    nxt.append(oid)
        frontier = nxt
    print("hop-distance from cut face: max=%d, unreachable=%d"
          % (max(dist.values()), len(real) - len(dist)))

    P = read_edgedata(args.parent_edgedata)
    C = read_edgedata(args.cut_edgedata)

    print("\n%-8s %5s | %-28s | %-28s" % ("class", "n", "parent (speed/tt/timeLoss/wait)",
                                          "cut    (speed/tt/timeLoss/wait)"))
    rows = []
    bands = [("hop<=1", [e for e in dist if dist[e] <= 1]),
             ("hop2-3", [e for e in dist if 2 <= dist[e] <= 3]),
             ("hop4-6", [e for e in dist if 4 <= dist[e] <= 6]),
             ("hop>=7", [e for e in dist if dist[e] >= 7])]
    for name, eids in (("entry", entry), ("sink", snk), ("inner", inner)) + tuple(bands):
        eids = [e for e in eids if e in P and e in C
                and P[e]["sampledSeconds"] > 0 and C[e]["sampledSeconds"] > 0]
        if not eids:
            continue

        def agg(D, k):
            num = sum(D[e][k] * D[e]["sampledSeconds"] for e in eids
                      if D[e][k] is not None)
            den = sum(D[e]["sampledSeconds"] for e in eids)
            return num / den if den else float("nan")

        def tot(D, k):
            return sum(D[e][k] or 0 for e in eids)
        r = (name, len(eids),
             agg(P, "speed"), agg(P, "traveltime"),
             tot(P, "timeLoss") / max(1, tot(P, "entered") + tot(P, "departed")),
             tot(P, "waitingTime") / max(1, tot(P, "entered") + tot(P, "departed")),
             agg(C, "speed"), agg(C, "traveltime"),
             tot(C, "timeLoss") / max(1, tot(C, "entered") + tot(C, "departed")),
             tot(C, "waitingTime") / max(1, tot(C, "entered") + tot(C, "departed")))
        rows.append(r)
        print("%-8s %5d | %6.2f m/s %6.2f s %6.2f s %6.2f s | "
              "%6.2f m/s %6.2f s %6.2f s %6.2f s   [speed %+.1f%%, timeLoss %+.1f%%]"
              % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                 100 * (r[6] - r[2]) / r[2], 100 * (r[8] - r[4]) / r[4] if r[4] else float("nan")))

    # ---- teleports -----------------------------------------------------
    def teleports(log, netobj):
        out = []
        for line in open(log, errors="ignore"):
            m = re.search(r"Teleporting vehicle '([^']+)'; waited too long "
                          r"\(([a-z ]+)\), lane='([^']+)'", line)
            if m:
                out.append((m.group(1), m.group(2), m.group(3).rsplit("_", 1)[0]))
        return out

    ct = teleports(args.cut_log, net)
    pt = teleports(args.parent_log, pnet)
    print("\nteleports: parent=%d (whole %d-edge net), cut=%d (%d-edge net)"
          % (len(pt), len([e for e in pnet.getEdges() if e.getFunction() != 'internal']),
             len(ct), len([e for e in net.getEdges() if e.getFunction() != 'internal'])))
    p_in_area = [t for t in pt if t[2] in allroute or t[2] in C]
    print("  parent teleports that occurred on edges inside the study area: %d"
          % len(p_in_area))
    for cls, s in (("entry", entry), ("exit", exitset)):
        print("  cut teleports on %-5s edges: %d" % (cls, sum(1 for t in ct if t[2] in s)))
    print("  cut teleports on inner edges: %d" % sum(1 for t in ct if t[2] in inner))
    print("  cut teleport reasons: %s"
          % {r: sum(1 for t in ct if t[1] == r) for r in set(t[1] for t in ct)})
    print("  cut teleport edges: %s" % sorted(set(t[2] for t in ct)))


if __name__ == "__main__":
    main()
