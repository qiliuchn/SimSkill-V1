#!/usr/bin/env python3
"""
STEP 3/4 -- compute the dynamic user equilibrium with duaIterate.py for one
(variant, demand-level) case, then run a "simulation of record" on the converged routes.

Per the compute-dynamic-user-equilibrium skill:
  * duaIterate.py lives in $SUMO_HOME/tools/assign/ (not tools/ directly)
  * the convergence trace is built by parsing the numbered iteration subdirs 000/, 001/, ...
  * a single large --aggregation window is used so the router's edge weights are
    period-averaged -> a static-like equilibrium, comparable to textbook Braess.

Demand, seed and departure schedule are byte-identical across the two variants: the same
<flow> definition is expanded deterministically by duarouter, and the same sumo seed is used.
"""
import argparse
import glob
import gzip
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SUMO = shutil.which("sumo")
DUAITERATE = os.path.join(os.environ["SUMO_HOME"], "tools", "assign", "duaIterate.py")

# route classification markers, checked in this order
MARKERS = [("zigzag", "AB"), ("upper_SAT", "AT"), ("lower_SBT", "SB")]


def classify(edges):
    s = edges.split()
    for label, m in MARKERS:
        if m in s:
            return label
    return "other"


def write_demand(path, veh_per_hour, load_s):
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write(f'  <flow id="v" begin="0" end="{load_s}" vehsPerHour="{veh_per_hour}" '
                f'from="S_in" to="T_out" departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')


