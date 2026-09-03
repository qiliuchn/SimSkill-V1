#!/usr/bin/env python3
"""
Build the driveway-TIA network variants from plain XML + netconvert.

Geometry (identical across every variant except where noted):

                       N  (development driveway, 250 m stub)
                       |
   W ---- maj_W_feed --+-- maj_W_bay ---- C ---- maj_out_E ---- E
     <--- maj_out_W ------------------- C <-- maj_E_bay -- maj_E_feed ---
                       |
                       S  (existing minor street, 250 m)

* Major arterial E-W : 2 through lanes per direction, 55 km/h (15.28 m/s),
  edge priority 3.  The last 100 m of each approach widens to 3 lanes:
  lane 0 = through+right, lane 1 = through, lane 2 = EXCLUSIVE LEFT-TURN BAY.
  The EB (from W) bay is the major-street left-turn bay INTO THE SITE.
* Minor street / driveway N-S : 1 lane per approach, 40 km/h, edge priority 1.
* Fringe nodes W and E carry an explicit U-turn connection, used only by the
  right-in/right-out (RIRO) mitigation's re-routed site trips.

Variants
  twsc        center junction type = priority   (two-way stop control)
  signal      center junction type = traffic_light
  twsc_rt     TWSC + driveway widened to 2 lanes (exclusive right-turn lane)
  twsc_riro   TWSC + driveway restricted to right-in / right-out by CONNECTIONS
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SCEN, find_bin, run, write

NET = os.path.join(SCEN, "net")
os.makedirs(NET, exist_ok=True)

MAJ_SPEED = 15.28      # m/s  = 55.0 km/h posted
MIN_SPEED = 11.11      # m/s  = 40 km/h  (minor street)
DRW_SPEED = 8.33       # m/s  = 30 km/h  (driveway)
# Node spacings are pre-compensated for netconvert's junction-radius shortening
# so that the COMPILED lane lengths land on the intended design values
# (bay 100 m, feed 300 m, minor arm 250 m).  Verified in network_verification.txt.
BAY_LEN = 111.2        # m  node spacing -> compiled left-turn bay storage ~100 m
FEED_LEN = 304.0       # m  node spacing -> compiled 2-lane upstream feed ~300 m
MINOR_LEN = 263.6      # m  node spacing -> compiled minor/driveway arm ~250 m
DESIGN = {"bay": 100.0, "feed": 300.0, "minor": 250.0}
MAJ_PRIO, MIN_PRIO = 3, 1

NODES = {
    "C":  (0.0, 0.0),
    "WB": (-BAY_LEN, 0.0),
    "EB": (BAY_LEN, 0.0),
    "W":  (-(BAY_LEN + FEED_LEN), 0.0),
    "E":  (BAY_LEN + FEED_LEN, 0.0),
    "N":  (0.0, MINOR_LEN),
    "S":  (0.0, -MINOR_LEN),
}


def edge_xml(driveway_lanes):
    e = []
    a = e.append
    a('<?xml version="1.0" encoding="UTF-8"?>')
    a("<edges>")
    # EB direction  W -> WB -> C -> E
    a(f'  <edge id="maj_W_feed" from="W"  to="WB" numLanes="2" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    a(f'  <edge id="maj_W_bay"  from="WB" to="C"  numLanes="3" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    a(f'  <edge id="maj_out_E"  from="C"  to="E"  numLanes="2" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    # WB direction  E -> EB -> C -> W
    a(f'  <edge id="maj_E_feed" from="E"  to="EB" numLanes="2" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    a(f'  <edge id="maj_E_bay"  from="EB" to="C"  numLanes="3" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    a(f'  <edge id="maj_out_W"  from="C"  to="W"  numLanes="2" speed="{MAJ_SPEED}" priority="{MAJ_PRIO}"/>')
    # driveway (N) and minor street (S)
    a(f'  <edge id="drw_N_in"   from="N"  to="C"  numLanes="{driveway_lanes}" speed="{DRW_SPEED}" priority="{MIN_PRIO}"/>')
    a(f'  <edge id="drw_N_out"  from="C"  to="N"  numLanes="1" speed="{DRW_SPEED}" priority="{MIN_PRIO}"/>')
    a(f'  <edge id="min_S_in"   from="S"  to="C"  numLanes="1" speed="{MIN_SPEED}" priority="{MIN_PRIO}"/>')
    a(f'  <edge id="min_S_out"  from="C"  to="S"  numLanes="1" speed="{MIN_SPEED}" priority="{MIN_PRIO}"/>')
    a("</edges>")
    return "\n".join(e) + "\n"


def node_xml(center_type):
    e = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for nid, (x, y) in NODES.items():
        t = center_type if nid == "C" else "priority"
        e.append(f'  <node id="{nid}" x="{x}" y="{y}" type="{t}"/>')
    e.append("</nodes>")
    return "\n".join(e) + "\n"


def conn_xml(driveway_lanes, riro):
    """Explicit connections: bay access, all centre movements, fringe U-turns."""
    c = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    a = c.append
    # ---- feed -> bay (lane 1 also feeds the bay lane 2)
    for side in ("W", "E"):
        a(f'  <connection from="maj_{side}_feed" to="maj_{side}_bay" fromLane="0" toLane="0"/>')
        a(f'  <connection from="maj_{side}_feed" to="maj_{side}_bay" fromLane="1" toLane="1"/>')
        a(f'  <connection from="maj_{side}_feed" to="maj_{side}_bay" fromLane="1" toLane="2"/>')
    # ---- EB approach (maj_W_bay): right->S, through->E, left->N
    a('  <connection from="maj_W_bay" to="min_S_out" fromLane="0" toLane="0"/>')     # EBR
    a('  <connection from="maj_W_bay" to="maj_out_E" fromLane="0" toLane="0"/>')     # EBT
    a('  <connection from="maj_W_bay" to="maj_out_E" fromLane="1" toLane="1"/>')     # EBT
    if not riro:
        a('  <connection from="maj_W_bay" to="drw_N_out" fromLane="2" toLane="0"/>') # EBL into site
    # ---- WB approach (maj_E_bay): right->N, through->W, left->S
    a('  <connection from="maj_E_bay" to="drw_N_out" fromLane="0" toLane="0"/>')     # WBR into site
    a('  <connection from="maj_E_bay" to="maj_out_W" fromLane="0" toLane="0"/>')     # WBT
    a('  <connection from="maj_E_bay" to="maj_out_W" fromLane="1" toLane="1"/>')     # WBT
    a('  <connection from="maj_E_bay" to="min_S_out" fromLane="2" toLane="0"/>')     # WBL
    # ---- driveway (N) southbound: left->E, through->S, right->W
    if driveway_lanes == 2:
        # exclusive right-turn lane: lane 0 = right only, lane 1 = left + through
        a('  <connection from="drw_N_in" to="maj_out_W" fromLane="0" toLane="0"/>')  # NBR (=SB right)
        if not riro:
            a('  <connection from="drw_N_in" to="maj_out_E" fromLane="1" toLane="1"/>')
            a('  <connection from="drw_N_in" to="min_S_out" fromLane="1" toLane="0"/>')
    else:
        a('  <connection from="drw_N_in" to="maj_out_W" fromLane="0" toLane="0"/>')  # right-out
        if not riro:
            a('  <connection from="drw_N_in" to="maj_out_E" fromLane="0" toLane="1"/>')
            a('  <connection from="drw_N_in" to="min_S_out" fromLane="0" toLane="0"/>')
    # ---- minor street (S) northbound: left->W, through->N, right->E
    a('  <connection from="min_S_in" to="maj_out_W" fromLane="0" toLane="1"/>')
    a('  <connection from="min_S_in" to="maj_out_E" fromLane="0" toLane="0"/>')
    a('  <connection from="min_S_in" to="drw_N_out" fromLane="0" toLane="0"/>')
    # ---- fringe U-turns (used only by RIRO re-routed site trips)
    a('  <connection from="maj_out_E" to="maj_E_feed" fromLane="0" toLane="0"/>')
    a('  <connection from="maj_out_W" to="maj_W_feed" fromLane="0" toLane="0"/>')
    c.append("</connections>")
    return "\n".join(c) + "\n"


VARIANTS = {
    #  name        center type      driveway lanes  riro
    "twsc":       ("priority",      1, False),
    "signal":     ("traffic_light", 1, False),
    "twsc_rt":    ("priority",      2, False),
    "twsc_riro":  ("priority",      1, True),
}


def build():
    netconvert = find_bin("netconvert")
    made = {}
    for name, (ctype, dlanes, riro) in VARIANTS.items():
        nod = write(os.path.join(NET, f"{name}.nod.xml"), node_xml(ctype))
        edg = write(os.path.join(NET, f"{name}.edg.xml"), edge_xml(dlanes))
        con = write(os.path.join(NET, f"{name}.con.xml"), conn_xml(dlanes, riro))
        out = os.path.join(NET, f"{name}.net.xml")
        cmd = [netconvert, "--node-files", nod, "--edge-files", edg,
               "--connection-files", con,
               "--no-turnarounds", "true",
               "--tls.guess", "false",
               "--no-internal-links", "false",
               "--default.junctions.keep-clear", "true",
               "--offset.disable-normalization", "true",
               "-o", out]
        r = run(cmd)
        if r.returncode != 0:
            print(r.stdout); print(r.stderr, file=sys.stderr)
            sys.exit(f"netconvert failed for {name}")
        warn = [l for l in r.stderr.splitlines() if l.strip()]
        print(f"[build] {name:11s} -> {os.path.basename(out)}  center={ctype:13s} "
              f"driveway_lanes={dlanes} riro={riro}  ({len(warn)} netconvert messages)")
        for w in warn[:6]:
            print("        ", w)
        made[name] = out
    return made


# --------------------------------------------------------------- verification
def verify(netfile, name):
    """Decode the compiled net's connection states + request/response bitstrings."""
    root = ET.parse(netfile).getroot()
    lines = [f"### {name}  ({os.path.basename(netfile)})"]

    # lane lengths (bay / feed / driveway compiled lengths)
    lens = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        for ln in e.findall("lane"):
            lens[ln.get("id")] = float(ln.get("length"))
    lines.append("compiled lane lengths:")
    for lid in sorted(lens):
        lines.append(f"    {lid:20s} {lens[lid]:8.2f} m")

    # connection states at junction C
    lines.append("connections into junction C (state char, tl link index):")
    states = {}
    for c in root.findall("connection"):
        if c.get("via") is None:
            continue
        frm, to = c.get("from"), c.get("to")
        st = c.get("state")
        li = c.get("linkIndex", "-")
        d = c.get("dir")
        key = f"{frm}_{c.get('fromLane')} -> {to}_{c.get('toLane')}"
        states[key] = (st, d, li)
        lines.append(f"    {key:42s} state={st}  dir={d}  linkIndex={li}")

    # junction C request/response matrix, DECODED.
    # SUMO writes response/foes bitstrings with the RIGHTMOST character = link
    # index 0, i.e. char position p corresponds to link index (len-1-p).
    order = []   # link index -> "from_lane -> to_lane (dir)"
    for j in root.findall("junction"):
        if j.get("id") != "C":
            continue
        inc = j.get("incLanes").split()
        for lane in inc:
            for c in root.findall("connection"):
                if c.get("via") is None:
                    continue
                if f"{c.get('from')}_{c.get('fromLane')}" == lane:
                    order.append((f"{c.get('from')}_{c.get('fromLane')}"
                                  f"->{c.get('to')}_{c.get('toLane')}", c.get("dir"),
                                  c.get("state")))
        lines.append(f"junction C type={j.get('type')}  incLanes={j.get('incLanes')}")
        lines.append("  idx  movement                                 dir state  yields-to (decoded)")
        for req in j.findall("request"):
            idx = int(req.get("index"))
            resp = req.get("response")
            n = len(resp)
            yields = [order[n - 1 - p][0] for p, ch in enumerate(resp) if ch == "1"]
            mv, d, st = order[idx] if idx < len(order) else ("?", "?", "?")
            lines.append("  %3d  %-40s %-3s %-5s %s" %
                         (idx, mv, d, st, ", ".join(yields) if yields else "(nobody)"))
    return "\n".join(lines), states, lens


