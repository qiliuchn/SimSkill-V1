#!/usr/bin/env python3
"""
DNDP testbed definition: 4x4 grid with asymmetric capacities, 8 external gates,
fixed OD demand, and a candidate project set of exactly 10 discrete projects.

This module is imported by every other script so that the network topology,
the project set and the demand are defined in exactly one place.
"""
import os
import subprocess
import random

SUMO_HOME = os.environ.get("SUMO_HOME",
                           "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
NETCONVERT = "netconvert"

SPACING = 500.0          # m between grid nodes
NCOL = 4
NROW = 4
GRID_SPEED = 13.89       # m/s  (50 km/h)
ACCESS_SPEED = 16.67     # m/s  (60 km/h)
ACCESS_LEN = 400.0

# ---------------------------------------------------------------- geometry ---
def nid(i, j):
    return "n%d%d" % (i, j)

GATES = {                      # gate node -> (grid node it attaches to, x, y)
    "W1": (nid(0, 1), -ACCESS_LEN, 1 * SPACING),
    "W2": (nid(0, 2), -ACCESS_LEN, 2 * SPACING),
    "E1": (nid(3, 1), 3 * SPACING + ACCESS_LEN, 1 * SPACING),
    "E2": (nid(3, 2), 3 * SPACING + ACCESS_LEN, 2 * SPACING),
    "S1": (nid(1, 0), 1 * SPACING, -ACCESS_LEN),
    "S2": (nid(2, 0), 2 * SPACING, -ACCESS_LEN),
    "N1": (nid(1, 3), 1 * SPACING, 3 * SPACING + ACCESS_LEN),
    "N2": (nid(2, 3), 2 * SPACING, 3 * SPACING + ACCESS_LEN),
}
SIDE_OF = {"W1": "W", "W2": "W", "E1": "E", "E2": "E",
           "S1": "S", "S2": "S", "N1": "N", "N2": "N"}


def eid(a, b):
    return "%s_%s" % (a, b)


# ------------------------------------------------------- base network spec ---
def base_edges():
    """Return dict edge_id -> dict(frm, to, lanes, speed, length_from_geom)."""
    E = {}
    # horizontal grid edges (both directions)
    for j in range(NROW):
        for i in range(NCOL - 1):
            a, b = nid(i, j), nid(i + 1, j)
            lanes = 2 if j == 2 else 1          # row j=2 is the 2-lane E-W arterial
            E[eid(a, b)] = dict(frm=a, to=b, lanes=lanes, speed=GRID_SPEED)
            E[eid(b, a)] = dict(frm=b, to=a, lanes=lanes, speed=GRID_SPEED)
    # vertical grid edges (both directions)
    for i in range(NCOL):
        for j in range(NROW - 1):
            a, b = nid(i, j), nid(i, j + 1)
            lanes = 2 if i == 2 else 1          # column i=2 is the 2-lane N-S arterial
            E[eid(a, b)] = dict(frm=a, to=b, lanes=lanes, speed=GRID_SPEED)
            E[eid(b, a)] = dict(frm=b, to=a, lanes=lanes, speed=GRID_SPEED)
    # access edges from external gates
    for g, (gn, x, y) in GATES.items():
        E[eid(g, gn)] = dict(frm=g, to=gn, lanes=2, speed=ACCESS_SPEED)
        E[eid(gn, g)] = dict(frm=gn, to=g, lanes=2, speed=ACCESS_SPEED)
    return E


def base_nodes():
    N = {}
    for i in range(NCOL):
        for j in range(NROW):
            N[nid(i, j)] = dict(x=i * SPACING, y=j * SPACING, typ="traffic_light")
    for g, (gn, x, y) in GATES.items():
        N[g] = dict(x=x, y=y, typ="priority")
    return N


# ------------------------------------------------------------- projects -----
# Exactly 10 discrete, mutually independent candidate projects.
#  L1..L7  : lane additions (numLanes +1) on named existing 1-lane edge PAIRS
#  N1, N2  : genuinely new links (diagonal connectors)
#  NB      : the deliberately-included "shortcut" new link -- Braess candidate
#
# Costs are in consistent monetary units (MU). A lane-km is priced at 3.0 MU/km
# of new lane (both directions => 2 lane-km per 500 m link pair = 1.0 km).
# New links are priced at 12.0 MU/km of new 1-lane-each-way road; the shortcut
# is 2 lanes each way at 70 km/h so it is priced at 20.0 MU/km.
PROJECTS = [
    # id, kind, payload, cost (MU), description
    dict(id="L1", kind="lane", edges=[eid(nid(0, 1), nid(1, 1)), eid(nid(1, 1), nid(0, 1))],
         cost=3.0, desc="+1 lane both dir on row-1 west link n01<->n11"),
    dict(id="L2", kind="lane", edges=[eid(nid(1, 1), nid(2, 1)), eid(nid(2, 1), nid(1, 1))],
         cost=3.0, desc="+1 lane both dir on row-1 middle link n11<->n21"),
    dict(id="L3", kind="lane", edges=[eid(nid(2, 1), nid(3, 1)), eid(nid(3, 1), nid(2, 1))],
         cost=3.0, desc="+1 lane both dir on row-1 east link n21<->n31"),
    dict(id="L4", kind="lane", edges=[eid(nid(1, 0), nid(1, 1)), eid(nid(1, 1), nid(1, 0))],
         cost=3.0, desc="+1 lane both dir on col-1 south link n10<->n11"),
    dict(id="L5", kind="lane", edges=[eid(nid(1, 1), nid(1, 2)), eid(nid(1, 2), nid(1, 1))],
         cost=3.0, desc="+1 lane both dir on col-1 middle link n11<->n12"),
    dict(id="L6", kind="lane", edges=[eid(nid(1, 2), nid(1, 3)), eid(nid(1, 3), nid(1, 2))],
         cost=3.0, desc="+1 lane both dir on col-1 north link n12<->n13"),
    dict(id="L7", kind="lane", edges=[eid(nid(0, 2), nid(0, 1)), eid(nid(0, 1), nid(0, 2))],
         cost=3.0, desc="+1 lane both dir on col-0 link n02<->n01"),
    dict(id="N1", kind="newlink", pair=(nid(0, 0), nid(1, 1)), lanes=1, speed=GRID_SPEED,
         cost=8.5, desc="new diagonal link n00<->n11 (1 lane/dir, 50 km/h, 707 m)"),
    dict(id="N2", kind="newlink", pair=(nid(2, 2), nid(3, 3)), lanes=1, speed=GRID_SPEED,
         cost=8.5, desc="new diagonal link n22<->n33 (1 lane/dir, 50 km/h, 707 m)"),
    dict(id="NB", kind="newlink", pair=(nid(1, 1), nid(2, 2)), lanes=2, speed=19.44,
         cost=14.1, desc="SHORTCUT new diagonal link n11<->n22 (2 lanes/dir, 70 km/h, 707 m) "
                         "- deliberate Braess candidate"),
]
PROJECT_IDS = [p["id"] for p in PROJECTS]
NPROJ = len(PROJECTS)
assert NPROJ == 10


def subset_from_mask(mask):
    return [PROJECT_IDS[k] for k in range(NPROJ) if (mask >> k) & 1]


def mask_from_subset(sub):
    m = 0
    for s in sub:
        m |= 1 << PROJECT_IDS.index(s)
    return m


def subset_cost(mask):
    return round(sum(PROJECTS[k]["cost"] for k in range(NPROJ) if (mask >> k) & 1), 4)


# ------------------------------------------------------- network building ----
def write_plain_xml(mask, outdir):
    """Write nod.xml / edg.xml for the design given by `mask`."""
    os.makedirs(outdir, exist_ok=True)
    N = base_nodes()
    E = base_edges()
    for k in range(NPROJ):
        if not (mask >> k) & 1:
            continue
        p = PROJECTS[k]
        if p["kind"] == "lane":
            for e in p["edges"]:
                E[e]["lanes"] += 1
        elif p["kind"] == "newlink":
            a, b = p["pair"]
            E[eid(a, b)] = dict(frm=a, to=b, lanes=p["lanes"], speed=p["speed"])
            E[eid(b, a)] = dict(frm=b, to=a, lanes=p["lanes"], speed=p["speed"])
    nodf = os.path.join(outdir, "net.nod.xml")
    edgf = os.path.join(outdir, "net.edg.xml")
    with open(nodf, "w") as f:
        f.write("<nodes>\n")
        for k in sorted(N):
            v = N[k]
            f.write('  <node id="%s" x="%.2f" y="%.2f" type="%s"/>\n'
                    % (k, v["x"], v["y"], v["typ"]))
        f.write("</nodes>\n")
    with open(edgf, "w") as f:
        f.write("<edges>\n")
        for k in sorted(E):
            v = E[k]
            f.write('  <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f" priority="%d"/>\n'
                    % (k, v["frm"], v["to"], v["lanes"], v["speed"],
                       2 if v["lanes"] >= 2 else 1))
        f.write("</edges>\n")
    return nodf, edgf


def build_net(mask, outdir, netfile=None):
    nodf, edgf = write_plain_xml(mask, outdir)
    netfile = netfile or os.path.join(outdir, "net.net.xml")
    cmd = [NETCONVERT, "--node-files", nodf, "--edge-files", edgf,
           "-o", netfile, "--no-turnarounds", "true",
           "--tls.default-type", "static",
           "--default.junctions.keep-clear", "true",
           "--no-warnings", "true"]
    subprocess.run(cmd, check=True, capture_output=True)
    return netfile


# ------------------------------------------------------------- demand -------
def od_weights():
    """Fixed OD weight table over the 8 gates (no same-side pairs)."""
    W = {}
    for o in GATES:
        for d in GATES:
            if SIDE_OF[o] == SIDE_OF[d]:
                continue
            w = 1.0
            if SIDE_OF[o] == "W" and SIDE_OF[d] == "E":
                w = 3.0
            elif SIDE_OF[o] == "E" and SIDE_OF[d] == "W":
                w = 3.0
            elif SIDE_OF[o] == "S" and SIDE_OF[d] == "N":
                w = 2.0
            elif SIDE_OF[o] == "N" and SIDE_OF[d] == "S":
                w = 2.0
            W[(o, d)] = w
    return W


DEMAND_END = 1800.0          # s : the loading period
DEMAND_SEED = 20260805       # fixed demand-realisation seed (never varied)


def write_trips(nveh, path, seed=DEMAND_SEED):
    """Write a fixed trip file with `nveh` vehicles over [0, DEMAND_END)."""
    rng = random.Random(seed)
    W = od_weights()
    keys = sorted(W)
    tot = sum(W[k] for k in keys)
    cum, acc = [], 0.0
    for k in keys:
        acc += W[k] / tot
        cum.append(acc)
    trips = []
    for v in range(nveh):
        r = rng.random()
        idx = next(t for t in range(len(cum)) if r <= cum[t])
        o, d = keys[idx]
        t = rng.random() * DEMAND_END
        trips.append((t, o, d))
    trips.sort()
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write('  <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" '
                'maxSpeed="27.78" tau="1.0"/>\n')
        for k, (t, o, d) in enumerate(trips):
            f.write('  <trip id="v%d" type="car" depart="%.2f" from="%s" to="%s"/>\n'
                    % (k, t, eid(o, GATES[o][0]), eid(GATES[d][0], d)))
        f.write('</routes>\n')
    return path, {("v%d" % k): trips[k][0] for k in range(len(trips))}


if __name__ == "__main__":
    import json
    print(json.dumps([{k: v for k, v in p.items() if k != "edges" or True}
                      for p in PROJECTS], indent=2, default=str))
