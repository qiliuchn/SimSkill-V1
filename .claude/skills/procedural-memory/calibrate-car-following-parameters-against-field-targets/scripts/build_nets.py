#!/usr/bin/env python3
"""Build + VERIFY the three testbeds from the COMPILED net (never from the
plain-XML inputs).  Writes outputs/net/*.net.xml and outputs/net/verify.json.
"""
import os, sys, math, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import (NETDIR, NETCONVERT, RING_L, RING_N_EDGES, FREE_SPEED,
                       SIG_SPEED, RING_NET, RING_NET_1L, RING_LANES, FWY_NET, SIG_NET)
sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib

os.makedirs(NETDIR, exist_ok=True)
REP = {}


def nc(prefix, out, extra=()):
    cmd = [NETCONVERT, "--node-files", prefix + ".nod.xml",
           "--edge-files", prefix + ".edg.xml",
           "--connection-files", prefix + ".con.xml",
           "--output-file", out] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr); sys.exit("netconvert failed for " + out)


# ============================== 1. RING ====================================
def build_ring(lanes=1, name="ring"):
    pfx = os.path.join(NETDIR, name)
    c = RING_L / RING_N_EDGES
    R = c / (2.0 * math.sin(math.pi / RING_N_EDGES))
    nod = ["<nodes>"] + [
        '  <node id="n%d" x="%.6f" y="%.6f" type="priority"/>'
        % (k, R * math.cos(2 * math.pi * k / RING_N_EDGES),
           R * math.sin(2 * math.pi * k / RING_N_EDGES))
        for k in range(RING_N_EDGES)] + ["</nodes>"]
    edg = ["<edges>"] + [
        '  <edge id="e%d" from="n%d" to="n%d" numLanes="%d" speed="%s" priority="1"/>'
        % (k, k, (k + 1) % RING_N_EDGES, lanes, FREE_SPEED) for k in range(RING_N_EDGES)] + ["</edges>"]
    con = ["<connections>"] + [
        '  <connection from="e%d" to="e%d" fromLane="%d" toLane="%d"/>'
        % (k, (k + 1) % RING_N_EDGES, l, l)
        for k in range(RING_N_EDGES) for l in range(lanes)] + ["</connections>"]
    for ext, body in ((".nod.xml", nod), (".edg.xml", edg), (".con.xml", con)):
        open(pfx + ext, "w").write("\n".join(body))
    netout = os.path.join(NETDIR, name + ".net.xml")
    nc(pfx, netout, ["--no-internal-links", "true", "--no-turnarounds", "true",
                     "--offset.disable-normalization", "true"])
    net = sumolib.net.readNet(netout)
    E = net.getEdges()
    succ = {e.getID(): [o.getID() for o in e.getOutgoing()] for e in E}
    seen, cur = [], "e0"
    for _ in range(len(E) + 2):
        seen.append(cur); cur = succ[cur][0]
        if cur == "e0":
            break
    REP[name] = dict(
        n_edges=len(E),
        n_internal=len([e for e in net.getEdges(withInternal=True) if e.isSpecial()]),
        n_tls=len(net.getTrafficLights()),
        lane_counts=sorted(set(e.getLaneNumber() for e in E)),
        speeds_ms=sorted(set(round(e.getSpeed(), 4) for e in E)),
        perimeter_m=round(sum(e.getLane(0).getLength() for e in E), 4),
        requested_L=RING_L,
        circular=(len(seen) == len(E) and cur == "e0"
                  and all(len(v) == 1 for v in succ.values())))
    REP[name]["PASS"] = (REP[name]["circular"] and REP[name]["n_tls"] == 0
                         and REP[name]["n_internal"] == 0
                         and REP[name]["lane_counts"] == [lanes]
                         and abs(REP[name]["perimeter_m"] - RING_L) < 1.0)


