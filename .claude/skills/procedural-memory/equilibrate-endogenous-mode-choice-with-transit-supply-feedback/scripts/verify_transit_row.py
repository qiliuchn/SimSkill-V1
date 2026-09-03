"""VERIFICATION (i): the dedicated transit right-of-way is genuinely car-inaccessible
in the COMPILED net, and transit running time is insensitive to car volume.

Four independent checks, all against compiled artefacts / the SUMO binary:
  A  compiled .net.xml lane permissions on t1_0 / t2_0 and on the internal turn lane
     that connects the general-traffic feeder edge to t1 at junction O
  B  duarouter routing a *passenger* vehicle ORG -> DST must not use t1/t2
  C  duarouter routing a *bus* ORG -> DST may use t1/t2 (so the ROW is not simply broken)
  D  sumo must HARD-FAIL on a passenger vehicle explicitly routed over t1 t2
"""
import os
import re
import subprocess
import sys
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, ".."))
WORK = os.path.join(OUT, "..", "attempts", "attempt-1", "verify")
WORK = os.path.abspath(WORK)
os.makedirs(WORK, exist_ok=True)

ok_all = True


def report(name, ok, detail):
    global ok_all
    ok_all = ok_all and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


for variant in ("base", "expanded"):
    net = os.path.join(OUT, "net", f"corridor_{variant}.net.xml")
    root = ET.parse(net).getroot()

    # ---- A: lane permissions in the compiled net
    perms = {}
    for e in root.findall("edge"):
        for ln in e.findall("lane"):
            perms[ln.get("id")] = (ln.get("allow"), ln.get("disallow"))
    for lid in ("t1_0", "t2_0"):
        a, d = perms.get(lid, (None, None))
        report(f"A {variant} {lid}", a == "bus" and d is None,
               f'allow={a!r} disallow={d!r}')
    # the internal lane at junction O that realises feed -> t1
    conn = [c for c in root.findall("connection")
            if c.get("from") == "feed" and c.get("to") == "t1"]
    if conn:
        via = conn[0].get("via")
        a, d = perms.get(via, (None, None))
        report(f"A {variant} internal {via} (feed->t1 turn EXISTS geometrically)",
               a == "bus", f'allow={a!r} -- the turn is built but only buses may take it')
    else:
        report(f"A {variant} feed->t1 connection", True,
               "netconvert built no feed->t1 connection at all")
    # r2 lane count = the only thing that differs between variants
    n_r2 = len([l for l in perms if l.startswith("r2_")])
    report(f"A {variant} bottleneck r2 lanes", n_r2 == (1 if variant == "base" else 2),
           f"{n_r2} lane(s)")

# ---- B/C: duarouter mode-specific shortest paths
net = os.path.join(OUT, "net", "corridor_base.net.xml")
trips = os.path.join(WORK, "probe.trips.xml")
with open(trips, "w") as f:
    f.write('<routes>\n'
            '  <vType id="car" vClass="passenger"/>\n'
            '  <vType id="bus" vClass="bus"/>\n'
            '  <trip id="probe_car" type="car" depart="0" from="feed" to="exit"/>\n'
            '  <trip id="probe_bus" type="bus" depart="0" from="feed" to="exit"/>\n'
            '</routes>\n')
routed = os.path.join(WORK, "probe.rou.xml")
r = subprocess.run(["duarouter", "-n", net, "-r", trips, "-o", routed,
                    "--no-step-log", "true", "--no-warnings", "true"],
                   capture_output=True, text=True)
if r.returncode == 0 and os.path.exists(routed):
    rr = ET.parse(routed).getroot()
    got = {}
    for v in rr.iter():
        if v.tag in ("vehicle", "trip") and v.get("id"):
            rt = v.find("route")
            if rt is not None:
                got[v.get("id")] = rt.get("edges")
    car_edges = got.get("probe_car", "")
    bus_edges = got.get("probe_bus", "")
    report("B passenger route avoids transit ROW",
           "t1" not in car_edges.split() and "t2" not in car_edges.split(),
           f"probe_car -> {car_edges!r}")
    # NB: duarouter gives the bus the ROAD path here -- both paths are legal for a bus
    # and the road path happens to be marginally faster.  That is not evidence about
    # permissions, so check C is done properly below by execution, not by routing.
    print(f"[INFO] duarouter's chosen bus route (both paths legal for a bus): {bus_edges!r}")
