#!/usr/bin/env python3
"""
Build ONE shared +-shaped single-intersection geometry (plain-XML nodes/edges),
then compile FOUR .net.xml variants that differ ONLY in the center junction's
control type:
    A right_before_left  (uncontrolled, yield-to-the-right)
    B priority           (TWSC: E-W major road has HIGHER edge priority than N-S)
    C allway_stop        (AWSC)
    D traffic_light      (signalized baseline, netconvert default fixed-time plan)

Geometry (nodes, edges, lanes, speed, and even the E-W>N-S edge priority) is
IDENTICAL across all four; only the center node's `type` attribute changes.
The E-W>N-S priority is baked into the shared edge file because it is only
CONSULTED by the `priority` junction type -- right_before_left / allway_stop /
traffic_light all ignore edge priority -- so a single shared edge file keeps the
geometry truly identical while still giving variant B a major-road TWSC.
"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(BASE, "outputs", "network")

ARM = 200.0        # m from center to fringe node
SPEED = 13.89      # m/s (~50 km/h)
MAJOR_PRIO = 3     # E-W arterial
MINOR_PRIO = 1     # N-S minor

VARIANTS = {
    "A_right_before_left": "right_before_left",
    "B_priority":          "priority",
    "C_allway_stop":       "allway_stop",
    "D_traffic_light":     "traffic_light",
}

# fringe nodes: N up, S down, E right, W left
FRINGE = {"N": (0, ARM), "S": (0, -ARM), "E": (ARM, 0), "W": (-ARM, 0)}
MAJOR_ARMS = {"E", "W"}   # E-W is the major (higher-priority) axis


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        c = os.path.join(os.path.dirname(sumo), name)
        if os.path.isfile(c):
            return c
    sh = os.environ.get("SUMO_HOME")
    if sh:
        c = os.path.join(sh, "bin", name)
        if os.path.isfile(c):
            return c
    sys.exit(f"cannot find {name}")


def write_edge_file(path):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for name, _ in FRINGE.items():
        prio = MAJOR_PRIO if name in MAJOR_ARMS else MINOR_PRIO
        lines.append(f'    <edge id="in_{name}"  from="{name}" to="center" numLanes="1" speed="{SPEED}" priority="{prio}"/>')
        lines.append(f'    <edge id="out_{name}" from="center" to="{name}" numLanes="1" speed="{SPEED}" priority="{prio}"/>')
    lines.append("</edges>")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_node_file(path, center_type):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    lines.append(f'    <node id="center" x="0" y="0" type="{center_type}"/>')
    for name, (x, y) in FRINGE.items():
        lines.append(f'    <node id="{name}" x="{x}" y="{y}" type="priority"/>')
    lines.append("</nodes>")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    os.makedirs(NET, exist_ok=True)
    netconvert = find_bin("netconvert")

    edg = os.path.join(NET, "shared.edg.xml")
    write_edge_file(edg)
    print("wrote shared edges:", edg)

    for vname, ctype in VARIANTS.items():
        nod = os.path.join(NET, f"{vname}.nod.xml")
        write_node_file(nod, ctype)
        out = os.path.join(NET, f"{vname}.net.xml")
        cmd = [
            netconvert,
            "--node-files", nod,
            "--edge-files", edg,
            "--no-turnarounds", "true",
            "--tls.guess", "false",          # only the traffic_light node becomes a TLS
            "-o", out,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(f"netconvert failed for {vname}")
        # strip netconvert's stderr warnings but surface them briefly
        print(f"compiled {vname} -> {out}  (center type={ctype})")
    print("DONE building 4 net variants")


if __name__ == "__main__":
    main()
