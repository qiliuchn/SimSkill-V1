#!/usr/bin/env python3
r"""
Build the corridor network for the travel-time-reliability study.

Topology (main corridor is ONE-WAY eastbound):

    N (side street, north)
        |
        v
  O --> A --> C --> M --> B --> D
         \                /
          \-> P --------->
             (parallel detour, 1 lane, slower)

  Main corridor edges : OA, AC, CB1 (C->M), CB2 (M->B), BD
  Detour edges        : AP (A->P), PB (P->B)
  Side street         : NC (N->C), CN (C->N)
  Signal              : at C  (main phase vs side-street phase)
  Incident location   : a lane closure on CB1 or CB2 (both DOWNSTREAM of the
                        diverge at A, with the main-exclusive edge AC in
                        between, per `simulate-incident-rerouting`)

`--approach-lanes` sets the lane count on OA and AC (the signalised approach,
which carries the RECURRENT bottleneck); `--mid-lanes` sets it on CB1 and CB2
(the incident-prone midblock).  BD always gets mid+1 lanes so the detour merges
into its own dedicated lane (zero merge conflict -- the study is about
reliability, not merge dynamics).

  A_base / C_info : approach 3, mid 3
  B_capacity      : approach 4, mid 4  (full corridor widening)
  D_shoulder      : approach 3, mid 4  (midblock hard-shoulder lane only; no
                                        recurrent benefit, because the signal
                                        at C still discharges only 3 lanes --
                                        pure incident redundancy)
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

V_MAIN = 16.67   # 60 km/h
V_ALT = 13.89    # 50 km/h

NODES = [
    ("O",     0.0,     0.0, "priority"),
    ("A",   800.0,     0.0, "priority"),
    ("C",  2300.0,     0.0, "traffic_light"),
    ("N",  2300.0,   600.0, "priority"),
    ("M",  3050.0,     0.0, "priority"),
    ("B",  3800.0,     0.0, "priority"),
    ("D",  4800.0,     0.0, "priority"),
    ("P",  2300.0,  -600.0, "priority"),
]

MAIN_GREEN = 40
SIDE_GREEN = 14
YELLOW = 3


def write_nodes(path):
    with open(path, "w") as f:
        f.write('<nodes>\n')
        for nid, x, y, t in NODES:
            f.write(f'    <node id="{nid}" x="{x}" y="{y}" type="{t}"/>\n')
        f.write('</nodes>\n')


def write_edges(path, LA, LM):
    e = []
    e.append(("OA", "O", "A", LA, V_MAIN))
    e.append(("AC", "A", "C", LA, V_MAIN))
    e.append(("CB1", "C", "M", LM, V_MAIN))
    e.append(("CB2", "M", "B", LM, V_MAIN))
    e.append(("BD", "B", "D", LM + 1, V_MAIN))
    e.append(("AP", "A", "P", 1, V_ALT))
    e.append(("PB", "P", "B", 1, V_ALT))
    e.append(("NC", "N", "C", 1, V_ALT))
    e.append(("CN", "C", "N", 1, V_ALT))
    with open(path, "w") as f:
        f.write('<edges>\n')
        for eid, fr, to, lanes, spd in e:
            f.write(f'    <edge id="{eid}" from="{fr}" to="{to}" '
                    f'numLanes="{lanes}" speed="{spd}" priority="'
                    f'{2 if eid in ("AP","PB","NC","CN") else 10}"/>\n')
        f.write('</edges>\n')


def write_connections(path, LA, LM):
    c = []
    # diverge at A: straight through + rightmost lane feeds the detour
    for i in range(LA):
        c.append(("OA", "AC", i, i))
    c.append(("OA", "AP", 0, 0))
    # junction C: main through, leftmost main lane turns left onto the side st.
    for i in range(LA):
        c.append(("AC", "CB1", i, i))
    c.append(("AC", "CN", LA - 1, 0))
    # side street enters the corridor on the rightmost lane
    c.append(("NC", "CB1", 0, 0))
    # M is a plain continuation
    for i in range(LM):
        c.append(("CB1", "CB2", i, i))
    # merge at B: main -> BD lanes 1..L ; detour -> BD lane 0 (no conflict)
    for i in range(LM):
        c.append(("CB2", "BD", i, i + 1))
    c.append(("PB", "BD", 0, 0))
    with open(path, "w") as f:
        f.write('<connections>\n')
        for fr, to, fl, tl in c:
            f.write(f'    <connection from="{fr}" to="{to}" '
                    f'fromLane="{fl}" toLane="{tl}"/>\n')
        f.write('</connections>\n')


def retime_tls(netfile):
    """Rewrite the auto-generated TLS program at C to a 60 s cycle with a
    main-street green of 40 s.  The state strings produced by netconvert are
    kept verbatim; only durations change.  Main-phase identification is done by
    looking up the linkIndex values of connections whose `from` edge is AC."""
    tree = ET.parse(netfile)
    root = tree.getroot()
    main_links = set()
    side_links = set()
    for con in root.findall("connection"):
        li = con.get("linkIndex")
        if li is None:
            continue
        if con.get("from") == "AC":
            main_links.add(int(li))
        elif con.get("from") == "NC":
            side_links.add(int(li))
    if not main_links or not side_links:
        sys.exit("could not locate main/side links at C")

    tl = root.find("tlLogic")
    if tl is None:
        sys.exit("no tlLogic in net")
    phases = tl.findall("phase")
    info = []
    for ph in phases:
        st = ph.get("state")
        is_y = any(st[i] in "yY" for i in main_links | side_links)
        main_g = any(st[i] in "gG" for i in main_links)
        side_g = any(st[i] in "gG" for i in side_links)
        info.append((ph, st, is_y, main_g, side_g))

    for ph, st, is_y, main_g, side_g in info:
        if is_y:
            ph.set("duration", str(YELLOW))
        elif main_g and not side_g:
            ph.set("duration", str(MAIN_GREEN))
        elif side_g and not main_g:
            ph.set("duration", str(SIDE_GREEN))
        elif main_g and side_g:
            ph.set("duration", str(MAIN_GREEN))
        else:
            ph.set("duration", str(YELLOW))
    tree.write(netfile, encoding="UTF-8", xml_declaration=True)

    cycle = sum(int(ph.get("duration")) for ph in tl.findall("phase"))
    green_main = sum(int(ph.get("duration")) for ph, st, y, mg, sg in info
                     if mg and not y)
    return cycle, green_main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approach-lanes", type=int, required=True,
                    help="lanes on OA and AC (the signalised approach)")
    ap.add_argument("--mid-lanes", type=int, required=True,
                    help="lanes on CB1 and CB2 (the incident-prone midblock)")
    ap.add_argument("--out", required=True, help="output .net.xml path")
    a = ap.parse_args()

    d = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(d, exist_ok=True)
    tag = os.path.basename(a.out).replace(".net.xml", "")
    nod = os.path.join(d, tag + ".nod.xml")
    edg = os.path.join(d, tag + ".edg.xml")
    con = os.path.join(d, tag + ".con.xml")
    write_nodes(nod)
    write_edges(edg, a.approach_lanes, a.mid_lanes)
    write_connections(con, a.approach_lanes, a.mid_lanes)

    cmd = ["netconvert", "-n", nod, "-e", edg, "-x", con, "-o", a.out,
           "--no-turnarounds", "true", "--default.junctions.keep-clear", "true",
           "--tls.yellow.time", str(YELLOW), "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit(1)
    cycle, gmain = retime_tls(a.out)
    print(f"built {a.out}  approach={a.approach_lanes} mid={a.mid_lanes}  "
          f"tls cycle={cycle}s main_green={gmain}s g/C={gmain/cycle:.3f}")


if __name__ == "__main__":
    main()
