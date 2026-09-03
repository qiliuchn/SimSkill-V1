#!/usr/bin/env python3
"""
Background car demand + Webster fixed-time signal plan.

v/c CONVENTION.  The arterial's capacity is its SIGNALISED approach capacity,
    c = (g/C) * s * n_lanes,   s = 1800 veh/h/lane,
with g/C read from the compiled network's own TLS programme (not assumed).  Demand
is then built to hit a chosen v/c directly, rather than hoping a randomTrips period
lands there:

  * ARTERIAL CORRIDOR demand -- explicit Poisson-seeded <vehicle> elements running
    the full length of each of the 10 arterial corridor-directions (4 ring legs x 2
    + bisector x 2) at rate Q = v/c * c.
  * DISPERSED demand -- randomTrips + duarouter at a fixed period, giving turning
    movements at the signals and genuine local-street traffic for the delivery
    double-parks to interact with.  Identical across arms at a given seed.

Cars are routed on the unrestricted net and the identical route file is reused in
every policy arm at the same seed (the bans touch only truck/delivery vClasses), so
background traffic is exact Common Random Numbers across arms.
"""
import os, sys, json, random, argparse, math
import xml.etree.ElementTree as ET
from common import *   # noqa
import build_network as bn
import sumolib

BASE_NET = os.path.join(NET, "d_strict_0.net.xml")
RANDOMTRIPS = os.path.join(TOOLS, "randomTrips.py")
TLSCYCLE = os.path.join(TOOLS, "tlsCycleAdaptation.py")
SAT_FLOW = 1800.0                 # veh/h/lane
DISPERSED_PERIOD = 2.0            # randomTrips period for the dispersed layer


def corridors():
    """The 10 arterial corridor-directions as node-index paths."""
    C = []
    west = [(0, j) for j in range(N)]
    east = [(N - 1, j) for j in range(N)]
    south = [(i, 0) for i in range(N)]
    north = [(i, N - 1) for i in range(N)]
    bis = [(BISECT_I, j) for j in range(N)]
    for path, name in ((west, "W"), (east, "E"), (south, "S"), (north, "Nr"), (bis, "B")):
        C.append((name + "+", path))
        C.append((name + "-", path[::-1]))
    return C


def corridor_edges(path):
    return [eid(nid(*a), nid(*b)) for a, b in zip(path, path[1:])]


def _arterial_through_links(net, tlsID):
    """Link indices of the TLS that carry an ARTERIAL THROUGH movement
    (from-edge and to-edge both arterial, and geometrically collinear)."""
    arts = set(bn.arterial_edges())
    out = []
    tls = {t.getID(): t for t in net.getTrafficLights()}
    if tlsID not in tls:
        return []
    for conn in tls[tlsID].getConnections():
        inLane, outLane, li = conn[0], conn[1], conn[2]
        fe, te = inLane.getEdge().getID(), outLane.getEdge().getID()
        if fe in arts and te in arts:
            a1, b1 = fe.split("_"); a2, b2 = te.split("_")
            v1 = (int(b1[1]) - int(a1[1]), int(b1[2]) - int(a1[2]))
            v2 = (int(b2[1]) - int(a2[1]), int(b2[2]) - int(a2[2]))
            if v1 == v2:
                out.append(li)
    return sorted(set(out))


def arterial_green_ratio(net_file, tll_file=None):
    """Mean g/C for the ARTERIAL THROUGH movement, read from the compiled net (or
    from the overriding .tll.xml when one is supplied)."""
    net = sumolib.net.readNet(net_file)
    src = tll_file if (tll_file and os.path.exists(tll_file)) else net_file
    progs = {}
    for tl in ET.parse(src).getroot().iter("tlLogic"):
        progs[tl.get("id")] = [(float(p.get("duration")), p.get("state"))
                               for p in tl if p.tag == "phase"]
    ratios = []
    for tlsID, phases in progs.items():
        C = sum(d for d, _ in phases)
        if C <= 0:
            continue
        links = _arterial_through_links(net, tlsID)
        if not links:
            continue
        g = max(sum(d for d, s in phases if s[li] in "Gg") for li in links)
        ratios.append(g / C)
    return sum(ratios) / len(ratios) if ratios else 0.5


def build_arterial_layer(vc_target, seed, out_file, gC, end=DEMAND_END):
    cap = gC * SAT_FLOW * ART_LANES
    Q = vc_target * cap
    rng = random.Random(90000 + seed)
    veh = []
    for cname, path in corridors():
        edges = corridor_edges(path)
        t = 0.0
        rate = Q / 3600.0
        k = 0
        while t < end:
            t += rng.expovariate(rate)
            if t >= end:
                break
            veh.append((t, '  <vehicle id="a%s_%d" type="car" depart="%.2f" '
                            'departLane="best" departSpeed="max"><route edges="%s"/></vehicle>'
                        % (cname, k, t, " ".join(edges))))
            k += 1
    veh.sort()
    open(out_file, "w").write("<routes>\n%s\n</routes>\n" % "\n".join(v[1] for v in veh))
    return len(veh), Q, cap


