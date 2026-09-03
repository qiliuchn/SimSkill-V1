#!/usr/bin/env python3
"""
Independent re-derivation of every headline number, straight from the raw XML with a
SEPARATE parsing path (regex over the file text, not the shared plaza_lib parsers), so a
bug in plaza_lib cannot make a number agree with itself.
"""
import glob
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
R = os.path.join(EP, "attempts", "attempt-1", "runs")
OUT = os.path.join(EP, "outputs")

ST = re.compile(r'<stopinfo id="([^"]+)"[^>]*?lane="booth_(\d+)_0"[^>]*?started="([0-9.]+)" ended="([0-9.]+)"')
IN = re.compile(r'<instantOut id="([^"]+)" time="([0-9.]+)" state="enter" vehID="([^"]+)"')
E2 = re.compile(r'<interval begin="([0-9.]+)"[^>]*?id="(q_app_\d)"[^>]*?maxJamLengthInMeters="([0-9.]+)"')

res = {}

# ---------- 1. saturation run: service stats, move-up gap, booth capacity ----------
d = os.path.join(R, "mech_exp8")
stops = [(m[0], int(m[1]), float(m[2]), float(m[3])) for m in ST.findall(open(d + "/stops.xml").read())]
W0, W1 = 600.0, 1500.0
w = [s for s in stops if W0 <= s[2] <= W1]
dur = np.array([s[3] - s[2] for s in w])
res["1_service_mean_s"] = float(dur.mean())
res["1_service_CV"] = float(dur.std(ddof=1) / dur.mean())
res["1_n_services"] = len(dur)
gaps = []
for b in range(6):
    sb = sorted([s for s in w if s[1] == b], key=lambda z: z[2])
    gaps += [sb[k + 1][2] - sb[k][3] for k in range(len(sb) - 1)]
res["1_move_up_gap_mean_s"] = float(np.mean(gaps))
inst = IN.findall(open(d + "/instant.xml").read())
hh = []
for b in range(6):
    t = sorted(float(x[1]) for x in inst if x[0] == "dep_%d" % b and W0 <= float(x[1]) <= W1)
    hh += list(np.diff(t))
res["1_departure_headway_mean_s"] = float(np.mean(hh))
res["1_booth_capacity_vph"] = 3600.0 / np.mean(hh)
res["1_plaza_capacity_vph"] = 6 * 3600.0 / np.mean(hh)
res["1_textbook_plaza_capacity_vph"] = 6 * 3600.0 / 8.0
res["1_capacity_shortfall_pct"] = 100 * (1 - res["1_plaza_capacity_vph"] / res["1_textbook_plaza_capacity_vph"])
res["1_headway_CV2"] = float((np.std(hh, ddof=1) / np.mean(hh)) ** 2)

# ---------- 2. Wq at rho=0.80, both arms, re-derived per vehicle ----------
tff = json.load(open(os.path.join(OUT, "free_flow_tff.json")))
tff = {int(k): v for k, v in tff.items()}
for arm, pre in (("random", "rnd"), ("shortest_queue", "sq")):
    per_seed = []
    for seed in (101, 202, 303, 404, 505):
        d = os.path.join(R, "sweep", "%s_r080_s%d" % (pre, seed))
        ent = {}
        for det, t, v in IN.findall(open(d + "/instant.xml").read()):
            if det.startswith("ent_") and v not in ent:
                ent[v] = float(t)
        wq = []
        for vid, b, st, en in [(m[0], int(m[1]), float(m[2]), float(m[3]))
                               for m in ST.findall(open(d + "/stops.xml").read())]:
            if vid in ent and 900.0 <= ent[vid] <= 5400.0:
                wq.append(st - ent[vid] - tff[b])
        per_seed.append(np.mean(wq))
    res["2_Wq_rho080_%s_mean_s" % arm] = float(np.mean(per_seed))
    res["2_Wq_rho080_%s_per_seed" % arm] = [round(float(x), 3) for x in per_seed]

# ---------- 3. c=3 spillback run: served flow and mainline jam ----------
d = os.path.join(R, "design", "c3_s101")
inst = IN.findall(open(d + "/instant.xml").read())
n = sum(1 for det, t, v in inst if det.startswith("dep_") and 900.0 <= float(t) <= 5400.0)
res["3_c3_served_vph"] = n / 4500.0 * 3600.0
res["3_c3_capacity_vph"] = 3 * res["1_booth_capacity_vph"]
jam = [float(m[2]) for m in E2.findall(open(d + "/e2.xml").read())]
res["3_c3_max_mainline_jam_m"] = max(jam)

# ---------- 4. 100% ETC mixed vs open-road tolling ----------
for tag, key in (("mix_p100", "4_etc100_mixed"), ("ort", "4_open_road")):
    served, jams = [], []
    for seed in (101, 202, 303):
        d = os.path.join(R, "design", "%s_s%d" % (tag, seed))
        inst = IN.findall(open(d + "/instant.xml").read())
        served.append(sum(1 for det, t, v in inst
                          if det.startswith("dep_") and 900.0 <= float(t) <= 5400.0) / 4500.0 * 3600.0)
        jams.append(max([float(m[2]) for m in E2.findall(open(d + "/e2.xml").read())] + [0.0]))
    res[key + "_served_vph"] = float(np.mean(served))
    res[key + "_max_mainline_jam_m"] = float(np.mean(jams))

for k in sorted(res):
    print("%-42s %s" % (k, res[k] if not isinstance(res[k], float) else round(res[k], 4)))
json.dump(res, open(os.path.join(OUT, "crosscheck_independent.json"), "w"), indent=1)
