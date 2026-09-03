#!/usr/bin/env python3
"""
Fix the convergence criterion for the inner loop, and benchmark evaluation cost.

(a) Cold start on the do-nothing net at the selected demand: run duaIterate for
    many iterations and record the relative gap and mean-travel-time
    stabilisation after EVERY iteration, so the stopping rule is chosen from
    data rather than assumed.
(b) Warm start: re-run a few project subsets starting from the converged
    do-nothing route file (duaIterate -r) with a short iteration budget, and
    compare the resulting TSTT against a full cold-start evaluation of the same
    subsets.  If they agree, the warm start is the affordable way to buy 1024
    equilibrium evaluations.
"""
import os, sys, json, glob, shutil, subprocess, time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import write_trips, build_net, mask_from_subset
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "conv")
OUT = os.path.join(ROOT, "outputs")
NVEH = 4000
TRIPS = os.path.join(ROOT, "work", "trips_main.xml")


def cold_trace():
    wd = os.path.join(WORK, "cold")
    os.makedirs(wd, exist_ok=True)
    net = build_net(0, wd)
    duadir = os.path.join(wd, "dua")
    shutil.rmtree(duadir, ignore_errors=True); os.makedirs(duadir)
    t0 = time.time()
    cmd = [sys.executable, EV.DUAITERATE, "-n", os.path.abspath(net),
           "-t", os.path.abspath(TRIPS), "-l", "25", "-e", str(int(EV.SIM_END)),
           "--convergence-iterations", "25", "--max-convergence-deviation", "0.0",
           "--time-to-teleport", str(int(EV.TIME_TO_TELEPORT)),
           "--disable-warnings", "--routing-algorithm", "astar"]
    r = subprocess.run(cmd, cwd=duadir, capture_output=True, text=True)
    wall = time.time() - t0
    steps = sorted(d for d in os.listdir(duadir)
                   if os.path.isdir(os.path.join(duadir, d)) and d.isdigit())
    rows = []
    for s in steps:
        alt = glob.glob(os.path.join(duadir, s, "*_%s.rou.alt.xml*" % s))
        ti = glob.glob(os.path.join(duadir, s, "tripinfo_%s.xml*" % s))
        rows.append(dict(step=int(s),
                         rel_gap=round(EV.rel_gap_from_alt(alt[0]), 5) if alt else None,
                         mean_dur=round(EV.mean_dur(ti[0]), 3) if ti else None))
    # keep the converged route file for warm starts
    last = steps[-1]
    rou = [p for p in glob.glob(os.path.join(duadir, last, "*_%s.rou.xml*" % last))
           if ".alt." not in p]
    shutil.copy(rou[0], os.path.join(ROOT, "work", "base_equilibrium.rou.xml"
                                     + (".gz" if rou[0].endswith(".gz") else "")))
    return dict(rows=rows, wall_s=round(wall, 1), n_steps=len(steps),
                rc=r.returncode, stderr=r.stderr[-500:])


def main():
    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(TRIPS):
        write_trips(NVEH, TRIPS)
    c = cold_trace()
    print("cold-start duaIterate, %d iterations, %.1f s wall (%.2f s/iteration)"
          % (c["n_steps"], c["wall_s"], c["wall_s"] / max(1, c["n_steps"])))
    print("%5s %10s %10s" % ("iter", "rel_gap", "mean_dur"))
    for r in c["rows"]:
        print("%5d %10s %10s" % (r["step"], r["rel_gap"], r["mean_dur"]))
    with open(os.path.join(OUT, "convergence_study.json"), "w") as f:
        json.dump(c, f, indent=2)


if __name__ == "__main__":
    main()
