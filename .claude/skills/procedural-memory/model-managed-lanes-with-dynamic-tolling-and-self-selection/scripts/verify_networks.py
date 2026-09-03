#!/usr/bin/env python3
"""Prove corridor geometry and lane permissions FROM THE COMPILED .net.xml (not the source XML)."""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.abspath(os.path.join(HERE, "..", "net"))
REP = os.path.abspath(os.path.join(HERE, "..", "analysis", "network_verification.txt"))
os.makedirs(os.path.dirname(REP), exist_ok=True)

MAIN = [f"m{i}" for i in range(1, 15)]
GATES = {"m2", "m5", "m8", "m11"}
out = []


def p(s=""):
    print(s)
    out.append(s)


for variant in ("gp4", "managed", "managed_gated"):
    path = os.path.join(NET, f"{variant}.net.xml")
    net = sumolib.net.readNet(path)
    p("=" * 78)
    p(f"VARIANT {variant}   ({path})")
    p("=" * 78)

    # --- geometry ---
    tot = 0.0
    nlanes = set()
    for eid in MAIN:
        e = net.getEdge(eid)
        tot += e.getLength()
        nlanes.add(e.getLaneNumber())
    p(f"mainline: {len(MAIN)} edges, total compiled length = {tot:.1f} m ({tot/1000:.3f} km)")
    p(f"mainline lane counts (compiled) = {sorted(nlanes)}   speed = {net.getEdge('m1').getSpeed():.2f} m/s"
      f" ({net.getEdge('m1').getSpeed()*2.23694:.1f} mph)")
    ramps = []
    for r in ("on1", "on2", "off1", "off2"):
        e = net.getEdge(r)
        ramps.append(f"{r}: len={e.getLength():.1f}m lanes={e.getLaneNumber()} speed={e.getSpeed():.2f}")
    p("ramps: " + " | ".join(ramps))
    p(f"on-ramp merge nodes: N3 type={net.getNode('N3').getType()}, N9 type={net.getNode('N9').getType()}")
    p(f"off-ramp diverge nodes: N6 type={net.getNode('N6').getType()}, N12 type={net.getNode('N12').getType()}")

    # zipper proof: connection state on the contested lane, read from raw XML
    root = ET.parse(path).getroot()
    zst = []
    for c in root.iter("connection"):
        if c.get("from") in ("m3", "on1") and c.get("to") == "m4" and c.get("toLane") == "0":
            zst.append(f"{c.get('from')}_{c.get('fromLane')}->m4_0 state={c.get('state')}")
        if c.get("from") == "m3" and c.get("to") == "m4" and c.get("toLane") == "2":
            zst.append(f"m3_2->m4_2 state={c.get('state')} (uncontested)")
    p("merge-1 connection states: " + "; ".join(zst))

    # --- lane permissions on the compiled net ---
    for li in range(4):
        allows = {vc: all(net.getEdge(eid).getLane(li).allows(vc) for eid in MAIN)
                  for vc in ("passenger", "hov", "bus", "truck")}
        p(f"  sumolib lane {li}: allowed-on-ALL-14-mainline-edges -> {allows}")
    # explicit allow strings from raw XML (authoritative + printable)
    perm = {}
    chg = {}
    for e in root.iter("edge"):
        if e.get("id") not in MAIN:
            continue
        for ln in e.iter("lane"):
            idx = int(ln.get("index"))
            perm.setdefault(idx, set()).add(ln.get("allow") or ("DISALLOW:" + ln.get("disallow") if ln.get("disallow") else "ALL"))
            chg.setdefault(idx, set()).add((ln.get("changeLeft") or "all", ln.get("changeRight") or "all"))
    for idx in sorted(perm):
        p(f"  lane index {idx}: allow-set across 14 mainline edges = {sorted(perm[idx])}")
    for idx in sorted(chg):
        p(f"  lane index {idx}: (changeLeft,changeRight) set = {sorted(chg[idx])}")

    # gate-specific check
    if variant == "managed_gated":
        gate_ok, nongate_ok = [], []
        for e in root.iter("edge"):
            eid = e.get("id")
            if eid not in MAIN:
                continue
            l2 = l3 = None
            for ln in e.iter("lane"):
                if int(ln.get("index")) == 2:
                    l2 = ln
                if int(ln.get("index")) == 3:
                    l3 = ln
            cl = l2.get("changeLeft") or "all"
            cr = l3.get("changeRight") or "all"
            if eid in GATES:
                gate_ok.append(f"{eid}:(cl={cl},cr={cr})")
            else:
                nongate_ok.append(f"{eid}:(cl={cl},cr={cr})")
        p("  GATE edges      : " + " ".join(gate_ok))
        p("  NON-GATE edges  : " + " ".join(nongate_ok))

    # internal-lane permission check at a junction (HSR gotcha relevance)
    ints = [l for l in root.iter("edge") if l.get("function") == "internal" and l.get("id", "").startswith(":N5")]
    for e in ints:
        for ln in e.iter("lane"):
            p(f"  internal {ln.get('id')}: allow={ln.get('allow')} disallow={ln.get('disallow')}")
    p()

# cross-variant diff proof
a = open(os.path.join(NET, "gp4.net.xml")).read()
b = open(os.path.join(NET, "managed.net.xml")).read()
c = open(os.path.join(NET, "managed_gated.net.xml")).read()
p(f"gp4 vs managed nets differ: {a != b};  managed vs managed_gated differ: {b != c}")
p(f'gp4 contains allow="hov bus": {chr(39)}hov bus{chr(39) } in gp4 -> {"hov bus" in a}')
p(f'managed contains allow="hov bus": {"hov bus" in b}')
p(f'managed_gated contains changeLeft="authority": {chr(34)}changeLeft={chr(34)}authority -> {"changeLeft=" + chr(34) + "authority" in c}')

open(REP, "w").write("\n".join(out) + "\n")
print(f"\nwritten -> {REP}")
