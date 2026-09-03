#!/usr/bin/env python3
"""STEP 1 -- build both testbed networks and VERIFY them from the COMPILED net.

A. cross.net.xml   : isolated 4-way signalised intersection, 1 through lane/approach.
B. fwy_g{G}.net.xml: 3-lane -> 1-lane freeway lane drop at sustained upgrade G%.

Verification performed here (never trusted from the source XML):
  * exact compiled lane lengths (needed to clip the laneAreaDetector correctly)
  * the lane drop really exists in the compiled connections (3 lanes -> 1 lane)
  * the realised grade of every mainline/bottleneck lane, computed from the
    compiled lane `shape` attribute's (x,y,z) triples.
"""
import os
import json
import subprocess
import xml.etree.ElementTree as ET

from common import (NETCONVERT, NETS, WORK, SIG_SPEED, SIG_ARM, FWY_SPEED,
                    FWY_NLANES, GRADES)


def netconvert(nod, edg, out, extra=()):
    cmd = [NETCONVERT, "-n", nod, "-e", edg, "-o", out,
           "--no-turnarounds", "true", "--offset.disable-normalization", "true"]
    cmd += list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("netconvert failed\n%s" % p.stderr[-3000:])
    return out


# ------------------------------------------------------------------ shapes ---
def shape_points(s):
    pts = []
    for tok in s.split():
        c = [float(v) for v in tok.split(",")]
        if len(c) == 2:          # 2-coord shape point == flat (z = 0), not malformed
            c.append(0.0)
        pts.append(c)
    return pts


def lane_grade_pct(shape):
    pts = shape_points(shape)
    (x0, y0, z0), (x1, y1, z1) = pts[0], pts[-1]
    horiz = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    return 100.0 * (z1 - z0) / horiz if horiz > 0 else 0.0


def inspect(net):
    """-> dict of edge -> {lanes:[{id,length,grade_pct}], nlanes}"""
    root = ET.parse(net).getroot()
    info = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = []
        for ln in e.findall("lane"):
            lanes.append(dict(id=ln.get("id"), length=float(ln.get("length")),
                              grade_pct=round(lane_grade_pct(ln.get("shape")), 6),
                              speed=float(ln.get("speed")),
                              allow=ln.get("allow"), disallow=ln.get("disallow")))
        info[e.get("id")] = dict(nlanes=len(lanes), lanes=lanes)
    conns = []
    for c in root.findall("connection"):
        if c.get("from", "").startswith(":"):
            continue
        conns.append((c.get("from"), c.get("fromLane"), c.get("to"), c.get("toLane")))
    return info, conns


# --------------------------------------------------------------- testbed A ---
def build_signal():
    nod = os.path.join(NETS, "cross.nod.xml")
    with open(nod, "w") as f:
        f.write('<nodes>\n')
        f.write('  <node id="C" x="0" y="0" z="0" type="traffic_light"/>\n')
        f.write('  <node id="N" x="0"  y="%g"  z="0"/>\n' % SIG_ARM)
        f.write('  <node id="S" x="0"  y="-%g" z="0"/>\n' % SIG_ARM)
        f.write('  <node id="E" x="%g" y="0"   z="0"/>\n' % SIG_ARM)
        f.write('  <node id="W" x="-%g" y="0"  z="0"/>\n' % SIG_ARM)
        f.write('</nodes>\n')
    edg = os.path.join(NETS, "cross.edg.xml")
    with open(edg, "w") as f:
        f.write('<edges>\n')
        for d, nid in (("N", "N"), ("S", "S"), ("E", "E"), ("W", "W")):
            f.write('  <edge id="in_%s"  from="%s" to="C" numLanes="1" speed="%g"/>\n' % (d, nid, SIG_SPEED))
            f.write('  <edge id="out_%s" from="C" to="%s" numLanes="1" speed="%g"/>\n' % (d, nid, SIG_SPEED))
        f.write('</edges>\n')
    net = os.path.join(NETS, "cross.net.xml")
    netconvert(nod, edg, net)
    return net


