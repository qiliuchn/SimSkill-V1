#!/usr/bin/env python3
"""STEP 5 & 6 -- brute-force cycle-length sweep against Webster's prediction.

For each of three saturation levels (Y ~ 0.50, 0.85, 1.05) and each cycle
length C in 30..180 step 10:
  * build a fixed-time 2-phase plan with WEBSTER-PROPORTIONAL splits at that C
    (splits come from webster.py using the MEASURED s, l1, l2)
  * run SUMO with a demand file that is byte-identical across all cycle lengths
    (explicit <vehicle> entries with pre-drawn exponential/Poisson arrivals,
     numpy seed 12345) and the same SUMO --seed
  * extract mean timeLoss / duration / waitingTime per ARRIVED vehicle from
    tripinfo, plus loaded/inserted/arrived/running/teleport counts from summary

Demand: 3600 s of Poisson arrivals per approach, simulation runs to 7200 s so
the oversaturated cases get a chance to drain (they may not -- reported).
"""
import os
import sys
import json
import math
import random
import xml.etree.ElementTree as ET
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (WORK, NET, VTYPES, vtype_xml, ROUTES, tls_xml, YELLOW,
                    ALLRED, STEP_LENGTH, run_sumo)
from webster import WebsterDesign

SWEEP = os.path.join(WORK, "sweep")
os.makedirs(SWEEP, exist_ok=True)

CYCLES = list(range(20, 190, 10))          # 20..180 s (extended below 30 s
                                           # so the undersaturated C_opt is bracketed)
DEMAND_END = 3600.0
SIM_END = 7200.0
SEED = 42
DEMAND_SEED = 12345
VT = "base"

# phase 0 = NS through (in_N->out_S, in_S->out_N), phase 1 = EW through
PHASE_OF = {"NS": 0, "SN": 0, "EW": 1, "WE": 1}
# split of Y between the two phases
Y_SHARE = {0: 0.60, 1: 0.40}
Y_LEVELS = {"under": 0.50, "critical": 0.85, "over": 1.05}


# ------------------------------------------------------------------ demand --
def make_demand(level, Y, s_vph):
    """Explicit-vehicle Poisson demand; identical for every cycle length."""
    q = {ph: Y * Y_SHARE[ph] * s_vph for ph in (0, 1)}      # veh/h per approach
    rng = random.Random(DEMAND_SEED)
    vehs = []
    for rid in ROUTES:
        ph = PHASE_OF[rid]
        rate = q[ph] / 3600.0
        t = 0.0
        k = 0
        while True:
            t += rng.expovariate(rate)
            if t >= DEMAND_END:
                break
            vehs.append((t, "%s.%d" % (rid, k), rid))
            k += 1
    vehs.sort()
    path = os.path.join(SWEEP, "demand_%s.rou.xml" % level)
    with open(path, "w") as f:
        f.write('<routes>\n')
        f.write(vtype_xml(VT, VTYPES[VT]))
        for rid, edges in ROUTES.items():
            f.write('    <route id="r_%s" edges="%s"/>\n' % (rid, edges))
        for t, vid, rid in vehs:
            f.write('    <vehicle id="%s" type="%s" route="r_%s" depart="%.2f" '
                    'departLane="0" departSpeed="max" departPos="base"/>\n'
                    % (vid, VT, rid, t))
        f.write('</routes>\n')
    return path, q, len(vehs)


# -------------------------------------------------------------------- runs --
def one_run(job):
    level, C, gdisp, demand_file = job
    tag = "%s_C%03d" % (level, C)
    od = os.path.join(SWEEP, tag)
    os.makedirs(od, exist_ok=True)
    tls = os.path.join(od, "tls.add.xml")
    g0 = round(gdisp[0], 1)
    g1 = round(C - 2 * (YELLOW + ALLRED) - g0, 1)   # absorb rounding: cycle is exact
    with open(tls, "w") as f:
        f.write(tls_xml(g0, g1, program="C%03d" % C))
    args = [
        "-n", NET, "-r", demand_file, "-a", tls,
        "--begin", "0", "--end", str(SIM_END),
        "--step-length", str(STEP_LENGTH),
        "--seed", str(SEED),
        "--time-to-teleport", "600",
        "--no-step-log", "true",
        "--xml-validation", "never",
        "--tripinfo-output", os.path.join(od, "tripinfo.xml"),
        "--summary-output", os.path.join(od, "summary.xml"),
    ]
    run_sumo(args, tag)
    return level, C, parse_run(od, gdisp)


