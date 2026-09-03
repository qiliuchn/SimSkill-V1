"""Stage 5 prerequisite: measure the NOISE FLOOR before optimizing anything
(protocol from `optimize-under-simulation-noise-with-a-fixed-budget`).

Evaluates several near-optimal allocations across many seeds, pools sigma over
the near-optimal set only, converts it into the minimum difference resolvable at
n replications, and measures what CRN pairing actually buys (rho).
"""
import os, sys, json, math, itertools, statistics as st
import tspcore as T
from tspcore import WORK
import plans as P
import harness as H
import alloc as A

BUDGET = int(os.environ.get("BUDGET", "24"))
STRUCT = os.environ.get("STRUCT", "trunkfeeder")
SEEDS = list(range(201, 221))          # noise-floor seed book (disjoint)
OUTJ = os.path.join(WORK, "noise_floor.json")


def perturb(buses, cycles, ids, moves):
    b = dict(buses)
    lo, hi = A.bounds(cycles, ids)
    for i, j in moves:
        if b[i] - 1 >= lo[i] and b[j] + 1 <= hi[j]:
            b[i] -= 1; b[j] += 1
    return b


def main():
    speeds = H.load_json(H.SPEED_FILE)
    cycles = H.load_json(H.CYCLE_FILE)[STRUCT]
    demand = H.load_json(os.path.join(WORK, "linedemand.json"))[STRUCT]
    ids = [l[0] for l in P.PLAN_DEFS[STRUCT]]
    base, ok, msg = A.sqrt_rule(BUDGET, cycles, demand, ids)
    assert ok, msg
    order = sorted(ids, key=lambda l: -demand[l])
    designs = {
        "sqrt": base,
        "near1": perturb(base, cycles, ids, [(order[-1], order[0])]),
        "near2": perturb(base, cycles, ids, [(order[0], order[-1])]),
    }
    eq, ok2, _ = A.equal_rule(BUDGET, cycles, ids)
    if ok2:
        designs["equal"] = eq
    print("designs:", json.dumps(designs))

    jobs, keys = [], []
    for dn, b in designs.items():
        for s in SEEDS:
            jobs.append((STRUCT, b, s, None, cycles, speeds[STRUCT],
                         f"nf_{STRUCT}_{dn}", False))
            keys.append((dn, s))
    print(f"{len(jobs)} runs")
    res = H.evaluate_many(jobs, workers=6)
    vals = {}
    for (dn, s), m in zip(keys, res):
        if "error" in m:
            print("ERR", m["error"]); continue
        vals.setdefault(dn, {})[s] = H.gc_total(m)

    out = dict(structure=STRUCT, budget=BUDGET, seeds=SEEDS, designs=designs,
               values={k: {str(s): v for s, v in d.items()} for k, d in vals.items()})
    stats = {}
    for dn, d in vals.items():
        a = list(d.values())
        stats[dn] = dict(mean=st.mean(a), sd=st.pstdev(a), cv=st.pstdev(a)/st.mean(a))
    out["per_design"] = stats
    print("\nper-design objective (total passenger generalized time, pax-h)")
    for dn, s_ in stats.items():
        print(f"  {dn:8s} mean {s_['mean']/3600:9.1f}  sd {s_['sd']/3600:7.2f}  "
              f"CV {s_['cv']*100:5.2f}%")

    # sigma pooled over the NEAR-OPTIMAL designs only
    near = [dn for dn in ("sqrt", "near1", "near2") if dn in stats]
    sig = math.sqrt(sum(stats[dn]["sd"] ** 2 for dn in near) / len(near))
    mu = st.mean([stats[dn]["mean"] for dn in near])
    out["sigma_pooled_near_optimal"] = sig
    out["mean_near_optimal"] = mu
    out["sigma_pooled_all"] = math.sqrt(sum(s_["sd"] ** 2 for s_ in stats.values())
                                        / len(stats))

    # correlations (what CRN buys)
    rho = {}
    for a, b in itertools.combinations(vals.keys(), 2):
        xs = [vals[a][s] for s in SEEDS if s in vals[a] and s in vals[b]]
        ys = [vals[b][s] for s in SEEDS if s in vals[a] and s in vals[b]]
        if len(xs) > 2:
            mx, my = st.mean(xs), st.mean(ys)
            num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
            den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
            r = num/den if den else 0.0
            dif_ind = [x - y for x, y in zip(xs, ys)]
            rho[f"{a}|{b}"] = dict(rho=r, var_reduction_analytic=1/(1-r) if r < 1 else None,
                                   sd_paired_diff=st.pstdev(dif_ind),
                                   sd_indep_diff=math.sqrt(st.pstdev(xs)**2+st.pstdev(ys)**2))
    out["crn"] = rho

    tab = {}
    for n in (1, 3, 5, 10, 20):
        tab[n] = dict(independent=1.96*math.sqrt(2)*sig/math.sqrt(n),
                      independent_pct=100*1.96*math.sqrt(2)*sig/math.sqrt(n)/mu)
    out["resolvable"] = tab
    print(f"\npooled sigma over near-optimal designs: {sig/3600:.2f} pax-h "
          f"({100*sig/mu:.2f}% of mean)")
    print("minimum resolvable difference (independent seeds):")
    for n, v in tab.items():
        print(f"  n={n:3d}: {v['independent']/3600:8.2f} pax-h  ({v['independent_pct']:5.2f}%)")
    print("\nCRN correlation between designs (paired on seed):")
    for k, v in rho.items():
        print(f"  {k:16s} rho={v['rho']:+.3f}  var-reduction {v['var_reduction_analytic']}"
              if v['var_reduction_analytic'] else f"  {k}: rho={v['rho']:+.3f}")
    with open(OUTJ, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
