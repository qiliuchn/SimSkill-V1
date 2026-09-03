#!/usr/bin/env python3
"""
Step 1 verification: every candidate project must be a REAL mechanism change in
the COMPILED net.xml, not a silent no-op.

For each project P (alone, vs the do-nothing base) we diff the compiled
net.xml:
  * set of edge ids
  * lane count per edge
  * total lane-metres
  * tlLogic phase-state signature per junction  (a lane addition regenerates the
    signal program at the two endpoint junctions -- we quantify that here rather
    than discovering it later)
Writes outputs/project_verification.csv and .json
"""
import os, sys, json, csv
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import PROJECTS, PROJECT_IDS, NPROJ, build_net

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "verify")
OUT = os.path.join(ROOT, "outputs")
os.makedirs(WORK, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def net_signature(netfile):
    tree = ET.parse(netfile)
    root = tree.getroot()
    edges, lanem = {}, 0.0
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        edges[e.get("id")] = len(lanes)
        for ln in lanes:
            lanem += float(ln.get("length"))
    tls = {}
    for t in root.findall("tlLogic"):
        tls[t.get("id")] = "|".join(p.get("state") + ":" + p.get("duration")
                                    for p in t.findall("phase"))
    return dict(edges=edges, lane_metres=lanem, tls=tls)


def main():
    base_net = build_net(0, os.path.join(WORK, "base"))
    base = net_signature(base_net)
    rows = []
    for k, p in enumerate(PROJECTS):
        d = os.path.join(WORK, p["id"])
        nf = build_net(1 << k, d)
        s = net_signature(nf)
        new_edges = sorted(set(s["edges"]) - set(base["edges"]))
        changed_lanes = {e: (base["edges"][e], s["edges"][e])
                         for e in base["edges"]
                         if e in s["edges"] and base["edges"][e] != s["edges"][e]}
        tls_changed = sorted(j for j in base["tls"]
                             if j in s["tls"] and base["tls"][j] != s["tls"][j])
        tls_new = sorted(set(s["tls"]) - set(base["tls"]))
        rows.append(dict(
            project=p["id"], kind=p["kind"], cost=p["cost"], desc=p["desc"],
            n_new_edges=len(new_edges), new_edges=";".join(new_edges),
            n_edges_lane_changed=len(changed_lanes),
            lane_changes=";".join("%s:%d->%d" % (e, a, b)
                                  for e, (a, b) in sorted(changed_lanes.items())),
            base_lane_metres=round(base["lane_metres"], 1),
            new_lane_metres=round(s["lane_metres"], 1),
            delta_lane_metres=round(s["lane_metres"] - base["lane_metres"], 1),
            n_tls_programs_changed=len(tls_changed) + len(tls_new),
            tls_changed=";".join(tls_changed + tls_new),
            is_real_change=bool(new_edges or changed_lanes),
        ))
    with open(os.path.join(OUT, "project_verification.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "project_verification.json"), "w") as f:
        json.dump(dict(base_edges=len(base["edges"]),
                       base_lane_metres=round(base["lane_metres"], 1),
                       base_tls=len(base["tls"]), projects=rows), f, indent=2)
    for r in rows:
        print("%-3s %-8s cost=%5.1f  new_edges=%d  lane_chg=%d  d_lane_m=%+8.1f  tls_chg=%d  REAL=%s"
              % (r["project"], r["kind"], r["cost"], r["n_new_edges"],
                 r["n_edges_lane_changed"], r["delta_lane_metres"],
                 r["n_tls_programs_changed"], r["is_real_change"]))
    bad = [r["project"] for r in rows if not r["is_real_change"]]
    print("\nbase: %d edges, %.1f lane-metres, %d tlLogic programs"
          % (len(base["edges"]), base["lane_metres"], len(base["tls"])))
    print("NO-OP projects:", bad if bad else "none")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
