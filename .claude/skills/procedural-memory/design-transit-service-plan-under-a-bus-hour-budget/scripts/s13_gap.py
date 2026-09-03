"""Stage 5c: how far does the analytic square-root rule land from the simulated
optimum, and what is the gap made of?

Decomposition (all arms evaluated on the SAME held-out seeds, CRN-paired):
  gap_total   = GC(square-root rule) - GC(simulation optimum)
  congestion  = GC(sqrt rule fed FREE-FLOW cycle times) - GC(sqrt rule fed
                MEASURED congested cycle times)      <- what the rule ignores
                when it has no simulation to measure C_l with
  transfer    = GC(sqrt rule fed UNLINKED boardings) - GC(sqrt rule fed LINKED
                first-boardings)                     <- the rule's demand term
                cannot see that a transferring rider is counted twice
  residual    = gap_total - (the part of the above that the rule actually pays)
  noise floor = minimum difference resolvable at n held-out replications
"""
import os, sys, json, math, statistics as st
from collections import defaultdict
import tspcore as T
from tspcore import WORK
import plans as P
import harness as H
import alloc as A

STRUCT = os.environ.get("STRUCT", "trunkfeeder")
BUDGET = int(os.environ.get("BUDGET", "24"))
SEEDS = list(range(701, 713))
OUTJ = os.path.join(WORK, "stage5_gap.json")


def linked_boardings(dirs):
    """First-boarding counts per line (linked trips) and total boardings."""
    first, total = defaultdict(float), defaultdict(float)
    n = 0
    for d in dirs:
        p = os.path.join(d, "persons.json")
        if not os.path.exists(p):
            continue
        n += 1
        for r in json.load(open(p)):
            if r["mode"] != "transit":
                continue
            first[r["lines"][0].split(".")[0]] += 1
            for v in r["lines"]:
                total[v.split(".")[0]] += 1
    return ({k: v/max(1, n) for k, v in first.items()},
            {k: v/max(1, n) for k, v in total.items()})


def main():
    speeds = H.load_json(H.SPEED_FILE)[STRUCT]
    cyc = H.load_json(H.CYCLE_FILE)[STRUCT]
    dem = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    s5 = H.load_json(os.path.join(WORK, "stage5_optimize.json"))
    s4 = H.load_json(os.path.join(WORK, "stage4_compare.json"))
    h3 = H.load_json(os.path.join(WORK, "h3_congestion.json"))
    nf = H.load_json(os.path.join(WORK, "noise_floor.json"))

    first, total = linked_boardings(s4["summary"][STRUCT]["dirs"])
    print("line demand terms used by the analytic rule:")
    for l in ids:
        print(f"  {l:5s} unlinked boardings {total.get(l,0):7.1f}   "
              f"linked first-boardings {first.get(l,0):7.1f}")

    ff = h3["cycle_inflation"]["free_flow"]
    ff_C = {l: ff[l] + max(T.LAYOVER_FRAC*ff[l], T.LAYOVER_MIN) for l in ids}

    arms = {}
    arms["sqrt_measuredC_unlinked"] = A.sqrt_rule(BUDGET, cyc, total, ids)[0]
    arms["sqrt_measuredC_linked"] = A.sqrt_rule(BUDGET, cyc, first, ids)[0]
    arms["sqrt_freeflowC_unlinked"] = A.sqrt_rule(BUDGET, ff_C, total, ids)[0]
    arms["optimizer"] = s5["allocations"]["optimizer"]
    for k, v in arms.items():
        print(f"  {k:26s} {v}")

    jobs, keys = [], []
    for an, b in arms.items():
        for s in SEEDS:
            jobs.append((STRUCT, b, s, None, cyc, speeds, f"gap_{an}", False))
            keys.append((an, s))
    print(f"\n{len(jobs)} runs on {len(SEEDS)} fresh seeds")
    res = H.evaluate_many(jobs, workers=8)
    vals = defaultdict(dict)
    for (an, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        vals[an][s] = H.gc_total(m)

    def mean(a): return st.mean(list(vals[a].values()))

    def paired(a, b):
        ds = [vals[a][s] - vals[b][s] for s in SEEDS if s in vals[a] and s in vals[b]]
        m = st.mean(ds); sd = st.pstdev(ds)
        se = sd / math.sqrt(len(ds)) if ds else 0
        return m, sd, se, len(ds)

    print("\n%-28s %14s %12s" % ("arm", "GC mean (pax-h)", "sd"))
    for an in arms:
        v = list(vals[an].values())
        print("%-28s %14.2f %12.3f" % (an, st.mean(v)/3600, st.pstdev(v)/3600))

    gap, gsd, gse, n = paired("sqrt_measuredC_unlinked", "optimizer")
    cong, csd, cse, _ = paired("sqrt_freeflowC_unlinked", "sqrt_measuredC_unlinked")
    xf, xsd, xse, _ = paired("sqrt_measuredC_unlinked", "sqrt_measuredC_linked")
    sig = nf["sigma_pooled_near_optimal"] if nf else None
    res_floor = (1.96*math.sqrt(2)*sig/math.sqrt(n)) if sig else None

    print(f"\ngap decomposition ({n} CRN-paired held-out seeds)")
    print(f"  total gap   sqrt rule - optimizer            "
          f"{gap/3600:+8.3f} pax-h  (se {gse/3600:.3f}, "
          f"{100*gap/mean('optimizer'):+.2f}%)")
    print(f"  congestion  free-flow C - measured C         "
          f"{cong/3600:+8.3f} pax-h  (se {cse/3600:.3f})")
    print(f"  transfers   unlinked Q - linked Q            "
          f"{xf/3600:+8.3f} pax-h  (se {xse/3600:.3f})")
    if res_floor:
        print(f"  noise floor resolvable at n={n} (indep)     "
              f"{res_floor/3600:8.3f} pax-h")
        print(f"  -> total gap is {'RESOLVABLE' if abs(gap) > res_floor else 'NOT resolvable'}"
              f" against the measured noise floor")
    out = dict(structure=STRUCT, budget=BUDGET, seeds=SEEDS, arms=arms,
               values={k: {str(s): v for s, v in d.items()} for k, d in vals.items()},
               means={k: st.mean(list(d.values())) for k, d in vals.items()},
               gap_total=dict(value=gap, se=gse, n=n,
                              pct=100*gap/mean("optimizer")),
               component_congestion=dict(value=cong, se=cse),
               component_transfer_structure=dict(value=xf, se=xse),
               noise_floor_resolvable=res_floor,
               unlinked_boardings=total, linked_boardings=first)
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
