#!/usr/bin/env python3
"""
Step 6 -- the EVAPORATION hypothesis, tested explicitly.

Re-runs a chosen filter variant with ELASTIC demand: a generalized-cost feedback loop
that suppresses trips whose equilibrium cost rises past what they paid in the baseline.

  retention(OD pair p) = min(1, ( C_X(p) / C_A(p) ) ** (-elasticity))

with C = mean TOTAL experienced generalized cost (in-network duration + departDelay,
the dual-cost definition from `compute-dynamic-user-equilibrium`).  A fixed per-trip
uniform draw (common random numbers) decides which individual trips survive, so the
same trip is suppressed consistently across elasticities and outer iterations, and
trips can come BACK if costs fall again (a genuine fixed point, not monotone attrition).

Outer loop: demand -> DUE -> costs -> demand, 3 passes plus a final DUE of record.
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
import shutil
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NET, DEM, RUNS, ANA = (os.path.join(ROOT, x) for x in ("net", "demand", "runs", "analysis"))
TOOLS = os.path.join(os.environ["SUMO_HOME"], "tools")
DUAIT = os.path.join(TOOLS, "assign", "duaIterate.py")
END = 14400
TTT = 300
INNER = 6          # duaIterate iterations per outer pass
OUTER = 4          # demand<->cost fixed-point passes before the DUE of record
MSA_ALPHA = 0.5    # damping on the RETENTION vector (see below)

sets = {}
for line in open(os.path.join(NET, "edge_sets.txt")):
    k, _, v = line.strip().partition("=")
    sets[k] = v.split() if v else []
INTERIOR = set(sets["INTERIOR_STREETS"])
RING = set(sets["RING"])

sys.path.append(TOOLS)
import sumolib  # noqa: E402
net = sumolib.net.readNet(os.path.join(NET, "A.net.xml"))
LEN = {e.getID(): e.getLength() for e in net.getEdges() if not e.getFunction()}

# ---------------------------------------------------------- OD pair labelling ----
edge2zone = {}
for taz in ET.parse(os.path.join(DEM, "zones.taz.xml")).getroot().findall("taz"):
    for tag in ("tazSource", "tazSink"):
        for e in taz.findall(tag):
            edge2zone.setdefault(e.get("id"), taz.get("id"))

TRIPS = []
HEADER = []
for line in open(os.path.join(DEM, "all.trips.xml")):
    TRIPS.append(line)
root = ET.parse(os.path.join(DEM, "all.trips.xml")).getroot()
TRIP_EL = root.findall("trip")
PAIR = {}
for t in TRIP_EL:
    PAIR[t.get("id")] = "%s>%s" % (edge2zone.get(t.get("from"), "?"),
                                   edge2zone.get(t.get("to"), "?"))


def udraw(vid):
    h = hashlib.md5(("crn|" + vid).encode()).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


U = {t.get("id"): udraw(t.get("id")) for t in TRIP_EL}
VTYPE_LINE = ('  <vType id="car" vClass="passenger" length="4.5" minGap="2.5" accel="2.6"\n'
              '         decel="4.5" sigma="0.5" tau="1.0" maxSpeed="27.8" '
              'emissionClass="HBEFA3/PC_G_EU4"/>\n')


def write_trips(path, keep):
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write(VTYPE_LINE)
        for t in TRIP_EL:
            if t.get("id") in keep:
                f.write('  <trip id="%s" type="car" depart="%s" from="%s" to="%s" '
                        'departLane="best" departSpeed="max"/>\n'
                        % (t.get("id"), t.get("depart"), t.get("from"), t.get("to")))
        f.write('</routes>\n')


# ------------------------------------------------------------------ DUE call ----
def run_due(netf, trips, outdir, steps=INNER):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    cmd = [sys.executable, DUAIT, "-n", netf, "-t", trips, "-l", str(steps), "-e", str(END),
           "--begin", "0", "-A", "0.3", "-B", "0.9", "--time-to-teleport", str(TTT),
           "--clean-alt", "--additional", os.path.join(NET, "webster.tll.xml"),
           "sumo--ignore-route-errors", "True"]
    with open(os.path.join(outdir, "due.log"), "w") as lg:
        subprocess.run(cmd, cwd=outdir, stdout=lg, stderr=subprocess.STDOUT, check=True)
    for it in range(steps - 1, -1, -1):
        ti = os.path.join(outdir, "%03d" % it, "tripinfo_%03d.xml" % it)
        if os.path.exists(ti):
            return it, outdir
    raise SystemExit("no DUE output in " + outdir)


def costs_and_metrics(outdir, it):
    ti = os.path.join(outdir, "%03d" % it, "tripinfo_%03d.xml" % it)
    # duaIterate names its route output after the INPUT trips file's basename, not "all"
    import glob as _g
    cand = [f for f in _g.glob(os.path.join(outdir, "%03d" % it, "*_%03d.rou.xml.gz" % it))
            if not f.endswith(".rou.alt.xml.gz")]
    rou = cand[0]
    dmp = os.path.join(outdir, "%03d" % it, "dump_900.xml.gz")
    by = collections.defaultdict(list)
    dur = dd = 0.0
    n = 0
    bycls = collections.Counter()
    for t in ET.parse(ti).getroot().findall("tripinfo"):
        c = float(t.get("duration")) + float(t.get("departDelay"))
        by[PAIR[t.get("id")]].append(c)
        dur += float(t.get("duration"))
        dd += float(t.get("departDelay"))
        bycls[t.get("id").split("_")[0]] += 1
        n += 1
    C = {p: st.mean(v) for p, v in by.items()}
    m = dict(n_completed=n, VHT_h=round(dur / 3600.0, 2),
             VHT_incl_dd_h=round((dur + dd) / 3600.0, 2),
             mean_total_cost=round((dur + dd) / max(1, n), 2),
             by_class=dict(bycls))
    # interior cut-through veh-km from the equilibrium routes
    ikm = collections.Counter()
    for v in ET.parse(gzip.open(rou)).getroot().findall("vehicle"):
        es = v.find("route").get("edges").split()
        ikm[v.get("id").split("_")[0]] += sum(LEN.get(e, 0) for e in es if e in INTERIOR) / 1000.0
    m["cutthrough_vehkm"] = round(ikm["ee"] + ikm["bg"], 1)
    m["interior_vehkm_total"] = round(sum(ikm.values()), 1)
    # boundary arterial burden
    rv = rl = 0.0
    root = ET.parse(gzip.open(dmp)).getroot()
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            if e.get("id") in RING:
                if e.get("entered"):
                    rv += float(e.get("entered")) * LEN[e.get("id")] / 1000.0
                if e.get("timeLoss"):
                    rl += float(e.get("timeLoss"))
    m["ring_vehkm"] = round(rv, 1)
    m["ring_timeloss_vehh"] = round(rl / 3600.0, 2)
    return C, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--elasticity", type=float, required=True)
    a = ap.parse_args()
    v, e = a.variant, a.elasticity
    netf = os.path.join(NET, "%s.net.xml" % v)
    base_dir = os.path.join(RUNS, "elastic", "%s_e%s" % (v, ("%g" % e).replace(".", "p")))
    os.makedirs(base_dir, exist_ok=True)

    # reference costs C_A(p): variant A's own DUE equilibrium, full demand
    ref = json.load(open(os.path.join(ANA, "reference_costs_A.json")))

    keep = set(PAIR)
    Rk = {p: 1.0 for p in ref}     # damped retention state, starts at "keep everything"
    trace = []
    for k in range(OUTER + 1):
        tf = os.path.join(base_dir, "demand_%d.trips.xml" % k)
        write_trips(tf, keep)
        it, od = run_due(netf, tf, os.path.join(base_dir, "pass%d" % k), INNER)
        C, m = costs_and_metrics(od, it)
        m["pass"] = k
        m["n_demanded"] = len(keep)
        m["n_suppressed"] = len(PAIR) - len(keep)
        trace.append(m)
        print("  %s e=%g pass %d: demand=%d completed=%d VHT=%.1f cutkm=%.1f ringkm=%.0f"
              % (v, e, k, len(keep), m["n_completed"], m["VHT_h"],
                 m["cutthrough_vehkm"], m["ring_vehkm"]), flush=True)
        if k == OUTER:
            break
        # generalized-cost elasticity update, DAMPED with MSA on the retention vector.
        # An undamped best-response update oscillates: suppressing trips lowers the
        # equilibrium cost below the reference, retention snaps back to 1.0, demand
        # returns in full, cost rises again.  Verified directly -- an undamped run went
        # 6096 -> 4142 -> 5774 trips over three passes.  R_{k+1} = (1-a) R_k + a R_target.
        for p, cA in ref.items():
            cX = C.get(p, cA)
            tgt = min(1.0, (cX / cA) ** (-e)) if cA > 0 else 1.0
            Rk[p] = (1.0 - MSA_ALPHA) * Rk[p] + MSA_ALPHA * tgt
        keep = {vid for vid in PAIR if U[vid] <= Rk.get(PAIR[vid], 1.0)}

    out = dict(variant=v, elasticity=e, trace=trace,
               msa_alpha=MSA_ALPHA, inner_iterations=INNER, outer_passes=OUTER,
               retention_by_pair={p: round(Rk[p], 4) for p in ref})
    json.dump(out, open(os.path.join(ANA, "elastic_%s_e%s.json"
                                     % (v, ("%g" % e).replace(".", "p"))), "w"), indent=1)


if __name__ == "__main__":
    main()
