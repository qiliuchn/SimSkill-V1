"""Shared helpers: SUMO binary resolution, paths, XML utilities.

Used by every script in this study.
"""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../outputs
NET_DIR = os.path.join(BASE, "net")
CFG_DIR = os.path.join(BASE, "cfg")
RUN_DIR = os.path.join(BASE, "runs")
ANA_DIR = os.path.join(BASE, "analysis")
FIG_DIR = os.path.join(BASE, "figures")
for _d in (NET_DIR, CFG_DIR, RUN_DIR, ANA_DIR, FIG_DIR):
    os.makedirs(_d, exist_ok=True)


def sumo_home():
    sh = os.environ.get("SUMO_HOME")
    if sh:
        return sh
    b = shutil.which("sumo")
    if b:
        # <prefix>/bin/sumo -> <prefix>/share/sumo
        cand = os.path.join(os.path.dirname(os.path.dirname(b)), "share", "sumo")
        if os.path.isdir(cand):
            return cand
    raise RuntimeError("SUMO_HOME not resolvable")


def add_tools_to_path():
    t = os.path.join(sumo_home(), "tools")
    if t not in sys.path:
        sys.path.insert(0, t)
    return t


def find_bin(name):
    """Resolve a SUMO binary: PATH -> next to sumo -> $SUMO_HOME/bin."""
    p = shutil.which(name)
    if p:
        return p
    s = shutil.which("sumo")
    if s:
        cand = os.path.join(os.path.dirname(s), name)
        if os.path.exists(cand):
            return cand
    sh = os.environ.get("SUMO_HOME")
    if sh:
        for c in (os.path.join(sh, "bin", name),
                  os.path.join(os.path.dirname(sh.rstrip("/")), "bin", name)):
            if os.path.exists(c):
                return c
    raise RuntimeError("cannot find binary %s" % name)


SUMO = find_bin("sumo")
NETCONVERT = find_bin("netconvert")


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("cmd failed: %s\nSTDOUT:%s\nSTDERR:%s"
                           % (" ".join(map(str, cmd)), r.stdout[-4000:], r.stderr[-4000:]))
    return r


def parse_shape(s):
    pts = []
    for tok in s.split():
        c = [float(x) for x in tok.split(",")]
        if len(c) == 2:
            c.append(0.0)
        pts.append(tuple(c))
    return pts


def net_lane_grade_pct(net_xml, edge_id, lane_idx=0):
    """Realized grade (%) of a lane, read back from the COMPILED net's shape."""
    root = ET.parse(net_xml).getroot()
    for e in root.findall("edge"):
        if e.get("id") != edge_id:
            continue
        for ln in e.findall("lane"):
            if int(ln.get("index")) != lane_idx:
                continue
            pts = parse_shape(ln.get("shape"))
            (x0, y0, z0), (x1, y1, z1) = pts[0], pts[-1]
            horiz = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            return 100.0 * (z1 - z0) / horiz if horiz > 0 else 0.0
    raise KeyError("edge/lane not found: %s_%d" % (edge_id, lane_idx))


def net_lane_length(net_xml, lane_id):
    root = ET.parse(net_xml).getroot()
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            if ln.get("id") == lane_id:
                return float(ln.get("length"))
    raise KeyError(lane_id)


def net_tls_links(net_xml, tls_id):
    """linkIndex -> dict(from_edge, from_lane, to_edge, to_lane, via) from the COMPILED net."""
    root = ET.parse(net_xml).getroot()
    out = {}
    for c in root.findall("connection"):
        if c.get("tl") != tls_id:
            continue
        li = int(c.get("linkIndex"))
        out[li] = dict(from_edge=c.get("from"), from_lane=int(c.get("fromLane")),
                       to_edge=c.get("to"), to_lane=int(c.get("toLane")),
                       via=c.get("via"), dir=c.get("dir"))
    return out


def net_internal_lengths(net_xml):
    """internal lane id -> length (the physical crossing distance of each movement)."""
    root = ET.parse(net_xml).getroot()
    out = {}
    for e in root.findall("edge"):
        if e.get("function") != "internal":
            continue
        for ln in e.findall("lane"):
            out[ln.get("id")] = float(ln.get("length"))
    return out


def last_summary_value(summary_xml, attr):
    """summary.xml cumulative fields (teleports, collisions) -> LAST step value, never a sum."""
    try:
        root = ET.parse(summary_xml).getroot()
    except Exception:
        return None
    val = None
    for st in root.findall("step"):
        v = st.get(attr)
        if v is not None:
            val = float(v)
    return val


def summary_series(summary_xml, attr):
    root = ET.parse(summary_xml).getroot()
    return [(float(s.get("time")), float(s.get(attr))) for s in root.findall("step")]
