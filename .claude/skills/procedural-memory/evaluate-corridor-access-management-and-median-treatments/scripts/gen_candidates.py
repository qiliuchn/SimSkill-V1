#!/usr/bin/env python3
"""
Sub-goal 1 test rig: three candidate SUMO encodings of a continuous TWLTL
median, on ONE minimal shared geometry (2 driveway nodes, 150 m apart),
so the representation question can be settled before the full corridor
is built.

Geometry (shared by all three candidates):

    W(-150,0) --- D1(0,0) --- D2(150,0) --- E(300,0)
                    |  |         |  |
                   A1  B1       A2  B2      (driveway stubs, 30 m)

2 lanes/direction on the mainline (13.89 m/s = 50 km/h). A1/B1 are the two
driveway stubs at D1 (generic "left/right of the road", not committing to a
compass direction -- the point of this rig is to test the median TOPOLOGY,
not full lane-level geometric realism, which is handled later in the full
corridor build).

Candidate A: continuous coincident opposite-direction one-lane median edges
             (the work-zone skill's defensible shared-lane pattern), spanning
             the WHOLE rig (W..D1..D2..E), stitched through every node.
Candidate B: a single literal one-directional median lane (D1->D2 only),
             with connections attempted symmetrically for both directions --
             tests whether SUMO/netconvert will even accept the opposing
             direction's connection.
Candidate C: the same coincident-edge pattern as A, but DISCRETIZED into a
             short (~20 m) local pocket at EACH driveway independently, with
             plain undivided 2-lane mainline (no median) in between and
             beyond -- pockets are NOT stitched to each other.
"""
import os
import subprocess
import sys

SPEED = 13.89
LANES = 2
PRIO = 3


def node_line(nid, x, y, ntype="priority"):
    return f'  <node id="{nid}" x="{x:.2f}" y="{y:.2f}" type="{ntype}"/>\n'


def edge_line(eid, a, b, nl, speed=SPEED, prio=PRIO, shape=None, spread=None):
    s = f'  <edge id="{eid}" from="{a}" to="{b}" numLanes="{nl}" speed="{speed}" priority="{prio}"'
    if shape:
        s += f' shape="{shape}"'
    if spread:
        s += f' spreadType="{spread}"'
    return s + "/>\n"


def con_line(a, b, fl, tl):
    return f'  <connection from="{a}" to="{b}" fromLane="{fl}" toLane="{tl}"/>\n'


def write_all(outdir, nodes, edges, cons, extra_netconvert_args=None):
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/n.nod.xml", "w") as f:
        f.write("<nodes>\n" + "".join(nodes) + "</nodes>\n")
    with open(f"{outdir}/n.edg.xml", "w") as f:
        f.write("<edges>\n" + "".join(edges) + "</edges>\n")
    with open(f"{outdir}/n.con.xml", "w") as f:
        f.write("<connections>\n" + "".join(cons) + "</connections>\n")
    args = ["netconvert",
            "--node-files", f"{outdir}/n.nod.xml",
            "--edge-files", f"{outdir}/n.edg.xml",
            "--connection-files", f"{outdir}/n.con.xml",
            "--no-turnarounds", "true",
            "--junctions.corner-detail", "0",
            "--geometry.avoid-overlap", "false",
            "-o", f"{outdir}/net.net.xml"]
    if extra_netconvert_args:
        args += extra_netconvert_args
    r = subprocess.run(args, capture_output=True, text=True)
    with open(f"{outdir}/netconvert.log", "w") as f:
        f.write("CMD: " + " ".join(args) + "\n\n" + r.stdout + "\n" + r.stderr)
    return r.returncode, r.stdout + r.stderr


# ---------------------------------------------------------------- common ---
def base_nodes():
    return [
        node_line("W", -150, 0),
        node_line("D1", 0, 0),
        node_line("D2", 150, 0),
        node_line("E", 300, 0),
        node_line("A1", -8, 40),
        node_line("B1", 8, -40),
        node_line("A2", 142, 40),
        node_line("B2", 158, -40),
    ]


def base_mainline_edges():
    e = []
    e.append(edge_line("EB_W_D1", "W", "D1", LANES))
    e.append(edge_line("EB_D1_D2", "D1", "D2", LANES))
    e.append(edge_line("EB_D2_E", "D2", "E", LANES))
    e.append(edge_line("WB_E_D2", "E", "D2", LANES))
    e.append(edge_line("WB_D2_D1", "D2", "D1", LANES))
    e.append(edge_line("WB_D1_W", "D1", "W", LANES))
    return e


