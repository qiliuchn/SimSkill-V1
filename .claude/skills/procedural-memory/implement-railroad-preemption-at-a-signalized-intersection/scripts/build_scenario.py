#!/usr/bin/env python3
"""
Build the rail-preemption corridor network + demand.

Geometry (all distances in m, road at y=0):

      RN (0, +900)                 JN (55, +400)
        |                             |
        | rail (bidi, vClass=rail)    | cross street
        |                             |
  W ----X--------- 55 m -------------J------------------ E
 (-600,0)  rail_crossing        traffic_light         (555,0)
        |                             |
        |                             |
      RS (0, -900)                 JS (55, -400)

The signalized 4-leg intersection J sits 55 m downstream (east) of the
at-grade rail crossing X, so a red-signal queue on edge X_J (55 m of storage)
physically extends back across the tracks.

Movements are through-only (explicit .con.xml) to keep the TLS state string
minimal and the "which movements feed vehicles back toward the crossing"
question unambiguous:
   link EB : X_J  -> J_E   (the approach LYING ACROSS the tracks)
   link WB : E_J  -> J_X   (feeds vehicles TOWARD the crossing)
   link NB : JS_J -> J_JN  (does NOT feed the crossing)
   link SB : JN_J -> J_JS  (does NOT feed the crossing)
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))   # episode dir
NET = os.path.join(ROOT, "outputs", "network")
os.makedirs(NET, exist_ok=True)

# ---------------------------------------------------------------- geometry --
CROSS_TO_STOPBAR = 55.0        # m, X -> J  (tuned, see FINDINGS)
ROAD_SPEED = 13.89             # m/s (50 km/h)
RAIL_SPEED = 22.0              # m/s (~79 km/h)
RAIL_APPROACH = 1500.0         # m each side of X.  The maximum achievable
                               # advance preemption time is bounded by this:
                               # approach/speed - crossing time-gap =
                               # 1500/22 - 15 = 53.2 s.
# Rail edge width is a GEOMETRIC device only: it sets how long junction X is
# ALONG THE ROAD.  14 m compiles to a 17.0 m crossing footprint, a realistic
# MUTCD "minimum track clearance distance" for a double-track crossing with
# gates.  It does not affect train dynamics (single rail lane either way).
RAIL_WIDTH = 14.0
# Drivers who queue across the tracks.  SUMO's DEFAULT (-1 = never violate
# keep-clear) makes the MUTCD failure mode structurally impossible -- see
# outputs/instrumentation/junction_blocking_probe.json.  0 = drivers do not
# defer to keep-clear, i.e. they queue across the crossing.
JM_IGNORE_KEEPCLEAR = 0

NOD = f"""<?xml version="1.0" encoding="UTF-8"?>
<nodes>
    <node id="W"  x="-600"  y="0"   type="priority"/>
    <node id="X"  x="0"     y="0"   type="rail_crossing"/>
    <node id="J"  x="{CROSS_TO_STOPBAR}" y="0" type="traffic_light" tl="J"/>
    <node id="E"  x="555"   y="0"   type="priority"/>
    <node id="RN" x="0"     y="{RAIL_APPROACH}"  type="priority"/>
    <node id="RS" x="0"     y="-{RAIL_APPROACH}" type="priority"/>
    <node id="JN" x="{CROSS_TO_STOPBAR}" y="400"  type="priority"/>
    <node id="JS" x="{CROSS_TO_STOPBAR}" y="-400" type="priority"/>
</nodes>
"""

EDG = f"""<?xml version="1.0" encoding="UTF-8"?>
<edges>
    <!-- main road, two-way, one lane each direction -->
    <edge id="W_X" from="W" to="X" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="X_J" from="X" to="J" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="J_E" from="J" to="E" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="E_J" from="E" to="J" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="J_X" from="J" to="X" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="X_W" from="X" to="W" priority="3" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <!-- cross street at J, two-way, one lane each direction -->
    <edge id="JS_J" from="JS" to="J" priority="2" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="J_JN" from="J" to="JN" priority="2" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="JN_J" from="JN" to="J" priority="2" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <edge id="J_JS" from="J" to="JS" priority="2" numLanes="1" speed="{ROAD_SPEED}" allow="passenger"/>
    <!-- bidirectional rail through X; spreadType=center so netconvert sees bidi -->
    <edge id="RS_X" from="RS" to="X" priority="1" numLanes="1" speed="{RAIL_SPEED}" spreadType="center" width="{RAIL_WIDTH}" allow="rail"/>
    <edge id="X_RN" from="X" to="RN" priority="1" numLanes="1" speed="{RAIL_SPEED}" spreadType="center" width="{RAIL_WIDTH}" allow="rail"/>
    <edge id="RN_X" from="RN" to="X" priority="1" numLanes="1" speed="{RAIL_SPEED}" spreadType="center" width="{RAIL_WIDTH}" allow="rail"/>
    <edge id="X_RS" from="X" to="RS" priority="1" numLanes="1" speed="{RAIL_SPEED}" spreadType="center" width="{RAIL_WIDTH}" allow="rail"/>
