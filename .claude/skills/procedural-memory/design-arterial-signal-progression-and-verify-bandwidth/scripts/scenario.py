#!/usr/bin/env python3
"""Scenario cache: (spacing L, demand seed, demand level) -> net + routed demand.

Every experiment pulls its networks/demand from here so that Common Random
Numbers really are common: the SAME routed .rou.xml file object is reused
across every signal-plan arm compared at a given (L, seed, demand).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import sumolib               # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(HERE, "work")
N_INT = 7
END = 3000.0
WARM = 600.0


def key(L, seed, thru, cross, side, n_int=N_INT, end=END):
    return "L%.0f_s%d_t%.0f_c%.0f_x%.0f_n%d_e%.0f" % (
        L, seed, thru, cross, side, n_int, end)


def get(L=400.0, seed=1, thru=600.0, cross=250.0, side=60.0, n_int=N_INT,
        end=END, cross_len=300.0):
    """Return dict(net, rou, xs, n_int, ntrips). Builds + caches on first call."""
    k = key(L, seed, thru, cross, side, n_int, end)
    d = os.path.join(WORK, "scen", k)
    meta = os.path.join(d, "meta.json")
    if os.path.exists(meta):
        return json.load(open(meta))
    os.makedirs(d, exist_ok=True)
    net = A.build_net(d, n_int=n_int, L=L, cross_len=cross_len)
    trips, ntr = A.write_demand(os.path.join(d, "trips.xml"), n_int, seed,
                                end=end, thru=thru, cross=cross, art_side=side)
    rou = A.route(net, trips, os.path.join(d, "routes.rou.xml"))
    nt = sumolib.net.readNet(net)
    xs = [nt.getNode("J%d" % i).getCoord()[0] for i in range(n_int)]
    m = dict(net=net, rou=rou, trips=trips, xs=xs, n_int=n_int, ntrips=ntr,
             L=L, seed=seed, thru=thru, cross=cross, side=side, end=end, dir=d)
    json.dump(m, open(meta, "w"), indent=1)
    return m


def coordinate_plan(scen, plan_add, outdir, speed_factor=None, tag="coord"):
    """Run tlsCoordinator.py on an EXISTING hand-authored plan (via -a).

    This is what makes the H2 comparison fair: all three offset sets act on the
    identical cycle, phase structure and green splits -- only the offsets
    differ. speed_factor is passed through so the tool gets the SAME assumed
    progression speed the analytic MAXBAND search uses (see the search-space
    fairness requirement in optimize-signal-plan-with-simulation-in-the-loop-ga).
    """
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "%s.offsets.add.xml" % tag)
    cmd = [sys.executable, os.path.join(A.SUMO_HOME, "tools", "tlsCoordinator.py"),
           "-n", scen["net"], "-r", scen["rou"], "-o", out, "-a", plan_add]
    if speed_factor is not None:
        cmd += ["--speed-factor", "%.4f" % speed_factor]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out):
        raise RuntimeError("tlsCoordinator failed:\n%s\n%s" % (p.stdout, p.stderr))
    with open(os.path.join(outdir, "%s.log" % tag), "w") as f:
        f.write(p.stdout + "\n" + p.stderr)
    progs = A.load_programs([scen["net"], plan_add, out])
    return out, [progs["J%d" % i][0] for i in range(scen["n_int"])]


def tls_tools(scen, outdir, max_cycle=120, min_cycle=40, begin=WARM):
    """Run tlsCycleAdaptation --unified-cycle then tlsCoordinator on a scenario.

    Returns (cycles_add, offsets_add).
    """
    os.makedirs(outdir, exist_ok=True)
    tools = os.path.join(A.SUMO_HOME, "tools")
    cyc = os.path.join(outdir, "cycles.add.xml")
    off = os.path.join(outdir, "offsets.add.xml")
    p1 = subprocess.run([sys.executable,
                         os.path.join(tools, "tlsCycleAdaptation.py"),
                         "-n", scen["net"], "-r", scen["rou"], "-o", cyc,
                         "--unified-cycle", "-b", str(begin),
                         "--min-cycle", str(min_cycle),
                         "--max-cycle", str(max_cycle)],
                        capture_output=True, text=True)
    if not os.path.exists(cyc):
        raise RuntimeError("tlsCycleAdaptation failed:\n%s\n%s"
                           % (p1.stdout[-2000:], p1.stderr[-2000:]))
    p2 = subprocess.run([sys.executable,
                         os.path.join(tools, "tlsCoordinator.py"),
                         "-n", scen["net"], "-r", scen["rou"], "-o", off,
                         "-a", cyc],
                        capture_output=True, text=True)
    if not os.path.exists(off):
        raise RuntimeError("tlsCoordinator failed:\n%s\n%s"
                           % (p2.stdout[-2000:], p2.stderr[-2000:]))
    with open(os.path.join(outdir, "tools.log"), "w") as f:
        f.write("### tlsCycleAdaptation\n%s\n%s\n### tlsCoordinator\n%s\n%s\n"
                % (p1.stdout, p1.stderr, p2.stdout, p2.stderr))
    return cyc, off
