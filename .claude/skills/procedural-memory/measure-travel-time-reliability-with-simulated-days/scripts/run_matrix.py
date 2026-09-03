#!/usr/bin/env python3
"""
Run the whole experiment matrix.

Blocks
------
FULL   : the Monte-Carlo day set (demand multiplier + incident + seed),
         replayed under all 3 scenarios with Common Random Numbers.
DEMAND : the same demand multipliers and the same seeds, incidents DISABLED.
SEED   : demand multiplier pinned at 1.0, incidents disabled, seed varying.
FF     : one negligible-demand run -> the free-flow travel-time reference.

Var(FULL) - Var(DEMAND) = incident contribution
Var(DEMAND) - Var(SEED) = day-to-day demand contribution
Var(SEED)               = simulator noise floor (no real-world counterpart)
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_lib as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
def netfile(la, lm):
    return os.path.join(WORK, "net", S.NETNAME[(la, lm)] + ".net.xml")


REUSE = {}


def one(job):
    # NOTE: the re-use row travels IN the job tuple.  On macOS the process
    # pool uses spawn, so a module-level dict populated in main() is empty in
    # the workers -- relying on a global here silently disables re-use.
    block, scen, day, keep_raw, vehroute, old = job
    la, lm, eq = S.SCENARIOS[scen]
    rd = os.path.join(WORK, "runs", block, scen, f"day{day['day']:03d}")
    if (old is not None and os.path.exists(os.path.join(rd, "corr_tt.npz"))
            and abs(float(old["mult"]) - day["mult"]) < 1e-9
            and int(old["seed"]) == day["seed"]
            and int(old["incident"]) == day["incident"]
            and float(old["inc_start"]) == day["inc_start"]
            and float(old["inc_dur"]) == day["inc_dur"]):
        r = dict(old)
        r["ok"] = 1
        r["reused"] = 1
        return r
    if os.path.exists(os.path.join(rd, "corr_tt.npz")):
        # cell already completed on disk -- re-summarise it instead of
        # re-simulating (tripinfo may already have been pruned)
        try:
            res = S.parse_cell(rd, cached=True)
            res.update(block=block, scenario=scen, day=day["day"], ok=1,
                       reused=1, mult=day["mult"], incident=day["incident"],
                       inc_start=day["inc_start"], inc_dur=day["inc_dur"],
                       inc_lanes=day["inc_lanes"], inc_edge=day["inc_edge"],
                       seed=day["seed"], equip=eq, approach_lanes=la,
                       mid_lanes=lm, rundir=rd)
            return res
        except Exception:
            pass
    err = ""
    for attempt in range(2):
        try:
            res = S.run_cell(rd, netfile(la, lm), day, eq, lm,
                             keep_raw=keep_raw, vehroute=vehroute)
            break
        except Exception:
            err = traceback.format_exc()[-500:]
            res = None
    if res is None:
        return dict(block=block, scenario=scen, day=day["day"], ok=0, err=err)
    if True:
        pass
    res.update(block=block, scenario=scen, day=day["day"], ok=1, reused=0,
               mult=day["mult"], incident=day["incident"],
               inc_start=day["inc_start"], inc_dur=day["inc_dur"],
               inc_lanes=day["inc_lanes"], inc_edge=day["inc_edge"],
               seed=day["seed"], equip=eq, approach_lanes=la,
               mid_lanes=lm, rundir=rd)
    if not keep_raw:
        tp = os.path.join(rd, "tripinfo.xml")
        if os.path.exists(tp):
            os.remove(tp)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--seed-block", type=int, default=20)
    ap.add_argument("--master-seed", type=int, default=20260801)
    ap.add_argument("--cv", type=float, default=0.18)
    ap.add_argument("--p-incident", type=float, default=0.25)
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--reuse", default="",
                    help="path to a previous cells.csv whose completed cells "
                         "should be re-used instead of re-simulated")
    a = ap.parse_args()
    if a.reuse and os.path.exists(a.reuse):
        for r in csv.DictReader(open(a.reuse)):
            REUSE[(r["block"], r["scenario"], int(r["day"]))] = r
        print(f"re-use pool: {len(REUSE)} previously completed cells")

    days = S.draw_days(a.days, a.master_seed, a.cv, a.p_incident)
    os.makedirs(os.path.join(WORK, "runs"), exist_ok=True)
    with open(os.path.join(WORK, "days.json"), "w") as f:
        json.dump(days, f, indent=1)

    # DEMAND block: identical multiplier + identical seed, incidents removed
    days_demand = []
    for d in days:
        e = dict(d)
        e.update(incident=0, inc_start=0.0, inc_dur=0.0, inc_lanes=0,
                 inc_edge="")
        days_demand.append(e)

    # SEED block: multiplier pinned to 1.0, incidents removed, seeds vary
    rng = np.random.default_rng(a.master_seed + 777)
    days_seed = [dict(day=i, mult=1.0, incident=0, inc_start=0.0, inc_dur=0.0,
                      inc_lanes=0, inc_edge="",
                      seed=int(rng.integers(1, 1_000_000)))
                 for i in range(a.seed_block)]

    jobs = []
    for scen in S.SCENARIOS:
        for d in days:
            # keep the full raw output set for the first 3 days of each scenario
            jobs.append(("FULL", scen, d, d["day"] < 3, d["day"] < 3,
                         REUSE.get(("FULL", scen, d["day"]))))
        for d in days_demand:
            jobs.append(("DEMAND", scen, d, False, False,
                         REUSE.get(("DEMAND", scen, d["day"]))))
        for d in days_seed:
            jobs.append(("SEED", scen, d, False, False,
                         REUSE.get(("SEED", scen, d["day"]))))
    ff_day = dict(day=0, mult=0.02, incident=0, inc_start=0.0, inc_dur=0.0,
                  inc_lanes=0, inc_edge="", seed=12345)
    jobs.append(("FF", "A_base", ff_day, True, True,
                 REUSE.get(("FF", "A_base", 0))))

    print(f"{len(jobs)} runs on {a.workers} workers ...", flush=True)
    rows = []
    done = 0
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(one, jobs):
            rows.append(r)
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    bad = [r for r in rows if not r.get("ok")]
    if bad:
        print("FAILURES:", len(bad))
        for b in bad[:3]:
            print(b)
        sys.exit(2)

    print(f"  re-used {sum(int(r.get('reused', 0)) for r in rows)} cells, "
          f"simulated {sum(1 for r in rows if not int(r.get('reused', 0)))}")
    keys = sorted({k for r in rows for k in r})
    out = os.path.join(WORK, "cells.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["block"], r["scenario"],
                                             r["day"])):
            w.writerow(r)
    print("wrote", out, len(rows), "rows")


if __name__ == "__main__":
    main()
