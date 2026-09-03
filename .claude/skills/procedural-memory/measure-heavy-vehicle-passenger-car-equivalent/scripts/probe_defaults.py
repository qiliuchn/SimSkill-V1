#!/usr/bin/env python3
"""PROBE 0 -- establish ground truth before any measurement.

(a) Read back SUMO's OWN default vType attribute values for vClass="truck",
    "trailer" and "passenger" via TraCI (never assume documented defaults).
(b) Test empirically whether longitudinal GRADE affects the car-following /
    acceleration model at all (as opposed to only the emission model): a single
    truck accelerates from rest on a 0% and on a 6% upgrade, identical in every
    other respect; compare the realised speed profiles.
"""
import os, sys, subprocess, json

SUMO_HOME = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
os.environ["SUMO_HOME"] = SUMO_HOME
sys.path.append(os.path.join(SUMO_HOME, "tools"))
BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
import traci

W = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "probe")
os.makedirs(W, exist_ok=True)


def build(grade_pct, tag):
    dz = 2000.0 * grade_pct / 100.0
    nod = os.path.join(W, "%s.nod.xml" % tag)
    with open(nod, "w") as f:
        f.write('<nodes>\n')
        f.write('  <node id="A" x="0" y="0" z="0"/>\n')
        f.write('  <node id="B" x="2000" y="0" z="%.4f"/>\n' % dz)
        f.write('</nodes>\n')
    edg = os.path.join(W, "%s.edg.xml" % tag)
    with open(edg, "w") as f:
        f.write('<edges>\n  <edge id="E" from="A" to="B" numLanes="1" speed="40.0"/>\n</edges>\n')
    net = os.path.join(W, "%s.net.xml" % tag)
    subprocess.run([os.path.join(BIN, "netconvert"), "-n", nod, "-e", edg, "-o", net,
                    "--no-turnarounds", "true"], check=True, capture_output=True)
    return net


def realised_grade(net):
    import xml.etree.ElementTree as ET
    t = ET.parse(net)
    out = {}
    for e in t.getroot().findall("edge"):
        if e.get("function") == "internal":
            continue
        for ln in e.findall("lane"):
            pts = []
            for p in ln.get("shape").split():
                c = [float(v) for v in p.split(",")]
                if len(c) == 2:
                    c.append(0.0)          # 2-coord shape point == flat (z=0)
                pts.append(c)
            (x0, y0, z0), (x1, y1, z1) = pts[0], pts[-1]
            horiz = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            out[ln.get("id")] = 100.0 * (z1 - z0) / horiz
    return out


def run(net, tag):
    rou = os.path.join(W, "%s.rou.xml" % tag)
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="dcar"   vClass="passenger"/>\n')
        f.write('  <vType id="dtruck" vClass="truck"/>\n')
        f.write('  <vType id="dtrail" vClass="trailer"/>\n')
        f.write('  <route id="r" edges="E"/>\n')
        f.write('  <vehicle id="car"   type="dcar"   route="r" depart="0" departSpeed="0"/>\n')
        f.write('  <vehicle id="truck" type="dtruck" route="r" depart="0" departSpeed="0" departLane="0"/>\n')
        f.write('</routes>\n')
    traci.start([os.path.join(BIN, "sumo"), "-n", net, "-r", rou, "--step-length", "0.1",
                 "--no-step-log", "true", "--xml-validation", "never", "--begin", "0", "--end", "400"],
                label=tag)
    traci.switch(tag)
    defaults = {}
    prof = {"car": [], "truck": []}
    step = 0
    while traci.simulation.getMinExpectedNumber() > 0 and step < 4000:
        traci.simulationStep()
        t = traci.simulation.getTime()
        for vid in ("car", "truck"):
            if vid in traci.vehicle.getIDList():
                prof[vid].append((round(t, 1), round(traci.vehicle.getSpeed(vid), 4),
                                  round(traci.vehicle.getSlope(vid), 4),
                                  round(traci.vehicle.getAcceleration(vid), 4)))
        if not defaults:
            for tid in traci.vehicletype.getIDList():
                try:
                    defaults[tid] = dict(
                        length=traci.vehicletype.getLength(tid),
                        minGap=traci.vehicletype.getMinGap(tid),
                        maxSpeed=traci.vehicletype.getMaxSpeed(tid),
                        accel=traci.vehicletype.getAccel(tid),
                        decel=traci.vehicletype.getDecel(tid),
                        tau=traci.vehicletype.getTau(tid),
                        speedFactor=traci.vehicletype.getSpeedFactor(tid),
                        speedDev=traci.vehicletype.getSpeedDeviation(tid),
                        vClass=traci.vehicletype.getVehicleClass(tid),
                        emissionClass=traci.vehicletype.getEmissionClass(tid),
                        cfmodel=traci.vehicletype.getParameter(tid, "carFollowModel"),
                    )
                except Exception as ex:
                    defaults[tid] = {"error": str(ex)}
        step += 1
    traci.close()
    return defaults, prof


res = {}
for g in (0.0, 6.0):
    tag = "g%g" % g
    net = build(g, tag)
    rg = realised_grade(net)
    d, prof = run(net, tag)
    res["grade_%g" % g] = {
        "realised_grade_pct_from_compiled_net": rg,
        "vtype_defaults": d,
        "truck_speed_at_t": {str(t): s for (t, s, sl, a) in prof["truck"] if abs(t * 10 - round(t * 10)) < 1e-9 and round(t, 1) in (5.0, 10.0, 20.0, 30.0, 40.0, 60.0, 90.0, 120.0)},
        "car_speed_at_t": {str(t): s for (t, s, sl, a) in prof["car"] if round(t, 1) in (5.0, 10.0, 20.0, 30.0, 40.0, 60.0, 90.0, 120.0)},
        "truck_slope_seen_by_traci": prof["truck"][50][2] if len(prof["truck"]) > 50 else None,
        "truck_max_speed_reached": max(s for (_, s, _, _) in prof["truck"]),
        "car_max_speed_reached": max(s for (_, s, _, _) in prof["car"]),
    }

with open(os.path.join(W, "probe_defaults.json"), "w") as f:
    json.dump(res, f, indent=2)
print(json.dumps(res, indent=2))
