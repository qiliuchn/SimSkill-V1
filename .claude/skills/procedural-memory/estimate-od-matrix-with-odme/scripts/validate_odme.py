#!/usr/bin/env python3
"""Close the ODME loop: feed the estimated matrix back through od2trips ->
duarouter -> sumo and check the *simulated* counts, not just the assigned ones.

Reports count fit in two measurement windows, which behave very differently:
  whole run   every trip is counted exactly once, so counts are invariant to
              congestion (congestion moves flow in time, not in space)
  peak window the realistic field-count window; under congestion the assignment
              model over-predicts what a detector actually records inside it,
              because queued flow spills past the end of the window

A fresh random seed (never used to build P, the observations, or the estimate) is
mandatory here -- reusing the estimation seed turns the check into a tautology.

Usage:
  python validate_odme.py --net grid.net.xml --taz districts.taz.xml \
      --matrix estimated.od --observed edgedata.out.xml --add detectors.add.xml \
      --begin 25200 --end 39600 --peak-begin 25200 --peak-end 28800 \
      --sim-seed 9001 [--truth-matrix truth.od] [--report validation.json]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odme_core import (read_od, read_counts_file, read_edgedata, read_e1, route_matrix,
                       simulate, counts_from_routes, count_fit, od_recovery, rmsn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--taz", required=True)
    ap.add_argument("--matrix", required=True, help="the estimated O-format matrix")
    ap.add_argument("--observed", required=True, help="observed counts (edgeData XML or CSV)")
    ap.add_argument("--p", help="P.npz -- defines the counted-link set (strongly recommended)")
    ap.add_argument("--counted-edges", help="alternative: file with one counted edge id per line")
    ap.add_argument("--add", required=True, help="detector/edgeData additional file")
    ap.add_argument("--edgedata-name", default="edgedata.out.xml")
    ap.add_argument("--peak-edgedata-name", default=None,
                    help="second edgeData output restricted to the count window")
    ap.add_argument("--observed-peak", default=None)
    ap.add_argument("--e1-name", default=None, help="E1 output file name, for a sensor cross-check")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=86400)
    ap.add_argument("--sim-seed", default="9001")
    ap.add_argument("--router-seed", default=None, help="defaults to --sim-seed")
    ap.add_argument("--random-factor", default="1.4")
    ap.add_argument("--workdir", default="odme_work")
    ap.add_argument("--truth-matrix", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--geh-threshold", type=float, default=85.0,
                    help="required %% of links with GEH<5")
    a = ap.parse_args()

    pairs, x, _ = read_od(a.matrix)
    # The counted-link set must be given explicitly. Defaulting to "every edge in
    # the edgeData file" silently pulls in the TAZ attach edges, where edgeData
    # `entered` is 0 for vehicles that DEPART on them -- the route file says those
    # edges carry the whole zone's demand, so the comparison looks catastrophically
    # broken for a reason that has nothing to do with the estimate.
    if a.p:
        edges = [str(e) for e in np.load(a.p, allow_pickle=True)["edges"]]
    elif a.counted_edges:
        edges = [l.strip() for l in open(a.counted_edges) if l.strip()]
    else:
        edges = None
        sys.stderr.write("WARNING: no --p/--counted-edges given; using every edge in the "
                         "observed file. TAZ source/sink edges will distort the result.\n")
    edges, obs = read_counts_file(a.observed, edges)
    _, rou = route_matrix(a.net, a.taz, a.matrix, "validate", a.workdir,
                          seed=a.router_seed or a.sim_seed, random_factor=a.random_factor)
    r = simulate(a.net, rou, a.add, a.workdir, "validate", a.begin, a.end, seed=a.sim_seed)

    sim = np.array([read_edgedata(os.path.join(r["dir"], a.edgedata_name)).get(e, 0.0)
                    for e in edges])
    assigned = counts_from_routes(rou, edges)

    out = dict(matrix=a.matrix, sim_seed=a.sim_seed,
               run=dict(inserted=r["inserted"], finished=r["finished"],
                        teleports=r["teleports"], collisions=r["collisions"],
                        mean_speed_mps=r["mean_speed"], time_loss_s=r["time_loss"],
                        depart_delay_s=r["depart_delay"]),
               total_demand=round(float(x.sum()), 1),
               simulated_vs_observed=count_fit(sim, obs),
               assigned_vs_observed=count_fit(assigned, obs),
               simulated_vs_own_assignment=count_fit(sim, assigned))

    if a.peak_edgedata_name and a.observed_peak:
        _, obs_p = read_counts_file(a.observed_peak, edges)
        sim_p = np.array([read_edgedata(os.path.join(r["dir"], a.peak_edgedata_name)).get(e, 0.0)
                          for e in edges])
        out["peak_window"] = dict(
            simulated_vs_observed=count_fit(sim_p, obs_p),
            assigned_vs_observed=count_fit(assigned, obs_p),
            flow_deficit_vs_whole_run_pct=round(100.0 * (sim_p.sum() - sim.sum()) / sim.sum(), 3))

    if a.e1_name:
        e1 = read_e1(os.path.join(r["dir"], a.e1_name))
        # detector ids are assumed to be "<prefix><edge>_<laneindex>"
        agg = np.array([sum(v for k, v in e1.items()
                            if k.rsplit("_", 1)[0] in (e, "e1_" + e, "det_" + e))
                        for e in edges])
        out["e1_vs_edgedata"] = count_fit(agg, sim)

    if a.truth_matrix:
        truth = read_od(a.truth_matrix)[1]
        out["od_recovery"] = od_recovery(pairs, x, truth)

    passed = out["simulated_vs_observed"]["geh_lt5_pct"] >= a.geh_threshold
    out["acceptance"] = dict(criterion="GEH<5 on >= %.0f%% of counted links" % a.geh_threshold,
                             achieved_pct=out["simulated_vs_observed"]["geh_lt5_pct"],
                             passed=bool(passed))

    if r["teleports"] > 0:
        out["warning_teleports"] = ("%d teleports: the network is congested enough that "
                                    "some vehicles were removed. Counts read with `entered` "
                                    "stay consistent with the routes; `left` would under-count."
                                    % r["teleports"])

    if a.report:
        with open(a.report, "w") as f:
            json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
