#!/usr/bin/env python3
"""Build the monocentric city network (base / policy A / policy B) + TAZ zone system.

Topology: netgenerate spider, 8 arms x 6 concentric circles, 500 m ring spacing
(=> 3 km radius).  A road hierarchy is imposed by rewriting the plain XML:
  * radial arms          -> arterials (2 lanes)
  * ring C (1000 m), E (2000 m) -> ring arterials (2 lanes)
  * ring B, D, F, G      -> local streets (1 lane, 30 km/h)  == the "local grid" layer
  * peripheral low-income sectors (4..7) get 1-lane, 40 km/h outer radials and a
    ONE-WAY outer ring G (poor road connectivity by design)

Zones: 25 TAZs = 1 core + 8 inner + 8 middle + 8 outer, defined by polar band x
angular sector of each edge's midpoint.  Sector k spans [ (k-1)*45deg , k*45deg ).
"""
import math
import os
import subprocess
import sys
import json
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

WORK = sys.argv[1] if len(sys.argv) > 1 else "work"
os.makedirs(WORK, exist_ok=True)

ARMS, CIRCLES, SPACE = 8, 6, 500.0
LOW_INCOME_SECTORS = [4, 5, 6, 7]          # peripheral, poorly connected
AFFLUENT_SECTORS = [1, 2, 8]               # inner ring served by the arm-1 radial

BANDS = [("CORE", 0.0, 1100.0), ("INNER", 1100.0, 1900.0),
         ("MID", 1900.0, 2500.0), ("OUTER", 2500.0, 1e9)]


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:]);  print(r.stderr[-3000:])
        raise SystemExit("command failed: " + " ".join(cmd))
    return r


# ---------------------------------------------------------------- 1. plain net
run(["netgenerate", "--spider",
     "--spider.arm-number", str(ARMS), "--spider.circle-number", str(CIRCLES),
     "--spider.space-radius", str(SPACE),
     "--default.lanenumber", "2", "--default.speed", "13.89", "-j", "priority",
     "--plain-output-prefix", os.path.join(WORK, "plain"),
     "-o", os.path.join(WORK, "spider_raw.net.xml")])

nod = ET.parse(os.path.join(WORK, "plain.nod.xml")).getroot()
NODE = {n.get("id"): (float(n.get("x")), float(n.get("y"))) for n in nod.findall("node")}
CX, CY = NODE["A1"]
POLAR = {k: (math.hypot(x - CX, y - CY), math.degrees(math.atan2(y - CY, x - CX)) % 360.0)
         for k, (x, y) in NODE.items()}
RING_LETTER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6}


