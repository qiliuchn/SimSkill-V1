#!/usr/bin/env python3
"""Build the assignment-proportion matrix P for ODME.

P[l, k] = fraction of OD pair k's vehicles that traverse counted link l, so that
assigned link flow is v = P @ x.

Estimated by Monte Carlo: a uniform *reference* demand (equal trips on every OD
pair) is routed with exactly the router configuration the scenario's own
simulations use, and per-pair edge-usage frequencies are tabulated.  Trips carry
od2trips' `fromTaz`/`toTaz` attributes, which duarouter preserves -- that is what
makes the per-pair tabulation possible from a single router run.

Two things to know:
  * With duarouter on free-flow weights, route choice does not depend on the demand
    level, so P is a demand-independent linear operator and the ODME upper level is
    an exactly linear problem.  If you route with congested/iterated weights
    (duaIterate, marouter with capacity restraint), P becomes demand-dependent and
    you must re-derive it at the current solution -- use --outer-iterations.
  * --random-factor 1.0 makes duarouter deterministic, giving a binary P (each OD
    pair uses exactly one route).  That is a legitimate all-or-nothing assignment,
    but it makes the system far more degenerate.  Keep it above 1.

Usage:
  python build_assignment_matrix.py --net grid.net.xml --taz districts.taz.xml \
      --seed-matrix seed.od --out P.npz [--counted-edges edges.txt] \
      [--trips-per-pair 1000] [--random-factor 1.4]
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odme_core import read_od, write_od, route_matrix, sumo_bin


def internal_edges(net_file):
    """Every edge not touching a dead-end node (i.e. excluding TAZ attach edges)."""
    sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib
    net = sumolib.net.readNet(net_file)
    dead = {n.getID() for n in net.getNodes() if len(n.getNeighboringNodes()) == 1}
    return sorted(e.getID() for e in net.getEdges()
                  if e.getFromNode().getID() not in dead and e.getToNode().getID() not in dead)


def tabulate(rou_file, edges, pair_index):
    idx = {e: i for i, e in enumerate(edges)}
    hits = np.zeros((len(edges), len(pair_index)))
    n = np.zeros(len(pair_index))
    routes = defaultdict(set)
    for _, veh in ET.iterparse(rou_file, events=("end",)):
        if veh.tag != "vehicle":
            continue
        k = pair_index.get((veh.get("fromTaz"), veh.get("toTaz")))
        if k is not None:
            es = veh.find("route").get("edges").split()
            routes[k].add(tuple(es))
            n[k] += 1
            for e in es:
                if e in idx:
                    hits[idx[e], k] += 1
        veh.clear()
    return hits / np.maximum(n, 1), n, {k: len(v) for k, v in routes.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--taz", required=True)
    ap.add_argument("--seed-matrix", required=True, help="O-format matrix defining the OD pairs")
    ap.add_argument("--out", default="P.npz")
    ap.add_argument("--counted-edges", help="file with one edge id per line (default: all internal edges)")
    ap.add_argument("--trips-per-pair", type=int, default=1000)
    ap.add_argument("--random-factor", default="1.4")
    ap.add_argument("--router-seed", default="7")
    ap.add_argument("--workdir", default="odme_work")
    a = ap.parse_args()

    pairs, _, header = read_od(a.seed_matrix)
    pair_index = {p: i for i, p in enumerate(pairs)}
    edges = ([l.strip() for l in open(a.counted_edges) if l.strip()]
             if a.counted_edges else internal_edges(a.net))

    os.makedirs(a.workdir, exist_ok=True)
    ref = os.path.join(a.workdir, "reference_uniform.od")
    write_od(ref, pairs, np.full(len(pairs), a.trips_per_pair), header,
             "uniform reference demand for assignment-proportion estimation")
    _, rou = route_matrix(a.net, a.taz, ref, "reference", a.workdir,
                          seed=a.router_seed, random_factor=a.random_factor)
    P, n, div = tabulate(rou, edges, pair_index)

    lost = int((n < 0.9 * a.trips_per_pair).sum())
    if lost:
        sys.stderr.write("WARNING: %d OD pairs routed far fewer trips than requested "
                         "(unreachable zone pair?)\n" % lost)

    sv = np.linalg.svd(P, compute_uv=False)
    rank = int((sv > sv.max() * 1e-10).sum())
    meta = dict(edges=edges, pairs=["%s->%s" % p for p in pairs],
                n_links=len(edges), n_pairs=len(pairs), rank=rank,
                nullspace_dim=len(pairs) - rank,
                trips_per_pair=a.trips_per_pair, random_factor=a.random_factor,
                distinct_routes_mean=round(float(np.mean(list(div.values()))), 2),
                distinct_routes_max=int(max(div.values())),
                pairs_with_missing_trips=lost)
    np.savez(a.out, P=P, edges=np.array(edges),
             pairs=np.array(["%s->%s" % p for p in pairs]))
    with open(os.path.splitext(a.out)[0] + "_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print("P: %d counted links x %d OD pairs" % P.shape)
    print("rank(P) = %d  ->  null space dimension %d" % (rank, len(pairs) - rank))
    if rank < len(pairs):
        print("  !! the counts CANNOT determine %d of the %d degrees of freedom in the "
              "matrix; that part of the answer comes entirely from the seed."
              % (len(pairs) - rank, len(pairs)))
    print("distinct routes per OD pair: mean %.2f max %d"
          % (meta["distinct_routes_mean"], meta["distinct_routes_max"]))


if __name__ == "__main__":
    main()
