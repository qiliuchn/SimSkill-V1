#!/usr/bin/env python3
"""
Choose the route file of record for each variant, and quantify the DUE assignment
plateau.

The Wardrop equilibrium pins down route COSTS, not the route SPLIT, when many
parallel routes are near-cost-indifferent -- which is exactly the situation in a
permeable grid with a parallel boundary arterial.  Empirically the mean generalized
cost converges while cut-through veh-km keeps wandering over a wide band.  So:

  * primary metric  = MEAN +- SD of cut-through veh-km over a tail window of DUE
                      iterations (the equilibrium SET, not one point in it);
  * route file of record for the simulation stage = the tail iteration whose
    cut-through veh-km is closest to the tail MEDIAN (a pre-declared, reproducible
    rule -- not "whatever the last iteration happened to be").
"""
import gzip
import json
import os
import shutil
import statistics as st
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "runs", "analysis"))
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

VARIANTS = list("ABCDEF")
TAIL_FROM = int(sys.argv[1]) if len(sys.argv) > 1 else 10

sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
INTERIOR = set(sets["INTERIOR_STREETS"])
net = sumolib.net.readNet(os.path.join(NET, "A.net.xml"))
LEN = {e.getID(): e.getLength() for e in net.getEdges() if not e.getFunction()}

out = {}
for v in VARIANTS:
    d = os.path.join(RUNS, "due", v)
    its = sorted(int(x) for x in os.listdir(d) if x.isdigit())
    pts = []
    for it in its:
        p = os.path.join(d, "%03d" % it, "all_%03d.rou.xml.gz" % it)
        if not os.path.exists(p):
            continue
        km = ikm = 0.0
        for veh in ET.parse(gzip.open(p)).getroot().findall("vehicle"):
            es = veh.find("route").get("edges").split()
            x = sum(LEN.get(e, 0) for e in es if e in INTERIOR) / 1000.0
            ikm += x
            if veh.get("id").split("_")[0] in ("ee", "bg"):
                km += x
        pts.append((it, km, ikm))
    tail = [(i, k, t) for i, k, t in pts if i >= TAIL_FROM]
    ks = [k for _, k, _ in tail]
    med = st.median(ks)
    pick = min(tail, key=lambda r: abs(r[1] - med))
    src = os.path.join(d, "%03d" % pick[0], "all_%03d.rou.xml.gz" % pick[0])
    dst = os.path.join(RUNS, "routes_%s.rou.xml" % v)
    with gzip.open(src) as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    out[v] = dict(tail_from=TAIL_FROM, n_tail=len(tail),
                  cutthrough_vehkm_tail_mean=round(st.mean(ks), 1),
                  cutthrough_vehkm_tail_sd=round(st.pstdev(ks), 1),
                  cutthrough_vehkm_tail_median=round(med, 1),
                  cutthrough_vehkm_tail_min=round(min(ks), 1),
                  cutthrough_vehkm_tail_max=round(max(ks), 1),
                  cv_pct=round(100 * st.pstdev(ks) / st.mean(ks), 2),
                  selected_iteration=pick[0],
                  selected_cutthrough_vehkm=round(pick[1], 1),
                  selected_interior_vehkm_total=round(pick[2], 1),
                  full_trace=[dict(iter=i, cutthrough_vehkm=round(k, 1),
                                   interior_vehkm_total=round(t, 1)) for i, k, t in pts])
    print("%s tail[%d:] n=%d  mean=%.1f sd=%.1f (cv %.1f%%) range %.0f-%.0f | picked it%d = %.1f"
          % (v, TAIL_FROM, len(tail), out[v]["cutthrough_vehkm_tail_mean"],
             out[v]["cutthrough_vehkm_tail_sd"], out[v]["cv_pct"],
             out[v]["cutthrough_vehkm_tail_min"], out[v]["cutthrough_vehkm_tail_max"],
             pick[0], pick[1]))
json.dump(out, open(os.path.join(ANA, "equilibrium_selection.json"), "w"), indent=1)
