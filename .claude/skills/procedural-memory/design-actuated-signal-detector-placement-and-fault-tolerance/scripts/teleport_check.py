#!/usr/bin/env python3
"""Teleport-artifact validity check on the congested / faulted cells.

Per `validate-congested-scenario-results-against-teleport-artifacts`:
re-run the most congested configurations under three teleport settings and
check whether the conclusion is an artifact of SUMO's gridlock-resolution
machinery.  --time-to-teleport -1 (disabled) is included precisely because it
is the setting that can make a starved approach look artificially GOOD through
survivorship censoring of tripinfo.
"""
import csv
import json
import os
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import cfgutil                                     # noqa: E402

TTT = [-1, 120, 180, 300]
MAJOR_THRU = ["EC_0", "WC_0"]


def cases(best_sb, best_mg):
    C = []
    for lv in ("med", "high"):
        C.append((f"healthy_{lv}", lv, cfgutil.actuated_cfg(lv, best_sb, best_mg)))
        C.append((f"stuckoff_major_{lv}", lv,
                  cfgutil.actuated_cfg(lv, best_sb, best_mg, dead_lanes=MAJOR_THRU)))
        C.append((f"stuckon_major_{lv}", lv,
                  cfgutil.actuated_cfg(lv, best_sb, best_mg, stuck_on_lanes=MAJOR_THRU)))
        C.append((f"setback90_{lv}", lv, cfgutil.actuated_cfg(lv, 90, 3.0)))
        C.append((f"webster_{lv}", lv, cfgutil.webster_cfg(lv)))
    return C


def one(a):
    import run_cell
    name, lv, cfg, ttt, seed = a
    run_cell.TTT_OVERRIDE = ttt
    wd = os.path.join(cfgutil.WORK, "teleport", f"{name}__ttt{ttt}__s{seed}")
    m = run_cell.run(wd, cfgutil.NET, cfgutil.rou(lv, seed), cfg, seed)
    return dict(case=name, level=lv, ttt=ttt, seed=seed,
                delay=m["all"]["delay"], delay_robust=m["delay_censor_robust"],
                throughput=m["throughput"], completion=m["completion_rate"],
                teleports=m["teleports"])


if __name__ == "__main__":
    sb, mg = float(sys.argv[1]), float(sys.argv[2])
    tasks = [(n, lv, c, t, s) for (n, lv, c) in cases(sb, mg)
             for t in TTT for s in (1, 2, 3)]
    with Pool(9) as p:
        res = p.map(one, tasks, chunksize=1)
    out = os.path.join(cfgutil.WORK, "teleport_check.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0].keys()))
        w.writeheader()
        w.writerows(res)
    # compact: mean over seeds per (case, ttt)
    agg = {}
    for r in res:
        agg.setdefault((r["case"], r["ttt"]), []).append(r)
    comp = []
    for (case, t), rs in sorted(agg.items()):
        n = len(rs)
        comp.append(dict(case=case, ttt=t, n=n,
                         delay=round(sum(x["delay"] for x in rs) / n, 2),
                         delay_robust=round(sum(x["delay_robust"] for x in rs) / n, 2),
                         throughput=round(sum(x["throughput"] for x in rs) / n, 1),
                         completion=round(sum(x["completion"] for x in rs) / n, 4),
                         teleports=round(sum(x["teleports"] for x in rs) / n, 2)))
    json.dump(comp, open(os.path.join(cfgutil.WORK, "teleport_check.json"), "w"),
              indent=2)
    for c in comp:
        print(f"{c['case']:24s} ttt={c['ttt']:4d}  delay={c['delay']:8.1f} "
              f"robust={c['delay_robust']:9.1f} thr={c['throughput']:7.1f} "
              f"comp={c['completion']:.3f} tel={c['teleports']:.2f}")
