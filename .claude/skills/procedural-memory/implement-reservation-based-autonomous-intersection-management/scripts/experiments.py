#!/usr/bin/env python3
"""
Builds the job lists for every stage of the AIM study and runs them through
batch.py.  Common Random Numbers: for a given (demand, seed) the vehicle
population is byte-identical across every controller/policy/penetration arm
(demand.py), and `sumo --seed` is set to the same value in every arm.

Stages
  demand   generate all route files
  plans    Webster-sized fixed-time plans (p2 / p4) across the cycle grid
  s0       fixed-time cycle-length sweep  -> picks the "well-tuned" fixed plan
  s1       main comparison: fixed / actuated / maxpressure / aim-fcfs / aim-batch
  s2       AIM safety-buffer negative control (degradation toward all-way stop)
  s3       H2: HDV penetration sweep with the hybrid virtual-signal fallback
  s4       H3: unbalanced 80/20 demand, FCFS vs batch
  s5       H4: SSM-instrumented runs
  s6       communication realism: latency and position-noise sweeps
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
NET_S = "net/inter_static.net.xml"
NET_A = "net/inter_actuated.net.xml"
NET_AWS = "net/inter_allwaystop.net.xml"
CONF = "net/conflicts.json"
SAT = "runs/satflow/saturation.txt"

DEMANDS = [300, 600, 900, 1200, 1500]
SEEDS = [101, 102, 103, 104, 105]
TEND = 900.0          # demand loading period
SIMEND = 3600.0       # hard simulation end (drain)
CYCLES = [40, 50, 60, 70, 80, 90, 110, 130]
PENETRATIONS = [0.0, 0.05, 0.10, 0.25, 0.50, 1.00]
BUFFERS = [0.2, 0.6, 1.5, 3.0, 5.0, 8.0]
LATENCIES = [0.0, 0.2, 0.4, 0.6, 1.0, 1.5, 2.0, 3.0]
NOISES = [0.0, 1.0, 2.5, 5.0, 8.0, 12.0, 20.0]


def sh(cmd):
    p = subprocess.run(cmd, shell=True, cwd=BASE, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-3000:], p.stderr[-3000:])
        sys.exit("failed: " + cmd)
    return p.stdout


def rou(d, s, tag=""):
    return "demand/d%d_s%d%s.rou.xml" % (d, s, tag)


def meta(d, s, tag=""):
    return "demand/d%d_s%d%s.rou.meta.json" % (d, s, tag)


def gen_demand():
    os.makedirs(os.path.join(BASE, "demand"), exist_ok=True)
    for d in DEMANDS:
        for s in SEEDS:
            sh("python3 scripts/demand.py --demand %d --seed %d --t-end %d --out %s"
               % (d, s, TEND, rou(d, s)))
            sh("python3 scripts/demand.py --demand %d --seed %d --t-end %d --ssm --out %s"
               % (d, s, TEND, rou(d, s, "_ssm")))
    # H3: unbalanced 80/20 major(N,S) / minor(E,W)
    for d in DEMANDS:
        for s in SEEDS:
            sh("python3 scripts/demand.py --demand %d --seed %d --t-end %d "
               "--weights N=1.6,S=1.6,E=0.4,W=0.4 --out %s" % (d, s, TEND, rou(d, s, "_ub")))


def gen_plans():
    os.makedirs(os.path.join(BASE, "net/plans"), exist_ok=True)
    info = {}
    for d in DEMANDS:
        for stru in ("p2", "p4"):
            o = sh("python3 scripts/plans.py --conflicts %s --sat %s --structure %s "
                   "--demand %d --out net/plans/%s_d%d_webster.xml"
                   % (CONF, SAT, stru, d, stru, d))
            info["%s_%d_webster" % (stru, d)] = json.loads(o)
            for c in CYCLES:
                sh("python3 scripts/plans.py --conflicts %s --sat %s --structure %s "
                   "--demand %d --cycle %d --out net/plans/%s_d%d_c%d.xml"
                   % (CONF, SAT, stru, d, c, stru, d, c))
    json.dump(info, open(os.path.join(BASE, "net/plans/webster.json"), "w"), indent=1)
    return info


def base(d, s, ctrl, out, **kw):
    j = dict(net=NET_S, routes=rou(d, s), controller=ctrl, outdir=out,
             seed=s, end=SIMEND, meta=meta(d, s), conflicts=CONF)
    j.update(kw)
    return j


def jobs_s0():
    J = []
    for d in DEMANDS:
        for stru in ("p2", "p4"):
            for c in CYCLES:
                for s in SEEDS[:3]:
                    J.append(dict(net=NET_S, routes=rou(d, s), controller="fixed",
                                  additional="net/plans/%s_d%d_c%d.xml" % (stru, d, c),
                                  outdir="runs/s0/%s_d%d_c%d_s%d" % (stru, d, c, s),
                                  seed=s, end=SIMEND))
    return J


def jobs_s1(best_plan):
    J = []
    for d in DEMANDS:
        for s in SEEDS:
            J.append(dict(net=NET_S, routes=rou(d, s), controller="fixed",
                          additional=best_plan[d], meta=meta(d, s),
                          outdir="runs/s1/fixed_d%d_s%d" % (d, s), seed=s, end=SIMEND))
            J.append(dict(net=NET_A, routes=rou(d, s), controller="actuated",
                          meta=meta(d, s),
                          outdir="runs/s1/actuated_d%d_s%d" % (d, s), seed=s, end=SIMEND))
            J.append(base(d, s, "maxpressure", "runs/s1/maxpressure_d%d_s%d" % (d, s)))
            for pol in ("fcfs", "batch"):
                J.append(base(d, s, "aim", "runs/s1/aim%s_d%d_s%d" % (pol, d, s),
                              policy=pol))
            J.append(dict(net=NET_AWS, routes=rou(d, s), controller="allwaystop",
                          meta=meta(d, s),
                          outdir="runs/s1/awsc_d%d_s%d" % (d, s), seed=s, end=SIMEND))
    return J


def jobs_s2():
    J = []
    for d in (300, 900):
        for b in BUFFERS:
            for s in SEEDS[:3]:
                J.append(base(d, s, "aim", "runs/s2/buf%.1f_d%d_s%d" % (b, d, s),
                              policy="batch", buffer=b))
    return J


def jobs_s3():
    J = []
    for d in (600, 1200):
        for p in PENETRATIONS:
            for s in SEEDS:
                J.append(base(d, s, "aim", "runs/s3/pen%.2f_d%d_s%d" % (p, d, s),
                              policy="batch", penetration=p))
    return J


def jobs_s4():
    J = []
    for d in DEMANDS:
        for s in SEEDS[:3]:
            for pol in ("fcfs", "batch"):
                J.append(dict(net=NET_S, routes=rou(d, s, "_ub"),
                              meta=meta(d, s, "_ub"), conflicts=CONF,
                              controller="aim", policy=pol,
                              outdir="runs/s4/aim%s_d%d_s%d" % (pol, d, s),
                              seed=s, end=SIMEND))
            J.append(dict(net=NET_A, routes=rou(d, s, "_ub"), meta=meta(d, s, "_ub"),
                          controller="actuated",
                          outdir="runs/s4/actuated_d%d_s%d" % (d, s), seed=s, end=SIMEND))
    return J


def jobs_s5(best_plan):
    J = []
    for d in (600, 1200):
        for s in SEEDS[:3]:
            r, m = rou(d, s, "_ssm"), meta(d, s, "_ssm")
            J.append(dict(net=NET_S, routes=r, controller="fixed", meta=m,
                          additional=best_plan[d],
                          ssm_out="ssm.xml",
                          outdir="runs/s5/fixed_d%d_s%d" % (d, s), seed=s, end=SIMEND))
            J.append(dict(net=NET_A, routes=r, controller="actuated", meta=m,
                          ssm_out="ssm.xml",
                          outdir="runs/s5/actuated_d%d_s%d" % (d, s), seed=s, end=SIMEND))
            for pol in ("fcfs", "batch"):
                J.append(dict(net=NET_S, routes=r, meta=m, conflicts=CONF,
                              controller="aim", policy=pol, ssm_out="ssm.xml",
                              outdir="runs/s5/aim%s_d%d_s%d" % (pol, d, s),
                              seed=s, end=SIMEND))
    return J


def jobs_s6():
    J = []
    d = 900
    for lat in LATENCIES:
        for s in SEEDS[:3]:
            J.append(base(d, s, "aim", "runs/s6/lat%.1f_d%d_s%d" % (lat, d, s),
                          policy="batch", latency=lat))
    for nz in NOISES:
        for s in SEEDS[:3]:
            J.append(base(d, s, "aim", "runs/s6/noise%.1f_d%d_s%d" % (nz, d, s),
                          policy="batch", pos_noise=nz))
    return J


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--best-plan", default="")
    a = ap.parse_args()

    if a.stage == "demand":
        gen_demand()
        print("demand generated")
        return
    if a.stage == "plans":
        print(json.dumps(gen_plans(), indent=1))
        return

    bp = {}
    if a.best_plan and os.path.exists(os.path.join(BASE, a.best_plan)):
        bp = {int(k): v for k, v in json.load(open(os.path.join(BASE, a.best_plan))).items()}

    J = {"s0": jobs_s0, "s2": jobs_s2, "s3": jobs_s3, "s4": jobs_s4, "s6": jobs_s6}
    if a.stage in J:
        jobs = J[a.stage]()
    elif a.stage == "s1":
        jobs = jobs_s1(bp)
    elif a.stage == "s5":
        jobs = jobs_s5(bp)
    else:
        sys.exit("unknown stage")

    jf = os.path.join("/tmp", "jobs_%s.json" % a.stage)
    json.dump(jobs, open(jf, "w"))
    print("stage %s: %d jobs" % (a.stage, len(jobs)))
    subprocess.run([sys.executable, os.path.join(HERE, "batch.py"),
                    "--jobs", jf, "--workers", str(a.workers)], cwd=BASE)


if __name__ == "__main__":
    main()