def driveway_edges():
    e = []
    for i, (dwy_a, dwy_b, node) in enumerate([("A1", "B1", "D1"), ("A2", "B2", "D2")]):
        e.append(edge_line(f"IN_{dwy_a}", node, dwy_a, 1))
        e.append(edge_line(f"OUT_{dwy_a}", dwy_a, node, 1))
        e.append(edge_line(f"IN_{dwy_b}", node, dwy_b, 1))
        e.append(edge_line(f"OUT_{dwy_b}", dwy_b, node, 1))
    return e


def base_mainline_cons():
    c = []
    for i in range(LANES):
        c.append(con_line("EB_W_D1", "EB_D1_D2", i, i))
        c.append(con_line("EB_D1_D2", "EB_D2_E", i, i))
        c.append(con_line("WB_E_D2", "WB_D2_D1", i, i))
        c.append(con_line("WB_D2_D1", "WB_D1_W", i, i))
    return c


def driveway_direct_cons():
    # right-in / right-out (no crossing needed): always legal in every candidate
    c = []
    c.append(con_line("WB_D2_D1", "IN_A1", 0, 0))
    c.append(con_line("OUT_A1", "WB_D1_W", 0, 0))
    c.append(con_line("EB_W_D1", "IN_B1", 0, 0))
    c.append(con_line("OUT_B1", "EB_D1_D2", 0, 0))
    c.append(con_line("WB_E_D2", "IN_A2", 0, 0))
    c.append(con_line("OUT_A2", "WB_D2_D1", 0, 0))
    c.append(con_line("EB_D1_D2", "IN_B2", 0, 0))
    c.append(con_line("OUT_B2", "EB_D2_E", 0, 0))
    return c


# ------------------------------------------------------------- candidate A -
def build_candA(outdir):
    nodes = base_nodes()
    edges = base_mainline_edges() + driveway_edges()
    # coincident median edges spanning the WHOLE rig, spreadType=center.
    # netconvert auto-spaces separate edge-pairs between the same two nodes
    # (here: mainline EB/WB vs. median EB/WB) even with avoid-overlap=false --
    # an explicit shape pinned to y=0 is required to force true coincidence
    # with the mainline centerline (verified: without it, compiled median
    # geometry landed at y=40, on top of the driveway stubs).
    coords = {"W": -150.0, "D1": 0.0, "D2": 150.0, "E": 300.0}
    med_segs = [("W", "D1"), ("D1", "D2"), ("D2", "E")]
    for a, b in med_segs:
        xa, xb = coords[a], coords[b]
        edges.append(edge_line(f"MED_EB_{a}_{b}", a, b, 1, spread="center",
                                shape=f"{xa:.2f},0.00 {xb:.2f},0.00"))
        edges.append(edge_line(f"MED_WB_{b}_{a}", b, a, 1, spread="center",
                                shape=f"{xb:.2f},0.00 {xa:.2f},0.00"))

    cons = base_mainline_cons() + driveway_direct_cons()
    # enter median (from inside/lane1 mainline) at every node that has an outgoing MED edge
    med_out_at = {"W": "MED_EB_W_D1", "D1": "MED_EB_D1_D2", "D2": "MED_EB_D2_E"}
    med_in_at = {"D1": "MED_EB_W_D1", "D2": "MED_EB_D1_D2", "E": "MED_EB_D2_E"}
    wmed_out_at = {"E": "MED_WB_E_D2", "D2": "MED_WB_D2_D1", "D1": "MED_WB_D1_W"}
    wmed_in_at = {"D2": "MED_WB_E_D2", "D1": "MED_WB_D2_D1", "W": "MED_WB_D1_W"}

    cons.append(con_line("EB_W_D1", med_out_at["D1"], 1, 0))
    cons.append(con_line("EB_D1_D2", med_out_at["D2"], 1, 0))
    cons.append(con_line("WB_E_D2", wmed_out_at["D2"], 1, 0))
    cons.append(con_line("WB_D2_D1", wmed_out_at["D1"], 1, 0))

    # exit median back to mainline
    cons.append(con_line(med_in_at["D1"], "EB_D1_D2", 0, 1))
    cons.append(con_line(med_in_at["D2"], "EB_D2_E", 0, 1))
    cons.append(con_line(wmed_in_at["D2"], "WB_D2_D1", 0, 1))
    cons.append(con_line(wmed_in_at["D1"], "WB_D1_W", 0, 1))

    # median <-> driveway (the actual left-turn-in / left-turn-out via refuge)
    cons.append(con_line(wmed_in_at["D1"], "IN_A1", 0, 0))
    cons.append(con_line(wmed_in_at["D1"], "IN_B1", 0, 0))
    cons.append(con_line("OUT_A1", med_out_at["D1"], 0, 0))
    cons.append(con_line("OUT_B1", med_out_at["D1"], 0, 0))

    cons.append(con_line(med_in_at["D2"], "IN_A2", 0, 0))
    cons.append(con_line(med_in_at["D2"], "IN_B2", 0, 0))
    cons.append(con_line("OUT_A2", wmed_out_at["D2"], 0, 0))
    cons.append(con_line("OUT_B2", wmed_out_at["D2"], 0, 0))

    return write_all(outdir, nodes, edges, cons)