</edges>
"""

CON = """<?xml version="1.0" encoding="UTF-8"?>
<connections>
    <!-- crossing X: road through only, rail through only -->
    <connection from="W_X" to="X_J" fromLane="0" toLane="0"/>
    <connection from="J_X" to="X_W" fromLane="0" toLane="0"/>
    <connection from="RS_X" to="X_RN" fromLane="0" toLane="0"/>
    <connection from="RN_X" to="X_RS" fromLane="0" toLane="0"/>
    <!-- signal J: through only -->
    <connection from="X_J"  to="J_E"  fromLane="0" toLane="0"/>
    <connection from="E_J"  to="J_X"  fromLane="0" toLane="0"/>
    <connection from="JS_J" to="J_JN" fromLane="0" toLane="0"/>
    <connection from="JN_J" to="J_JS" fromLane="0" toLane="0"/>
</connections>
"""


def write(path, text):
    with open(path, "w") as f:
        f.write(text)
    return path


def build_net(tll=None):
    n = write(os.path.join(NET, "corridor.nod.xml"), NOD)
    e = write(os.path.join(NET, "corridor.edg.xml"), EDG)
    c = write(os.path.join(NET, "corridor.con.xml"), CON)
    out = os.path.join(NET, "corridor.net.xml")
    cmd = ["netconvert", "-n", n, "-e", e, "-x", c, "-o", out,
           "--no-turnarounds", "true", "--tls.default-type", "static",
           "--junctions.internal-link-detail", "10"]
    if tll:
        cmd += ["-i", tll]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("netconvert rc=", r.returncode)
    if r.stderr.strip():
        print("--- netconvert stderr ---")
        print(r.stderr)
    if r.returncode != 0:
        sys.exit(1)
    return out


def verify_net(netfile):
    """Confirm from the COMPILED net (not the source XML) that:
       - junction X really is type="rail_crossing" (not silently reverted)
       - junction J really is type="traffic_light"
       - the rail edge pair is recognised as bidirectional (bidi= attribute)
       - report link indices at J so the tlLogic state string can be authored
    """
    tree = ET.parse(netfile)
    root = tree.getroot()
    facts = {}
    for j in root.findall("junction"):
        if j.get("id") in ("X", "J"):
            facts["junction_" + j.get("id") + "_type"] = j.get("type")
            facts["junction_" + j.get("id") + "_shape"] = j.get("shape")
    bidi = {}
    for ed in root.findall("edge"):
        if ed.get("bidi"):
            bidi[ed.get("id")] = ed.get("bidi")
    facts["rail_bidi"] = bidi
    for ed in root.findall("edge"):
        if ed.get("id") in ("X_J", "J_X"):
            ln = ed.find("lane")
            facts["lane_%s_length" % ed.get("id")] = float(ln.get("length"))
            facts["lane_%s_shape" % ed.get("id")] = ln.get("shape")

    # link indices at J
    links = {}
    for con in root.findall("connection"):
        if con.get("tl") == "J":
            links[(con.get("from"), con.get("to"))] = int(con.get("linkIndex"))
    facts["J_link_index"] = {f"{a}->{b}": i for (a, b), i in sorted(links.items(), key=lambda kv: kv[1])}

    # crossing envelope from junction X's compiled shape bounding box
    shp = facts.get("junction_X_shape", "")
    xs = [float(p.split(",")[0]) for p in shp.split()] if shp else []
    facts["junction_X_xrange"] = [min(xs), max(xs)] if xs else None
    return facts, links


# --------------------------------------------------------------- tlLogic ----
YELLOW = 3
ALLRED = 2
G_EW = 40
G_NS = 40


def write_tls(links, path):
    """Author the fixed-time program using the linkIndex mapping read back from
    the compiled net -- never assume SUMO's link ordering."""
    n = len(links)
    idx = {
        "EB": links[("X_J", "J_E")],
        "WB": links[("E_J", "J_X")],
        "NB": links[("JS_J", "J_JN")],
        "SB": links[("JN_J", "J_JS")],
    }

    def st(spec):
        s = ["r"] * n
        for k, ch in spec.items():
            s[idx[k]] = ch
        return "".join(s)

    phases = [
        (G_EW, st({"EB": "G", "WB": "G"}), "EW green"),
        (YELLOW, st({"EB": "y", "WB": "y"}), "EW yellow"),
        (ALLRED, st({}), "all-red"),
        (G_NS, st({"NB": "G", "SB": "G"}), "NS green"),
        (YELLOW, st({"NB": "y", "SB": "y"}), "NS yellow"),
        (ALLRED, st({}), "all-red"),
    ]
    body = "\n".join(
        f'        <phase duration="{d}" state="{s}" name="{nm}"/>' for d, s, nm in phases)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<additional>
    <tlLogic id="J" type="static" programID="0" offset="0">
{body}
    </tlLogic>
