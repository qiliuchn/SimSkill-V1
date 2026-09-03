#!/usr/bin/env python3
"""Build the 4-approach signalized intersection used for the detector-design study.

Geometry
--------
    Junction C at (0,0).  Four 400 m approach edges.
      * MAJOR arterial  = E-W  (edges WC/CW, EC/CE), free-flow 60 km/h (16.667 m/s)
      * MINOR cross st. = N-S  (edges NC/CN, SC/CS), free-flow 40 km/h (11.111 m/s)
    Every approach has 2 incoming lanes:
      lane _0 (rightmost) : through + right turn
      lane _1 (leftmost)  : LEFT TURN ONLY   -> allows a protected left phase
    Every departing edge has 2 lanes.

The network is written with netconvert from plain XML so the phase structure and
lane->link assignment are fully under our control (netconvert's own tl guessing
would not reliably give us a protected-left 4-phase plan).

Output: <outdir>/inter.net.xml   (tlLogic type="static", 8 phases)
"""
import os
import subprocess
import sys

MAJOR_SPEED = 60 / 3.6   # 16.667 m/s
MINOR_SPEED = 40 / 3.6   # 11.111 m/s
L = 400.0                # approach length [m]


def write_plain(outdir):
    os.makedirs(outdir, exist_ok=True)

    nod = f"""<nodes>
    <node id="C" x="0.0"  y="0.0"  type="traffic_light" tl="C"/>
    <node id="W" x="{-L}" y="0.0"  type="priority"/>
    <node id="E" x="{L}"  y="0.0"  type="priority"/>
    <node id="S" x="0.0"  y="{-L}" type="priority"/>
    <node id="N" x="0.0"  y="{L}"  type="priority"/>
    <!-- Isolated dummy corridor, 5 km away, topologically disconnected from the
         intersection.  It exists ONLY to host a permanently-occupied induction
         loop used to model a STUCK-ON detector fault (see faults.py).  It is
         present in the network used by EVERY variant, so no variant differs in
         topology; only whether a vehicle is parked on it differs. -->
    <node id="D1" x="5000.0" y="0.0" type="priority"/>
    <node id="D2" x="5200.0" y="0.0" type="priority"/>
</nodes>
"""

    def edge(eid, frm, to, spd):
        return (f'    <edge id="{eid}" from="{frm}" to="{to}" numLanes="2" '
                f'speed="{spd:.4f}" priority="{2 if spd > 14 else 1}"/>\n')

    edg = "<edges>\n"
    for eid, a, b in (("WC", "W", "C"), ("CE", "C", "E"),
                      ("EC", "E", "C"), ("CW", "C", "W")):
        edg += edge(eid, a, b, MAJOR_SPEED)
    for eid, a, b in (("SC", "S", "C"), ("CN", "C", "N"),
                      ("NC", "N", "C"), ("CS", "C", "S")):
        edg += edge(eid, a, b, MINOR_SPEED)
    edg += ('    <edge id="DUMMY" from="D1" to="D2" numLanes="1" '
            'speed="13.89" priority="1"/>\n')
    edg += "</edges>\n"

    # connections: lane 0 -> through + right ; lane 1 -> left only
    # W approach (heading east):  through=CE, right=CS, left=CN
    # E approach (heading west):  through=CW, right=CN, left=CS
    # S approach (heading north): through=CN, right=CE, left=CW
    # N approach (heading south): through=CS, right=CW, left=CE
    spec = {
        "WC": {"t": "CE", "r": "CS", "l": "CN"},
        "EC": {"t": "CW", "r": "CN", "l": "CS"},
        "SC": {"t": "CN", "r": "CE", "l": "CW"},
        "NC": {"t": "CS", "r": "CW", "l": "CE"},
    }
    con = "<connections>\n"
    for ap, m in spec.items():
        # lane 0 -> through (to lane 0) and right (to lane 0)
        con += f'    <connection from="{ap}" to="{m["t"]}" fromLane="0" toLane="0"/>\n'
        con += f'    <connection from="{ap}" to="{m["r"]}" fromLane="0" toLane="0"/>\n'
        # lane 1 -> left (to lane 1)
        con += f'    <connection from="{ap}" to="{m["l"]}" fromLane="1" toLane="1"/>\n'
    con += "</connections>\n"

    # Link indices are assigned by netconvert in a deterministic order; we generate
    # a first pass without a tll file, read back the link order, then emit the tll.
    for name, txt in (("inter.nod.xml", nod), ("inter.edg.xml", edg),
                      ("inter.con.xml", con)):
        with open(os.path.join(outdir, name), "w") as f:
            f.write(txt)


def netconvert(outdir, tll=None):
    cmd = ["netconvert",
           "-n", os.path.join(outdir, "inter.nod.xml"),
           "-e", os.path.join(outdir, "inter.edg.xml"),
           "-x", os.path.join(outdir, "inter.con.xml"),
           "--no-turnarounds", "true",
           "--default.junctions.keep-clear", "true",
           "--tls.default-type", "static",
           "-o", os.path.join(outdir, "inter.net.xml")]
    if tll:
        cmd += ["-i", tll]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit(1)
    return r.stderr


if __name__ == "__main__":
    outdir = sys.argv[1]
    write_plain(outdir)
    err = netconvert(outdir)
    print("netconvert stderr:", err.strip() or "(clean)")
    print("wrote", os.path.join(outdir, "inter.net.xml"))
