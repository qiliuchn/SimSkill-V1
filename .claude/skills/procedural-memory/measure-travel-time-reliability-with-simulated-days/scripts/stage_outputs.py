#!/usr/bin/env python3
"""Copy the small, self-contained deliverables into episodic-memory outputs/:
the scenario/network files, the scripts, and one FULL raw SUMO output set."""
import gzip
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "outputs"))

for sub in ("scenario_files", "scripts", "raw_example_A_base_day000",
            "raw_example_D_shoulder_day000"):
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)

# --- networks and their plain-XML sources
for f in sorted(os.listdir(os.path.join(WORK, "net"))):
    shutil.copy2(os.path.join(WORK, "net", f),
                 os.path.join(OUT, "scenario_files", f))

# --- an example demand file and an example incident file, regenerated so the
#     reader can see exactly what the generator emits
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import json                                  # noqa: E402
import sim_lib as S                          # noqa: E402

days = json.load(open(os.path.join(WORK, "days.json")))
inc = next(d for d in days if d["incident"] and d["inc_lanes"] == 2)
S.write_routes(os.path.join(OUT, "scenario_files",
                            "example_demand_mult1.00.rou.xml"), 1.0, 0.0)
S.write_additional(os.path.join(OUT, "scenario_files",
                                "example_incident_2lane.add.xml"), inc, 3)
json.dump(inc, open(os.path.join(OUT, "scenario_files",
                                 "example_incident_day.json"), "w"), indent=1)
shutil.copy2(os.path.join(WORK, "days.json"),
             os.path.join(OUT, "day_draws.json"))
shutil.copy2(os.path.join(WORK, "seedrep.json"),
             os.path.join(OUT, "variance_block_seedrep_design.json"))
shutil.copy2(os.path.join(WORK, "cells.csv"),
             os.path.join(OUT, "per_cell_compact_metrics.csv"))
shutil.copy2(os.path.join(WORK, "cells_extra.csv"),
             os.path.join(OUT, "per_cell_compact_metrics_extra_blocks.csv"))

# --- scripts
for f in ("build_network.py", "sim_lib.py", "run_matrix.py", "run_extra.py",
          "analyze.py", "verify.py", "stage_outputs.py", "digest.py"):
    shutil.copy2(os.path.join(ROOT, "scripts", f),
                 os.path.join(OUT, "scripts", f))

# --- one FULL raw SUMO output set per example scenario (gzipped where bulky)
for scen, dst in (("A_base", "raw_example_A_base_day000"),
                  ("D_shoulder", "raw_example_D_shoulder_day000")):
    src = os.path.join(WORK, "runs", "FULL", scen, "day000")
    for f in sorted(os.listdir(src)):
        sp = os.path.join(src, f)
        if not os.path.isfile(sp):
            continue
        if os.path.getsize(sp) > 400_000:
            with open(sp, "rb") as a, gzip.open(
                    os.path.join(OUT, dst, f + ".gz"), "wb") as b:
                shutil.copyfileobj(a, b)
        else:
            shutil.copy2(sp, os.path.join(OUT, dst, f))

tot = 0
for r, _, fs in os.walk(OUT):
    for f in fs:
        tot += os.path.getsize(os.path.join(r, f))
print(f"outputs/ staged: {tot/1e6:.1f} MB")