def parse_run(od, gdisp):
    tl = dur = wt = dep_delay = 0.0
    n = 0
    per_phase = {0: [0, 0.0], 1: [0, 0.0]}
    for _, el in ET.iterparse(os.path.join(od, "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            n += 1
            tl += float(el.get("timeLoss"))
            dur += float(el.get("duration"))
            wt += float(el.get("waitingTime"))
            dep_delay += float(el.get("departDelay"))
            rid = el.get("id").split(".")[0]
            p = PHASE_OF[rid]
            per_phase[p][0] += 1
            per_phase[p][1] += float(el.get("timeLoss"))
            el.clear()
    last = None
    for _, el in ET.iterparse(os.path.join(od, "summary.xml"), events=("end",)):
        if el.tag == "step":
            last = dict(el.attrib)
            el.clear()
    loaded = int(float(last["loaded"]))
    inserted = int(float(last["inserted"]))
    ended = int(float(last["ended"]))
    running = int(float(last["running"]))
    tele = int(float(last.get("teleports", 0)))
    return dict(
        arrived=n,
        mean_timeLoss=tl / n if n else None,
        mean_duration=dur / n if n else None,
        mean_waitingTime=wt / n if n else None,
        mean_departDelay=dep_delay / n if n else None,
        timeLoss_phase0=per_phase[0][1] / per_phase[0][0] if per_phase[0][0] else None,
        timeLoss_phase1=per_phase[1][1] / per_phase[1][0] if per_phase[1][0] else None,
        loaded=loaded, inserted=inserted, ended=ended, running=running,
        not_inserted=loaded - inserted, teleports=tele,
        g_disp=[round(g, 2) for g in gdisp],
    )


# -------------------------------------------------------------------- main --
def main():
    sat = json.load(open(os.path.join(WORK, "saturation_results.json")))
    reg = sat[VT]["regression"]
    s_vph, l1, l2 = reg["s"], reg["l1"], reg["l2"]
    W = WebsterDesign(s_vph, l1, l2, YELLOW, ALLRED)
    print("measured s=%.1f veh/h/lane  l1=%.2f s  l2=%.2f s  L=%.2f s"
          % (s_vph, l1, l2, 2 * (l1 + l2)))

    out = {"measured": dict(s=s_vph, l1=l1, l2=l2, L=2 * (l1 + l2),
                            yellow=YELLOW, allred=ALLRED),
           "levels": {}}
    jobs = []
    for level, Y in Y_LEVELS.items():
        dfile, q, nveh = make_demand(level, Y, s_vph)
        crit = [q[0], q[1]]
        copt, Yc, L = W.c_opt(crit)
        print("%-9s Y=%.3f  q_NS=%.0f q_EW=%.0f veh/h  C_opt=%s  vehicles=%d"
              % (level, Yc, q[0], q[1],
                 ("%.1f s" % copt) if copt else "UNDEFINED (Y>=1)", nveh))
        lvl = dict(Y_target=Y, Y=Yc, L=L, C_opt=copt, q_phase=q,
                   n_vehicles=nveh, demand_file=dfile, webster={}, sim={})
        approach_flows = [(PHASE_OF[r], q[PHASE_OF[r]]) for r in ROUTES]
        for C in CYCLES:
            geff, gdisp = W.splits(float(C), crit)
            d, _, _, parts = W.intersection_delay(float(C), crit, approach_flows)
            lvl["webster"][C] = dict(g_eff=[round(x, 2) for x in geff],
                                     g_disp=[round(x, 2) for x in gdisp],
                                     delay=d,
                                     x=[round(v, 4) for v in
                                        W.degree_of_saturation(float(C), crit)])
            jobs.append((level, C, gdisp, dfile))
        out["levels"][level] = lvl

    with Pool(6) as p:
        for level, C, r in p.imap_unordered(one_run, jobs):
            out["levels"][level]["sim"][C] = r
            print("  %-9s C=%3d  simTL=%7.2f  arrived=%5d  notIns=%4d  run=%4d  tele=%d"
                  % (level, C, r["mean_timeLoss"], r["arrived"],
                     r["not_inserted"], r["running"], r["teleports"]), flush=True)

    with open(os.path.join(WORK, "sweep_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("written", os.path.join(WORK, "sweep_results.json"))


if __name__ == "__main__":
    main()
