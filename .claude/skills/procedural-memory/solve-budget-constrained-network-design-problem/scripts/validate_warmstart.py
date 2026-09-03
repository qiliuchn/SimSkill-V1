#!/usr/bin/env python3
"""
Benchmark and validate the evaluation protocol BEFORE launching the 1024-subset
search, as required by the evaluation-budget discipline.

For a sample of subsets, evaluate twice:
  COLD : duaIterate from the raw trip file, 20 iterations, tail-4 objective
  WARM : duaIterate restarted from the converged do-nothing equilibrium route
         file, 8 iterations, tail-4 objective
and compare TSTT, wall time and convergence measures.  If WARM reproduces COLD
within the tail oscillation noise it is the affordable way to buy 1024
equilibrium evaluations; if not, the enumeration must be cold-started (or
truncated) and that has to be stated up front.
"""
import os, sys, json, shutil, csv
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import mask_from_subset, subset_from_mask, subset_cost, NPROJ
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "warmval")
OUT = os.path.join(ROOT, "outputs")
TRIPS = os.path.join(ROOT, "work", "trips_main.xml")
WARM = os.path.join(ROOT, "work", "base_equilibrium.rou.xml.gz")

SAMPLE = [0] + [1 << k for k in range(NPROJ)] + [
    mask_from_subset(["L1", "L2", "L3"]),
    mask_from_subset(["NB", "L5", "N1"]),
    mask_from_subset(["L2", "L4", "L5", "N2"]),
    mask_from_subset(["L1", "L2", "L3", "L4", "L5", "L6", "L7"]),
]


def job(args):
    mask, mode = args
    wd = os.path.join(WORK, "%s_m%04d" % (mode, mask))
    shutil.rmtree(wd, ignore_errors=True)
    try:
        r = EV.score(mask, TRIPS, wd, seed=1,
                     warm_routes=(WARM if mode == "warm" else None),
                     last_step=(EV.WARM_STEPS if mode == "warm" else EV.COLD_STEPS))
        r["error"] = None
    except Exception as e:
        r = dict(mask=mask, error=repr(e)[:300])
    r["mode"] = mode
    r["subset"] = "+".join(subset_from_mask(mask)) or "(none)"
    shutil.rmtree(wd, ignore_errors=True)
    return r


def main():
    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    jobs = [(m, mode) for m in SAMPLE for mode in ("cold", "warm")]
    with ProcessPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(job, jobs))
    by = {}
    for r in res:
        by.setdefault(r["mask"], {})[r["mode"]] = r
    rows = []
    for m in SAMPLE:
        c, w = by[m].get("cold"), by[m].get("warm")
        if not c or not w or c.get("error") or w.get("error"):
            rows.append(dict(mask=m, subset=subset_from_mask(m),
                             error=(c or {}).get("error") or (w or {}).get("error")))
            continue
        rows.append(dict(
            mask=m, subset="+".join(subset_from_mask(m)) or "(none)",
            cold_tstt=c["tstt"], warm_tstt=w["tstt"],
            diff_s=round(w["tstt"] - c["tstt"], 1),
            diff_pct=round(100 * (w["tstt"] - c["tstt"]) / c["tstt"], 3),
            cold_sd_tail=c["tstt_sd_tail"], warm_sd_tail=w["tstt_sd_tail"],
            cold_sd_pct=round(100 * c["tstt_sd_tail"] / c["tstt"], 3),
            warm_sd_pct=round(100 * w["tstt_sd_tail"] / w["tstt"], 3),
            cold_gap=c["rel_gap_tail_mean"], warm_gap=w["rel_gap_tail_mean"],
            cold_ttstab=c["tt_stab"], warm_ttstab=w["tt_stab"],
            cold_wall_s=c["wall_s"], warm_wall_s=w["wall_s"],
            cold_conv=c["converged"], warm_conv=w["converged"],
            cold_acct=c["accounting_ok"], warm_acct=w["accounting_ok"]))
    with open(os.path.join(OUT, "warmstart_validation.csv"), "w", newline="") as f:
        keys = [k for k in rows[0]]
        wcsv = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        wcsv.writeheader(); wcsv.writerows(rows)
    with open(os.path.join(OUT, "warmstart_validation.json"), "w") as f:
        json.dump(dict(rows=rows, raw=res), f, indent=2)

    print("%-26s %11s %11s %9s %8s %8s %8s %8s %8s" %
          ("subset", "cold_TSTT", "warm_TSTT", "diff_%", "coldSD%", "warmSD%",
           "coldgap", "warmgap", "wall_c/w"))
    for r in rows:
        if r.get("error"):
            print(r["subset"], "ERROR", r["error"]); continue
        print("%-26s %11.0f %11.0f %+9.3f %8.3f %8.3f %8.4f %8.4f %4.0f/%-4.0f" %
              (r["subset"], r["cold_tstt"], r["warm_tstt"], r["diff_pct"],
               r["cold_sd_pct"], r["warm_sd_pct"], r["cold_gap"], r["warm_gap"],
               r["cold_wall_s"], r["warm_wall_s"]))
    good = [r for r in rows if not r.get("error")]
    import statistics as st
    print("\nmean |warm-cold| = %.3f%%   max = %.3f%%" %
          (st.mean(abs(r["diff_pct"]) for r in good),
           max(abs(r["diff_pct"]) for r in good)))
    print("mean tail SD: cold %.3f%%  warm %.3f%%" %
          (st.mean(r["cold_sd_pct"] for r in good),
           st.mean(r["warm_sd_pct"] for r in good)))
    print("mean wall: cold %.1f s  warm %.1f s  (speedup %.2fx)" %
          (st.mean(r["cold_wall_s"] for r in good),
           st.mean(r["warm_wall_s"] for r in good),
           st.mean(r["cold_wall_s"] for r in good) / st.mean(r["warm_wall_s"] for r in good)))
    # rank agreement on the sample
    import itertools
    cs = [r["cold_tstt"] for r in good]; ws = [r["warm_tstt"] for r in good]
    conc = sum(1 for a, b in itertools.combinations(range(len(good)), 2)
               if (cs[a] - cs[b]) * (ws[a] - ws[b]) > 0)
    tot = len(good) * (len(good) - 1) // 2
    print("pairwise rank agreement cold vs warm: %d/%d = %.1f%% (Kendall tau = %.3f)"
          % (conc, tot, 100 * conc / tot, 2.0 * conc / tot - 1))


if __name__ == "__main__":
    main()
