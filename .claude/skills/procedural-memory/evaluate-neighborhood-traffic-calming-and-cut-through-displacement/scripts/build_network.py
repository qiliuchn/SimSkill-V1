#!/usr/bin/env python3
"""
Build the neighbourhood-traffic-management test bed and all six network variants.

Topology
--------
  * Interior: 6x6 junction residential grid (5x5 blocks), 130 m blocks, 1 lane per
    direction, 30 km/h, unsignalized junctions.
  * Boundary arterial ring: 2 lanes per direction, 50 km/h, signalized at the four
    corners plus one mid-block signal per side (8 signals).
  * 24 short residential connectors join every interior boundary junction to the ring
    (a highly permeable grid -- the classic rat-running geometry).
  * 8 external gateway stubs (4 side mid-block + 4 corner) carry external demand.

Variants
--------
  A  baseline
  B  interior speed limit 30 -> 20 km/h
  C  modal filter: car-free perimeter of the central block (8 directed edges),
     allow="bus bicycle pedestrian emergency"
  D  diagonal diverters (turn prohibitions) at 8 interior junctions
  E  one-way loop cells on the inner interior streets (perimeter stays two-way)
  F  C + B combined
"""
import os
import subprocess
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "net"))
os.makedirs(OUT, exist_ok=True)


def bindir():
    p = shutil.which("netconvert")
    if p:
        return os.path.dirname(p)
    p = shutil.which("sumo")
    if p:
        return os.path.dirname(p)
    return os.path.join(os.environ["SUMO_HOME"], "bin")


NETCONVERT = os.path.join(bindir(), "netconvert")

# ---------------------------------------------------------------- geometry ----
N = 6                       # interior junctions per side
BLOCK = 130.0               # interior block length (m)
X0 = 200.0                  # interior grid origin
XS = [X0 + BLOCK * i for i in range(N)]          # 200 .. 850
MID = (XS[0] + XS[-1]) / 2.0                     # 525
RING_LO, RING_HI = 50.0, 1000.0                  # ring rectangle
STUB = 450.0                                     # external stub length

V_RES = 30.0 / 3.6          # 8.333 m/s
V_RES_CALM = 20.0 / 3.6     # 5.556 m/s
V_ART = 50.0 / 3.6          # 13.889 m/s

PRIO_RES = 1
PRIO_ART = 3

FILTER_ALLOW = "bus bicycle pedestrian emergency"

# ------------------------------------------------------------------ nodes ----
nodes = {}   # id -> (x, y, type)


def nd(i, x, y, t):
    nodes[i] = (x, y, t)


for i in range(N):
    for j in range(N):
        # right_before_left: symmetric unsignalized residential right-of-way.
        # (plain "priority" makes netconvert pick N-S as the major street at EVERY
        #  interior junction, which would bias the spatial cut-through analysis.)
        nd("I%d%d" % (i, j), XS[i], XS[j], "right_before_left")

# ring corner + mid-block signals
nd("CSW", RING_LO, RING_LO, "traffic_light")
nd("CSE", RING_HI, RING_LO, "traffic_light")
nd("CNE", RING_HI, RING_HI, "traffic_light")
nd("CNW", RING_LO, RING_HI, "traffic_light")
nd("MS", MID, RING_LO, "traffic_light")
nd("MN", MID, RING_HI, "traffic_light")
nd("MW", RING_LO, MID, "traffic_light")
nd("ME", RING_HI, MID, "traffic_light")

# ring access nodes (unsignalized T-junctions, arterial has priority)
for i in range(N):
    nd("RSa%d" % i, XS[i], RING_LO, "priority")
    nd("RNa%d" % i, XS[i], RING_HI, "priority")
    nd("RWa%d" % i, RING_LO, XS[i], "priority")
    nd("REa%d" % i, RING_HI, XS[i], "priority")