</additional>
"""
    write(path, xml)
    return idx, [p[1] for p in phases]


# ----------------------------------------------------------------- demand ---
def write_routes(path, eb_vph, wb_vph, ns_vph, train_headway, sim_end,
                 train_first=600, seed_note="", keepclear=JM_IGNORE_KEEPCLEAR):
    trains = []
    t = train_first
    i = 0
    while t <= sim_end - 300:
        direction = "NB" if i % 2 == 0 else "SB"
        route = "rail_nb" if i % 2 == 0 else "rail_sb"
        trains.append(f'    <vehicle id="train_{i}_{direction}" type="train" '
                      f'route="{route}" depart="{t}" departSpeed="max"/>')
        t += train_headway
        i += 1
    trains_xml = "\n".join(trains)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- {seed_note} -->
<routes>
    <vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6"
           decel="4.5" sigma="0.5" maxSpeed="13.89" tau="1.0"
           jmIgnoreKeepClearTime="{keepclear}"/>
    <vType id="train" vClass="rail" carFollowModel="Rail" trainType="RB628"
           length="50" accel="0.8" decel="0.9" maxSpeed="{RAIL_SPEED}"/>

    <route id="eb"      edges="W_X X_J J_E"/>
    <route id="wb"      edges="E_J J_X X_W"/>
    <route id="nb"      edges="JS_J J_JN"/>
    <route id="sb"      edges="JN_J J_JS"/>
    <route id="rail_nb" edges="RS_X X_RN"/>
    <route id="rail_sb" edges="RN_X X_RS"/>

    <flow id="f_eb" type="car" route="eb" begin="0" end="{sim_end}" vehsPerHour="{eb_vph}" departSpeed="max" departPos="base"/>
    <flow id="f_wb" type="car" route="wb" begin="0" end="{sim_end}" vehsPerHour="{wb_vph}" departSpeed="max" departPos="base"/>
    <flow id="f_nb" type="car" route="nb" begin="0" end="{sim_end}" vehsPerHour="{ns_vph}" departSpeed="max" departPos="base"/>
    <flow id="f_sb" type="car" route="sb" begin="0" end="{sim_end}" vehsPerHour="{ns_vph}" departSpeed="max" departPos="base"/>

{trains_xml}
</routes>
"""
    write(path, xml)
    return len(trains)


if __name__ == "__main__":
    import json
    # pass 1: compile with netconvert's default TLS to learn the true linkIndex
    # ordering at J (never assume SUMO's link ordering)
    net = build_net()
    _, links = verify_net(net)
    tll = os.path.join(NET, "signal.tll.xml")
    idx, phase_states = write_tls(links, tll)
    # pass 2: recompile with the hand-authored program baked in as programID "0"
    net = build_net(tll=tll)
    facts, links2 = verify_net(net)
    assert links2 == links, "link ordering changed between passes"
    facts["J_state_index"] = idx
    facts["phase_states_authored"] = phase_states
    # read back the COMPILED program, don't trust the input file
    root = ET.parse(net).getroot()
    for tl in root.findall("tlLogic"):
        if tl.get("id") == "J":
            facts["phase_states_compiled"] = [
                [p.get("duration"), p.get("state"), p.get("name")] for p in tl.findall("phase")]
    for lvl in (450, 600, 750):
        for hw in (290, 120):
            ntr = write_routes(
                os.path.join(NET, f"demand_eb{lvl}_h{hw}.rou.xml"),
                lvl, 300, 400, hw, 3600)
            facts[f"n_trains_eb{lvl}_h{hw}"] = ntr
    print(json.dumps(facts, indent=2))
    with open(os.path.join(NET, "net_verification.json"), "w") as f:
        json.dump(facts, f, indent=2)
