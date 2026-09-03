"""Build + VERIFY the four testbeds for the dt study.

(a) ring        - single-lane closed ring, 1000 m, 16 nodes  -> FD/capacity, string stability
(b) appr        - single-lane signalized approach            -> saturation flow, lost time, stop-line accuracy
(c) merge       - 1-lane mainline + 1-lane on-ramp -> 1 lane -> SSM/TTC/PET/collisions
(d) x4_prio / x4_tls - identical 4-arm intersection, priority vs signal (retro-audit A2/A3)
"""
import os
import re
import math
import json
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import NET, netconvert, SUMO_HOME, savejson   # noqa

sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import sumolib   # noqa

REP = {}

RING_L = 1000.0
RING_N = 16
RING_V = 30.0


def w(pfx, nod, edg, con):
    for ext, body in ((".nod.xml", nod), (".edg.xml", edg), (".con.xml", con)):
        open(pfx + ext, "w").write("\n".join(body))


# ------------------------------------------------------------------ (a) ring
def build_ring():
    pfx = os.path.join(NET, "ring")
    c = RING_L / RING_N
    R = c / (2.0 * math.sin(math.pi / RING_N))
    nod = ["<nodes>"] + ['  <node id="n%d" x="%.6f" y="%.6f" type="priority"/>'
                         % (k, R * math.cos(2 * math.pi * k / RING_N),
                            R * math.sin(2 * math.pi * k / RING_N))
                         for k in range(RING_N)] + ["</nodes>"]
    edg = ["<edges>"] + ['  <edge id="e%d" from="n%d" to="n%d" numLanes="1" speed="%.3f" priority="1"/>'
                         % (k, k, (k + 1) % RING_N, RING_V) for k in range(RING_N)] + ["</edges>"]
    con = ["<connections>"] + ['  <connection from="e%d" to="e%d" fromLane="0" toLane="0"/>'
                               % (k, (k + 1) % RING_N) for k in range(RING_N)] + ["</connections>"]
    w(pfx, nod, edg, con)
    out = os.path.join(NET, "ring.net.xml")
    netconvert(pfx, out, ["--no-internal-links", "true", "--no-turnarounds", "true",
                          "--offset.disable-normalization", "true"])
    net = sumolib.net.readNet(out)
    E = net.getEdges()
    succ = {e.getID(): [o.getID() for o in e.getOutgoing()] for e in E}
    seen, cur = [], "e0"
    for _ in range(len(E) + 2):
        seen.append(cur)
        cur = succ[cur][0]
        if cur == "e0":
            break
    per = sum(e.getLane(0).getLength() for e in E)
    REP["ring"] = dict(n_edges=len(E), n_tls=len(net.getTrafficLights()),
                       n_internal=len([e for e in net.getEdges(withInternal=True) if e.isSpecial()]),
                       perimeter_m=round(per, 3), lanes=sorted({e.getLaneNumber() for e in E}),
                       speeds=sorted({round(e.getSpeed(), 3) for e in E}),
                       circular=(len(seen) == len(E) and cur == "e0"))
    REP["ring"]["PASS"] = (REP["ring"]["circular"] and REP["ring"]["n_tls"] == 0
                           and REP["ring"]["n_internal"] == 0
                           and REP["ring"]["lanes"] == [1]
                           and abs(per - RING_L) < 1.0)
    return per


# ------------------------------------------- (b) signalized single approach
APPR_IN = 600.0     # length of approach edge
APPR_OUT = 400.0
APPR_V = 13.89      # 50 km/h


def build_appr():
    pfx = os.path.join(NET, "appr")
    nod = ["<nodes>",
           '  <node id="a0" x="0" y="0" type="priority"/>',
           '  <node id="a1" x="%.1f" y="0" type="traffic_light"/>' % APPR_IN,
           '  <node id="a2" x="%.1f" y="0" type="priority"/>' % (APPR_IN + APPR_OUT),
           "</nodes>"]
    edg = ["<edges>",
           '  <edge id="ein" from="a0" to="a1" numLanes="1" speed="%.2f" priority="1"/>' % APPR_V,
           '  <edge id="eout" from="a1" to="a2" numLanes="1" speed="%.2f" priority="1"/>' % APPR_V,
           "</edges>"]
    con = ["<connections>", '  <connection from="ein" to="eout" fromLane="0" toLane="0"/>',
           "</connections>"]
    w(pfx, nod, edg, con)
    out = os.path.join(NET, "appr.net.xml")
    netconvert(pfx, out, ["--no-turnarounds", "true", "--offset.disable-normalization", "true",
                          "--tls.guess", "false"])
    net = sumolib.net.readNet(out)
    lin = net.getEdge("ein").getLane(0).getLength()
    tls = net.getTrafficLights()
    nlinks = len(tls[0].getLinks()) if tls else 0
    REP["appr"] = dict(ein_len=round(lin, 3), n_tls=len(tls), n_links=nlinks,
                       stopline_x=round(net.getEdge("ein").getLane(0).getShape()[-1][0], 3))
    REP["appr"]["PASS"] = (len(tls) == 1 and nlinks == 1)
    return REP["appr"]["stopline_x"]


