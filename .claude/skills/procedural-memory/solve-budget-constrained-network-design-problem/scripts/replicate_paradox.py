#!/usr/bin/env python3
"""
Claim 2 (capacity paradox): does any single project INCREASE equilibrium TSTT
versus do-nothing, and is that real rather than seed noise?

Replication discipline follows construct-and-verify-braess-paradox /
scan-network-link-criticality-and-vulnerability: >=10 Common-Random-Numbers
paired seeds, a paired test (t-test + Wilcoxon), an effect size (Cohen's dz)
and a bootstrap CI on the paired difference.  Every arm is COLD-started
(14 duaIterate iterations, tail-4 objective) so no warm-start bias can be
blamed for the sign.  A positive control (the project with the largest single
benefit) is replicated too, to demonstrate the test can detect a real effect at
this replication count.

usage: replicate_paradox.py CAND1[,CAND2,...] CONTROL  [--seeds 10]
"""
import os, sys, json, shutil, csv, math, argparse, random
import statistics as st
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import mask_from_subset, PROJECT_IDS
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "paradox")
OUT = os.path.join(ROOT, "outputs")
TRIPS = os.path.join(ROOT, "work", "trips_main.xml")


def job(args):
    arm, mask, seed = args
    wd = os.path.join(WORK, "%s_s%d" % (arm, seed))
    shutil.rmtree(wd, ignore_errors=True)
    try:
        r = EV.score(mask, TRIPS, wd, seed=seed, dua_seed=seed,
                     last_step=EV.COLD_STEPS)
        r["error"] = None
    except Exception as e:
        r = dict(mask=mask, error=repr(e)[:300], tstt=None)
    r.update(arm=arm, seed=seed)
    shutil.rmtree(wd, ignore_errors=True)
    return r


def paired_stats(d):
    n = len(d)
    m = st.mean(d); s = st.stdev(d) if n > 1 else 0.0
    t = m / (s / math.sqrt(n)) if s > 0 else float("inf")
    # two-sided p from t with n-1 df, via scipy if present
    try:
        from scipy import stats as sps
        p = float(sps.t.sf(abs(t), n - 1) * 2)          # two-sided paired t
        try:
            wp = float(sps.wilcoxon(d).pvalue)          # two-sided signed-rank
        except Exception:
            wp = None
    except Exception:
        p, wp = None, None
    dz = m / s if s > 0 else float("inf")
    rng = random.Random(7)
    boots = []
    for _ in range(20000):
        boots.append(st.mean(rng.choice(d) for _ in range(n)))
    boots.sort()
    return dict(n=n, mean_diff=m, sd_diff=s, t=t, p_ttest=p, p_wilcoxon=wp,
                cohens_dz=dz,
                ci95_lo=boots[int(0.025 * len(boots))],
                ci95_hi=boots[int(0.975 * len(boots))],
                n_seeds_positive=sum(1 for x in d if x > 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("control")
    ap.add_argument("--seeds", type=int, default=10)
    a = ap.parse_args()
    cands = [c for c in a.candidates.split(",") if c]
    arms = {"base": 0}
    for c in cands:
        arms[c] = mask_from_subset([c])
    arms[a.control] = mask_from_subset([a.control])

    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    jobs = [(arm, m, s) for arm, m in arms.items() for s in range(1, a.seeds + 1)]
    with ProcessPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(job, jobs))
    tab = {}
    for r in res:
        tab.setdefault(r["arm"], {})[r["seed"]] = r
    rows, summ = [], []
    seeds = list(range(1, a.seeds + 1))
    for arm in arms:
        for s in seeds:
            r = tab[arm][s]
            rows.append(dict(arm=arm, seed=s, tstt=r.get("tstt"),
                             tstt_sd_tail=r.get("tstt_sd_tail"),
                             rel_gap=r.get("rel_gap_tail_mean"),
                             tt_stab=r.get("tt_stab"),
                             converged=r.get("converged"),
                             accounting_ok=r.get("accounting_ok"),
                             teleports_max=r.get("teleports_max"),
                             error=r.get("error")))
    with open(os.path.join(OUT, "paradox_replication_runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    for arm in arms:
        if arm == "base":
            continue
        d = [tab[arm][s]["tstt"] - tab["base"][s]["tstt"] for s in seeds]
        stt = paired_stats(d)
        stt.update(arm=arm,
                   mean_base=st.mean(tab["base"][s]["tstt"] for s in seeds),
                   mean_arm=st.mean(tab[arm][s]["tstt"] for s in seeds),
                   mean_diff_pct=100 * st.mean(d) / st.mean(tab["base"][s]["tstt"] for s in seeds),
                   paired_diffs=[round(x, 1) for x in d],
                   verdict=("HARMFUL (paradox)" if stt["ci95_lo"] > 0 else
                            "BENEFICIAL" if stt["ci95_hi"] < 0 else
                            "INDISTINGUISHABLE FROM ZERO"))
        summ.append(stt)
    with open(os.path.join(OUT, "paradox_replication_summary.json"), "w") as f:
        json.dump(summ, f, indent=2)

    print("%-5s %12s %12s %11s %8s %9s %9s %9s %10s %s" %
          ("arm", "mean_base", "mean_arm", "mean_diff", "diff_%", "p_ttest",
           "p_wilcox", "dz", "CI95", "verdict"))
    for s in summ:
        print("%-5s %12.0f %12.0f %+11.1f %+8.3f %9s %9s %9.3f  [%+.0f,%+.0f] %d/%d>0 %s" %
              (s["arm"], s["mean_base"], s["mean_arm"], s["mean_diff"],
               s["mean_diff_pct"],
               ("%.5f" % s["p_ttest"]) if s["p_ttest"] is not None else "n/a",
               ("%.5f" % s["p_wilcoxon"]) if s["p_wilcoxon"] is not None else "n/a",
               s["cohens_dz"], s["ci95_lo"], s["ci95_hi"],
               s["n_seeds_positive"], s["n"], s["verdict"]))


if __name__ == "__main__":
    main()
