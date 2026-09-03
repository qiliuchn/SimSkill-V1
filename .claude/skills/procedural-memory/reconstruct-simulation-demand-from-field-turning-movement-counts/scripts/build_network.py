#!/usr/bin/env python3
"""
Build the 3-intersection signalized arterial test bed (plain XML + netconvert),
then overwrite netconvert's auto-generated tlLogic with a hand-built fixed-time
coordinated plan whose state strings are derived from the COMPILED link indices.

Geometry (see common.X for coordinates):

  WF ==2000m== [bay 80m] J1 ==200m== MB ==120m==[bay] J2 ==320m==[bay] J3 ==2080m== EF
                                     |
                                  driveway D1 (right-in / right-out, EB side only)

  Each Ji has a 250 m single-lane side street leg north (Ni) and south (Si).
  Each arterial approach: 2 through lanes (feed) widening to 3 lanes over the
  last 80 m, where lane 2 is an EXCLUSIVE left-turn bay and lane 0 carries
  through+right.
"""
import os
import xml.etree.ElementTree as ET

from common import (SCEN, NET, NETCONVERT, X, SIDE_Y, DWY, JUNCTIONS, CYCLE,
                    PH_ART_G, PH_ART_Y, PH_ART_AR, PH_LEFT_G, PH_LEFT_Y,
                    PH_LEFT_AR, PH_SIDE_G, PH_SIDE_Y, PH_SIDE_AR, OFFSETS, run,
                    EB_BAY, WB_BAY, EB_FEED, WB_FEED, SB_IN, NB_IN)

V_ART = 13.89
V_SIDE = 11.11
V_DWY = 8.33
BAY_LEN = 80.0

NOD = os.path.join(SCEN, "corridor.nod.xml")
EDG = os.path.join(SCEN, "corridor.edg.xml")
CON = os.path.join(SCEN, "corridor.con.xml")


