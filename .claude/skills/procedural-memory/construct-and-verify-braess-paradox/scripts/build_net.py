#!/usr/bin/env python3
"""
Build the two Braess network variants (NOLINK / LINK) from plain XML via netconvert.

Topology (classic Braess):

                     SA_a(3ln)   A1  SA_b(1ln)        AT (3ln, 4800m, 20m/s)
   S0 --S_in--> S ==========================> A ------------------------------> T --T_out--> T1
                 \                             |                               ^
                  \  SB (3ln, 4800m, 20m/s)    | AB  (cross link, LINK only)   |
                   \                           v                               |
                    ----------------------->   B =========================> B1 -
                                                  BT_a(3ln)     BT_b(1ln)

  * FLOW-DEPENDENT links: S->A (SA_a + SA_b) and B->T (BT_a + BT_b)
      short, ending in a 1-lane low-speed bottleneck  -> LOW capacity, steep t(q);
      3-lane upstream section provides queue storage so the queue stays in-network.
  * FLOW-INDEPENDENT links: S->B (SB) and A->T (AT)
      long, 3 lanes, high speed -> capacity far above any demand -> t(q) ~ constant.
  * CROSS link A->B (AB): short, 3 lanes, fast -> nearly costless.
  * S_in / T_out: common origin / destination edges so every route shares the same OD
    edge pair (required by duarouter / duaIterate).

Every place where parallel routes merge (A1, B, B1, T) uses junction type "zipper" rather
than "priority" -- per the compute-dynamic-user-equilibrium skill, a priority merge injects
spurious asymmetric congestion unrelated to the routes' own capacity.

Connections are specified explicitly so that (a) the whole width of the storage edge feeds
the 1-lane bottleneck (otherwise netconvert wires only one lane through and the storage is
useless), and (b) the shared part of the topology is bit-identical between the two variants.
"""
import os
import subprocess
import sys
import shutil

NODES = [
    ("S0", -400.0, 0.0, "priority"),
    ("S", 0.0, 0.0, "priority"),      # diverge S -> {SA_a, SB}
    ("A1", 450.0, 330.0, "zipper"),   # 3-lane -> 1-lane bottleneck merge
    ("A", 700.0, 500.0, "priority"),  # diverge A -> {AT, AB}
    ("B", 700.0, -500.0, "zipper"),   # merge {SB, AB} -> BT_a
    ("B1", 1150.0, -330.0, "zipper"), # 3-lane -> 1-lane bottleneck merge
    ("T", 1600.0, 0.0, "zipper"),     # merge {AT, BT_b} -> T_out
    ("T1", 2000.0, 0.0, "priority"),
]

V_FAST = 20.0     # m/s (72 km/h) flow-independent + access edges
V_MED = 13.89     # m/s (50 km/h) wide storage part of the flow-dependent links
V_SLOW = 8.33     # m/s (30 km/h) 1-lane bottleneck -> sets the flow-dependent link capacity

# id, from, to, numLanes, speed, length
EDGES = [
    ("S_in", "S0", "S", 6, V_FAST, 400.0),   # 6 lanes: 3 dedicated to each branch (see CONNS)
    ("SA_a", "S", "A1", 3, V_MED, 500.0),     # flow-dependent link S->A, storage part
    ("SA_b", "A1", "A", 1, V_SLOW, 250.0),    # flow-dependent link S->A, bottleneck part
    ("AT", "A", "T", 3, V_FAST, 4800.0),      # flow-INdependent link A->T
    ("SB", "S", "B", 3, V_FAST, 4800.0),      # flow-INdependent link S->B
    ("BT_a", "B", "B1", 3, V_MED, 500.0),     # flow-dependent link B->T, storage part
    ("BT_b", "B1", "T", 1, V_SLOW, 250.0),    # flow-dependent link B->T, bottleneck part
    ("T_out", "T", "T1", 4, V_FAST, 400.0),
]
CROSS_EDGE = ("AB", "A", "B", 3, V_FAST, 400.0)   # LINK variant only

