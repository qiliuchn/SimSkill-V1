#!/usr/bin/env python3
"""
Inner loop: for a given project subset (bit mask) build the network, compute a
dynamic user equilibrium with duaIterate.py (Gawron) on the SAME OD demand and
seed, then score it with a horizon-censored FULL-DEMAND total system travel
time.

Objective (TSTT, vehicle-seconds), charging EVERY scheduled vehicle:
    arrived vehicle      : arrival_time - intended_depart   (= duration + departDelay)
    still running at end : SIM_END - intended_depart
    never inserted       : SIM_END - intended_depart
    unroutable/discarded : SIM_END - intended_depart
Accounting identity checked on every simulation of record:
    arrived + running + not_inserted + discarded == scheduled

CONVERGENCE.  A 25-iteration cold-start trace on this congested testbed
(outputs/convergence_study.json) shows the relative gap falling from 0.478 to a
FLOOR of ~0.08-0.11 by iteration ~12 and then oscillating, with mean trip
duration swinging +/-2.5% between adjacent iterations.  duaIterate does not
reach a point fixed point here, it reaches a limit cycle -- the same behaviour
scan-network-link-criticality-and-vulnerability documented on a congested
network.  A single final-iteration TSTT therefore carries oscillation noise of
the same order as the project benefits being measured, so the objective is a
TAIL AVERAGE: the simulation of record is run on the route file of each of the
last TAIL iterations and the TSTTs averaged.  Reported per evaluation:
    rel_gap_final, rel_gap_tail_mean : relative gap over the generated
        route-alternative set, sum_v (E_p[c] - min_a c_a) / sum_v E_p[c]
    tt_stab : (max-min)/mean of mean in-network duration over the tail
    tstt_sd_tail : s.d. of the tail TSTTs (the residual equilibrium noise)
Declared acceptance criterion: rel_gap_tail_mean <= 0.15 and tt_stab <= 0.08.
"""
import os, sys, shutil, subprocess, glob, gzip, json, time, statistics
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import build_net

SUMO_HOME = os.environ["SUMO_HOME"]
DUAITERATE = os.path.join(SUMO_HOME, "tools", "assign", "duaIterate.py")

SIM_END = 7200.0
TIME_TO_TELEPORT = 300.0
WARM_STEPS = 8          # duaIterate iterations when warm-started
COLD_STEPS = 13         # duaIterate iterations when cold-started (14 sims)
TAIL = 4                # iterations averaged into the objective
REL_GAP_TARGET = 0.15
TT_STAB_TARGET = 0.08


def _open(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path, "r")


