#!/usr/bin/env python3
"""
Mechanistic attribution: a null ablation result is only interpretable if we know how
much traffic actually EXPOSED itself to the defect. Counts, per fix class, how many of
the control arm's routed vehicles traverse the defective element.
"""
import os, sys, json, collections
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patchlib as P

OUT = os.environ.get("QA_DIR", os.getcwd())
spec = json.load(open(os.path.join(OUT, "repair_patch_spec.json")))
r, edges, junc, conns, tls = P.load_net(os.path.join(OUT, "base.net.xml"))

# ---- which edges belong to each defect ------------------------------------
# FIX-A : the 167 removed edges
A_edges = set(spec["A"]["remove_edges"])
# FIX-B : edges incident to the 5 under-joined nodes
B_nodes = set(spec["B"]["join_nodes"])
B_edges = {e for e, x in edges.items() if x.get("from") in B_nodes or x.get("to") in B_nodes}
# FIX-C : the Tremont approach
C_edges = {spec["C"]["edge"]}
# FIX-D : approaches controlled by the 4 no-conflict signals
D_tls = set(spec["D"]["unset_tls"])
D_edges = {c.get("from") for c in conns if c.get("tl") in D_tls}

GROUPS = {"A_connectivity": A_edges, "B_underjoined_junction": B_edges,
          "C_shared_left_lane": C_edges, "D_noconflict_signals": D_edges}
print("defect element sets:")
for k, v in GROUPS.items():
    print(f"  {k:<24} {len(v)} edges")
print()

SIMS = [("sim", "congested p=3.0", 15), ("sim_low", "light p=5.0", 10)]
report = {}
for simdir, lab, nseeds in SIMS:
    d = os.path.join(OUT, simdir)
    if not os.path.isdir(d):
        continue
    tot_veh = 0
    hits = collections.Counter()
    trav = collections.Counter()
    for seed in range(1, nseeds + 1):
        f = os.path.join(d, f"control_s{seed}.rou.xml")
        if not os.path.exists(f):
            continue
        for v in ET.parse(f).getroot().findall("vehicle"):
            tot_veh += 1
            e = set(v.find("route").get("edges").split())
            seq = v.find("route").get("edges").split()
            for g, s in GROUPS.items():
                if e & s:
                    hits[g] += 1
                trav[g] += sum(1 for x in seq if x in s)
    print(f"--- {lab}: {tot_veh} routed vehicles across {nseeds} seeds (control arm) ---")
    row = {}
    for g in GROUPS:
        pct = 100.0 * hits[g] / tot_veh if tot_veh else 0
        row[g] = dict(vehicles_touching=hits[g], pct=round(pct, 2),
                      edge_traversals=trav[g])
        print(f"  {g:<24} vehicles whose route touches it: {hits[g]:>6} ({pct:5.2f}%)"
              f"   edge traversals: {trav[g]}")
    report[simdir] = dict(total_vehicles=tot_veh, **row)
    print()

json.dump(dict(groups={k: sorted(v) for k, v in GROUPS.items()}, exposure=report),
          open(os.path.join(OUT, "defect_exposure.json"), "w"), indent=2)
print("-> defect_exposure.json")
