#!/usr/bin/env python3
"""
The connectivity defect's cost depends entirely on HOW demand is generated.

  * randomTrips.py's own source/sink samplers exclude no-successor edges as origins
    and no-predecessor edges as destinations, which (empirically) hid the defect
    completely -- 0 unroutable in 20,000 trips on the defective net.
  * An OD-matrix-style generator samples origin and destination INDEPENDENTLY from
    the edge set (this is what od2trips does from a zone/edge OD table). That is the
    workflow the defect actually bites.

This measures the independent-uniform-OD unroutable rate on base vs repaired,
weighting edges by lane-km (the usual "trips originate proportional to road supply"
assumption), 10 seeds x 2000 trips.
"""
import os, sys, random, subprocess, json
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patchlib as P

OUT = os.environ.get("QA_DIR", os.getcwd())
W = os.path.join(OUT, "od_routability")
os.makedirs(W, exist_ok=True)
N = 2000


def sample(net, seed, path):
    r, edges, junc, conns, tls = P.load_net(net)
    ids = sorted(edges)
    wts = [float(edges[e].findall("lane")[0].get("length")) * len(edges[e].findall("lane"))
           for e in ids]
    rnd = random.Random(seed)
    lines = []
    for i in range(N):
        o = rnd.choices(ids, wts)[0]
        d = rnd.choices(ids, wts)[0]
        while d == o:
            d = rnd.choices(ids, wts)[0]
        lines.append(f'  <trip id="t{i}" depart="{i*3600.0/N:.2f}" from="{o}" to="{d}"/>')
    open(path, "w").write("<routes>\n" + "\n".join(lines) + "\n</routes>\n")


res = {}
for arm in ["base", "repaired"]:
    net = os.path.join(OUT, arm + ".net.xml")
    tot_in = tot_out = 0
    per = []
    for seed in range(1, 11):
        tp = os.path.join(W, f"{arm}_s{seed}.trips.xml")
        sample(net, seed, tp)
        ro = os.path.join(W, f"{arm}_s{seed}.rou.xml")
        subprocess.run(["duarouter", "-n", net, "-r", tp, "-o", ro,
                        "--no-step-log", "true", "--ignore-errors"],
                       capture_output=True, text=True)
        a = len(ET.parse(tp).getroot().findall("trip"))
        b = len(ET.parse(ro).getroot().findall("vehicle")) if os.path.exists(ro) else 0
        tot_in += a; tot_out += b; per.append(a - b)
    res[arm] = dict(offered=tot_in, routed=tot_out, unroutable=tot_in - tot_out,
                    pct=round(100.0 * (tot_in - tot_out) / tot_in, 2), per_seed=per)
    print(f"{arm:<10} offered={tot_in} routed={tot_out} UNROUTABLE={tot_in-tot_out} "
          f"({res[arm]['pct']}%)  per-seed={per}")

json.dump(res, open(os.path.join(OUT, "od_routability.json"), "w"), indent=2)
print("-> od_routability.json")
