#!/usr/bin/env python3
"""
Build a directional freeway corridor (~10 km) with:
  - 3-lane mainline, lane drop 3->2 at x=8600 (recurrent downstream bottleneck, zipper node)
  - 3 metered on-ramps (zipper merges) at x=2000, 5000, 7500
  - 2 off-ramps (priority diverges) at x=3800, 6300
  - EVERY on-ramp fed by a SIGNALIZED SURFACE RAMP TERMINAL with a storage-limited
    ramp segment between the terminal stop bar and the ramp meter, so ramp-queue
    spillback into the surface network is physically representable, not assumed.

Hand-authored plain XML -> netconvert (netgenerate cannot express this geometry).
Follows `implement-alinea-ramp-metering` (zipper merge + explicit .con.xml) and
`build-diamond-interchange-with-signal-offset-spillback` (distinct z, no shared
node between freeway and surface street; genuine tlLogic ramp terminals).

Usage: build_corridor.py OUTDIR [--stor L1 L2 L3]
"""
import argparse
import os
import subprocess
import sys

ML_SPEED = 33.33          # 120 km/h mainline
RAMP_SPEED = 16.67        # 60 km/h ramp storage segment
MERGE_SPEED = 22.22       # 80 km/h acceleration lane
SURF_SPEED = 13.89        # 50 km/h surface arterial

X_START, X_END = 0.0, 10000.0
X_R1, X_OFF1, X_R2, X_OFF2, X_R3, X_DROP = 2000., 3800., 5000., 6300., 7500., 8600.
MERGE_LEN = 220.0
SURF_APPROACH = 700.0
CROSS_LEG = 240.0
Y_ART = -300.0            # surface arterial y
Y_MET = -40.0             # ramp meter y

RAMPS = [("r1", X_R1), ("r2", X_R2), ("r3", X_R3)]
OFFRAMPS = [("o1", X_OFF1), ("o2", X_OFF2)]
ML_NODES = [("m_start", X_START, "priority"), ("m_r1", X_R1, "zipper"),
            ("m_o1", X_OFF1, "priority"), ("m_r2", X_R2, "zipper"),
            ("m_o2", X_OFF2, "priority"), ("m_r3", X_R3, "zipper"),
            ("m_drop", X_DROP, "zipper"), ("m_end", X_END, "priority")]


def shp(pts):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)