else:
    report("B/C duarouter probe", False, r.stderr[:400])

# ---- C: sumo must ACCEPT a bus explicitly routed over the ROW (mirror image of D)
good = os.path.join(WORK, "legal_bus.rou.xml")
with open(good, "w") as f:
    f.write('<routes>\n'
            '  <vType id="bus" vClass="bus"/>\n'
            '  <vehicle id="legal_bus" type="bus" depart="0">\n'
            '    <route edges="feed t1 t2 exit"/>\n'
            '  </vehicle>\n'
            '</routes>\n')
r = subprocess.run(["sumo", "-n", net, "-r", good, "--no-step-log", "true", "--end", "1000",
                    "--tripinfo-output", os.path.join(WORK, "legal_bus.tripinfo.xml")],
                   capture_output=True, text=True)
arrived = False
if r.returncode == 0 and os.path.exists(os.path.join(WORK, "legal_bus.tripinfo.xml")):
    tr = ET.parse(os.path.join(WORK, "legal_bus.tripinfo.xml")).getroot()
    arrived = any(t.get("id") == "legal_bus" for t in tr.findall("tripinfo"))
report("C sumo ACCEPTS a bus routed over t1/t2 (ROW works, it is not simply broken)",
       r.returncode == 0 and arrived, f"rc={r.returncode} arrived={arrived}")

# ---- D: sumo must reject a passenger vehicle explicitly routed over the ROW
bad = os.path.join(WORK, "illegal.rou.xml")
with open(bad, "w") as f:
    f.write('<routes>\n'
            '  <vType id="car" vClass="passenger"/>\n'
            '  <vehicle id="illegal_car" type="car" depart="0">\n'
            '    <route edges="feed t1 t2 exit"/>\n'
            '  </vehicle>\n'
            '</routes>\n')
r = subprocess.run(["sumo", "-n", net, "-r", bad, "--no-step-log", "true", "--end", "600"],
                   capture_output=True, text=True)
msg = (r.stderr + r.stdout)
hit = re.search(r"(not allowed|no connection|does not allow|disallowed|Invalid)", msg, re.I)
report("D sumo rejects passenger vehicle routed over t1/t2",
       r.returncode != 0 and hit is not None,
       f"rc={r.returncode} :: {(hit.group(0) if hit else msg[:200]).strip()} :: "
       f"{[l for l in msg.splitlines() if 'Error' in l][:1]}")

# ---- E: transit running time is insensitive to car volume (dedicated ROW)
sys.path.insert(0, HERE)
import dt_scenario as S  # noqa: E402
ivts = {}
for p_car in (0.05, 0.95):
    rr = S.simulate(os.path.join(WORK, f"ivt_p{int(p_car*100)}"),
                    os.path.join(OUT, "net", "corridor_base.net.xml"),
                    3000, p_car, 1, feedback=False, h_fixed=374.0)
    ivts[p_car] = (rr["transit_ivt"], rr["car_cost"])
lo, hi = ivts[0.05][0], ivts[0.95][0]
report("E transit in-vehicle time insensitive to car volume",
       abs(hi - lo) / lo < 0.05,
       f"IVT {lo:.1f}s at 5% car share vs {hi:.1f}s at 95% car share "
       f"({100*(hi-lo)/lo:+.1f}%), while CAR cost went "
       f"{ivts[0.05][1]:.0f}s -> {ivts[0.95][1]:.0f}s "
       f"({100*(ivts[0.95][1]-ivts[0.05][1])/ivts[0.05][1]:+.0f}%)")

print("\nALL CHECKS PASSED" if ok_all else "\nSOME CHECKS FAILED")
sys.exit(0 if ok_all else 1)