# external gateways
nd("XS", MID, RING_LO - STUB, "priority")
nd("XN", MID, RING_HI + STUB, "priority")
nd("XW", RING_LO - STUB, MID, "priority")
nd("XE", RING_HI + STUB, MID, "priority")
nd("XSW", RING_LO - 320, RING_LO - 320, "priority")
nd("XSE", RING_HI + 320, RING_LO - 320, "priority")
nd("XNE", RING_HI + 320, RING_HI + 320, "priority")
nd("XNW", RING_LO - 320, RING_HI + 320, "priority")

# ------------------------------------------------------------------ edges ----
# edge record: id -> dict(frm,to,lanes,speed,prio,allow)
edges = {}


def link(base, a, b, lanes, speed, prio, suf_f, suf_b):
    edges[base + suf_f] = dict(frm=a, to=b, lanes=lanes, speed=speed, prio=prio)
    edges[base + suf_b] = dict(frm=b, to=a, lanes=lanes, speed=speed, prio=prio)


# interior grid
for i in range(N - 1):
    for j in range(N):
        link("IH%d%d" % (i, j), "I%d%d" % (i, j), "I%d%d" % (i + 1, j),
             1, V_RES, PRIO_RES, "E", "W")
for i in range(N):
    for j in range(N - 1):
        link("IV%d%d" % (i, j), "I%d%d" % (i, j), "I%d%d" % (i, j + 1),
             1, V_RES, PRIO_RES, "N", "S")

# connectors ring <-> interior  (I = into the neighbourhood, O = out)
for i in range(N):
    link("KS%d" % i, "RSa%d" % i, "I%d0" % i, 1, V_RES, PRIO_RES, "I", "O")
    link("KN%d" % i, "RNa%d" % i, "I%d%d" % (i, N - 1), 1, V_RES, PRIO_RES, "I", "O")
    link("KW%d" % i, "RWa%d" % i, "I0%d" % i, 1, V_RES, PRIO_RES, "I", "O")
    link("KE%d" % i, "REa%d" % i, "I%d%d" % (N - 1, i), 1, V_RES, PRIO_RES, "I", "O")

# ring: ordered node chains per side
south = ["CSW"] + ["RSa%d" % i for i in range(3)] + ["MS"] + ["RSa%d" % i for i in range(3, N)] + ["CSE"]
north = ["CNW"] + ["RNa%d" % i for i in range(3)] + ["MN"] + ["RNa%d" % i for i in range(3, N)] + ["CNE"]
west = ["CSW"] + ["RWa%d" % i for i in range(3)] + ["MW"] + ["RWa%d" % i for i in range(3, N)] + ["CNW"]
east = ["CSE"] + ["REa%d" % i for i in range(3)] + ["ME"] + ["REa%d" % i for i in range(3, N)] + ["CNE"]

for tag, chain, fwd, bwd in (("S", south, "E", "W"), ("N", north, "E", "W"),
                             ("W", west, "N", "S"), ("E", east, "N", "S")):
    for k in range(len(chain) - 1):
        link("RG%s%d" % (tag, k), chain[k], chain[k + 1], 2, V_ART, PRIO_ART, fwd, bwd)

# external stubs (I = inbound to the study area, O = outbound)
for tag, xn, rn in (("S", "XS", "MS"), ("N", "XN", "MN"), ("W", "XW", "MW"), ("E", "XE", "ME"),
                    ("SW", "XSW", "CSW"), ("SE", "XSE", "CSE"),
                    ("NE", "XNE", "CNE"), ("NW", "XNW", "CNW")):
    link("EX%s" % tag, xn, rn, 2, V_ART, PRIO_ART, "I", "O")

# ------------------------------------------------------- variant definitions --
# C / F: modal filter = car-free perimeter of the central block
CENTER_LINKS = ["IH22", "IH23", "IV22", "IV32"]
FILTERED_EDGES = []
for b in CENTER_LINKS:
    for s in (("E", "W") if b.startswith("IH") else ("N", "S")):
        FILTERED_EDGES.append(b + s)

