"""Shared configuration + helpers for the freeway work-zone study.

Geometry (single direction, west->east), all distances in metres from x=0:

  N0   0      origin (mainline source)
  N1   2000   off-ramp diverge  -> detour arterial
  N2   3000   start of ADVANCE WARNING area
  N3   3000+AW      taper start  (end of advance warning)
  N4   N3+TAPER     activity-area start (lane drop point in the geometric variant)
  N5   N4+WZLEN     activity-area end
  N6   N5+TERM      termination-area end
  N7   7500   on-ramp merge (detour returns)
  N8   9500   sink

Mainline edges: fA fB fC fD fE fF fG fH  (3 lanes, 120 km/h nominal)
  fC = advance warning area   (length AW)
  fD = transition / taper     (length TAPER)
  fE = activity area          (length WZLEN)  <-- lanes closed here
  fF = termination area       (length TERM)

Detour: rOFF (N1->D0) -> dA (D0->D1) -> dB (D1->D2) -> dC (D2->D3) -> dD (D3->D4)
        -> rON (D4->N7).  D1,D2,D3 are fixed-time signals.
"""
import os
import subprocess
import xml.etree.ElementTree as ET

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-04_04-00-00"
SCRIPTS = os.path.join(BASE, "attempts/attempt-1/scripts")
OUT = os.path.join(BASE, "outputs")
NETS = os.path.join(OUT, "nets")
RUNS = os.path.join(OUT, "runs")
TABLES = os.path.join(OUT, "tables")
PLOTS = os.path.join(OUT, "plots")
for d in (NETS, RUNS, TABLES, PLOTS):
    os.makedirs(d, exist_ok=True)

SUMO_BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
SUMO = os.path.join(SUMO_BIN, "sumo")
NETCONVERT = os.path.join(SUMO_BIN, "netconvert")

# ---------------------------------------------------------------- parameters
DEFAULTS = dict(
    lanes_closed=1,      # number of RIGHT-hand lanes closed in the activity area
    wz_len=1500.0,       # activity-area length (m)
    taper_len=200.0,     # transition/taper length (m)
    aw_len=1500.0,       # advance-warning-area length (m)
    term_len=300.0,      # termination-area length (m)
    wz_speed_kmh=80.0,   # posted work-zone speed in taper+activity+termination
    free_speed_kmh=120.0,
    wz_speed_factor=0.95,  # driver behaviour inside the activity area
    wz_sigma=0.7,          # driver imperfection inside the activity area
)

MAIN_LANES = 3
ART_LANES = 2
ART_SPEED_KMH = 60.0
RAMP_SPEED_KMH = 60.0

X_N0, X_N1, X_N2 = 0.0, 2000.0, 3000.0
X_N7, X_N8 = 7500.0, 9500.0

MAINLINE_ORDER = ["fA", "fB", "fC", "fD", "fE", "fF", "fG", "fH"]
DETOUR_ORDER = ["rOFF", "dA", "dB", "dC", "dD", "rON"]


def geom(p):
    """Return node x-positions for a parameter dict."""
    x3 = X_N2 + p["aw_len"]
    x4 = x3 + p["taper_len"]
    x5 = x4 + p["wz_len"]
    x6 = x5 + p["term_len"]
    # N7 sits 1000 m past the end of the termination area.  With the default geometry
    # this evaluates to exactly 7500 m (= X_N7), so the default corridor is unchanged;
    # long advance-warning variants simply push the merge and sink downstream instead
    # of overrunning them.
    x7 = x6 + 1000.0
    return dict(N0=X_N0, N1=X_N1, N2=X_N2, N3=x3, N4=x4, N5=x5, N6=x6,
                N7=x7, N8=x7 + 2000.0)


def params(**kw):
    p = dict(DEFAULTS)
    p.update(kw)
    return p


def tag(p, rep, merge="zipper"):
    """Short filename tag encoding the geometry parameters + representation."""
    m = "" if rep != "geom" else f"_{merge[:3]}"
    return (f"{rep}{m}_lc{p['lanes_closed']}_wz{int(p['wz_len'])}"
            f"_tp{int(p['taper_len'])}_aw{int(p['aw_len'])}"
            f"_v{int(p['wz_speed_kmh'])}")


