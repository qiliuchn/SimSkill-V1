#!/usr/bin/env python3
"""Convert the ground-truth E1 output into the two files dfrouter consumes:
   (1) a detector-definition XML (<detectors><detectorDefinition .../></detectors>)
   (2) a detector flow measure file (CSV, ';' separated):
       header  Detector;Time;qPKW;qLKW;vPKW;vLKW
       Time is in MINUTES; qPKW = car count in that minute; vPKW = km/h.
"""
import xml.etree.ElementTree as ET
from collections import defaultdict
import os

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/run"
E1 = os.path.join(RUN, "gt_e1.xml")

# detector geometry (id -> (lane, pos)) — must match the E1 additional file
DETS = [
    ("det_m0",   "m0_0",   400),
    ("det_m1",   "m1_0",   400),
    ("det_m2",   "m2_0",   400),
    ("det_m3",   "m3_0",   400),
    ("det_m4",   "m4_0",   400),
    ("det_on1",  "on1_0",  30),
    ("det_on2",  "on2_0",  30),
    ("det_off1", "off1_0", 150),
    ("det_off2", "off2_0", 150),
]

# ---- detector-definition file ----
with open(os.path.join(RUN, "detectors.det.xml"), "w") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<detectors>\n')
    for did, lane, pos in DETS:
        f.write(f'    <detectorDefinition id="{did}" lane="{lane}" pos="{pos}"/>\n')
    f.write('</detectors>\n')

# ---- measure file ----
tree = ET.parse(E1)
# per detector, per minute: count and mean speed (km/h)
rows = defaultdict(dict)  # did -> minute -> (count, speed_kmh)
for iv in tree.getroot().findall("interval"):
    did = iv.get("id")
    begin = float(iv.get("begin"))
    minute = int(round(begin / 60.0))
    n = int(iv.get("nVehContrib"))
    s = float(iv.get("speed"))  # m/s, -1 when empty
    v_kmh = s * 3.6 if s >= 0 else 100.0  # nominal free-flow when empty
    rows[did][minute] = (n, v_kmh)

minutes = sorted({m for d in rows for m in rows[d]})
with open(os.path.join(RUN, "flows.txt"), "w") as f:
    f.write("Detector;Time;qPKW;qLKW;vPKW;vLKW\n")
    for did, lane, pos in DETS:
        for m in minutes:
            n, v = rows[did].get(m, (0, 100.0))
            f.write(f"{did};{m};{n};0;{v:.1f};0\n")

# report totals
print("detector totals (measured, veh/h over the hour):")
for did, lane, pos in DETS:
    tot = sum(c for c, v in rows[did].values())
    print(f"  {did:10s} {tot}")
print("wrote detectors.det.xml and flows.txt to", RUN)
