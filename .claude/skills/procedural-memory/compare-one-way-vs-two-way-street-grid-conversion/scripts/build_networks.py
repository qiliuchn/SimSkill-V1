#!/usr/bin/env python3
"""Build three grid-network variants for the one-way vs two-way study.

Common base geometry (all variants identical):
  * N x N junction lattice (default 5x5) at 200 m spacing, all traffic_light
  * 200 m boundary "access stub" at every perimeter junction, one per perimeter
    street end (20 stubs for a 5x5 grid)

Variants:
  A  twoway      every street bidirectional, 1 lane per direction  -> 2 lanes/cross-section
  B  oneway_fair alternating one-way pairs,  2 lanes one direction -> 2 lanes/cross-section
  C  oneway_naive alternating one-way pairs, 1 lane one direction  -> 1 lane/cross-section (UNFAIR)

One-way pattern (variant B and C):
  row j (E-W street):  j even -> eastbound,   j odd -> westbound
  col i (N-S street):  i even -> northbound,  i odd -> southbound

Stub edge IDs are IDENTICAL across variants so a single trips file routes on all
three.  Stub direction in B/C follows the street direction, so a stub is either
an entry (`in_*`) or an exit (`out_*`).  Variant A gets BOTH `in_*` and `out_*`
at every stub (a two-way access road), which is what keeps total lane count
equal: A stub = 1 lane in + 1 lane out; B stub = 2 lanes in one direction.
"""
import argparse
import os
import subprocess
import sys

SPACING = 200.0
STUB_LEN = 200.0
SPEED = 13.89  # m/s  (~50 km/h) -- netgenerate/netconvert default, in m/s not km/h


def node_id(i, j):
    return "J%d_%d" % (i, j)


def row_eastbound(j):
    return j % 2 == 0


def col_northbound(i):
    return i % 2 == 0


