#!/usr/bin/env python3
"""Validate both skims against raw simulation output.

CAR: take the congested-skim route duarouter produced for a random sample of OD
     pairs, inject those exact routes as probe vehicles at 3 departure times into
     the simulation of record, and compare tripinfo duration with the skim value.
PT : compare duarouter's a-priori intermodal plan cost (sum of <walk>/<ride>
     cost attributes written by --write-costs) with the realised <personinfo>
     duration from the same simulation.
"""
import os
import sys
import json
import csv
import statistics
import subprocess
import xml.etree.ElementTree as ET

WORK, SCN = sys.argv[1], sys.argv[2]
SK = json.load(open(os.path.join(WORK, "skims_%s.json" % SCN)))
META = json.load(open(os.path.join(WORK, "skim_meta_%s.json" % SCN)))
PROBE_DEPS = META["probe_deps"]
probe_pairs = [tuple(p) for p in META["probe_pairs"]]

# ------------------------------------------------------------------ car probes
routes = SK["routes_cong"]
pf = os.path.join(WORK, "proberoutes_%s.rou.xml" % SCN)
with open(pf, "w") as f:
    f.write("<routes>\n")
    for t in PROBE_DEPS:
        for i, j in probe_pairs:
            k = "%s|%s" % (i, j)
            if k not in routes:
                continue
            f.write('    <vehicle id="C#%s#%s#%d" depart="%d" departLane="best" '
                    'departSpeed="max">\n        <route edges="%s"/>\n    </vehicle>\n'
                    % (i, j, t, t, routes[k]))
    f.write("</routes>\n")

subprocess.run([sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_scenario.py"),
                WORK, SCN, "1", pf], check=True,
               stdout=subprocess.DEVNULL)

ti = os.path.join(WORK, "tripinfo_%s_s1_probe.xml" % SCN)
obs = {}
for _, el in ET.iterparse(ti, events=("end",)):
    if el.tag == "tripinfo" and el.get("id", "").startswith("C#"):
        _, i, j, t = el.get("id").split("#")
        obs.setdefault((i, j), []).append(float(el.get("duration")) +
                                          float(el.get("departDelay")))
    if el.tag in ("tripinfo", "personinfo"):
        el.clear()

rows, errs = [], []
for i, j in probe_pairs:
    if (i, j) not in obs:
        continue
    skim = SK["T_car_cong"]["%s|%s" % (i, j)]
    o = statistics.fmean(obs[(i, j)])
    rows.append(dict(origin=i, dest=j, skim_s=round(skim, 1), sim_mean_s=round(o, 1),
                     n=len(obs[(i, j)]),
                     sim_min_s=round(min(obs[(i, j)]), 1),
                     sim_max_s=round(max(obs[(i, j)]), 1),
                     abs_err_s=round(o - skim, 1),
                     pct_err=round(100.0 * (o - skim) / skim, 2)))
    errs.append(100.0 * (o - skim) / skim)

# ------------------------------------------------------------------ PT check
dua = {}
root = ET.parse(os.path.join(WORK, "skim_persons_%s.rou.xml" % SCN)).getroot()
for p in root:
    if p.tag != "person":
        continue
    legs = list(p)
    if not any(c.tag == "ride" for c in legs):
        continue
    c = sum(float(x.get("cost", 0)) for x in legs)
    _, i, j, t = p.get("id").split("#")
    dua.setdefault((i, j), []).append(c)
pt_rows, pt_err = [], []
for k, v in SK["T_pt"].items():
    if v is None:
        continue
    i, j = k.split("|")
    if (i, j) not in dua:
        continue
    d = statistics.fmean(dua[(i, j)])
    pt_rows.append(dict(origin=i, dest=j, dua_pred_s=round(d, 1),
                        sim_mean_s=round(v, 1), abs_err_s=round(v - d, 1),
                        pct_err=round(100.0 * (v - d) / d, 2)))
    pt_err.append(100.0 * (v - d) / d)


def summ(x):
    a = sorted(abs(v) for v in x)
    return dict(n=len(x), mean_signed_pct=round(statistics.fmean(x), 2),
                mean_abs_pct=round(statistics.fmean(a), 2),
                median_abs_pct=round(statistics.median(a), 2),
                p90_abs_pct=round(a[int(0.9 * (len(a) - 1))], 2),
                max_abs_pct=round(a[-1], 2),
                within_10pct=round(100.0 * sum(1 for v in a if v <= 10) / len(a), 1),
                within_20pct=round(100.0 * sum(1 for v in a if v <= 20) / len(a), 1))


out = dict(scenario=SCN, car=summ(errs), pt=summ(pt_err))
print(json.dumps(out, indent=1))
json.dump(dict(summary=out, car_rows=rows, pt_rows=pt_rows),
          open(os.path.join(WORK, "verify_%s.json" % SCN), "w"), indent=1)
with open(os.path.join(WORK, "verify_car_%s.csv" % SCN), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
with open(os.path.join(WORK, "verify_pt_%s.csv" % SCN), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(pt_rows[0].keys())); w.writeheader(); w.writerows(pt_rows)