def strip_tllogic(src, dst):
    """netconvert always writes an explicit <tlLogic programID='0'>; a hand-written
    program loaded from an additional file cannot reuse programID '0' ("Another
    logic with id 'C' and programID '0' exists").  Remove the auto-generated
    program so our own Webster / actuated plan can BE programID '0'."""
    tree = ET.parse(src)
    root = tree.getroot()
    n = 0
    for tl in list(root.findall("tlLogic")):
        root.remove(tl)
        n += 1
    tree.write(dst, encoding="UTF-8", xml_declaration=True)
    print(f"[build] stripped {n} auto-generated tlLogic -> {os.path.basename(dst)}")


def main():
    made = build()
    # (auto-generated tlLogic is kept; custom programs are activated via WAUT)
    report = []
    summary = {}
    for name, path in made.items():
        txt, states, lens = verify(path, name)
        report.append(txt)
        summary[name] = (states, lens)
    write(os.path.join(NET, "network_verification.txt"), "\n\n".join(report) + "\n")
    print("\n[verify] wrote", os.path.join(NET, "network_verification.txt"))

    # ---- automatic TWSC right-of-way assertions on the `twsc` variant
    states, lens = summary["twsc"]
    problems = []
    major_through = [k for k in states if k.startswith(("maj_W_bay", "maj_E_bay"))
                     and states[k][1] == "s"]
    minor_all = [k for k in states if k.startswith(("drw_N_in", "min_S_in"))]
    for k in major_through:
        if states[k][0] != "M":
            problems.append(f"major through {k} has state {states[k][0]} (expected M)")
    for k in minor_all:
        if states[k][0] != "m":
            problems.append(f"minor movement {k} has state {states[k][0]} (expected m)")
    print("\n[verify] TWSC right-of-way check:")
    print(f"    major-street through connections with state 'M': "
          f"{sum(1 for k in major_through if states[k][0]=='M')}/{len(major_through)}")
    print(f"    minor-approach connections with state 'm'      : "
          f"{sum(1 for k in minor_all if states[k][0]=='m')}/{len(minor_all)}")
    if problems:
        for p in problems:
            print("    PROBLEM:", p)
    else:
        print("    OK - major road has priority, every minor movement yields")
    # bay / feed compiled lengths vs design intent
    print("\n[verify] compiled key lengths (twsc) vs design intent:")
    for lid, key in (("maj_W_bay_2", "bay"), ("maj_W_feed_1", "feed"),
                     ("drw_N_in_0", "minor"), ("min_S_in_0", "minor")):
        if lid in lens:
            print(f"    {lid:16s} {lens[lid]:7.2f} m  (design {DESIGN[key]:6.1f} m, "
                  f"err {lens[lid]-DESIGN[key]:+.2f} m)")


if __name__ == "__main__":
    main()