# ---------------------------------------------------------------- net build
def build_net(p, rep, outdir=NETS, force=False, merge="zipper"):
    """Build one compiled network.

    rep is one of:
      'full'  -- full 3-lane geometry everywhere (baseline / unobstructed, and the
                 carrier geometry for the rerouter and permission representations)
      'geom'  -- genuinely rebuilt net: fE (activity area) has 3-lanes_closed lanes,
                 the drop happens at node N4 (zipper), taper length = len(fD)
    """
    g = geom(p)
    name = tag(p, rep, merge)
    netfile = os.path.join(outdir, f"{name}.net.xml")
    if os.path.exists(netfile) and not force:
        return netfile

    nl = MAIN_LANES
    open_lanes = MAIN_LANES - p["lanes_closed"] if rep == "geom" else MAIN_LANES
    v_free = p["free_speed_kmh"] / 3.6
    v_wz = p["wz_speed_kmh"] / 3.6
    v_art = ART_SPEED_KMH / 3.6
    v_ramp = RAMP_SPEED_KMH / 3.6

    # ---- nodes
    nods = ['<nodes>']
    for n in ["N0", "N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"]:
        if n == "N1":
            t = 'type="priority"'
        elif n == "N7":
            t = 'type="zipper"'
        elif n == "N4" and rep == "geom":
            t = f'type="{merge}"'
        else:
            t = 'type="priority"'
        nods.append(f'  <node id="{n}" x="{g[n]}" y="0" {t}/>')
    # detour arterial nodes, offset south; spread between the diverge and the merge
    _f = [0.05, 0.22, 0.44, 0.69, 0.91, 0.96]
    ax = [X_N1 + f * (g["N7"] - X_N1) for f in _f]
    for i, x in enumerate(ax):
        nid = f"D{i}"
        t = 'type="traffic_light"' if nid in ("D1", "D2", "D3") else 'type="priority"'
        nods.append(f'  <node id="{nid}" x="{x}" y="-800" {t}/>')
    nods.append('</nodes>')

    # ---- edges
    def lane_speed_attrs(edge_id, nlanes, speed):
        return f'numLanes="{nlanes}" speed="{speed:.4f}"'

    edg = ['<edges>']
    mainspec = [
        ("fA", "N0", "N1", nl, v_free),
        ("fB", "N1", "N2", nl, v_free),
        ("fC", "N2", "N3", nl, v_free),
        ("fD", "N3", "N4", nl, v_wz),           # taper: posted WZ speed
        ("fE", "N4", "N5", open_lanes, v_wz),   # activity area
        ("fF", "N5", "N6", open_lanes if rep == "geom" else nl, v_wz),
        ("fG", "N6", "N7", nl, v_free),
        ("fH", "N7", "N8", nl, v_free),
    ]
    for eid, f, t, n, s in mainspec:
        edg.append(f'  <edge id="{eid}" from="{f}" to="{t}" '
                   f'{lane_speed_attrs(eid, n, s)} spreadType="center" priority="10"/>')
    # detour
    det = [("rOFF", "N1", "D0", 1, v_ramp), ("dA", "D0", "D1", ART_LANES, v_art),
           ("dB", "D1", "D2", ART_LANES, v_art), ("dC", "D2", "D3", ART_LANES, v_art),
           ("dD", "D3", "D4", ART_LANES, v_art), ("rON", "D4", "N7", 1, v_ramp)]
    for eid, f, t, n, s in det:
        edg.append(f'  <edge id="{eid}" from="{f}" to="{t}" '
                   f'{lane_speed_attrs(eid, n, s)} spreadType="center" priority="3"/>')
    edg.append('</edges>')

    # ---- connections
    con = ['<connections>']

    def straight(a, b, na, nb):
        for i in range(min(na, nb)):
            con.append(f'  <connection from="{a}" to="{b}" fromLane="{i}" toLane="{i}"/>')

    straight("fA", "fB", nl, nl)
    # off-ramp diverge from mainline lane 0 (right)
    con.append('  <connection from="fA" to="rOFF" fromLane="0" toLane="0"/>')
    straight("fB", "fC", nl, nl)
    straight("fC", "fD", nl, nl)
    if rep == "geom":
        # geometric lane drop at N4: right-hand lanes_closed lanes end.
        k = p["lanes_closed"]
        # lane k-1 and lane k both feed downstream lane 0 (the zipper pair);
        # remaining lanes go straight across with the lateral shift.
        for i in range(k, nl):
            con.append(f'  <connection from="fD" to="fE" fromLane="{i}" toLane="{i-k}"/>')
        for i in range(k):
            con.append(f'  <connection from="fD" to="fE" fromLane="{i}" toLane="0"/>')
        straight("fE", "fF", open_lanes, open_lanes)
        # termination area: lanes re-open
        for i in range(open_lanes):
            con.append(f'  <connection from="fF" to="fG" fromLane="{i}" toLane="{i+k}"/>')
    else:
        straight("fD", "fE", nl, nl)
        straight("fE", "fF", nl, nl)
        straight("fF", "fG", nl, nl)
    straight("fG", "fH", nl, nl)
    # detour chain
    con.append('  <connection from="rOFF" to="dA" fromLane="0" toLane="0"/>')
    for a, b in [("dA", "dB"), ("dB", "dC"), ("dC", "dD")]:
        straight(a, b, ART_LANES, ART_LANES)
    con.append('  <connection from="dD" to="rON" fromLane="0" toLane="0"/>')
    # on-ramp merges into mainline lane 0 (zipper at N7)
    con.append('  <connection from="rON" to="fH" fromLane="0" toLane="0"/>')
    con.append('</connections>')

    stem = os.path.join(outdir, name)
    for suffix, body in (("nod", nods), ("edg", edg), ("con", con)):
        with open(f"{stem}.{suffix}.xml", "w") as fh:
            fh.write("\n".join(body) + "\n")

    # ---- fixed-time signals on the arterial (green/red split limits detour capacity)
    tll = ['<additional>']
    for nid in ("D1", "D2", "D3"):
        tll.append(f'  <tlLogic id="{nid}" type="static" programID="0" offset="0">')
        tll.append('    <phase duration="34" state="GG"/>')
        tll.append('    <phase duration="4"  state="yy"/>')
        tll.append('    <phase duration="30" state="rr"/>')
        tll.append('    <phase duration="2"  state="rr"/>')
        tll.append('  </tlLogic>')
    tll.append('</additional>')
    with open(f"{stem}.tll.xml", "w") as fh:
        fh.write("\n".join(tll) + "\n")

    cmd = [NETCONVERT,
           "--node-files", f"{stem}.nod.xml",
           "--edge-files", f"{stem}.edg.xml",
           "--connection-files", f"{stem}.con.xml",
           "--tllogic-files", f"{stem}.tll.xml",
           "--no-turnarounds", "true",
           "--junctions.limit-turn-speed", "-1",
           "--default.junctions.keep-clear", "true",
           "-o", netfile]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"netconvert failed for {name}:\n{r.stderr}")
    return netfile


