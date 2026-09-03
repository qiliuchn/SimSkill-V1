#!/usr/bin/env python3
"""Robustness check: does congestion-RESPONSIVE routing move the crossover?

The main sweep re-runs duarouter per network, which gives free-flow shortest
paths (routes adapt to the one-way TOPOLOGY but not to congestion).  Here every
vehicle carries a rerouting device and re-evaluates its route against measured
edge travel times, which is a cheap stand-in for an equilibrium assignment.
"""
import argparse, csv, os, subprocess, xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

def one(job):
    net, rou, out, seed, end = job
    os.makedirs(out, exist_ok=True)
    cmd = ["sumo", "-n", net, "-r", rou,
           "--device.rerouting.probability", "1",
           "--device.rerouting.period", "60",
           "--device.rerouting.adaptation-interval", "10",
           "--device.rerouting.adaptation-steps", "18",
           "--tripinfo-output", os.path.join(out, "tripinfo.xml"),
           "--seed", str(seed), "--end", str(end), "--time-to-teleport", "300",
           "--no-step-log", "--no-warnings",
           "--tripinfo-output.write-unfinished", "true"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return out, r.returncode

def agg(path):
    n = d = rl = stops = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            if float(el.get("arrival", -1)) >= 0:
                n += 1; d += float(el.get("duration")); rl += float(el.get("routeLength"))
                stops += float(el.get("waitingCount", 0))
            el.clear()
    return dict(n_arrived=n, mean_duration_s=d / max(n, 1),
                mean_speed_ms=rl / d if d else 0, mean_stops=stops / max(n, 1),
                mean_routelen_m=rl / max(n, 1))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True); p.add_argument("--nets", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--demands", type=int, nargs="+", required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--variants", nargs="+", default=["twoway", "oneway_fair"])
    p.add_argument("--end", type=float, default=12000); p.add_argument("--jobs", type=int, default=8)
    a = p.parse_args()
    jobs = [(os.path.join(a.nets, v, "%s.net.xml" % v),
             os.path.join(a.work, "d%d_s%d" % (d, s), "%s.rou.xml" % v),
             os.path.join(a.outdir, "d%d_s%d_%s" % (d, s, v)), s, a.end)
            for d in a.demands for s in a.seeds for v in a.variants]
    os.makedirs(a.outdir, exist_ok=True)
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for o, rc in ex.map(one, jobs):
            if rc: print("FAIL", o)
    rows = []
    for d in a.demands:
        for s in a.seeds:
            for v in a.variants:
                f = os.path.join(a.outdir, "d%d_s%d_%s" % (d, s, v), "tripinfo.xml")
                if os.path.exists(f):
                    rows.append(dict(demand=d, seed=s, variant=v, **agg(f)))
    out = os.path.join(a.outdir, "rerouting_runs.csv")
    with open(out, "w") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader()
        for r in rows: w.writerow(r)
    print("wrote", out)
