#!/usr/bin/env python3
"""
Test bed for HCM Chapter 19 signalized-intersection LOS validation.

Isolated 4-leg signalized intersection.  Each approach:

    X_F  (fringe) --feed_X (FEED_LEN, 2 lanes)--> X_M
    X_M           --inA_X  (SEG_LEN-BAY, 2 lanes)--> X_B
    X_B           --inB_X  (BAY, 3 lanes)--> C   (stop line)

    lane 0 = shared THROUGH + RIGHT
    lane 1 = THROUGH only
    lane 2 = exclusive LEFT-TURN BAY          (added on the left, index 2)

    C --out_X (FEED_LEN+SEG_LEN, 2 lanes)--> X_F

X_M sits exactly SEG_LEN (=250 m) upstream of the stop line: that is the
HCM control-delay measurement entry cross-section.  The exit cross-section is
EXIT_POS (=100 m) along the downstream out_ edge.

Compiled-length calibration (netconvert shortens edges by junction geometry;
a nominal 50 m bay has been observed to compile to 35.6 m) is applied
iteratively so that BOTH the bay length AND the 250 m measurement segment are
the intended values in the COMPILED network, following
`design-left-turn-storage-bay-length`.
"""
import argparse, os, shutil, subprocess, sys
import xml.etree.ElementTree as ET

FEED_LEN = 700.0    # upstream feeder / insertion + queue-storage reservoir (m)
SEG_LEN  = 250.0    # HCM measurement segment: entry point -> stop line (m)
BAY_LEN  = 150.0    # exclusive left-turn storage bay (m)
SPEED    = 13.89    # m/s  (50 km/h)
TOL      = 0.15

# approach heading -> destination out-edge for each movement
MOV = {
    "N": dict(t="out_S", r="out_W", l="out_E"),   # N approach heads SOUTH
    "S": dict(t="out_N", r="out_E", l="out_W"),
    "E": dict(t="out_W", r="out_N", l="out_S"),   # E approach heads WEST
    "W": dict(t="out_E", r="out_S", l="out_N"),
}
# unit vector from centre toward each approach's fringe
DIRV = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    s = shutil.which("sumo")
    if s:
        c = os.path.join(os.path.dirname(s), name)
        if os.path.exists(c):
            return c
    home = os.environ.get("SUMO_HOME")
    if home:
        for c in (os.path.join(home, "bin", name), os.path.join(os.path.dirname(home), "bin", name)):
            if os.path.exists(c):
                return c
    raise RuntimeError(f"{name} not found")


def compiled_lane_lengths(net):
    """{edge_id: [lane lengths]} for non-internal edges."""
    r = ET.parse(net).getroot()
    out = {}
    for ed in r.findall("edge"):
        if ed.get("function") == "internal":
            continue
        out[ed.get("id")] = [float(l.get("length")) for l in ed.findall("lane")]
    return out


