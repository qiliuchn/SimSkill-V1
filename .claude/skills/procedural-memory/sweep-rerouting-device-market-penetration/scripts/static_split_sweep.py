#!/usr/bin/env python3
"""Control / reference experiment: STATIC route split, no rerouting device at all.

A fixed fraction of vehicles is assigned the alternate route at departure and
never re-decides.  Sweeping that fraction does two things the reactive sweep
cannot:

  * it measures the alternate's real capacity and the shape of the
    total-travel-time-vs-split curve, i.e. the best a perfectly coordinated
    planner could do with this network and this incident (a system-optimum
    reference), and
  * it gives an upper bound on how much any information system could possibly
    help, so the reactive-rerouting results can be read against something other
    than the do-nothing baseline.

Also used to pick a demand level at which the incident queue stores on the
main-exclusive edge AC instead of spilling back over the diverge junction A.
"""
import argparse
import os
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

MAIN = "OA AC CB BD"
ALT = "OA AP PB BD"


def write_routes(path, vph, horizon, alt_share, seed):
    import random
    n = int(round(vph * horizon / 3600.0))
    rng = random.Random(20260731)
    h = horizon / float(n)
    ts = sorted(min(horizon - .1, max(0., (i + .5) * h + rng.uniform(-.45 * h, .45 * h))) for i in range(n))
    rng2 = random.Random(1000000 + seed)
    u = [rng2.random() for _ in range(n)]
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        f.write('    <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" '
                'length="5.0" minGap="2.5" maxSpeed="45" speedDev="0.1"/>\n')
        f.write('    <route id="main" edges="%s"/>\n    <route id="alt" edges="%s"/>\n' % (MAIN, ALT))
        for i, t in enumerate(ts):
            f.write('    <vehicle id="v%04d" type="car" route="%s" depart="%.2f" '
                    'departLane="best" departSpeed="max"/>\n'
                    % (i, "alt" if u[i] < alt_share else "main", t))
        f.write('</routes>\n')


def one(job):
    W, net, add, vph, share, seed = job
    d = os.path.join(W, "vph%d_s%03d_seed%d" % (vph, int(round(share * 100)), seed))
    os.makedirs(d, exist_ok=True)
    write_routes(os.path.join(d, "d.rou.xml"), vph, 3600, share, seed)
    with open(os.path.join(d, "ed.add.xml"), "w") as f:
        f.write('<additional><edgeData id="ed" file="edgedata.xml" period="60" excludeEmpty="false"/></additional>')
    r = subprocess.run(["sumo", "-n", net, "-r", os.path.join(d, "d.rou.xml"),
                        "-a", add + "," + os.path.join(d, "ed.add.xml"),
                        "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
                        "--begin", "0", "--end", "12000", "--time-to-teleport", "300",
                        "--no-step-log", "true", "--seed", str(seed)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return (vph, share, seed, None, None, None, None, None)
    tt = []
    for t in ET.parse(os.path.join(d, "tripinfo.xml")).getroot().findall("tripinfo"):
        tt.append(float(t.get("duration")) + float(t.get("departDelay")))
    oa_minv, oa_maxocc = 1e9, 0.0
    for iv in ET.parse(os.path.join(d, "edgedata.xml")).getroot().findall("interval"):
        tb = float(iv.get("begin"))
        if not (900 <= tb < 3000):
            continue
        for ed in iv.findall("edge"):
            if ed.get("id") == "OA":
                s = float(ed.get("speed") or 0)
                if float(ed.get("entered") or 0) > 0:
                    oa_minv = min(oa_minv, s)
                oa_maxocc = max(oa_maxocc, float(ed.get("occupancy") or 0))
    return (vph, share, seed, len(tt), sum(tt) / len(tt), sum(tt),
            oa_minv, oa_maxocc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--incident-add", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vph", type=int, nargs="+", default=[2500])
    ap.add_argument("--shares", type=float, nargs="+",
                    default=[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1.0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--jobs", type=int, default=9)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    jobs = [(os.path.abspath(a.workdir), os.path.abspath(a.net), os.path.abspath(a.incident_add),
             v, s, sd) for v in a.vph for s in a.shares for sd in a.seeds]
    rows = []
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for r in ex.map(one, jobs):
            rows.append(r)
            print("vph=%d altshare=%.2f seed=%d  n=%s meanTT=%s totTT=%s  OA_minv=%s OA_maxocc=%s"
                  % (r[0], r[1], r[2], r[3],
                     "%.1f" % r[4] if r[4] else "ERR", "%.0f" % r[5] if r[5] else "-",
                     "%.1f" % r[6] if r[6] and r[6] < 1e8 else "-",
                     "%.1f" % r[7] if r[7] is not None else "-"))
    with open(a.out, "w") as f:
        f.write("vph,alt_share,seed,n_arrived,mean_total_tt_s,sum_total_tt_s,OA_min_speed_mps,OA_max_occupancy_pct\n")
        for r in rows:
            f.write(",".join("" if x is None else (("%.4f" % x) if isinstance(x, float) else str(x)) for x in r) + "\n")
    print("wrote " + a.out)


if __name__ == "__main__":
    main()
