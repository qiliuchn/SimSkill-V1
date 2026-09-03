#!/usr/bin/env python3
"""Run duaIterate.py to (near-)equilibrium for a given scenario network and copy
the converged route file out.  PT vehicles are deliberately EXCLUDED from the
equilibration (they are a fixed 1-2% of the vehicle stream and are not
route-choosing agents); they are added back for the simulation of record."""
import os
import re
import sys
import glob
import gzip
import shutil
import subprocess
import json

SUMO_HOME = os.environ["SUMO_HOME"]
WORK, SCN, NET, LAST = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
d = os.path.join(WORK, "dua_%s" % SCN)
os.makedirs(d, exist_ok=True)

cmd = [sys.executable, os.path.join(SUMO_HOME, "tools", "assign", "duaIterate.py"),
       "-n", os.path.abspath(os.path.join(WORK, NET)),
       "-t", os.path.abspath(os.path.join(WORK, "peak.trips.xml")),
       "-l", str(LAST), "-e", "9000",
       "--convergence-iterations", "3", "--max-convergence-deviation", "0.01",
       "-A", "0.5", "-B", "0.9", "--clean-alt", "--no-gzip", "--weight-memory",
       "duarouter--seed", "42",
       "sumo--seed", "42", "sumo--duration-log.statistics"]
print("+", " ".join(cmd), flush=True)
r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
open(os.path.join(d, "duaIterate.log"), "w").write(r.stdout + "\n=== STDERR ===\n" + r.stderr)
if r.returncode != 0:
    print(r.stdout[-4000:]); print(r.stderr[-4000:])
    raise SystemExit("duaIterate failed for %s" % SCN)

# ---- convergence trace from each iteration's tripinfo
trace = []
for it in sorted(glob.glob(os.path.join(d, "[0-9][0-9][0-9]"))):
    k = int(os.path.basename(it))
    ti = os.path.join(it, "tripinfo_%03d.xml" % k)
    if not os.path.exists(ti):
        continue
    import xml.etree.ElementTree as ET
    dur, tl, n, dd = 0.0, 0.0, 0, 0.0
    for _, el in ET.iterparse(ti, events=("end",)):
        if el.tag == "tripinfo":
            dur += float(el.get("duration")); tl += float(el.get("timeLoss"))
            dd += float(el.get("departDelay")); n += 1
            el.clear()
    trace.append(dict(iteration=k, n=n, mean_duration=dur / n, mean_timeloss=tl / n,
                      mean_departdelay=dd / n, mean_total=(dur + dd) / n))
final = max(t["iteration"] for t in trace)
src = os.path.join(d, "%03d" % final, "peak_%03d.rou.xml" % final)
if not os.path.exists(src):
    cand = glob.glob(os.path.join(d, "%03d" % final, "*.rou.xml")) + \
           glob.glob(os.path.join(d, "%03d" % final, "*.rou.xml.gz"))
    src = [c for c in cand if "alt" not in os.path.basename(c)][0]
dst = os.path.join(WORK, "routes_%s.rou.xml" % SCN)
if src.endswith(".gz"):
    with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
else:
    shutil.copy(src, dst)
json.dump(trace, open(os.path.join(WORK, "dua_trace_%s.json" % SCN), "w"), indent=1)
print("scenario %s: %d iterations, final=%s" % (SCN, len(trace), final))
for t in trace:
    print("  it%02d n=%d meanDur=%.1f meanTotal=%.1f meanTimeLoss=%.1f"
          % (t["iteration"], t["n"], t["mean_duration"], t["mean_total"], t["mean_timeloss"]))