def run_duaiterate(net, demand, work, end_s, last_step, seed, logit=False,
                   conv_iters=5, conv_dev=0.002, logit_theta=None):
    os.makedirs(work, exist_ok=True)
    cmd = [sys.executable, DUAITERATE, "-n", os.path.abspath(net), "-F", os.path.abspath(demand),
           "-e", str(end_s), "-a", str(end_s),          # one weight-aggregation window
           "-l", str(last_step),
           "--convergence-iterations", str(conv_iters),
           "--max-convergence-deviation", str(conv_dev),
           "--time-to-teleport=-1",
           "--disable-warnings",
           "sumo--seed", str(seed)]
    if logit:
        cmd.insert(-2, "--logit")
        if logit_theta is not None:
            cmd[-2:-2] = ["--logittheta", str(logit_theta)]
    with open(os.path.join(work, "duaIterate.cmd"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
    with open(os.path.join(work, "duaIterate.stdout"), "w") as f:
        f.write(r.stdout)
    with open(os.path.join(work, "duaIterate.stderr"), "w") as f:
        f.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"duaIterate failed in {work}:\n{r.stderr[-4000:]}")
    return work


def iter_dirs(work):
    return sorted(d for d in glob.glob(os.path.join(work, "[0-9][0-9][0-9]")) if os.path.isdir(d))


def load_routes_of_iter(it_dir):
    """{vehID: (route-label, edges)} for the routes actually simulated in this iteration."""
    cands = [p for p in glob.glob(os.path.join(it_dir, "*.rou.xml")) if ".alt." not in p]
    cands += [p for p in glob.glob(os.path.join(it_dir, "*.rou.xml.gz")) if ".alt." not in p]
    if not cands:
        return {}
    p = cands[0]
    fh = gzip.open(p) if p.endswith(".gz") else open(p, "rb")
    with fh:
        root = ET.parse(fh).getroot()
    out = {}
    for v in root.iter("vehicle"):
        r = v.find("route")
        if r is None:
            rd = v.find("routeDistribution")
            if rd is not None:
                r = rd.findall("route")[-1]
        if r is not None:
            out[v.get("id")] = (classify(r.get("edges", "")), r.get("edges", ""))
    return out


def load_trips(p):
    out = {}
    for t in ET.parse(p).getroot().iter("tripinfo"):
        d = float(t.get("duration"))
        dd = float(t.get("departDelay", 0.0))
        out[t.get("id")] = {"duration": d, "departDelay": dd, "total": d + dd,
                            "timeLoss": float(t.get("timeLoss", 0.0))}
    return out


def convergence_trace(work):
    trace, prev = [], None
    for it_dir in iter_dirs(work):
        routes = load_routes_of_iter(it_dir)
        tf = glob.glob(os.path.join(it_dir, "tripinfo_*.xml"))
        if not routes or not tf:
            continue
        trips = load_trips(tf[0])
        ids = [i for i in trips]
        if not ids:
            continue
        n = len(ids)
        chg = (100.0 * sum(1 for k in routes if prev and prev.get(k) != routes[k][0]) / len(routes)) if prev else float("nan")
        prev = {k: v[0] for k, v in routes.items()}
        row = {"iteration": int(os.path.basename(it_dir)),
               "n_arrived": n,
               "mean_duration_s": round(sum(trips[i]["duration"] for i in ids) / n, 2),
               "mean_total_s": round(sum(trips[i]["total"] for i in ids) / n, 2),
               "mean_departDelay_s": round(sum(trips[i]["departDelay"] for i in ids) / n, 2),
               "route_change_pct": (round(chg, 2) if chg == chg else "")}
        for label, _ in MARKERS:
            row[f"n_{label}"] = sum(1 for v in routes.values() if v[0] == label)
        trace.append(row)
    return trace


def simulate_of_record(net, routes, out_dir, end_s, seed):
    """Re-simulate the converged route set with full outputs (the simulation of record)."""
    os.makedirs(out_dir, exist_ok=True)
    add = os.path.join(out_dir, "edgedata.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n  <edgeData id="whole" file="edgedata.xml" begin="0" end="%d" '
                'excludeEmpty="true"/>\n</additional>\n' % end_s)
    cmd = [SUMO, "-n", os.path.abspath(net), "-r", os.path.abspath(routes), "-a", add,
           "--no-step-log", "true", "--seed", str(seed), "--time-to-teleport", "-1",
           "--end", str(end_s),
           "--tripinfo-output", os.path.join(out_dir, "tripinfo.xml"),
           "--vehroute-output", os.path.join(out_dir, "vehroutes.xml"),
           "--vehroute-output.exit-times", "true",
           "--summary-output", os.path.join(out_dir, "summary.xml"),
           "--statistic-output", os.path.join(out_dir, "stats.xml"),
           "--duration-log.statistics", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=out_dir)
    with open(os.path.join(out_dir, "sumo.stderr"), "w") as f:
        f.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"simulation of record failed:\n{r.stderr}")
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--demand", type=int, required=True, help="total S->T demand, veh/h")
    ap.add_argument("--load-s", type=int, default=1800)
    ap.add_argument("--end-s", type=int, default=7200)
    ap.add_argument("--last-step", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--logit", action="store_true")
    ap.add_argument("--conv-iters", type=int, default=5)
    ap.add_argument("--conv-dev", type=float, default=0.002)
    ap.add_argument("--logit-theta", type=float, default=None)
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    demand = os.path.join(a.work, "demand.flows.xml")
    write_demand(demand, a.demand, a.load_s)
    dua = os.path.join(a.work, "dua")
    run_duaiterate(a.net, demand, dua, a.end_s, a.last_step, a.seed, a.logit,
                   a.conv_iters, a.conv_dev, a.logit_theta)

    trace = convergence_trace(dua)
    last_dir = iter_dirs(dua)[-1]
    cands = [p for p in glob.glob(os.path.join(last_dir, "*.rou.xml*")) if ".alt." not in p]
    final_rou = cands[0]
    conv = os.path.join(a.work, "converged.rou.xml")
    if final_rou.endswith(".gz"):
        with gzip.open(final_rou, "rb") as fi, open(conv, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    else:
        shutil.copy(final_rou, conv)
    rec = simulate_of_record(a.net, conv,
                             os.path.join(a.work, "record"), a.end_s, a.seed)
    with open(os.path.join(a.work, "convergence.json"), "w") as f:
        json.dump({"trace": trace, "final_iteration": os.path.basename(last_dir)}, f, indent=2)
    print(f"[{os.path.basename(a.work)}] iterations={len(trace)} final={os.path.basename(last_dir)} "
          f"record={rec}")


if __name__ == "__main__":
    main()
