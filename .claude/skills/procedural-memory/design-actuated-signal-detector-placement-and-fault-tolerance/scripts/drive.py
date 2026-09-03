#!/usr/bin/env python3
"""Run the full experiment grid in parallel and compact it into one CSV.

Experiments
-----------
E1  setback x max-gap x demand x 5 seeds      (the main design surface)
E2  SUMO-default auto-generated detectors     (the thing we compare against)
E3  per-approach setback (major-only / minor-only) -> is 2.0 s x speed right
    for EACH speed, not just on average?
E4  detector fault injection on the best-tuned config, vs healthy AND Webster
E5  fail-safe maxDur = Webster green, healthy and stuck-on

Common Random Numbers: seed s always means the same route file AND the same
SUMO RNG seed, so every variant sees an identical arrival stream.
"""
import csv
import json
import os
import sys
import time
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import cfgutil                                             # noqa: E402
from tls_common import GREEN_PHASES, GREEN_ORDER           # noqa: E402

SEEDS = [1, 2, 3, 4, 5]
LEVELS = ["low", "med", "high"]
SETBACKS = [0, 10, 25, 40, 60, 90]
MAXGAPS = [1.0, 2.0, 3.0, 5.0, 8.0]
MAJOR_THRU = ["EC_0", "WC_0"]
MINOR_THRU = ["NC_0", "SC_0"]
RUNS = os.path.join(cfgutil.WORK, "runs")


def task_list():
    T = []

    def add(exp, name, cfg, level, seed, keep=False):
        T.append(dict(exp=exp, name=name, cfg=cfg, level=level, seed=seed,
                      keep=keep))

    # --- E1: the main sweep -------------------------------------------------
    for lv in LEVELS:
        for sb in SETBACKS:
            for mg in MAXGAPS:
                for s in SEEDS:
                    keep = (lv == "med" and sb == 40 and mg == 3.0 and s == 1)
                    add("E1", f"sb{sb}_mg{mg:g}", cfgutil.actuated_cfg(lv, sb, mg),
                        lv, s, keep)

    # --- E2: SUMO's own auto-generated detectors + the Webster baseline ------
    for lv in LEVELS:
        for s in SEEDS:
            c = cfgutil.actuated_cfg(lv, 0, 3.0)
            c["auto_detectors"] = True
            add("E2", "auto_default", c, lv, s, keep=(lv == "med" and s == 1))
            add("E2", "webster", cfgutil.webster_cfg(lv), lv, s,
                keep=(lv == "med" and s == 1))

    # --- E3: one approach's setback at a time -------------------------------
    for lv in LEVELS:
        for sb in SETBACKS:
            for s in SEEDS:
                ov = {ln: float(sb) for ln in MAJOR_THRU}
                add("E3major", f"majsb{sb}",
                    cfgutil.actuated_cfg(lv, 25, 3.0, det_overrides=ov), lv, s)
                ov2 = {ln: float(sb) for ln in MINOR_THRU}
                add("E3minor", f"minsb{sb}",
                    cfgutil.actuated_cfg(lv, 40, 3.0, det_overrides=ov2), lv, s)
    return T


def fault_tasks(best_sb, best_mg, tag=""):
    T = []

    def add(exp, name, cfg, level, seed, keep=False):
        T.append(dict(exp=exp, name=name, cfg=cfg, level=level, seed=seed,
                      keep=keep))
    for lv in LEVELS:
        for s in SEEDS:
            A = lambda **k: cfgutil.actuated_cfg(lv, best_sb, best_mg, **k)
            add("E4"+tag, "healthy", A(), lv, s, keep=(s == 1))
            add("E4"+tag, "stuckoff_major", A(dead_lanes=MAJOR_THRU), lv, s, keep=(s == 1))
            add("E4"+tag, "stuckoff_minor", A(dead_lanes=MINOR_THRU), lv, s, keep=(s == 1))
            add("E4"+tag, "stuckoff_partial", A(dead_lanes=["WC_0"]), lv, s, keep=(s == 1))
            add("E4"+tag, "stuckon_major", A(stuck_on_lanes=MAJOR_THRU), lv, s, keep=(s == 1))
            add("E4"+tag, "stuckon_partial", A(stuck_on_lanes=["WC_0"]), lv, s, keep=(s == 1))
            # E5: fail-safe maxDur = Webster green
            add("E5"+tag, "failsafe_healthy",
                cfgutil.actuated_cfg(lv, best_sb, best_mg, maxdur="webster"),
                lv, s, keep=(s == 1))
            add("E5"+tag, "failsafe_stuckon_major",
                cfgutil.actuated_cfg(lv, best_sb, best_mg, maxdur="webster",
                                     stuck_on_lanes=MAJOR_THRU), lv, s, keep=(s == 1))
            add("E5"+tag, "failsafe_stuckoff_major",
                cfgutil.actuated_cfg(lv, best_sb, best_mg, maxdur="webster",
                                     dead_lanes=MAJOR_THRU), lv, s, keep=(s == 1))
    return T


