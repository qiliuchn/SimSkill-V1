"""CRN-paired significance of every comparative claim made from the equal-budget
route-structure comparison, against the measured noise floor.

Also re-tests the ranking under the CENSORED (completed + still-travelling)
accounting, because that is where a ranking flip appears.
"""
import os, json, math, itertools, statistics as st
import tspcore as T
from tspcore import WORK
import harness as H

OUTJ = os.path.join(WORK, "stage4_significance.json")


def per_seed(d):
    out = {}
    for run in d["dirs"]:
        m = json.load(open(os.path.join(run, "metrics.json")))
        out[m["seed"]] = m
    return out


def main():
    s4 = H.load_json(os.path.join(WORK, "stage4_compare.json"))
    nf = H.load_json(os.path.join(WORK, "noise_floor.json"))
    ms = {n: per_seed(d) for n, d in s4["summary"].items()}
    seeds = sorted(set.intersection(*[set(v) for v in ms.values()]))
    sig = nf["sigma_pooled_near_optimal"]
    n = len(seeds)
    thr_ind = 1.96 * math.sqrt(2) * sig / math.sqrt(n)
    print(f"{n} common seeds; pooled sigma {sig/3600:.2f} pax-h; "
          f"independent-seed resolvable difference at n={n}: {thr_ind/3600:.2f} pax-h")
    rows = []
    for metric, fn in (("completed-only GC", lambda m: H.gc_total(m)),
                       ("censored-inclusive GC",
                        lambda m: H.gc_total(m, include_incomplete=True)),
                       ("ridership", lambda m: -m["n_riders"])):
        print(f"\n-- {metric} --")
        vals = {p: [fn(ms[p][s]) for s in seeds] for p in ms}
        for p in sorted(vals, key=lambda p: st.mean(vals[p])):
            u = "pax-h" if "GC" in metric else "riders"
            v = [x/3600 for x in vals[p]] if "GC" in metric else [-x for x in vals[p]]
            print(f"   {p:12s} mean {st.mean(v):9.2f} {u}  sd {st.pstdev(v):6.2f}")
        for a, b in itertools.combinations(sorted(vals), 2):
            ds = [x - y for x, y in zip(vals[a], vals[b])]
            m_, sd = st.mean(ds), st.pstdev(ds)
            se = sd / math.sqrt(n)
            t = m_ / se if se else float("inf")
            resolvable = abs(m_) > thr_ind if "GC" in metric else None
            sc = 3600 if "GC" in metric else 1
            print(f"   {a:12s} - {b:12s}: {m_/sc:+9.2f}  paired sd {sd/sc:6.2f}  "
                  f"t={t:+6.2f}  |diff| vs noise floor: "
                  f"{'RESOLVABLE' if resolvable else ('below floor' if resolvable is not None else 'n/a')}")
            rows.append(dict(metric=metric, a=a, b=b, diff=m_, paired_sd=sd, se=se,
                             t=t, resolvable_vs_noise_floor=resolvable))
    with open(OUTJ, "w") as f:
        json.dump(dict(seeds=seeds, sigma_pooled=sig, threshold=thr_ind, rows=rows), f, indent=1)
    print("\nwritten", OUTJ)


if __name__ == "__main__":
    main()
