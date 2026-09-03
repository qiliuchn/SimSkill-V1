#!/usr/bin/env python3
"""Zone demographics (population / jobs / car ownership) + peak-hour gravity OD
matrix -> od2trips -> peak.trips.xml."""
import os
import sys
import json
import math
import subprocess
import csv

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

WORK = sys.argv[1]
Z = json.load(open(os.path.join(WORK, "zones.json")))
ZONES = sorted(Z["zones"])
NET = sumolib.net.readNet(os.path.join(WORK, "base.net.xml"))

# ------------------------------------------------- 1. demographics (stipulated)
LOW = ["OUTER_4", "OUTER_5", "OUTER_6", "OUTER_7"]
AFFLUENT = ["INNER_1", "INNER_2", "INNER_8"]


def demog(z):
    band = "CORE" if z == "CORE" else z.split("_")[0]
    sec = 0 if z == "CORE" else int(z.split("_")[1])
    if z == "CORE":
        return 4000, 40000, 0.45, "job core"
    if band == "INNER":
        if z in AFFLUENT:
            return 9000, 3000, 0.90, "affluent inner ring"
        return 8000, 2000, 0.72, "inner ring"
    if band == "MID":
        if sec in (4, 5, 6, 7):
            return 6000, 800, 0.55, "middle (west)"
        return 6000, 1200, 0.75, "middle (east)"
    if z in LOW:
        return 7000, 400, 0.35, "peripheral low-income"
    return 5000, 700, 0.70, "peripheral (east)"


DEM = {}
for z in ZONES:
    p, o, car, lab = demog(z)
    DEM[z] = dict(pop=p, jobs=o, car_ownership=car, label=lab,
                  low_income=z in LOW, affluent=z in AFFLUENT)

# ------------------------------------------------- 2. free-flow times (sumolib)
conn = {z: Z["zones"][z]["connector"] for z in ZONES}
ff = {}
for i in ZONES:
    for j in ZONES:
        if i == j:
            ff[(i, j)] = 3.0 * 60.0        # intrazonal: stipulated 3 min
            continue
        r = NET.getShortestPath(NET.getEdge(conn[i]), NET.getEdge(conn[j]))
        ff[(i, j)] = None
        if r[0] is not None:
            t = sum(e.getLength() / e.getSpeed() for e in r[0])
            ff[(i, j)] = t

unreach = [(i, j) for (i, j), v in ff.items() if v is None]
print("free-flow unreachable centroid pairs:", len(unreach), unreach[:10])

# ------------------------------------------------- 3. gravity OD  (peak hour)
BETA0 = 0.10 / 60.0       # 0.10 per minute -> per second, deterrence for demand
TOTAL_TRIPS = 6000.0      # peak-hour vehicle trips generated across the city

raw = {}
for i in ZONES:
    for j in ZONES:
        t = ff[(i, j)]
        if t is None:
            raw[(i, j)] = 0.0
            continue
        raw[(i, j)] = DEM[i]["pop"] * DEM[j]["jobs"] * math.exp(-BETA0 * t)
s = sum(raw.values())
OD = {k: v / s * TOTAL_TRIPS for k, v in raw.items()}

with open(os.path.join(WORK, "peak.od"), "w") as f:
    f.write("$OR;D2\n* From-Time  To-Time\n0.00 1.00\n* Factor\n1.00\n")
    for i in ZONES:
        for j in ZONES:
            if OD[(i, j)] > 0.005:
                f.write("%s %s %.4f\n" % (i, j, OD[(i, j)]))

cmd = ["od2trips", "-n", os.path.join(WORK, "taz.add.xml"),
       "-d", os.path.join(WORK, "peak.od"),
       "-o", os.path.join(WORK, "peak.trips.xml"),
       "--begin", "0", "--end", "3600", "--different-source-sink",
       "--departlane", "best", "--departspeed", "max",
       "--seed", "42", "--spread.uniform"]
print("+", " ".join(cmd), flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stderr[-1500:])
if r.returncode != 0:
    raise SystemExit("od2trips failed")

# shift od2trips departure times (7:00-8:00 -> 0-3600) if needed
import xml.etree.ElementTree as ET
tree = ET.parse(os.path.join(WORK, "peak.trips.xml"))
root = tree.getroot()
trips = root.findall("trip")
deps = [float(t.get("depart")) for t in trips]
print("od2trips: %d trips, depart range %.0f..%.0f" % (len(trips), min(deps), max(deps)))
print("sample ids:", [t.get("id") for t in trips[:4]])
if min(deps) >= 3600:
    off = 7 * 3600.0
    for t in trips:
        t.set("depart", "%.2f" % (float(t.get("depart")) - off))
    tree.write(os.path.join(WORK, "peak.trips.xml"))
    print("shifted departures by -%d s" % off)

# ------------------------------------------------- 4. write tables
with open(os.path.join(WORK, "zone_table.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["zone", "label", "population", "jobs", "car_ownership",
                "low_income", "n_edges", "lane_km", "centroid_connector",
                "r_m", "theta_deg", "trips_produced", "trips_attracted"])
    for z in ZONES:
        prod = sum(OD[(z, j)] for j in ZONES)
        attr = sum(OD[(i, z)] for i in ZONES)
        zi = Z["zones"][z]
        w.writerow([z, DEM[z]["label"], DEM[z]["pop"], DEM[z]["jobs"],
                    DEM[z]["car_ownership"], DEM[z]["low_income"], zi["n_edges"],
                    round(zi["lane_km"], 2), zi["connector"], round(zi["r"], 0),
                    round(zi["theta"], 1), round(prod, 1), round(attr, 1)])

json.dump(dict(demographics=DEM, od={"%s|%s" % k: v for k, v in OD.items()},
               freeflow_sumolib={"%s|%s" % k: v for k, v in ff.items()},
               total_pop=sum(d["pop"] for d in DEM.values()),
               total_jobs=sum(d["jobs"] for d in DEM.values()),
               beta0_demand_per_min=0.10, total_trips=TOTAL_TRIPS),
          open(os.path.join(WORK, "demand.json"), "w"), indent=1)
print("total pop %d, total jobs %d" % (sum(d["pop"] for d in DEM.values()),
                                       sum(d["jobs"] for d in DEM.values())))