def build(outdir, stor):
    os.makedirs(outdir, exist_ok=True)
    nodes, edges, cons = [], [], []

    for nid, x, t in ML_NODES:
        nodes.append(f'<node id="{nid}" x="{x}" y="0" z="0.0" type="{t}"/>')

    seq = [n[0] for n in ML_NODES]
    ml_edges = []
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        eid = f"ml_{i}"
        nl = 2 if a == "m_drop" else 3
        edges.append(f'<edge id="{eid}" from="{a}" to="{b}" numLanes="{nl}" '
                     f'speed="{ML_SPEED}" priority="20" spreadType="center"/>')
        ml_edges.append((eid, a, b, nl))
    up_of = {b: e for e, a, b, _ in ml_edges}
    dn_of = {a: e for e, a, b, _ in ml_edges}

    for i in range(len(ml_edges) - 1):
        e0, _, _, nl0 = ml_edges[i]
        e1, _, _, nl1 = ml_edges[i + 1]
        if nl0 == nl1:
            for l in range(nl0):
                cons.append(f'<connection from="{e0}" to="{e1}" fromLane="{l}" toLane="{l}"/>')
        else:  # 3 -> 2 lane drop, zipper on downstream lane 1
            cons.append(f'<connection from="{e0}" to="{e1}" fromLane="0" toLane="0"/>')
            cons.append(f'<connection from="{e0}" to="{e1}" fromLane="1" toLane="1"/>')
            cons.append(f'<connection from="{e0}" to="{e1}" fromLane="2" toLane="1"/>')

    for oid, x in OFFRAMPS:
        nodes.append(f'<node id="{oid}_end" x="{x + 500:.1f}" y="-160" z="0.0" type="priority"/>')
        edges.append(f'<edge id="{oid}_off" from="m_{oid}" to="{oid}_end" numLanes="1" '
                     f'speed="{MERGE_SPEED}" priority="1" '
                     f'shape="{shp([(x, 0), (x + 220, -60), (x + 500, -160)])}"/>')
        cons.append(f'<connection from="{up_of["m_" + oid]}" to="{oid}_off" fromLane="0" toLane="0"/>')

    for (rid, x), L in zip(RAMPS, stor):
        xm = x - MERGE_LEN
        xt = xm - L
        nodes.append(f'<node id="{rid}_met" x="{xm:.1f}" y="{Y_MET}" z="0.0" type="traffic_light"/>')
        nodes.append(f'<node id="{rid}_term" x="{xt:.1f}" y="{Y_ART}" z="0.0" type="traffic_light"/>')
        nodes.append(f'<node id="{rid}_sw" x="{xt - SURF_APPROACH:.1f}" y="{Y_ART}" z="0.0" type="priority"/>')
        nodes.append(f'<node id="{rid}_se" x="{xt + SURF_APPROACH:.1f}" y="{Y_ART}" z="0.0" type="priority"/>')
        nodes.append(f'<node id="{rid}_cn" x="{xt:.1f}" y="{Y_ART + CROSS_LEG:.1f}" z="0.0" type="priority"/>')
        nodes.append(f'<node id="{rid}_cs" x="{xt:.1f}" y="{Y_ART - CROSS_LEG:.1f}" z="0.0" type="priority"/>')

        edges.append(f'<edge id="{rid}_sapp" from="{rid}_sw" to="{rid}_term" numLanes="2" '
                     f'speed="{SURF_SPEED}" priority="5"/>')
        edges.append(f'<edge id="{rid}_sout" from="{rid}_term" to="{rid}_se" numLanes="2" '
                     f'speed="{SURF_SPEED}" priority="5"/>')
        edges.append(f'<edge id="{rid}_capp" from="{rid}_cn" to="{rid}_term" numLanes="1" '
                     f'speed="{SURF_SPEED}" priority="5"/>')
        edges.append(f'<edge id="{rid}_cout" from="{rid}_term" to="{rid}_cs" numLanes="1" '
                     f'speed="{SURF_SPEED}" priority="5"/>')
        # storage-limited ramp: shaped so it LEAVES the terminal as a left turn and
        # ARRIVES at the meter parallel to the mainline (0-degree internal link at
        # the meter, so netconvert does not throttle the meter's discharge speed).
        st_shape = [(xt, Y_ART), (xt + 0.30 * L, Y_ART + 0.30 * (Y_MET - Y_ART)),
                    (xt + 0.75 * L, Y_MET), (xm, Y_MET)]
        edges.append(f'<edge id="{rid}_stor" from="{rid}_term" to="{rid}_met" numLanes="1" '
                     f'speed="{RAMP_SPEED}" priority="1" length="{L:.1f}" shape="{shp(st_shape)}"/>')
        mg_shape = [(xm, Y_MET), (xm + 0.5 * MERGE_LEN, Y_MET), (x, 0)]
        edges.append(f'<edge id="{rid}_mrg" from="{rid}_met" to="m_{rid}" numLanes="1" '
                     f'speed="{MERGE_SPEED}" priority="1" length="{MERGE_LEN:.1f}" '
                     f'shape="{shp(mg_shape)}"/>')

        # ramp-bound movement is the LEFT turn out of the LEFT lane (lane 1) -- so an
        # overflowing ramp queue blocks arterial through traffic sharing lane 1, the
        # classic left-turn-bay overflow. keepClear="false": when the storage segment
        # is full the ramp-bound vehicle stalls INSIDE the junction box and physically
        # blocks the cross street. This is the H4 spillback mechanism; with keep-clear
        # on, the queue would hold at the stop bar and could never block the terminal.
        cons.append(f'<connection from="{rid}_sapp" to="{rid}_stor" fromLane="1" toLane="0" keepClear="false"/>')
        cons.append(f'<connection from="{rid}_sapp" to="{rid}_sout" fromLane="1" toLane="1"/>')
        cons.append(f'<connection from="{rid}_sapp" to="{rid}_sout" fromLane="0" toLane="0"/>')
        cons.append(f'<connection from="{rid}_capp" to="{rid}_cout" fromLane="0" toLane="0"/>')
        cons.append(f'<connection from="{rid}_stor" to="{rid}_mrg" fromLane="0" toLane="0"/>')
        cons.append(f'<connection from="{rid}_mrg" to="{dn_of["m_" + rid]}" fromLane="0" toLane="0"/>')

    nod = os.path.join(outdir, "corridor.nod.xml")
    edg = os.path.join(outdir, "corridor.edg.xml")
    con = os.path.join(outdir, "corridor.con.xml")
    net = os.path.join(outdir, "corridor.net.xml")
    open(nod, "w").write("<nodes>\n  " + "\n  ".join(nodes) + "\n</nodes>\n")
    open(edg, "w").write("<edges>\n  " + "\n  ".join(edges) + "\n</edges>\n")
    open(con, "w").write("<connections>\n  " + "\n  ".join(cons) + "\n</connections>\n")

    cmd = ["netconvert", "-n", nod, "-e", edg, "-x", con, "-o", net,
           "--no-turnarounds", "true", "--junctions.corner-detail", "0",
           "--offset.disable-normalization", "true", "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--check-lane-foes.all", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + "\n" + r.stderr + "\n")
        raise SystemExit("netconvert failed")
    return net, [l for l in r.stderr.splitlines() if l.strip()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--stor", nargs=3, type=float, default=[280.0, 220.0, 160.0])
    a = ap.parse_args()
    net, warn = build(a.outdir, a.stor)
    print("built", net, "storage=", a.stor)
    for w in warn[:30]:
        print("  netconvert:", w)