def build(variant, n, outdir):
    """Write <variant>.nod.xml / <variant>.edg.xml / <variant>.netccfg."""
    os.makedirs(outdir, exist_ok=True)
    nodes = []
    edges = []

    # --- lane allocation -----------------------------------------------------
    if variant == "twoway":
        lanes_fwd = lanes_bwd = 1          # total cross-section = 2
    elif variant == "oneway_fair":
        lanes_fwd, lanes_bwd = 2, 0        # total cross-section = 2 (EQUAL to A)
    elif variant == "oneway_naive":
        lanes_fwd, lanes_bwd = 1, 0        # total cross-section = 1 (HALF of A)
    else:
        raise ValueError(variant)

    # --- grid junctions ------------------------------------------------------
    for i in range(n):
        for j in range(n):
            nodes.append((node_id(i, j), i * SPACING, j * SPACING, "traffic_light"))

    def add_edge(eid, frm, to, nl):
        edges.append((eid, frm, to, nl))

    # --- E-W street segments -------------------------------------------------
    for j in range(n):
        for i in range(n - 1):
            a, b = node_id(i, j), node_id(i + 1, j)
            e_id = "EW_%d_%d_E" % (j, i)      # eastbound segment id
            w_id = "EW_%d_%d_W" % (j, i)      # westbound segment id
            if variant == "twoway":
                add_edge(e_id, a, b, 1)
                add_edge(w_id, b, a, 1)
            else:
                if row_eastbound(j):
                    add_edge(e_id, a, b, lanes_fwd)
                else:
                    add_edge(w_id, b, a, lanes_fwd)

    # --- N-S street segments -------------------------------------------------
    for i in range(n):
        for j in range(n - 1):
            a, b = node_id(i, j), node_id(i, j + 1)
            n_id = "NS_%d_%d_N" % (i, j)
            s_id = "NS_%d_%d_S" % (i, j)
            if variant == "twoway":
                add_edge(n_id, a, b, 1)
                add_edge(s_id, b, a, 1)
            else:
                if col_northbound(i):
                    add_edge(n_id, a, b, lanes_fwd)
                else:
                    add_edge(s_id, b, a, lanes_fwd)

    # --- boundary access stubs ----------------------------------------------
    # stub label -> (stub node coords, attached grid junction, inbound-direction
    #                is "into the grid")
    stubs = []
    for j in range(n):
        stubs.append(("W%d" % j, (-STUB_LEN, j * SPACING), node_id(0, j),
                      "E" if row_eastbound(j) else "W", "ew", j))
        stubs.append(("E%d" % j, ((n - 1) * SPACING + STUB_LEN, j * SPACING),
                      node_id(n - 1, j), "E" if row_eastbound(j) else "W", "ew", j))
    for i in range(n):
        stubs.append(("S%d" % i, (i * SPACING, -STUB_LEN), node_id(i, 0),
                      "N" if col_northbound(i) else "S", "ns", i))
        stubs.append(("N%d" % i, (i * SPACING, (n - 1) * SPACING + STUB_LEN),
                      node_id(i, n - 1), "N" if col_northbound(i) else "S", "ns", i))

    entries, exits = [], []
    for label, (x, y), gj, sdir, axis, _idx in stubs:
        nodes.append(("STUB_" + label, x, y, "priority"))
        sn = "STUB_" + label
        # does the one-way street direction point INTO the grid at this stub?
        if axis == "ew":
            into = (label[0] == "W" and sdir == "E") or (label[0] == "E" and sdir == "W")
        else:
            into = (label[0] == "S" and sdir == "N") or (label[0] == "N" and sdir == "S")
        if variant == "twoway":
            add_edge("in_" + label, sn, gj, 1)
            add_edge("out_" + label, gj, sn, 1)
        else:
            if into:
                add_edge("in_" + label, sn, gj, lanes_fwd)
            else:
                add_edge("out_" + label, gj, sn, lanes_fwd)
        (entries if into else exits).append(label)

    # --- write plain XML -----------------------------------------------------
    nod = os.path.join(outdir, "%s.nod.xml" % variant)
    edg = os.path.join(outdir, "%s.edg.xml" % variant)
    cfg = os.path.join(outdir, "%s.netccfg" % variant)
    net = os.path.join(outdir, "%s.net.xml" % variant)

    with open(nod, "w") as f:
        f.write('<nodes>\n')
        for nid, x, y, t in nodes:
            f.write('    <node id="%s" x="%.2f" y="%.2f" type="%s"/>\n' % (nid, x, y, t))
        f.write('</nodes>\n')

    with open(edg, "w") as f:
        f.write('<edges>\n')
        for eid, frm, to, nl in edges:
            f.write('    <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f"'
                    ' priority="%d"/>\n' % (eid, frm, to, nl, SPEED,
                                            2 if eid.startswith(("EW", "NS")) else 1))
        f.write('</edges>\n')

    with open(cfg, "w") as f:
        f.write('<configuration>\n'
                '    <input>\n'
                '        <node-files value="%s"/>\n'
                '        <edge-files value="%s"/>\n'
                '    </input>\n'
                '    <output>\n'
                '        <output-file value="%s"/>\n'
                '    </output>\n'
                '    <processing>\n'
                '        <no-turnarounds value="true"/>\n'
                '        <no-internal-links value="false"/>\n'
                '    </processing>\n'
                '    <tls_building>\n'
                '        <tls.default-type value="static"/>\n'
                '    </tls_building>\n'
                '</configuration>\n' % (os.path.basename(nod), os.path.basename(edg),
                                        os.path.basename(net)))

    subprocess.run(["netconvert", "-c", os.path.basename(cfg)], cwd=outdir, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return net, sorted(entries), sorted(exits)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--outdir", required=True)
    p.add_argument("-n", "--number", type=int, default=5)
    a = p.parse_args()
    for v in ("twoway", "oneway_fair", "oneway_naive"):
        net, ent, ex = build(v, a.number, os.path.join(a.outdir, v))
        print(v, "->", net)
        print("   entries:", ",".join(ent))
        print("   exits  :", ",".join(ex))
