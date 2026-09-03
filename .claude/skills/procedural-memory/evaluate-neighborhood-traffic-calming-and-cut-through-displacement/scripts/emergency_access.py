#!/usr/bin/env python3
"""
Step 7 -- the ACCESS COST of a modal filter.

Shortest-path response distance / time from an external depot to every interior
address, for an EMERGENCY vClass (permitted through the filter) versus an ordinary
PASSENGER car, on every variant.  Routed with duarouter (SUMO's own router, so
vClass permissions and turn prohibitions are honoured exactly), under both
free-flow weights and the variant's own DUE-equilibrium edge travel times.
"""
import collections
import csv
import glob
import gzip
import json
import os
import shutil
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "runs", "analysis"))
WORK = os.path.join(RUNS, "access")
os.makedirs(WORK, exist_ok=True)
DUAROUTER = shutil.which("duarouter") or os.path.join(os.environ["SUMO_HOME"], "bin", "duarouter")

VARIANTS = list("ABCDEF")
DEPOT = "EXSWI"        # external depot: the SW gateway inbound stub

sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
DEST = [e for e in sets["ONEWAY_KEPT"] if e not in set(sets["FILTERED"])]

VTYPES = """<routes>
  <vType id="car" vClass="passenger" maxSpeed="27.8"/>
  <vType id="ems" vClass="emergency" maxSpeed="27.8"/>
"""


def trips_file(path, vtype, prefix):
    with open(path, "w") as f:
        f.write(VTYPES)
        for k, d in enumerate(DEST):
            f.write('  <trip id="%s%d" type="%s" depart="0" from="%s" to="%s"/>\n'
                    % (prefix, k, vtype, DEPOT, d))
        f.write("</routes>\n")


def eq_weights(v):
    """final DUE iteration edgeData dump for variant v (peak-hour interval)"""
    cands = sorted(glob.glob(os.path.join(RUNS, "due", v, "*", "dump_900.xml.gz")))
    if not cands:
        return {}
    root = ET.parse(gzip.open(cands[-1])).getroot()
    num, den = collections.Counter(), collections.Counter()
    for iv in root.findall("interval"):
        if float(iv.get("begin")) >= 3600:
            continue
        for e in iv.findall("edge"):
            if e.get("traveltime") is None or e.get("sampledSeconds") is None:
                continue
            w = float(e.get("sampledSeconds"))
            num[e.get("id")] += float(e.get("traveltime")) * w
            den[e.get("id")] += w
    return {k: num[k] / den[k] for k in num if den[k] > 0}


