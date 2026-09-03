#!/usr/bin/env python3
"""
CONTROL EXPERIMENT: what is the maximum flow SUMO can actually INSERT onto a plain
3-lane 120 km/h freeway edge with this study's vType?

Motivation: across all three interchange designs and every demand level above scale 1.10,
the most upstream E1 station on EB-A reads an essentially constant ~4270 veh/h, even in
the flyover design whose interior is demonstrably free-flowing (mean time loss ~25 s).
That is the signature of a boundary-insertion ceiling rather than an interchange capacity,
and it decides whether the flyover's throughput plateau is a measured capacity or merely a
lower bound.  This isolates the ceiling on a bottleneck-free straight pipe.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(EPISODE, "outputs", "runs", "_insertion_ceiling")
VTYPE = ('<vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6" '
         'decel="4.5" sigma="0.5" tau="1.1" maxSpeed="45" '
         'speedFactor="normc(1.0,0.10,0.75,1.25)" carFollowModel="Krauss" '
         'laneChangeModel="LC2013"/>')


def build():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "p.nod.xml"), "w").write(
        '<nodes>\n<node id="a" x="0" y="0"/>\n<node id="b" x="4000" y="0"/>\n</nodes>\n')
    open(os.path.join(OUT, "p.edg.xml"), "w").write(
        '<edges>\n<edge id="pipe" from="a" to="b" numLanes="3" speed="33.33" '
        'spreadType="center"/>\n</edges>\n')
    subprocess.run(["netconvert", "-n", os.path.join(OUT, "p.nod.xml"),
                    "-e", os.path.join(OUT, "p.edg.xml"),
                    "-o", os.path.join(OUT, "p.net.xml")],
                   capture_output=True, text=True, check=True)
    lines = ['<additional>']
    for l in range(3):
        lines.append('  <inductionLoop id="d%d" lane="pipe_%d" pos="200" period="60" '
                     'file="ins_e1.xml"/>' % (l, l))
    lines.append('</additional>')
    open(os.path.join(OUT, "det.add.xml"), "w").write("\n".join(lines) + "\n")


def run(vph, depart_speed, depart_lane, eager, tag):
    rou = os.path.join(OUT, "r_%s.rou.xml" % tag)
    open(rou, "w").write(
        '<routes>\n  %s\n  <route id="r" edges="pipe"/>\n'
        '  <flow id="f" type="car" route="r" begin="0" end="1800" vehsPerHour="%d" '
        'departLane="%s" departSpeed="%s"/>\n</routes>\n' % (VTYPE, vph, depart_lane, depart_speed))
    cmd = ["sumo", "-n", os.path.join(OUT, "p.net.xml"), "-r", rou,
           "-a", os.path.join(OUT, "det.add.xml"),
           "--statistic-output", os.path.join(OUT, "st_%s.xml" % tag),
           "--end", "2400", "--seed", "11", "--no-step-log", "--xml-validation", "never",
           "--eager-insert", str(eager).lower()]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=OUT)
    tot, k = 0.0, 0
    for iv in ET.parse(os.path.join(OUT, "ins_e1.xml")).getroot().iter("interval"):
        t = float(iv.get("begin"))
        if 600 <= t < 1800:
            tot += float(iv.get("flow"))
            k += 1
    served = tot / (k / 3.0) if k else 0.0
    root = ET.parse(os.path.join(OUT, "st_%s.xml" % tag)).getroot()
    v = root.find("vehicles")
    return served, int(v.get("loaded")), int(v.get("inserted"))


def main():
    build()
    print("Max insertable flow on a plain 3-lane 120 km/h edge (no downstream bottleneck)")
    print("%-38s %12s %10s %10s %10s" % ("configuration", "served vph", "veh/h/ln",
                                         "loaded", "inserted"))
    cases = [
        ("demand 6000, desired/free, lazy", 6000, "desired", "free", False),
        ("demand 9000, desired/free, lazy", 9000, "desired", "free", False),
        ("demand 15000, desired/free, lazy", 15000, "desired", "free", False),
        ("demand 15000, max/free, lazy", 15000, "max", "free", False),
        ("demand 15000, desired/best, lazy", 15000, "desired", "best", False),
        ("demand 15000, max/free, EAGER", 15000, "max", "free", True),
        ("demand 15000, max/random, lazy", 15000, "max", "random", False),
    ]
    res = {}
    for name, vph, ds, dl, eager in cases:
        served, loaded, ins = run(vph, ds, dl, eager, re.sub(r"[^A-Za-z0-9]", "", name))
        res[name] = served
        print("%-38s %12.0f %10.0f %10d %10d" % (name, served, served / 3.0, loaded, ins))
    print("\nThe study's own configuration is 'desired/free, lazy'.")


if __name__ == "__main__":
    main()
