#!/usr/bin/env python3
"""Verify the compiled corridor .net.xml: geometry, lane connectivity, merge/zipper
states, ramp storage lengths, separation of freeway vs surface, TLS link indices."""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

net_path = sys.argv[1]
root = ET.parse(net_path).getroot()

edges = {}
for e in root.findall("edge"):
    if e.get("function") == "internal":
        continue
    lanes = [(l.get("id"), float(l.get("length")), float(l.get("speed"))) for l in e.findall("lane")]
    edges[e.get("id")] = dict(frm=e.get("from"), to=e.get("to"), lanes=lanes)

junc = {j.get("id"): j.get("type") for j in root.findall("junction")}
cons = root.findall("connection")

print("=" * 78)
print("A. MAINLINE GEOMETRY")
tot = 0.0
for i in range(7):
    eid = f"ml_{i}"
    d = edges[eid]
    L = d["lanes"][0][1]
    tot += L
    print(f"  {eid:6s} {d['frm']:8s}->{d['to']:8s} lanes={len(d['lanes'])} "
          f"len={L:8.2f} v={d['lanes'][0][2]:.2f} junctype(to)={junc[d['to']]}")
print(f"  TOTAL mainline length = {tot:.1f} m ({tot/1000:.2f} km)")

print("\nB. LANE-DROP BOTTLENECK (ml_5 3-lane -> ml_6 2-lane) connection states")
for c in cons:
    if c.get("from") == "ml_5" and c.get("to") == "ml_6":
        print(f"    lane {c.get('fromLane')} -> {c.get('toLane')}  state={c.get('state')} dir={c.get('dir')}")

print("\nC. ON-RAMP MERGES (must show state 'Z' on BOTH mainline and ramp side of lane 0)")
merge_dn = {"r1": "ml_1", "r2": "ml_3", "r3": "ml_5"}
merge_up = {"r1": "ml_0", "r2": "ml_2", "r3": "ml_4"}
ok_merge = True
for r in ["r1", "r2", "r3"]:
    st = {}
    for c in cons:
        if c.get("to") == merge_dn[r] and c.get("toLane") == "0":
            st[(c.get("from"), c.get("fromLane"))] = c.get("state")
    ml_state = st.get((merge_up[r], "0"))
    rp_state = st.get((f"{r}_mrg", "0"))
    unc = [c.get("state") for c in cons
           if c.get("from") == merge_up[r] and c.get("to") == merge_dn[r] and c.get("toLane") == "2"]
    good = (ml_state == "Z" and rp_state == "Z")
    ok_merge &= good
    print(f"  {r}: node {merge_dn[r]}<-  mainline lane0 state={ml_state}  ramp state={rp_state}"
          f"  | uncontested lane2 state={unc}  -> {'ZIPPER OK' if good else 'FAIL'}")

print("\nD. RAMP STORAGE (terminal stop bar -> meter) and merge/accel lane lengths")
for r in ["r1", "r2", "r3"]:
    s = edges[f"{r}_stor"]["lanes"][0]
    m = edges[f"{r}_mrg"]["lanes"][0]
    print(f"  {r}: storage lane {s[0]} len={s[1]:7.2f} m v={s[2]:.2f}   "
          f"accel lane len={m[1]:7.2f} m v={m[2]:.2f}")

print("\nE. OFF-RAMP DIVERGES")
for o, up in [("o1", "ml_1"), ("o2", "ml_3")]:
    sts = [(c.get("from"), c.get("fromLane"), c.get("state"))
           for c in cons if c.get("to") == f"{o}_off"]
    print(f"  {o}: from {sts}  junction type={junc['m_'+o]}  len={edges[o+'_off']['lanes'][0][1]:.1f}")

print("\nF. FREEWAY / SURFACE SEPARATION (no direct connection mainline<->surface)")
surf = {e for e in edges if any(e.endswith(s) for s in ("_sapp", "_sout", "_capp", "_cout"))}
ml = {e for e in edges if e.startswith("ml_")}
bad = [(c.get("from"), c.get("to")) for c in cons
       if (c.get("from") in ml and c.get("to") in surf) or (c.get("from") in surf and c.get("to") in ml)]
print(f"  surface edges: {sorted(surf)}")
print(f"  direct mainline<->surface connections: {len(bad)}  -> {'OK' if not bad else 'FAIL '+str(bad)}")

print("\nG. TLS LINK INDEX MAPS")
tls_links = defaultdict(dict)
for c in cons:
    if c.get("tl"):
        tls_links[c.get("tl")][int(c.get("linkIndex"))] = (
            c.get("from"), c.get("fromLane"), c.get("to"), c.get("dir"), c.get("state"))
for tl in sorted(tls_links):
    print(f"  {tl} (junction type={junc.get(tl)}), {len(tls_links[tl])} controlled links:")
    for i in sorted(tls_links[tl]):
        f, fl, t, d, s = tls_links[tl][i]
        print(f"     idx {i}: {f}_{fl} -> {t}   dir={d} defaultstate={s}")

print("\nH. KEEP-CLEAR at ramp terminals")
kc = [(c.get("from"), c.get("to"), c.get("keepClear")) for c in cons
      if c.get("tl", "").endswith("_term")]
print(f"  terminal connections keepClear attr (absent => default true): {kc}")

print("\n" + "=" * 78)
print("MERGE VERIFICATION:", "PASS" if ok_merge else "FAIL")
