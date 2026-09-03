#!/usr/bin/env python3
"""
Per-variant DUE assignment (duaIterate) followed by CRN-seeded replications.

  stage 1  `--due`   : duaIterate.py separately for EVERY network variant, on the
                       identical trips file, with the identical Webster TLS plans.
                       Writes a convergence diagnostic per variant.
  stage 2  `--sim`   : replicate the converged route set with 5 common random numbers
                       (identical seed list across variants), collecting tripinfo,
                       summary, vehroute, edgeData, emissions (+ SSM on seed #1).
"""
import argparse
import gzip
import json
import os
import shutil
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET = os.path.join(ROOT, "net")
DEM = os.path.join(ROOT, "demand")
RUNS = os.path.join(ROOT, "runs")
ANA = os.path.join(ROOT, "analysis")
TOOLS = os.path.join(os.environ["SUMO_HOME"], "tools")
DUAIT = os.path.join(TOOLS, "assign", "duaIterate.py")
SUMO = shutil.which("sumo") or os.path.join(os.environ["SUMO_HOME"], "bin", "sumo")

VARIANTS = list("ABCDEF")
SEEDS = [101, 202, 303, 404, 505]          # common random numbers, identical per variant
END = 14400
DUE_STEPS = 25
TTT = 300                                   # > longest Webster red phase (verified separately)


def due(variant, trips=None, outdir=None, steps=DUE_STEPS, net=None):
    net = net or os.path.join(NET, "%s.net.xml" % variant)
    trips = trips or os.path.join(DEM, "all.trips.xml")
    outdir = outdir or os.path.join(RUNS, "due", variant)
    os.makedirs(outdir, exist_ok=True)
    for f in os.listdir(outdir):
        p = os.path.join(outdir, f)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    cmd = [sys.executable, DUAIT, "-n", net, "-t", trips, "-l", str(steps),
           "-e", str(END), "--begin", "0", "-A", "0.5", "-B", "0.9",
           # gA=0.3 (default 0.5) damps the Gawron path-flow SWAP RATE.  Needed because
           # with the defaults variant F's assignment OSCILLATED (cut-through veh-km
           # 527 -> 190 -> 535 over iterations 2/13/15).  --weight-memory was tried too
           # and REJECTED: smoothing the link costs as well froze every variant on a
           # still-declining trajectory at a ~60%% worse total cost (see
           # analysis/due_weightmemory_cutthrough_trace.json).
           "--time-to-teleport", str(TTT), "--clean-alt",
           "--additional", os.path.join(NET, "webster.tll.xml"),
           "sumo--ignore-route-errors", "True"]
    with open(os.path.join(outdir, "due.log"), "w") as lg:
        subprocess.run(cmd, cwd=outdir, stdout=lg, stderr=subprocess.STDOUT, check=True)
    return outdir


def route_edges(path):
    op = gzip.open if path.endswith(".gz") else open
    out = {}
    for v in ET.parse(op(path)).getroot().findall("vehicle"):
        out[v.get("id")] = tuple(v.find("route").get("edges").split())
    return out


def due_diagnostic(outdir, steps):
    """mean duration / departDelay / fraction of vehicles that changed route per iteration"""
    trace, prev = [], None
    for it in range(steps):
        tri = os.path.join(outdir, "%03d" % it, "tripinfo_%03d.xml" % it)
        rou = os.path.join(outdir, "%03d" % it, "all_%03d.rou.xml.gz" % it)
        if not (os.path.exists(tri) and os.path.exists(rou)):
            break
        tis = ET.parse(tri).getroot().findall("tripinfo")
        d = [float(t.get("duration")) for t in tis]
        dd = [float(t.get("departDelay")) for t in tis]
        cur = route_edges(rou)
        chg = None
        if prev is not None:
            common = set(cur) & set(prev)
            chg = sum(1 for k in common if cur[k] != prev[k]) / max(1, len(common))
        prev = cur
        trace.append(dict(iter=it, n_completed=len(tis), mean_duration=round(st.mean(d), 2),
                          mean_depart_delay=round(st.mean(dd), 2),
                          mean_total_cost=round(st.mean(d) + st.mean(dd), 2),
                          route_change_fraction=None if chg is None else round(chg, 4)))
    return trace


