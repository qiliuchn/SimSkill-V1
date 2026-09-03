#!/usr/bin/env python3
"""
Build TAZs and the three-class OD matrix, run od2trips, and merge into one
identical-across-variants trips file.

OD classes (encoded in the vehicle-id prefix, so classification is exact):
  ee_  external-external THROUGH trips     -> the potential rat-runners
  bg_  external-external BACKGROUND trips between adjacent gateways (arterial load)
  ei_  external -> interior  (resident inbound)
  ie_  interior -> external  (resident outbound)
  ii_  interior -> interior  (local)

TAZ interior edges are restricted to directed edges that exist in EVERY variant
(i.e. the one-way-retained directions) and exclude the modal-filtered edges, so the
identical trips file is routable on all six networks.
"""
import os
import sys
import shutil
import subprocess
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.abspath(os.path.join(HERE, "..", "net"))
DEM = os.path.abspath(os.path.join(HERE, "..", "demand"))
os.makedirs(DEM, exist_ok=True)
BIN = os.path.dirname(shutil.which("od2trips") or os.path.join(os.environ["SUMO_HOME"], "bin"))
OD2TRIPS = os.path.join(BIN, "od2trips")

MID = 525.0
SEED = 20260802

sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
FILTERED = set(sets["FILTERED"])
KEPT = [e for e in sets["ONEWAY_KEPT"] if e not in FILTERED]

net = sumolib.net.readNet(os.path.join(NET, "A.net.xml"))


def quad(eid):
    e = net.getEdge(eid)
    (x0, y0), (x1, y1) = e.getFromNode().getCoord(), e.getToNode().getCoord()
    x, y = (x0 + x1) / 2, (y0 + y1) / 2
    return ("N" if y >= MID else "S") + ("E" if x >= MID else "W")


INT_ZONES = {"INT_SW": [], "INT_SE": [], "INT_NW": [], "INT_NE": []}
for eid in KEPT:
    INT_ZONES["INT_" + quad(eid)].append(eid)

EXT = ["S", "N", "W", "E", "SW", "SE", "NE", "NW"]

# ------------------------------------------------------------------- TAZ ----
taz = os.path.join(DEM, "zones.taz.xml")
with open(taz, "w") as f:
    f.write("<tazs>\n")
    for t in EXT:
        f.write('  <taz id="EXT_%s">\n' % t)
        f.write('    <tazSource id="EX%sI" weight="1.0"/>\n' % t)
        f.write('    <tazSink id="EX%sO" weight="1.0"/>\n' % t)
        f.write('  </taz>\n')
    for z, es in sorted(INT_ZONES.items()):
        f.write('  <taz id="%s">\n' % z)
        for e in sorted(es):
            f.write('    <tazSource id="%s" weight="1.0"/>\n' % e)
        for e in sorted(es):
            f.write('    <tazSink id="%s" weight="1.0"/>\n' % e)
        f.write('  </taz>\n')
    f.write("</tazs>\n")
print("TAZ zone sizes:", {z: len(e) for z, e in sorted(INT_ZONES.items())},
      "| 8 external zones")

# ---------------------------------------------------------------- matrices ----
THROUGH = [("EXT_S", "EXT_N"), ("EXT_N", "EXT_S"), ("EXT_W", "EXT_E"), ("EXT_E", "EXT_W"),
           ("EXT_SW", "EXT_NE"), ("EXT_NE", "EXT_SW"), ("EXT_SE", "EXT_NW"), ("EXT_NW", "EXT_SE")]
ADJ = [("EXT_S", "EXT_E"), ("EXT_E", "EXT_S"), ("EXT_E", "EXT_N"), ("EXT_N", "EXT_E"),
       ("EXT_N", "EXT_W"), ("EXT_W", "EXT_N"), ("EXT_W", "EXT_S"), ("EXT_S", "EXT_W")]
INTZ = sorted(INT_ZONES)

RATE_EE, RATE_BG, RATE_EI, RATE_IE, RATE_II = 290.0, 230.0, 23.0, 23.0, 29.0


def write_od(path, pairs_rate):
    with open(path, "w") as f:
        f.write("$OR;D2\n* From-Time  To-Time\n0.00 1.00\n* Factor\n1.00\n")
        for (a, b), r in pairs_rate:
            f.write("%s %s %.2f\n" % (a, b, r))


mats = {
    "ee": [(p, RATE_EE) for p in THROUGH],
    "bg": [(p, RATE_BG) for p in ADJ],
    "ei": [((e, z), RATE_EI) for e in ["EXT_" + t for t in EXT] for z in INTZ],
    "ie": [((z, e), RATE_IE) for e in ["EXT_" + t for t in EXT] for z in INTZ],
    "ii": [((a, b), RATE_II) for a in INTZ for b in INTZ],
}

trip_files = []
for k, pr in mats.items():
    od = os.path.join(DEM, "%s.od" % k)
    write_od(od, pr)
    out = os.path.join(DEM, "%s.trips.xml" % k)
    cmd = [OD2TRIPS, "-n", taz, "-d", od, "-o", out, "--prefix", k + "_",
           "--seed", str(SEED), "--departlane", "best", "--departspeed", "max",
           "--vtype", "car", "--no-step-log", "true"]
    if k == "ii":
        cmd.append("--different-source-sink")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("od2trips failed for " + k)
    n = len(ET.parse(out).getroot().findall("trip"))
    print("  %s: %4d trips (%d OD pairs)" % (k, n, len(pr)))
    trip_files.append(out)

# ------------------------------------------------------------------ merge ----
trips = []
for tf in trip_files:
    for t in ET.parse(tf).getroot().findall("trip"):
        trips.append((float(t.get("depart")), t))
trips.sort(key=lambda x: x[0])

VTYPES = (
    '  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"\n'
    '         decel="4.5" sigma="0.5" tau="1.0" maxSpeed="27.8" emissionClass="HBEFA3/PC_G_EU4"/>\n')
# NOTE: the SSM device is NOT enabled via vType params -- doing so makes SUMO write one
# ssm_<vehid>.xml per vehicle (4400 files).  It is enabled per-run on the sumo command
# line instead (--device.ssm.probability 1 --device.ssm.file <path>), which also keeps
# duarouter from path-mangling device.ssm.file (see analyze-intersection-safety-with-ssm).

merged = os.path.join(DEM, "all.trips.xml")
with open(merged, "w") as f:
    f.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">\n')
    f.write(VTYPES)
    for _, t in trips:
        f.write('  <trip id="%s" type="car" depart="%s" from="%s" to="%s" '
                'departLane="best" departSpeed="max"/>\n'
                % (t.get("id"), t.get("depart"), t.get("from"), t.get("to")))
    f.write("</routes>\n")

import collections
cnt = collections.Counter(t.get("id").split("_")[0] for _, t in trips)
print("MERGED %s : %d trips  %s" % (merged, len(trips), dict(cnt)))
