"""H1 -- Mohring / economies of scale.

Sweeps the bus-hour budget on a fixed route structure, allocating each budget
with the square-root rule, and asks:
  * is per-passenger generalized cost CONVEX in budget?
  * is the budget-benefit frontier CONCAVE, or does it have a non-concave first
    increment as the road NDP's did (`solve-budget-constrained-network-design-problem`)?
"""
import os, sys, json, statistics as st
import tspcore as T
from tspcore import WORK
import plans as P
import harness as H
import alloc as A

STRUCT = os.environ.get("STRUCT", "trunkfeeder")
SEEDS = [401, 402, 403]
BUDGETS = [int(x) for x in os.environ.get(
    "BUDGETS", "8,11,14,18,24,32,42").split(",")]
OUTJ = os.path.join(WORK, "h1_frontier.json")


def main():
    speeds = H.load_json(H.SPEED_FILE)[STRUCT]
    cycles = H.load_json(H.CYCLE_FILE)[STRUCT]
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    jobs, keys, allocs, infeasible = [], [], {}, {}
    for B in BUDGETS:
        buses, ok, msg = A.sqrt_rule(B, cycles, demand, ids)
        if not ok:
            infeasible[B] = msg
            print(f"B={B}: {msg}")
            continue
        allocs[B] = buses
        for s in SEEDS:
            jobs.append((STRUCT, buses, s, None, cycles, speeds, f"h1_B{B}", False))
            keys.append((B, s))
    print(f"{len(jobs)} runs")
    res = H.evaluate_many(jobs, workers=8)
    by = {}
    for (B, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        by.setdefault(B, []).append(m)

    rows = []
    for B in sorted(by):
        ms = by[B]
        gcs = [H.gc_total(m) for m in ms]
        rows.append(dict(
            budget=B, bus_hours=B * T.BUS_HOUR_SPAN_H, alloc=allocs[B],
            headways={l: round(cycles[l] / allocs[B][l], 1) for l in ids},
            gc_total=st.mean(gcs), gc_sd=st.pstdev(gcs),
            gc_per_completed=st.mean([H.gc_per_person(m) for m in ms]),
            riders=st.mean([m["n_riders"] for m in ms]),
            walkonly=st.mean([m["n_walkonly"] for m in ms]),
            incomplete=st.mean([m["n_incomplete"] for m in ms]),
            transfers=st.mean([m["n_transfers"] for m in ms]),
            mean_wait=st.mean([m["sum_wait"] / max(1, m["n_riders"]) for m in ms]),
            mean_ivt=st.mean([m["sum_ivt"] / max(1, m["n_riders"]) for m in ms]),
            mean_access=st.mean([m["sum_access"] / max(1, m["n_riders"]) for m in ms]),
            max_concurrent=st.mean([m["max_concurrent_total"] for m in ms]),
        ))
    base = rows[0]
    print("\n%6s %10s %12s %12s %10s %12s %14s" % (
        "B(bh)", "GC(pax-h)", "GC/pax(s)", "riders", "walk-only",
        "benefit(pax-h)", "marginal/bus-h"))
    prev = None
    for r in rows:
        ben = (base["gc_total"] - r["gc_total"]) / 3600.0
        marg = ("" if prev is None else
                f"{((prev['gc_total']-r['gc_total'])/3600.0)/(r['budget']-prev['budget']):14.3f}")
        r["benefit_pax_h"] = ben
        r["marginal_per_bus_hour"] = (None if prev is None else
                                      ((prev['gc_total']-r['gc_total'])/3600.0)
                                      / (r['budget']-prev['budget']))
        print("%6d %10.1f %12.1f %12.1f %10.1f %14.2f %s" % (
            r["budget"], r["gc_total"]/3600.0, r["gc_per_completed"], r["riders"],
            r["walkonly"], ben, marg))
        prev = r
    # convexity / concavity checks (second differences on the common grid)
    d2 = []
    for i in range(1, len(rows) - 1):
        a, b, c = rows[i-1], rows[i], rows[i+1]
        h1 = b["budget"] - a["budget"]; h2 = c["budget"] - b["budget"]
        sec = ((c["gc_per_completed"] - b["gc_per_completed"]) / h2
               - (b["gc_per_completed"] - a["gc_per_completed"]) / h1)
        secb = ((c["benefit_pax_h"] - b["benefit_pax_h"]) / h2
                - (b["benefit_pax_h"] - a["benefit_pax_h"]) / h1)
        d2.append(dict(B=b["budget"], second_diff_gc_per_pax=sec,
                       second_diff_benefit=secb))
    print("\nsecond differences (per-pax GC should be >0 if convex; "
          "benefit should be <0 if concave)")
    for x in d2:
        print(f"  B={x['B']:3d}  d2(GC/pax) = {x['second_diff_gc_per_pax']:+8.4f}   "
              f"d2(benefit) = {x['second_diff_benefit']:+8.4f}")
    with open(OUTJ, "w") as f:
        json.dump(dict(structure=STRUCT, seeds=SEEDS, rows=rows,
                       second_differences=d2, infeasible=infeasible), f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
