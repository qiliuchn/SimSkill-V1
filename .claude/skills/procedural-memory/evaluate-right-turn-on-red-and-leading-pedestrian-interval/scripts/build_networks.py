#!/usr/bin/env python3
"""Build the two geometry variants of a 4-leg signalised intersection with
sidewalks / marked crossings / walkingareas.

Variant A ("excl"):   each approach has an EXCLUSIVE right-turn lane.
                      vehicle lanes (right->left): [R] [T] [L]
Variant B ("shared"): the right turn SHARES the through lane.
                      vehicle lanes (right->left): [T+R] [L]

Both variants: 2 vehicle lanes on every departure edge; right and through
connect into departure lane 0 (so a right-turner merges into the curb lane the
through movement also uses -> a genuine merge conflict), left into lane 1.

Approach geometry: 300 m arms, 13.89 m/s.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))  # episode dir
NETDIR = os.path.join(BASE, "outputs", "net")
os.makedirs(NETDIR, exist_ok=True)

ARM = 300.0
SPEED = 13.89

# arm -> (x, y) of the fringe node
ARMS = {"N": (0.0, ARM), "E": (ARM, 0.0), "S": (0.0, -ARM), "W": (-ARM, 0.0)}

# approach -> {movement: destination arm}
MOVES = {
    "N": {"r": "W", "s": "S", "l": "E"},
    "E": {"r": "N", "s": "W", "l": "S"},
    "S": {"r": "E", "s": "N", "l": "W"},
    "W": {"r": "S", "s": "E", "l": "N"},
}


def write_plain(variant, prefix):
    """variant: 'excl' -> 3 vehicle lanes in; 'shared' -> 2 vehicle lanes in."""
    n_in = 3 if variant == "excl" else 2

    nodes = ['<nodes>', '  <node id="C" x="0" y="0" type="traffic_light" tlType="static"/>']
    for a, (x, y) in ARMS.items():
        nodes.append(f'  <node id="{a}" x="{x}" y="{y}" type="priority"/>')
    nodes.append('</nodes>')

    edges = ['<edges>']
    for a in ARMS:
        edges.append(f'  <edge id="in_{a}"  from="{a}" to="C" numLanes="{n_in}" speed="{SPEED}" priority="3"/>')
        edges.append(f'  <edge id="out_{a}" from="C" to="{a}" numLanes="2" speed="{SPEED}" priority="3"/>')
    edges.append('</edges>')

    # lane assignment of the *vehicle* lanes (index within the vehicle lanes,
    # 0 = rightmost).  netconvert prepends the guessed sidewalk as lane 0, so
    # the final index is verified from the compiled net afterwards, not assumed.
    if variant == "excl":
        fl = {"r": 0, "s": 1, "l": 2}
    else:
        fl = {"r": 0, "s": 0, "l": 1}
    tl = {"r": 0, "s": 0, "l": 1}

    cons = ['<connections>']
    for a, mv in MOVES.items():
        for m in ("r", "s", "l"):
            cons.append(
                f'  <connection from="in_{a}" to="out_{mv[m]}" '
                f'fromLane="{fl[m]}" toLane="{tl[m]}"/>')
    cons.append('</connections>')

    for name, body in (("nod", nodes), ("edg", edges), ("con", cons)):
        with open(os.path.join(NETDIR, f"{prefix}.{name}.xml"), "w") as f:
            f.write("\n".join(body) + "\n")


def build(variant, prefix):
    write_plain(variant, prefix)
    net = os.path.join(NETDIR, f"{prefix}.net.xml")
    cmd = [
        "netconvert",
        "-n", os.path.join(NETDIR, f"{prefix}.nod.xml"),
        "-e", os.path.join(NETDIR, f"{prefix}.edg.xml"),
        "-x", os.path.join(NETDIR, f"{prefix}.con.xml"),
        "--sidewalks.guess", "--crossings.guess", "--walkingareas",
        "--sidewalks.guess.max-speed", "20",
        "--no-turnarounds", "true",
        "--tls.default-type", "static",
        "--default.junctions.keep-clear", "true",
        "-o", net,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(os.path.join(NETDIR, f"{prefix}.netconvert.log"), "w") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\nSTDOUT:\n" + r.stdout + "\n\nSTDERR:\n" + r.stderr)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit(f"netconvert failed for {prefix}")
    return net


def verify(net, prefix):
    """Verify state-string length == vehicle links + crossing links, and dump
    the linkIndex -> movement map derived from the compiled net itself."""
    root = ET.parse(net).getroot()
    tls = root.find("tlLogic")
    states = [p.get("state") for p in tls.findall("phase")]
    slen = set(len(s) for s in states)
    assert len(slen) == 1, f"ragged state strings in {prefix}: {slen}"
    slen = slen.pop()

    crossing_edges = {e.get("id"): e.get("crossingEdges", "").split()
                      for e in root.findall("edge") if e.get("function") == "crossing"}
    veh_links, xing_links = {}, {}
    for c in root.findall("connection"):
        if c.get("tl") != "C":
            continue
        li = int(c.get("linkIndex"))
        frm, to = c.get("from"), c.get("to")
        if to in crossing_edges:
            xing_links[li] = (frm, to, crossing_edges[to])
        else:
            veh_links[li] = (frm, to, c.get("dir"), int(c.get("fromLane")), int(c.get("toLane")))

    report = []
    report.append(f"=== {prefix} ({net}) ===")
    report.append(f"tlLogic id={tls.get('id')} programID={tls.get('programID')} phases={len(states)}")
    report.append(f"state-string length          = {slen}")
    report.append(f"vehicle <connection tl=C>    = {len(veh_links)}")
    report.append(f"crossing <connection tl=C>   = {len(xing_links)}")
    report.append(f"sum                          = {len(veh_links) + len(xing_links)}")
    ok = slen == len(veh_links) + len(xing_links)
    report.append(f"CHECK state_len == veh+xing  : {'PASS' if ok else 'FAIL'}")
    report.append("")
    report.append("linkIndex -> (from-edge, to-edge, movement / crossing-id)")
    for li in sorted(set(veh_links) | set(xing_links)):
        if li in veh_links:
            f_, t_, d_, fl_, tl_ = veh_links[li]
            dname = {"r": "RIGHT", "s": "THROUGH", "l": "LEFT", "t": "U-TURN"}.get(d_, d_)
            report.append(f"  {li:3d}  {f_:>6s} -> {t_:<6s}  {dname:<8s} fromLane={fl_} toLane={tl_}")
        else:
            f_, t_, ce = xing_links[li]
            report.append(f"  {li:3d}  {f_:>6s} -> {t_:<6s}  CROSSING spans {ce}")
    report.append("")
    report.append("compiled default program phases:")
    for i, p in enumerate(tls.findall("phase")):
        report.append(f"  phase {i:2d} dur={p.get('duration'):>4s} {p.get('state')}")
    report.append("")
    # lane composition of one approach
    for e in root.findall("edge"):
        if e.get("id") == "in_N":
            report.append("in_N lanes:")
            for ln in e.findall("lane"):
                report.append(f"  idx={ln.get('index')} allow={ln.get('allow')} disallow={ln.get('disallow')} width={ln.get('width')}")
    txt = "\n".join(report)
    print(txt)
    return txt, ok


if __name__ == "__main__":
    out = []
    allok = True
    for variant, prefix in (("excl", "A_excl"), ("shared", "B_shared")):
        net = build(variant, prefix)
        txt, ok = verify(net, prefix)
        out.append(txt)
        allok &= ok
    with open(os.path.join(BASE, "outputs", "net_verification.txt"), "w") as f:
        f.write("\n\n".join(out) + "\n")
    print("\nALL CHECKS PASS" if allok else "\nCHECK FAILED")
