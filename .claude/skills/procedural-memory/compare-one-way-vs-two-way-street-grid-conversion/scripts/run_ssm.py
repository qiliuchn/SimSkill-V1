#!/usr/bin/env python3
"""Surrogate-safety (SSM) side-study: does removing intersection conflict
points by one-way conversion show up as fewer measurable conflicts?

Per the analyze-intersection-safety-with-ssm skill, `device.ssm.file` is passed
on the sumo COMMAND LINE (not as a vType param), because duarouter re-embeds the
vType into its output route file and can path-mangle a relative value there.
Conflicts are classified by the SSM `type` code: 2/3/18 rear-end, 6/7/8/19
merging, 10-17 crossing/angle, 111 actual collision.
"""
import argparse
import csv
import os
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

REAR = {2, 3, 18}
MERGE = {6, 7, 8, 19}
CROSS = set(range(10, 18))


def one(job):
    net, rou, outdir, seed, end = job
    os.makedirs(outdir, exist_ok=True)
    cmd = ["sumo", "-n", net, "-r", rou,
           "--device.ssm.probability", "1",
           "--device.ssm.measures", "TTC DRAC PET",
           "--device.ssm.thresholds", "3.0 3.0 2.0",
           "--device.ssm.range", "50.0",
           "--device.ssm.extratime", "5.0",
           "--device.ssm.file", os.path.join(outdir, "ssm.xml"),
           "--device.ssm.write-positions", "false",
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--seed", str(seed), "--end", str(end),
           "--time-to-teleport", "300", "--no-step-log", "--no-warnings",
           "--tripinfo-output.write-unfinished", "true"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    return outdir, r.returncode, r.stdout[-500:]


def parse(path):
    n_veh, cnt = 0, Counter()
    ttc_low = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "conflict":
            t = None
            for m in el:
                if m.get("type") not in (None, "NA"):
                    try:
                        t = int(float(m.get("type")))
                    except ValueError:
                        pass
                if m.tag == "minTTC" and m.get("value") not in (None, "NA"):
                    if float(m.get("value")) < 1.5:
                        ttc_low += 1
            cnt["all"] += 1
            if t in REAR:
                cnt["rear_end"] += 1
            elif t in MERGE:
                cnt["merging"] += 1
            elif t in CROSS:
                cnt["crossing"] += 1
            elif t == 111:
                cnt["collision"] += 1
            else:
                cnt["other"] += 1
            el.clear()
        elif el.tag == "globalMeasures":
            n_veh += 1
            el.clear()
    cnt["ttc_lt_1p5"] = ttc_low
    return n_veh, cnt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True)
    p.add_argument("--nets", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--demand", type=int, required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--variants", nargs="+",
                   default=["twoway", "oneway_fair", "oneway_naive"])
    p.add_argument("--end", type=float, default=12000)
    p.add_argument("--jobs", type=int, default=6)
    a = p.parse_args()

    jobs = []
    for s in a.seeds:
        cell = os.path.join(a.work, "d%d_s%d" % (a.demand, s))
        for v in a.variants:
            jobs.append((os.path.join(a.nets, v, "%s.net.xml" % v),
                         os.path.join(cell, "%s.rou.xml" % v),
                         os.path.join(a.outdir, "%s_s%d" % (v, s)), s, a.end))
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for od, rc, log in ex.map(one, jobs):
            if rc != 0:
                print("FAIL", od, log)

    rows = []
    for s in a.seeds:
        for v in a.variants:
            f = os.path.join(a.outdir, "%s_s%d" % (v, s), "ssm.xml")
            if not os.path.exists(f):
                continue
            nv, c = parse(f)
            # normalise by vehicle-km actually driven
            vkm = 0.0
            for _, el in ET.iterparse(os.path.join(a.outdir, "%s_s%d" % (v, s),
                                                   "tripinfo.xml"),
                                      events=("end",)):
                if el.tag == "tripinfo":
                    vkm += float(el.get("routeLength", 0)) / 1000.0
                    el.clear()
            rows.append(dict(variant=v, seed=s, n_vehicles=nv, veh_km=vkm,
                             **{k: c[k] for k in ("all", "rear_end", "merging",
                                                  "crossing", "collision",
                                                  "other", "ttc_lt_1p5")},
                             conflicts_per_100vkm=100.0 * c["all"] / vkm if vkm else 0,
                             crossing_per_100vkm=100.0 * c["crossing"] / vkm if vkm else 0))
    out = os.path.join(a.outdir, "ssm_summary.csv")
    with open(out, "w") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", out)


if __name__ == "__main__":
    main()
