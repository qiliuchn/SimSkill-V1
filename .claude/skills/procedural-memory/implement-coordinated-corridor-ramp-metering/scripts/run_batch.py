#!/usr/bin/env python3
"""Parallel batch runner for the corridor ramp-metering experiment.

Every (seed, demand) pair gets ONE route file, reused byte-for-byte by every
control arm -> Common Random Numbers. Every run gets its OWN output directory so
detector files can never clobber each other (the documented
implement-alinea-ramp-metering data-integrity gotcha).
"""
import argparse
import itertools
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(ROOT, "outputs", "runs2")
NETS = os.path.join(ROOT, "outputs", "net")
ROU = os.path.join(ROOT, "outputs", "routes")
SUMO_HOME = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"

ARMS = ["nocontrol", "fixed", "alinea", "bnalinea", "coord", "coord_flush", "negctrl"]
DEMANDS = [0.55, 0.65, 0.75, 0.85, 0.95, 1.05]
SEEDS = list(range(1, 9))
END = 9000


def net_for(stor3):
    """compiled net for a given r3 storage length (r1/r2 fixed)"""
    d = os.path.join(NETS, f"s3_{int(stor3)}")
    if not os.path.exists(os.path.join(d, "corridor.net.xml")):
        from build_corridor import build
        build(d, [280.0, 220.0, float(stor3)])
    return os.path.join(d, "corridor.net.xml")


def route_for(seed, demand):
    p = os.path.join(ROU, f"s{seed}_d{int(round(demand*100))}.rou.xml")
    if not os.path.exists(p):
        from gen_demand import gen
        gen(seed, demand, p)
    return p


def one(job):
    tag, arm, seed, demand, stor3, extra = job
    d = os.path.join(RUNS, tag)
    os.makedirs(d, exist_ok=True)
    done = os.path.join(d, "ctl.json")
    if os.path.exists(done) and os.path.getsize(done) > 1000:
        return tag, "cached"
    from gen_additional import build as build_add
    net = net_for(stor3)
    add = build_add(net, d, period=30)
    cmd = [sys.executable, os.path.join(HERE, "corridor_control.py"),
           "--net", net, "--routes", route_for(seed, demand), "--additional", add,
           "--arm", arm, "--seed", str(seed), "--demand", str(demand),
           "--end", str(extra.pop("end", END)),
           "--tripinfo", os.path.join(d, "tripinfo.xml"),
           "--summary", os.path.join(d, "summary.xml"),
           "--outjson", done]
    for k, v in extra.items():
        cmd += [f"--{k}", str(v)]
    env = dict(os.environ, SUMO_HOME=SUMO_HOME)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=HERE)
    open(os.path.join(d, "stderr.txt"), "w").write(r.stderr[-200000:])
    if r.returncode != 0:
        return tag, "FAIL:" + r.stderr[-600:]
    return tag, "ok"


def jobs():
    J = []
    # ---- core matrix: arms x demand x seed (r3 storage = 160 m) ----
    for arm, dem, sd in itertools.product(ARMS, DEMANDS, SEEDS):
        if arm == "negctrl" and dem in (0.55, 0.65):
            continue
        J.append((f"core/{arm}_d{int(dem*100)}_s{sd}", arm, sd, dem, 160, {}))
    # ---- H2: ramp-storage sweep at the bottleneck-adjacent ramp ----
    for st in (80, 320, 640):
        for arm in ("alinea", "coord", "nocontrol"):
            for sd in SEEDS:
                J.append((f"stor/{arm}_st{st}_s{sd}", arm, sd, 0.95, st, {}))
    # ---- H3: queue-override strictness ----
    # (w_flush = 1.20 -- "override can never fire" -- is EXACTLY the `coord` arm,
    #  so the core coord runs are reused as that point rather than re-simulated)
    for wf in (0.70,):
        for dem in (0.85, 1.05):
            for sd in SEEDS:
                J.append((f"flush/wf{int(wf*100)}_d{int(dem*100)}_s{sd}",
                          "coord_flush", sd, dem, 160, {"w-flush": wf}))
    # ---- H6: activation-threshold / hysteresis sweep on the master ----
    for on, off in ((7.5, 6.0), (12.0, 9.0), (20.0, 15.0)):
        for sd in SEEDS:
            J.append((f"act/on{int(on*10)}_s{sd}", "coord", sd, 0.95, 160,
                      {"o-on-bn": on, "o-off-bn": off}))
    # ---- teleport-artifact sensitivity ----
    for ttt in (120, -1):
        for arm in ("nocontrol", "coord"):
            for sd in (1, 2, 3):
                J.append((f"tele/{arm}_ttt{ttt}_s{sd}", arm, sd, 0.95, 160, {"ttt": ttt}))
    return J


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    os.makedirs(ROU, exist_ok=True)
    J = jobs()
    if a.only:
        J = [j for j in J if j[0].startswith(a.only)]
    # pre-generate nets and routes serially (avoids races)
    for st in (80, 160, 320, 640):
        net_for(st)
    for dem, sd in itertools.product(DEMANDS + [0.55, 0.65], SEEDS):
        route_for(sd, dem)
    print(f"{len(J)} jobs", flush=True)
    nfail = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, (tag, st) in enumerate(ex.map(one, J)):
            if st.startswith("FAIL"):
                nfail += 1
                print(f"[{i+1}/{len(J)}] {tag}: {st}", flush=True)
            elif (i + 1) % 10 == 0:
                print(f"[{i+1}/{len(J)}] {tag}: {st}", flush=True)
    print("failures:", nfail)