# ------------------------------------------------------------- candidate B -
def build_candB(outdir):
    nodes = base_nodes()
    edges = base_mainline_edges() + driveway_edges()
    edges.append(edge_line("MED", "D1", "D2", 1, spread="center", shape="0.00,0.00 150.00,0.00"))
    cons = base_mainline_cons() + driveway_direct_cons()
    # EB direction: enter at D1, exit/peel at D2 -- topologically fine
    cons.append(con_line("EB_W_D1", "MED", 1, 0))
    cons.append(con_line("MED", "EB_D2_E", 0, 1))
    cons.append(con_line("MED", "IN_A2", 0, 0))
    cons.append(con_line("MED", "IN_B2", 0, 0))
    cons.append(con_line("OUT_A2", "EB_D2_E", 0, 1))  # driveway exits east directly (not via MED)
    # WB direction: ATTEMPT the symmetric connections a naive modeler would
    # try -- entering MED "from the D2 end" and exiting "at the D1 end" the
    # same way candidate A does for its WB coincident edge. MED only starts
    # at D1 and ends at D2, so these are attempts to attach at the WRONG
    # node (MED does not originate at D2, is not incident there as an
    # outgoing edge). This is the literal single-lane test.
    cons.append(con_line("WB_E_D2", "MED", 1, 0))     # <- expected to fail: MED not outgoing at D2
    cons.append(con_line("MED", "WB_D1_W", 0, 1))       # <- expected to fail: MED not incoming at D1
    cons.append(con_line("MED", "IN_A1", 0, 0))         # <- expected to fail
    cons.append(con_line("MED", "IN_B1", 0, 0))         # <- expected to fail
    return write_all(outdir, nodes, edges, cons)


