#!/usr/bin/env python3
"""PROBE 1 -- is ANY SUMO car-following model grade-sensitive?

A single default-truck vehicle accelerates from rest along a 2 km edge that is
flat / +4% / +6% (grade verified from the COMPILED net's lane shape).  For each
carFollowModel we record the speed reached at t=20/40/80 s and the max speed.
If SUMO modelled grade in the longitudinal dynamics, uphill speeds would drop.
"""
import os, sys, subprocess, json
SUMO_HOME = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ["SUMO_HOME"] = SUMO_HOME
sys.path.append(os.path.join(SUMO_HOME, "tools"))
BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
import traci

W = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "probe")
MODELS = ["Krauss", "KraussOrig1", "IDM", "EIDM", "ACC", "CACC", "W99", "Wiedemann", "PWagner2009", "BKerner", "Daniel1"]
GRADES = [0.0, 4.0, 6.0]
res = {}
for g in GRADES:
    net = os.path.join(W, "gg%g.net.xml" % g)
    if not os.path.exists(net):
        nod = os.path.join(W, "gg%g.nod.xml" % g); edg = os.path.join(W, "gg%g.edg.xml" % g)
        open(nod, "w").write('<nodes>\n <node id="A" x="0" y="0" z="0"/>\n <node id="B" x="2000" y="0" z="%.4f"/>\n</nodes>\n' % (2000 * g / 100.0))
        open(edg, "w").write('<edges>\n <edge id="E" from="A" to="B" numLanes="1" speed="40.0"/>\n</edges>\n')
        subprocess.run([os.path.join(BIN, "netconvert"), "-n", nod, "-e", edg, "-o", net, "--no-turnarounds", "true"], check=True, capture_output=True)
    rou = os.path.join(W, "gg%g.rou.xml" % g)
    with open(rou, "w") as f:
        f.write('<routes>\n <route id="r" edges="E"/>\n')
        for m in MODELS:
            f.write('  <vType id="t_%s" vClass="truck" carFollowModel="%s" sigma="0" speedDev="0"/>\n' % (m, m))
        for i, m in enumerate(MODELS):
            f.write('  <vehicle id="v_%s" type="t_%s" route="r" depart="%d" departSpeed="0"/>\n' % (m, m, i * 200))
        f.write('</routes>\n')
    lab = "L%g" % g
    traci.start([os.path.join(BIN, "sumo"), "-n", net, "-r", rou, "--step-length", "0.1",
                 "--no-step-log", "true", "--xml-validation", "never", "--end", "3000"], label=lab)
    traci.switch(lab)
    born = {}; prof = {m: {} for m in MODELS}; vmax = {m: 0.0 for m in MODELS}
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        t = traci.simulation.getTime()
        for vid in traci.vehicle.getIDList():
            m = vid[2:]
            born.setdefault(m, t)
            dt = round(t - born[m], 1)
            sp = traci.vehicle.getSpeed(vid)
            vmax[m] = max(vmax[m], sp)
            if dt in (20.0, 40.0, 80.0):
                prof[m][dt] = round(sp, 4)
    traci.close()
    res["grade_%g" % g] = {m: {"v20": prof[m].get(20.0), "v40": prof[m].get(40.0), "v80": prof[m].get(80.0), "vmax": round(vmax[m], 4)} for m in MODELS}
json.dump(res, open(os.path.join(W, "probe_grade_cfmodels.json"), "w"), indent=2)
print("%-14s %10s %10s %10s   %10s %10s %10s" % ("model", "v40@0%", "v40@4%", "v40@6%", "vmax@0%", "vmax@4%", "vmax@6%"))
for m in MODELS:
    r = [res["grade_%g" % g][m] for g in GRADES]
    print("%-14s %10s %10s %10s   %10s %10s %10s" % (m, r[0]["v40"], r[1]["v40"], r[2]["v40"], r[0]["vmax"], r[1]["vmax"], r[2]["vmax"]))
