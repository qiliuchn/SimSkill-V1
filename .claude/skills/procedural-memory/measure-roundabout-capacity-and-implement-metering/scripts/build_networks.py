"""
Build the four (+1) junction variants used in this study, all sharing identical
fringe-node positions, approach lengths and speeds so ONE demand file routes on
every variant.

Ring geometry (right-hand traffic => COUNTERCLOCKWISE circulation).  Unlike the
compact 4-ring-node model in `create-roundabout-network`, this build uses EIGHT
ring nodes -- an exit node xX and an entry node eX per arm -- because the HCM
entry-capacity law is defined against the circulating flow that passes IN FRONT
OF the entry, i.e. the flow on the short ring segment BETWEEN the leg's exit and
the leg's entry.  With only one ring node per arm, entering and exiting traffic
share a junction and the "circulating flow" cannot be measured separately from
the exiting flow.

    ring node angles (deg, CCW):  xN=67.5  eN=112.5  xW=157.5  eW=202.5
                                  xS=247.5 eS=292.5  xE=337.5  eE=22.5
    -> a regular octagon of radius R; the 8 ring edges are:
         rg_N: eN->xW   rl_W: xW->eW   rg_W: eW->xS   rl_S: xS->eS
         rg_S: eS->xE   rl_E: xE->eE   rg_E: eE->xN   rl_N: xN->eN
       rl_X is the "leg segment" of arm X -- the CIRCULATING (conflicting) flow
       for the entry at arm X is exactly the flow on rl_X.

Variants
    sl     single-lane roundabout      1-lane approaches, 1-lane ring
    two    conventional two-lane RAB   2-lane approaches, 2-lane ring, ring
                                       weaving PERMITTED (SUMO default)
    turbo  turbo roundabout            identical to `two` except every
                                       circulatory lane carries
                                       changeLeft="none" changeRight="none"
                                       (spiral discipline: pick your lane before
                                       entering, no weaving on the ring)
    sig    signalized reference        2-lane approaches, single center node,
                                       type=traffic_light (program written
                                       separately by webster_signal.py)
    slm    metering test bed           = sl, but every approach is split at 60 m
                                       upstream by a traffic_light node mX so a
                                       part-time metering signal can be placed on
                                       one entry.  All four are split so the
                                       geometry stays symmetric; only mE is ever
                                       actually held red.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys

ARMS = ["N", "E", "S", "W"]
# CCW order of arms as encountered while circulating: N -> W -> S -> E -> N
NEXT_ARM = {"N": "W", "W": "S", "S": "E", "E": "N"}
PREV_ARM = {v: k for k, v in NEXT_ARM.items()}
ARM_ANGLE = {"N": 90.0, "W": 180.0, "S": 270.0, "E": 0.0}
DELTA = 22.5  # half-width of the leg segment, degrees


def find_bin(name):
    f = shutil.which(name)
    if f:
        return f
    sh = os.environ.get("SUMO_HOME")
    if sh:
        c = os.path.join(sh, "bin", name)
        if os.path.isfile(c):
            return c
    sys.exit("could not locate " + name)


def pol(R, deg):
    a = math.radians(deg)
    return (round(R * math.cos(a), 2), round(R * math.sin(a), 2))


def ring_node_angles():
    """exit node xX sits UPSTREAM of entry node eX in the CCW direction."""
    ang = {}
    for a in ARMS:
        ang["x" + a] = ARM_ANGLE[a] - DELTA
        ang["e" + a] = ARM_ANGLE[a] + DELTA
    return ang


RING_EDGES = []  # (id, from, to, kind) in CCW order
for _a in ["N", "W", "S", "E"]:
    RING_EDGES.append(("rg_" + _a, "e" + _a, "x" + NEXT_ARM[_a], "quadrant"))
    RING_EDGES.append(("rl_" + NEXT_ARM[_a], "x" + NEXT_ARM[_a], "e" + NEXT_ARM[_a], "leg"))


def build_roundabout(outdir, name, R, D, app_lanes, ring_lanes, app_speed, ring_speed,
                     no_ring_lanechange=False, meter_nodes=False, meter_setback=60.0):
    ang = ring_node_angles()
    nod = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for a in ARMS:
        x, y = pol(D, ARM_ANGLE[a])
        nod.append(f'    <node id="{a}" x="{x}" y="{y}" type="priority"/>')
    for n, deg in ang.items():
        x, y = pol(R, deg)
        nod.append(f'    <node id="{n}" x="{x}" y="{y}" type="priority"/>')
    if meter_nodes:
        for a in ARMS:
            fx, fy = pol(D, ARM_ANGLE[a])
            ex, ey = pol(R, ang["e" + a])
            L = math.hypot(fx - ex, fy - ey)
            t = meter_setback / L  # fraction of the way from eX back toward X
            mx, my = ex + (fx - ex) * t, ey + (fy - ey) * t
            nod.append(f'    <node id="m{a}" x="{round(mx,2)}" y="{round(my,2)}" type="traffic_light"/>')
    nod.append("</nodes>")

    lane_block = ""
    if no_ring_lanechange:
        lane_block = "".join(
            # netconvert rejects changeLeft="none" / "" -- the attribute takes a
            # LIST OF PERMITTED vClasses.  "authority" permits only emergency
            # authority vehicles to weave; the passenger fleet used here cannot.
            f'\n        <lane index="{i}" changeLeft="authority" changeRight="authority"/>' for i in range(ring_lanes)
        ) + "\n    "

    edg = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a in ARMS:
        if meter_nodes:
            edg.append(f'    <edge id="in_{a}"  from="{a}"   to="m{a}" numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
            edg.append(f'    <edge id="ap_{a}"  from="m{a}"  to="e{a}" numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
        else:
            edg.append(f'    <edge id="in_{a}"  from="{a}"   to="e{a}" numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
        edg.append(f'    <edge id="out_{a}" from="x{a}" to="{a}"  numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
    for eid, fr, to, _kind in RING_EDGES:
        if lane_block:
            edg.append(f'    <edge id="{eid}" from="{fr}" to="{to}" numLanes="{ring_lanes}" speed="{ring_speed}" priority="3">{lane_block}</edge>')
        else:
            edg.append(f'    <edge id="{eid}" from="{fr}" to="{to}" numLanes="{ring_lanes}" speed="{ring_speed}" priority="3"/>')
    rn = " ".join(n for n in ang)
    re_ = " ".join(e[0] for e in RING_EDGES)
    edg.append(f'    <roundabout nodes="{rn}" edges="{re_}"/>')
    edg.append("</edges>")

    # explicit lane-to-lane connections
    con = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    ent_edge = (lambda a: "ap_" + a) if meter_nodes else (lambda a: "in_" + a)
    for a in ARMS:
        # entry: approach -> the quadrant ring edge leaving eX
        for i in range(min(app_lanes, ring_lanes)):
            con.append(f'    <connection from="{ent_edge(a)}" to="rg_{a}" fromLane="{i}" toLane="{i}"/>')
        if app_lanes > ring_lanes:  # e.g. 2-lane approach into 1-lane ring
            for i in range(ring_lanes, app_lanes):
                con.append(f'    <connection from="{ent_edge(a)}" to="rg_{a}" fromLane="{i}" toLane="{ring_lanes-1}"/>')
        # circulating: leg segment -> quadrant segment (through the entry node eX)
        for i in range(ring_lanes):
            con.append(f'    <connection from="rl_{a}" to="rg_{a}" fromLane="{i}" toLane="{i}"/>')
        # at exit node xX: incoming quadrant edge rg_{PREV(a)} -> out_a and -> rl_a
        p = PREV_ARM[a]
        for i in range(ring_lanes):
            con.append(f'    <connection from="rg_{p}" to="rl_{a}" fromLane="{i}" toLane="{i}"/>')
            con.append(f'    <connection from="rg_{p}" to="out_{a}" fromLane="{i}" toLane="{min(i, app_lanes-1)}"/>')
        if meter_nodes:
            for i in range(app_lanes):
                con.append(f'    <connection from="in_{a}" to="ap_{a}" fromLane="{i}" toLane="{i}"/>')
    con.append("</connections>")

    base = os.path.join(outdir, name)
    open(base + ".nod.xml", "w").write("\n".join(nod) + "\n")
    open(base + ".edg.xml", "w").write("\n".join(edg) + "\n")
    open(base + ".con.xml", "w").write("\n".join(con) + "\n")

    cmd = [find_bin("netconvert"),
           "--node-files", base + ".nod.xml",
           "--edge-files", base + ".edg.xml",
           "--connection-files", base + ".con.xml",
           "-o", base + ".net.xml",
           "--roundabouts.guess", "true",
           "--check-lane-foes.roundabout", "true",
           "--no-turnarounds", "true",
           "--no-internal-links", "false",
           "--junctions.corner-detail", "5",
           "--offset.disable-normalization", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr); sys.exit(r.returncode)
    if r.stderr.strip():
        print(f"[{name}] netconvert stderr:\n" + r.stderr)
    print("wrote", base + ".net.xml")


def build_signalized(outdir, name, D, app_lanes, app_speed):
    nod = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for a in ARMS:
        x, y = pol(D, ARM_ANGLE[a])
        nod.append(f'    <node id="{a}" x="{x}" y="{y}" type="priority"/>')
    nod.append('    <node id="C" x="0" y="0" type="traffic_light"/>')
    nod.append("</nodes>")
    edg = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a in ARMS:
        edg.append(f'    <edge id="in_{a}"  from="{a}" to="C" numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
        edg.append(f'    <edge id="out_{a}" from="C" to="{a}" numLanes="{app_lanes}" speed="{app_speed}" priority="1"/>')
    edg.append("</edges>")
    # right / through on lane 0, left on lane 1  (heading into the junction)
    RIGHT = {"N": "W", "W": "S", "S": "E", "E": "N"}
    THRU = {"N": "S", "S": "N", "E": "W", "W": "E"}
    LEFT = {"N": "E", "E": "S", "S": "W", "W": "N"}
    con = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for a in ARMS:
        con.append(f'    <connection from="in_{a}" to="out_{RIGHT[a]}" fromLane="0" toLane="0"/>')
        con.append(f'    <connection from="in_{a}" to="out_{THRU[a]}"  fromLane="0" toLane="0"/>')
        con.append(f'    <connection from="in_{a}" to="out_{LEFT[a]}"  fromLane="1" toLane="1"/>')
    con.append("</connections>")
    base = os.path.join(outdir, name)
    open(base + ".nod.xml", "w").write("\n".join(nod) + "\n")
    open(base + ".edg.xml", "w").write("\n".join(edg) + "\n")
    open(base + ".con.xml", "w").write("\n".join(con) + "\n")
    cmd = [find_bin("netconvert"),
           "--node-files", base + ".nod.xml",
           "--edge-files", base + ".edg.xml",
           "--connection-files", base + ".con.xml",
           "-o", base + ".net.xml",
           "--no-turnarounds", "true",
           "--tls.default-type", "static",
           "--offset.disable-normalization", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr); sys.exit(r.returncode)
    if r.stderr.strip():
        print(f"[{name}] netconvert stderr:\n" + r.stderr)
    print("wrote", base + ".net.xml")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--outdir", required=True)
    p.add_argument("--radius", type=float, default=32.0)
    p.add_argument("--fringe", type=float, default=200.0)
    p.add_argument("--app-speed", type=float, default=13.89)
    p.add_argument("--ring-speed", type=float, default=8.33)
    a = p.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    build_roundabout(a.outdir, "sl", a.radius, a.fringe, 1, 1, a.app_speed, a.ring_speed)
    build_roundabout(a.outdir, "two", a.radius, a.fringe, 2, 2, a.app_speed, a.ring_speed)
    build_roundabout(a.outdir, "turbo", a.radius, a.fringe, 2, 2, a.app_speed, a.ring_speed,
                     no_ring_lanechange=True)
    build_roundabout(a.outdir, "slm", a.radius, a.fringe, 1, 1, a.app_speed, a.ring_speed,
                     meter_nodes=True)
    build_roundabout(a.outdir, "twom", a.radius, a.fringe, 2, 2, a.app_speed, a.ring_speed,
                     meter_nodes=True)
    build_signalized(a.outdir, "sig", a.fringe, 2, a.app_speed)
