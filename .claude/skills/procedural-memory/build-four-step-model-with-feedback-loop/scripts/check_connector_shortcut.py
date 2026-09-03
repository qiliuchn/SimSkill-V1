"""Centroid-connector shortcut diagnostic.

Two independent checks that centroid connectors are not letting demand skip network
it should really have to traverse.  Run BOTH before trusting any zone system.

A) Skim-level (no simulation needed).  Recompute the free-flow zone-to-zone skim under
   two connector policies on the same network and zone geometry.  If the permissive
   policy is systematically cheaper, its connectors are creating shortcuts.

B) Realised-vs-skim ratio (needs one routed+simulated run).  Mean realised route
   length per OD pair divided by the distance skim.  A healthy zone system gives a
   ratio slightly ABOVE 1 (real routes are a bit longer than the idealised weighted
   skim).  Below 1 means vehicles are getting shorter trips than the zone geometry
   says they should.

Usage:
  python check_connector_shortcut.py -n net.net.xml -z zones.json            # check A
  python check_connector_shortcut.py -n net.net.xml -z zones.json \
      --routes demand.rou.xml --tripinfo tripinfo.xml                        # A + B
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import sumolib  # noqa: E402
from skim import EdgeGraph  # noqa: E402


def graph_for(net, meta, key):
    zones = meta["zones"]
    conn, w = {}, {}
    for z in zones:
        edges = meta["meta"][z][key]
        conn[z] = edges
        tot = sum(net.getEdge(e).getLength() * net.getEdge(e).getLaneNumber() for e in edges)
        w[z] = {e: net.getEdge(e).getLength() * net.getEdge(e).getLaneNumber() / tot
                for e in edges}
    return zones, EdgeGraph(net, conn, w, dict(w))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--net-file", required=True)
    ap.add_argument("-z", "--zones-json", required=True)
    ap.add_argument("--routes", help="routed .rou.xml carrying fromTaz/toTaz (for check B)")
    ap.add_argument("--tripinfo", help="tripinfo.xml of the same run (for check B)")
    ap.add_argument("--out-json")
    args = ap.parse_args()

    net = sumolib.net.readNet(args.net_file)
    meta = json.load(open(args.zones_json))
    out = {}
    S, D = {}, {}
    for label, key in (("restricted", "connectors"), ("permissive", "edges")):
        zones, G = graph_for(net, meta, key)
        S[label], D[label] = G.zone_skim(G.ff, aux=G.length)
        n = len(zones)
        off = ~np.eye(n, dtype=bool)
        out[label] = {
            "n_connectors": sum(len(G.connectors_by_zone[z]) for z in zones),
            "mean_interzonal_time_s": float(S[label][off].mean()),
            "mean_interzonal_dist_m": float(D[label][off].mean()),
        }
    n = S["restricted"].shape[0]
    off = ~np.eye(n, dtype=bool)
    dt = (S["permissive"] - S["restricted"])[off]
    out["shortcut"] = {
        "interzonal_time_change_pct": float(100 * dt.mean() / S["restricted"][off].mean()),
        "worst_pair_time_change_pct": float(100 * (dt / S["restricted"][off]).min()),
        "pairs_made_cheaper": int((dt < 0).sum()),
        "pairs_total": int(off.sum()),
    }

    if args.routes and args.tripinfo:
        zones = meta["zones"]
        zi = {z: i for i, z in enumerate(zones)}
        vt = {}
        for _, el in ET.iterparse(args.routes, events=("end",)):
            if el.tag == "vehicle":
                vt[el.get("id")] = (el.get("fromTaz"), el.get("toTaz"))
                el.clear()
        s_len = np.zeros((len(zones), len(zones)))
        s_cnt = np.zeros_like(s_len)
        for _, el in ET.iterparse(args.tripinfo, events=("end",)):
            if el.tag == "tripinfo":
                a, b = vt.get(el.get("id"), (None, None))
                if a in zi and b in zi:
                    s_len[zi[a], zi[b]] += float(el.get("routeLength"))
                    s_cnt[zi[a], zi[b]] += 1
                el.clear()
        realised = np.where(s_cnt > 0, s_len / np.maximum(s_cnt, 1), np.nan)
        ok = off & (s_cnt > 0) & np.isfinite(realised)
        ratio = float(np.nanmean(realised[ok] / D["restricted"][ok]))
        out["realised_over_skim_interzonal"] = ratio
        out["verdict_B"] = ("OK (realised routes longer than skim)" if ratio >= 1.0
                            else "SHORTCUT: realised routes SHORTER than the skim")

    print(json.dumps(out, indent=1))
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
