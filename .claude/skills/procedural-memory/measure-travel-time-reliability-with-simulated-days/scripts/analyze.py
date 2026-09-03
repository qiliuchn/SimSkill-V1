#!/usr/bin/env python3
"""
Reliability analysis for the corridor-investment study.

Everything downstream of the SUMO runs lives here: the reliability-metric
suite, the paired cluster bootstrap, the variance decomposition, the
incident-probability / demand-CV reweighting, the teleport + censoring audit,
and the plots.

Statistical conventions
-----------------------
* The independent sampling unit is a DAY, not a vehicle.  Vehicles within a day
  are heavily correlated (they share a demand level, an incident and a seed),
  so every confidence interval comes from a **cluster (day) bootstrap**:
  resample the 60 day indices with replacement, and recompute the pooled
  statistic.  The SAME resampled day list is used for every scenario in a given
  replicate, which preserves Common Random Numbers and makes the difference
  CIs paired.
* Percentile-based metrics (p80, p95, PTI, Buffer Index, Misery Index) get
  bootstrap percentile CIs.  No t-test is used anywhere on a percentile --
  a t-test presumes a statistic that is an average of independent draws, which
  a sample quantile of clustered data is not.
* Travel time is DOOR-TO-DOOR: tripinfo `duration` + `departDelay`.  Excluding
  departDelay would hide the queue that forms at the corridor entrance on
  oversaturated days, i.e. would censor exactly the worst experiences.
"""
import csv
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from scipy.stats import norm             # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "outputs"))
os.makedirs(OUT, exist_ok=True)

SC = ["A_base", "B_capacity", "C_info", "D_shoulder"]
LBL = {"A_base": "A  Base", "B_capacity": "B  Corridor widening",
       "C_info": "C  Information (40%)", "D_shoulder": "D  Midblock shoulder"}
# dataviz reference categorical palette, slots 1/2/3/7 -- validated all-pairs
# (node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a,#4a3aa7"
#  --mode light --pairs all  ->  ALL CHECKS PASS)
COL = {"A_base": "#2a78d6", "B_capacity": "#eb6834",
       "C_info": "#1baf7a", "D_shoulder": "#4a3aa7"}
NBOOT = 1000
RNG = np.random.default_rng(7)

days = json.load(open(os.path.join(WORK, "days.json")))
seedrep = json.load(open(os.path.join(WORK, "seedrep.json")))
NDAY = len(days)
INC = np.array([d["incident"] for d in days], bool)
MULT = np.array([d["mult"] for d in days], float)


def cell(block, scen, tag):
    f = os.path.join(WORK, "runs", block, scen, tag, "corr_tt.npz")
    return np.load(f, allow_pickle=True)


def tt_of(block, scen, tag):
    """Door-to-door corridor travel time of every corridor vehicle."""
    d = cell(block, scen, tag)
    return (d["dur"] + d["departdelay"]).astype(np.float64), d["finished"]


# ------------------------------------------------------- free-flow reference
ff, _ = tt_of("FF", "A_base", "day000")
FFT = float(ff.min())
FFT_ANALYTIC = 4800.0 / 16.67


# ------------------------------------------------------------- metric suite
def metrics(v, w=None, fft=FFT):
    """Full reliability suite on a (optionally weighted) vehicle-level sample.
    `v` must be sorted ascending and `w` aligned with it."""
    if w is None:
        w = np.ones_like(v)
    tot = w.sum()
    cw = np.cumsum(w)

    def q(p):
        return float(v[min(np.searchsorted(cw, p * tot), len(v) - 1)])

    mean = float((w * v).sum() / tot)
    p50, p80, p95 = q(.50), q(.80), q(.95)
    i95 = min(np.searchsorted(cw, .95 * tot), len(v) - 1)
    wt = w[i95:]
    misery = float((wt * v[i95:]).sum() / wt.sum()) if wt.sum() > 0 else np.nan
    return dict(
        mean=mean, median=p50, p80=p80, p95=p95,
        TTI=mean / fft, PTI=p95 / fft, BI=(p95 - mean) / mean,
        BI_median=(p95 - p50) / p50,
        MiseryIndex=misery, MI_ratio=misery / fft,
        ontime_1p10_ff=float((w * (v <= 1.10 * fft)).sum() / tot),
        ontime_1p25_ff=float((w * (v <= 1.25 * fft)).sum() / tot),
        ontime_1p10_med=float((w * (v <= 1.10 * p50)).sum() / tot),
        ontime_1p25_med=float((w * (v <= 1.25 * p50)).sum() / tot),
    )


METRIC_KEYS = ["mean", "median", "p80", "p95", "TTI", "PTI", "BI",
               "BI_median", "MiseryIndex", "MI_ratio", "ontime_1p10_ff",
               "ontime_1p25_ff", "ontime_1p10_med", "ontime_1p25_med"]


class Pool:
    """Vehicle-level pooled sample for one scenario, sorted once, with each
    vehicle tagged by its day so that a day-cluster bootstrap is a cheap
    re-weighting rather than a re-concatenation."""

    def __init__(self, scen, block="FULL", day_ids=None):
        day_ids = range(NDAY) if day_ids is None else day_ids
        vs, ls, fs = [], [], []
        for i in day_ids:
            v, fin = tt_of(block, scen, "day%03d" % i)
            vs.append(v)
            fs.append(fin)
            ls.append(np.full(len(v), i, np.int32))
        v = np.concatenate(vs)
        lab = np.concatenate(ls)
        o = np.argsort(v, kind="stable")
        self.v = v[o]
        self.lab = lab[o]
        self.n = len(v)
        self.finished_all = int(np.concatenate(fs).sum())

    def m(self, daycount=None, dayweight=None):
        if daycount is None and dayweight is None:
            return metrics(self.v)
        w = (daycount if dayweight is None else dayweight)[self.lab]
        w = w.astype(np.float64)
        keep = w > 0
        return metrics(self.v[keep], w[keep])


def boot_day_indices(nboot=NBOOT, n=NDAY):
    return RNG.integers(0, n, size=(nboot, n))


def counts_from(idx, n=NDAY):
    return np.bincount(idx, minlength=n).astype(np.float64)


def ci(a, lo=2.5, hi=97.5):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return float(np.percentile(a, lo)), float(np.percentile(a, hi))