# E: one-way loop cells.  Inner streets only (grid perimeter stays two-way).
#    row j  (1..N-2): East if j odd else West
#    col i  (1..N-2): North if i odd else South
ONEWAY_REMOVED = []
for i in range(N - 1):
    for j in range(1, N - 1):
        ONEWAY_REMOVED.append("IH%d%d" % (i, j) + ("W" if j % 2 == 1 else "E"))
for i in range(1, N - 1):
    for j in range(N - 1):
        ONEWAY_REMOVED.append("IV%d%d" % (i, j) + ("S" if i % 2 == 1 else "N"))
ONEWAY_KEPT = [e for e in edges if (e.startswith("IH") or e.startswith("IV"))
               and e not in ONEWAY_REMOVED]

# D: diagonal diverters.  barrier "NESW" keeps N<->W and S<->E; "NWSE" keeps N<->E and S<->W
DIVERTERS = {(1, 1): "NESW", (3, 1): "NESW", (1, 3): "NESW", (3, 3): "NESW",
             (2, 2): "NWSE", (4, 2): "NWSE", (2, 4): "NWSE", (4, 4): "NWSE"}


def arm_edges(i, j):
    """incoming and outgoing edge id per compass arm at interior junction I{i}{j}"""
    inc, out = {}, {}
    # north arm
    if j < N - 1:
        inc["N"] = "IV%d%dS" % (i, j)
        out["N"] = "IV%d%dN" % (i, j)
    else:
        inc["N"] = "KN%dI" % i
        out["N"] = "KN%dO" % i
    # south arm
    if j > 0:
        inc["S"] = "IV%d%dN" % (i, j - 1)
        out["S"] = "IV%d%dS" % (i, j - 1)
    else:
        inc["S"] = "KS%dI" % i
        out["S"] = "KS%dO" % i
    # east arm
    if i < N - 1:
        inc["E"] = "IH%d%dW" % (i, j)
        out["E"] = "IH%d%dE" % (i, j)
    else:
        inc["E"] = "KE%dI" % j
        out["E"] = "KE%dO" % j
    # west arm
    if i > 0:
        inc["W"] = "IH%d%dE" % (i - 1, j)
        out["W"] = "IH%d%dW" % (i - 1, j)
    else:
        inc["W"] = "KW%dI" % j
        out["W"] = "KW%dO" % j
    return inc, out


ALLOWED_PAIRS = {"NESW": {("N", "W"), ("W", "N"), ("S", "E"), ("E", "S")},
                 "NWSE": {("N", "E"), ("E", "N"), ("S", "W"), ("W", "S")}}

# ---------------------------------------------------------------- writers ----


def write_nodes(path):
    with open(path, "w") as f:
        f.write('<nodes>\n')
        for nid, (x, y, t) in sorted(nodes.items()):
            f.write('    <node id="%s" x="%.2f" y="%.2f" type="%s"/>\n' % (nid, x, y, t))
        f.write('</nodes>\n')


def write_edges(path, speed_override=None, allow_map=None, drop=()):
    """speed_override: dict predicate-name -> speed applied to interior residential edges"""
    with open(path, "w") as f:
        f.write('<edges>\n')
        for eid, e in sorted(edges.items()):
            if eid in drop:
                continue
            sp = e["speed"]
            if speed_override is not None and (eid[:2] in ("IH", "IV") or eid[0] == "K"):
                sp = speed_override
            extra = ""
            if allow_map and eid in allow_map:
                extra = ' allow="%s"' % allow_map[eid]
            f.write('    <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.4f" '
                    'priority="%d"%s/>\n' % (eid, e["frm"], e["to"], e["lanes"], sp,
                                             e["prio"], extra))
        f.write('</edges>\n')


