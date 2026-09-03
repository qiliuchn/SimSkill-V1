#!/usr/bin/env python3
"""
01_build_scenario.py -- Build a 5-intersection signalized arterial corridor for the
traffic-state-estimation-from-partial-sensor-data study.

Geometry
--------
  W0 --eb_0--> J1 --eb_1--> J2 --eb_2--> J3 --eb_3--> J4 --eb_4--> J5 --eb_5--> E6
     <--wb_0--    <--wb_1--    <--wb_2--    <--wb_3--    <--wb_4--    <--wb_5--

  Cross street at each Ji: S_i --nb_i--> Ji --nbo_i--> N_i
                           N_i --sb_i--> Ji --sbo_i--> S_i

Only THROUGH movements are permitted (no turns).  This is a deliberate
simplification: it keeps routes deterministic (no rerouting, no turn-ratio
stochasticity) so that the ONLY thing changing between sensing arms is the
observation layer.

Signals: FIXED-TIME (static), 90 s cycle, held byte-identical across all arms.
J3 is deliberately given a shorter arterial green so it is the corridor
bottleneck and the EB queue there grows past the advance-detector ladder.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))
os.makedirs(SCEN, exist_ok=True)

# ----------------------------------------------------------------- geometry
SPACING = 400.0          # m between arterial intersections
CROSS_LEN = 260.0        # m cross-street stub length
N_INT = 5                # J1..J5
ART_SPEED = 13.89        # m/s (50 km/h)
CROSS_SPEED = 11.11      # m/s (40 km/h)
ART_LANES = 2
CROSS_LANES = 1

# ----------------------------------------------------------------- signals
CYCLE = 90
ART_GREEN_NORMAL = 52
ART_GREEN_J3 = 44        # bottleneck intersection
YELLOW = 4
# cross green = CYCLE - art_green - 2*YELLOW

# progression offsets for EB band, offset_i = i * SPACING / ART_SPEED  (mod CYCLE)
OFFSETS = [int(round(i * SPACING / ART_SPEED)) % CYCLE for i in range(N_INT)]


def node_x(i):
    """i = 0 -> W0, 1..5 -> J1..J5, 6 -> E6"""
    return (i - 1) * SPACING


def write_nodes():
    lines = ['<nodes>']
    lines.append(f'  <node id="W0" x="{node_x(0):.1f}" y="0.0" type="priority"/>')
    for i in range(1, N_INT + 1):
        lines.append(f'  <node id="J{i}" x="{node_x(i):.1f}" y="0.0" type="traffic_light" tl="J{i}"/>')
        lines.append(f'  <node id="N{i}" x="{node_x(i):.1f}" y="{CROSS_LEN:.1f}" type="priority"/>')
        lines.append(f'  <node id="S{i}" x="{node_x(i):.1f}" y="{-CROSS_LEN:.1f}" type="priority"/>')
    lines.append(f'  <node id="E6" x="{node_x(N_INT + 1):.1f}" y="0.0" type="priority"/>')
    lines.append('</nodes>')
    open(os.path.join(SCEN, "arterial.nod.xml"), "w").write("\n".join(lines) + "\n")


def _art_node(i):
    if i == 0:
        return "W0"
    if i == N_INT + 1:
        return "E6"
    return f"J{i}"


def write_edges():
    lines = ['<edges>']
    for i in range(N_INT + 1):           # eb_0 .. eb_5
        a, b = _art_node(i), _art_node(i + 1)
        lines.append(f'  <edge id="eb_{i}" from="{a}" to="{b}" numLanes="{ART_LANES}" '
                     f'speed="{ART_SPEED}" priority="10"/>')
        lines.append(f'  <edge id="wb_{i}" from="{b}" to="{a}" numLanes="{ART_LANES}" '
                     f'speed="{ART_SPEED}" priority="10"/>')
    for i in range(1, N_INT + 1):
        lines.append(f'  <edge id="nb_{i}" from="S{i}" to="J{i}" numLanes="{CROSS_LANES}" '
                     f'speed="{CROSS_SPEED}" priority="5"/>')
        lines.append(f'  <edge id="nbo_{i}" from="J{i}" to="N{i}" numLanes="{CROSS_LANES}" '
                     f'speed="{CROSS_SPEED}" priority="5"/>')
        lines.append(f'  <edge id="sb_{i}" from="N{i}" to="J{i}" numLanes="{CROSS_LANES}" '
                     f'speed="{CROSS_SPEED}" priority="5"/>')
        lines.append(f'  <edge id="sbo_{i}" from="J{i}" to="S{i}" numLanes="{CROSS_LANES}" '
                     f'speed="{CROSS_SPEED}" priority="5"/>')
    lines.append('</edges>')
    open(os.path.join(SCEN, "arterial.edg.xml"), "w").write("\n".join(lines) + "\n")


def write_connections():
    """Through movements only."""
    lines = ['<connections>']
    for i in range(1, N_INT + 1):
        for ln in range(ART_LANES):
            lines.append(f'  <connection from="eb_{i-1}" to="eb_{i}" fromLane="{ln}" toLane="{ln}"/>')
            lines.append(f'  <connection from="wb_{i}" to="wb_{i-1}" fromLane="{ln}" toLane="{ln}"/>')
        lines.append(f'  <connection from="nb_{i}" to="nbo_{i}" fromLane="0" toLane="0"/>')
        lines.append(f'  <connection from="sb_{i}" to="sbo_{i}" fromLane="0" toLane="0"/>')
    lines.append('</connections>')
    open(os.path.join(SCEN, "arterial.con.xml"), "w").write("\n".join(lines) + "\n")


def run_netconvert():
    net = os.path.join(SCEN, "arterial.net.xml")
    cmd = [
        "netconvert",
        "-n", os.path.join(SCEN, "arterial.nod.xml"),
        "-e", os.path.join(SCEN, "arterial.edg.xml"),
        "-x", os.path.join(SCEN, "arterial.con.xml"),
        "-o", net,
        "--no-turnarounds", "true",
        "--tls.default-type", "static",
        "--default.junctions.keep-clear", "true",
        "--no-internal-links", "false",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr); sys.exit(1)
    if r.stderr.strip():
        print("netconvert stderr:", r.stderr.strip()[:2000])
    return net


def rewrite_tls(net):
    """Read netconvert-generated tlLogic, rewrite durations+offset, emit tls.add.xml.

    We keep the generated PHASE STATE STRINGS verbatim (they encode the correct
    link ordering) and only change durations and offsets.  Generated programs for
    a 4-leg through-only crossing have 4 phases: art-green, art-yellow,
    cross-green, cross-yellow.
    """
    tree = ET.parse(net)
    root = tree.getroot()
    out = ['<additional>']
    report = {}
    for tl in root.findall("tlLogic"):
        tlid = tl.get("id")
        idx = int(tlid[1:])
        phases = tl.findall("phase")
        states = [p.get("state") for p in phases]
        if len(states) != 4:
            raise RuntimeError(f"{tlid}: expected 4 generated phases, got {len(states)}: {states}")
        art_green = ART_GREEN_J3 if idx == 3 else ART_GREEN_NORMAL
        cross_green = CYCLE - art_green - 2 * YELLOW
        durs = [art_green, YELLOW, cross_green, YELLOW]
        off = OFFSETS[idx - 1]
        out.append(f'  <tlLogic id="{tlid}" type="static" programID="fixed" offset="{off}">')
        for d, s in zip(durs, states):
            out.append(f'    <phase duration="{d}" state="{s}"/>')
        out.append('  </tlLogic>')
        report[tlid] = dict(offset=off, durations=durs, states=states)
    out.append('</additional>')
    open(os.path.join(SCEN, "tls.add.xml"), "w").write("\n".join(out) + "\n")
    return report


def main():
    write_nodes()
    write_edges()
    write_connections()
    net = run_netconvert()
    rep = rewrite_tls(net)
    print("Network built:", net)
    for k, v in sorted(rep.items()):
        print(f"  {k} offset={v['offset']:3d} durations={v['durations']} states={v['states']}")


if __name__ == "__main__":
    main()
