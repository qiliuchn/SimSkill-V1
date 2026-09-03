#!/usr/bin/env python3
"""Build the zone-to-zone skim probes:
  * intermodal PERSONS  (personTrip modes="public") for all 600 ordered zone pairs
    x 4 departure offsets that uniformly cover one base headway (600 s)
  * car PROBE VEHICLES for a random sample of zone pairs x 3 departure times,
    used to validate the duarouter car skim against tripinfo
Then routes the persons with duarouter (intermodal) and filters out the
walk-only fallbacks (= "no transit option", infinite PT impedance).
"""
import os
import sys
import json
import random
import subprocess
import xml.etree.ElementTree as ET

WORK, SCN = sys.argv[1], sys.argv[2]
NET = os.path.join(WORK, "%s.net.xml" % SCN)
Z = json.load(open(os.path.join(WORK, "zones.json")))
ZONES = sorted(Z["zones"])
CONN = {z: Z["zones"][z]["connector"] for z in ZONES}
DEP_OFFSETS = [900, 1050, 1200, 1350]
PROBE_DEPS = [900, 1500, 2100]
N_PROBE_PAIRS = 40

pairs = [(i, j) for i in ZONES for j in ZONES if i != j]

# ------------------------------------------------------------ persons
ptrips = os.path.join(WORK, "skim_persons_%s.trips.xml" % SCN)
with open(ptrips, "w") as f:
    f.write("<routes>\n")
    for t in DEP_OFFSETS:
        for i, j in pairs:
            f.write('    <person id="P#%s#%s#%d" depart="%d">\n'
                    '        <personTrip from="%s" to="%s" modes="public"/>\n'
                    '    </person>\n' % (i, j, t, t, CONN[i], CONN[j]))
    f.write("</routes>\n")

routed = os.path.join(WORK, "skim_persons_%s.rou.xml" % SCN)
cmd = ["duarouter", "-n", NET,
       "-a", os.path.join(WORK, "%s_busstops.add.xml" % SCN),
       "-r", "%s,%s" % (os.path.join(WORK, "%s_ptvehicles.rou.xml" % SCN), ptrips),
       "-o", routed, "--ignore-errors", "--seed", "42",
       "--persontrip.walkfactor", "0.9", "--write-costs",
       "--routing-threads", "4", "-b", "0", "-e", "9000"]
print("+", " ".join(cmd), flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stderr[-2000:])
if r.returncode != 0:
    raise SystemExit("duarouter (intermodal) failed")

# ------------------------------------------------------------ filter walk-only
tree = ET.parse(routed)
root = tree.getroot()
keep, walkonly, missing = [], [], []
found = set()
for p in list(root):
    if p.tag != "person":
        continue
    pid = p.get("id")
    found.add(pid)
    if any(c.tag == "ride" for c in p):
        keep.append(p)
    else:
        walkonly.append(pid)
        root.remove(p)
for i, j in pairs:
    for t in DEP_OFFSETS:
        pid = "P#%s#%s#%d" % (i, j, t)
        if pid not in found:
            missing.append(pid)
# strip the vType/route echo of PT vehicles duarouter copies into its output
for el in list(root):
    if el.tag in ("vehicle", "vType", "route"):
        root.remove(el)
tree.write(os.path.join(WORK, "skim_persons_%s.filtered.rou.xml" % SCN))
print("persons: requested=%d routed=%d with_ride=%d walkonly=%d unrouted=%d"
      % (len(pairs) * len(DEP_OFFSETS), len(found), len(keep), len(walkonly), len(missing)))

# ------------------------------------------------------------ car probes
rng = random.Random(7)
probe_pairs = rng.sample(pairs, N_PROBE_PAIRS)
ptr = os.path.join(WORK, "probe_cars_%s.trips.xml" % SCN)
with open(ptr, "w") as f:
    f.write("<routes>\n")
    for t in PROBE_DEPS:
        for i, j in probe_pairs:
            f.write('    <trip id="C#%s#%s#%d" depart="%d" from="%s" to="%s" '
                    'departLane="best" departSpeed="max"/>\n'
                    % (i, j, t, t, CONN[i], CONN[j]))
    f.write("</routes>\n")

json.dump(dict(walkonly=walkonly, unrouted=missing, probe_pairs=probe_pairs,
               dep_offsets=DEP_OFFSETS, probe_deps=PROBE_DEPS),
          open(os.path.join(WORK, "skim_meta_%s.json" % SCN), "w"), indent=1)