def work(t):
    import run_cell
    wd = os.path.join(RUNS, t["exp"], f"{t['name']}__{t['level']}__s{t['seed']}")
    try:
        m = run_cell.run(wd, cfgutil.NET, cfgutil.rou(t["level"], t["seed"]),
                         t["cfg"], t["seed"], keep_raw=t["keep"])
    except Exception:
        return dict(exp=t["exp"], name=t["name"], level=t["level"],
                    seed=t["seed"], error=traceback.format_exc()[-800:])
    r = dict(exp=t["exp"], name=t["name"], level=t["level"], seed=t["seed"],
             wd=wd, setback=t["cfg"].get("setback"),
             max_gap=t["cfg"].get("max_gap"),
             maxdur_mode=t["cfg"].get("maxdur_mode", "-"),
             mode=t["cfg"]["mode"],
             auto_det=int(bool(t["cfg"].get("auto_detectors"))),
             dead=";".join(t["cfg"].get("dead_lanes", [])) or "-",
             stuckon=";".join(t["cfg"].get("stuck_on_lanes", [])) or "-",
             delay=m["all"].get("delay"), wait=m["all"].get("wait"),
             stops=m["all"].get("stops"), tt=m["all"].get("tt"),
             delay_major=m["major"].get("delay"), delay_minor=m["minor"].get("delay"),
             stops_major=m["major"].get("stops"), stops_minor=m["minor"].get("stops"),
             throughput=m["throughput"], n_scheduled=m["n_scheduled"],
             completion=m["completion_rate"],
             delay_robust=m["delay_censor_robust"],
             teleports=m["teleports"],
             stuckon_max_tsd=m.get("stuckon_max_time_since_detection", ""))
    for gp in GREEN_ORDER:
        nm = GREEN_PHASES[gp]["name"]
        p = m["phases"].get(nm, {})
        pre = nm.split("_")[0]
        for k in ("mean_green", "f_gapout", "f_maxout", "f_minout",
                  "f_cut_with_blind_queue", "f_premature_gapout",
                  "f_premature_gapout_anyimminent", "mean_unseen_imminent",
                  "mean_blind_veh", "mean_blind_slow", "mean_imminent",
                  "mean_queued_at_end", "n"):
            r[f"{pre}_{k}"] = p.get(k)
    return r


def run_all(tasks, out_csv, nproc=9):
    t0 = time.time()
    with Pool(nproc) as p:
        res = p.map(work, tasks, chunksize=1)
    errs = [r for r in res if "error" in r]
    ok = [r for r in res if "error" not in r]
    if errs:
        print(f"!! {len(errs)} FAILED, first:\n{errs[0]['error']}")
    keys = list(ok[0].keys())
    mode = "a" if os.path.exists(out_csv) else "w"
    with open(out_csv, mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        if mode == "w":
            w.writeheader()
        w.writerows(ok)
    print(f"{len(ok)} runs ok, {len(errs)} failed, {time.time()-t0:.0f}s -> {out_csv}")
    return ok, errs


if __name__ == "__main__":
    which = sys.argv[1]
    out = os.path.join(cfgutil.WORK, "cells_raw.csv")
    if which == "main":
        if os.path.exists(out):
            os.remove(out)
        run_all(task_list(), out)
    elif which == "faults":
        sb, mg = float(sys.argv[2]), float(sys.argv[3])
        tag = sys.argv[4] if len(sys.argv) > 4 else ""
        run_all(fault_tasks(sb, mg, tag), out)
