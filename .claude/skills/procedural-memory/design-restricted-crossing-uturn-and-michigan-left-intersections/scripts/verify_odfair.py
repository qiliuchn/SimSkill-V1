#!/usr/bin/env python3
"""
OD-fairness verification (task item 3).

For every (D, Q, m) cell and every variant:
  * the routed vehicle set must be IDENTICAL (same ids, same departure times,
    same OD pairs) -- only the EDGE SEQUENCES may differ
  * no OD pair may have lost any vehicle (duarouter ran with --ignore-errors,
    which would silently drop unroutable trips)
  * report the per-variant path signature (mean route length per OD pair) so the
    detour structure of each design is visible and auditable
"""
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from demand import od_counts, movement_class  # noqa: E402

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402


def _open_maybe_gz(p):
    """Open an XML file that may have been gzipped by prune_runs/archival."""
    import gzip as _gz, os as _os
    if not _os.path.exists(p) and _os.path.exists(p + ".gz"):
        return _gz.open(p + ".gz", "rb")
    if p.endswith(".gz"):
        return _gz.open(p, "rb")
    return open(p, "rb")




def read_routes(p):
    out = {}
    for _, v in ET.iterparse(_open_maybe_gz(p), events=("end",)):
        if v.tag != "vehicle":
            continue
        r = v.find("route")
        out[v.get("id")] = (v.get("fromTaz"), v.get("toTaz"), float(v.get("depart")),
                            r.get("edges").split())
        v.clear()
    return out


def read_trips(p):
    out = {}
    for _, v in ET.iterparse(_open_maybe_gz(p), events=("end",)):
        if v.tag != "trip":
            continue
        out[v.get("id")] = (v.get("fromTaz"), v.get("toTaz"), float(v.get("depart")))
        v.clear()
    return out


def main():
    rep = []
    rroot = os.path.join(ROOT, "routes")
    cells = defaultdict(dict)
    for name in sorted(os.listdir(rroot)):
        v, d, q, m = name.split("_")
        cells[(d, q, m)][v] = os.path.join(rroot, name, "rou.xml")
    for cell, byv in sorted(cells.items()):
        d, q, m = cell
        trips = os.path.join(ROOT, "demand", f"{q}_{m}", "trips.xml")
        T = read_trips(trips)
        exp = od_counts(float(q[1:]), int(m[1:]) / 100.0)
        entry = {"cell": f"{d}_{q}_{m}", "n_trips": len(T), "variants": {}}
        # expected per-OD counts from the matrix (integerised by od2trips)
        trip_od = defaultdict(int)
        for o, dd, _ in T.values():
            trip_od[(o, dd)] += 1
        entry["trip_od_counts"] = {f"{a}->{b}": c for (a, b), c in sorted(trip_od.items())}
        entry["matrix_od_counts"] = {f"{a}->{b}": round(c, 1) for (a, b), c in sorted(exp.items())}
        entry["matrix_vs_trips_max_abs_diff"] = max(
            abs(trip_od.get(k, 0) - v) for k, v in exp.items())
        net_cache = {}
        for v, rf in sorted(byv.items()):
            R = read_routes(rf)
            netf = os.path.join(ROOT, "nets", f"{v}_{d}", "net.net.xml")
            if netf not in net_cache:
                n = sumolib.net.readNet(netf)
                net_cache[netf] = {e.getID(): e.getLength() for e in n.getEdges()}
            EL = net_cache[netf]
            od = defaultdict(list)
            for vid, (o, dd, dep, edges) in R.items():
                od[(o, dd)].append(sum(EL[e] for e in edges))
            entry["variants"][v] = {
                "n_routed": len(R),
                "ids_match_trips": set(R) == set(T),
                "departures_match": all(abs(R[k][2] - T[k][2]) < 1e-6 for k in R) if set(R) == set(T) else False,
                "od_match": all(len(od[k]) == trip_od[k] for k in trip_od),
                "missing_od_pairs": [f"{a}->{b}" for (a, b) in trip_od if (a, b) not in od],
                "mean_path_len_m": {f"{a}->{b}({movement_class(a,b)})": round(sum(L) / len(L), 1)
                                    for (a, b), L in sorted(od.items())},
            }
        rep.append(entry)
    bad = [e for e in rep if not all(x["ids_match_trips"] and x["od_match"] and x["departures_match"]
                                     for x in e["variants"].values())]
    print(f"cells checked: {len(rep)}   cells with an OD-fairness defect: {len(bad)}")
    for e in bad:
        print("  DEFECT", e["cell"], {k: (v["n_routed"], v["missing_od_pairs"])
                                      for k, v in e["variants"].items()})
    with open(os.path.join(ROOT, "results", "odfair_report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    # show one cell's path-length signature
    e = [x for x in rep if x["cell"] == "D400_Q2400_m30"][0]
    print("\npath-length signature, cell D400_Q2400_m30 (m):")
    keys = sorted(e["variants"]["conv"]["mean_path_len_m"])
    print(f"  {'OD pair':38s} {'conv':>9s} {'rcut':>9s} {'mut':>9s}")
    for k in keys:
        print(f"  {k:38s} {e['variants']['conv']['mean_path_len_m'][k]:9.1f} "
              f"{e['variants']['rcut']['mean_path_len_m'][k]:9.1f} "
              f"{e['variants']['mut']['mean_path_len_m'][k]:9.1f}")


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    main()