def zone_of(x, y):
    r = math.hypot(x - CX, y - CY)
    a = math.degrees(math.atan2(y - CY, x - CX)) % 360.0
    band = next(b for b, lo, hi in BANDS if lo <= r < hi)
    if band == "CORE":
        return "CORE"
    sector = int(a // 45.0) + 1          # 1..8
    return "%s_%d" % (band, sector)


def arm_of_node(nid):
    return int(nid[1:])


def is_radial(frm, to):
    return frm[0] != to[0]


def sector_of_ring_edge(frm, to):
    """ring edge between arm k and arm k+1 -> sector k"""
    a, b = arm_of_node(frm), arm_of_node(to)
    if (a, b) in ((ARMS, 1), (1, ARMS)):
        return ARMS
    return min(a, b)


# ------------------------------------------------------- 2. impose hierarchy
edg_tree = ET.parse(os.path.join(WORK, "plain.edg.xml"))
edg_root = edg_tree.getroot()

edge_meta = {}
to_delete = []
for e in list(edg_root.findall("edge")):
    eid, frm, to = e.get("id"), e.get("from"), e.get("to")
    radial = is_radial(frm, to)
    if radial:
        outer_letter = max(frm[0], to[0])
        ring_idx = RING_LETTER[outer_letter]          # segment ends at this ring
        arm = arm_of_node(frm if frm[0] != "A" else to)
        sector = arm
        kind = "radial"
        lanes, speed = 2, 16.67                       # radial arterial 60 km/h
        if arm % 2 == 0:
            speed = 13.89                             # minor radial 50 km/h
        if sector in LOW_INCOME_SECTORS and ring_idx >= 5:   # E-F and F-G segments
            lanes, speed = 1, 11.11                   # degraded peripheral radial
    else:
        ring_idx = RING_LETTER[frm[0]]
        sector = sector_of_ring_edge(frm, to)
        kind = "ring"
        if ring_idx in (2, 4):                        # ring C (1000 m), ring E (2000 m)
            lanes, speed = 2, 13.89                   # ring arterial
        else:
            lanes, speed = 1, 8.33                    # local street 30 km/h
        # one-way outer ring in the low-income periphery (clockwise-only G_k -> G_k+1)
        if ring_idx == 6 and sector in LOW_INCOME_SECTORS:
            a, b = arm_of_node(frm), arm_of_node(to)
            forward = (b == a + 1) or (a == ARMS and b == 1)
            if not forward:
                to_delete.append(e)
                continue
    e.set("numLanes", str(lanes))
    e.set("speed", "%.2f" % speed)
    e.set("priority", "3" if lanes == 2 else "1")
    mx, my = (NODE[frm][0] + NODE[to][0]) / 2.0, (NODE[frm][1] + NODE[to][1]) / 2.0
    edge_meta[eid] = dict(frm=frm, to=to, kind=kind, ring=ring_idx, sector=sector,
                          lanes=lanes, speed=speed, zone=zone_of(mx, my),
                          x=mx, y=my, r=math.hypot(mx - CX, my - CY))
for e in to_delete:
    edg_root.remove(e)
print("deleted one-way-ring edges:", len(to_delete))

edg_tree.write(os.path.join(WORK, "base.edg.xml"))

# policy A: widen + speed-up the arm-1 radial corridor (A1-B1-C1-D1-E1-F1), serving
# the affluent inner ring.  2 -> 3 lanes, 60 -> 70 km/h.
CORRIDOR_A, RINGUP_A = [], []
for eid, m in edge_meta.items():
    if m["kind"] == "radial" and m["sector"] == 1:
        CORRIDOR_A.append(eid)                       # whole arm-1 radial, A1..G1
    if m["kind"] == "ring" and m["ring"] in (3, 4) and m["sector"] in (8, 1):
        RINGUP_A.append(eid)                         # ring D/E links of the affluent ring
treeA = ET.parse(os.path.join(WORK, "base.edg.xml"))
for e in treeA.getroot().findall("edge"):
    if e.get("id") in CORRIDOR_A:
        e.set("numLanes", "3")
        e.set("speed", "19.44")
    elif e.get("id") in RINGUP_A:
        e.set("numLanes", "2")
        e.set("speed", "16.67")
        e.set("priority", "3")
treeA.write(os.path.join(WORK, "altA.edg.xml"))
print("policy A widened radial edges:", len(CORRIDOR_A), sorted(CORRIDOR_A))
print("policy A upgraded ring edges:", len(RINGUP_A), sorted(RINGUP_A))

# ------------------------------------------------------- 3. netconvert passes
TLS = ["A1"] + ["%s%d" % (L, k) for L in "BCDEF" for k in range(1, 9)]
for tag, edgf in (("base", "base.edg.xml"), ("altA", "altA.edg.xml")):
    run(["netconvert",
         "-n", os.path.join(WORK, "plain.nod.xml"),
         "-e", os.path.join(WORK, edgf),
         "--sidewalks.guess", "--sidewalks.guess.max-speed", "25",
         "--crossings.guess", "--walkingareas",
         "--tls.set", ",".join(TLS), "--tls.default-type", "static",
         "--no-turnarounds",
         "-o", os.path.join(WORK, "%s.net.xml" % tag)])

# policy B uses the base road network (transit-only intervention)
import shutil
shutil.copy(os.path.join(WORK, "base.net.xml"), os.path.join(WORK, "altB.net.xml"))

# ------------------------------------------------------- 4. zones + TAZ file
net = sumolib.net.readNet(os.path.join(WORK, "base.net.xml"))
zones = {}
for e in net.getEdges():
    eid = e.getID()
    if eid.startswith(":"):
        continue
    if not e.allows("passenger"):
        continue
    # zone assignment uses the EXACT node-based midpoint (edge_meta), not the lane
    # shape centroid: lane offsets push a radial edge lying exactly on a sector
    # boundary into the neighbouring sector (a real boundary/MAUP artefact).
    m = edge_meta[eid]
    mx, my, z = m["x"], m["y"], m["zone"]
    zones.setdefault(z, []).append(dict(id=eid, x=mx, y=my, length=e.getLength(),
                                        lanes=e.getLaneNumber(), speed=e.getSpeed()))

# centroid connector edge per zone = edge whose midpoint is nearest the zone centroid
zone_info = {}
for z, es in zones.items():
    zx = sum(e["x"] * e["length"] for e in es) / sum(e["length"] for e in es)
    zy = sum(e["y"] * e["length"] for e in es) / sum(e["length"] for e in es)
    # prefer a two-way edge (one whose reverse exists) so that the zone can be both
    # entered and left from its connector; then take the one nearest the centroid
    have = {e["id"] for e in es}
    two_way = [e for e in es
               if any(o.getID() in have for o in net.getEdge(e["id"]).getToNode().getOutgoing()
                      if o.getToNode() == net.getEdge(e["id"]).getFromNode())]
    pool = two_way or es
    best = min(pool, key=lambda e: math.hypot(e["x"] - zx, e["y"] - zy))
    zone_info[z] = dict(centroid=[zx, zy], connector=best["id"],
                        edges=[e["id"] for e in es],
                        n_edges=len(es),
                        r=math.hypot(zx - CX, zy - CY),
                        theta=math.degrees(math.atan2(zy - CY, zx - CX)) % 360.0,
                        lane_km=sum(e["length"] * e["lanes"] for e in es) / 1000.0)

with open(os.path.join(WORK, "taz.add.xml"), "w") as f:
    f.write("<additional>\n")
    for z in sorted(zone_info):
        f.write('    <taz id="%s">\n' % z)
        tot = sum(net.getEdge(e).getLength() for e in zone_info[z]["edges"])
        for e in zone_info[z]["edges"]:
            w = net.getEdge(e).getLength() / tot
            f.write('        <tazSource id="%s" weight="%.5f"/>\n' % (e, w))
            f.write('        <tazSink id="%s" weight="%.5f"/>\n' % (e, w))
        f.write("    </taz>\n")
    f.write("</additional>\n")

json.dump(dict(zones=zone_info, center=[CX, CY], edge_meta=edge_meta,
               corridor_A=sorted(CORRIDOR_A), ringup_A=sorted(RINGUP_A),
               low_income_sectors=LOW_INCOME_SECTORS),
          open(os.path.join(WORK, "zones.json"), "w"), indent=1)

print("\nzones: %d" % len(zone_info))
for z in sorted(zone_info):
    zi = zone_info[z]
    print("  %-9s edges=%2d connector=%-8s r=%6.0f theta=%5.1f laneKm=%5.2f"
          % (z, zi["n_edges"], zi["connector"], zi["r"], zi["theta"], zi["lane_km"]))
