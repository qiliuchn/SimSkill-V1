"""
Classify network edges into interior-origin vs. boundary/fringe-exit sets for
an evacuation demand pattern, verified against the actual compiled net (never
assumed from grid coordinates or node naming).

- Fringe node: a node with exactly one distinct neighbor (a dead-end stub at
  the map boundary -- with netgenerate's --grid.attach-length these are the
  outward attach edges).
- Fringe EXIT edge: any edge whose TO-node is a fringe node -- reaching it
  means leaving the network. These are the evacuation destinations.
- Interior ORIGIN edge: an edge that is not a fringe-exit edge and whose
  FROM-node is not a fringe node (a genuine in-grid street segment). These
  are the evacuation origins.

Also assigns each interior edge to a concentric zone (by distance from the
network's geometric center) for a staged/phased release strategy, and writes
randomTrips.py-compatible weight files restricting trip origins to interior
edges and destinations to fringe-exit edges.

Usage:
    python classify_evacuation_edges.py --net grid.net.xml --out-dir demand/ --n-zones 3
"""

import argparse
import json
import math
import os
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Classify interior/fringe-exit edges and zones for an evacuation scenario.")
    p.add_argument("--net", required=True)
    p.add_argument("--out-dir", default="demand")
    p.add_argument("--n-zones", type=int, default=3, help="Number of concentric zones for staged release (0=innermost/farthest from exits)")
    return p.parse_args()


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib  # noqa: E402

    os.makedirs(args.out_dir, exist_ok=True)
    net = sumolib.net.readNet(args.net)
    edges = [e for e in net.getEdges() if e.getFunction() != "internal"]

    def neighbors(node):
        nb = set()
        for e in node.getOutgoing():
            if e.getFunction() != "internal":
                nb.add(e.getToNode().getID())
        for e in node.getIncoming():
            if e.getFunction() != "internal":
                nb.add(e.getFromNode().getID())
        nb.discard(node.getID())
        return nb

    fringe_nodes = {n.getID() for n in net.getNodes() if len(neighbors(n)) == 1}

    fringe_exit, interior = [], []
    for e in edges:
        to_fr = e.getToNode().getID() in fringe_nodes
        from_fr = e.getFromNode().getID() in fringe_nodes
        if to_fr:
            fringe_exit.append(e)
        elif not from_fr:
            interior.append(e)
        # from_fr and not to_fr -> inbound stub bringing traffic IN; excluded from both sets.

    xs, ys = [], []
    for e in edges:
        for x, y in e.getShape():
            xs.append(x)
            ys.append(y)
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

    def edge_center(e):
        shp = e.getShape()
        return sum(p[0] for p in shp) / len(shp), sum(p[1] for p in shp) / len(shp)

    dists = {}
    for e in interior:
        mx, my = edge_center(e)
        dists[e.getID()] = math.hypot(mx - cx, my - cy)

    dvals = sorted(dists.values())
    n = len(dvals)
    tertiles = [dvals[int(n * (i + 1) / args.n_zones)] for i in range(args.n_zones - 1)] if n else []

    def zone_of(eid):
        d = dists[eid]
        for z, t in enumerate(tertiles):
            if d <= t:
                return z
        return args.n_zones - 1

    zones = {eid: zone_of(eid) for eid in dists}

    manifest = {
        "net": args.net, "center": [cx, cy], "n_total_edges": len(edges),
        "n_fringe_exit": len(fringe_exit), "n_interior": len(interior),
        "fringe_exit_ids": sorted(e.getID() for e in fringe_exit),
        "interior_ids": sorted(e.getID() for e in interior),
        "zone_boundaries": tertiles, "zones": zones,
        "zone_counts": {z: sum(1 for v in zones.values() if v == z) for z in range(args.n_zones)},
    }
    with open(os.path.join(args.out_dir, "edge_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    def write_weights(path, ids, val=1.0):
        with open(path, "w") as wf:
            wf.write('<edgedata>\n  <interval begin="0" end="100000">\n')
            for eid in ids:
                wf.write(f'    <edge id="{eid}" value="{val}"/>\n')
            wf.write("  </interval>\n</edgedata>\n")

    write_weights(os.path.join(args.out_dir, "evac.src.xml"), [e.getID() for e in interior])
    write_weights(os.path.join(args.out_dir, "evac.dst.xml"), [e.getID() for e in fringe_exit])

    print(f"total edges: {len(edges)}")
    print(f"interior origin edges: {len(interior)}")
    print(f"fringe exit edges: {len(fringe_exit)}")
    print(f"zone counts (0=innermost): {manifest['zone_counts']}")


if __name__ == "__main__":
    main()
