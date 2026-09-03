#!/usr/bin/env python3
"""Compare measured (ground-truth) vs realized (dfrouter-driven validation)
   per-detector counts using the GEH statistic. Also report off-ramp split fidelity."""
import xml.etree.ElementTree as ET
from collections import defaultdict
import math, os, json

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/run"

def totals(path):
    c = defaultdict(int)
    for iv in ET.parse(path).getroot().findall("interval"):
        c[iv.get("id")] += int(iv.get("nVehContrib"))
    return c

meas = totals(os.path.join(RUN, "gt_e1.xml"))
real = totals(os.path.join(RUN, "val_e1.xml"))

order = ["det_m0","det_m1","det_m2","det_m3","det_m4","det_on1","det_on2","det_off1","det_off2"]
cls = {"det_m0":"source","det_m1":"between","det_m2":"between","det_m3":"between",
       "det_m4":"sink","det_on1":"source","det_on2":"source","det_off1":"sink","det_off2":"sink"}

def geh(m, c):
    if m + c == 0: return 0.0
    return math.sqrt((m - c) ** 2 / ((m + c) / 2.0))

print(f"{'detector':10s} {'class':8s} {'measured':>8s} {'realized':>8s} {'diff':>5s} {'GEH':>6s} {'ok<5':>5s}")
rows = []; npass = 0
for d in order:
    m, r = meas[d], real[d]
    g = geh(m, r); ok = g < 5.0
    npass += ok
    rows.append({"detector": d, "class": cls[d], "measured": m, "realized": r,
                 "diff": r - m, "geh": round(g, 2), "pass": ok})
    print(f"{d:10s} {cls[d]:8s} {m:8d} {r:8d} {r-m:5d} {g:6.2f} {str(ok):>5s}")
print(f"\nGEH<5: {npass}/{len(order)} detectors ({100*npass/len(order):.0f}%)")

# aggregate GEH from summed volumes
sm = sum(meas[d] for d in order); sr = sum(real[d] for d in order)
print(f"aggregate GEH (summed): {geh(sm, sr):.2f}   (sum measured={sm}, sum realized={sr})")

# ---- off-ramp split fidelity ----
print("\n=== off-ramp diverge split fidelity (measured detector ratios) ===")
# n2 diverge: upstream m1 -> {off1, m2};  n4 diverge: upstream m3 -> {off2, m4}
for name, up, offd, downd in [("n2", "det_m1", "det_off1", "det_m2"),
                               ("n4", "det_m3", "det_off2", "det_m4")]:
    upc = meas[up]; offc = meas[offd]; downc = meas[downd]
    split = offc / upc if upc else 0
    consist = offc + downc  # should ~ upc
    print(f"  diverge {name}: upstream {up}={upc}, off {offd}={offc}, down {downd}={downc}")
    print(f"     measured off-ramp split = {offc}/{upc} = {split:.3f}  "
          f"| off+down = {consist} vs upstream {upc} (conservation gap {upc-consist})")

json.dump({"rows": rows, "pass": npass, "n": len(order),
           "agg_geh": round(geh(sm, sr), 2)},
          open(os.path.join(RUN, "geh_table.json"), "w"), indent=2)
print("\nwrote geh_table.json")