# ============================ 2. FREEWAY ===================================
# x:  0 --in(3ln,500)--> 500 --main(3ln,2500)--> 3000 --merge(3ln,500)-->
#     3500 --out(2LN,1000)--> 4500        ramp: (2600,-120) --1ln--> 3000
# E1 station at pos 2000 on 'main'  (x = 2500), 500 m upstream of the merge
# nose and 1000 m upstream of the lane drop.
FWY_STATION_POS = 2000.0
FWY_MAIN_LANES = 3
FWY_OUT_LANES = 2


def build_fwy(out_lanes=3, name="fwy"):
    global OUT_LANES
    OUT_LANES = out_lanes
    pfx = os.path.join(NETDIR, name)
    nodes = [("f0", 0, 0), ("f1", 500, 0), ("f2", 3000, 0), ("f3", 3500, 0),
             ("f4", 4500, 0), ("r0", 2400, -150)]
    edges = [("in", "f0", "f1", 3, FREE_SPEED),
             ("main", "f1", "f2", 3, FREE_SPEED),
             ("merge", "f2", "f3", 3, FREE_SPEED),
             ("out", "f3", "f4", OUT_LANES, FREE_SPEED),
             ("ramp", "r0", "f2", 1, 25.0)]
    nod = ["<nodes>"] + ['  <node id="%s" x="%d" y="%d" type="priority"/>' % n
                         for n in nodes] + ["</nodes>"]
    edg = ["<edges>"] + [
        '  <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%s" priority="%d"/>'
        % (i, f, t, l, s, 1 if i == "ramp" else 10) for i, f, t, l, s in edges] + ["</edges>"]
    con = ["<connections>"]
    for a, b in (("in", "main"), ("main", "merge")):
        for l in range(3):
            con.append('  <connection from="%s" to="%s" fromLane="%d" toLane="%d"/>' % (a, b, l, l))
    if OUT_LANES == 3:
        for l in range(3):
            con.append('  <connection from="merge" to="out" fromLane="%d" toLane="%d"/>' % (l, l))
    else:   # severe variant: lane drop 3 -> 2, lane 2 must merge
        con.append('  <connection from="merge" to="out" fromLane="0" toLane="0"/>')
        con.append('  <connection from="merge" to="out" fromLane="1" toLane="1"/>')
        con.append('  <connection from="merge" to="out" fromLane="2" toLane="1"/>')
    con.append('  <connection from="ramp" to="merge" fromLane="0" toLane="0"/>')
    con.append("</connections>")
    for ext, body in ((".nod.xml", nod), (".edg.xml", edg), (".con.xml", con)):
        open(pfx + ext, "w").write("\n".join(body))
    netout = os.path.join(NETDIR, name + ".net.xml")
    nc(pfx, netout, ["--no-turnarounds", "true",
                      "--offset.disable-normalization", "true",
                      "--default.lanenumber", "3"])
    net = sumolib.net.readNet(netout)
    lanes = {e.getID(): (e.getLaneNumber(), round(e.getLength(), 2), round(e.getSpeed(), 3))
             for e in net.getEdges()}
    main = net.getEdge("main")
    conns = {}
    for eid in ("in", "main", "merge", "ramp"):
        e = net.getEdge(eid)
        conns[eid] = sorted((c.getFromLane().getIndex(), c.getTo().getID(),
                             c.getToLane().getIndex())
                            for ll in e.getLanes() for c in ll.getOutgoing())
    REP[name] = dict(
        edges=lanes, n_tls=len(net.getTrafficLights()),
        mainline_length_m=round(sum(lanes[e][1] for e in ("in", "main", "merge", "out")), 2),
        station_pos_on_main=FWY_STATION_POS,
        station_x=round(lanes["in"][1] + FWY_STATION_POS, 1),
        connections=conns,
        out_lanes=lanes["out"][0],
        lane_drop_verified=(lanes["merge"][0] == 3
                            and lanes["out"][0] == out_lanes
                            and len(conns["merge"]) == 3),
        ramp_merge_verified=(lanes["ramp"][0] == 1 and len(conns["ramp"]) == 1),
        station_upstream_of_merge=(FWY_STATION_POS < lanes["main"][1]))
    REP[name]["PASS"] = (REP[name]["lane_drop_verified"]
                         and REP[name]["ramp_merge_verified"]
                         and REP[name]["n_tls"] == 0
                         and 3000 <= REP[name]["mainline_length_m"] <= 5000)