# ============================================================== main analysis
def main():
    log = []

    def say(s=""):
        print(s)
        log.append(str(s))

    say("free-flow reference: empirical min corridor tt at 2% demand = "
        f"{FFT:.1f} s  (analytic 4800 m / 16.67 m/s = {FFT_ANALYTIC:.1f} s "
        "plus signal + junction time)")

    # ---------------------------------------------------- 1. day-draw audit
    sig = np.sqrt(np.log(1 + 0.20 ** 2))
    dd_rows = []
    for d in days:
        dd_rows.append(d)
    with open(os.path.join(OUT, "day_draws.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(days[0].keys()))
        w.writeheader()
        w.writerows(days)
    lm = np.log(MULT)
    audit = dict(
        n_days=NDAY, target_E_mult=1.0, realised_E_mult=float(MULT.mean()),
        target_CV=0.20,
        realised_CV=float(MULT.std(ddof=1) / MULT.mean()),
        target_sigma_log=float(sig), realised_sd_log=float(lm.std(ddof=1)),
        realised_mean_log=float(lm.mean()), target_mu_log=float(-sig ** 2 / 2),
        target_p_incident=0.25, realised_p_incident=float(INC.mean()),
        binom_95CI_lo=float(INC.mean() - 1.96 * np.sqrt(.25 * .75 / NDAY)),
        binom_95CI_hi=float(INC.mean() + 1.96 * np.sqrt(.25 * .75 / NDAY)),
        n_incident_days=int(INC.sum()),
        inc_lanes_1=sum(1 for d in days if d["inc_lanes"] == 1),
        inc_lanes_2=sum(1 for d in days if d["inc_lanes"] == 2),
        inc_edge_CB1=sum(1 for d in days if d["inc_edge"] == "CB1"),
        inc_edge_CB2=sum(1 for d in days if d["inc_edge"] == "CB2"),
        inc_start_min=min((d["inc_start"] for d in days if d["incident"])),
        inc_start_max=max((d["inc_start"] for d in days if d["incident"])),
        inc_dur_min=min((d["inc_dur"] for d in days if d["incident"])),
        inc_dur_max=max((d["inc_dur"] for d in days if d["incident"])),
        mult_min=float(MULT.min()), mult_max=float(MULT.max()))
    json.dump(audit, open(os.path.join(OUT, "day_draw_audit.json"), "w"),
              indent=1)
    say("\n== day-draw realised distribution ==")
    for k, v in audit.items():
        say(f"   {k:22s} {v}")

    # ---------------------------------------------- 2. per-day metrics table
    pools = {s: Pool(s) for s in SC}
    perday = []
    daily = {s: np.zeros(NDAY) for s in SC}
    daily_p95 = {s: np.zeros(NDAY) for s in SC}
    cells = {}
    for r in csv.DictReader(open(os.path.join(WORK, "cells.csv"))):
        cells[(r["block"], r["scenario"], int(r["day"]))] = r
    for s in SC:
        for i, d in enumerate(days):
            v, fin = tt_of("FULL", s, "day%03d" % i)
            dur = cell("FULL", s, "day%03d" % i)["dur"]
            c = cells[("FULL", s, i)]
            m = metrics(np.sort(v))
            daily[s][i] = m["mean"]
            daily_p95[s][i] = m["p95"]
            perday.append(dict(
                scenario=s, day=i, mult=d["mult"], incident=d["incident"],
                inc_lanes=d["inc_lanes"], inc_edge=d["inc_edge"],
                inc_start=d["inc_start"], inc_dur=d["inc_dur"],
                seed=d["seed"], n_corr=len(v),
                n_unfinished=int((fin == 0).sum()),
                not_inserted=int(c["not_inserted"]),
                teleports=int(c["teleports"]),
                teleport_corr_veh=int(c["teleport_corr_veh"]),
                detour_entries=float(c["ap_entered"]),
                mean_tt=round(m["mean"], 2),
                mean_tt_innetwork=round(float(dur.mean()), 2),
                median_tt=round(m["median"], 2), p80_tt=round(m["p80"], 2),
                p95_tt=round(m["p95"], 2),
                misery=round(m["MiseryIndex"], 2),
                TTI=round(m["TTI"], 4), PTI=round(m["PTI"], 4),
                BI=round(m["BI"], 4)))
    with open(os.path.join(OUT, "per_day_metrics.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(perday[0].keys()))
        w.writeheader()
        w.writerows(perday)
    say(f"\nwrote per_day_metrics.csv ({len(perday)} rows)")

    # ------------------------------------- 3. reliability table + bootstrap
    BIDX = boot_day_indices()
    subsets = {"all": np.arange(NDAY),
               "no_incident_days": np.where(~INC)[0],
               "incident_days": np.where(INC)[0]}
    pool_sub = {}
    for name, ids in subsets.items():
        for s in SC:
            pool_sub[(name, s)] = (pools[s] if name == "all"
                                   else Pool(s, day_ids=ids))

    rows = []
    boot_store = {}
    sub_boot = {}
    for name, ids in subsets.items():
        # ONE bootstrap resample of days per subset, shared by every scenario
        # (paired / CRN-preserving) and reused for the difference CIs below.
        sub_b = RNG.integers(0, len(ids), size=(NBOOT, len(ids)))
        sub_boot[name] = sub_b
        for s in SC:
            P = pool_sub[(name, s)]
            pt = P.m()
            reps = {k: np.empty(NBOOT) for k in METRIC_KEYS}
            for b in range(NBOOT):
                c = np.zeros(NDAY)
                np.add.at(c, ids[sub_b[b]], 1.0)
                mm = P.m(daycount=c)
                for k in METRIC_KEYS:
                    reps[k][b] = mm[k]
            boot_store[(name, s)] = reps
            for k in METRIC_KEYS:
                lo, hi = ci(reps[k])
                rows.append(dict(level="vehicle", subset=name, scenario=s,
                                 metric=k, value=round(pt[k], 4),
                                 ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                                 n_vehicles=P.n, n_days=len(ids),
                                 method="day-cluster bootstrap percentile CI, "
                                        f"B={NBOOT}"))
    # day level
    for s in SC:
        for name, ids in subsets.items():
            dm = daily[s][ids]
            dp = daily_p95[s][ids]
            sub_b = RNG.integers(0, len(ids), size=(NBOOT, len(ids)))
            defs = {
                "day_mean_of_daily_means": lambda x: x.mean(),
                "day_median_of_daily_means": lambda x: np.median(x),
                "day_p80_of_daily_means": lambda x: np.percentile(x, 80),
                "day_p95_of_daily_means": lambda x: np.percentile(x, 95),
                "day_sd_of_daily_means": lambda x: x.std(ddof=1),
                "day_cv_of_daily_means": lambda x: x.std(ddof=1) / x.mean(),
                "day_TTI": lambda x: x.mean() / FFT,
                "day_PTI": lambda x: np.percentile(x, 95) / FFT,
                "day_BI": lambda x: (np.percentile(x, 95) - x.mean()) / x.mean(),
                "day_MiseryIndex":
                    lambda x: x[x >= np.percentile(x, 95)].mean(),
                "day_worst5pct_share":
                    lambda x: float((x > 1.5 * FFT).mean()),
            }
            for k, fn in defs.items():
                pt = float(fn(dm))
                rep = np.array([fn(dm[sub_b[b]]) for b in range(NBOOT)])
                lo, hi = ci(rep)
                rows.append(dict(level="day", subset=name, scenario=s,
                                 metric=k, value=round(pt, 4),
                                 ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                                 n_vehicles="", n_days=len(ids),
                                 method="day bootstrap percentile CI, "
                                        f"B={NBOOT}"))
            pt = float(np.percentile(dp, 95))
            rows.append(dict(level="day", subset=name, scenario=s,
                             metric="day_p95_of_daily_p95", value=round(pt, 4),
                             ci_lo="", ci_hi="", n_vehicles="",
                             n_days=len(ids), method="point estimate"))
    with open(os.path.join(OUT, "reliability_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    say(f"wrote reliability_table.csv ({len(rows)} rows)")

    say(f"\n== vehicle-level pooled reliability (all {NDAY} days) ==")
    say(f"{'scenario':<12}{'mean':>9}{'median':>9}{'p80':>9}{'p95':>10}"
        f"{'TTI':>7}{'PTI':>7}{'BI':>7}{'Misery':>9}{'on-time<=1.25FF':>17}")
    for s in SC:
        m = pool_sub[("all", s)].m()
        say(f"{s:<12}{m['mean']:9.1f}{m['median']:9.1f}{m['p80']:9.1f}"
            f"{m['p95']:10.1f}{m['TTI']:7.3f}{m['PTI']:7.3f}{m['BI']:7.3f}"
            f"{m['MiseryIndex']:9.1f}{m['ontime_1p25_ff']:17.3f}")

    # --------------------------------- 4. paired differences (CRN, bootstrap)
    diffs = []
    pairs = [("A_base", "B_capacity"), ("A_base", "C_info"),
             ("A_base", "D_shoulder"), ("C_info", "D_shoulder"),
             ("B_capacity", "C_info"), ("B_capacity", "D_shoulder")]
    for name, ids in subsets.items():
        # the replicates from section 3 already used ONE shared day resample
        # per subset, so differencing them is exactly the paired bootstrap
        cache = {s: boot_store[(name, s)] for s in SC}
        for a, b_ in pairs:
            pa, pb = pool_sub[(name, a)].m(), pool_sub[(name, b_)].m()
            for k in METRIC_KEYS:
                d = cache[b_][k] - cache[a][k]
                lo, hi = ci(d)
                pt = pb[k] - pa[k]
                diffs.append(dict(
                    subset=name, base=a, treatment=b_, metric=k,
                    base_value=round(pa[k], 4), treat_value=round(pb[k], 4),
                    diff=round(pt, 4), pct_change=round(
                        100 * pt / pa[k], 3) if pa[k] else "",
                    ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                    frac_boot_negative=round(float((d < 0).mean()), 4),
                    significant_95=int(lo > 0 or hi < 0),
                    method=f"paired day-cluster bootstrap, B={NBOOT}"))
    with open(os.path.join(OUT, "paired_differences.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(diffs[0].keys()))
        w.writeheader()
        w.writerows(diffs)
    say(f"wrote paired_differences.csv ({len(diffs)} rows)")

    # ---- 4b. systematic scan for metric RANKING disagreements ------------
    # A reliability metric ranks two scenarios; different metrics can rank
    # them differently.  Only disagreements where BOTH differences are
    # significant at 95% under the paired day-cluster bootstrap are counted.
    LOWER_BETTER = {"mean", "median", "p80", "p95", "TTI", "PTI", "BI",
                    "BI_median", "MiseryIndex", "MI_ratio"}
    dmap = {}
    for r in diffs:
        dmap[(r["subset"], r["base"], r["treatment"], r["metric"])] = r
    dis_rows = []
    for name in subsets:
        for a, b_ in pairs:
            better = {}
            for k in METRIC_KEYS:
                r = dmap[(name, a, b_, k)]
                if not r["significant_95"]:
                    continue
                d = r["diff"]
                better[k] = (d < 0) if k in LOWER_BETTER else (d > 0)
            ks = sorted(better)
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    if better[ks[i]] != better[ks[j]]:
                        m1, m2 = ks[i], ks[j]
                        dis_rows.append(dict(
                            subset=name, scenario_1=a, scenario_2=b_,
                            metric_1=m1,
                            metric_1_prefers=(b_ if better[m1] else a),
                            metric_1_pct_change=dmap[(name, a, b_, m1)]
                            ["pct_change"],
                            metric_1_ci=f"[{dmap[(name,a,b_,m1)]['ci_lo']},"
                                        f"{dmap[(name,a,b_,m1)]['ci_hi']}]",
                            metric_2=m2,
                            metric_2_prefers=(b_ if better[m2] else a),
                            metric_2_pct_change=dmap[(name, a, b_, m2)]
                            ["pct_change"],
                            metric_2_ci=f"[{dmap[(name,a,b_,m2)]['ci_lo']},"
                                        f"{dmap[(name,a,b_,m2)]['ci_hi']}]"))
    if dis_rows:
        with open(os.path.join(OUT, "metric_ranking_disagreements.csv"), "w",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(dis_rows[0].keys()))
            w.writeheader()
            w.writerows(dis_rows)
    say(f"\n== metric ranking disagreements (both sides significant at 95%) "
        f"==\n   {len(dis_rows)} disagreeing metric pairs found")
    seen = set()
    for r in dis_rows:
        key = (r["subset"], r["scenario_1"], r["scenario_2"],
               r["metric_1"], r["metric_2"])
        if key in seen:
            continue
        seen.add(key)
        say(f"   [{r['subset']}] {r['scenario_1']} vs {r['scenario_2']}: "
            f"{r['metric_1']} prefers {r['metric_1_prefers']} "
            f"({r['metric_1_pct_change']}%), but {r['metric_2']} prefers "
            f"{r['metric_2_prefers']} ({r['metric_2_pct_change']}%)")

    # ---- 4c. the ranking of all four scenarios under each metric ---------
    rk_rows = []
    for name in subsets:
        for k in METRIC_KEYS:
            vals = {s: pool_sub[(name, s)].m()[k] for s in SC}
            order = sorted(SC, key=lambda s: (vals[s] if k in LOWER_BETTER
                                              else -vals[s]))
            rk_rows.append(dict(subset=name, metric=k,
                                best_to_worst=" > ".join(
                                    x.split("_")[0] for x in order),
                                values=" ".join(f"{x.split('_')[0]}="
                                                f"{vals[x]:.3f}"
                                                for x in order)))
    with open(os.path.join(OUT, "scenario_ranking_by_metric.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rk_rows[0].keys()))
        w.writeheader()
        w.writerows(rk_rows)

    # ------------------------------------------- 5. variance decomposition
    say("\n== variance decomposition (day-level daily-mean travel time) ==")
    levels = seedrep["levels"]
    nrep = 6
    vd_rows = []
    seedvar_curve = {s: [] for s in SC}
    for s in SC:
        T_full = daily[s]
        T_dem = np.array([tt_of("DEMAND", s, "day%03d" % i)[0].mean()
                          for i in range(NDAY)])
        within = []
        for k in range(len(levels)):
            vals = np.array([tt_of("SEEDREP", s, "s%02dr%d" % (k, r))[0].mean()
                             for r in range(nrep)])
            within.append(vals.var(ddof=1))
            seedvar_curve[s].append((levels[k], float(vals.mean()),
                                     float(vals.std(ddof=1))))
        var_seed = float(np.mean(within))
        var_dem_block = float(T_dem.var(ddof=1))
        var_total = float(T_full.var(ddof=1))
        delta = T_full - T_dem
        var_demand_pure = var_dem_block - var_seed
        var_incident = var_total - var_dem_block
        # also the pinned-demand SEED block, for reference
        seed_pinned = np.array([tt_of("SEED", s, "day%03d" % i)[0].mean()
                                for i in range(24)])
        vd_rows.append(dict(
            scenario=s,
            var_total_FULL=round(var_total, 2),
            sd_total_FULL=round(np.sqrt(var_total), 2),
            var_DEMAND_block=round(var_dem_block, 2),
            var_seed_floor_SEEDREP=round(var_seed, 2),
            sd_seed_floor=round(np.sqrt(var_seed), 2),
            var_seed_pinned_m1_SEEDblock=round(
                float(seed_pinned.var(ddof=1)), 2),
            var_demand_pure=round(var_demand_pure, 2),
            var_incident=round(var_incident, 2),
            frac_seed=round(var_seed / var_total, 4),
            frac_demand=round(var_demand_pure / var_total, 4),
            frac_incident=round(var_incident / var_total, 4),
            check_sum=round((var_seed + var_demand_pure + var_incident)
                            / var_total, 6),
            mean_incident_effect=round(float(delta.mean()), 2),
            var_of_incident_delta=round(float(delta.var(ddof=1)), 2),
            cov_term=round(2 * float(np.cov(T_dem, delta)[0, 1]), 2)))
        say(f"   {s:<12} Var_total={var_total:9.1f}  seed={var_seed:8.1f}"
            f" ({100*var_seed/var_total:5.1f}%)  demand="
            f"{var_demand_pure:9.1f} ({100*var_demand_pure/var_total:5.1f}%)"
            f"  incident={var_incident:9.1f}"
            f" ({100*var_incident/var_total:5.1f}%)")
    with open(os.path.join(OUT, "variance_decomposition.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(vd_rows[0].keys()))
        w.writeheader()
        w.writerows(vd_rows)
    with open(os.path.join(OUT, "seed_noise_by_demand_level.csv"), "w",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "demand_multiplier", "mean_daily_mean_tt",
                    "sd_over_6_seeds", "cv_over_6_seeds"])
        for s in SC:
            for m_, mu_, sd_ in seedvar_curve[s]:
                w.writerow([s, round(m_, 4), round(mu_, 2), round(sd_, 3),
                            round(sd_ / mu_, 5)])

    # ---------------------------- 6. incident-probability reweighting (Q1)
    say("\n== ranking crossover vs incident probability ==")
    p_hat = float(INC.mean())
    grid = np.linspace(0.0, 1.0, 101)
    cross_rows = []
    curves = {s: {"mean": [], "p95": [], "PTI": [], "BI": []} for s in SC}
    for p in grid:
        w_day = np.where(INC, p / p_hat, (1 - p) / (1 - p_hat))
        for s in SC:
            m = pools[s].m(dayweight=w_day)
            for k in ("mean", "p95", "PTI", "BI"):
                curves[s][k].append(m[k])
            cross_rows.append(dict(p_incident=round(float(p), 3), scenario=s,
                                   mean=round(m["mean"], 2),
                                   p95=round(m["p95"], 2),
                                   PTI=round(m["PTI"], 4),
                                   BI=round(m["BI"], 4)))
    with open(os.path.join(OUT, "crossover_vs_incident_probability.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cross_rows[0].keys()))
        w.writeheader()
        w.writerows(cross_rows)

    def crossing(a, b, key):
        ya = np.array(curves[a][key])
        yb = np.array(curves[b][key])
        d = yb - ya
        sgn = np.sign(d)
        idx = np.where(np.diff(sgn) != 0)[0]
        return [float(grid[i] + (grid[i + 1] - grid[i]) * abs(d[i]) /
                      (abs(d[i]) + abs(d[i + 1]))) for i in idx]

    cross_summary = []
    for a, b_ in pairs:
        for key in ("mean", "p95", "PTI"):
            xs = crossing(a, b_, key)
            cross_summary.append(dict(pair=f"{a} vs {b_}", metric=key,
                                      crossings=";".join(f"{x:.3f}"
                                                         for x in xs)))
            if xs:
                say(f"   {a} vs {b_:<12} {key:<5} crosses at p_incident = "
                    + ", ".join(f"{x:.3f}" for x in xs))
    # bootstrap CI on the C-vs-D crossover points AND, crucially, on their
    # DIFFERENCE -- the width of the window in which the mean and the tail
    # rank the two treatments oppositely.  Comparing two wide marginal CIs is
    # not a test of whether the window exists; the paired difference is.
    NCB = 250
    gridc = np.linspace(0, 1, 21)
    boot_cross = {"mean": [], "p95": []}
    boot_gap = []
    disagree = np.zeros(len(gridc))
    for b in range(NCB):
        c = counts_from(BIDX[b])
        cm = {}
        for s in ("C_info", "D_shoulder"):
            cm[s] = {"mean": [], "p95": []}
            for p in gridc:
                wd = np.where(INC, p / p_hat, (1 - p) / (1 - p_hat)) * c
                mm = pools[s].m(dayweight=wd)
                cm[s]["mean"].append(mm["mean"])
                cm[s]["p95"].append(mm["p95"])
        dmean = (np.array(cm["D_shoulder"]["mean"])
                 - np.array(cm["C_info"]["mean"]))
        dp95 = (np.array(cm["D_shoulder"]["p95"])
                - np.array(cm["C_info"]["p95"]))
        disagree += (dmean * dp95 < 0)
        got = {}
        for key in ("mean", "p95"):
            d = np.array(cm["D_shoulder"][key]) - np.array(cm["C_info"][key])
            ii = np.where(np.diff(np.sign(d)) != 0)[0]
            if len(ii):
                i = ii[0]
                x = gridc[i] + (gridc[i + 1] - gridc[i]) * abs(d[i]) / (
                    abs(d[i]) + abs(d[i + 1]))
                boot_cross[key].append(x)
                got[key] = x
        if len(got) == 2:
            boot_gap.append(got["p95"] - got["mean"])
    for key in ("mean", "p95"):
        if boot_cross[key]:
            lo, hi = ci(boot_cross[key])
            say(f"   C vs D crossover in {key}: point "
                f"{crossing('C_info','D_shoulder',key)}  "
                f"bootstrap 95% CI [{lo:.3f}, {hi:.3f}] "
                f"({len(boot_cross[key])}/{NCB} replicates had a crossing)")
            cross_summary.append(dict(
                pair="C_info vs D_shoulder", metric=key + "_bootCI",
                crossings=f"[{lo:.3f},{hi:.3f}] from "
                          f"{len(boot_cross[key])}/{NCB} reps"))
    if boot_gap:
        g = np.array(boot_gap)
        lo, hi = ci(g)
        say(f"   PAIRED difference (p*_p95 - p*_mean): point "
            f"{crossing('C_info','D_shoulder','p95')[0] - crossing('C_info','D_shoulder','mean')[0]:+.4f}"
            f"  bootstrap 95% CI [{lo:+.4f}, {hi:+.4f}]  "
            f"P(gap>0)={float((g > 0).mean()):.3f}  n={len(g)}")
        cross_summary.append(dict(
            pair="C_info vs D_shoulder", metric="crossover_gap_p95_minus_mean",
            crossings=f"point {crossing('C_info','D_shoulder','p95')[0] - crossing('C_info','D_shoulder','mean')[0]:+.4f}"
                      f"; 95% CI [{lo:+.4f},{hi:+.4f}]; "
                      f"P(gap>0)={float((g > 0).mean()):.3f}"))
        json.dump(dict(gap=[float(x) for x in g]),
                  open(os.path.join(OUT, "crossover_gap_bootstrap.json"), "w"))
    # A more powerful and more direct test of "do the two metrics disagree?":
    # at each assumed incident rate, the bootstrap probability that the mean
    # and the 95th percentile rank C and D in OPPOSITE directions.
    dis = disagree / NCB
    dis_rows = []
    for j, p in enumerate(gridc):
        w_day = np.where(INC, p / p_hat, (1 - p) / (1 - p_hat))
        mc = pools["C_info"].m(dayweight=w_day)
        md = pools["D_shoulder"].m(dayweight=w_day)
        pointdis = int((md["mean"] - mc["mean"]) * (md["p95"] - mc["p95"]) < 0)
        dis_rows.append(dict(
            p_incident=round(float(p), 3),
            C_mean=round(mc["mean"], 1), D_mean=round(md["mean"], 1),
            C_p95=round(mc["p95"], 1), D_p95=round(md["p95"], 1),
            point_estimate_metrics_disagree=pointdis,
            bootstrap_P_metrics_disagree=round(float(dis[j]), 4)))
    with open(os.path.join(OUT, "metric_disagreement_vs_p.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dis_rows[0].keys()))
        w.writeheader()
        w.writerows(dis_rows)
    jbest = int(np.argmax(dis))
    say(f"   direct test -- P(mean and p95 rank C vs D OPPOSITELY) peaks at "
        f"p_incident={gridc[jbest]:.2f} with P={dis[jbest]:.3f}; "
        f"point-estimate disagreement holds at p in "
        + str([round(float(gridc[j]), 2) for j in range(len(gridc))
               if dis_rows[j]["point_estimate_metrics_disagree"]]))
    with open(os.path.join(OUT, "crossover_summary.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pair", "metric", "crossings"])
        w.writeheader()
        w.writerows(cross_summary)

    # ------------------------- 6b. demand-CV reweighting (importance sampling)
    cv0 = 0.20
    s0 = np.sqrt(np.log(1 + cv0 ** 2))
    m0 = -s0 ** 2 / 2
    cv_rows = []
    for cvx in np.arange(0.10, 0.325, 0.025):
        s1 = np.sqrt(np.log(1 + cvx ** 2))
        m1 = -s1 ** 2 / 2
        lw = (norm.logpdf(np.log(MULT), m1, s1)
              - norm.logpdf(np.log(MULT), m0, s0))
        w_ = np.exp(lw - lw.max())
        w_ = w_ / w_.sum()
        ess = float(1.0 / (w_ ** 2).sum())
        for s in SC:
            m = pools[s].m(dayweight=w_ * NDAY)
            cv_rows.append(dict(demand_CV=round(float(cvx), 3), ESS_days=round(
                ess, 1), scenario=s, mean=round(m["mean"], 2),
                p95=round(m["p95"], 2), PTI=round(m["PTI"], 4),
                BI=round(m["BI"], 4)))
    with open(os.path.join(OUT, "crossover_vs_demand_cv.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cv_rows[0].keys()))
        w.writeheader()
        w.writerows(cv_rows)

    # ------------------- 6c. what a naive seed-only study would have claimed
    say("\n== what a study that mistook seed noise for reliability "
        "would report ==")
    naive_rows = []
    for s in SC:
        sd_pin = np.array([tt_of("SEED", s, "day%03d" % i)[0].mean()
                           for i in range(24)])
        vs = np.sort(np.concatenate([tt_of("SEED", s, "day%03d" % i)[0]
                                     for i in range(24)]))
        m_seed = metrics(vs)
        real = [r for r in vd_rows if r["scenario"] == s][0]
        sd_tot = np.sqrt(real["var_total_FULL"])
        sd_seedfloor = np.sqrt(real["var_seed_floor_SEEDREP"])
        pooled = pool_sub[("all", s)].m()
        naive_rows.append(dict(
            scenario=s,
            # (a) demand pinned at 1.0, incidents off: only the seed varies
            seedonly_day_mean=round(float(sd_pin.mean()), 2),
            seedonly_day_sd=round(float(sd_pin.std(ddof=1)), 3),
            seedonly_day_cv=round(float(sd_pin.std(ddof=1) / sd_pin.mean()), 5),
            seedonly_vehicle_PTI=round(m_seed["PTI"], 4),
            seedonly_vehicle_BI=round(m_seed["BI"], 4),
            # (b) the real study
            full_day_sd=round(float(sd_tot), 2),
            full_vehicle_PTI=round(pooled["PTI"], 4),
            full_vehicle_BI=round(pooled["BI"], 4),
            # (c) how much of the real study's day-level sd is artefact
            seed_share_of_var=round(real["frac_seed"], 5),
            sd_overreport_pct=round(100 * (sd_tot / np.sqrt(
                max(real["var_total_FULL"] - real["var_seed_floor_SEEDREP"],
                    1e-9)) - 1), 4),
            seedonly_share_of_full_day_sd=round(
                float(sd_seedfloor / sd_tot), 4)))
        say(f"   {s:<12} seed-only day-level CV="
            f"{sd_pin.std(ddof=1)/sd_pin.mean():.4f} "
            f"(100% artefact) | seed share of Var(daily mean) in the real "
            f"study = {100*real['frac_seed']:.1f}% -> day-level sd "
            f"over-reported by {100*(sd_tot/np.sqrt(max(real['var_total_FULL']-real['var_seed_floor_SEEDREP'],1e-9))-1):.2f}%")
    with open(os.path.join(OUT, "seed_noise_overreporting.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(naive_rows[0].keys()))
        w.writeheader()
        w.writerows(naive_rows)

    # ------------------------------------------ 7. Buffer-Index paradox hunt
    say("\n== Buffer-Index paradox search ==")
    par_rows = []
    # 7a. across reweighted incident probabilities (vehicle level)
    for p in grid:
        w_day = np.where(INC, p / p_hat, (1 - p) / (1 - p_hat))
        mm = {s: pools[s].m(dayweight=w_day) for s in SC}
        for a, b_ in pairs:
            pa, pb = mm[a], mm[b_]
            par_rows.append(dict(
                level="vehicle", subset=f"reweighted_p={p:.2f}", base=a,
                treatment=b_,
                d_mean_pct=round(100 * (pb["mean"] - pa["mean"]) / pa["mean"],
                                 3),
                d_p95_pct=round(100 * (pb["p95"] - pa["p95"]) / pa["p95"], 3),
                d_BI=round(pb["BI"] - pa["BI"], 4),
                paradox=int(pb["mean"] < pa["mean"] and pb["p95"] < pa["p95"]
                            and pb["BI"] > pa["BI"])))
    # 7b. within demand terciles (vehicle level)
    ter = np.quantile(MULT, [1 / 3, 2 / 3])
    for tname, sel in (("demand_low", MULT <= ter[0]),
                       ("demand_mid", (MULT > ter[0]) & (MULT <= ter[1])),
                       ("demand_high", MULT > ter[1])):
        w_day = sel.astype(float)
        mm = {s: pools[s].m(dayweight=w_day) for s in SC}
        for a, b_ in pairs:
            pa, pb = mm[a], mm[b_]
            par_rows.append(dict(
                level="vehicle", subset=tname, base=a, treatment=b_,
                d_mean_pct=round(100 * (pb["mean"] - pa["mean"]) / pa["mean"],
                                 3),
                d_p95_pct=round(100 * (pb["p95"] - pa["p95"]) / pa["p95"], 3),
                d_BI=round(pb["BI"] - pa["BI"], 4),
                paradox=int(pb["mean"] < pa["mean"] and pb["p95"] < pa["p95"]
                            and pb["BI"] > pa["BI"])))
    for name in subsets:
        for a, b_ in pairs:
            pa = pool_sub[(name, a)].m()
            pb = pool_sub[(name, b_)].m()
            par_rows.append(dict(level="vehicle", subset=name, base=a,
                                 treatment=b_,
                                 d_mean_pct=round(100*(pb["mean"]-pa["mean"])
                                                  / pa["mean"], 3),
                                 d_p95_pct=round(100*(pb["p95"]-pa["p95"])
                                                 / pa["p95"], 3),
                                 d_BI=round(pb["BI"]-pa["BI"], 4),
                                 paradox=int(pb["mean"] < pa["mean"] and
                                             pb["p95"] < pa["p95"] and
                                             pb["BI"] > pa["BI"])))
    for a, b_ in pairs:
        for name, ids in subsets.items():
            ma, mb = daily[a][ids].mean(), daily[b_][ids].mean()
            qa = np.percentile(daily[a][ids], 95)
            qb = np.percentile(daily[b_][ids], 95)
            par_rows.append(dict(level="day", subset=name, base=a,
                                 treatment=b_,
                                 d_mean_pct=round(100*(mb-ma)/ma, 3),
                                 d_p95_pct=round(100*(qb-qa)/qa, 3),
                                 d_BI=round((qb-mb)/mb - (qa-ma)/ma, 4),
                                 paradox=int(mb < ma and qb < qa and
                                             (qb-mb)/mb > (qa-ma)/ma)))
    with open(os.path.join(OUT, "buffer_index_paradox_scan.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(par_rows[0].keys()))
        w.writeheader()
        w.writerows(par_rows)
    hits = [r for r in par_rows if r["paradox"]]
    say(f"   {len(hits)} paradox cases out of {len(par_rows)} scanned "
        f"(scan = {len(pairs)} scenario pairs x "
        f"{len(grid)} reweighted incident rates + 3 demand terciles "
        f"+ 3 day subsets, at vehicle level, plus 3 day subsets at day level)")
    for h in hits:
        say(f"     {h}")

    def dayweights(name):
        if name == "all":
            return np.ones(NDAY)
        if name == "no_incident_days":
            return (~INC).astype(float)
        if name == "incident_days":
            return INC.astype(float)
        if name.startswith("reweighted_p="):
            p = float(name.split("=")[1])
            return np.where(INC, p / p_hat, (1 - p) / (1 - p_hat))
        if name == "demand_low":
            return (MULT <= ter[0]).astype(float)
        if name == "demand_mid":
            return ((MULT > ter[0]) & (MULT <= ter[1])).astype(float)
        if name == "demand_high":
            return (MULT > ter[1]).astype(float)
        raise KeyError(name)

    # bootstrap the paradox cases that were found (cap the vehicle-level ones
    # at the 4 with the largest BI margin, to keep runtime sane)
    vh = sorted([h for h in hits if h["level"] == "vehicle"],
                key=lambda h: -h["d_BI"])[:4]
    dh = [h for h in hits if h["level"] == "day"]
    par_ci = []
    for h in vh + dh:
        name, a, b_ = h["subset"], h["base"], h["treatment"]
        if h["level"] == "vehicle":
            wbase = dayweights(name)
            Pa, Pb = pools[a], pools[b_]
            dm, dq, db = [], [], []
            for b in range(NBOOT // 2):
                c = counts_from(BIDX[b]) * wbase
                ma_, mb_ = Pa.m(dayweight=c), Pb.m(dayweight=c)
                dm.append(mb_["mean"] - ma_["mean"])
                dq.append(mb_["p95"] - ma_["p95"])
                db.append(mb_["BI"] - ma_["BI"])
            joint = float(np.mean((np.array(dm) < 0) & (np.array(dq) < 0)
                                  & (np.array(db) > 0)))
        else:
            ids = subsets[name]
            sub_b = RNG.integers(0, len(ids), size=(NBOOT, len(ids)))
            dm, dq, db = [], [], []
            for b in range(NBOOT):
                jj = ids[sub_b[b]]
                xa, xb = daily[a][jj], daily[b_][jj]
                dm.append(xb.mean() - xa.mean())
                dq.append(np.percentile(xb, 95) - np.percentile(xa, 95))
                db.append((np.percentile(xb, 95) - xb.mean()) / xb.mean()
                          - (np.percentile(xa, 95) - xa.mean()) / xa.mean())
            joint = float(np.mean((np.array(dm) < 0) & (np.array(dq) < 0)
                                  & (np.array(db) > 0)))
        par_ci.append(dict(level=h["level"], subset=name, base=a,
                           treatment=b_,
                           d_mean_ci=str([round(x, 2) for x in ci(dm)]),
                           d_p95_ci=str([round(x, 2) for x in ci(dq)]),
                           d_BI_ci=str([round(x, 4) for x in ci(db)]),
                           P_mean_improves=round(
                               float((np.array(dm) < 0).mean()), 4),
                           P_p95_improves=round(
                               float((np.array(dq) < 0).mean()), 4),
                           P_BI_worsens=round(
                               float((np.array(db) > 0).mean()), 4),
                           P_all_three_hold=round(joint, 4)))
        say(f"     bootstrap: {b_} vs {a} [{name}, {h['level']}-level]  "
            f"P(mean improves)={float((np.array(dm) < 0).mean()):.3f}  "
            f"P(p95 improves)={float((np.array(dq) < 0).mean()):.3f}  "
            f"P(BI worsens)={float((np.array(db) > 0).mean()):.3f}  "
            f"P(all three)={joint:.3f}")
    if par_ci:
        with open(os.path.join(OUT, "buffer_index_paradox_bootstrap.csv"),
                  "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(par_ci[0].keys()))
            w.writeheader()
            w.writerows(par_ci)

    # ------------------------------------- 8. teleport + censoring audit
    say("\n== teleport / censoring audit ==")
    tel_rows = []
    for s in SC:
        tel = sum(int(cells[("FULL", s, i)]["teleports"]) for i in range(NDAY))
        telv = sum(int(cells[("FULL", s, i)]["teleport_corr_veh"])
                   for i in range(NDAY))
        nveh = pools[s].n
        unf = sum(int(cells[("FULL", s, i)]["n_corr_unfinished"])
                  for i in range(NDAY))
        noins = sum(int(cells[("FULL", s, i)]["not_inserted"])
                    for i in range(NDAY))
        frz = sum(int(cells[("FULL", s, i)]["gridlock_freeze"])
                  for i in range(NDAY))
        tel_rows.append(dict(scenario=s, total_teleports=tel,
                             corridor_vehicles_teleported=telv,
                             corridor_vehicles=nveh,
                             teleport_share_pct=round(100 * telv / nveh, 5),
                             unfinished_corridor_trips=unf,
                             loaded_but_never_inserted=noins,
                             gridlock_freeze_days=frz))
        say(f"   {s:<12} teleports={tel:4d}  corridor veh teleported={telv:4d}"
            f" ({100*telv/nveh:.4f}%)  unfinished={unf}  not-inserted={noins}"
            f"  freeze-days={frz}")
    with open(os.path.join(OUT, "teleport_audit.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tel_rows[0].keys()))
        w.writeheader()
        w.writerows(tel_rows)

    # ttt sensitivity
    ttt_rows = []
    ex = list(csv.DictReader(open(os.path.join(WORK, "cells_extra.csv"))))
    tttdays = json.load(open(os.path.join(WORK, "ttt_days.json")))
    for d in tttdays:
        for s in SC:
            for t in (-1, 120, 200):
                tag = f"day{d['day']:03d}_ttt{t}"
                v, fin = tt_of("TTT", s, tag)
                r = [x for x in ex if x["block"] == "TTT" and
                     x["scenario"] == s and x["tag"] == tag][0]
                vs = np.sort(v[fin == 1])
                m = metrics(vs)
                ttt_rows.append(dict(day=d["day"], mult=d["mult"],
                                     inc_lanes=d["inc_lanes"], scenario=s,
                                     time_to_teleport=t,
                                     n_finished=int(fin.sum()),
                                     n_unfinished=int((fin == 0).sum()),
                                     teleports=int(r["teleports"]),
                                     gridlock_freeze=int(r["gridlock_freeze"]),
                                     mean=round(m["mean"], 1),
                                     p95=round(m["p95"], 1),
                                     misery=round(m["MiseryIndex"], 1)))
    with open(os.path.join(OUT, "teleport_sensitivity.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ttt_rows[0].keys()))
        w.writeheader()
        w.writerows(ttt_rows)
    say(f"   teleport_sensitivity.csv: {len(ttt_rows)} rows "
        "(6 worst incident days x 4 scenarios x 3 time-to-teleport values)")

    # synthetic-horizon censoring demonstration
    cen_rows = []
    for H in (4800, 5400, 6000, 7200, 10800):
        for s in SC:
            vv, ww, cen = [], [], 0
            for i in range(NDAY):
                d = cell("FULL", s, "day%03d" % i)
                dep = d["depart"]
                dd = d["departdelay"]
                dur = d["dur"]
                door = dur + dd
                wish = dep - dd
                completion = dep + dur
                fin = completion <= H
                cen += int((~fin).sum())
                vv.append(np.where(fin, door, H - wish))
                ww.append(fin.astype(float))
            door_all = np.concatenate(vv)
            finmask = np.concatenate(ww).astype(bool)
            naive = np.sort(door_all[finmask])          # drop unfinished
            lower = np.sort(door_all)                   # censored lower bound
            mn = metrics(naive)
            ml = metrics(lower)
            cen_rows.append(dict(horizon_s=H, scenario=s,
                                 n_censored=cen,
                                 censored_pct=round(100*cen/len(door_all), 4),
                                 naive_mean=round(mn["mean"], 1),
                                 naive_p95=round(mn["p95"], 1),
                                 naive_misery=round(mn["MiseryIndex"], 1),
                                 lowerbound_mean=round(ml["mean"], 1),
                                 lowerbound_p95=round(ml["p95"], 1),
                                 lowerbound_misery=round(ml["MiseryIndex"], 1),
                                 p95_bias_pct=round(
                                     100*(mn["p95"]-ml["p95"])/ml["p95"], 3)))
    with open(os.path.join(OUT, "censoring_horizon_sensitivity.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cen_rows[0].keys()))
        w.writeheader()
        w.writerows(cen_rows)
    say("   censoring_horizon_sensitivity.csv written")

    # ------------------------------------------------------------- 9. plots
    ontime_ci = {}
    for s in SC:
        for k in ("ontime_1p10_ff", "ontime_1p25_ff"):
            ontime_ci[(s, k)] = ci(boot_store[("all", s)][k])
    make_plots(pools, daily, seedvar_curve, vd_rows, curves, grid, ontime_ci)

    open(os.path.join(OUT, "analysis_console_log.txt"), "w").write(
        "\n".join(log) + "\n")
    say("\nDONE. outputs -> " + OUT)


# ------------------------------------------------------------------- plots
def make_plots(pools, daily, seedvar_curve, vd_rows, curves, grid,
               ontime_ci):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#b9b8b2",
                         "axes.labelcolor": "#0b0b0b",
                         "text.color": "#0b0b0b",
                         "xtick.color": "#52514e", "ytick.color": "#52514e",
                         "figure.facecolor": "#fcfcfb",
                         "axes.facecolor": "#fcfcfb",
                         "savefig.facecolor": "#fcfcfb"})

    # --- CDF overlay
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.6))
    for s in SC:
        v = pools[s].v
        y = np.arange(1, len(v) + 1) / len(v)
        k = max(1, len(v) // 4000)
        ax[0].plot(v[::k], y[::k], color=COL[s], lw=2, label=LBL[s])
        ax[1].plot(v[::k], y[::k], color=COL[s], lw=2, label=LBL[s])
    for a in ax:
        a.axvline(FFT, color="#8f8e88", lw=1, ls=":")
        a.grid(alpha=.25, lw=.6)
        a.set_xlabel("door-to-door corridor travel time (s)")
        a.spines[["top", "right"]].set_visible(False)
    ax[0].set_ylabel("cumulative share of corridor trips")
    ax[0].set_title("Full distribution", loc="left")
    ax[0].set_xlim(250, 3000)
    ax[1].set_title("Upper tail (log scale)", loc="left")
    ax[1].set_xscale("log")
    ax[1].set_ylim(0.5, 1.001)
    ax[1].set_xlim(280, 6000)
    ax[1].axhline(0.95, color="#8f8e88", lw=1, ls="--")
    ax[1].text(300, .953, "95th percentile", color="#52514e", fontsize=8)
    ax[0].text(FFT + 30, .06, f"free-flow {FFT:.0f} s", color="#52514e",
               fontsize=8)
    # direct labels (relief rule: aqua is below 3:1 on the light surface)
    for s in SC:
        v = pools[s].v
        x = v[int(.995 * len(v))]
        ax[1].annotate(LBL[s].split()[0], (x, .995), color=COL[s],
                       fontsize=9, fontweight="bold",
                       xytext=(3, 0), textcoords="offset points", va="center")
    ax[0].legend(frameon=False, fontsize=8, loc="lower right")
    ax[0].set_ylim(0, 1.0)
    from matplotlib.ticker import FuncFormatter, NullFormatter
    ax[1].xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}"))
    ax[1].xaxis.set_minor_formatter(NullFormatter())
    ax[1].set_xticks([300, 500, 1000, 2000, 4000])
    fig.suptitle(f"Corridor travel-time distribution, {NDAY} simulated days, "
                 "pooled over all corridor trips", x=.01, ha="left",
                 fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, .95])
    fig.savefig(os.path.join(OUT, "travel_time_cdf.png"), dpi=150)
    plt.close(fig)

    # --- percentile curve
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ps = np.concatenate([np.arange(5, 95, 5), np.arange(95, 99.9, .5)])
    for s in SC:
        v = pools[s].v
        y = np.percentile(v, ps)
        ax.plot(ps, y / FFT, color=COL[s], lw=2, label=LBL[s])
        ax.annotate(LBL[s].split()[0], (ps[-1], y[-1] / FFT), color=COL[s],
                    fontsize=9, fontweight="bold", xytext=(4, 0),
                    textcoords="offset points", va="center")
    ax.axhline(1.0, color="#8f8e88", lw=1, ls=":")
    ax.axvline(95, color="#8f8e88", lw=1, ls="--")
    ax.text(95.3, ax.get_ylim()[1] * .95, "PTI is read here", fontsize=8,
            color="#52514e")
    ax.set_xlabel("percentile of corridor trips")
    ax.set_ylabel("travel time / free-flow travel time")
    ax.grid(alpha=.25, lw=.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_title("Travel-time percentile curve (travel-time index by "
                 "percentile)", loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "percentile_curve.png"), dpi=150)
    plt.close(fig)

    # --- variance decomposition + seed noise vs demand
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.4))
    x = np.arange(len(SC))
    fs = [r["frac_seed"] for r in vd_rows]
    fd = [r["frac_demand"] for r in vd_rows]
    fi = [r["frac_incident"] for r in vd_rows]
    ax[0].bar(x, fs, .55, color="#8f8e88", label="seed (simulator artefact)")
    ax[0].bar(x, fd, .55, bottom=fs, color="#2a78d6",
              label="day-to-day demand (recurrent)")
    ax[0].bar(x, fi, .55, bottom=np.array(fs) + np.array(fd), color="#eb6834",
              label="incidents (non-recurrent)")
    for i in range(len(SC)):
        ax[0].text(i, fs[i] / 2, f"{100*fs[i]:.0f}%", ha="center", fontsize=8,
                   color="#0b0b0b")
        ax[0].text(i, fs[i] + fd[i] / 2, f"{100*fd[i]:.0f}%", ha="center",
                   fontsize=8, color="#ffffff")
        ax[0].text(i, fs[i] + fd[i] + fi[i] / 2, f"{100*fi[i]:.0f}%",
                   ha="center", fontsize=8, color="#ffffff")
    ax[0].set_xticks(x)
    ax[0].set_xticklabels([s.split("_")[0] for s in SC])
    ax[0].set_ylabel("share of Var(daily mean travel time)")
    ax[0].set_title("Variance decomposition of the daily mean travel time",
                    loc="left")
    ax[0].set_ylim(0, 1.18)
    ax[0].legend(frameon=False, fontsize=8, ncol=1, loc="upper center")
    ax[0].spines[["top", "right"]].set_visible(False)

    for s in SC:
        m_ = [t[0] for t in seedvar_curve[s]]
        sd = [t[2] for t in seedvar_curve[s]]
        ax[1].plot(m_, sd, color=COL[s], lw=2, marker="o", ms=4, label=LBL[s])
    ax[1].set_xlabel("demand multiplier")
    ax[1].set_ylabel("sd of daily mean travel time over 6 seeds (s)")
    ax[1].set_title("Simulator noise floor peaks at the congestion knee",
                    loc="left")
    ax[1].grid(alpha=.25, lw=.6)
    ax[1].spines[["top", "right"]].set_visible(False)
    ax[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "variance_decomposition.png"), dpi=150)
    plt.close(fig)

    # --- crossover plot
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.4))
    for s in SC:
        ax[0].plot(grid, curves[s]["mean"], color=COL[s], lw=2, label=LBL[s])
        ax[1].plot(grid, curves[s]["PTI"], color=COL[s], lw=2, label=LBL[s])
    for a, t in ((ax[0], "Mean travel time (s)"),
                 (ax[1], "Planning Time Index (p95 / free-flow)")):
        a.set_xlabel("assumed incident probability per day")
        a.set_ylabel(t)
        a.grid(alpha=.25, lw=.6)
        a.spines[["top", "right"]].set_visible(False)
        a.axvline(float(INC.mean()), color="#8f8e88", ls=":", lw=1)
        a.legend(frameon=False, fontsize=8)
    ax[0].set_title("Ranking by the mean", loc="left")
    ax[1].set_title("Ranking by the tail", loc="left")
    fig.suptitle(f"Reweighting the same {NDAY} day-draws to other incident "
                 "rates", x=.01, ha="left", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, .94])
    fig.savefig(os.path.join(OUT, "crossover_vs_incident_probability.png"),
                dpi=150)
    plt.close(fig)

    # --- on-time reliability at two thresholds (where the metrics disagree)
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    x = np.arange(len(SC))
    for off, (k, lab) in enumerate((("ontime_1p10_ff",
                                     "within 1.10 x free-flow"),
                                    ("ontime_1p25_ff",
                                     "within 1.25 x free-flow"))):
        vals = [pools[s].m()[k] for s in SC]
        lo = [ontime_ci[(s, k)][0] for s in SC]
        hi = [ontime_ci[(s, k)][1] for s in SC]
        b = ax.bar(x + (off - .5) * .38, vals, .34,
                   color=[COL[s] for s in SC],
                   alpha=1.0 if off else .45,
                   edgecolor="#fcfcfb", linewidth=2, label=lab)
        ax.errorbar(x + (off - .5) * .38, vals,
                    yerr=[np.array(vals) - np.array(lo),
                          np.array(hi) - np.array(vals)],
                    fmt="none", ecolor="#52514e", elinewidth=1.2, capsize=3)
        for i, v in enumerate(vals):
            ax.text(x[i] + (off - .5) * .38, v + .015, f"{v:.3f}",
                    ha="center", fontsize=7.5, color="#0b0b0b")
    ax.set_xticks(x)
    ax.set_xticklabels([LBL[s] for s in SC], fontsize=8)
    ax.set_ylabel("share of corridor trips on time")
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=.25, lw=.6, axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#8f8e88", alpha=.45,
                             label="within 1.10 x free-flow (left bar)"),
                       Patch(facecolor="#8f8e88",
                             label="within 1.25 x free-flow (right bar)")],
              frameon=False, fontsize=8, loc="upper left")
    ax.set_title("On-time reliability: the two standard thresholds rank C "
                 "and D differently", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "ontime_reliability.png"), dpi=150)
    plt.close(fig)

    # --- daily mean vs demand
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for s in SC:
        ax.scatter(MULT[~INC], daily[s][~INC], s=18, color=COL[s],
                   label=LBL[s] + "  (no incident)", alpha=.85,
                   edgecolors="#fcfcfb", linewidths=.7)
        ax.scatter(MULT[INC], daily[s][INC], s=42, color=COL[s], marker="^",
                   edgecolors="#0b0b0b", linewidths=.7)
    ax.set_xlabel("day demand multiplier")
    ax.set_ylabel("daily mean corridor travel time (s)")
    ax.grid(alpha=.25, lw=.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
    ax.set_title("Daily mean travel time vs demand "
                 "(triangles = incident days)", loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "daily_mean_vs_demand.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