def main():
    rows = []
    for v in VARIANTS:
        netf = os.path.join(NET, "%s.net.xml" % v)
        net = sumolib.net.readNet(netf)
        ff = {e.getID(): e.getLength() / e.getSpeed()
              for e in net.getEdges() if not e.getFunction()}
        ln = {e.getID(): e.getLength() for e in net.getEdges() if not e.getFunction()}
        eqw = eq_weights(v)
        for mode, vtype in (("passenger", "car"), ("emergency", "ems")):
            tf = os.path.join(WORK, "%s_%s.trips.xml" % (v, mode))
            of = os.path.join(WORK, "%s_%s.rou.xml" % (v, mode))
            trips_file(tf, vtype, "%s%s" % (v, mode[0]))
            r = subprocess.run([DUAROUTER, "-n", netf, "-r", tf, "-o", of,
                                "--no-step-log", "--ignore-errors"],
                               capture_output=True, text=True)
            routed = {}
            if os.path.exists(of):
                for veh in ET.parse(of).getroot().findall("vehicle"):
                    routed[veh.get("id")] = veh.find("route").get("edges").split()
            for k, d in enumerate(DEST):
                vid = "%s%s%d" % (v, mode[0], k)
                if vid not in routed:
                    rows.append(dict(variant=v, mode=mode, dest=d, ok=0,
                                     dist_m="", ff_s="", eq_s=""))
                    continue
                es = routed[vid]
                rows.append(dict(variant=v, mode=mode, dest=d, ok=1,
                                 dist_m=round(sum(ln[e] for e in es), 1),
                                 ff_s=round(sum(ff[e] for e in es), 1),
                                 eq_s=round(sum(eqw.get(e, ff[e]) for e in es), 1)))
            print("%s %-10s routed %d/%d" % (v, mode, len(routed), len(DEST)))

    with open(os.path.join(ANA, "emergency_access_raw.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "mode", "dest", "ok", "dist_m", "ff_s", "eq_s"])
        w.writeheader()
        w.writerows(rows)

    summ = {}
    for v in VARIANTS:
        summ[v] = {}
        for mode in ("passenger", "emergency"):
            rs = [r for r in rows if r["variant"] == v and r["mode"] == mode and r["ok"]]
            summ[v][mode] = dict(
                n=len(rs),
                mean_dist_m=round(st.mean([r["dist_m"] for r in rs]), 1),
                mean_ff_s=round(st.mean([r["ff_s"] for r in rs]), 1),
                p95_ff_s=round(sorted(r["ff_s"] for r in rs)[int(0.95 * len(rs))], 1),
                max_ff_s=round(max(r["ff_s"] for r in rs), 1),
                mean_eq_s=round(st.mean([r["eq_s"] for r in rs]), 1),
                max_eq_s=round(max(r["eq_s"] for r in rs), 1))
        # paired penalty passenger-vs-emergency on the same destinations
        pp = {r["dest"]: r for r in rows if r["variant"] == v and r["mode"] == "passenger" and r["ok"]}
        ee = {r["dest"]: r for r in rows if r["variant"] == v and r["mode"] == "emergency" and r["ok"]}
        com = sorted(set(pp) & set(ee))
        summ[v]["paired_car_minus_ems"] = dict(
            n=len(com),
            mean_dist_m=round(st.mean([pp[d]["dist_m"] - ee[d]["dist_m"] for d in com]), 1),
            mean_ff_s=round(st.mean([pp[d]["ff_s"] - ee[d]["ff_s"] for d in com]), 2),
            max_ff_s=round(max(pp[d]["ff_s"] - ee[d]["ff_s"] for d in com), 2),
            n_dest_worse=sum(1 for d in com if pp[d]["ff_s"] - ee[d]["ff_s"] > 0.5))
    # penalty of each variant vs baseline A, per mode
    for v in VARIANTS:
        for mode in ("passenger", "emergency"):
            base = {r["dest"]: r for r in rows if r["variant"] == "A" and r["mode"] == mode and r["ok"]}
            cur = {r["dest"]: r for r in rows if r["variant"] == v and r["mode"] == mode and r["ok"]}
            com = sorted(set(base) & set(cur))
            summ[v]["%s_vs_A" % mode] = dict(
                mean_dist_delta_m=round(st.mean([cur[d]["dist_m"] - base[d]["dist_m"] for d in com]), 1),
                mean_ff_delta_s=round(st.mean([cur[d]["ff_s"] - base[d]["ff_s"] for d in com]), 2),
                max_ff_delta_s=round(max(cur[d]["ff_s"] - base[d]["ff_s"] for d in com), 2),
                mean_eq_delta_s=round(st.mean([cur[d]["eq_s"] - base[d]["eq_s"] for d in com]), 2))
    json.dump(summ, open(os.path.join(ANA, "emergency_access.json"), "w"), indent=1)
    for v in VARIANTS:
        s = summ[v]
        print("%s  car ff=%.1fs dist=%.0fm | ems ff=%.1fs dist=%.0fm | car-ems=%+.2fs "
              "| car vs A %+.2fs, ems vs A %+.2fs"
              % (v, s["passenger"]["mean_ff_s"], s["passenger"]["mean_dist_m"],
                 s["emergency"]["mean_ff_s"], s["emergency"]["mean_dist_m"],
                 s["paired_car_minus_ems"]["mean_ff_s"],
                 s["passenger_vs_A"]["mean_ff_delta_s"], s["emergency_vs_A"]["mean_ff_delta_s"]))


if __name__ == "__main__":
    main()
