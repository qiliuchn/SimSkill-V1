#!/usr/bin/env python3
"""
Crossover control test (task item 4): are the median U-turn crossovers better left
UNSIGNALIZED-YIELD (the baseline everywhere else in this study) or SIGNALIZED?

Builds a parallel set of nets in which XW/XE are traffic_light junctions, authors a
2-phase crossover program derived from each net's own compiled link indices
(phase A: both arterial through streams, U-turn red;
 phase B: U-turn green + the non-conflicting WB/EB through stream, conflicting
          through stream red),
and re-runs the most crossover-stressed cells.
"""
import itertools
import json
import os
import subprocess
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
import gen_network as gn  # noqa: E402
import run as R  # noqa: E402
import signals as sg  # noqa: E402

GA, GB, Y, AR = 38.0, 12.0, 3.0, 2.0
CELLS = [(100, 3600, 0.50), (100, 3600, 0.10), (200, 3600, 0.40), (400, 3600, 0.30)]
SEEDS = [1, 2, 3]


def build_xsig_net(variant, D):
    d = os.path.join(ROOT, "nets_xsig", f"{variant}_D{int(D)}")
    netf = os.path.join(d, "net.net.xml")
    if os.path.exists(netf):
        return netf
    gn.build(d, variant, D)
    # re-run netconvert with the crossovers promoted to traffic lights
    nod = os.path.join(d, "net.nod.xml")
    s = open(nod).read()
    for n in ("XW", "XE"):
        s = s.replace(f'id="{n}" x=', f'id="{n}" TLMARK x=')
    s = s.replace('TLMARK', '').replace('type="priority"/>', 'type="priority"/>')
    # simpler: rewrite the two node lines explicitly
    lines = []
    for ln in open(nod):
        if 'id="XW"' in ln or 'id="XE"' in ln:
            ln = ln.replace('type="priority"', 'type="traffic_light"')
        lines.append(ln)
    open(nod, "w").write("".join(lines))
    subprocess.run(["netconvert", "-n", nod, "-e", os.path.join(d, "net.edg.xml"),
                    "-x", os.path.join(d, "net.con.xml"), "-o", netf,
                    "--no-turnarounds", "true", "--default.junctions.keep-clear", "true",
                    "--tls.default-type", "static", "--no-internal-links", "false",
                    "--offset.disable-normalization", "true"],
                   check=True, capture_output=True, text=True)
    return netf


def xover_program(netfile, node):
    net = sumolib.net.readNet(netfile)
    tls = net.getTLS(node)
    conns = tls.getConnections()
    n = max(c[2] for c in conns) + 1
    ut, ebt, wbt = [], [], []
    nd = net.getNode(node)
    for inl, outl, li in conns:
        c = [x for x in nd.getConnections()
             if x.getFromLane().getID() == inl.getID() and x.getToLane().getID() == outl.getID()]
        dirn = c[0].getDirection() if c else "s"
        if dirn == "t":
            ut.append(li)
        elif node == "XW":
            (ebt if inl.getEdge().getID() == "E_W_XW" else wbt).append(li)
        else:
            (ebt if inl.getEdge().getID() == "W_E_XE" else wbt).append(li)
    # ebt = the stream the U-turn must cross;  wbt = the stream feeding the U-turn
    def st(g):
        return "".join("G" if i in g else "r" for i in range(n))
    ph = [(GA, st(ebt + wbt)), (Y, "".join("y" if i in (ebt + wbt) else "r" for i in range(n))),
          (AR, "r" * n),
          (GB, st(ut + wbt)), (Y, "".join("y" if i in (ut + wbt) else "r" for i in range(n))),
          (AR, "r" * n)]
    body = f'  <tlLogic id="{node}" type="static" programID="webster" offset="0">\n'
    for d, s in ph:
        body += f'    <phase duration="{d:.1f}" state="{s}"/>\n'
    return body + "  </tlLogic>\n", {"n_links": n, "uturn": ut, "crossed_through": ebt,
                                     "parallel_through": wbt}


def run_one(kw):
    variant, D, Q, m, seed, mode = kw
    if mode == "xsig":
        netf = build_xsig_net(variant, D)
    else:
        netf = R.ensure_net(variant, D)
    trips, taz = R.ensure_trips(Q, m)
    rd = os.path.join(ROOT, "routes_x", f"{mode}_{variant}_D{int(D)}_Q{int(Q)}_m{int(m*100)}")
    os.makedirs(rd, exist_ok=True)
    rou = os.path.join(rd, "rou.xml")
    if not os.path.exists(rou):
        subprocess.run(["duarouter", "-n", netf, "--additional-files", taz, "-r", trips,
                        "-o", rou, "--with-taz", "--no-step-log", "true", "--ignore-errors",
                        "--routing-threads", "1"], check=True, capture_output=True, text=True)
    plan = sg.design(netf, rou, variant)
    d = os.path.join(ROOT, "runs_xsig",
                     f"{mode}_{variant}_D{int(D)}_Q{int(Q)}_m{int(m*100)}_s{seed}")
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, "DONE")):
        return d
    add = os.path.join(d, "add.xml")
    R.write_additional(add, netf, plan, d)
    if mode == "xsig":
        body = open(add).read().replace("</additional>", "")
        info = {}
        for node in ("XW", "XE"):
            b, i = xover_program(netf, node)
            body += b
            info[node] = i
        open(add, "w").write(body + "</additional>\n")
        json.dump(info, open(os.path.join(d, "xover_program.json"), "w"), indent=1)
    cmd = ["sumo", "-n", netf, "-r", rou, "-a", add, "--begin", "0", "--end", str(R.SIM_END),
           "--step-length", "0.5", "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "300",
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(d, "summary.xml"),
           "--duration-log.statistics", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=d)
    open(os.path.join(d, "sumo.log"), "w").write(r.stdout + "\n--STDERR--\n" + r.stderr)
    if r.returncode != 0:
        return "FAIL " + str(kw) + r.stderr[-1500:]
    json.dump({"variant": variant, "D": D, "Q": Q, "m": m, "seed": seed,
               "tag": f"xover_{mode}", "ttt": 300, "ssm": False, "route_file": rou,
               "net": netf, "plan": plan}, open(os.path.join(d, "meta.json"), "w"), indent=1)
    open(os.path.join(d, "DONE"), "w").close()
    return d


if __name__ == "__main__":
    jobs = [(v, D, Q, m, s, mode)
            for (D, Q, m) in CELLS
            for v in ("conv", "rcut", "mut")
            for s in SEEDS
            for mode in ("yield", "xsig")]
    with Pool(4) as p:
        for r in p.imap_unordered(run_one, jobs):
            if str(r).startswith("FAIL"):
                print(r)
    print("xsig test done:", len(jobs), "runs")
