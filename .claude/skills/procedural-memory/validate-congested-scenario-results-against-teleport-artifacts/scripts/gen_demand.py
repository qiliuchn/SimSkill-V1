#!/usr/bin/env python3
"""
Generate demand for the gridlock-prone 6x6 signalized grid.

Two demand components:
  1. "general" : fringe -> fringe random OD, routed by duarouter (shortest path).
  2. "loop"    : explicit routes that traverse a COUNTER-CLOCKWISE ring around the
                 network core.  In SUMO's (x right, y up) coordinates a CCW circuit
                 turns LEFT at every corner, and a saturated ring of short blocks is
                 the canonical circular-blocking / gridlock generator: each block's
                 queue depends on the next block around the cycle.

The same route file is reused verbatim across every --time-to-teleport value and
every keep-clear arm, so the treatment is numerically pure.
"""
import argparse
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET

COLS = "ABCDEF"
ROWS = "012345"


def sumo_bin(name):
    import shutil
    p = shutil.which(name)
    if p:
        return p
    p = shutil.which("sumo")
    if p:
        cand = os.path.join(os.path.dirname(p), name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("cannot find " + name)


def load_net(netfile):
    root = ET.parse(netfile).getroot()
    jtype = {}
    for j in root.findall("junction"):
        if j.get("type") == "internal":
            continue
        jtype[j.get("id")] = j.get("type")
    edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges[e.get("id")] = (e.get("from"), e.get("to"))
    return jtype, edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--general", type=int, required=True, help="number of general trips")
    ap.add_argument("--loop", type=int, required=True, help="number of ring-circulating trips")
    ap.add_argument("--load-end", type=float, default=1800.0)
    ap.add_argument("--laps", type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    jtype, edges = load_net(args.net)

    fringe_in = [eid for eid, (f, t) in edges.items()
                 if jtype.get(f) == "dead_end" and jtype.get(t) == "traffic_light"]
    fringe_out = [eid for eid, (f, t) in edges.items()
                  if jtype.get(t) == "dead_end" and jtype.get(f) == "traffic_light"]
    fringe_in.sort()
    fringe_out.sort()

    workdir = os.path.dirname(os.path.abspath(args.out))
    tag = os.path.basename(args.out).replace(".rou.xml", "")

    # ---------------- general demand: fringe -> fringe ----------------
    trips_path = os.path.join(workdir, tag + ".trips.xml")
    with open(trips_path, "w") as fh:
        fh.write("<routes>\n")
        n = args.general
        for i in range(n):
            fr = rng.choice(fringe_in)
            to = rng.choice(fringe_out)
            # forbid immediate U-turn back out of the same fringe node
            guard = 0
            while edges[to][1] == edges[fr][0] and guard < 20:
                to = rng.choice(fringe_out)
                guard += 1
            dep = rng.uniform(0.0, args.load_end)
            fh.write('    <trip id="gen.%d" depart="%.2f" from="%s" to="%s"/>\n' % (i, dep, fr, to))
        fh.write("</routes>\n")

    gen_rou = os.path.join(workdir, tag + ".gen.rou.xml")
    cmd = [sumo_bin("duarouter"), "-n", args.net, "-r", trips_path, "-o", gen_rou,
           "--ignore-errors", "true", "--no-step-log", "true",
           "--routing-threads", "4", "--seed", str(args.seed)]
    subprocess.run(cmd, check=True, capture_output=True)

    # ---------------- loop demand: CCW ring (all left turns) ----------------
    # Ring corners B1 (SW) - E1 (SE) - E4 (NE) - B4 (NW), traversed CCW:
    #   bottom W->E, right S->N, top E->W, left N->S
    ring_nodes = (["B1", "C1", "D1", "E1"] +          # bottom, eastbound
                  ["E2", "E3", "E4"] +                 # right, northbound  (left turn at E1)
                  ["D4", "C4", "B4"] +                 # top, westbound     (left turn at E4)
                  ["B3", "B2"])                        # left, southbound   (left turn at B4)
    ring_edges = []
    for i in range(len(ring_nodes)):
        a = ring_nodes[i]
        b = ring_nodes[(i + 1) % len(ring_nodes)]
        eid = a + b
        assert eid in edges, "missing ring edge " + eid
        ring_edges.append(eid)

    # entry: fringe edge feeding the ring start node B1 -> reach ring via bottom0B0? use
    # explicit path from a fringe entry into B1, then n laps, then exit to a fringe sink.
    def path_edges(nodes):
        out = []
        for i in range(len(nodes) - 1):
            eid = nodes[i] + nodes[i + 1]
            assert eid in edges, "missing edge " + eid
            out.append(eid)
        return out

    # four staggered entry/exit spurs so the ring is fed from all four sides
    spurs = [
        (["left1", "A1", "B1"], 0),    # enters ring at B1 (index 0)
        (["bottom4", "E0", "E1"], 3),  # enters at E1
        (["right4", "F4", "E4"], 6),   # enters at E4
        (["top1", "B5", "B4"], 9),     # enters at B4
    ]
    exits = {
        0: ["B1", "A1", "left1"],
        3: ["E1", "E0", "bottom4"],
        6: ["E4", "F4", "right4"],
        9: ["B4", "B5", "top1"],
    }

    loop_routes = []
    for i in range(args.loop):
        spur_nodes, start_idx = spurs[i % len(spurs)]
        entry = path_edges(spur_nodes)
        ring_seq = []
        for _ in range(args.laps):
            for k in range(len(ring_edges)):
                ring_seq.append(ring_edges[(start_idx + k) % len(ring_edges)])
        exit_idx = start_idx  # exit where it entered, after completing whole laps
        ex = path_edges(exits[exit_idx])
        # ring_seq's last edge already ends at the ring node == exits[exit_idx][0]
        full = entry + ring_seq + ex[1:] if False else entry + ring_seq + path_edges(exits[exit_idx])
        dep = rng.uniform(0.0, args.load_end)
        loop_routes.append((dep, "loop.%d" % i, full))

    # ---------------- merge, sorted by depart ----------------
    gen_root = ET.parse(gen_rou).getroot()
    all_veh = []
    for v in gen_root.findall("vehicle"):
        r = v.find("route")
        all_veh.append((float(v.get("depart")), v.get("id"), r.get("edges").split()))
    for dep, vid, ed in loop_routes:
        all_veh.append((dep, vid, ed))
    all_veh.sort(key=lambda x: (x[0], x[1]))

    with open(args.out, "w") as fh:
        fh.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                 'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">\n')
        fh.write('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" '
                 'minGap="2.5" maxSpeed="13.89" tau="1.0"/>\n')
        for dep, vid, ed in all_veh:
            fh.write('    <vehicle id="%s" type="car" depart="%.2f" departLane="best" '
                     'departSpeed="max">\n' % (vid, dep))
            fh.write('        <route edges="%s"/>\n' % " ".join(ed))
            fh.write('    </vehicle>\n')
        fh.write("</routes>\n")

    print("wrote %s : %d vehicles (%d general routed, %d loop), ring=%s"
          % (args.out, len(all_veh), len(all_veh) - len(loop_routes), len(loop_routes),
             ",".join(ring_edges)))


if __name__ == "__main__":
    sys.exit(main())