# ---------------------------------------------------------------- net verify
def net_lane_table(netfile):
    """{edge_id: [(lane_id, length, speed, allow, disallow), ...]} from the COMPILED net."""
    root = ET.parse(netfile).getroot()
    out = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = []
        for ln in e.findall("lane"):
            lanes.append((ln.get("id"), float(ln.get("length")), float(ln.get("speed")),
                          ln.get("allow"), ln.get("disallow")))
        out[e.get("id")] = lanes
    return out


def net_connections(netfile, frm=None, to=None):
    root = ET.parse(netfile).getroot()
    res = []
    for c in root.findall("connection"):
        if frm and c.get("from") != frm:
            continue
        if to and c.get("to") != to:
            continue
        res.append(dict(c.attrib))
    return res


# ---------------------------------------------------------------- permission edit
def apply_permission_closure(src_net, dst_net, edges_lanes, disallow="all"):
    """Representation R2: edit the COMPILED net's lane permissions in place.

    edges_lanes: list of lane ids, e.g. ['fE_0'].
    """
    tree = ET.parse(src_net)
    root = tree.getroot()
    want = set(edges_lanes)
    hit = set()
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            if ln.get("id") in want:
                ln.set("disallow", disallow)
                if "allow" in ln.attrib:
                    del ln.attrib["allow"]
                hit.add(ln.get("id"))
    missing = want - hit
    if missing:
        raise RuntimeError(f"lanes not found in {src_net}: {missing}")
    tree.write(dst_net, encoding="UTF-8", xml_declaration=True)
    return dst_net
