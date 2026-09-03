#!/usr/bin/env python3
"""Drive the whole experiment: scenario build, ground truth, field-count export,
counts_to_demand reconstruction, round-trip reruns and the two corrections."""
import json
import os
import shutil
import subprocess
import sys

from common import SCEN, RUNS, OUT, NET, run

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CFG = os.path.join(SCEN, "corridor_config.json")


def sh(*args, **kw):
    print(">>", " ".join(str(a) for a in args))
    p = subprocess.run([str(a) for a in args], cwd=HERE, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-3000:]); print(p.stderr[-3000:])
        raise SystemExit("failed: " + " ".join(str(a) for a in args))
    print(p.stdout.strip()[-600:])
    return p


def sim(route, name, end=None):
    args = [PY, "run_sim.py", "--route", route, "--name", name]
    if end:
        args += ["--end", str(end)]
    sh(*args)


def c2d(tmc, atr, out, report, extra=()):
    sh(PY, "counts_to_demand.py", "--tmc", tmc, "--atr", atr, "--net", NET,
       "--config", CFG, "--out", out, "--report", report, *extra)


def main():
    skip_gt = "--skip-gt" in sys.argv
    if not skip_gt:
        # ---- 1. scenario
        sh(PY, "build_network.py")
        sh(PY, "demand.py")
        sh(PY, "build_detectors.py")
        sh(PY, "make_config.py")

    for arm in ("under", "over"):
        if not skip_gt:
            # ---- 2. ground truth
            sim(os.path.join(SCEN, "gt_%s.rou.xml" % arm), "gt_" + arm)
            # ---- 3. field count export
            sh(PY, "export_tmc.py", "--arm", arm)
        tmc = os.path.join(OUT, "tmc_counts_%s.csv" % arm)
        atr = os.path.join(OUT, "atr_profile_%s.csv" % arm)
        # ---- 4. baseline reconstruction (counts used directly as demand)
        c2d(tmc, atr, os.path.join(SCEN, "rec_%s.rou.xml" % arm),
            os.path.join(SCEN, "rec_%s_report.json" % arm))
        sim(os.path.join(SCEN, "rec_%s.rou.xml" % arm), "rec_" + arm)
        # ---- 5a. correction A: residual-queue accounting (E2 queue only)
        c2d(tmc, atr, os.path.join(SCEN, "recq_%s.rou.xml" % arm),
            os.path.join(SCEN, "recq_%s_report.json" % arm),
            extra=["--queue-correction",
                   os.path.join(RUNS, "gt_%s" % arm, "queue_bins.csv")])
        sim(os.path.join(SCEN, "recq_%s.rou.xml" % arm), "recq_" + arm)
        # ---- 5b. correction A': the SAME correction driven by the E2 residual
        # JAM length instead of approach storage (the naive queue metric)
        c2d(tmc, atr, os.path.join(SCEN, "recqj_%s.rou.xml" % arm),
            os.path.join(SCEN, "recqj_%s_report.json" % arm),
            extra=["--queue-correction",
                   os.path.join(RUNS, "gt_%s" % arm, "queue_bins.csv"),
                   "--queue-metric", "jam"])
        sim(os.path.join(SCEN, "recqj_%s.rou.xml" % arm), "recqj_" + arm)
    print("PIPELINE DONE")


if __name__ == "__main__":
    main()