# ------------------------------------------------------------------ (c) merge
def build_merge():
    pfx = os.path.join(NET, "merge")
    nod = ["<nodes>",
           '  <node id="m0" x="-800" y="0" type="priority"/>',
           '  <node id="m1" x="0" y="0" type="priority"/>',
           '  <node id="m2" x="800" y="0" type="priority"/>',
           '  <node id="r0" x="-300" y="-120" type="priority"/>',
           "</nodes>"]
    edg = ["<edges>",
           '  <edge id="main_up" from="m0" to="m1" numLanes="1" speed="25.0" priority="10"/>',
           '  <edge id="main_dn" from="m1" to="m2" numLanes="1" speed="25.0" priority="10"/>',
           '  <edge id="ramp" from="r0" to="m1" numLanes="1" speed="20.0" priority="1"/>',
           "</edges>"]
    con = ["<connections>",
           '  <connection from="main_up" to="main_dn" fromLane="0" toLane="0"/>',
           '  <connection from="ramp" to="main_dn" fromLane="0" toLane="0"/>',
           "</connections>"]
    w(pfx, nod, edg, con)
    out = os.path.join(NET, "merge.net.xml")
    netconvert(pfx, out, ["--no-turnarounds", "true", "--offset.disable-normalization", "true",
                          "--tls.guess", "false"])
    net = sumolib.net.readNet(out)
    raw = open(out).read()
    nint = raw.count('<edge id=":')
    # ramp must YIELD to the mainline: its request row must have a nonzero response
    reqs = re.findall(r'<request index="(\d+)" response="(\d+)"', raw)
    yields_ok = any(int(r) > 0 for _, r in reqs)
    REP["merge"] = dict(n_tls=len(net.getTrafficLights()), n_internal=nint,
                        n_requests=len(reqs), ramp_yields=yields_ok,
                        main_up=round(net.getEdge("main_up").getLane(0).getLength(), 2),
                        ramp=round(net.getEdge("ramp").getLane(0).getLength(), 2))
    REP["merge"]["PASS"] = (REP["merge"]["n_tls"] == 0 and nint > 0 and yields_ok)


# ------------------------------------------------- (d) 4-arm, prio vs signal
ARM = 250.0
X4_V = 13.89


def build_x4(kind):
    name = "x4_" + kind
    pfx = os.path.join(NET, name)
    ctype = "priority" if kind == "prio" else "traffic_light"
    nod = ["<nodes>", '  <node id="c" x="0" y="0" type="%s"/>' % ctype]
    dirs = dict(N=(0, ARM), S=(0, -ARM), E=(ARM, 0), W=(-ARM, 0))
    for d, (x, y) in dirs.items():
        nod.append('  <node id="%s" x="%.1f" y="%.1f" type="priority"/>' % (d, x, y))
    nod.append("</nodes>")
    edg = ["<edges>"]
    for d in dirs:
        edg.append('  <edge id="%s_in" from="%s" to="c" numLanes="1" speed="%.2f" priority="1"/>' % (d, d, X4_V))
        edg.append('  <edge id="%s_out" from="c" to="%s" numLanes="1" speed="%.2f" priority="1"/>' % (d, d, X4_V))
    edg.append("</edges>")
    opp = dict(N="S", S="N", E="W", W="E")
    con = ["<connections>"]
    for d in dirs:
        for o in dirs:
            if o == d:
                continue          # no U-turn
            con.append('  <connection from="%s_in" to="%s_out" fromLane="0" toLane="0"/>' % (d, o))
    con.append("</connections>")
    w(pfx, nod, edg, con)
    out = os.path.join(NET, name + ".net.xml")
    extra = ["--no-turnarounds", "true", "--offset.disable-normalization", "true"]
    extra += ["--tls.guess", "false"] if kind == "prio" else ["--tls.default-type", "static"]
    netconvert(pfx, out, extra)
    net = sumolib.net.readNet(out)
    REP[name] = dict(n_tls=len(net.getTrafficLights()),
                     arm_len=round(net.getEdge("N_in").getLane(0).getLength(), 2),
                     n_edges=len(net.getEdges()))
    REP[name]["PASS"] = ((len(net.getTrafficLights()) == (0 if kind == "prio" else 1))
                         and REP[name]["n_edges"] == 8)
    if kind == "tls":
        import xml.etree.ElementTree as ET
        root = ET.parse(out).getroot()
        ph = []
        for tl in root.findall("tlLogic"):
            for p in tl.findall("phase"):
                ph.append((p.get("duration"), p.get("state")))
        REP[name]["tls_phases"] = ph
        REP[name]["PASS"] = REP[name]["PASS"] and len(ph) >= 2


if __name__ == "__main__":
    build_ring()
    build_appr()
    build_merge()
    build_x4("prio")
    build_x4("tls")
    p = savejson("net_verification.json", REP)
    print(json.dumps(REP, indent=1))
    bad = [k for k, v in REP.items() if not v.get("PASS")]
    print("\nVERIFY:", "ALL PASS" if not bad else "FAILED: " + ",".join(bad))
    print("written ->", p)
