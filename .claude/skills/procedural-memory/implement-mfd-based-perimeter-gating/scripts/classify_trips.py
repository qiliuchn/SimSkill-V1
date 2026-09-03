#!/usr/bin/env python3
"""
Classify each routed vehicle from its ACTUAL duarouter route:
  CORE     : the destination (last) edge is a core edge
  THROUGH  : route uses >=1 core edge but does not end in the core
  OUTSIDE  : route never touches a core edge
Also stores the planned route of every vehicle so that a later check can prove
no vehicle deviated from it (rerouting disabled).
"""
import argparse
import json
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True)
    ap.add_argument("--core-gate", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cg = json.load(open(args.core_gate))
    core = set(cg["core_edges"])

    cls = {}
    planned = {}
    counts = {"core": 0, "through": 0, "outside": 0}
    n_core_edge_uses = 0
    for _, veh in ET.iterparse(args.routes, events=("end",)):
        if veh.tag != "vehicle":
            continue
        vid = veh.get("id")
        r = veh.find("route")
        edges = r.get("edges").split()
        planned[vid] = " ".join(edges)
        used = [e for e in edges if e in core]
        n_core_edge_uses += len(used)
        if edges[-1] in core:
            k = "core"
        elif used:
            k = "through"
        else:
            k = "outside"
        cls[vid] = k
        counts[k] += 1
        veh.clear()

    json.dump({"counts": counts, "class": cls, "planned": planned,
               "core_edge_uses": n_core_edge_uses},
              open(args.out, "w"))
    print(counts, "core-edge traversals planned:", n_core_edge_uses)


if __name__ == "__main__":
    main()
