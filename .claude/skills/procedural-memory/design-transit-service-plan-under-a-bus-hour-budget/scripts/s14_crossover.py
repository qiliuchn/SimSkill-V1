"""H2 (part 2): the route-structure ranking is not fixed -- find the crossover.

Two axes:
  (a) BUDGET: all three structures at equal bus-hours, at several budgets.  The
      coverage plan is simply INFEASIBLE below the budget at which every one of
      its 8 routes can still meet the 20-minute policy headway cap -- that is
      itself the first crossover.
  (b) DEMAND DENSITY: the same three structures at B = 24 bus-hours with the
      person demand scaled up and down (the transit market is regenerated from
      the same documented OD with the same seed, only the trip count changes).
"""
import os, sys, json, math, statistics as st
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

BUDGETS = [int(x) for x in os.environ.get("BUDGETS", "12,16,24,40").split(",")]
SCALES = [float(x) for x in os.environ.get("SCALES", "0.5,1.0,2.0").split(",")]
SEEDS = [801, 802, 803]
NAMES = ("coverage", "trunkfeeder", "freqgrid")
OUTJ = os.path.join(WORK, "h2_crossover.json")


def budget_axis():
    speeds = H.load_json(H.SPEED_FILE)
    cycles = H.load_json(H.CYCLE_FILE)
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))
    jobs, keys, infeas, allocs = [], [], {}, {}
    for B in BUDGETS:
        for n in NAMES:
            ids = [l[0] for l in P.PLAN_DEFS[n]]
            b, ok, msg = A.sqrt_rule(B, cycles[n], demand[n], ids)
            if not ok:
                infeas[f"{n}@{B}"] = msg
                print(f"  B={B:3d} {n:12s} INFEASIBLE: {msg}")
                continue
            allocs[f"{n}@{B}"] = b
            for s in SEEDS:
                jobs.append((n, b, s, None, cycles[n], speeds[n], f"x_{n}_B{B}", False))
                keys.append((n, B, s))
    print(f"budget axis: {len(jobs)} runs")
    res = H.evaluate_many(jobs, workers=8)
    rows = {}
    for (n, B, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        rows.setdefault((n, B), []).append(m)
    tab = []
    for (n, B), ms in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        tab.append(dict(plan=n, budget=B, alloc=allocs[f"{n}@{B}"],
                        gc=st.mean([H.gc_total(m) for m in ms]),
                        gc_sd=st.pstdev([H.gc_total(m) for m in ms]),
                        gc_per_pax=st.mean([H.gc_per_person(m) for m in ms]),
                        riders=st.mean([m["n_riders"] for m in ms]),
                        walkonly=st.mean([m["n_walkonly"] for m in ms]),
                        incomplete=st.mean([m["n_incomplete"] for m in ms])))
    return tab, infeas, allocs


def density_axis():
    speeds = H.load_json(H.SPEED_FILE)
    cycles = H.load_json(H.CYCLE_FILE)
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))
    net = T.Net(os.path.join(WORK, "base.net.xml"))
    tab = []
    for sc in SCALES:
        wd = ensure(os.path.join(WORK, f"dens_{sc}"))
        T.build_demand(net, wd, n_trips=int(round(1800 * sc)), seed=7)
        pfile = os.path.join(wd, "persons.trips.xml")
        # background car traffic is held FIXED so only the transit market changes
        jobs, keys = [], []
        for n in NAMES:
            ids = [l[0] for l in P.PLAN_DEFS[n]]
            b, ok, msg = A.sqrt_rule(24, cycles[n], demand[n], ids)
            if not ok:
                continue
            for s in SEEDS:
                jobs.append((n, b, s, None, cycles[n], speeds[n],
                             f"d_{n}_x{sc}", False, pfile))
                keys.append((n, s))
        npers = len([1 for l in open(pfile) if "<person " in l])
        print(f"  density {sc}: {len(jobs)} runs, {npers} transit-market persons")
        res = H.evaluate_many(jobs, workers=8)
        agg = {}
        for (n, s), m in zip(keys, res):
            if "error" in m:
                print("ERR", m["error"]); continue
            agg.setdefault(n, []).append(m)
        for n, ms in agg.items():
            tab.append(dict(plan=n, scale=sc,
                            gc=st.mean([H.gc_total(m) for m in ms]),
                            gc_per_pax=st.mean([H.gc_per_person(m) for m in ms]),
                            riders=st.mean([m["n_riders"] for m in ms]),
                            walkonly=st.mean([m["n_walkonly"] for m in ms]),
                            incomplete=st.mean([m["n_incomplete"] for m in ms]),
                            transfers_per_rider=st.mean([m["n_transfers"]/max(1, m["n_riders"])
                                                         for m in ms])))
    return tab


def main():
    print("=== H2(a): equal-budget ranking as a function of the budget ===")
    tab, infeas, allocs = budget_axis()
    print("\n%6s %-12s %12s %12s %10s %10s" % ("B", "plan", "GC(pax-h)",
                                               "GC/pax(s)", "riders", "walk-only"))
    for r in tab:
        print("%6d %-12s %12.1f %12.1f %10.1f %10.1f" % (
            r["budget"], r["plan"], r["gc"]/3600, r["gc_per_pax"],
            r["riders"], r["walkonly"]))
    print("\nwinner on generalized time by budget:")
    for B in sorted({r["budget"] for r in tab}):
        rr = [r for r in tab if r["budget"] == B]
        w = min(rr, key=lambda r: r["gc"])
        wr = max(rr, key=lambda r: r["riders"])
        print(f"  B={B:3d}: GC winner = {w['plan']:12s} ({w['gc']/3600:7.1f} pax-h)   "
              f"ridership winner = {wr['plan']:12s} ({wr['riders']:.0f})   "
              f"[{len(rr)} feasible structures]")

    print("\n=== H2(b): ranking as a function of demand density ===")
    dt = density_axis()
    print("\n%6s %-12s %12s %12s %10s %16s" % ("scale", "plan", "GC(pax-h)",
                                               "GC/pax(s)", "riders", "xfers/rider"))
    for r in dt:
        print("%6.2f %-12s %12.1f %12.1f %10.1f %16.3f" % (
            r["scale"], r["plan"], r["gc"]/3600, r["gc_per_pax"], r["riders"],
            r["transfers_per_rider"]))
    print("\nwinner on GC per passenger by demand scale:")
    for sc in sorted({r["scale"] for r in dt}):
        rr = [r for r in dt if r["scale"] == sc]
        w = min(rr, key=lambda r: r["gc_per_pax"])
        print(f"  scale {sc:4.2f}: {w['plan']:12s} ({w['gc_per_pax']:.1f} s/pax)  "
              + "  ".join(f"{r['plan'][:4]}={r['gc_per_pax']:.0f}" for r in rr))
    with open(OUTJ, "w") as f:
        json.dump(dict(budget_axis=tab, infeasible=infeas, allocations=allocs,
                       density_axis=dt, seeds=SEEDS), f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
