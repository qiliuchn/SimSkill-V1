#!/usr/bin/env python3
"""Goal 4: the over-injection trap. At the oversaturated (high) demand level,
compare what each child actually managed to insert at the cut face against
what the parent handed it, for both the micro-parent cut (best case) and the
meso-parent cut (realistic handoff), at buffer=0 and buffer=1 (smallest,
most exposed buffers).
"""
import os
import statistics
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.dirname(__file__))
from common import WD, read_tripinfo, count_teleports

SEEDS_CHILD = [42, 43, 44]
LEVEL = "high"


def injection_face_edges(cut_routes_path):
    root = ET.parse(cut_routes_path).getroot()
    entry = set()
    n_trunc = n_whole = 0
    for v in root.findall("vehicle"):
        route = v.find("route")
        eds = route.get("edges").split()
        if v.get("departSpeed") is not None:
            entry.add(eds[0])
            n_trunc += 1
        else:
            n_whole += 1
    return entry, n_trunc, n_whole


def scheduled_departs(cut_routes_path, entry_edges):
    root = ET.parse(cut_routes_path).getroot()
    out = []
    for v in root.findall("vehicle"):
        route = v.find("route")
        eds = route.get("edges").split()
        if eds[0] in entry_edges:
            out.append(float(v.get("depart")))
    return out


RESULTS = []


def main():
    for parent in ["micro", "meso"]:
        for buf in [0, 1, 2, 3]:
            name = "buf%d_%s_%s" % (buf, parent, LEVEL)
            cutdir = os.path.join(WD, "cuts", name)
            routes = os.path.join(cutdir, "rou_%s.rou.xml" % name)
            entry_edges, n_trunc, n_whole = injection_face_edges(routes)
            sched = scheduled_departs(routes, entry_edges)

            print("\n=== %s ===" % name)
            print("  injection-face edges (%d): %s" % (len(entry_edges), sorted(entry_edges)))
            print("  truncated (boundary-injected) vehicles: %d, entirely-interior: %d" % (n_trunc, n_whole))
            print("  scheduled insertion count at cut face: %d over the demand window" % len(sched))

            for s in SEEDS_CHILD:
                tag = "%s_seed%d" % (name, s)
                tripinfo_path = os.path.join(cutdir, "runs", "%s_tripinfo.xml" % tag)
                trips = read_tripinfo(tripinfo_path)
                trips_by_id = {t["id"]: t for t in trips}
                # match trips whose route's first edge is an entry edge -- reparse cut routes' vehicle->route map once
                pass

            # Load vehicle -> first-edge map once, use for all seeds' tripinfo (route identical across seeds)
            root = ET.parse(routes).getroot()
            veh_first_edge = {}
            for v in root.findall("vehicle"):
                eds = v.find("route").get("edges").split()
                veh_first_edge[v.get("id")] = eds[0]

            for s in SEEDS_CHILD:
                tag = "%s_seed%d" % (name, s)
                tripinfo_path = os.path.join(cutdir, "runs", "%s_tripinfo.xml" % tag)
                trips = read_tripinfo(tripinfo_path)
                entry_trips = [t for t in trips if veh_first_edge.get(t["id"]) in entry_edges]
                if not entry_trips:
                    print("  seed %d: no entry-edge trips found in tripinfo!" % s)
                    continue
                delays = [t["departDelay"] for t in entry_trips]
                backlog_vehs = sum(1 for d in delays if d > 1.0)
                stderr_log = os.path.join(cutdir, "runs", "%s_stderr.log" % tag)
                n_tel, tel_edges = count_teleports(stderr_log)
                tel_on_entry = sum(1 for e in tel_edges if e in entry_edges)
                print("  seed %-3d n_entry_veh=%-5d mean_departDelay=%6.2fs  max_departDelay=%7.2fs  "
                      "median=%5.2fs  vehicles_delayed>1s=%d (%.1f%%)  teleports_total=%d teleports_on_entry_edge=%d"
                      % (s, len(entry_trips), statistics.mean(delays), max(delays),
                         statistics.median(delays), backlog_vehs, 100.0 * backlog_vehs / len(entry_trips),
                         n_tel, tel_on_entry))
                RESULTS.append({
                    "parent": parent, "buffer": buf, "seed": s,
                    "n_entry": len(entry_trips), "mean_delay": statistics.mean(delays),
                    "pct_delayed": 100.0 * backlog_vehs / len(entry_trips),
                })

    import csv
    with open(os.path.join(WD, "analysis", "injection_trap.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(RESULTS[0].keys()))
        w.writeheader()
        w.writerows(RESULTS)
    print("\nwrote", os.path.join(WD, "analysis", "injection_trap.csv"))


if __name__ == "__main__":
    main()