# --------------------------------------------------------------- testbed B ---
# feed(3 lanes,800m) -> main(3 lanes,2000m) -> bneck(1 lane,1500m) -> exit(1 lane,600m)
FWY_SEG = [("feed", 800.0, FWY_NLANES), ("main", 2000.0, FWY_NLANES),
           ("bneck", 1500.0, 1), ("exit", 600.0, 1)]


def build_freeway(grade_pct):
    xs = [0.0]
    for _, L, _ in FWY_SEG:
        xs.append(xs[-1] + L)
    zs = [x * grade_pct / 100.0 for x in xs]
    tag = "fwy_g%g" % grade_pct
    nod = os.path.join(NETS, tag + ".nod.xml")
    with open(nod, "w") as f:
        f.write('<nodes>\n')
        for i, (x, z) in enumerate(zip(xs, zs)):
            f.write('  <node id="n%d" x="%.4f" y="0" z="%.6f"/>\n' % (i, x, z))
        f.write('</nodes>\n')
    edg = os.path.join(NETS, tag + ".edg.xml")
    with open(edg, "w") as f:
        f.write('<edges>\n')
        for i, (eid, L, nl) in enumerate(FWY_SEG):
            f.write('  <edge id="%s" from="n%d" to="n%d" numLanes="%d" speed="%g"/>\n'
                    % (eid, i, i + 1, nl, FWY_SPEED))
        f.write('</edges>\n')
    net = os.path.join(NETS, tag + ".net.xml")
    # NOTE: --flatten would STRIP elevation; netconvert preserves z by default.
    netconvert(nod, edg, net)
    return net


def main():
    report = {}

    sig = build_signal()
    info, conns = inspect(sig)
    report["signal"] = dict(net=sig, edges={k: v for k, v in info.items()},
                            n_connections=len(conns))
    print("== testbed A: signalised cross ==")
    for e in sorted(info):
        print("   %-8s nlanes=%d  len=%.2f  speed=%.2f  grade=%.4f%%"
              % (e, info[e]["nlanes"], info[e]["lanes"][0]["length"],
                 info[e]["lanes"][0]["speed"], info[e]["lanes"][0]["grade_pct"]))

    report["freeway"] = {}
    for g in GRADES:
        net = build_freeway(g)
        info, conns = inspect(net)
        drop = [c for c in conns if c[0] == "main" and c[2] == "bneck"]
        # A genuine 3->1 lane drop: `main` has 3 lanes, `bneck` has 1, and only
        # ONE mainline lane continues -- the other two physically END, forcing an
        # upstream merge.  That is netconvert's standard lane-drop encoding.
        ok_drop = (info["main"]["nlanes"] == 3 and info["bneck"]["nlanes"] == 1
                   and len(drop) == 1 and drop[0][3] == "0")
        grades = {e: [round(l["grade_pct"], 4) for l in info[e]["lanes"]] for e in info}
        report["freeway"]["g%g" % g] = dict(
            net=net, intended_grade_pct=g,
            realised_grade_pct_per_lane=grades,
            grade_verified=all(abs(v - g) < 1e-3 for lst in grades.values() for v in lst),
            lane_drop_connections=drop, lane_drop_verified=bool(ok_drop),
            edge_nlanes={e: info[e]["nlanes"] for e in info},
            edge_lane_length={e: info[e]["lanes"][0]["length"] for e in info})
        print("== testbed B grade %g%% == drop_ok=%s grade_ok=%s realised=%s"
              % (g, ok_drop, report["freeway"]["g%g" % g]["grade_verified"],
                 grades["main"]))

    with open(os.path.join(WORK, "network_verification.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\nwritten", os.path.join(WORK, "network_verification.json"))


if __name__ == "__main__":
    main()