def last_iter(outdir, steps):
    for it in range(steps - 1, -1, -1):
        p = os.path.join(outdir, "%03d" % it, "all_%03d.rou.xml.gz" % it)
        if os.path.exists(p):
            return it, p
    raise SystemExit("no DUE route output in " + outdir)


ADD_TMPL = """<additional>
    <edgeData id="ed" file="edgedata.xml" begin="0" end="{end}" period="300" excludeEmpty="false" withInternal="false"/>
    <edgeData id="em" type="emissions" file="emissions.xml" begin="0" end="{end}" excludeEmpty="true" withInternal="false"/>
</additional>
"""


def simulate(variant, routes, seed, tag, netfile=None, ssm=False):
    d = os.path.join(RUNS, "sim", "%s_s%s" % (tag, seed))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meandata.add.xml"), "w") as f:
        f.write(ADD_TMPL.format(end=END))
    cmd = [SUMO, "-n", netfile or os.path.join(NET, "%s.net.xml" % variant),
           "-r", routes,
           "-a", "%s,%s" % (os.path.join(NET, "webster.tll.xml"),
                            os.path.join(d, "meandata.add.xml")),
           "--begin", "0", "--end", str(END),
           "--time-to-teleport", str(TTT),
           "--seed", str(seed),
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--summary-output", os.path.join(d, "summary.xml"),
           "--vehroute-output", os.path.join(d, "vehroute.xml"),
           "--vehroute-output.exit-times", "false",
           "--ignore-route-errors", "true",
           "--no-step-log", "true", "--duration-log.statistics", "true"]
    if ssm:
        cmd += ["--device.ssm.probability", "0.25",
                "--device.ssm.file", os.path.join(d, "ssm.xml"),
                "--device.ssm.measures", "TTC DRAC PET BR",
                "--device.ssm.thresholds", "3.0 3.0 2.0 0.0",
                "--device.ssm.range", "40.0", "--device.ssm.extratime", "5.0"]
    with open(os.path.join(d, "sumo.log"), "w") as lg:
        r = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise SystemExit("sumo failed in " + d)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--variants", default="ABCDEF")
    a = ap.parse_args()
    vs = list(a.variants)
    os.makedirs(ANA, exist_ok=True)

    if a.due:
        diag = {}
        if os.path.exists(os.path.join(ANA, "due_convergence.json")):
            diag = json.load(open(os.path.join(ANA, "due_convergence.json")))
        for v in vs:
            print("=== DUE for variant %s ===" % v, flush=True)
            od = due(v)
            diag[v] = due_diagnostic(od, DUE_STEPS)
            it, p = last_iter(od, DUE_STEPS)
            dst = os.path.join(RUNS, "routes_%s.rou.xml" % v)
            with gzip.open(p) as fi, open(dst, "wb") as fo:
                shutil.copyfileobj(fi, fo)
            print("  final iteration %d -> %s" % (it, dst), flush=True)
            for r in diag[v]:
                print("   it%-3d n=%-5d dur=%8.2f dd=%6.2f chg=%s"
                      % (r["iter"], r["n_completed"], r["mean_duration"],
                         r["mean_depart_delay"], r["route_change_fraction"]), flush=True)
            json.dump(diag, open(os.path.join(ANA, "due_convergence.json"), "w"), indent=1)

    if a.sim:
        for v in vs:
            routes = os.path.join(RUNS, "routes_%s.rou.xml" % v)
            for k, s in enumerate(SEEDS):
                d = simulate(v, routes, s, v, ssm=(k == 0))
                print("ran %s seed %d -> %s" % (v, s, d), flush=True)


if __name__ == "__main__":
    main()
