"""
Build a compact single-ring 4-arm ROUNDABOUT SUMO network via plain-XML node/edge
files compiled by netconvert.

Geometry (right-hand traffic => COUNTERCLOCKWISE circulation):
  - 4 fringe nodes at compass points, `--fringe-dist` out: N(0,d) E(d,0) S(0,-d) W(-d,0)
  - 4 ring nodes on a radius-R circle at the compass points: rN(0,R) rE(R,0) rS(0,-R) rW(-R,0)
  - 8 approach edges (2-lane by default): in_<A>: A->r<A>, out_<A>: r<A>->A
  - 4 one-way ring edges (1-lane by default) circulating CCW:
        ring_N: rN->rW, ring_W: rW->rS, ring_S: rS->rE, ring_E: rE->rN
    CCW from rN gives first-exit=W (right turn), 2nd=S (through), 3rd=E (left) --
    the correct right-hand-traffic movement order for the North approach. For a
    left-hand-traffic network, reverse the ring direction (clockwise) instead.
  - An explicit <roundabout nodes=... edges=...> element is written into the edge
    file, AND netconvert is run with --roundabouts.guess, so SUMO recognizes the
    ring and gives circulating traffic priority over entering traffic.

The fringe node names (N/E/S/W) and approach edge ids (in_N..out_W) match what
create-single-intersection's generate_intersection.py produces for a 4-arm
intersection, so the SAME demand (trips/flows over in_X -> out_Y) can be routed
on a roundabout, a signalized, or a priority-controlled version of the "same"
junction for a controlled comparison.

Usage:
    python build_roundabout.py -o roundabout.net.xml
    python build_roundabout.py -o roundabout.net.xml --ring-radius 22 --ring-lanes 1
"""
import argparse
import os
import shutil
import subprocess
import sys

ARMS = ["N", "E", "S", "W"]


def find_bin(name):
    f = shutil.which(name)
    if f:
        return f
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
    sys.exit(f"could not locate {name}")


def build(out, fringe_dist, R, approach_lanes, ring_lanes, approach_speed, ring_speed, keep_plain):
    fringe = {"N": (0, fringe_dist), "E": (fringe_dist, 0), "S": (0, -fringe_dist), "W": (-fringe_dist, 0)}
    ring_pos = {"N": (0, R), "E": (R, 0), "S": (0, -R), "W": (-R, 0)}
    workdir = os.path.dirname(os.path.abspath(out)) or "."
    base = os.path.splitext(os.path.basename(out))[0]
    nod = os.path.join(workdir, base + ".nod.xml")
    edg = os.path.join(workdir, base + ".edg.xml")

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for a in ARMS:
        x, y = fringe[a]
        lines.append(f'    <node id="{a}" x="{x}" y="{y}" type="priority"/>')
    for a in ARMS:
        x, y = ring_pos[a]
        # priority nodes; roundabout recognition (below) sets yield-at-entry right-of-way
        lines.append(f'    <node id="r{a}" x="{x}" y="{y}" type="priority"/>')
    lines.append("</nodes>")
    open(nod, "w").write("\n".join(lines) + "\n")

    ring = [("ring_N", "rN", "rW"), ("ring_W", "rW", "rS"), ("ring_S", "rS", "rE"), ("ring_E", "rE", "rN")]
    edges = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a in ARMS:
        edges.append(f'    <edge id="in_{a}"  from="{a}"  to="r{a}" numLanes="{approach_lanes}" speed="{approach_speed}" priority="1"/>')
        edges.append(f'    <edge id="out_{a}" from="r{a}" to="{a}"  numLanes="{approach_lanes}" speed="{approach_speed}" priority="1"/>')
    for eid, fr, to in ring:
        edges.append(f'    <edge id="{eid}" from="{fr}" to="{to}" numLanes="{ring_lanes}" speed="{ring_speed}" priority="3"/>')
    ring_nodes = " ".join("r" + a for a in ["N", "W", "S", "E"])
    ring_edges = " ".join(e[0] for e in ring)
    edges.append(f'    <roundabout nodes="{ring_nodes}" edges="{ring_edges}"/>')
    edges.append("</edges>")
    open(edg, "w").write("\n".join(edges) + "\n")

    nc = find_bin("netconvert")
    cmd = [
        nc, "--node-files", nod, "--edge-files", edg, "-o", out,
        "--roundabouts.guess", "true",
        "--no-turnarounds", "true",
        "--check-lane-foes.roundabout", "true",
    ]
    print("Running:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(r.returncode)
    if r.stderr.strip():
        print("STDERR:", r.stderr, file=sys.stderr)
    if not keep_plain:
        os.remove(nod)
        os.remove(edg)
    print("Wrote", out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build a compact 4-arm roundabout network via plain-XML + netconvert.")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--fringe-dist", type=float, default=150.0, help="distance from center to each fringe node (m)")
    p.add_argument("--ring-radius", type=float, default=22.0, help="radius of the circulating ring (m)")
    p.add_argument("--approach-lanes", type=int, default=2)
    p.add_argument("--ring-lanes", type=int, default=1)
    p.add_argument("--approach-speed", type=float, default=13.89, help="m/s")
    p.add_argument("--ring-speed", type=float, default=8.33, help="m/s (lower than approach speed -- circulating traffic slows through the ring)")
    p.add_argument("--keep-plain", action="store_true", help="keep the intermediate .nod.xml/.edg.xml files")
    a = p.parse_args()
    build(a.output, a.fringe_dist, a.ring_radius, a.approach_lanes, a.ring_lanes, a.approach_speed, a.ring_speed, a.keep_plain)
