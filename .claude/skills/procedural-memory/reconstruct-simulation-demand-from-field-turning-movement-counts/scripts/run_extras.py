#!/usr/bin/env python3
"""(1) the queue-corrected + trust-propagation variant, and
   (2) replications of both ground-truth arms at extra seeds, so every
       GT-vs-rerun difference can be read against a run-to-run noise floor."""
import json
import os
import subprocess
import sys

from common import SCEN, RUNS, OUT, NET

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CFG = os.path.join(SCEN, "corridor_config.json")
SEEDS = [43, 44, 45]


def sh(*a):
    p = subprocess.run([str(x) for x in a], cwd=HERE, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-2500:], p.stderr[-2500:])
        raise SystemExit("failed " + " ".join(str(x) for x in a))
    print("ok:", " ".join(str(x) for x in a[1:4]))


for arm in ("under", "over"):
    sh(PY, "counts_to_demand.py",
       "--tmc", os.path.join(OUT, "tmc_counts_%s.csv" % arm),
       "--atr", os.path.join(OUT, "atr_profile_%s.csv" % arm),
       "--net", NET, "--config", CFG,
       "--out", os.path.join(SCEN, "recqt_%s.rou.xml" % arm),
       "--report", os.path.join(SCEN, "recqt_%s_report.json" % arm),
       "--queue-correction", os.path.join(RUNS, "gt_%s" % arm, "queue_bins.csv"),
       "--queue-metric", "storage", "--trust-propagation")
    sh(PY, "run_sim.py", "--route", os.path.join(SCEN, "recqt_%s.rou.xml" % arm),
       "--name", "recqt_" + arm)

for arm in ("under", "over"):
    for s in SEEDS:
        sh(PY, "run_sim.py", "--route", os.path.join(SCEN, "gt_%s.rou.xml" % arm),
           "--name", "gtseed%d_%s" % (s, arm), "--seed", str(s))
    for s in SEEDS[:2]:
        sh(PY, "run_sim.py", "--route", os.path.join(SCEN, "rec_%s.rou.xml" % arm),
           "--name", "recseed%d_%s" % (s, arm), "--seed", str(s))
print("EXTRAS DONE")