def build_plain():
    nodes, edges, cons = [], [], []

    def node(nid, x, y, typ="priority"):
        nodes.append('  <node id="%s" x="%.2f" y="%.2f" type="%s"/>' % (nid, x, y, typ))

    def edge(eid, frm, to, lanes, speed):
        edges.append('  <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f"/>'
                     % (eid, frm, to, lanes, speed))

    def con(frm, to, fl, tl):
        cons.append('  <connection from="%s" to="%s" fromLane="%d" toLane="%d"/>'
                    % (frm, to, fl, tl))

    # ---- nodes
    node("WF", X["WF"], 0); node("EF", X["EF"], 0)
    node("bWF_J1", X["bWF_J1"], 0); node("bMB_J1", X["bMB_J1"], 0)
    node("bMB_J2", X["bMB_J2"], 0); node("bJ3_J2", X["bJ3_J2"], 0)
    node("bJ2_J3", X["bJ2_J3"], 0); node("bEF_J3", X["bEF_J3"], 0)
    node("MB", X["MB"], 0)
    node("D1", DWY[0], DWY[1])
    for j in JUNCTIONS:
        node(j, X[j], 0, "traffic_light")
        node("N" + j[-1], X[j], SIDE_Y)
        node("S" + j[-1], X[j], -SIDE_Y)

    # ---- arterial eastbound chain
    edge("eb_WF_J1_feed", "WF", "bWF_J1", 2, V_ART)
    edge("eb_WF_J1_bay", "bWF_J1", "J1", 3, V_ART)
    edge("eb_J1_MB", "J1", "MB", 2, V_ART)
    edge("eb_MB_J2_feed", "MB", "bMB_J2", 2, V_ART)
    edge("eb_MB_J2_bay", "bMB_J2", "J2", 3, V_ART)
    edge("eb_J2_J3_feed", "J2", "bJ2_J3", 2, V_ART)
    edge("eb_J2_J3_bay", "bJ2_J3", "J3", 3, V_ART)
    edge("eb_J3_EF", "J3", "EF", 2, V_ART)
    # ---- arterial westbound chain
    edge("wb_EF_J3_feed", "EF", "bEF_J3", 2, V_ART)
    edge("wb_EF_J3_bay", "bEF_J3", "J3", 3, V_ART)
    edge("wb_J3_J2_feed", "J3", "bJ3_J2", 2, V_ART)
    edge("wb_J3_J2_bay", "bJ3_J2", "J2", 3, V_ART)
    edge("wb_J2_MB", "J2", "MB", 2, V_ART)
    edge("wb_MB_J1_feed", "MB", "bMB_J1", 2, V_ART)
    edge("wb_MB_J1_bay", "bMB_J1", "J1", 3, V_ART)
    edge("wb_J1_WF", "J1", "WF", 2, V_ART)
    # ---- side streets
    for j in JUNCTIONS:
        i = j[-1]
        edge("sN%s_in" % i, "N" + i, j, 1, V_SIDE)
        edge("sN%s_out" % i, j, "N" + i, 1, V_SIDE)
        edge("sS%s_in" % i, "S" + i, j, 1, V_SIDE)
        edge("sS%s_out" % i, j, "S" + i, 1, V_SIDE)
    # ---- mid-block driveway (right-in / right-out on the EB side)
    edge("dw_in", "D1", "MB", 1, V_DWY)
    edge("dw_out", "MB", "D1", 1, V_DWY)

    # ---- feed -> bay connections (2 lanes widening to 3)
    for feed, bay in [(EB_FEED[j], EB_BAY[j]) for j in JUNCTIONS] + \
                     [(WB_FEED[j], WB_BAY[j]) for j in JUNCTIONS]:
        con(feed, bay, 0, 0); con(feed, bay, 0, 1)
        con(feed, bay, 1, 1); con(feed, bay, 1, 2)

    # ---- junction connections
    eb_down = {"J1": "eb_J1_MB", "J2": "eb_J2_J3_feed", "J3": "eb_J3_EF"}
    wb_down = {"J3": "wb_J3_J2_feed", "J2": "wb_J2_MB", "J1": "wb_J1_WF"}
    for j in JUNCTIONS:
        i = j[-1]
        ebb, wbb = EB_BAY[j], WB_BAY[j]
        # eastbound: lane0 through+right, lane1 through, lane2 left
        con(ebb, eb_down[j], 0, 0); con(ebb, eb_down[j], 1, 1)
        con(ebb, "sS%s_out" % i, 0, 0)          # EB right -> south leg
        con(ebb, "sN%s_out" % i, 2, 0)          # EB left  -> north leg
        # westbound
        con(wbb, wb_down[j], 0, 0); con(wbb, wb_down[j], 1, 1)
        con(wbb, "sN%s_out" % i, 0, 0)          # WB right -> north leg
        con(wbb, "sS%s_out" % i, 2, 0)          # WB left  -> south leg
        # southbound approach (from north leg): T -> south leg, L -> east, R -> west
        con("sN%s_in" % i, "sS%s_out" % i, 0, 0)
        con("sN%s_in" % i, eb_down[j], 0, 0)
        con("sN%s_in" % i, wb_down[j], 0, 1)
        # northbound approach (from south leg): T -> north leg, L -> west, R -> east
        con("sS%s_in" % i, "sN%s_out" % i, 0, 0)
        con("sS%s_in" % i, wb_down[j], 0, 0)
        con("sS%s_in" % i, eb_down[j], 0, 1)

    # ---- mid-block node MB: right-in / right-out only
    con("eb_J1_MB", "eb_MB_J2_feed", 0, 0)
    con("eb_J1_MB", "eb_MB_J2_feed", 1, 1)
    con("eb_J1_MB", "dw_out", 0, 0)
    con("dw_in", "eb_MB_J2_feed", 0, 0)
    con("wb_J2_MB", "wb_MB_J1_feed", 0, 0)
    con("wb_J2_MB", "wb_MB_J1_feed", 1, 1)

    with open(NOD, "w") as f:
        f.write('<nodes>\n' + "\n".join(nodes) + '\n</nodes>\n')
    with open(EDG, "w") as f:
        f.write('<edges>\n' + "\n".join(edges) + '\n</edges>\n')
    with open(CON, "w") as f:
        f.write('<connections>\n' + "\n".join(cons) + '\n</connections>\n')


