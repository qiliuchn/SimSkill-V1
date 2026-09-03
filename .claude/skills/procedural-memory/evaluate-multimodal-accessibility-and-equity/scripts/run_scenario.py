#!/usr/bin/env python3
"""Simulation of record for one scenario and one seed:
equilibrium car routes + PT vehicles + intermodal skim persons (+ optional car
probes).  Emits tripinfo (with <personinfo>), summary and edgeData."""
import os
import sys
import subprocess

WORK, SCN, SEED = sys.argv[1], sys.argv[2], sys.argv[3]
PROBES = sys.argv[4] if len(sys.argv) > 4 else None
tag = "%s_s%s%s" % (SCN, SEED, "_probe" if PROBES else "")

ed = os.path.join(WORK, "ed_%s.add.xml" % tag)
with open(ed, "w") as f:
    f.write('<additional>\n    <edgeData id="ed" file="edgedata_%s.xml" begin="0" '
            'end="3600" excludeEmpty="false"/>\n</additional>\n' % tag)

routes = [os.path.join(WORK, "routes_%s.rou.xml" % ("base" if SCN == "altB" else SCN)),
          os.path.join(WORK, "%s_ptvehicles.rou.xml" % SCN),
          os.path.join(WORK, "skim_persons_%s.filtered.rou.xml" % SCN)]
if PROBES:
    routes.append(PROBES)

cmd = ["sumo", "-n", os.path.join(WORK, "%s.net.xml" % SCN),
       "-r", ",".join(routes),
       "-a", "%s,%s" % (os.path.join(WORK, "%s_busstops.add.xml" % SCN), ed),
       "--tripinfo-output", os.path.join(WORK, "tripinfo_%s.xml" % tag),
       "--summary-output", os.path.join(WORK, "summary_%s.xml" % tag),
       "--statistic-output", os.path.join(WORK, "stats_%s.xml" % tag),
       "--duration-log.statistics", "--no-step-log",
       "--time-to-teleport", "300", "--seed", SEED,
       "--begin", "0", "--end", "25000",
       "--pedestrian.striping.dawdling", "0.2",
       "--ignore-route-errors", "true"]
print("+", " ".join(cmd), flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
tailerr = "\n".join([l for l in r.stderr.splitlines()
                     if "Warning" not in l or "teleport" in l.lower()][-15:])
print(r.stdout[-1500:])
print(tailerr)
open(os.path.join(WORK, "sumo_%s.log" % tag), "w").write(r.stdout + "\n===\n" + r.stderr)
if r.returncode != 0:
    raise SystemExit("sumo failed for %s" % tag)
