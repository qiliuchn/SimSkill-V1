"""Build the parameterized downtown grid (5x5 junctions, ~150 m blocks, 1 lane/dir,
sidewalks + crossings) and verify the compiled result.

Uses the `create-grid-network` skill's netgenerate approach (binary resolved via
PATH -> next to sumo -> $SUMO_HOME/bin, per that skill's gotcha).
"""
import json
import os
import sys

from common import NETGENERATE, NET_DIR, run, SUMO_HOME

sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

NET = os.path.join(NET_DIR, "downtown.net.xml")

GRID_N = 5
BLOCK = 150.0
ATTACH = 140.0


def build():
    cmd = [
        NETGENERATE, "--grid",
        "--grid.x-number", str(GRID_N), "--grid.y-number", str(GRID_N),
        "--grid.x-length", str(BLOCK), "--grid.y-length", str(BLOCK),
        "--grid.attach-length", str(ATTACH),
        "--default.lanenumber", "1",
        "--default.speed", "11.11",
        "--default-junction-type", "priority",
        "--sidewalks.guess",
        "--crossings.guess",
        "--no-turnarounds", "true",
        "--tls.guess", "false",
        "--seed", "1",
        "-o", NET,
    ]
    run(cmd)
    return NET


def verify(net_path):
    net = sumolib.net.readNet(net_path)
    edges = [e for e in net.getEdges() if not e.isSpecial()]
    info = {
        "net": net_path,
        "n_junctions": len(net.getNodes()),
        "n_edges_normal": len(edges),
        "junction_types": {},
        "n_edges_with_sidewalk": 0,
        "n_crossings": 0,
        "car_lane_index": {},
    }
    for n in net.getNodes():
        info["junction_types"][n.getType()] = info["junction_types"].get(n.getType(), 0) + 1
    for e in edges:
        has_ped = any(l.allows("pedestrian") and not l.allows("passenger") for l in e.getLanes())
        if has_ped:
            info["n_edges_with_sidewalk"] += 1
        for l in e.getLanes():
            if l.allows("passenger"):
                idx = l.getIndex()
                info["car_lane_index"][str(idx)] = info["car_lane_index"].get(str(idx), 0) + 1
    # crossings appear as special edges of function 'crossing'
    info["n_crossings"] = sum(1 for e in net.getEdges() if e.getFunction() == "crossing")
    lens = sorted(set(round(e.getLength(), 1) for e in edges))
    info["edge_lengths"] = lens
    return info


if __name__ == "__main__":
    p = build()
    info = verify(p)
    with open(os.path.join(NET_DIR, "network_verification.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))
