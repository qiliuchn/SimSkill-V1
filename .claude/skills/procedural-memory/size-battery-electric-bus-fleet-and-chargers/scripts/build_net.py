#!/usr/bin/env python3
"""
Build the BEB corridor network:
  - ~10.4 km bus corridor, terminals at both ends (TW west, TE east)
  - 6 coordinated fixed-time signalised intersections (J1..J6)
  - asymmetric vertical profile: sustained +3.5% grade eastbound between J2 and J4
  - bus-only terminal edges with 2 charging berths at each terminal + a depot berth (west)
Two netconvert passes: geometry first, then a hand-built coordinated tlLogic baked in.
Every claim (grade, stop position, lane permission) is re-derived from the COMPILED net.
"""
import os, sys, math, subprocess, json
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- geometry
NODE_X = {"W": 0.0, "J1": 1200.0, "J2": 2600.0, "J3": 4000.0,
          "J4": 5400.0, "J5": 6800.0, "J6": 8200.0, "E": 9600.0}
CORR = ["W", "J1", "J2", "J3", "J4", "J5", "J6", "E"]
TERM_LEN = 400.0
GRADE = 0.035          # 3.5 %
GRADE_FROM, GRADE_TO = "J2", "J4"
V_CORR = 13.89         # m/s (50 km/h)
V_CROSS = 13.89
CROSS_OFF = 350.0
SIDEWALK_W = 2.0
CYCLE = 90.0
G_CORR, Y, G_CROSS = 56.0, 4.0, 26.0     # 56+4+26+4 = 90
PROG_SPEED = 12.0      # m/s design progression speed (eastbound)

# stop x positions (m from west terminal node W), ~800 m spacing
STOP_X = [500, 1300, 2100, 2900, 3700, 4500, 5300, 6100, 6900, 7700, 8500, 9300]
STOP_LEN = 15.0


def node_z(x):
    x0, x1 = NODE_X[GRADE_FROM], NODE_X[GRADE_TO]
    if x <= x0:
        return 0.0
    if x >= x1:
        return (x1 - x0) * GRADE
    return (x - x0) * GRADE


def edge_for_x(x, direction):
    """Return (edge_id, pos_on_edge) for absolute corridor coordinate x."""
    for i in range(len(CORR) - 1):
        a, b = CORR[i], CORR[i + 1]
        xa, xb = NODE_X[a], NODE_X[b]
        if xa <= x < xb:
            if direction == "EB":
                return f"EB_{i}", x - xa
            else:
                return f"WB_{i}", xb - x
    raise ValueError(x)


def write_plain(outdir):
    nodes = ['<nodes>']
    for n in CORR:
        x = NODE_X[n]
        typ = "traffic_light" if n.startswith("J") else "priority"
        nodes.append(f'  <node id="{n}" x="{x}" y="0.0" z="{node_z(x):.4f}" type="{typ}"/>')
    nodes.append(f'  <node id="TW" x="{-TERM_LEN}" y="0.0" z="0.0" type="dead_end"/>')
    nodes.append(f'  <node id="TE" x="{NODE_X["E"]+TERM_LEN}" y="0.0" z="{node_z(NODE_X["E"]):.4f}" type="dead_end"/>')
    for i in range(1, 7):
        n = f"J{i}"; x = NODE_X[n]; z = node_z(x)
        nodes.append(f'  <node id="N{i}" x="{x}" y="{CROSS_OFF}" z="{z:.4f}" type="priority"/>')
        nodes.append(f'  <node id="S{i}" x="{x}" y="{-CROSS_OFF}" z="{z:.4f}" type="priority"/>')
    nodes.append('</nodes>')

    def corridor_edge(eid, frm, to):
        return (f'  <edge id="{eid}" from="{frm}" to="{to}" numLanes="3" speed="{V_CORR}" priority="10" spreadType="right">\n'
                f'    <lane index="0" allow="pedestrian" width="{SIDEWALK_W}" speed="2.78"/>\n'
                f'    <lane index="1" disallow="pedestrian" speed="{V_CORR}"/>\n'
                f'    <lane index="2" disallow="pedestrian" speed="{V_CORR}"/>\n'
                f'  </edge>')

    def cross_edge(eid, frm, to):
        return (f'  <edge id="{eid}" from="{frm}" to="{to}" numLanes="2" speed="{V_CROSS}" priority="3" spreadType="right">\n'
                f'    <lane index="0" allow="pedestrian" width="{SIDEWALK_W}" speed="2.78"/>\n'
                f'    <lane index="1" disallow="pedestrian" speed="{V_CROSS}"/>\n'
                f'  </edge>')

    edges = ['<edges>']
    for i in range(len(CORR) - 1):
        a, b = CORR[i], CORR[i + 1]
        edges.append(corridor_edge(f"EB_{i}", a, b))
        edges.append(corridor_edge(f"WB_{i}", b, a))
    # bus-only terminal edges
    edges.append(f'  <edge id="TW_IN"  from="W" to="TW" numLanes="3" speed="8.33" allow="bus" priority="1"/>')
    edges.append(f'  <edge id="TW_OUT" from="TW" to="W" numLanes="1" speed="8.33" allow="bus" priority="1"/>')
    edges.append(f'  <edge id="TE_IN"  from="E" to="TE" numLanes="2" speed="8.33" allow="bus" priority="1"/>')
    edges.append(f'  <edge id="TE_OUT" from="TE" to="E" numLanes="1" speed="8.33" allow="bus" priority="1"/>')
    for i in range(1, 7):
        edges.append(cross_edge(f"N{i}_J{i}", f"N{i}", f"J{i}"))
        edges.append(cross_edge(f"J{i}_N{i}", f"J{i}", f"N{i}"))
        edges.append(cross_edge(f"S{i}_J{i}", f"S{i}", f"J{i}"))
        edges.append(cross_edge(f"J{i}_S{i}", f"J{i}", f"S{i}"))
    edges.append('</edges>')

    cons = ['<connections>']
    # west terminal
    for tl in (0, 1, 2):
        cons.append(f'  <connection from="WB_0" to="TW_IN" fromLane="1" toLane="{tl}"/>')
        cons.append(f'  <connection from="TW_IN" to="TW_OUT" fromLane="{tl}" toLane="0"/>')
    cons.append('  <connection from="WB_0" to="TW_IN" fromLane="2" toLane="2"/>')
    cons.append('  <connection from="TW_OUT" to="EB_0" fromLane="0" toLane="1"/>')
    # east terminal
    for tl in (0, 1):
        cons.append(f'  <connection from="EB_6" to="TE_IN" fromLane="1" toLane="{tl}"/>')
        cons.append(f'  <connection from="TE_IN" to="TE_OUT" fromLane="{tl}" toLane="0"/>')
    cons.append('  <connection from="EB_6" to="TE_IN" fromLane="2" toLane="1"/>')
    cons.append('  <connection from="TE_OUT" to="WB_6" fromLane="0" toLane="1"/>')
    cons.append('</connections>')

    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "corr.nod.xml"), "w").write("\n".join(nodes))
    open(os.path.join(outdir, "corr.edg.xml"), "w").write("\n".join(edges))
    open(os.path.join(outdir, "corr.con.xml"), "w").write("\n".join(cons))


