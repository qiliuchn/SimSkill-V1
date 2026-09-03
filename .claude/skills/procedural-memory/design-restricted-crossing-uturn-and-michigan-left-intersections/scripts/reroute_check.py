#!/usr/bin/env python3
"""
Robustness check on the single-shot-duarouter assumption
(see semantic-memory/dynamic-user-equilibrium-and-wardrop).

Each variant is routed once, against free-flow weights, so every OD pair collapses
to a single path.  That is CORRECT for the alternatives (the detour is the only
legal path) but it also freezes the CONVENTIONAL design onto its direct paths --
and at high demand a conventional-network driver might genuinely prefer the same
median-U-turn detour the RCUT forces on them.  If so, the conventional baseline is
being handicapped and the comparison is unfair in the OTHER direction.

Test: re-run the conventional design with a rerouting device on every vehicle
(congestion-aware, 60 s edge-weight updates) and count how many vehicles
voluntarily choose a U-turn crossover.
"""
import itertools
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run as R  # noqa: E402

CELLS = [(400, 3600, 0.50), (400, 6000, 0.30), (400, 6000, 0.50), (100, 4800, 0.30)]
UT = {("W_J_XW", "E_XW_J"), ("E_J_XE", "W_XE_J")}


def one(kw):
    v, D, Q, m, seed = kw
    netf, rou, rd, plan = R.ensure_plan(v, D, Q, m)
    d = os.path.join(ROOT, "runs_reroute", f"rr_{v}_D{D}_Q{Q}_m{int(m*100)}_s{seed}")
    os.makedirs(d, exist_ok=True)
    add = os.path.join(d, "add.xml")
    R.write_additional(add, netf, plan, d)
    cmd = ["sumo", "-n", netf, "-r", rou, "-a", add, "--begin", "0", "--end", str(R.SIM_END),
           "--step-length", "0.5", "--seed", str(seed), "--no-step-log", "true",
           "--time-to-teleport", "300",
           "--device.rerouting.probability", "1", "--device.rerouting.period", "60",
           "--device.rerouting.adaptation-steps", "10",
           "--vehroute-output", os.path.join(d, "vehroute.xml"),
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished", "true",
           "--summary-output", os.path.join(d, "summary.xml")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=d)
    if r.returncode != 0:
        return {"cell": kw, "error": r.stderr[-800:]}
    n_ut, n = 0, 0
    for _, veh in ET.iterparse(os.path.join(d, "vehroute.xml"), events=("end",)):
        if veh.tag != "vehicle":
            continue
        n += 1
        rt = veh.find("route") if veh.find("route") is not None else veh.find("routeDistribution")
        edges = []
        if rt is not None and rt.get("edges"):
            edges = rt.get("edges").split()
        else:
            rs = veh.findall(".//route")
            if rs:
                edges = rs[-1].get("edges", "").split()
        if any(p in UT for p in zip(edges, edges[1:])):
            n_ut += 1
        veh.clear()
    tot = dur = 0.0
    cnt = 0
    for _, t in ET.iterparse(os.path.join(d, "tripinfo.xml"), events=("end",)):
        if t.tag == "tripinfo" and float(t.get("arrival")) >= 0:
            cnt += 1
            dur += float(t.get("duration")) + float(t.get("departDelay"))
            t.clear()
    return {"variant": v, "D": D, "Q": Q, "m": m, "seed": seed, "n_veh": n,
            "n_chose_uturn": n_ut, "share_uturn": n_ut / max(n, 1),
            "completed": cnt, "mean_totaltime_s": dur / max(cnt, 1)}


if __name__ == "__main__":
    jobs = [("conv", D, Q, m, s) for (D, Q, m) in CELLS for s in (1, 2, 3)]
    with Pool(6) as p:
        res = list(p.imap_unordered(one, jobs))
    with open(os.path.join(ROOT, "results", "reroute_check.json"), "w") as f:
        json.dump(res, f, indent=1)
    for r in sorted(res, key=lambda x: (x.get("D", 0), x.get("Q", 0), x.get("m", 0), x.get("seed", 0))):
        print(r)
