#!/usr/bin/env python3
"""Network builders for the route-choice-model investigation.

build_independent(lengths, speed, outdir)
    N fully independent parallel S->T edges of given lengths (all same speed), plus
    common S_in/T_out approach edges. Free-flow travel time of route i = lengths[i]/speed
    (+ small constant offset from S_in/T_out, common to all routes).

build_overlap(phi, L, speed, outdir)
    The Daganzo-Sheffi "loop-hole" testbed: route A independent (S->T direct, length L),
    routes B and C share a common section S->M of length phi*L then diverge onto two
    separate parallel M->T edges of length (1-phi)*L each. All three routes have identical
    total free-flow cost L/speed regardless of phi -- phi controls ONLY the physical overlap
    fraction between B and C (A has zero overlap with either).
"""
import os
import shutil
import subprocess
import sys


def find_tool(name):
    p = shutil.which(name)
    if p:
        return p
    sumo = shutil.which("sumo")
    if sumo:
        cand = os.path.join(os.path.dirname(sumo), name)
        if os.path.exists(cand):
            return cand
    cand = os.path.join(os.environ.get("SUMO_HOME", ""), "bin", name)
    if os.path.exists(cand):
        return cand
    raise SystemExit(f"{name} not found")


NETCONVERT = None


def _netconvert():
    global NETCONVERT
    if NETCONVERT is None:
        NETCONVERT = find_tool("netconvert")
    return NETCONVERT


def _run_netconvert(nod, edg, out_net, extra=None):
    # --no-internal-links is essential here: it removes internal (within-junction) link
    # geometry so that duarouter/sumo route cost reduces EXACTLY to sum(length/speed) over
    # the traversed edges, with zero geometry-dependent turn-angle artifact. Verified: with
    # internal links modeled, two edges of identical length/speed meeting a junction at
    # different turn angles picked up a ~1-1.5s (~1%) cost asymmetry purely from internal
    # lane geometry -- unacceptable when the task requires "exactly known and independently
    # controllable" free-flow costs. With --no-internal-links, three routes engineered to
    # have identical length/speed came back bit-identical (113.33/113.33/113.33).
    cmd = [_netconvert(), "-n", nod, "-e", edg, "-o", out_net,
           "--no-turnarounds", "true",
           "--offset.disable-normalization", "true",
           "--no-internal-links"]
    if extra:
        cmd += extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise SystemExit("netconvert failed")
    return out_net


def build_independent(lengths, outdir, speed=10.0, approach_len=200.0, approach_speed=30.0,
                       lanes=2, name="net"):
    """N independent parallel S->T edges labelled r1..rN with the given lengths (metres)."""
    os.makedirs(outdir, exist_ok=True)
    nod = os.path.join(outdir, f"{name}.nod.xml")
    edg = os.path.join(outdir, f"{name}.edg.xml")
    net = os.path.join(outdir, f"{name}.net.xml")
    n = len(lengths)
    with open(nod, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n')
        f.write(f'    <node id="S0" x="-{approach_len}" y="0" type="priority"/>\n')
        f.write('    <node id="S" x="0" y="0" type="priority"/>\n')
        maxlen = max(lengths)
        f.write(f'    <node id="T" x="{maxlen}" y="0" type="priority"/>\n')
        f.write(f'    <node id="T1" x="{maxlen + approach_len}" y="0" type="priority"/>\n')
        f.write("</nodes>\n")
    with open(edg, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n')
        f.write(f'    <edge id="S_in" from="S0" to="S" numLanes="{lanes+1}" '
                f'speed="{approach_speed}" length="{approach_len}"/>\n')
        for i, L in enumerate(lengths, start=1):
            yoff = (i - (n + 1) / 2.0) * 20.0
            f.write(f'    <edge id="r{i}" from="S" to="T" numLanes="{lanes}" speed="{speed}" '
                    f'length="{L}" shape="0,0 {maxlen},{yoff}"/>\n')
        f.write(f'    <edge id="T_out" from="T" to="T1" numLanes="{lanes+1}" '
                f'speed="{approach_speed}" length="{approach_len}"/>\n')
        f.write("</edges>\n")
    _run_netconvert(nod, edg, net)
    return net


def build_overlap(phi, outdir, L=1000.0, speed=10.0, approach_len=200.0, approach_speed=30.0,
                   lanes=2, name="net", min_seg=2.0):
    """Daganzo-Sheffi loop-hole network. Returns net.xml path.
    Route A = S_in,A,T_out (independent).
    Route B = S_in,shared,B_only,T_out.
    Route C = S_in,shared,C_only,T_out.
    """
    os.makedirs(outdir, exist_ok=True)
    nod = os.path.join(outdir, f"{name}_phi{phi:.3f}.nod.xml")
    edg = os.path.join(outdir, f"{name}_phi{phi:.3f}.edg.xml")
    net = os.path.join(outdir, f"{name}_phi{phi:.3f}.net.xml")

    shared_len = max(min_seg, phi * L)
    tail_len = max(min_seg, (1.0 - phi) * L)
    # keep total EXACTLY L for B/C by adjusting whichever piece is not clamped
    if phi * L < min_seg:
        shared_len = min_seg
        tail_len = L - min_seg
    elif (1.0 - phi) * L < min_seg:
        tail_len = min_seg
        shared_len = L - min_seg

    with open(nod, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n')
        f.write(f'    <node id="S0" x="-{approach_len}" y="0" type="priority"/>\n')
        f.write('    <node id="S" x="0" y="0" type="priority"/>\n')
        f.write(f'    <node id="M" x="{shared_len}" y="-40" type="priority"/>\n')
        f.write(f'    <node id="T" x="{L}" y="0" type="priority"/>\n')
        f.write(f'    <node id="T1" x="{L + approach_len}" y="0" type="priority"/>\n')
        f.write("</nodes>\n")
    with open(edg, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n')
        f.write(f'    <edge id="S_in" from="S0" to="S" numLanes="{lanes+2}" '
                f'speed="{approach_speed}" length="{approach_len}"/>\n')
        f.write(f'    <edge id="A" from="S" to="T" numLanes="{lanes}" speed="{speed}" '
                f'length="{L}" shape="0,0 {L},40"/>\n')
        f.write(f'    <edge id="shared" from="S" to="M" numLanes="{lanes}" speed="{speed}" '
                f'length="{shared_len}" shape="0,0 {shared_len},-40"/>\n')
        f.write(f'    <edge id="B_only" from="M" to="T" numLanes="{lanes}" speed="{speed}" '
                f'length="{tail_len}" shape="{shared_len},-40 {L},-20"/>\n')
        f.write(f'    <edge id="C_only" from="M" to="T" numLanes="{lanes}" speed="{speed}" '
                f'length="{tail_len}" shape="{shared_len},-40 {L},-60"/>\n')
        f.write(f'    <edge id="T_out" from="T" to="T1" numLanes="{lanes+2}" '
                f'speed="{approach_speed}" length="{approach_len}"/>\n')
        f.write("</edges>\n")
    _run_netconvert(nod, edg, net, extra=["--junctions.limit-turn-speed", "-1"])
    return net, shared_len, tail_len, L


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    n1 = build_independent([1000, 1200, 1500], os.path.join(out, "indep"))
    print("built", n1)
    for phi in (0.0, 0.25, 0.5, 0.75, 0.95):
        n2, sl, tl, L = build_overlap(phi, os.path.join(out, "overlap"))
        print("built", n2, "shared_len", sl, "tail_len", tl)
