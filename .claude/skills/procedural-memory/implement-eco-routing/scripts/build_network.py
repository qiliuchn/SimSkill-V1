"""Build the two-alternative eco-routing corridor.

Topology (x to the east, y to the north):

    N1    N2    N3    N4                (cross-street north stubs, y=+500)
     |     |     |     |
O -- A -- I1 -- I2 -- I3 -- I4 -- M -- D     ARTERIAL  (y=0, 2 lanes, 50 km/h,
     |     |     |     |     |                          4 fixed-time signals)
     |    S1     |     |    S4
     |           |     |
     +-- P1 --- P2 -- P3 --- P4 --+           BYPASS   (y=-700, 1 lane, 80 km/h,
                                                        uninterrupted / priority)

* Arterial A->M = 5 x 400 m = 2000 m, signalised at I1..I4.
* Bypass   A->M = 806 + 400 + 400 + 400 + 806 = 2812 m, no signals.
* Connectors I2<->P2 and I3<->P3 (700 m each) give local connectivity so a
  vehicle can switch corridors mid-trip => route shares move continuously.
* Cross streets at I1..I4 carry side demand so the fixed-time signals actually
  cost the arterial something.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, NET, run, sumo_bin  # noqa: E402

V_ART = 13.89     # 50 km/h
V_BYP = 22.22     # 80 km/h
V_CROSS = 13.89
V_STEM = 16.67

NODES = [
    # id, x, y, type
    ("O", -400, 0, "priority"),
    ("A", 0, 0, "priority"),
    ("I1", 400, 0, "traffic_light"),
    ("I2", 800, 0, "traffic_light"),
    ("I3", 1200, 0, "traffic_light"),
    ("I4", 1600, 0, "traffic_light"),
    ("M", 2000, 0, "zipper"),
    ("D", 2400, 0, "priority"),
    ("P1", 400, -700, "priority"),
    ("P2", 800, -700, "priority"),
    ("P3", 1200, -700, "priority"),
    ("P4", 1600, -700, "priority"),
    ("N1", 400, 500, "priority"),
    ("N2", 800, 500, "priority"),
    ("N3", 1200, 500, "priority"),
    ("N4", 1600, 500, "priority"),
    ("S1", 400, -350, "priority"),
    ("S4", 1600, -350, "priority"),
]

# id, from, to, lanes, speed, priority
EDGES = [
    ("O_A", "O", "A", 2, V_STEM, 10),
    ("M_D", "M", "D", 2, V_STEM, 10),
    # arterial (one-way eastbound)
    ("A_I1", "A", "I1", 2, V_ART, 9),
    ("I1_I2", "I1", "I2", 2, V_ART, 9),
    ("I2_I3", "I2", "I3", 2, V_ART, 9),
    ("I3_I4", "I3", "I4", 2, V_ART, 9),
    ("I4_M", "I4", "M", 2, V_ART, 9),
    # bypass (one-way eastbound, single lane, high speed, uninterrupted)
    ("A_P1", "A", "P1", 1, V_BYP, 11),
    ("P1_P2", "P1", "P2", 1, V_BYP, 11),
    ("P2_P3", "P2", "P3", 1, V_BYP, 11),
    ("P3_P4", "P3", "P4", 1, V_BYP, 11),
    ("P4_M", "P4", "M", 1, V_BYP, 11),
]

# two-way cross streets (side demand + the corridor connectors)
CROSS = [
    ("N1", "I1"), ("I1", "S1"),
    ("N2", "I2"), ("I2", "P2"),
    ("N3", "I3"), ("I3", "P3"),
    ("N4", "I4"), ("I4", "S4"),
]
for a, b in CROSS:
    EDGES.append(("%s_%s" % (a, b), a, b, 1, V_CROSS, 5))
    EDGES.append(("%s_%s" % (b, a), b, a, 1, V_CROSS, 5))


def main():
    nod = os.path.join(WORK, "corridor.nod.xml")
    edg = os.path.join(WORK, "corridor.edg.xml")
    with open(nod, "w") as f:
        f.write('<nodes>\n')
        for i, x, y, t in NODES:
            f.write('    <node id="%s" x="%s" y="%s" type="%s"/>\n' % (i, x, y, t))
        f.write('</nodes>\n')
    with open(edg, "w") as f:
        f.write('<edges>\n')
        for i, fr, to, nl, sp, pr in EDGES:
            f.write('    <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f" priority="%d"/>\n'
                    % (i, fr, to, nl, sp, pr))
        f.write('</edges>\n')

    run([sumo_bin("netconvert"),
         "-n", nod, "-e", edg, "-o", NET,
         "--no-turnarounds", "true",
         "--tls.default-type", "static",
         "--tls.green.time", "25",
         "--tls.yellow.time", "4",
         "--tls.allred.time", "1",
         "--junctions.corner-detail", "0",
         "--no-internal-links", "false",
         "--offset.disable-normalization", "true"])
    print("wrote", NET)


if __name__ == "__main__":
    main()
