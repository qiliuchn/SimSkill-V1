#!/usr/bin/env python3
"""
Build the ~7 km directional managed-lane freeway corridor in three network variants.

Geometry (single direction, west -> east):
  mainline nodes N0..N14 at x = 0,500,...,7000  (14 mainline edges m1..m14, 500 m each)
  4 lanes: index 0 = rightmost ... index 3 = leftmost = MANAGED lane
  on-ramp 1  merges at N3  (x=1500)   zipper
  off-ramp 1 diverges at N6  (x=3000) priority
  on-ramp 2  merges at N9  (x=4500)   zipper
  off-ramp 2 diverges at N12 (x=6000) priority

Variants:
  gp4            - all 4 lanes general purpose (policy arm A)
  managed        - lane 3 restricted to allow="hov bus" (arms B/C/D), continuous access
  managed_gated  - same restriction + limited access: changeLeft/changeRight blocked on
                   lane 2 / lane 3 everywhere except 4 designated gate segments
                   (m2, m5, m8, m11)  -> H3 access-design comparison
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "net"))
os.makedirs(OUT, exist_ok=True)

N_MAIN = 14                     # mainline edges m1..m14
SEG = 500.0                     # m per mainline segment
FF_MAIN = 31.29                 # m/s  (~70 mph) mainline free-flow
FF_RAMP = 22.22                 # m/s  (~50 mph) ramp
N_LANES = 4
MANAGED_LANE = 3                # leftmost
GATE_EDGES = ["m2", "m5", "m8", "m11"]   # limited-access ingress/egress gates

ON1_NODE, OFF1_NODE, ON2_NODE, OFF2_NODE = 3, 6, 9, 12


def nodes_xml():
    L = ["<nodes>"]
    for i in range(N_MAIN + 1):
        if i in (ON1_NODE, ON2_NODE):
            t = "zipper"
        elif i in (OFF1_NODE, OFF2_NODE):
            t = "priority"
        else:
            t = "priority"
        L.append(f'    <node id="N{i}" x="{i*SEG:.1f}" y="0.0" type="{t}"/>')
    # ramp terminal nodes
    L.append(f'    <node id="ON1_in"  x="{(ON1_NODE-1)*SEG:.1f}" y="-90.0" type="priority"/>')
    L.append(f'    <node id="OFF1_out" x="{(OFF1_NODE+1)*SEG:.1f}" y="-90.0" type="priority"/>')
    L.append(f'    <node id="ON2_in"  x="{(ON2_NODE-1)*SEG:.1f}" y="-90.0" type="priority"/>')
    L.append(f'    <node id="OFF2_out" x="{(OFF2_NODE+1)*SEG:.1f}" y="-90.0" type="priority"/>')
    L.append("</nodes>")
    return "\n".join(L)


def edges_xml(variant):
    """variant in {gp4, managed, managed_gated}"""
    L = ["<edges>"]
    for i in range(1, N_MAIN + 1):
        eid = f"m{i}"
        head = (f'    <edge id="{eid}" from="N{i-1}" to="N{i}" numLanes="{N_LANES}" '
                f'speed="{FF_MAIN}" priority="10"')
        lanes = []
        if variant in ("managed", "managed_gated"):
            lanes.append(f'        <lane index="{MANAGED_LANE}" allow="hov bus"'
                         + ('' if variant == "managed" or eid in GATE_EDGES
                            else ' changeRight="authority"') + '/>')
            if variant == "managed_gated" and eid not in GATE_EDGES:
                lanes.append('        <lane index="2" changeLeft="authority"/>')
        if lanes:
            L.append(head + ">")
            L.extend(lanes)
            L.append("    </edge>")
        else:
            L.append(head + "/>")
    L.append(f'    <edge id="on1"  from="ON1_in"   to="N{ON1_NODE}"  numLanes="1" speed="{FF_RAMP}" priority="1"/>')
    L.append(f'    <edge id="off1" from="N{OFF1_NODE}" to="OFF1_out" numLanes="1" speed="{FF_RAMP}" priority="1"/>')
    L.append(f'    <edge id="on2"  from="ON2_in"   to="N{ON2_NODE}"  numLanes="1" speed="{FF_RAMP}" priority="1"/>')
    L.append(f'    <edge id="off2" from="N{OFF2_NODE}" to="OFF2_out" numLanes="1" speed="{FF_RAMP}" priority="1"/>')
    L.append("</edges>")
    return "\n".join(L)


def cons_xml():
    L = ["<connections>"]
    for i in range(1, N_MAIN):
        for ln in range(N_LANES):
            L.append(f'    <connection from="m{i}" to="m{i+1}" fromLane="{ln}" toLane="{ln}"/>')
    # on-ramps feed rightmost lane (forced zipper merge with mainline lane 0)
    L.append(f'    <connection from="on1" to="m{ON1_NODE+1}" fromLane="0" toLane="0"/>')
    L.append(f'    <connection from="on2" to="m{ON2_NODE+1}" fromLane="0" toLane="0"/>')
    # off-ramps drain rightmost lane
    L.append(f'    <connection from="m{OFF1_NODE}" to="off1" fromLane="0" toLane="0"/>')
    L.append(f'    <connection from="m{OFF2_NODE}" to="off2" fromLane="0" toLane="0"/>')
    L.append("</connections>")
    return "\n".join(L)


def build(variant):
    nod = os.path.join(OUT, f"{variant}.nod.xml")
    edg = os.path.join(OUT, f"{variant}.edg.xml")
    con = os.path.join(OUT, f"{variant}.con.xml")
    net = os.path.join(OUT, f"{variant}.net.xml")
    open(nod, "w").write(nodes_xml())
    open(edg, "w").write(edges_xml(variant))
    open(con, "w").write(cons_xml())
    cmd = ["netconvert", "-n", nod, "-e", edg, "-x", con, "-o", net,
           "--no-turnarounds", "true", "--offset.disable-normalization", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = os.path.join(OUT, f"{variant}.netconvert.log")
    open(log, "w").write("CMD: " + " ".join(cmd) + "\n\nSTDOUT:\n" + r.stdout + "\n\nSTDERR:\n" + r.stderr)
    if r.returncode != 0:
        print(f"FAILED {variant}\n{r.stderr}")
        sys.exit(1)
    print(f"built {net}   (warnings: {r.stderr.count('Warning')})")


if __name__ == "__main__":
    for v in ("gp4", "managed", "managed_gated"):
        build(v)