# from, fromLane, to, toLane   (shared by both variants)
CONNS = [
    # S diverge: SB is the RIGHT branch (SE), SA_a the LEFT branch (NE). Giving each branch
    # its own dedicated, side-correct lane group is essential -- letting every S_in lane feed
    # both branches makes the internal links geometrically CROSS, which netconvert turns into
    # a yielding conflict that throttles the diverge to ~1700 veh/h (measured).
    ("S_in", 0, "SB", 0), ("S_in", 1, "SB", 1), ("S_in", 2, "SB", 2),
    ("S_in", 3, "SA_a", 0), ("S_in", 4, "SA_a", 1), ("S_in", 5, "SA_a", 2),
    ("SA_a", 0, "SA_b", 0), ("SA_a", 1, "SA_b", 0), ("SA_a", 2, "SA_b", 0),
    ("SA_b", 0, "AT", 0), ("SA_b", 0, "AT", 1), ("SA_b", 0, "AT", 2),
    ("SB", 0, "BT_a", 0), ("SB", 1, "BT_a", 1), ("SB", 2, "BT_a", 2),
    ("BT_a", 0, "BT_b", 0), ("BT_a", 1, "BT_b", 0), ("BT_a", 2, "BT_b", 0),
    ("AT", 0, "T_out", 0), ("AT", 1, "T_out", 1), ("AT", 2, "T_out", 2),
    ("BT_b", 0, "T_out", 3),
]
CROSS_CONNS = [
    ("SA_b", 0, "AB", 0), ("SA_b", 0, "AB", 1), ("SA_b", 0, "AB", 2),
    ("AB", 0, "BT_a", 0), ("AB", 1, "BT_a", 1), ("AB", 2, "BT_a", 2),
]


def find_netconvert():
    p = shutil.which("netconvert")
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        cand = os.path.join(os.path.dirname(sumo), "netconvert")
        if os.path.exists(cand):
            return cand
    cand = os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "netconvert")
    if os.path.exists(cand):
        return cand
    raise SystemExit("netconvert not found")


def write_plain(out_dir, variant):
    os.makedirs(out_dir, exist_ok=True)
    nod = os.path.join(out_dir, f"braess_{variant}.nod.xml")
    edg = os.path.join(out_dir, f"braess_{variant}.edg.xml")
    con = os.path.join(out_dir, f"braess_{variant}.con.xml")
    is_link = variant == "link"
    edges = list(EDGES) + ([CROSS_EDGE] if is_link else [])
    conns = list(CONNS) + (CROSS_CONNS if is_link else [])
    with open(nod, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n')
        for nid, x, y, t in NODES:
            f.write(f'    <node id="{nid}" x="{x}" y="{y}" type="{t}"/>\n')
        f.write("</nodes>\n")
    with open(edg, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n')
        for eid, a, b, nl, sp, ln in edges:
            f.write(f'    <edge id="{eid}" from="{a}" to="{b}" numLanes="{nl}" '
                    f'speed="{sp}" length="{ln}" priority="1"/>\n')
        f.write("</edges>\n")
    with open(con, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<connections>\n')
        for a, fl, b, tl in conns:
            f.write(f'    <connection from="{a}" fromLane="{fl}" to="{b}" toLane="{tl}"/>\n')
        f.write("</connections>\n")
    return nod, edg, con


def build(out_dir, variant):
    nod, edg, con = write_plain(out_dir, variant)
    net = os.path.join(out_dir, f"braess_{variant}.net.xml")
    cmd = [find_netconvert(), "-n", nod, "-e", edg, "-x", con, "-o", net,
           "--no-turnarounds", "true",
           "--offset.disable-normalization", "true",
           "--no-internal-links", "false",
           # disable the turning-radius speed limit on internal links: the bends at S/A/B/T
           # are an artefact of the schematic layout, not a design feature, and would inject
           # asymmetric junction delay between the two variants.
           "--junctions.limit-turn-speed", "-1",
           "--default.junctions.keep-clear", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"netconvert failed for {variant}")
    if r.stderr.strip():
        print(f"[{variant}] netconvert stderr:\n{r.stderr.strip()}")
    return net


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for v in ("nolink", "link"):
        print("built", build(out, v))
