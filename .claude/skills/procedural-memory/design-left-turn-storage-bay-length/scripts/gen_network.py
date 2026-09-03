#!/usr/bin/env python3
"""
Build a 4-leg signalized intersection whose NORTH approach carries a left-turn
STORAGE BAY of configurable length L.

Geometry (north approach, total length APPROACH_LEN = 400 m):

    Nf (fringe, y=+400)
      |            in_N_up   : 1 lane, THROUGH+RIGHT only, length = 400 - L
      |                        (left-turners must queue here if the bay is full)
    Nm (y = +L)   <-- bay entrance (taper point)
      |            in_N_bay  : 2 lanes, length = L
      |                        lane 0 = through + right
      |                        lane 1 = LEFT-TURN ONLY  (the storage bay)
      C (signalized junction, y=0)

The `full` variant is the upper-bound control: no split, a single 400 m
2-lane approach edge (lane 1 = exclusive left the whole way).

South / East / West approaches are held constant: 2 lanes, 250 m,
lane 0 = through+right, lane 1 = exclusive left (full length).

Usage:
    python3 gen_network.py --bay 50   --outdir <dir>
    python3 gen_network.py --bay full --outdir <dir>
"""
import argparse
import os
import shutil
import subprocess
import sys

APPROACH_LEN = 400.0     # north approach total length (m)
SIDE_LEN = 250.0         # other approaches (m)
SPEED = 13.89            # m/s (50 km/h)


def find_netconvert():
    p = shutil.which("netconvert")
    if p:
        return p
    s = shutil.which("sumo")
    if s:
        cand = os.path.join(os.path.dirname(s), "netconvert")
        if os.path.exists(cand):
            return cand
    home = os.environ.get("SUMO_HOME")
    if home:
        for c in (os.path.join(home, "bin", "netconvert"),
                  os.path.join(os.path.dirname(home), "bin", "netconvert")):
            if os.path.exists(c):
                return c
    raise RuntimeError("netconvert not found")


def _compiled_lengths(net):
    """Return {edge_id: lane length} for the north-approach edges of a compiled net."""
    import xml.etree.ElementTree as ET
    r = ET.parse(net).getroot()
    out = {}
    for ed in r.findall("edge"):
        if ed.get("function") == "internal":
            continue
        out[ed.get("id")] = float(ed.find("lane").get("length"))
    return out


def build(bay, outdir, verbose=False):
    """Build the network, iteratively calibrating node positions so the COMPILED
    lane lengths match the intended geometry:
        compiled len(in_N_bay) == L
        compiled len(in_N_up)  == APPROACH_LEN - L   (total approach held constant)
    netconvert shortens edges by the junction radii, so nominal node spacing !=
    usable storage length; without this calibration a nominal 50 m bay compiles
    to only 35.6 m of actual storage."""
    full = (bay == "full")
    L = APPROACH_LEN if full else float(bay)
    # initial guesses, refined below
    y_nm = L + 14.4
    y_nf = APPROACH_LEN + 18.4
    for it in range(8):
        net = _build_once(bay, outdir, y_nm, y_nf)
        cl = _compiled_lengths(net)
        if full:
            err_bay = cl["in_N_bay"] - APPROACH_LEN
            if abs(err_bay) < 0.15:
                break
            y_nf -= err_bay
        else:
            err_bay = cl["in_N_bay"] - L
            err_up = cl["in_N_up"] - (APPROACH_LEN - L)
            if abs(err_bay) < 0.15 and abs(err_up) < 0.15:
                break
            y_nm -= err_bay
            y_nf -= (err_bay + err_up)
        if verbose:
            print(f"  calib iter {it}: {cl.get('in_N_up')} / {cl['in_N_bay']}")
    return net


