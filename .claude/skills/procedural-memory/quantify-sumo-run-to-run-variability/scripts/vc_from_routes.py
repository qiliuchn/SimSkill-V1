#!/usr/bin/env python3
"""Compute DEMAND-side v/c per interior edge directly from a duarouter route
file, and compare it to the ACHIEVED (served) v/c measured from edgeData.

Why both are needed
-------------------
edgeData measures the flow that was actually *served*. On a signalized network
that quantity is bounded above by capacity: once a link is oversaturated the
served flow stops rising and then falls as gridlock spreads, so achieved v/c can
never exceed ~1.0 and in deep congestion it goes back DOWN. Reading "v/c = 0.34"
off edgeData at an insertion rate of 5000 veh/h would be badly wrong as a
statement about loading.

The demand-side v/c is the flow that *wants* to use each link. Because routes
here are computed by duarouter on the empty network and are not re-routed during
the simulation, the route file is an exact record of offered demand: counting
route traversals per interior edge, restricted to vehicles departing in the
analysis window, gives demand flow with no simulation and no assumption.

Both numbers are reported: achieved v/c verifies what the network delivered,
demand v/c labels the loading level.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
GRID = re.compile(r"^[A-D][0-3]$")

WINDOW = (600.0, 3600.0)


def interior_edges(net):
    root = ET.parse(net).getroot()
    return set(e.get("id") for e in root.findall("edge")
               if e.get("function") != "internal"
               and GRID.match(e.get("from") or "")
               and GRID.match(e.get("to") or ""))


def demand_flows(route_file, interior, window=WINDOW):
    """veh/h of offered demand on each interior edge."""
    counts = {e: 0 for e in interior}
    dur = window[1] - window[0]
    for _, el in ET.iterparse(route_file, events=("end",)):
        if el.tag == "vehicle":
            dep = float(el.get("depart"))
            if window[0] <= dep <= window[1]:
                r = el.find("route")
                if r is not None:
                    for eid in r.get("edges").split():
                        if eid in counts:
                            counts[eid] += 1
            el.clear()
    return {e: n * 3600.0 / dur for e, n in counts.items()}


def _pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


if __name__ == "__main__":
    import json
    import glob
    sys.path.insert(0, HERE)
    import run_replications as R

    cap = json.load(open(os.path.join(HERE, "capacity.json")))["capacity_vph"]
    net = os.path.join(HERE, "grid4x4.net.xml")
    interior = interior_edges(net)
    work = os.path.join(os.path.dirname(HERE), "attempts", "attempt-1",
                        "work", "capacity_probe")

    print("capacity c = %.1f veh/h/edge" % cap)
    print("%-6s %-6s | demand v/c            | achieved v/c" % ("rate", "seed"))
    print("%-6s %-6s | %-7s %-7s %-7s | %-7s %-7s %-7s"
          % ("", "", "mean", "p90", "max", "mean", "p90", "max"))
    rows = []
    for d in sorted(glob.glob(os.path.join(work, "r*_s*"))):
        m = re.search(r"r(\d+)_s(\d+)$", d)
        rate, seed = int(m.group(1)), int(m.group(2))
        rf = glob.glob(os.path.join(d, "routes_*.rou.xml"))
        ed = os.path.join(d, "edgedata_window.xml")
        if not rf or not os.path.exists(ed):
            continue
        df = demand_flows(rf[0], interior)
        dv = [v / cap for v in df.values()]
        R.CAPACITY_VPH = cap
        av, _ = R.parse_edgedata_window(ed, interior)
        rows.append(dict(rate=rate, seed=seed,
                         d_mean=sum(dv) / len(dv), d_p90=_pct(dv, .9),
                         d_max=max(dv),
                         a_mean=sum(av) / len(av), a_p90=_pct(av, .9),
                         a_max=max(av)))
    rows.sort(key=lambda r: (r["rate"], r["seed"]))
    agg = {}
    for r in rows:
        print("%-6d %-6d | %-7.3f %-7.3f %-7.3f | %-7.3f %-7.3f %-7.3f"
              % (r["rate"], r["seed"], r["d_mean"], r["d_p90"], r["d_max"],
                 r["a_mean"], r["a_p90"], r["a_max"]))
        agg.setdefault(r["rate"], []).append(r)
    print("\n-- averaged over seeds --")
    print("%-6s | %-7s %-7s %-7s | %-7s %-7s %-7s"
          % ("rate", "d_mean", "d_p90", "d_max", "a_mean", "a_p90", "a_max"))
    out = []
    for rate in sorted(agg):
        rs = agg[rate]
        row = {"rate": rate}
        for k in ("d_mean", "d_p90", "d_max", "a_mean", "a_p90", "a_max"):
            row[k] = sum(r[k] for r in rs) / len(rs)
        out.append(row)
        print("%-6d | %-7.3f %-7.3f %-7.3f | %-7.3f %-7.3f %-7.3f"
              % (rate, row["d_mean"], row["d_p90"], row["d_max"],
                 row["a_mean"], row["a_p90"], row["a_max"]))
    with open(os.path.join(HERE, "vc_calibration.json"), "w") as fh:
        json.dump({"capacity_vph": cap, "per_rate": out, "per_run": rows}, fh,
                  indent=2)
    print("\nwrote vc_calibration.json")