# ========================= 3. SIGNALISED APPROACH ==========================
def build_sig():
    pfx = os.path.join(NETDIR, "sig")
    arms = {"N": (0, 400), "S": (0, -400), "E": (400, 0), "W": (-400, 0)}
    nod = ['<nodes>', '  <node id="C" x="0" y="0" type="traffic_light"/>']
    for a, (x, y) in arms.items():
        nod.append('  <node id="%s" x="%d" y="%d" type="priority"/>' % (a, x, y))
    nod.append("</nodes>")
    edg = ["<edges>"]
    for a in arms:
        edg.append('  <edge id="in_%s" from="%s" to="C" numLanes="1" speed="%s" priority="10"/>' % (a, a, SIG_SPEED))
        edg.append('  <edge id="out_%s" from="C" to="%s" numLanes="1" speed="%s" priority="10"/>' % (a, a, SIG_SPEED))
    edg.append("</edges>")
    opp = {"N": "S", "S": "N", "E": "W", "W": "E"}
    con = ["<connections>"]
    for a in arms:
        for b in arms:
            if b == a:
                continue
            con.append('  <connection from="in_%s" to="out_%s" fromLane="0" toLane="0"/>' % (a, b))
    con.append("</connections>")
    for ext, body in ((".nod.xml", nod), (".edg.xml", edg), (".con.xml", con)):
        open(pfx + ext, "w").write("\n".join(body))
    nc(pfx, SIG_NET, ["--no-turnarounds", "true", "--offset.disable-normalization", "true",
                      "--tls.default-type", "static"])
    net = sumolib.net.readNet(SIG_NET)
    tls = net.getTrafficLights()
    links = tls[0].getLinks() if tls else {}
    idx = {}
    for li, conns in links.items():
        for (inl, outl, _) in conns:
            idx[li] = (inl.getID(), outl.getID())
    REP["signal"] = dict(
        n_tls=len(tls), n_controlled_links=len(idx),
        link_map={str(k): "%s->%s" % v for k, v in sorted(idx.items())},
        approach_len_m=round(net.getEdge("in_N").getLength(), 2),
        approach_lanes=net.getEdge("in_N").getLaneNumber(),
        speed_ms=round(net.getEdge("in_N").getSpeed(), 3))
    # find the four through-movement link indices
    thr = {}
    for k, (i, o) in idx.items():
        a = i.split("_")[1]; b = o.split("_")[1]
        if (a, b) in (("N", "S"), ("S", "N"), ("E", "W"), ("W", "E")):
            thr["%s%s" % (a, b)] = k
    REP["signal"]["through_links"] = thr
    REP["signal"]["PASS"] = (len(tls) == 1 and len(thr) == 4
                             and REP["signal"]["approach_lanes"] == 1)


# NOTE: RING_NET points at the 2-LANE ring (see cf_common).  Writing the
# 1-lane ring to RING_NET would silently replace the calibration instrument --
# that actually happened once here and corrupted a running optimisation.
build_ring(1, "ring")
build_ring(RING_LANES, os.path.basename(RING_NET).replace(".net.xml", ""))
build_fwy(3, "fwy"); build_fwy(2, "fwy_drop"); build_sig()
json.dump(REP, open(os.path.join(NETDIR, "verify.json"), "w"), indent=2)
print(json.dumps(REP, indent=2))
print("\nALL PASS:", all(v["PASS"] for v in REP.values()))