def _build_once(bay, outdir, y_nm, y_nf):
    os.makedirs(outdir, exist_ok=True)
    full = (bay == "full")
    L = APPROACH_LEN if full else float(bay)
    tag = "full" if full else f"{int(L)}"

    # ---------------- nodes ----------------
    nodes = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    nodes.append('    <node id="C"  x="0"    y="0"    type="traffic_light" tlType="static"/>')
    nodes.append(f'    <node id="Nf" x="0"    y="{y_nf:.3f}" type="priority"/>')
    if not full:
        nodes.append(f'    <node id="Nm" x="0"    y="{y_nm:.3f}" type="priority"/>')
    nodes.append(f'    <node id="Sf" x="0"    y="{-SIDE_LEN}" type="priority"/>')
    nodes.append(f'    <node id="Ef" x="{SIDE_LEN}"  y="0" type="priority"/>')
    nodes.append(f'    <node id="Wf" x="{-SIDE_LEN}" y="0" type="priority"/>')
    nodes.append("</nodes>")

    # ---------------- edges ----------------
    e = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    if full:
        e.append(f'    <edge id="in_N_bay" from="Nf" to="C"  numLanes="2" speed="{SPEED}" spreadType="right"/>')
    else:
        e.append(f'    <edge id="in_N_up"  from="Nf" to="Nm" numLanes="1" speed="{SPEED}" spreadType="right"/>')
        e.append(f'    <edge id="in_N_bay" from="Nm" to="C"  numLanes="2" speed="{SPEED}" spreadType="right"/>')
    e.append(f'    <edge id="out_N" from="C" to="Nf" numLanes="2" speed="{SPEED}" spreadType="right"/>')
    for d, n in (("S", "Sf"), ("E", "Ef"), ("W", "Wf")):
        e.append(f'    <edge id="in_{d}"  from="{n}" to="C" numLanes="2" speed="{SPEED}" spreadType="right"/>')
        e.append(f'    <edge id="out_{d}" from="C" to="{n}" numLanes="2" speed="{SPEED}" spreadType="right"/>')
    e.append("</edges>")

    # ---------------- connections ----------------
    # movement map (approach heading -> through / right / left destination)
    MOV = {
        "N": dict(s="out_S", r="out_W", l="out_E"),
        "S": dict(s="out_N", r="out_E", l="out_W"),
        "E": dict(s="out_W", r="out_N", l="out_S"),
        "W": dict(s="out_E", r="out_S", l="out_N"),
    }
    c = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    c.append("    <!-- NORTH approach: bay geometry under test -->")
    if not full:
        c.append('    <!-- bay entrance / taper: single upstream lane fans out to through lane 0 and bay lane 1 -->')
        c.append('    <connection from="in_N_up" to="in_N_bay" fromLane="0" toLane="0"/>')
        c.append('    <connection from="in_N_up" to="in_N_bay" fromLane="0" toLane="1"/>')
    c.append(f'    <connection from="in_N_bay" to="{MOV["N"]["s"]}" fromLane="0" toLane="1"/>  <!-- through -->')
    c.append(f'    <connection from="in_N_bay" to="{MOV["N"]["r"]}" fromLane="0" toLane="0"/>  <!-- right -->')
    c.append(f'    <connection from="in_N_bay" to="{MOV["N"]["l"]}" fromLane="1" toLane="1"/>  <!-- LEFT: bay lane only -->')
    for d in ("S", "E", "W"):
        c.append(f'    <!-- {d} approach (held constant) -->')
        c.append(f'    <connection from="in_{d}" to="{MOV[d]["s"]}" fromLane="0" toLane="1"/>')
        c.append(f'    <connection from="in_{d}" to="{MOV[d]["r"]}" fromLane="0" toLane="0"/>')
        c.append(f'    <connection from="in_{d}" to="{MOV[d]["l"]}" fromLane="1" toLane="1"/>')
    c.append("</connections>")

    base = os.path.join(outdir, f"bay_{tag}")
    for suffix, content in ((".nod.xml", nodes), (".edg.xml", e), (".con.xml", c)):
        with open(base + suffix, "w") as f:
            f.write("\n".join(content) + "\n")

    net = base + ".net.xml"
    cmd = [find_netconvert(),
           "-n", base + ".nod.xml",
           "-e", base + ".edg.xml",
           "-x", base + ".con.xml",
           "-o", net,
           "--no-turnarounds", "true",
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-internal-links", "false"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise RuntimeError("netconvert failed for bay=" + tag)
    if r.stderr.strip():
        print("[netconvert stderr]", r.stderr.strip()[:2000])
    return net


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bay", required=True, help="bay length in m, or 'full'")
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    n = build(a.bay, a.outdir, verbose=True)
    print(n, _compiled_lengths(n))
