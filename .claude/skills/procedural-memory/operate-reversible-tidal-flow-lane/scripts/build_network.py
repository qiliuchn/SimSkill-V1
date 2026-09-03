#!/usr/bin/env python3
"""Build every network variant for the reversible-lane study.

Produced in outputs/net/:

  encB_open.net.xml    ENCODING B (accepted).  One directional edge pair; every
                       directional edge declares all SIX physical lanes,
                       spreadType="center", compiled fully OPEN.
  encB_closed.net.xml  identical topology, but the two reversible lanes are
                       compiled CLOSED (allow="authority") on the westbound
                       edges -- used ONLY to test the netconvert
                       internal-junction-connector trap.
  encA.net.xml         ENCODING A (candidate).  The reversible lanes are
                       separate single-lane opposing edges laid over the same
                       geometry, alongside 2-lane permanent directional edges.
  (ENCODING C reuses encB_open.net.xml plus a rerouter additional file.)

Usage:  python3 build_network.py
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NETDIR, CORRIDOR_LEN, CORR_SPEED, STUB_LEN, CYCLE, G_CORR,
                    Y_CORR, G_CROSS, Y_CROSS, ensure_dirs)

XL = CORRIDOR_LEN


def _nodes(xl):
    return NODES_TMPL.format(stub=-STUB_LEN, xl=xl, xle=xl + STUB_LEN, xln=xl)


NODES_TMPL = """<nodes>
    <node id="WW" x="{stub}" y="0"  type="priority"/>
    <node id="W"  x="0"    y="0"  type="traffic_light"/>
    <node id="E"  x="{xl}" y="0"  type="traffic_light"/>
    <node id="EE" x="{xle}" y="0" type="priority"/>
    <node id="Wn" x="0"    y="400"  type="priority"/>
    <node id="Ws" x="0"    y="-400" type="priority"/>
    <node id="En" x="{xln}" y="400"  type="priority"/>
    <node id="Es" x="{xln}" y="-400" type="priority"/>
</nodes>
"""
NODES = _nodes(XL)

CROSS_EDGES = """
    <edge id="Wn_W" from="Wn" to="W" numLanes="2" speed="13.9"/>
    <edge id="W_Wn" from="W" to="Wn" numLanes="2" speed="13.9"/>
    <edge id="Ws_W" from="Ws" to="W" numLanes="2" speed="13.9"/>
    <edge id="W_Ws" from="W" to="Ws" numLanes="2" speed="13.9"/>
    <edge id="En_E" from="En" to="E" numLanes="2" speed="13.9"/>
    <edge id="E_En" from="E" to="En" numLanes="2" speed="13.9"/>
    <edge id="Es_E" from="Es" to="E" numLanes="2" speed="13.9"/>
    <edge id="E_Es" from="E" to="Es" numLanes="2" speed="13.9"/>
"""

CROSS_CONN = """
    <connection from="Wn_W" to="W_Ws" fromLane="0" toLane="0"/>
    <connection from="Wn_W" to="W_Ws" fromLane="1" toLane="1"/>
    <connection from="Ws_W" to="W_Wn" fromLane="0" toLane="0"/>
    <connection from="Ws_W" to="W_Wn" fromLane="1" toLane="1"/>
    <connection from="En_E" to="E_Es" fromLane="0" toLane="0"/>
    <connection from="En_E" to="E_Es" fromLane="1" toLane="1"/>
    <connection from="Es_E" to="E_En" fromLane="0" toLane="0"/>
    <connection from="Es_E" to="E_En" fromLane="1" toLane="1"/>
"""


# --------------------------------------------------------------- encoding B
def encB_edges(close_rev_wb=False):
    """Six declared lanes on every facility edge, spreadType=center, no explicit
    shape (netconvert normalises explicit shapes back onto the node line, so an
    explicit lateral offset cannot be used -- see findings)."""
    def e(eid, frm, to, body=""):
        if body:
            return (f'    <edge id="{eid}" from="{frm}" to="{to}" numLanes="6" '
                    f'speed="{CORR_SPEED}" spreadType="center">\n{body}    </edge>\n')
        return (f'    <edge id="{eid}" from="{frm}" to="{to}" numLanes="6" '
                f'speed="{CORR_SPEED}" spreadType="center"/>\n')

    # WB lane 3 == L3, WB lane 2 == L4
    closed_body = ('        <lane index="2" allow="authority"/>\n'
                   '        <lane index="3" allow="authority"/>\n')
    wb_body = closed_body if close_rev_wb else ""
    return (e("apW_in", "WW", "W") + e("COR_EB", "W", "E") + e("apE_out", "E", "EE")
            + e("apE_in", "EE", "E", wb_body) + e("COR_WB", "E", "W", wb_body)
            + e("apW_out", "W", "WW", wb_body))


def encB_conn():
    c = []
    for i in range(6):
        c.append(f'    <connection from="apW_in" to="COR_EB" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="COR_EB" to="apE_out" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="apE_in" to="COR_WB" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="COR_WB" to="apW_out" fromLane="{i}" toLane="{i}"/>')
    return "\n".join(c) + "\n" + CROSS_CONN


# --------------------------------------------------------------- encoding A
ENC_A_EDGES = f"""
    <edge id="apW_in"  from="WW" to="W"  numLanes="4" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="apW_out" from="W"  to="WW" numLanes="4" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="apE_in"  from="EE" to="E"  numLanes="4" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="apE_out" from="E"  to="EE" numLanes="4" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="COR_EB" from="W" to="E" numLanes="2" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="COR_WB" from="E" to="W" numLanes="2" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="RL3_EB" from="W" to="E" numLanes="1" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="RL3_WB" from="E" to="W" numLanes="1" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="RL4_EB" from="W" to="E" numLanes="1" speed="{CORR_SPEED}" spreadType="center"/>
    <edge id="RL4_WB" from="E" to="W" numLanes="1" speed="{CORR_SPEED}" spreadType="center"/>
