#!/usr/bin/env python3
"""How much is this ODME result actually pinned down by the counts?

Builds alternative OD matrices that reproduce the SAME link counts exactly, by
moving along the null space of the assignment matrix P (P n = 0 => P(x + n) = P x).
Each alternative is found by an LP that lands on a VERTEX of the feasible polytope
{x + N y : x + N y >= 0}, i.e. a maximally different flow-equivalent matrix -- a
single random null-space step hits the non-negativity boundary almost immediately
and badly understates how non-unique the answer is.

If the alternatives are far apart, the counts do not identify the matrix and the
ODME output must be reported as a flow-consistent adjustment, not as demand.

Optionally simulates each alternative (--net/--taz/--add) to prove the equivalence
survives real traffic dynamics rather than being a linear-algebra artefact.

Usage:
  python check_equifinality.py --p P.npz --matrix estimated.od --n-alt 6 \
      [--net grid.net.xml --taz districts.taz.xml --add detectors.add.xml \
       --observed edgedata.out.xml --begin 25200 --end 39600] \
      [--truth-matrix truth.od] [--out-dir alternatives/]
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odme_core import (read_od, write_od, read_counts_file, read_edgedata, route_matrix,
                       simulate, count_fit, od_recovery, rmsn)


def nullspace_basis(P, rcond=1e-10):
    _, sv, Vt = np.linalg.svd(P)
    return Vt[int((sv > sv.max() * rcond).sum()):].T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--p", required=True)
    ap.add_argument("--matrix", required=True, help="the ODME estimate to probe")
    ap.add_argument("--n-alt", type=int, default=6)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--truth-matrix", default=None)
    # optional simulation check
    ap.add_argument("--net"), ap.add_argument("--taz"), ap.add_argument("--add")
    ap.add_argument("--observed")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=86400)
    ap.add_argument("--sim-seed", default="777")
    ap.add_argument("--workdir", default="odme_work")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    z = np.load(a.p, allow_pickle=True)
    P, edges = z["P"], [str(e) for e in z["edges"]]
    pairs, x_ref, header = read_od(a.matrix)
    truth = read_od(a.truth_matrix)[1] if a.truth_matrix else None
    obs = read_counts_file(a.observed, edges)[1] if a.observed else None

    N = nullspace_basis(P)
    if N.shape[1] == 0:
        print("Null space is empty: these counts uniquely determine the matrix "
              "(rare - usually means far more counted links than OD pairs).")
        return
    rng = np.random.default_rng(a.seed)
    cands = {"estimate": x_ref}
    for j in range(a.n_alt):
        lp = linprog(c=-rng.normal(size=N.shape[1]), A_ub=-N, b_ub=x_ref,
                     bounds=[(-5000.0, 5000.0)] * N.shape[1], method="highs")
        if lp.success:
            cands["alt%d" % (j + 1)] = np.maximum(x_ref + N @ lp.x, 0.0)

    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)

    rows = []
    for name, x in cands.items():
        f_od = os.path.join(a.out_dir or a.workdir, "%s.od" % name)
        os.makedirs(os.path.dirname(f_od) or ".", exist_ok=True)
        write_od(f_od, pairs, x, header, "flow-equivalent alternative: %s" % name)
        d = np.abs(x - x_ref)
        row = dict(matrix=name, file=f_od, total_demand=round(float(x.sum()), 1),
                   vs_estimate_cell_rmsn_pct=round(rmsn(x, x_ref), 2),
                   vs_estimate_share_moved_pct=round(100.0 * d.sum() / (2 * x_ref.sum()), 1),
                   cells_differing_over_50pct=int((d > 0.5 * np.maximum(x_ref, 1e-9)).sum()))
        if obs is not None:
            row["assigned_fit"] = count_fit(P @ x, obs)
        if a.net and a.taz and a.add and obs is not None:
            _, rou = route_matrix(a.net, a.taz, f_od, "eq_" + name, a.workdir, seed=a.sim_seed)
            r = simulate(a.net, rou, a.add, a.workdir, "eq_" + name, a.begin, a.end, seed=a.sim_seed)
            sim = np.array([read_edgedata(os.path.join(r["dir"], "edgedata.out.xml")).get(e, 0.0)
                            for e in edges])
            row["simulated_fit"] = count_fit(sim, obs)
            row["teleports"] = r["teleports"]
        if truth is not None:
            row["od_recovery_vs_truth"] = od_recovery(pairs, x, truth)
        rows.append(row)

    summary = dict(nullspace_dim=int(N.shape[1]), n_od_pairs=int(P.shape[1]),
                   n_counted_links=int(P.shape[0]), rows=rows)
    if a.report:
        with open(a.report, "w") as f:
            json.dump(summary, f, indent=2)

    print("null space dimension %d of %d OD pairs (%d counted links)\n"
          % (N.shape[1], P.shape[1], P.shape[0]))
    head = "%-12s %10s %12s %10s" % ("matrix", "total", "vs est RMSN%", "% moved")
    if obs is not None:
        head += " %11s" % "assign RMSN%"
    if rows and "simulated_fit" in rows[0]:
        head += " %10s %10s" % ("sim RMSN%", "sim GEH<5%")
    if truth is not None:
        head += " %12s" % "OD RMSN%"
    print(head)
    for r in rows:
        line = "%-12s %10.0f %12.1f %10.1f" % (r["matrix"], r["total_demand"],
                                               r["vs_estimate_cell_rmsn_pct"],
                                               r["vs_estimate_share_moved_pct"])
        if obs is not None:
            line += " %11.2f" % r["assigned_fit"]["rmsn_pct"]
        if "simulated_fit" in r:
            line += " %10.2f %10.1f" % (r["simulated_fit"]["rmsn_pct"],
                                        r["simulated_fit"]["geh_lt5_pct"])
        if truth is not None:
            line += " %12.2f" % r["od_recovery_vs_truth"]["cell_rmsn_pct"]
        print(line)
    spread = max(r["vs_estimate_share_moved_pct"] for r in rows)
    print("\nUp to %.0f%% of all trips can be reallocated between OD pairs without "
          "changing the link counts at all." % spread)


if __name__ == "__main__":
    main()
