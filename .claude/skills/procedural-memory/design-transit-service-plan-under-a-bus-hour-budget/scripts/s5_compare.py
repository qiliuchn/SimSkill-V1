"""Stage 4: route-structure comparison at EQUAL BUS-HOURS (the fairness control).

Three structurally different plans, each given exactly the same integer bus
budget, each allocated across its own lines by the square-root rule using its
own measured cycle times and line demands.  Evaluated on a common set of CRN
seeds.  Winner reported on total passenger generalized time AND on ridership,
with the transfer-penalty sensitivity that answers H2.
"""
import os, sys, json, math, statistics as st
import tspcore as T
from tspcore import WORK, ensure
import plans as P
import harness as H
import alloc as A

BUDGET = int(os.environ.get("BUDGET", "24"))
SEEDS = [101, 102, 103, 104, 105, 106]
OUTJ = os.path.join(WORK, "stage4_compare.json")


def allocations(budget=BUDGET):
    cycles = H.load_json(H.CYCLE_FILE)
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))
    out = {}
    for name in ("coverage", "trunkfeeder", "freqgrid"):
        ids = [l[0] for l in P.PLAN_DEFS[name]]
        buses, ok, msg = A.sqrt_rule(budget, cycles[name], demand[name], ids)
        out[name] = dict(buses=buses, ok=ok, msg=msg, cycles=cycles[name],
                         demand=demand[name])
    return out


def main():
    speeds = H.load_json(H.SPEED_FILE)
    alloc = allocations()
    jobs, keys = [], []
    for name, a in alloc.items():
        if not a["ok"]:
            print(name, "INFEASIBLE", a["msg"]); continue
        tag = f"s4_{name}_B{BUDGET}"
        for s in SEEDS:
            jobs.append((name, a["buses"], s, None, a["cycles"], speeds[name], tag, True))
            keys.append((name, s))
    print(f"{len(jobs)} runs")
    res = H.evaluate_many(jobs, workers=8)

    by = {}
    for (name, s), m in zip(keys, res):
        by.setdefault(name, []).append(m)

    summary = {}
    for name, ms in by.items():
        ms = [m for m in ms if "error" not in m]
        def mean(f): return sum(f(m) for m in ms) / len(ms)
        gcs = [H.gc_total(m) for m in ms]
        gcp = [H.gc_per_person(m) for m in ms]
        d = dict(
            n_seeds=len(ms), buses=alloc[name]["buses"],
            bus_hours=sum(alloc[name]["buses"].values()) * T.BUS_HOUR_SPAN_H,
            headways={k: round(alloc[name]["cycles"][k] / v, 1)
                      for k, v in alloc[name]["buses"].items()},
            gc_total_mean=st.mean(gcs), gc_total_sd=st.pstdev(gcs) if len(gcs) > 1 else 0.0,
            gc_per_person_mean=st.mean(gcp),
            ridership=mean(lambda m: m["n_riders"]),
            walkonly=mean(lambda m: m["n_walkonly"]),
            incomplete=mean(lambda m: m["n_incomplete"]),
            stranded=mean(lambda m: m["n_stranded"]),
            transfers=mean(lambda m: m["n_transfers"]),
            transfers_per_rider=mean(lambda m: m["n_transfers"] / max(1, m["n_riders"])),
            mean_access=mean(lambda m: m["sum_access"] / max(1, m["n_riders"])),
            mean_wait=mean(lambda m: m["sum_wait"] / max(1, m["n_riders"])),
            mean_ivt=mean(lambda m: m["sum_ivt"] / max(1, m["n_riders"])),
            mean_xwalk=mean(lambda m: m["sum_xwalk"] / max(1, m["n_riders"])),
            mean_xwait=mean(lambda m: m["sum_xwait"] / max(1, m["n_riders"])),
            max_concurrent_total=mean(lambda m: m["max_concurrent_total"]),
            teleports=mean(lambda m: m["teleports"] or 0),
            cycles_measured=ms[0]["cycles_C"],
            gc_by_penalty={},
            gc_incl_incomplete=st.mean([H.gc_total(m, include_incomplete=True) for m in ms]),
            dirs=[m["dir"] for m in ms],
        )
        for pen in (0, 60, 120, 180, 240, 300, 420, 600, 900, 1200):
            d["gc_by_penalty"][pen] = st.mean([H.gc_total(m, p_transfer=pen) for m in ms])
        summary[name] = d

    with open(OUTJ, "w") as f:
        json.dump(dict(budget=BUDGET, seeds=SEEDS, alloc={k: v["buses"] for k, v in alloc.items()},
                       summary=summary), f, indent=1)

    print(f"\n=== equal-budget comparison, B = {BUDGET} bus-hours, "
          f"{len(SEEDS)} CRN seeds ===")
    hdr = ("plan", "buses", "GC total (pax-h)", "GC/pax (s)", "riders", "walk-only",
           "transfers/rider", "incomplete")
    print("%-12s %6s %18s %11s %8s %10s %16s %11s" % hdr)
    for name, d in sorted(summary.items(), key=lambda kv: kv[1]["gc_total_mean"]):
        print("%-12s %6d %18.1f %11.1f %8.1f %10.1f %16.3f %11.1f" % (
            name, sum(d["buses"].values()), d["gc_total_mean"] / 3600.0,
            d["gc_per_person_mean"], d["ridership"], d["walkonly"],
            d["transfers_per_rider"], d["incomplete"]))
    print("\nstage decomposition (mean seconds per rider)")
    print("%-12s %9s %9s %9s %9s %9s" % ("plan", "access", "wait", "in-veh", "x-walk", "x-wait"))
    for name, d in summary.items():
        print("%-12s %9.1f %9.1f %9.1f %9.1f %9.1f" % (
            name, d["mean_access"], d["mean_wait"], d["mean_ivt"],
            d["mean_xwalk"], d["mean_xwait"]))
    print("\nH2 transfer-penalty sensitivity: total GC (pax-h) by penalty (s/transfer)")
    pens = sorted(next(iter(summary.values()))["gc_by_penalty"].keys(), key=int)
    print("%-12s " % "plan" + " ".join(f"{int(p):>8d}" for p in pens))
    for name, d in summary.items():
        print("%-12s " % name + " ".join(f"{d['gc_by_penalty'][p]/3600.0:8.1f}" for p in pens))
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