def build_dispersed_layer(seed, out_prefix, end=DEMAND_END, period=DISPERSED_PERIOD):
    trips = out_prefix + ".trips.xml"
    rou = out_prefix + ".rou.xml"
    r = sh([sys.executable, RANDOMTRIPS, "-n", BASE_NET, "-b", "0", "-e", str(end),
            "--period", str(period), "--seed", str(seed), "--fringe-factor", "3",
            "--min-distance", "500", "--trip-attributes", 'type="car" departLane="best"',
            "--validate", "-o", trips, "--prefix", "d"])
    if r.returncode != 0:
        raise RuntimeError("randomTrips failed: %s" % r.stderr[-2000:])
    r = sh([DUAROUTER, "-n", BASE_NET, "-r", trips, "-o", rou, "--seed", str(seed),
            "--no-step-log", "true", "--additional-files", os.path.join(DEMAND, "vtypes.add.xml")])
    if r.returncode != 0:
        raise RuntimeError("duarouter failed: %s" % r.stderr[-2000:])
    # duarouter copies the referenced vType into its output; strip it, because the
    # vTypes are loaded once from demand/vtypes.add.xml and a second definition is a
    # hard SUMO error ("Another vehicle type ... exists").
    import re as _re
    txt = open(rou).read()
    txt = _re.sub(r"\s*<vType\b[^>]*/>", "", txt)
    txt = _re.sub(r"\s*<vType\b.*?</vType>", "", txt, flags=_re.S)
    open(rou, "w").write(txt)
    return rou, sum(1 for x in ET.parse(rou).getroot() if x.tag == "vehicle")


def write_vtypes():
    p = os.path.join(DEMAND, "vtypes.add.xml")
    open(p, "w").write("<additional>\n%s\n</additional>\n" % vtype_xml())
    return p


def build_webster(car_rou_files):
    out = os.path.join(NET, "webster.tll.xml")
    r = sh([sys.executable, TLSCYCLE, "-n", BASE_NET, "-r", ",".join(car_rou_files),
            "-o", out, "-b", "0", "--min-cycle", "50", "--max-cycle", "120",
            "-y", "4", "-a", "2", "-g", "8"])
    if r.returncode != 0 or not os.path.exists(out):
        print("tlsCycleAdaptation FAILED (falling back to netconvert default plan):",
              r.stderr[-800:])
        return None
    txt = open(out).read()
    for pid in ('programID="a"', "programID='a'"):
        txt = txt.replace(pid, 'programID="0"')
    open(out, "w").write(txt)
    cyc = []
    for tl in ET.parse(out).getroot().iter("tlLogic"):
        cyc.append(sum(float(p.get("duration")) for p in tl if p.tag == "phase"))
    print("webster plan: %d tlLogics, cycles %.0f-%.0f s (mean %.0f)"
          % (len(cyc), min(cyc), max(cyc), sum(cyc) / len(cyc)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="low,mid,high")
    args = ap.parse_args()
    write_vtypes()

    gC0 = arterial_green_ratio(BASE_NET)
    print("netconvert default arterial g/C = %.3f" % gC0)

    idx = {}
    # a first pass with the default TLS plan, to give tlsCycleAdaptation real demand
    seed0 = SEEDS[0]
    tmp = []
    for lvl, vc in DEMAND_LEVELS.items():
        f = os.path.join(DEMAND, "_tmp_art_%s.rou.xml" % lvl)
        build_arterial_layer(vc, seed0, f, gC0)
        tmp.append(f)
    disp0, _ = build_dispersed_layer(2000 + seed0, os.path.join(DEMAND, "_tmp_disp"))
    tll = build_webster([tmp[1], disp0])          # size Webster on the MID level
    gC = arterial_green_ratio(BASE_NET, tll)
    print("Webster arterial g/C = %.3f -> arterial capacity %.0f veh/h (2 lanes)"
          % (gC, gC * SAT_FLOW * ART_LANES))

    for lvl in args.levels.split(","):
        vc = DEMAND_LEVELS[lvl]
        for s in SEEDS:
            af = os.path.join(DEMAND, "cars_art_%s_s%d.rou.xml" % (lvl, s))
            n_a, Q, cap = build_arterial_layer(vc, s, af, gC)
            dp = os.path.join(DEMAND, "cars_disp_s%d" % s)
            if not os.path.exists(dp + ".rou.xml"):
                build_dispersed_layer(2000 + s, dp)
            n_d = sum(1 for x in ET.parse(dp + ".rou.xml").getroot() if x.tag == "vehicle")
            idx.setdefault(lvl, {})[str(s)] = dict(arterial=af, dispersed=dp + ".rou.xml",
                                                   n_arterial=n_a, n_dispersed=n_d,
                                                   Q_per_corridor=Q, capacity=cap, vc=vc)
        print("level %-4s vc=%.2f Q=%.0f veh/h/corridor  arterial veh=%d dispersed=%d"
              % (lvl, vc, Q, n_a, n_d))
    json.dump(dict(index=idx, gC=gC, sat_flow=SAT_FLOW, tll=tll),
              open(os.path.join(DEMAND, "car_index.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