"""


def encA_conn():
    c = []
    for i in range(2):
        c.append(f'    <connection from="apW_in" to="COR_EB" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="COR_EB" to="apE_out" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="apE_in" to="COR_WB" fromLane="{i}" toLane="{i}"/>')
        c.append(f'    <connection from="COR_WB" to="apW_out" fromLane="{i}" toLane="{i}"/>')
    c += ['    <connection from="apW_in" to="RL3_EB" fromLane="2" toLane="0"/>',
          '    <connection from="apW_in" to="RL4_EB" fromLane="3" toLane="0"/>',
          '    <connection from="RL3_EB" to="apE_out" fromLane="0" toLane="2"/>',
          '    <connection from="RL4_EB" to="apE_out" fromLane="0" toLane="3"/>',
          '    <connection from="apE_in" to="RL4_WB" fromLane="2" toLane="0"/>',
          '    <connection from="apE_in" to="RL3_WB" fromLane="3" toLane="0"/>',
          '    <connection from="RL4_WB" to="apW_out" fromLane="0" toLane="2"/>',
          '    <connection from="RL3_WB" to="apW_out" fromLane="0" toLane="3"/>']
    return "\n".join(c) + "\n" + CROSS_CONN


# ------------------------------------------------------------------ helpers
def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def netconvert(nod, edg, con, out, tll=None):
    cmd = ["netconvert", "--node-files", nod, "--edge-files", edg,
           "--connection-files", con, "--output-file", out,
           "--no-turnarounds", "true", "--offset.disable-normalization", "true",
           "--default.junctions.keep-clear", "true",
           "--geometry.avoid-overlap", "false"]
    if tll:
        cmd += ["--tllogic-files", tll]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("netconvert failed -> " + out)
    return r.stderr


def corridor_tls_program(netfile, tlsid, corridor_from):
    root = ET.parse(netfile).getroot()
    idx_corr, idx_cross, nlinks = [], [], 0
    for conn in root.findall("connection"):
        if conn.get("tl") != tlsid:
            continue
        li = int(conn.get("linkIndex"))
        nlinks = max(nlinks, li + 1)
        (idx_corr if conn.get("from") in corridor_from else idx_cross).append(li)

    def state(idx, colour):
        s = ["r"] * nlinks
        for i in idx:
            s[i] = colour
        return "".join(s)

    phases = [(G_CORR, state(idx_corr, "G")), (Y_CORR, state(idx_corr, "y")),
              (G_CROSS, state(idx_cross, "G")), (Y_CROSS, state(idx_cross, "y"))]
    assert sum(p[0] for p in phases) == CYCLE
    body = "\n".join(f'        <phase duration="{d}" state="{s}"/>' for d, s in phases)
    return (f'    <tlLogic id="{tlsid}" type="static" programID="corridor" offset="0">\n'
            f"{body}\n    </tlLogic>\n"), dict(links=nlinks, corridor=len(idx_corr),
                                               cross=len(idx_cross))


def build(name, edges_xml, conn_xml, corridor_from, nodes=None):
    nod = os.path.join(NETDIR, f"{name}.nod.xml")
    edg = os.path.join(NETDIR, f"{name}.edg.xml")
    con = os.path.join(NETDIR, f"{name}.con.xml")
    tll = os.path.join(NETDIR, f"{name}.tll.xml")
    tmp = os.path.join(NETDIR, f"{name}_tmp.net.xml")
    out = os.path.join(NETDIR, f"{name}.net.xml")
    write(nod, nodes or NODES)
    write(edg, "<edges>\n" + edges_xml + CROSS_EDGES + "</edges>\n")
    write(con, "<connections>\n" + conn_xml + "</connections>\n")
    netconvert(nod, edg, con, tmp)
    tl_xml, info = "", {}
    for tlsid in ("W", "E"):
        s, i = corridor_tls_program(tmp, tlsid, corridor_from)
        tl_xml += s
        info[tlsid] = i
    write(tll, "<additional>\n" + tl_xml + "</additional>\n")
    warn = netconvert(nod, edg, con, out, tll=tll)
    os.remove(tmp)
    return out, info, warn


def build_length_variant(xl):
    """Same encoding-B network with a different corridor length (clearance
    study only)."""
    global XL
    old = XL
    XL = xl
    name = f"encB_open_L{int(xl)}"
    out, info, _ = build(name, encB_edges(False), encB_conn(),
                         {"apW_in", "COR_EB", "apE_in", "COR_WB"}, nodes=_nodes(xl))
    XL = old
    return out


def main():
    ensure_dirs()
    cfB = {"apW_in", "COR_EB", "apE_in", "COR_WB"}
    cfA = cfB | {"RL3_EB", "RL3_WB", "RL4_EB", "RL4_WB"}
    for name, edges, conn, cfrom in [
        ("encB_open", encB_edges(False), encB_conn(), cfB),
        ("encB_closed", encB_edges(True), encB_conn(), cfB),
        ("encA", ENC_A_EDGES, encA_conn(), cfA),
    ]:
        out, info, warn = build(name, edges, conn, cfrom)
        print(f"[built] {out}")
        for k, v in info.items():
            print(f"        TLS {k}: {v}")
        wl = [l for l in warn.splitlines() if "Warning" in l]
        print(f"        netconvert warnings: {len(wl)}")
        for l in wl[:4]:
            print("          " + l)
    print("\nDONE")


if __name__ == "__main__":
    main()