# ------------------------------------------------------------------ parsing --
def parse_tripinfo(path):
    arrived, running = [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        arr = float(el.get("arrival"))
        rec = dict(id=el.get("id"), depart=float(el.get("depart")),
                   departDelay=float(el.get("departDelay")), arrival=arr,
                   duration=float(el.get("duration")),
                   routeLength=float(el.get("routeLength")),
                   timeLoss=float(el.get("timeLoss")))
        (arrived if arr >= 0 else running).append(rec)
        el.clear()
    return arrived, running


def parse_summary_last(path):
    last = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            last = {k: el.get(k) for k in el.keys()}
        el.clear()
    return last


def parse_trip_departs(trips_file):
    d = {}
    for _, el in ET.iterparse(trips_file, events=("end",)):
        if el.tag == "trip":
            d[el.get("id")] = float(el.get("depart"))
        el.clear()
    return d


def parse_rou_ids(path):
    ids = []
    with _open(path) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == "vehicle":
                ids.append(el.get("id"))
            el.clear()
    return ids


def rel_gap_from_alt(path):
    num = den = 0.0
    with _open(path) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag != "vehicle":
                continue
            rd = el.find("routeDistribution")
            if rd is None:
                el.clear(); continue
            costs, probs = [], []
            for r in rd.findall("route"):
                try:
                    costs.append(float(r.get("cost")))
                    probs.append(float(r.get("probability")))
                except (TypeError, ValueError):
                    pass
            if costs:
                ps = sum(probs) or 1.0
                exp = sum(c * p for c, p in zip(costs, probs)) / ps
                num += exp - min(costs); den += exp
            el.clear()
    return (num / den) if den > 0 else float("nan")


def mean_dur(path):
    n, s = 0, 0.0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo" and float(el.get("arrival")) >= 0:
            n += 1; s += float(el.get("duration"))
        el.clear()
    return (s / n) if n else float("nan")


# --------------------------------------------------------------- simulation --
def run_dua(netfile, trips, workdir, last_step, warm_routes=None,
            logit=False, seed=None, tag="dua"):
    """Run duaIterate with NO early stop, return every step's artefacts."""
    duadir = os.path.join(workdir, tag)
    shutil.rmtree(duadir, ignore_errors=True)
    os.makedirs(duadir)
    demand = ["-r", os.path.abspath(warm_routes)] if warm_routes \
        else ["-t", os.path.abspath(trips)]
    cmd = [sys.executable, DUAITERATE, "-n", os.path.abspath(netfile)] + demand + [
        "-l", str(last_step), "-e", str(int(SIM_END)),
        "--convergence-iterations", str(last_step + 5),
        "--max-convergence-deviation", "0.0",
        "--time-to-teleport", str(int(TIME_TO_TELEPORT)),
        "--disable-warnings", "--routing-algorithm", "astar"]
    if logit:
        cmd.append("--logit")
    # every duaIterate iteration IS a simulation of record: fix its seed and make
    # it report vehicles that never finished, so the horizon-censored full-demand
    # accounting can be done on the iteration's own output.
    cmd += ["sumo--seed", str(seed if seed is not None else 1),
            "sumo--tripinfo-output.write-unfinished", "true"]
    r = subprocess.run(cmd, cwd=duadir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("duaIterate rc=%d: %s" % (r.returncode, r.stderr[-1500:]))
    steps = sorted(d for d in os.listdir(duadir)
                   if d.isdigit() and os.path.isdir(os.path.join(duadir, d)))
    out = []
    for s in steps:
        rou = [p for p in glob.glob(os.path.join(duadir, s, "*_%s.rou.xml*" % s))
               if ".alt." not in p]
        alt = glob.glob(os.path.join(duadir, s, "*_%s.rou.alt.xml*" % s))
        ti = glob.glob(os.path.join(duadir, s, "tripinfo_%s.xml*" % s))
        sm = glob.glob(os.path.join(duadir, s, "summary_%s.xml*" % s))
        out.append(dict(step=int(s), rou=rou[0] if rou else None,
                        alt=alt[0] if alt else None, ti=ti[0] if ti else None,
                        summ=sm[0] if sm else None))
    if not out or out[-1]["rou"] is None:
        raise RuntimeError("duaIterate produced no usable route file")
    return duadir, out


def run_record(netfile, route_file, outdir, seed=1, edgedata=False):
    os.makedirs(outdir, exist_ok=True)
    tri = os.path.join(outdir, "tripinfo.xml")
    summ = os.path.join(outdir, "summary.xml")
    cmd = ["sumo", "-n", os.path.abspath(netfile), "-r", os.path.abspath(route_file),
           "--tripinfo-output", tri, "--tripinfo-output.write-unfinished", "true",
           "--summary-output", summ, "--begin", "0", "--end", str(int(SIM_END)),
           "--time-to-teleport", str(int(TIME_TO_TELEPORT)),
           "--seed", str(seed), "--no-step-log", "true",
           "--no-warnings", "true", "--xml-validation", "never"]
    if edgedata:
        add = os.path.join(outdir, "ed.add.xml")
        with open(add, "w") as f:
            f.write('<additional><edgeData id="ed" file="edgedata.xml" begin="0" '
                    'end="%d" period="1800" excludeEmpty="true"/></additional>\n'
                    % int(SIM_END))
        cmd += ["-a", add]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sumo rc=%d: %s" % (r.returncode, r.stderr[-1500:]))
    return tri, summ


def tstt_of_run(tri, summ, route_file, departs):
    routed = set(parse_rou_ids(route_file))
    arrived, running = parse_tripinfo(tri)
    seen = {r["id"] for r in arrived} | {r["id"] for r in running}
    not_ins = sorted(routed - seen)
    disc = sorted(set(departs) - routed)
    t = sum(r["arrival"] - (r["depart"] - r["departDelay"]) for r in arrived)
    t += sum(SIM_END - (r["depart"] - r["departDelay"]) for r in running)
    t += sum(SIM_END - departs[v] for v in not_ins)
    t += sum(SIM_END - departs[v] for v in disc)
    last = parse_summary_last(summ)
    return dict(tstt=t, arrived=len(arrived), running=len(running),
                not_inserted=len(not_ins), discarded=len(disc),
                accounting_ok=(len(arrived) + len(running) + len(not_ins)
                               + len(disc)) == len(departs),
                teleports=int(last.get("teleports", 0)) if last else -1,
                mean_dur=sum(r["duration"] for r in arrived) / max(1, len(arrived)),
                mean_departdelay=sum(r["departDelay"] for r in arrived) / max(1, len(arrived)),
                total_timeloss=sum(r["timeLoss"] for r in arrived))


# --------------------------------------------------------------- evaluation --
def score(mask, trips_file, workdir, seed=1, warm_routes=None, last_step=None,
          tail=TAIL, keep=False, edgedata=False, logit=False, dua_seed=None,
          netfile=None, departs=None):
    t0 = time.time()
    os.makedirs(workdir, exist_ok=True)
    if last_step is None:
        last_step = WARM_STEPS if warm_routes else COLD_STEPS
    netfile = netfile or build_net(mask, workdir)
    duadir, steps = run_dua(netfile, trips_file, workdir, last_step,
                            warm_routes=warm_routes, logit=logit,
                            seed=(dua_seed if dua_seed is not None else seed))
    departs = departs or parse_trip_departs(trips_file)

    # Score directly on each of the last `tail` duaIterate iterations' own
    # simulations -- no redundant re-simulation, and the scored run is exactly
    # the equilibrium iteration's run.
    tail_steps = [s for s in steps if s["rou"] and s["ti"] and s["summ"]][-tail:]
    runs = []
    for s in tail_steps:
        m = tstt_of_run(s["ti"], s["summ"], s["rou"], departs)
        m["step"] = s["step"]
        runs.append(m)
    if edgedata:
        run_record(netfile, tail_steps[-1]["rou"], os.path.join(workdir, "rec"),
                   seed=seed, edgedata=True)

    gaps = [rel_gap_from_alt(s["alt"]) for s in tail_steps if s["alt"]]
    gaps = [g for g in gaps if g == g]
    durs = [mean_dur(s["ti"]) for s in tail_steps if s["ti"]]
    durs = [d for d in durs if d == d]
    tstts = [r["tstt"] for r in runs]
    tt_stab = (max(durs) - min(durs)) / (sum(durs) / len(durs)) if len(durs) >= 2 else float("nan")
    gap_tail = sum(gaps) / len(gaps) if gaps else float("nan")

    res = dict(
        mask=mask, seed=seed,
        tstt=round(sum(tstts) / len(tstts), 2),
        tstt_sd_tail=round(statistics.pstdev(tstts), 2) if len(tstts) > 1 else 0.0,
        tstt_min_tail=round(min(tstts), 2), tstt_max_tail=round(max(tstts), 2),
        tail_tstts=[round(t, 1) for t in tstts],
        tail_steps=[r["step"] for r in runs],
        scheduled=len(departs),
        arrived=int(round(sum(r["arrived"] for r in runs) / len(runs))),
        running=int(round(sum(r["running"] for r in runs) / len(runs))),
        not_inserted=int(round(sum(r["not_inserted"] for r in runs) / len(runs))),
        discarded=int(round(sum(r["discarded"] for r in runs) / len(runs))),
        accounting_ok=all(r["accounting_ok"] for r in runs),
        teleports_max=max(r["teleports"] for r in runs),
        teleports_mean=round(sum(r["teleports"] for r in runs) / len(runs), 2),
        mean_dur_arrived=round(sum(r["mean_dur"] for r in runs) / len(runs), 3),
        mean_departdelay=round(sum(r["mean_departdelay"] for r in runs) / len(runs), 3),
        total_timeloss=round(sum(r["total_timeloss"] for r in runs) / len(runs), 1),
        rel_gap_final=round(gaps[-1], 5) if gaps else None,
        rel_gap_tail_mean=round(gap_tail, 5) if gap_tail == gap_tail else None,
        tt_stab=round(tt_stab, 5) if tt_stab == tt_stab else None,
        dua_iterations=len(steps), warm=bool(warm_routes),
        wall_s=round(time.time() - t0, 2),
    )
    res["converged"] = bool(res["rel_gap_tail_mean"] is not None
                            and res["rel_gap_tail_mean"] <= REL_GAP_TARGET
                            and res["tt_stab"] is not None
                            and res["tt_stab"] <= TT_STAB_TARGET
                            and res["accounting_ok"])
    if not keep:
        shutil.rmtree(duadir, ignore_errors=True)
    return res


if __name__ == "__main__":
    import argparse
    from testbed import write_trips
    ap = argparse.ArgumentParser()
    ap.add_argument("--mask", type=int, default=0)
    ap.add_argument("--nveh", type=int, default=4000)
    ap.add_argument("--work", default="/tmp/dndp_test")
    ap.add_argument("--warm", default=None)
    ap.add_argument("--steps", type=int, default=None)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    tf = os.path.join(a.work, "trips.xml")
    if not os.path.exists(tf):
        write_trips(a.nveh, tf)
    print(json.dumps(score(a.mask, tf, a.work, warm_routes=a.warm,
                           last_step=a.steps), indent=2))
