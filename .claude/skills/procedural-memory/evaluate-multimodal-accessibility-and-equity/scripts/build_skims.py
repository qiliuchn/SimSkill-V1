#!/usr/bin/env python3
"""Build the zone-to-zone skims for one scenario.

CAR  : re-route centroid-to-centroid trips with duarouter against the CONGESTED
       edge travel times dumped by the simulation of record
       (--weight-files <edgedata> --weight-attribute traveltime --write-costs),
       and again with no weight file at all (free-flow reference).
PT   : realised door-to-door time from the <personinfo> of the intermodal skim
       persons in the simulation of record, averaged over 4 departure offsets that
       uniformly cover one base headway and over the 3 replication seeds; pairs
       whose duarouter plan contains no <ride> leg are INFINITE (no transit option).
"""
import os
import sys
import json
import subprocess
import statistics
import xml.etree.ElementTree as ET

WORK, SCN = sys.argv[1], sys.argv[2]
SEEDS = ["1", "2", "3"]
NET = os.path.join(WORK, "%s.net.xml" % SCN)
Z = json.load(open(os.path.join(WORK, "zones.json")))
ZONES = sorted(Z["zones"])
CONN = {z: Z["zones"][z]["connector"] for z in ZONES}
pairs = [(i, j) for i in ZONES for j in ZONES if i != j]
INF = float("inf")

# --------------------------------------------------- 1. seed-averaged edge weights
tt = {}
for s in SEEDS:
    root = ET.parse(os.path.join(WORK, "edgedata_%s_s%s.xml" % (SCN, s))).getroot()
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            v = e.get("traveltime")
            if v is not None:
                tt.setdefault(e.get("id"), []).append(float(v))
wfile = os.path.join(WORK, "weights_%s.xml" % SCN)
with open(wfile, "w") as f:
    f.write('<meandata>\n  <interval begin="0" end="3600" id="ed">\n')
    for eid, vs in sorted(tt.items()):
        f.write('    <edge id="%s" traveltime="%.4f"/>\n' % (eid, sum(vs) / len(vs)))
    f.write("  </interval>\n</meandata>\n")
print("weights: %d edges, seeds=%s" % (len(tt), SEEDS))

# --------------------------------------------------- 2. car skim trips
ctrips = os.path.join(WORK, "skimcar_%s.trips.xml" % SCN)
with open(ctrips, "w") as f:
    f.write("<routes>\n")
    for i, j in pairs:
        f.write('    <trip id="S#%s#%s" depart="900" from="%s" to="%s"/>\n'
                % (i, j, CONN[i], CONN[j]))
    f.write("</routes>\n")


def car_skim(tag, weights):
    out = os.path.join(WORK, "skimcar_%s_%s.rou.xml" % (SCN, tag))
    cmd = ["duarouter", "-n", NET, "-r", ctrips, "-o", out,
           "--write-costs", "--ignore-errors", "--seed", "42",
           "--routing-algorithm", "dijkstra", "-b", "0", "-e", "3600"]
    if weights:
        cmd += ["--weight-files", weights, "--weight-attribute", "traveltime",
                "--weights.expand"]
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2500:]); raise SystemExit("duarouter car skim failed")
    T, routes = {}, {}
    root = ET.parse(out).getroot()
    for v in root.findall("vehicle"):
        _, i, j = v.get("id").split("#")
        rt = v.find("route")
        T[(i, j)] = float(rt.get("cost"))
        routes[(i, j)] = rt.get("edges")
    for p in pairs:
        T.setdefault(p, INF)
    return T, routes


T_cong, R_cong = car_skim("cong", wfile)
T_ff, R_ff = car_skim("ff", None)
print("car skim: congested routed=%d/%d, free-flow routed=%d/%d"
      % (sum(1 for v in T_cong.values() if v < INF), len(pairs),
         sum(1 for v in T_ff.values() if v < INF), len(pairs)))

# --------------------------------------------------- 3. PT skim from personinfo
meta = json.load(open(os.path.join(WORK, "skim_meta_%s.json" % SCN)))
walkonly = set(meta["walkonly"])
samples, decomp = {}, {}
completed = 0
for s in SEEDS:
    for _, el in ET.iterparse(os.path.join(WORK, "tripinfo_%s_s%s.xml" % (SCN, s)),
                              events=("end",)):
        if el.tag != "personinfo":
            continue
        pid = el.get("id")
        if not pid.startswith("P#"):
            el.clear(); continue
        _, i, j, t = pid.split("#")
        legs = list(el)
        rides = [c for c in legs if c.tag == "ride"]
        if not rides:
            el.clear(); continue
        completed += 1
        dur = float(el.get("duration"))
        first_ride, last_ride = legs.index(rides[0]), legs.index(rides[-1])
        access = sum(float(c.get("duration")) for c in legs[:first_ride])
        egress = sum(float(c.get("duration")) for c in legs[last_ride + 1:])
        invehicle = sum(float(c.get("duration")) for c in rides)
        wait0 = float(rides[0].get("waitingTime"))
        xfer_wait = sum(float(c.get("waitingTime")) for c in rides[1:])
        xfer_walk = sum(float(c.get("duration")) for c in legs[first_ride + 1:last_ride]
                        if c.tag in ("walk", "access", "stop"))
        samples.setdefault((i, j), []).append(dur)
        d = decomp.setdefault((i, j), dict(access=[], wait=[], invehicle=[],
                                           transfer=[], egress=[], n_rides=[]))
        d["access"].append(access); d["wait"].append(wait0)
        d["invehicle"].append(invehicle)
        d["transfer"].append(xfer_wait + xfer_walk)
        d["egress"].append(egress); d["n_rides"].append(len(rides))

T_pt, PTD = {}, {}
for p in pairs:
    if p in samples:
        T_pt[p] = statistics.fmean(samples[p])
        PTD[p] = {k: statistics.fmean(v) for k, v in decomp[p].items()}
    else:
        T_pt[p] = INF
n_pt = sum(1 for v in T_pt.values() if v < INF)
print("PT skim: %d/%d pairs with a transit option (%d personinfo samples over %d seeds)"
      % (n_pt, len(pairs), completed, len(SEEDS)))

# --------------------------------------------------- 4. free-flow PT skim
#  = same intermodal plans but scheduled/free-flow: duarouter's own predicted cost.
#  (parsed from the routed person file's leg costs where available)

# --------------------------------------------------- 5. dump
def enc(d):
    return {"%s|%s" % k: (None if v == INF else v) for k, v in d.items()}


json.dump(dict(zones=ZONES,
               T_car_cong=enc(T_cong), T_car_ff=enc(T_ff), T_pt=enc(T_pt),
               pt_decomp={"%s|%s" % k: v for k, v in PTD.items()},
               pt_samples={"%s|%s" % k: len(v) for k, v in samples.items()},
               n_walkonly_person_records=len(walkonly),
               routes_cong={"%s|%s" % k: v for k, v in R_cong.items()}),
          open(os.path.join(WORK, "skims_%s.json" % SCN), "w"))
print("wrote skims_%s.json" % SCN)
