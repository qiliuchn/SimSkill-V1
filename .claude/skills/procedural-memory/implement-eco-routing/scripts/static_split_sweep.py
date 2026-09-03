"""Static-split reference sweep: force a FIXED bypass share on the main OD with
no router of any kind, and find the split that minimises network CO2.

This is the reference that separates an "allocation" failure (the reactive
controller converges to the wrong average split) from a "timing" failure (it
converges to the right split but the path there costs real emissions).
"""
import json
import multiprocessing as mp
import os
import random
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT, ARTERIAL_EDGES, BYPASS_EDGES  # noqa: E402
import simlib  # noqa: E402
import assign_loop as al  # noqa: E402

ART = ["O_A"] + ARTERIAL_EDGES + ["M_D"]
BYP = ["O_A"] + BYPASS_EDGES + ["M_D"]
SEEDS = [0, 1, 2, 3, 4]
SPLITS = [0.25, 0.325, 0.40, 0.475, 0.55, 0.625]
D = os.path.join(WORK, "static_split")
os.makedirs(D, exist_ok=True)


def job(args):
    share, seed = args
    trips = al.read_trips(os.path.join(WORK, "demand_s%d.trips.xml" % seed))
    base = simlib.parse_routes(os.path.join(WORK, "baseline_ue_s%d.rou.xml" % seed))
    rng = random.Random(4242 + seed)
    assign = {}
    for vid, (ty, edges) in base.items():
        assign[vid] = BYP if (vid.startswith("main.") and rng.random() < share) else (
            ART if vid.startswith("main.") else edges)
    pre = os.path.join(D, "ss_%03d_s%d" % (round(share * 1000), seed))
    rou = pre + ".rou.xml"
    al.write_routes(rou, trips, assign)
    f = simlib.run_sumo(rou, pre, seed=100 + seed, emissions_edgedata=True)
    ti = simlib.parse_tripinfo(f["tripinfo"])
    m = [t for t in ti if t["id"].startswith("main.")]
    d = sorted(t["duration"] for t in m)
    r = dict(share=share, seed=seed, n=len(ti),
             net_CO2_kg=sum(t["CO2"] for t in ti) / 1e6,
             net_fuel_kg=sum(t["fuel"] for t in ti) / 1e6,
             mean_tt=statistics.mean(d), p90_tt=d[int(0.9 * (len(d) - 1))],
             teleports=simlib.count_teleports(f["stderr"]))
    for suf in ("_tripinfo.xml", "_edgeemis.xml", ".rou.xml"):
        if os.path.exists(pre + suf):
            os.remove(pre + suf)
    return r


if __name__ == "__main__":
    jobs = [(s, sd) for s in SPLITS for sd in SEEDS]
    with mp.Pool(6) as pool:
        res = pool.map(job, jobs)
    with open(os.path.join(D, "results.json"), "w") as f:
        json.dump(res, f, indent=1)
    lines = ["=" * 88,
             "STATIC-SPLIT REFERENCE (no router; fixed bypass share; 5 demand seeds)",
             "=" * 88,
             "%-10s %14s %14s %12s %12s %8s" % ("byp share", "netCO2 kg", "netfuel kg",
                                                "meanTT s", "p90TT s", "teleps")]
    for s in SPLITS:
        r = [x for x in res if x["share"] == s]
        c = np.array([x["net_CO2_kg"] for x in r])
        fu = np.array([x["net_fuel_kg"] for x in r])
        t = np.array([x["mean_tt"] for x in r])
        p = np.array([x["p90_tt"] for x in r])
        lines.append("%-10.3f %7.1f+-%-5.1f %7.2f+-%-5.2f %6.1f+-%-4.1f %6.1f+-%-4.1f %8d"
                     % (s, c.mean(), c.std(ddof=1), fu.mean(), fu.std(ddof=1),
                        t.mean(), t.std(ddof=1), p.mean(), p.std(ddof=1),
                        sum(x["teleports"] for x in r)))
    best_c = min(SPLITS, key=lambda s: np.mean([x["net_CO2_kg"] for x in res if x["share"] == s]))
    best_t = min(SPLITS, key=lambda s: np.mean([x["mean_tt"] for x in res if x["share"] == s]))
    lines.append("")
    lines.append("   CO2-minimising static bypass share  : %.3f" % best_c)
    lines.append("   time-minimising static bypass share : %.3f" % best_t)
    lines.append("   realised shares: travel-time UE 0.524 | offline eco equilibrium 0.417 |")
    lines.append("                    online eco @100%% penetration 0.367 | online tt-only @100%% 0.451")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(OUT, "static_split_reference.txt"), "w") as f:
        f.write(txt + "\n")
