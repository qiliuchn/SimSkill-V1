#!/usr/bin/env python3
"""Build the radial suburban -> CBD park-and-ride corridor network.

Layout (metres, x east, y north):

  suburban dispersed grid (600 m spacing)   arterial (2 lanes, 22.2 m/s)   CBD grid (400 m, signalised)
  x = 200 .. 1400                            x = 2200 .. 6400              x = 6400 .. 7600
  ------------------------------------------------------------------------------------------------
  BRT / rail busway at y = +250, physically SEPARATE from the road network
  (allow="bus" only), reached by pedestrians through <access> on each stop.

Outputs <out-dir>/corridor.net.xml plus the plain-xml sources.
"""
import argparse
import os
import subprocess
import sys

# ---------------------------------------------------------------- geometry ---
SUB_COLS = [200.0, 800.0, 1400.0]
SUB_ROWS = [-600.0, 0.0, 600.0]
ST_X = 2200.0
ART_X = [3400.0, 4600.0, 5800.0]          # A0, A1(intermediate P+R station), A2
CBD_COLS = [6400.0, 6800.0, 7200.0, 7600.0]
CBD_ROWS = [-400.0, 0.0, 400.0]
BW_Y = 250.0

SUB_SPEED = 13.89
ART_SPEED = 22.22
CBD_SPEED = 13.89
BW_SPEED = 22.22


def nid_sub(i, j):
    return "SUB%d%d" % (i, j)


def nid_cbd(i, j):
    return "CBD%d%d" % (i, j)


def build_xml(out_dir):
    nodes, edges = [], []

    def node(nid, x, y, typ="priority"):
        nodes.append('    <node id="%s" x="%.2f" y="%.2f" type="%s"/>' % (nid, x, y, typ))

    def edge(frm, to, lanes, speed, allow=None, prio=1):
        eid = "%s_%s" % (frm, to)
        extra = ' allow="%s"' % allow if allow else ""
        edges.append('    <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f" priority="%d"%s/>'
                     % (eid, frm, to, lanes, speed, prio, extra))
        return eid

    def bidir(frm, to, lanes, speed, allow=None, prio=1):
        return edge(frm, to, lanes, speed, allow, prio), edge(to, frm, lanes, speed, allow, prio)

    # --- suburban dispersed grid -------------------------------------------
    for i, x in enumerate(SUB_COLS):
        for j, y in enumerate(SUB_ROWS):
            node(nid_sub(i, j), x, y)
    sub_edges = []
    for i in range(len(SUB_COLS)):
        for j in range(len(SUB_ROWS)):
            if i + 1 < len(SUB_COLS):
                sub_edges += list(bidir(nid_sub(i, j), nid_sub(i + 1, j), 1, SUB_SPEED))
            if j + 1 < len(SUB_ROWS):
                sub_edges += list(bidir(nid_sub(i, j), nid_sub(i, j + 1), 1, SUB_SPEED))

    # --- suburban station node + collector ---------------------------------
    node("ST", ST_X, 0.0)
    bidir(nid_sub(2, 1), "ST", 2, SUB_SPEED, prio=2)
    # dead-end stub off ST holding the overflow lot
    node("STLOT", ST_X + 40.0, -250.0)
    bidir("ST", "STLOT", 1, SUB_SPEED)

    # --- arterial ----------------------------------------------------------
    art_nodes = ["ST"]
    for k, x in enumerate(ART_X):
        n = "A%d" % k
        node(n, x, 0.0)
        art_nodes.append(n)
    art_nodes.append(nid_cbd(0, 1))
    node(nid_cbd(0, 1), CBD_COLS[0], CBD_ROWS[1], "traffic_light")
    art_edges = []
    for a, b in zip(art_nodes[:-1], art_nodes[1:]):
        art_edges += list(bidir(a, b, 2, ART_SPEED, prio=3))

    # --- CBD grid ----------------------------------------------------------
    for i in range(len(CBD_COLS)):
        for j in range(len(CBD_ROWS)):
            if (i, j) == (0, 1):
                continue
            node(nid_cbd(i, j), CBD_COLS[i], CBD_ROWS[j], "traffic_light")
    cbd_edges = []
    for i in range(len(CBD_COLS)):
        for j in range(len(CBD_ROWS)):
            if i + 1 < len(CBD_COLS):
                cbd_edges += list(bidir(nid_cbd(i, j), nid_cbd(i + 1, j), 1, CBD_SPEED))
            if j + 1 < len(CBD_ROWS):
                cbd_edges += list(bidir(nid_cbd(i, j), nid_cbd(i, j + 1), 1, CBD_SPEED))

    # --- busway (separate component, bus only) -----------------------------
    bw = [("BW_W", 1800.0), ("BW_ST", ST_X), ("BW_MID", ART_X[1]),
          ("BW_CG", CBD_COLS[0]), ("BW_CC", CBD_COLS[2]), ("BW_E", CBD_COLS[3] + 200.0)]
    for n, x in bw:
        node(n, x, BW_Y)
    bw_edges = []
    for (a, _), (b, _) in zip(bw[:-1], bw[1:]):
        bw_edges += list(bidir(a, b, 1, BW_SPEED, allow="bus"))

    os.makedirs(out_dir, exist_ok=True)
    nod = os.path.join(out_dir, "corridor.nod.xml")
    edg = os.path.join(out_dir, "corridor.edg.xml")
    with open(nod, "w") as f:
        f.write('<nodes>\n' + "\n".join(nodes) + '\n</nodes>\n')
    with open(edg, "w") as f:
        f.write('<edges>\n' + "\n".join(edges) + '\n</edges>\n')
    return nod, edg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    nod, edg = build_xml(args.out_dir)
    net = os.path.join(args.out_dir, "corridor.net.xml")
    cmd = ["netconvert", "-n", nod, "-e", edg, "-o", net,
           "--sidewalks.guess", "--sidewalks.guess.max-speed", "30",
           "--crossings.guess", "--walkingareas",
           "--tls.default-type", "static", "--tls.guess-signals",
           "--no-turnarounds.tls", "true",
           "--junctions.corner-detail", "5",
           "--default.junctions.keep-clear", "true"]
    print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit(r.returncode)
    print("wrote", net)


if __name__ == "__main__":
    main()