# ------------------------------------------------------------- candidate C -
def build_candC(outdir):
    # Insert short (10 m each side) pocket-boundary nodes flanking D1 and D2.
    nodes = [
        node_line("W", -150, 0),
        node_line("D1u", -10, 0), node_line("D1", 0, 0), node_line("D1d", 10, 0),
        node_line("D2u", 140, 0), node_line("D2", 150, 0), node_line("D2d", 160, 0),
        node_line("E", 300, 0),
        node_line("A1", -8, 40), node_line("B1", 8, -40),
        node_line("A2", 142, 40), node_line("B2", 158, -40),
    ]
    edges = [
        edge_line("EB_W_D1u", "W", "D1u", LANES),
        edge_line("EB_D1d_D2u", "D1d", "D2u", LANES),
        edge_line("EB_D2d_E", "D2d", "E", LANES),
        edge_line("WB_E_D2d", "E", "D2d", LANES),
        edge_line("WB_D2u_D1d", "D2u", "D1d", LANES),
        edge_line("WB_D1u_W", "D1u", "W", LANES),
        # through-mainline across the pocket zone (bypass, for non-turning traffic)
        edge_line("EB_D1u_D1d", "D1u", "D1d", LANES),
        edge_line("WB_D1d_D1u", "D1d", "D1u", LANES),
        edge_line("EB_D2u_D2d", "D2u", "D2d", LANES),
        edge_line("WB_D2d_D2u", "D2d", "D2u", LANES),
        # LOCAL coincident median pocket, split at the driveway attach node.
        # Explicit shape pinned to y=0, same fix as candidate A (see there).
        edge_line("MED_EB_D1u_D1", "D1u", "D1", 1, spread="center", shape="-10.00,0.00 0.00,0.00"),
        edge_line("MED_EB_D1_D1d", "D1", "D1d", 1, spread="center", shape="0.00,0.00 10.00,0.00"),
        edge_line("MED_WB_D1d_D1", "D1d", "D1", 1, spread="center", shape="10.00,0.00 0.00,0.00"),
        edge_line("MED_WB_D1_D1u", "D1", "D1u", 1, spread="center", shape="0.00,0.00 -10.00,0.00"),
        edge_line("MED_EB_D2u_D2", "D2u", "D2", 1, spread="center", shape="140.00,0.00 150.00,0.00"),
        edge_line("MED_EB_D2_D2d", "D2", "D2d", 1, spread="center", shape="150.00,0.00 160.00,0.00"),
        edge_line("MED_WB_D2d_D2", "D2d", "D2", 1, spread="center", shape="160.00,0.00 150.00,0.00"),
        edge_line("MED_WB_D2_D2u", "D2", "D2u", 1, spread="center", shape="150.00,0.00 140.00,0.00"),
    ] + driveway_edges()

    cons = []
    for i in range(LANES):
        cons.append(con_line("EB_W_D1u", "EB_D1u_D1d", i, i))
        cons.append(con_line("EB_D1d_D2u", "EB_D2u_D2d", i, i))
        cons.append(con_line("EB_D2d_E", "EB_D2d_E", i, i)) if False else None
        cons.append(con_line("WB_E_D2d", "WB_D2d_D2u", i, i))
        cons.append(con_line("WB_D2u_D1d", "WB_D1d_D1u", i, i))
        cons.append(con_line("WB_D1u_W", "WB_D1u_W", i, i)) if False else None
        cons.append(con_line("EB_D1u_D1d", "EB_D1d_D2u", i, i))
        cons.append(con_line("WB_D1d_D1u", "WB_D1u_W", i, i))
        cons.append(con_line("EB_D2u_D2d", "EB_D2d_E", i, i))
        cons.append(con_line("WB_D2d_D2u", "WB_D2u_D1d", i, i))
    cons = [c for c in cons if c]

    # right-in / right-out direct, at the driveway-attach node of each pocket
    cons.append(con_line("WB_D2u_D1d", "IN_A1", 0, 0)) if False else None
    # (kept minimal/symmetric with candidate A: driveways only reachable via
    #  the local pocket median, matching a true TWLTL where ALL driveway
    #  turns -- including the "direct" side -- cross at least one opposing
    #  lane in this 2-lane-per-direction cross-section; right-in/out direct
    #  connections are added in the full corridor build for the undivided
    #  arm, not needed here.)

    # pocket median <-> mainline, and median <-> driveway, at D1
    cons.append(con_line("EB_W_D1u", "MED_EB_D1u_D1", 1, 0))
    cons.append(con_line("MED_EB_D1_D1d", "EB_D1d_D2u", 0, 1))
    cons.append(con_line("MED_EB_D1u_D1", "MED_EB_D1_D1d", 0, 0))  # straight through pocket
    cons.append(con_line("WB_D2u_D1d", "MED_WB_D1d_D1", 1, 0))
    cons.append(con_line("MED_WB_D1_D1u", "WB_D1u_W", 0, 1))
    cons.append(con_line("MED_WB_D1d_D1", "MED_WB_D1_D1u", 0, 0))
    cons.append(con_line("MED_WB_D1d_D1", "IN_A1", 0, 0))
    cons.append(con_line("MED_WB_D1d_D1", "IN_B1", 0, 0))
    cons.append(con_line("OUT_A1", "MED_EB_D1_D1d", 0, 0))
    cons.append(con_line("OUT_B1", "MED_EB_D1_D1d", 0, 0))

    # pocket median <-> mainline, and median <-> driveway, at D2
    cons.append(con_line("EB_D1d_D2u", "MED_EB_D2u_D2", 1, 0))
    cons.append(con_line("MED_EB_D2_D2d", "EB_D2d_E", 0, 1))
    cons.append(con_line("MED_EB_D2u_D2", "MED_EB_D2_D2d", 0, 0))
    cons.append(con_line("WB_E_D2d", "MED_WB_D2d_D2", 1, 0))
    cons.append(con_line("MED_WB_D2_D2u", "WB_D2u_D1d", 0, 1))
    cons.append(con_line("MED_WB_D2d_D2", "MED_WB_D2_D2u", 0, 0))
    cons.append(con_line("MED_WB_D2d_D2", "IN_A2", 0, 0))
    cons.append(con_line("MED_WB_D2d_D2", "IN_B2", 0, 0))
    cons.append(con_line("OUT_A2", "MED_EB_D2_D2d", 0, 0))
    cons.append(con_line("OUT_B2", "MED_EB_D2_D2d", 0, 0))

    return write_all(outdir, nodes, edges, cons)


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    for name, fn in [("candA", build_candA), ("candB", build_candB), ("candC", build_candC)]:
        rc, log = fn(os.path.join(root, name))
        print(f"=== {name}: netconvert returncode={rc} ===")
        # print only warnings/errors, not the full log
        for line in log.splitlines():
            if "arning" in line or "rror" in line:
                print("   ", line)