def compile_net():
    run([NETCONVERT, "-n", NOD, "-e", EDG, "-x", CON, "-o", NET,
         "--no-turnarounds", "true", "--tls.default-type", "static",
         "--default.junctions.keep-clear", "true",
         "--no-internal-links", "false", "--offset.disable-normalization", "true"])


# --------------------------------------------------------------- signal plan
def controlled_links(net_root, tls_id):
    """[(linkIndex, fromEdge, fromLane, toEdge, dir)] for one traffic light."""
    out = []
    for c in net_root.findall("connection"):
        if c.get("tl") == tls_id:
            out.append((int(c.get("linkIndex")), c.get("from"), int(c.get("fromLane")),
                        c.get("to"), c.get("dir")))
    out.sort()
    return out


def build_program(links, j):
    """Return list of (duration, state) for the fixed-time coordinated plan."""
    n = len(links)
    art_bays = {EB_BAY[j], WB_BAY[j]}
    side_in = {SB_IN[j], NB_IN[j]}

    grp = []
    for idx, frm, fl, to, d in links:
        if frm in art_bays:
            grp.append("art_left" if d == "l" else "art_tr")
        elif frm in side_in:
            grp.append("side")
        else:
            raise RuntimeError("unexpected controlled link %s at %s" % (frm, j))

    def state(active):
        return "".join("G" if g in active else "r" for g in grp)

    def yellow(active, nxt):
        # links green in `active` that are not green in `nxt` show yellow
        return "".join("y" if (g in active and g not in nxt) else
                       ("G" if g in active else "r") for g in grp)

    phases = [
        (PH_ART_G, state({"art_tr"})),
        (PH_ART_Y, yellow({"art_tr"}, set())),
        (PH_ART_AR, state(set())),
        (PH_LEFT_G, state({"art_left"})),
        (PH_LEFT_Y, yellow({"art_left"}, set())),
        (PH_LEFT_AR, state(set())),
        (PH_SIDE_G, state({"side"})),
        (PH_SIDE_Y, yellow({"side"}, set())),
        (PH_SIDE_AR, state(set())),
    ]
    assert sum(p[0] for p in phases) == CYCLE, sum(p[0] for p in phases)
    return phases, grp


def inject_program():
    tree = ET.parse(NET)
    root = tree.getroot()
    info = {}
    for j in JUNCTIONS:
        links = controlled_links(root, j)
        phases, grp = build_program(links, j)
        info[j] = dict(nlinks=len(links), groups=grp,
                       links=[(i, f, l, t, d) for i, f, l, t, d in links],
                       phases=phases, offset=OFFSETS[j])
        old = None
        for tl in root.findall("tlLogic"):
            if tl.get("id") == j:
                old = tl
        assert old is not None, "no tlLogic for " + j
        for ch in list(old):
            old.remove(ch)
        old.set("type", "static")
        old.set("programID", "0")
        old.set("offset", str(OFFSETS[j]))
        for dur, st in phases:
            ph = ET.SubElement(old, "phase")
            ph.set("duration", str(dur))
            ph.set("state", st)
    tree.write(NET, encoding="UTF-8", xml_declaration=True)
    return info


if __name__ == "__main__":
    build_plain()
    compile_net()
    info = inject_program()
    for j in JUNCTIONS:
        print("=== %s  offset=%d  links=%d" % (j, info[j]["offset"], info[j]["nlinks"]))
        for (idx, frm, fl, to, d), g in zip(info[j]["links"], info[j]["groups"]):
            print("   %2d  %-16s lane%d -> %-16s dir=%s  group=%s" % (idx, frm, fl, to, d, g))
        for dur, st in info[j]["phases"]:
            print("   phase %3s  %s" % (dur, st))
    print("\nnetwork written:", NET)
