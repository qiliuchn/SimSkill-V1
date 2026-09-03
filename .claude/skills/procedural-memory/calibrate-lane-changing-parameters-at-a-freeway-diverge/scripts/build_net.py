#!/usr/bin/env python3
"""STEP 1 -- hand-author the 3-lane / 4 km freeway off-ramp DIVERGE in plain XML
and compile it with netconvert (netgenerate is deliberately NOT used), then
VERIFY from the compiled .net.xml that:
  (i)  the auxiliary/deceleration lane D_0 has NO upstream connection, so it can
       only be entered by a lane change;
  (ii) the ONLY connection into the ramp R is from D_0;
  (iii) the only lane of C that reaches D_0 in one further change is C_0, the
       RIGHTMOST THROUGH lane => exiting is a genuine MANDATORY lane change.
"""
import os, sys, subprocess, json
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lc_common import NETCONVERT, NETDIR, NET, OUT, TBL

NODES = """<nodes>
  <node id="n0" x="0"    y="0"   type="priority"/>
  <node id="n1" x="600"  y="0"   type="priority"/>
  <node id="n2" x="2100" y="0"   type="priority"/>
  <node id="n3" x="3300" y="0"   type="priority"/>
  <node id="n4" x="3600" y="0"   type="priority"/>
  <node id="n5" x="4200" y="0"   type="priority"/>
  <node id="r1" x="4000" y="-60" type="priority"/>
</nodes>
"""

EDGES = """<edges>
  <edge id="A" from="n0" to="n1" numLanes="3" speed="33.33" priority="12"/>
  <edge id="B" from="n1" to="n2" numLanes="3" speed="33.33" priority="12"/>
  <edge id="C" from="n2" to="n3" numLanes="3" speed="33.33" priority="12"/>
  <edge id="D" from="n3" to="n4" numLanes="4" speed="33.33" priority="12"/>
  <edge id="E" from="n4" to="n5" numLanes="3" speed="33.33" priority="12"/>
  <edge id="R" from="n4" to="r1" numLanes="1" speed="22.22" priority="6"/>
</edges>
"""

CONN = """<connections>
  <connection from="A" to="B" fromLane="0" toLane="0"/>
  <connection from="A" to="B" fromLane="1" toLane="1"/>
  <connection from="A" to="B" fromLane="2" toLane="2"/>
  <connection from="B" to="C" fromLane="0" toLane="0"/>
  <connection from="B" to="C" fromLane="1" toLane="1"/>
  <connection from="B" to="C" fromLane="2" toLane="2"/>
  <connection from="C" to="D" fromLane="0" toLane="1"/>
  <connection from="C" to="D" fromLane="1" toLane="2"/>
  <connection from="C" to="D" fromLane="2" toLane="3"/>
  <connection from="D" to="E" fromLane="1" toLane="0"/>
  <connection from="D" to="E" fromLane="2" toLane="1"/>
  <connection from="D" to="E" fromLane="3" toLane="2"/>
  <connection from="D" to="R" fromLane="0" toLane="0"/>
</connections>
"""


def build():
    os.makedirs(NETDIR, exist_ok=True)
    for name, txt in (("diverge.nod.xml", NODES), ("diverge.edg.xml", EDGES),
                      ("diverge.con.xml", CONN)):
        open(os.path.join(NETDIR, name), "w").write(txt)
    cmd = [NETCONVERT,
           "-n", os.path.join(NETDIR, "diverge.nod.xml"),
           "-e", os.path.join(NETDIR, "diverge.edg.xml"),
           "-x", os.path.join(NETDIR, "diverge.con.xml"),
           "-o", NET,
           "--no-turnarounds", "true",
           "--offset.disable-normalization", "true",
           "--default.lanewidth", "3.5",
           "--junctions.minimal-shape", "true",
           "--xml-validation", "never"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    print(r.stderr)
    assert r.returncode == 0, "netconvert failed"
    return r


def verify():
    root = ET.parse(NET).getroot()
    edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges[e.get("id")] = [(l.get("id"), float(l.get("length")),
                               float(l.get("speed"))) for l in e.findall("lane")]
    conns = [(c.get("from"), c.get("fromLane"), c.get("to"), c.get("toLane"),
              c.get("via", ""), c.get("dir", ""), c.get("state", ""))
             for c in root.findall("connection")
             if not c.get("from").startswith(":")]
    internal_len = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            for l in e.findall("lane"):
                internal_len[l.get("id")] = float(l.get("length"))

    rep = {}
    rep["edges"] = {k: dict(n_lanes=len(v), length=v[0][1], speed=v[0][2],
                            lanes=[x[0] for x in v]) for k, v in edges.items()}
    rep["connections"] = conns

    # (i) D_0 has no upstream (non-internal) connection
    into_D0 = [c for c in conns if c[2] == "D" and c[3] == "0"]
    rep["check_aux_lane_has_no_upstream_connection"] = (len(into_D0) == 0)
    rep["connections_into_D_0"] = into_D0

    # (ii) only D_0 feeds the ramp
    into_R = [c for c in conns if c[2] == "R"]
    rep["connections_into_R"] = into_R
    rep["check_ramp_fed_only_by_D0"] = (len(into_R) == 1 and into_R[0][0] == "D"
                                        and into_R[0][1] == "0")

    # (iii) which C lane reaches D_1 (the rightmost through lane on D)
    C_to_D = {(c[1], c[3]) for c in conns if c[0] == "C" and c[2] == "D"}
    rep["C_to_D_lane_map"] = sorted(C_to_D)
    rep["check_C0_is_the_only_lane_reaching_D1"] = (("0", "1") in C_to_D and
        len([1 for f, t in C_to_D if t == "1"]) == 1)

    # (iv) internal-lane lengths at the 2 artificial splits must be ~0 so the
    #      station/window edge split does not itself suppress lane changing
    rep["internal_lane_lengths"] = internal_len
    split_int = {k: v for k, v in internal_len.items()
                 if k.startswith(":n1_") or k.startswith(":n2_")}
    rep["check_split_junction_internals_negligible"] = all(
        v < 1.0 for v in split_int.values())
    rep["split_junction_internal_lengths"] = split_int

    ok = all(rep[k] for k in rep if k.startswith("check_"))
    rep["ALL_CHECKS_PASS"] = ok
    json.dump(rep, open(os.path.join(TBL, "net_verification.json"), "w"), indent=2)
    for k in sorted(rep):
        if k.startswith("check_") or k == "ALL_CHECKS_PASS":
            print("%-55s %s" % (k, rep[k]))
    print("\nedges:")
    for k, v in rep["edges"].items():
        print("  %-3s lanes=%d len=%.1f speed=%.2f  %s" %
              (k, v["n_lanes"], v["length"], v["speed"], v["lanes"]))
    print("\nconnections (from,fromLane,to,toLane,via,dir,state):")
    for c in conns:
        print("  ", c)
    print("\nsplit-junction internal lane lengths:", split_int)
    return rep


if __name__ == "__main__":
    build()
    rep = verify()
    sys.exit(0 if rep["ALL_CHECKS_PASS"] else 1)