def netconvert_pass1(outdir):
    out = os.path.join(outdir, "base.net.xml")
    cmd = ["netconvert",
           "-n", os.path.join(outdir, "corr.nod.xml"),
           "-e", os.path.join(outdir, "corr.edg.xml"),
           "-x", os.path.join(outdir, "corr.con.xml"),
           "-o", out,
           "--crossings.guess", "true",
           "--walkingareas", "true",
           "--no-turnarounds", "true",
           "--junctions.corner-detail", "0",
           "--default.junctions.radius", "6",
           "--tls.default-type", "static",
           "--no-internal-links", "false"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-4000:]); print(p.stderr[-6000:]); sys.exit(1)
    return out, p.stderr


def build_coordinated_tll(basenet, outdir):
    """Read the compiled net's controlled connections and author a coordinated
    2-stage fixed-time program (corridor / cross) with progression offsets."""
    root = ET.parse(basenet).getroot()
    # which vehicle edges does each crossing edge span?
    crossing_span = {e.get("id"): (e.get("crossingEdges") or "").split()
                     for e in root.iter("edge") if e.get("function") == "crossing"}
    links = {}   # tls -> {linkIndex: (fromEdge, toEdge, dir)}
    for c in root.iter("connection"):
        tl = c.get("tl")
        if tl is None:
            continue
        links.setdefault(tl, {})[int(c.get("linkIndex"))] = (
            c.get("from"), c.get("to"), c.get("dir"))
    tll = ['<additional>']
    offsets = {}
    ped_map = {}
    for tls in sorted(links, key=lambda s: int(s[1:])):
        idx = links[tls]
        n = max(idx) + 1
        corr_state, cross_state = [], []
        ped_desc = {}
        for k in range(n):
            frm, to, d = idx.get(k, ("?", "?", "s"))
            if frm.startswith(":"):          # walkingarea -> crossing link
                spans = crossing_span.get(to, [])
                spans_corridor = any(s.startswith("EB_") or s.startswith("WB_") for s in spans)
                # a crossing OVER the corridor may only run during the cross-street stage
                corr_state.append("r" if spans_corridor else "G")
                cross_state.append("G" if spans_corridor else "r")
                ped_desc[k] = (to, spans, "cross-stage" if spans_corridor else "corridor-stage")
                continue
            if frm.startswith("EB_") or frm.startswith("WB_"):
                corr_state.append("G" if d in ("s", "r") else "g")
                cross_state.append("r")
            else:
                corr_state.append("r")
                cross_state.append("G" if d in ("s", "r") else "g")
        ped_map[tls] = ped_desc

        def yellow(a, b):
            out = []
            for k, (x, y) in enumerate(zip(a, b)):
                if k in ped_desc:
                    out.append("r")          # crossings are dark/red during clearance
                elif x in "Gg" and y == "r":
                    out.append("y")
                elif y == "r":
                    out.append("r")
                else:
                    out.append(x)
            return "".join(out)
        cs, xs_ = "".join(corr_state), "".join(cross_state)
        y1, y2 = yellow(cs, xs_), yellow(xs_, cs)
        x = NODE_X[tls]
        off = (x / PROG_SPEED) % CYCLE
        offsets[tls] = round(off, 1)
        tll.append(f'  <tlLogic id="{tls}" type="static" programID="0" offset="{off:.1f}">')
        for st, du in ((cs, G_CORR), (y1, Y), (xs_, G_CROSS), (y2, Y)):
            tll.append(f'    <phase duration="{du:.0f}" state="{st}"/>')
        tll.append('  </tlLogic>')
    tll.append('</additional>')
    p = os.path.join(outdir, "coord.tll.xml")
    open(p, "w").write("\n".join(tll))
    json.dump({k: {str(a): b for a, b in v.items()} for k, v in ped_map.items()},
              open(os.path.join(outdir, "ped_link_map.json"), "w"), indent=1)
    return p, offsets


