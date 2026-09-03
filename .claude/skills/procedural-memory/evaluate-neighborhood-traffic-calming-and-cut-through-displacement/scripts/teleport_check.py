#!/usr/bin/env python3
"""
Teleport-artifact validation (per `validate-congested-scenario-results-against-
teleport-artifacts`): sweep --time-to-teleport as a treatment variable on the baseline
and on the intervention variants, and check for the survivorship-censoring signature
(a permanently frozen running-vehicle count with zero arrivals) in the ttt=-1 arm.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "runs", "analysis"))
SUMO = shutil.which("sumo")
END = 14400
SEED = 101
TTTS = [-1, 120, 300, 600]
VARIANTS = sys.argv[1:] or ["A", "C", "F"]

ADD = """<additional>
    <edgeData id="ed" file="edgedata.xml" begin="0" end="%d" excludeEmpty="false" withInternal="false"/>
</additional>
""" % END

out = {}
for v in VARIANTS:
    for ttt in TTTS:
        d = os.path.join(RUNS, "ttt", "%s_%d" % (v, ttt))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "meandata.add.xml"), "w").write(ADD)
        cmd = [SUMO, "-n", os.path.join(NET, "%s.net.xml" % v),
               "-r", os.path.join(RUNS, "routes_%s.rou.xml" % v),
               "-a", "%s,%s" % (os.path.join(NET, "webster.tll.xml"),
                                os.path.join(d, "meandata.add.xml")),
               "--begin", "0", "--end", str(END), "--time-to-teleport", str(ttt),
               "--seed", str(SEED),
               "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
               "--summary-output", os.path.join(d, "summary.xml"),
               "--ignore-route-errors", "true", "--no-step-log", "true"]
        with open(os.path.join(d, "sumo.log"), "w") as lg:
            subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT, check=True)
        ti = ET.parse(os.path.join(d, "tripinfo.xml")).getroot().findall("tripinfo")
        steps = ET.parse(os.path.join(d, "summary.xml")).getroot().findall("step")
        run = [int(s.get("running")) for s in steps]
        end = [int(s.get("ended")) for s in steps]
        # frozen-tail signature: running count constant and no new arrivals over the last 20 min
        tail = 1200
        frozen = (len(run) > tail and len(set(run[-tail:])) == 1 and run[-1] > 0
                  and end[-1] == end[-tail])
        tele = sum(1 for line in open(os.path.join(d, "sumo.log"), errors="ignore")
                   if "teleporting" in line)
        dur = [float(t.get("duration")) for t in ti]
        out["%s_ttt%d" % (v, ttt)] = dict(
            variant=v, ttt=ttt, completed=len(ti), still_running=run[-1],
            teleports_summary=int(steps[-1].get("teleports")), teleport_log_lines=tele,
            mean_duration=round(sum(dur) / max(1, len(dur)), 2),
            frozen_tail=bool(frozen))
        print("%s ttt=%-4d completed=%-5d running=%-4d teleports=%-4d meanDur=%7.2f frozen=%s"
              % (v, ttt, len(ti), run[-1], int(steps[-1].get("teleports")),
                 sum(dur) / max(1, len(dur)), frozen), flush=True)

json.dump(out, open(os.path.join(ANA, "teleport_sweep.json"), "w"), indent=1)
print("wrote", os.path.join(ANA, "teleport_sweep.json"))
