"""H4 -- non-additivity of line-level frequency increments.

The transit counterpart of `solve-budget-constrained-network-design-problem`'s
pairwise project-interaction matrix.  A "project" here is +1 bus-hour on one
line.  From a base allocation at B0 bus-hours we evaluate every single project
(B0+1) and every pair (B0+2), all on the same CRN seeds, and compute

    interaction_ij = benefit(i and j) - benefit(i) - benefit(j)

where benefit(S) = GC(base) - GC(base + S).  Additive projects have
interaction 0; the road NDP found large negative (sub-additive) interactions.
"""
import os, sys, json, math, itertools, statistics as st
import tspcore as T
from tspcore import WORK
import plans as P
import harness as H
import alloc as A

STRUCT = os.environ.get("STRUCT", "trunkfeeder")
B0 = int(os.environ.get("B0", "20"))
SEEDS = [601, 602, 603]
OUTJ = os.path.join(WORK, "h4_interaction.json")


def main():
    speeds = H.load_json(H.SPEED_FILE)[STRUCT]
    cycles = H.load_json(H.CYCLE_FILE)[STRUCT]
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    base, ok, msg = A.sqrt_rule(B0, cycles, demand, ids)
    assert ok, msg
    lo, hi = A.bounds(cycles, ids)
    proj = [l for l in sorted(ids, key=lambda l: -demand[l]) if base[l] + 2 <= hi[l]][:3]
    print(f"base allocation at B0={B0}: {base}")
    print(f"projects (+1 bus each): {proj}")

    designs = {"base": dict(base)}
    for l in proj:
        b = dict(base); b[l] += 1; designs[f"+{l}"] = b
    for a, b_ in itertools.combinations(proj, 2):
        d = dict(base); d[a] += 1; d[b_] += 1; designs[f"+{a}+{b_}"] = d

    jobs, keys = [], []
    for dn, b in designs.items():
        for s in SEEDS:
            jobs.append((STRUCT, b, s, None, cycles, speeds,
                         "h4_" + dn.replace("+", "p"), False))
            keys.append((dn, s))
    print(f"{len(jobs)} runs")
    res = H.evaluate_many(jobs, workers=8)
    vals = {}
    for (dn, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        vals.setdefault(dn, {})[s] = H.gc_total(m)

    def mean(dn): return st.mean(list(vals[dn].values()))
    # CRN-paired benefit (per-seed difference from base, then averaged)
    def benefit(dn):
        ds = [vals["base"][s] - vals[dn][s] for s in SEEDS
              if s in vals["base"] and s in vals[dn]]
        return st.mean(ds), st.pstdev(ds), len(ds)

    print(f"\nbase GC = {mean('base')/3600:.2f} pax-h")
    print("%-14s %14s %12s" % ("project", "benefit(pax-h)", "sd(paired)"))
    single = {}
    for l in proj:
        b, sd, n = benefit(f"+{l}")
        single[l] = b
        print("%-14s %14.3f %12.3f" % (f"+{l}", b/3600, sd/3600))
    print("\npairwise interaction matrix (pax-h); "
          "interaction = benefit(i&j) - benefit(i) - benefit(j)")
    inter = {}
    for a, b_ in itertools.combinations(proj, 2):
        bp, sd, n = benefit(f"+{a}+{b_}")
        ii = bp - single[a] - single[b_]
        inter[f"{a}|{b_}"] = dict(pair_benefit=bp, sum_singles=single[a]+single[b_],
                                  interaction=ii,
                                  interaction_pct_of_sum=(100*ii/(single[a]+single[b_])
                                                          if abs(single[a]+single[b_]) > 1e-9
                                                          else None))
        print(f"  {a:5s} + {b_:5s}: pair {bp/3600:8.3f}  sum-of-singles "
              f"{(single[a]+single[b_])/3600:8.3f}  interaction {ii/3600:+8.3f} "
              f"({100*ii/(single[a]+single[b_]) if abs(single[a]+single[b_])>1e-9 else float('nan'):+7.1f}%)")
    med = st.median([abs(v["interaction"]) for v in inter.values()])
    print(f"\nmedian |interaction| = {med/3600:.3f} pax-h; "
          f"median |single benefit| = {st.median([abs(v) for v in single.values()])/3600:.3f} pax-h")
    with open(OUTJ, "w") as f:
        json.dump(dict(structure=STRUCT, B0=B0, seeds=SEEDS, base=base,
                       projects=proj, designs=designs,
                       values={k: {str(s): v for s, v in d.items()} for k, d in vals.items()},
                       single_benefit=single, interactions=inter,
                       median_abs_interaction=med), f, indent=1)
    print("written", OUTJ)


if __name__ == "__main__":
    main()