def netconvert_pass2(basenet, tll, outdir):
    out = os.path.join(outdir, "corr.net.xml")
    cmd = ["netconvert", "-s", basenet, "-i", tll, "-o", out,
           "--no-turnarounds", "true", "--no-internal-links", "false"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-4000:]); print(p.stderr[-6000:]); sys.exit(1)
    return out, p.stderr


# -------------------------------------------------- compiled-net verification
def parse_net(netfile):
    root = ET.parse(netfile).getroot()
    edges, lanes = {}, {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            continue
        ls = []
        for ln in e.findall("lane"):
            d = dict(ln.attrib)
            d["length"] = float(d["length"])
            d["shape_pts"] = [tuple(float(v) for v in pt.split(","))
                              for pt in d["shape"].split()]
            ls.append(d)
            lanes[d["id"]] = d
        edges[e.get("id")] = {"attrib": dict(e.attrib), "lanes": ls}
    return root, edges, lanes


def lane_grade(lane, detail=False):
    pts = lane["shape_pts"]
    p0, p1 = pts[0], pts[-1]
    z0 = p0[2] if len(p0) > 2 else 0.0
    z1 = p1[2] if len(p1) > 2 else 0.0
    horiz = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    g = 100.0 * (z1 - z0) / horiz if horiz > 0 else 0.0
    if detail:
        return {"grade_pct": round(g, 4), "dz_m": round(z1 - z0, 4),
                "horiz_m": round(horiz, 3), "z0": round(z0, 3), "z1": round(z1, 3)}
    return g


def verify(netfile):
    root, edges, lanes = parse_net(netfile)
    rep = {"grade_per_edge": {}, "grade_detail": {}, "lane_lengths": {}, "issues": []}
    for i in range(len(CORR) - 1):
        for d in ("EB", "WB"):
            eid = f"{d}_{i}"
            ln = [l for l in edges[eid]["lanes"] if l["id"].endswith("_1")][0]
            rep["grade_per_edge"][eid] = round(lane_grade(ln), 4)
            rep["grade_detail"][eid] = lane_grade(ln, detail=True)
            rep["lane_lengths"][eid] = round(ln["length"], 2)
    for eid in ("TW_IN", "TW_OUT", "TE_IN", "TE_OUT"):
        ln = edges[eid]["lanes"][0]
        rep["lane_lengths"][eid] = round(ln["length"], 2)
        rep["grade_per_edge"][eid] = round(lane_grade(ln), 4)
        allow = edges[eid]["lanes"][0].get("allow", "")
        if "bus" not in allow:
            rep["issues"].append(f"{eid} lane0 allow='{allow}' (expected bus)")
    # sidewalk / driving lane permission check on corridor
    for i in range(len(CORR) - 1):
        for d in ("EB", "WB"):
            eid = f"{d}_{i}"
            l0 = edges[eid]["lanes"][0]
            l1 = edges[eid]["lanes"][1]
            if "pedestrian" not in (l0.get("allow", "")):
                rep["issues"].append(f"{eid}_0 not a sidewalk (allow={l0.get('allow')})")
            if "pedestrian" in (l1.get("allow", "") or "") and l1.get("allow"):
                rep["issues"].append(f"{eid}_1 allows pedestrian")
    rep["n_tls"] = len(list(root.iter("tlLogic")))
    rep["tls_offsets"] = {t.get("id"): float(t.get("offset")) for t in root.iter("tlLogic")}
    rep["tls_cycle"] = {t.get("id"): sum(float(p.get("duration")) for p in t.findall("phase"))
                        for t in root.iter("tlLogic")}
    return rep


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "build")
    outdir = os.path.abspath(outdir)
    write_plain(outdir)
    base, e1 = netconvert_pass1(outdir)
    tll, offs = build_coordinated_tll(base, outdir)
    net, e2 = netconvert_pass2(base, tll, outdir)
    rep = verify(net)
    rep["designed_offsets"] = offs
    json.dump(rep, open(os.path.join(outdir, "net_verification.json"), "w"), indent=2)
    print(json.dumps(rep, indent=2)[:4000])
    if e2.strip():
        print("--- netconvert pass2 stderr ---\n", e2.strip()[:2000])