def _build_once(outdir, dB, dM, dF, tl_type, full_left=False):
    os.makedirs(outdir, exist_ok=True)
    n = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    n.append(f'  <node id="C" x="0" y="0" type="traffic_light" tlType="{tl_type}"/>')
    for a, (ux, uy) in DIRV.items():
        n.append(f'  <node id="{a}_B" x="{ux*dB:.3f}" y="{uy*dB:.3f}" type="priority"/>')
        n.append(f'  <node id="{a}_M" x="{ux*dM:.3f}" y="{uy*dM:.3f}" type="priority"/>')
        n.append(f'  <node id="{a}_F" x="{ux*dF:.3f}" y="{uy*dF:.3f}" type="priority"/>')
    n.append("</nodes>")

    e = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a in MOV:
        nup = 3 if full_left else 2
        e.append(f'  <edge id="feed_{a}" from="{a}_F" to="{a}_M" numLanes="{nup}" speed="{SPEED}" spreadType="right"/>')
        e.append(f'  <edge id="inA_{a}"  from="{a}_M" to="{a}_B" numLanes="{nup}" speed="{SPEED}" spreadType="right"/>')
        e.append(f'  <edge id="inB_{a}"  from="{a}_B" to="C"     numLanes="3" speed="{SPEED}" spreadType="right"/>')
        e.append(f'  <edge id="out_{a}"  from="C"     to="{a}_F" numLanes="2" speed="{SPEED}" spreadType="right"/>')
    e.append("</edges>")

    c = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for a in MOV:
        c.append(f'  <connection from="feed_{a}" to="inA_{a}" fromLane="0" toLane="0"/>')
        c.append(f'  <connection from="feed_{a}" to="inA_{a}" fromLane="1" toLane="1"/>')
        c.append(f'  <connection from="inA_{a}" to="inB_{a}" fromLane="0" toLane="0"/>')
        c.append(f'  <connection from="inA_{a}" to="inB_{a}" fromLane="1" toLane="1"/>')
        if full_left:
            # CALIBRATION variant: the exclusive left lane runs the whole approach,
            # so the bay can never starve and the stop-line discharge measurement
            # is not refill-limited.
            c.append(f'  <connection from="feed_{a}" to="inA_{a}" fromLane="2" toLane="2"/>')
            c.append(f'  <connection from="inA_{a}" to="inB_{a}" fromLane="2" toLane="2"/>')
        else:
            # OPERATIONAL variant: bay taper - inA lane 1 fans out to through
            # lane 1 and bay lane 2.
            c.append(f'  <connection from="inA_{a}" to="inB_{a}" fromLane="1" toLane="2"/>')
        m = MOV[a]
        c.append(f'  <connection from="inB_{a}" to="{m["t"]}" fromLane="0" toLane="0"/>')
        c.append(f'  <connection from="inB_{a}" to="{m["r"]}" fromLane="0" toLane="0"/>')
        c.append(f'  <connection from="inB_{a}" to="{m["t"]}" fromLane="1" toLane="1"/>')
        c.append(f'  <connection from="inB_{a}" to="{m["l"]}" fromLane="2" toLane="1"/>')
    c.append("</connections>")

    nod, edg, con = (os.path.join(outdir, f"net.{x}.xml") for x in ("nod", "edg", "con"))
    for path, body in ((nod, n), (edg, e), (con, c)):
        open(path, "w").write("\n".join(body) + "\n")
    net = os.path.join(outdir, "intersection.net.xml")
    subprocess.run([find_bin("netconvert"), "-n", nod, "-e", edg, "-x", con,
                    "-o", net, "--no-turnarounds", "true",
                    "--tls.default-type", tl_type,
                    "--no-warnings", "true"], check=True, capture_output=True)
    return net


def build(outdir, tl_type="static", verbose=True, full_left=False):
    dB, dM, dF = BAY_LEN + 14.0, SEG_LEN + 16.0, SEG_LEN + FEED_LEN + 18.0
    net = None
    for it in range(12):
        net = _build_once(outdir, dB, dM, dF, tl_type, full_left)
        cl = compiled_lane_lengths(net)
        eB = cl["inB_N"][0] - BAY_LEN
        eA = cl["inA_N"][0] - (SEG_LEN - BAY_LEN)
        eF = cl["feed_N"][0] - FEED_LEN
        if verbose:
            print(f"  calib {it}: bay={cl['inB_N'][0]:.2f} inA={cl['inA_N'][0]:.2f} feed={cl['feed_N'][0]:.2f}")
        if max(abs(eB), abs(eA), abs(eF)) < TOL:
            break
        dB -= eB
        dM -= (eB + eA)
        dF -= (eB + eA + eF)
    return net


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tl-type", default="static", choices=["static", "actuated"])
    ap.add_argument("--full-left", action="store_true")
    a = ap.parse_args()
    net = build(a.outdir, a.tl_type, full_left=a.full_left)
    cl = compiled_lane_lengths(net)
    print("compiled lane lengths (m):")
    for k in sorted(cl):
        print(f"  {k:10s} {['%.2f' % x for x in cl[k]]}")
    print("net:", net)