def write_diverter_connections(path):
    """explicit <delete> of every movement blocked by a diagonal barrier"""
    lines = []
    for (i, j), kind in sorted(DIVERTERS.items()):
        inc, out = arm_edges(i, j)
        keep = ALLOWED_PAIRS[kind]
        for a_in in "NSEW":
            for a_out in "NSEW":
                if (a_in, a_out) in keep:
                    continue
                # netconvert never builds the u-turn back onto the same road when
                # --no-turnarounds is set, but delete defensively anyway
                lines.append('    <delete from="%s" to="%s"/>' % (inc[a_in], out[a_out]))
    with open(path, "w") as f:
        f.write('<connections>\n')
        f.write("\n".join(lines))
        f.write('\n</connections>\n')
    return len(lines)


def netconv(nod, edg, out, con=None):
    cmd = [NETCONVERT, "-n", nod, "-e", edg, "-o", out,
           "--no-turnarounds", "true",
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-internal-links", "false",
           "--offset.disable-normalization", "true"]
    if con:
        cmd += ["-x", con]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("netconvert failed for %s" % out)
    warn = [l for l in r.stderr.splitlines() if "Warning" in l]
    return len(warn)


def main():
    nod = os.path.join(OUT, "base.nod.xml")
    write_nodes(nod)

    specs = {
        "A": dict(speed=None, allow=None, drop=(), con=None),
        "B": dict(speed=V_RES_CALM, allow=None, drop=(), con=None),
        "C": dict(speed=None, allow={e: FILTER_ALLOW for e in FILTERED_EDGES}, drop=(), con=None),
        "D": dict(speed=None, allow=None, drop=(), con="D"),
        "E": dict(speed=None, allow=None, drop=tuple(ONEWAY_REMOVED), con=None),
        "F": dict(speed=V_RES_CALM, allow={e: FILTER_ALLOW for e in FILTERED_EDGES},
                  drop=(), con=None),
    }
    ncon = write_diverter_connections(os.path.join(OUT, "D.con.xml"))
    print("variant D: %d explicit <delete> connection prohibitions" % ncon)

    for v, s in specs.items():
        edg = os.path.join(OUT, "%s.edg.xml" % v)
        write_edges(edg, speed_override=s["speed"], allow_map=s["allow"], drop=s["drop"])
        con = os.path.join(OUT, "D.con.xml") if s["con"] else None
        w = netconv(nod, edg, os.path.join(OUT, "%s.net.xml" % v), con=con)
        print("built %s.net.xml (%d netconvert warnings)" % (v, w))

    with open(os.path.join(OUT, "edge_sets.txt"), "w") as f:
        f.write("INTERIOR_STREETS=%s\n" % " ".join(sorted(e for e in edges if e[:2] in ("IH", "IV"))))
        f.write("ACCESS_CONNECTORS=%s\n" % " ".join(sorted(e for e in edges if e[0] == "K")))
        f.write("RING=%s\n" % " ".join(sorted(e for e in edges if e.startswith("RG"))))
        f.write("EXTERNAL=%s\n" % " ".join(sorted(e for e in edges if e.startswith("EX"))))
        f.write("FILTERED=%s\n" % " ".join(sorted(FILTERED_EDGES)))
        f.write("ONEWAY_REMOVED=%s\n" % " ".join(sorted(ONEWAY_REMOVED)))
        f.write("ONEWAY_KEPT=%s\n" % " ".join(sorted(ONEWAY_KEPT)))
        f.write("DIVERTERS=%s\n" % " ".join("I%d%d:%s" % (i, j, k)
                                            for (i, j), k in sorted(DIVERTERS.items())))
    print("total edges in base: %d ; interior streets: %d ; filtered: %d ; oneway-removed: %d"
          % (len(edges), sum(1 for e in edges if e[:2] in ("IH", "IV")),
             len(FILTERED_EDGES), len(ONEWAY_REMOVED)))


if __name__ == "__main__":
    main()
