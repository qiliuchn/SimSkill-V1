#!/usr/bin/env python3
"""Statistical analysis of the SUMO run-to-run variability study.

Reads replication_metrics.csv (+ replication_metrics_extra.csv), one row per
replication, plus the per-replication summary_ts.csv time series and the
keep_raw tripinfo traces, and produces:

  1. results_table.csv/.md      mean, sd, CV, 95% CI (t and bootstrap) per
                                metric per loading level
  2. variance_sources.csv/.md   variance decomposition across the SIM / DEM /
                                BOTH / NODRV replication families
  3. warmup_analysis.csv/.md    MSER-5 + Welch warm-up determination, with an
                                explicit stationarity diagnostic, and the bias
                                from not truncating
  4. required_n.csv/.md         n needed to resolve a target effect size d
  5. crn_vs_independent.csv/.md paired (CRN) vs two-sample t-test + variance
                                reduction factor
  6. single_run_detectability.csv/.md  what one seed could have resolved
  7. plots: warmup_welch.png, warmup_mser.png, warmup_truncation.png,
            ci_halfwidth_vs_n.png, cv_vs_vc.png, crn_scatter.png
"""
import csv
import glob
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(os.path.dirname(HERE), "attempts", "attempt-1", "work",
                    "study")
CSVS = [os.path.join(HERE, "replication_metrics.csv"),
        os.path.join(HERE, "replication_metrics_extra.csv")]
OUT = HERE

LEVEL_ORDER = ["L050", "L090", "L110"]
LEVEL_LABEL = {"L050": "undersaturated (demand v/c_p90 ~ 0.50)",
               "L090": "near capacity (demand v/c_p90 ~ 0.89)",
               "L110": "oversaturated (demand v/c_p90 ~ 1.09)"}
DEMAND_VC = {"L050": 0.50, "L090": 0.89, "L110": 1.09}
DEMAND_END = 3600

METRICS = [
    ("mean_duration",  "mean trip duration (s)"),
    ("mean_timeloss",  "mean time loss (s)"),
    ("n_completed",    "completed trips (throughput)"),
    ("queue_max_m",    "max network queue length (m)"),
    ("mean_waiting",   "mean waiting time (s)"),
]
CORE = METRICS[:4]

rng = np.random.default_rng(20260731)


# ---------------------------------------------------------------------------
def load():
    rows = []
    for c in CSVS:
        if not os.path.exists(c):
            continue
        with open(c) as fh:
            for r in csv.DictReader(fh):
                for k, v in list(r.items()):
                    if k in ("id", "family", "level", "arm"):
                        continue
                    try:
                        r[k] = float(v) if v != "" else float("nan")
                    except ValueError:
                        r[k] = float("nan")
                rows.append(r)
    return rows


def sel(rows, **kw):
    out = rows
    for k, v in kw.items():
        out = [r for r in out if r[k] == v]
    return out


def vals(rows, key):
    return np.array([r[key] for r in rows], dtype=float)


def ci95(x, boot=20000):
    """Mean, sd, CV, 95% CI half-width via Student-t, plus a percentile
    bootstrap CI (robustness check when the distribution is not normal --
    which matters near capacity, where the response is bimodal)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    m, s = x.mean(), x.std(ddof=1)
    t = stats.t.ppf(0.975, n - 1)
    hw = t * s / math.sqrt(n)
    if s > 0:
        bs = rng.choice(x, size=(boot, n), replace=True).mean(axis=1)
        blo, bhi = np.percentile(bs, [2.5, 97.5])
    else:
        blo = bhi = m
    return dict(n=n, mean=m, sd=s, cv=(s / m if m else float("nan")),
                t=t, hw=hw, lo=m - hw, hi=m + hw, boot_lo=blo, boot_hi=bhi,
                skew=float(stats.skew(x)) if s > 0 else 0.0,
                rel_hw=(hw / m if m else float("nan")))


def required_n(s, d, alpha=0.05):
    """Fixed-point solution of n = (t_{n-1,1-a/2} * s / d)^2.

    Returns (n_clamped, n_raw_float). n<2 is unusable (no df to estimate s),
    so the reported n is clamped at 2 while the raw value is kept for honesty.
    """
    if s <= 0:
        return 2, 0.0
    n_raw = (stats.norm.ppf(1 - alpha / 2) * s / d) ** 2
    n = max(2, int(math.ceil(n_raw)))
    for _ in range(200):
        t = stats.t.ppf(1 - alpha / 2, n - 1)
        nn = max(2, int(math.ceil((t * s / d) ** 2)))
        if nn == n:
            break
        n = nn
    return n, n_raw


# ===========================================================================
# 1. results table
# ===========================================================================
def results_table(rows):
    recs = []
    md = ["# Results table: mean +/- 95% CI per metric per loading level", "",
          "Replication family **BOTH** -- both the randomTrips demand seed and",
          "the sumo seed vary between replications. This is the only design",
          "that samples the full run-to-run distribution. n = 40 independent",
          "replications per loading level.", "",
          "The bootstrap CI is a robustness check on the t-interval: near",
          "capacity the response is strongly non-normal, so the two disagreeing",
          "is itself diagnostic.", "",
          "| level | demand v/c(p90) | metric | n | mean | sd | CV | 95% CI (t) | 95% CI (bootstrap) | rel. half-width | skew |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for lvl in LEVEL_ORDER:
        rs = sel(rows, level=lvl, family="BOTH")
        for key, label in METRICS:
            c = ci95(vals(rs, key))
            recs.append(dict(level=lvl, demand_vc=DEMAND_VC[lvl], metric=key,
                             label=label,
                             **{k: c[k] for k in ("n", "mean", "sd", "cv",
                                                  "hw", "lo", "hi", "boot_lo",
                                                  "boot_hi", "rel_hw",
                                                  "skew")}))
            md.append("| %s | %.2f | %s | %d | %.2f | %.2f | %.2f%% | [%.2f, %.2f] | [%.2f, %.2f] | %.2f%% | %+.2f |"
                      % (lvl, DEMAND_VC[lvl], label, c["n"], c["mean"],
                         c["sd"], 100 * c["cv"], c["lo"], c["hi"],
                         c["boot_lo"], c["boot_hi"], 100 * c["rel_hw"],
                         c["skew"]))
    md += ["", "## v/c verification (not assumed -- measured)", "",
           "`demand v/c` is counted from the duarouter route files (route",
           "traversals per interior link, vehicles departing 600-3600 s,",
           "divided by the measured capacity 512.4 veh/h/link).",
           "`achieved v/c` is the served flow measured from edgeData over the",
           "same window. The two agree while the network is stable and diverge",
           "once it is not -- served flow is bounded by capacity and *falls*",
           "in gridlock, which is why demand-side v/c is what labels the",
           "loading level.", "",
           "| level | insertion rate (veh/h) | demand v/c p90 | achieved v/c mean | achieved v/c p90 | achieved v/c max | teleports (mean) |",
           "|---|---|---|---|---|---|---|"]
    for lvl in LEVEL_ORDER:
        rs = sel(rows, level=lvl, family="BOTH")
        md.append("| %s | %.0f | %.2f | %.3f | %.3f | %.3f | %.1f |"
                  % (lvl, vals(rs, "rate").mean(), DEMAND_VC[lvl],
                     vals(rs, "vc_mean").mean(), vals(rs, "vc_p90").mean(),
                     vals(rs, "vc_max").mean(), vals(rs, "teleports").mean()))
    with open(os.path.join(OUT, "results_table.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)
    open(os.path.join(OUT, "results_table.md"), "w").write("\n".join(md) + "\n")
    return recs


# ===========================================================================
# 2. variance decomposition
# ===========================================================================
def variance_sources(rows):
    fams = ["SIM", "DEM", "BOTH", "NODRV"]
    desc = {"SIM": "fixed routes, sumo --seed varies",
            "DEM": "randomTrips --seed varies, sumo seed fixed",
            "BOTH": "both vary (total run-to-run variability)",
            "NODRV": "fixed routes, sumo --seed varies, sigma=0 & speedDev=0"}
    md = ["# Variance-source decomposition", "",
          "Four controlled replication families isolate SUMO's randomness",
          "sources. If the demand-side and simulation-side sources were",
          "independent and the response were linear, variances would add:",
          "`sd_SIM^2 + sd_DEM^2 ~= sd_BOTH^2`. The `*check*` row tests that.",
          "", "n = 30 for SIM/DEM/NODRV, n = 40 for BOTH.", ""]
    for k, label in [("mean_duration", "network mean trip duration"),
                     ("mean_timeloss", "mean time loss"),
                     ("n_completed", "completed trips (throughput)"),
                     ("queue_max_m", "max network queue length")]:
        md += ["## %s" % label, "",
               "| level | family | what varies | n | mean | sd | variance | CV | share of BOTH variance |",
               "|---|---|---|---|---|---|---|---|---|"]
        for lvl in LEVEL_ORDER:
            var_both = np.nanvar(vals(sel(rows, level=lvl, family="BOTH"), k),
                                 ddof=1)
            for f in fams:
                v = vals(sel(rows, level=lvl, family=f), k)
                if len(v) == 0:
                    continue
                m, s = np.nanmean(v), np.nanstd(v, ddof=1)
                share = (100 * s * s / var_both) if var_both > 0 else float("nan")
                md.append("| %s | %s | %s | %d | %.2f | %.4g | %.4g | %.2f%% | %s |"
                          % (lvl, f, desc[f], len(v), m, s, s * s,
                             100 * s / m if m else float("nan"),
                             "%.1f%%" % share if share == share else "n/a"))
            sd_sim = np.nanstd(vals(sel(rows, level=lvl, family="SIM"), k), ddof=1)
            sd_dem = np.nanstd(vals(sel(rows, level=lvl, family="DEM"), k), ddof=1)
            tot = sd_sim ** 2 + sd_dem ** 2
            md.append("| %s | *check* | sd_SIM^2 + sd_DEM^2 | | | %.4g | %.4g | | %s |"
                      % (lvl, math.sqrt(tot), tot,
                         "%.1f%%" % (100 * tot / var_both) if var_both > 0 else "n/a"))
        md.append("")
    recs = []
    for lvl in LEVEL_ORDER:
        for f in fams:
            rs = sel(rows, level=lvl, family=f)
            if not rs:
                continue
            rec = dict(level=lvl, family=f, n=len(rs))
            for k, _ in METRICS:
                v = vals(rs, k)
                rec[k + "_mean"] = np.nanmean(v)
                rec[k + "_sd"] = np.nanstd(v, ddof=1)
            rec["n_distinct_mean_duration"] = len(
                set(np.round(vals(rs, "mean_duration"), 9)))
            recs.append(rec)
    with open(os.path.join(OUT, "variance_sources.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)
    md += ["## The NODRV result is exact, not approximate", "",
           "| level | family | distinct values of mean_duration among the 30 replications |",
           "|---|---|---|"]
    for lvl in LEVEL_ORDER:
        for f in ("SIM", "NODRV"):
            r = [x for x in recs if x["level"] == lvl and x["family"] == f][0]
            md.append("| %s | %s | %d / %d |"
                      % (lvl, f, r["n_distinct_mean_duration"], r["n"]))
    md += ["",
           "With `sigma=0` and `speedDev=0` and a fixed route file, 30 different",
           "values of `sumo --seed` produce **bit-identical** output. Verified",
           "separately with four far-apart seeds (11 / 222 / 3333 / 44444):",
           "identical mean duration to 9 decimal places and identical max queue.",
           "In this scenario the sumo seed is therefore not an independent",
           "randomness source at all -- it is *entirely* a driver-dispersion",
           "seed. See FINDINGS.md for the scope conditions on that claim.", ""]
    open(os.path.join(OUT, "variance_sources.md"), "w").write("\n".join(md) + "\n")
    return recs


# ===========================================================================
# 3. warm-up
# ===========================================================================
def load_ts(lvl, family="BOTH", limit=40):
    d = os.path.join(WORK, lvl, family)
    series = []
    for sd in sorted(os.listdir(d))[:limit]:
        p = os.path.join(d, sd, "summary_ts.csv")
        if not os.path.exists(p):
            continue
        t, run, spd = [], [], []
        with open(p) as fh:
            for r in csv.DictReader(fh):
                t.append(float(r["time"]))
                run.append(float(r["running"]))
                spd.append(float(r["meanSpeed"]) if r["meanSpeed"] else np.nan)
        series.append((np.array(t), np.array(run), np.array(spd)))
    return series


def mser5(y):
    """MSER-5 truncation point (in original time units).

    Returns (d_time, d_batches, m_batches, search_limit_batches). The search is
    limited to the first half of the batches (standard); if the minimiser lands
    ON that limit, MSER has not found an interior minimum -- a classic sign the
    series never reaches steady state.
    """
    m = len(y) // 5
    yb = np.array([y[5 * i:5 * i + 5].mean() for i in range(m)])
    lim = m // 2
    best, bestd = np.inf, 0
    for d in range(lim):
        tail = yb[d:]
        v = np.sum((tail - tail.mean()) ** 2) / (len(tail) ** 2)
        if v < best:
            best, bestd = v, d
    return bestd * 5, bestd, m, lim


def welch_smooth(series, idx, w=60, cut=DEMAND_END + 1):
    n = min(min(len(s[0]) for s in series), cut)
    Y = np.vstack([s[idx][:n] for s in series])
    ybar = np.nanmean(Y, axis=0)
    sm = np.empty(n)
    for i in range(n):
        ww = min(w, i, n - 1 - i)
        sm[i] = np.nanmean(ybar[i - ww:i + ww + 1])
    return ybar, sm


def drift(sm, a=1200, b=DEMAND_END):
    """Relative drift of the smoothed ensemble mean over [a,b]: OLS slope
    extrapolated over the interval, as a fraction of the interval mean."""
    x = np.arange(a, min(b, len(sm)))
    y = sm[a:min(b, len(sm))]
    sl = stats.linregress(x, y).slope
    return sl * (x[-1] - x[0]) / abs(y.mean())


def warmup_analysis(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    md = ["# Warm-up (initialization-bias) determination", "",
          "The network starts empty, so `running` (vehicle count) and the",
          "instantaneous network `meanSpeed` from the `summary` output both",
          "show a transient. Two standard truncation rules are applied to the",
          "**loading period only** (0-3600 s); the drain-out after 3600 s is a",
          "deliberate non-stationarity, not initialization bias.", "",
          "`meanSpeed = -1` rows (SUMO's 'no vehicles running' sentinel) are",
          "dropped before any averaging -- otherwise the empty-network steps",
          "at the very start of the run, which are exactly the steps the",
          "warm-up analysis is about, would be read as a speed of -1 m/s.", "",
          "**A stationarity diagnostic is applied first.** Truncation methods",
          "assume the series eventually reaches steady state. Two checks:",
          "(i) relative drift of the Welch-smoothed ensemble mean over",
          "1200-3600 s; (ii) whether MSER-5's minimiser lands on the boundary",
          "of its search range (m/2 batches), which means no interior minimum",
          "was found. If either fails, no warm-up is adopted, because the",
          "correct statement is 'this configuration has no steady state within",
          "the loading period', not 'the warm-up is long'.", ""]
    recs = []
    fig1, ax1 = plt.subplots(2, 3, figsize=(16, 7))
    fig2, ax2 = plt.subplots(1, 3, figsize=(16, 4))

    for j, lvl in enumerate(LEVEL_ORDER):
        series = load_ts(lvl)
        cut = DEMAND_END + 1
        t = np.arange(cut)
        run_bar, run_sm = welch_smooth(series, 1, 60, cut)
        spd_bar, spd_sm = welch_smooth(series, 2, 60, cut)

        d_run, db_run, m, lim = mser5(run_bar)
        d_spd, db_spd, _, _ = mser5(spd_bar)
        dr_run, dr_spd = drift(run_sm), drift(spd_sm)
        boundary = (db_run >= lim - 1) or (db_spd >= lim - 1)
        stationary = (abs(dr_run) < 0.10 and abs(dr_spd) < 0.10
                      and not boundary)

        # Welch: first time the smoothed ensemble mean enters a +/-2% band
        # around its own plateau (mean of the last 900 s of the loading period)
        def welch_pt(sm):
            plateau = np.nanmean(sm[cut - 900:cut])
            band = 0.02 * abs(plateau)
            ok = np.abs(sm - plateau) <= band
            idx = np.where(ok)[0]
            return int(idx[0]) if len(idx) else cut - 1
        w_run, w_spd = welch_pt(run_sm), welch_pt(spd_sm)

        adopted = max(d_run, d_spd, w_run, w_spd) if stationary else None
        recs.append(dict(level=lvl, mser5_running_s=d_run,
                         mser5_meanspeed_s=d_spd, welch_running_s=w_run,
                         welch_meanspeed_s=w_spd,
                         drift_running_pct=100 * dr_run,
                         drift_meanspeed_pct=100 * dr_spd,
                         mser_on_boundary=int(boundary),
                         stationary=int(stationary),
                         adopted_warmup_s=(adopted if adopted is not None
                                           else -1)))

        a = ax1[0][j]
        a.plot(t, run_bar, lw=.4, color="0.75", label="ensemble mean (n=40)")
        a.plot(t, run_sm, lw=1.8, color="C0", label="Welch MA (w=60)")
        a.axvline(d_run, color="C3", ls="--", lw=1.3, label="MSER-5 = %d s" % d_run)
        a.axvline(w_run, color="C2", ls=":", lw=1.6, label="Welch 2%% band = %d s" % w_run)
        a.set_title("%s  running vehicles%s" % (lvl, "" if stationary else "  [NON-STATIONARY]"),
                    fontsize=10)
        a.set_ylabel("vehicles")
        a.legend(fontsize=7)
        a.grid(alpha=.3)
        b = ax1[1][j]
        b.plot(t, spd_bar, lw=.4, color="0.75")
        b.plot(t, spd_sm, lw=1.8, color="C1")
        b.axvline(d_spd, color="C3", ls="--", lw=1.3, label="MSER-5 = %d s" % d_spd)
        b.axvline(w_spd, color="C2", ls=":", lw=1.6, label="Welch 2%% band = %d s" % w_spd)
        b.set_title("%s  network mean speed" % lvl, fontsize=10)
        b.set_xlabel("simulation time (s)")
        b.set_ylabel("m/s")
        b.legend(fontsize=7)
        b.grid(alpha=.3)

        yb = np.array([run_bar[5 * i:5 * i + 5].mean() for i in range(m)])
        xs = np.arange(lim) * 5
        ys = [np.sum((yb[d:] - yb[d:].mean()) ** 2) / (len(yb[d:]) ** 2)
              for d in range(lim)]
        ax2[j].plot(xs, ys, lw=1.2)
        ax2[j].axvline(d_run, color="C3", ls="--",
                       label="minimiser = %d s" % d_run)
        if boundary:
            ax2[j].axvline(lim * 5, color="k", ls="-.", lw=1,
                           label="search boundary (no interior min)")
        ax2[j].set_yscale("log")
        ax2[j].set_title("%s  MSER-5 statistic (running veh)" % lvl, fontsize=10)
        ax2[j].set_xlabel("truncation point d (s)")
        ax2[j].legend(fontsize=7)
        ax2[j].grid(alpha=.3, which="both")

    fig1.suptitle("Warm-up determination from the summary output "
                  "(ensemble of 40 replications per level)")
    fig1.tight_layout()
    fig1.savefig(os.path.join(OUT, "warmup_welch.png"), dpi=130)
    fig2.tight_layout()
    fig2.savefig(os.path.join(OUT, "warmup_mser.png"), dpi=130)
    plt.close("all")

    md += ["| level | MSER-5 (running) | MSER-5 (meanSpeed) | Welch 2% band (running) | Welch 2% band (meanSpeed) | drift 1200-3600 s (running) | MSER on boundary? | steady state reached? | adopted warm-up |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in recs:
        md.append("| %s | %d s | %d s | %d s | %d s | %+.1f%% | %s | %s | %s |"
                  % (r["level"], r["mser5_running_s"], r["mser5_meanspeed_s"],
                     r["welch_running_s"], r["welch_meanspeed_s"],
                     r["drift_running_pct"],
                     "YES" if r["mser_on_boundary"] else "no",
                     "yes" if r["stationary"] else "**NO**",
                     ("**%d s**" % r["adopted_warmup_s"]) if r["stationary"]
                     else "n/a -- see note"))
    md += ["",
           "Only the undersaturated case reaches a steady state within the",
           "loading hour. At v/c ~ 0.89 and ~ 1.09 the running-vehicle count",
           "climbs for the whole hour, MSER-5's minimiser sits on its search",
           "boundary, and 'warm-up truncation' is simply the wrong tool: those",
           "runs are *terminating* simulations of a peak period, and the right",
           "treatment is to replicate them and average whole-run statistics,",
           "not to truncate an initial transient.", ""]

    # ---- time-series bias --------------------------------------------------
    md += ["## Bias from including the warm-up in a time-averaged metric", "",
           "Time-average of the `summary` series over 0-3600 s (no truncation)",
           "vs. over [warm-up, 3600 s]. For the two non-stationary levels the",
           "warm-up column uses the MSER-5(running) value purely to show the",
           "size of the sensitivity -- it is not endorsed as a warm-up.", "",
           "| level | truncation used | time-avg running veh, no trunc | truncated | bias | time-avg speed, no trunc | truncated | bias |",
           "|---|---|---|---|---|---|---|---|"]
    for r in recs:
        lvl = r["level"]
        series = load_ts(lvl)
        cut = DEMAND_END + 1
        run = np.nanmean(np.vstack([s[1][:cut] for s in series]), axis=0)
        spd = np.nanmean(np.vstack([s[2][:cut] for s in series]), axis=0)
        w = (r["adopted_warmup_s"] if r["stationary"]
             else r["mser5_running_s"])
        a1, b1 = np.nanmean(run), np.nanmean(run[w:])
        a2, b2 = np.nanmean(spd), np.nanmean(spd[w:])
        md.append("| %s | %d s%s | %.1f | %.1f | %+.2f%% | %.3f | %.3f | %+.2f%% |"
                  % (lvl, w, "" if r["stationary"] else " (illustrative)",
                     a1, b1, 100 * (a1 - b1) / b1, a2, b2,
                     100 * (a2 - b2) / b2))
        r["timeavg_running_notrunc"] = a1
        r["timeavg_running_trunc"] = b1
        r["timeavg_speed_notrunc"] = a2
        r["timeavg_speed_trunc"] = b2
        r["trunc_used_s"] = w

    with open(os.path.join(OUT, "warmup_analysis.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)
    return recs, md


# ---- truncation-sensitivity curves from raw tripinfo ----------------------
def truncation_curves(recs, md):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    Ws = list(range(0, 2401, 120))
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    md += ["", "## Truncation sensitivity of the trip-based metrics", "",
           "Mean trip duration / time loss recomputed over only those trips",
           "that *departed* at or after a truncation point W (and before",
           "3600 s), averaged over 12 replications per level with full",
           "tripinfo traces retained.", "",
           "| level | W = 0 s | W = adopted/illustrative | bias of W=0 | W=1200 s | W=2400 s |",
           "|---|---|---|---|---|---|"]
    csv_rows = []
    for j, lvl in enumerate(LEVEL_ORDER):
        files = sorted(glob.glob(os.path.join(WORK, lvl, "RAW", "s*",
                                              "tripinfo.xml")))
        curves_d, curves_l = [], []
        for f in files:
            dep, dur, loss = [], [], []
            for _, el in ET.iterparse(f, events=("end",)):
                if el.tag == "tripinfo":
                    dep.append(float(el.get("depart")))
                    dur.append(float(el.get("duration")))
                    loss.append(float(el.get("timeLoss")))
                    el.clear()
            dep = np.array(dep); dur = np.array(dur); loss = np.array(loss)
            cd, cl = [], []
            for W in Ws:
                m = (dep >= W) & (dep <= DEMAND_END)
                cd.append(dur[m].mean() if m.any() else np.nan)
                cl.append(loss[m].mean() if m.any() else np.nan)
            curves_d.append(cd); curves_l.append(cl)
        if not curves_d:
            continue
        CD = np.vstack(curves_d); CL = np.vstack(curves_l)
        md_d, sd_d = CD.mean(axis=0), CD.std(axis=0, ddof=1)
        md_l = CL.mean(axis=0)
        r = [x for x in recs if x["level"] == lvl][0]
        Wsel = r["trunc_used_s"]
        i_sel = int(np.argmin([abs(w - Wsel) for w in Ws]))
        i_1200 = Ws.index(1200); i_2400 = Ws.index(2400)
        md.append("| %s | %.1f s | %.1f s (W=%d) | %+.2f%% | %.1f s | %.1f s |"
                  % (lvl, md_d[0], md_d[i_sel], Ws[i_sel],
                     100 * (md_d[0] - md_d[i_sel]) / md_d[i_sel],
                     md_d[i_1200], md_d[i_2400]))
        for i, W in enumerate(Ws):
            csv_rows.append(dict(level=lvl, W=W, n_reps=CD.shape[0],
                                 mean_duration=md_d[i], sd_duration=sd_d[i],
                                 mean_timeloss=md_l[i]))
        ax = axes[j]
        for c in CD:
            ax.plot(Ws, c, lw=.6, color="0.8")
        ax.plot(Ws, md_d, lw=2.2, color="C0", label="mean over 12 reps")
        ax.axvline(Wsel, color="C3", ls="--",
                   label="W = %d s%s" % (Wsel, "" if r["stationary"]
                                         else " (illustrative)"))
        ax.set_title("%s\n%s" % (lvl, LEVEL_LABEL[lvl]), fontsize=9)
        ax.set_xlabel("truncation point W (s) -- trips departing >= W kept")
        ax.set_ylabel("mean trip duration (s)")
        ax.legend(fontsize=7)
        ax.grid(alpha=.3)
    fig.suptitle("Sensitivity of mean trip duration to the warm-up truncation point")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "warmup_truncation.png"), dpi=130)
    plt.close(fig)
    md += ["",
           "At v/c 0.50 the curve is flat after ~250 s: a genuine, short",
           "initialization transient, and ignoring it biases mean trip duration",
           "by well under 1%. At v/c 0.89 and 1.09 the curve never flattens --",
           "later departures really are slower because the queues are still",
           "growing. That is not initialization bias and truncating it would",
           "*create* a bias rather than remove one.", ""]
    if csv_rows:
        with open(os.path.join(OUT, "warmup_truncation.csv"), "w",
                  newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            for r in csv_rows:
                w.writerow(r)
    open(os.path.join(OUT, "warmup_analysis.md"), "w").write("\n".join(md) + "\n")


# ===========================================================================
# 4. required n
# ===========================================================================
def replication_count(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    md = ["# Required replication count", "",
          "`n = (t_{n-1,0.975} * s / d)^2`, solved by fixed-point iteration --",
          "the critical value itself depends on n, so a single evaluation with",
          "a normal quantile understates n for small samples. `s` is the",
          "between-replication sd from the 40 BOTH-family replications; `d` is",
          "the 95% CI half-width to be resolved, as a percentage of the mean.",
          "", "n is reported clamped at 2 (one run leaves no degrees of freedom",
          "to estimate s at all); the unclamped value is given in brackets",
          "where it is below 2.", ""]
    recs = []
    targets = [0.02, 0.05, 0.10]
    for key, label in CORE:
        md += ["## %s" % label, "",
               "| level | mean | s | CV | " +
               " | ".join("n for d = %d%%" % (100 * t) for t in targets) + " |",
               "|---|---|---|---|" + "---|" * len(targets)]
        for lvl in LEVEL_ORDER:
            c = ci95(vals(sel(rows, level=lvl, family="BOTH"), key))
            cells = []
            rec = dict(level=lvl, metric=key, mean=c["mean"], sd=c["sd"],
                       cv=c["cv"])
            for t in targets:
                n, raw = required_n(c["sd"], t * c["mean"])
                rec["n_d%d" % (100 * t)] = n
                rec["n_raw_d%d" % (100 * t)] = raw
                cells.append("%d%s" % (n, " (%.2f)" % raw if raw < 2 else ""))
            recs.append(rec)
            md.append("| %s | %.2f | %.4g | %.2f%% | %s |"
                      % (lvl, c["mean"], c["sd"], 100 * c["cv"],
                         " | ".join(cells)))
        md.append("")
    with open(os.path.join(OUT, "required_n.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)

    ns = np.arange(2, 101)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    for j, lvl in enumerate(LEVEL_ORDER):
        ax = axes[j]
        for key, label in CORE:
            c = ci95(vals(sel(rows, level=lvl, family="BOTH"), key))
            if c["sd"] <= 0:
                continue
            hw = stats.t.ppf(0.975, ns - 1) * c["sd"] / np.sqrt(ns)
            ax.plot(ns, 100 * hw / c["mean"], label=label, lw=1.7)
        ax.axhline(5, color="0.35", ls="--", lw=1)
        ax.text(99, 5.4, "5% target", ha="right", fontsize=8, color="0.3")
        for nn, cc in ((1, "C3"), (8, "C4"), (40, "C2")):
            ax.axvline(nn, color=cc, ls=":", lw=1.2, alpha=.8)
        ax.set_yscale("log"); ax.set_xscale("log")
        ax.set_xlabel("number of replications n")
        ax.set_ylabel("95% CI half-width (% of mean)")
        ax.set_title("%s\n%s" % (lvl, LEVEL_LABEL[lvl]), fontsize=9)
        ax.grid(alpha=.3, which="both")
        if j == 0:
            ax.legend(fontsize=7, loc="lower left")
    fig.suptitle("95% CI half-width vs replication count "
                 "(dotted verticals: n=1, n=8, n=40)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "ci_halfwidth_vs_n.png"), dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    for key, label in CORE:
        ys = [100 * ci95(vals(sel(rows, level=l, family="BOTH"), key))["cv"]
              for l in LEVEL_ORDER]
        ax.plot([DEMAND_VC[l] for l in LEVEL_ORDER], ys, "o-", label=label)
    ax.set_yscale("log")
    ax.set_xlabel("demand v/c on the 90th-percentile interior link")
    ax.set_ylabel("coefficient of variation (%)")
    ax.set_title("Run-to-run CV peaks AT capacity, not beyond it\n(n=40 per level)",
                 fontsize=10)
    ax.grid(alpha=.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cv_vs_vc.png"), dpi=130)
    plt.close(fig)
    open(os.path.join(OUT, "required_n.md"), "w").write("\n".join(md) + "\n")
    return recs


# ===========================================================================
# 5. CRN vs independent
# ===========================================================================
def crn_experiment(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    levels = [l for l in LEVEL_ORDER if sel(rows, level=l, arm="TRT_A")]
    md = ["# CRN (paired) vs independent seeds", "",
          "Treatment: **signal cycle length x0.8** on all 16 fixed-time signals",
          "(green 30 s -> 24 s, cycle 68 s -> 56 s; yellow unchanged), applied",
          "as a TLS program override additional file.", "",
          "Three arms, 40 replications each:", "",
          "* `BASE_A` baseline, seed list A (5000-5039)",
          "* `TRT_A`  treatment, **same** seed list A -> common random numbers",
          "* `TRT_B`  treatment, seed list B (6000-6039) -> independent seeds",
          "",
          "The independent-seed design is `BASE_A` vs `TRT_B`; the CRN design is",
          "`BASE_A` vs `TRT_A` paired by seed. Both consume 80 SUMO runs, so the",
          "comparison is fair on budget. The two designs deliberately share the",
          "baseline arm, so the ONLY difference between them is whether the",
          "treatment arm's seeds are matched to the baseline's.", "",
          "`VRF (empirical)` = Var(indep estimate) / Var(CRN estimate) as",
          "actually observed. `VRF (theoretical)` uses only the paired arms:",
          "`(s_B^2 + s_T^2) / (s_B^2 + s_T^2 - 2*rho*s_B*s_T)`, which is >= 1",
          "whenever rho > 0. Where the two disagree, the difference is sampling",
          "error in the variance estimates themselves (n=40 gives a variance",
          "estimate with ~23% relative standard error).", ""]
    out = {}
    fig, axes = plt.subplots(1, len(levels), figsize=(5.4 * len(levels), 4.7),
                             squeeze=False)
    for j, lvl in enumerate(levels):
        md += ["## %s -- %s" % (lvl, LEVEL_LABEL[lvl]), ""]
        for key, label in CORE:
            A = {int(r["sumo_seed"]): r[key]
                 for r in sel(rows, level=lvl, arm="BASE_A")}
            TA = {int(r["sumo_seed"]): r[key]
                  for r in sel(rows, level=lvl, arm="TRT_A")}
            TB = np.array([r[key] for r in sel(rows, level=lvl, arm="TRT_B")])
            seeds = sorted(set(A) & set(TA))
            a = np.array([A[s] for s in seeds])
            ta = np.array([TA[s] for s in seeds])
            av = np.array([A[s] for s in sorted(A)])
            n = len(seeds)
            sA, sTA, sTB = (av.std(ddof=1), ta.std(ddof=1), TB.std(ddof=1))
            if sA == 0 and sTA == 0 and sTB == 0:
                md += ["### %s" % label, "",
                       "Degenerate: this metric has exactly zero variance in "
                       "every arm at this loading level (every replication "
                       "completes all %.0f trips), so no test is defined and "
                       "no design can be preferred." % av.mean(), ""]
                continue

            var_ind = sTB ** 2 / len(TB) + sA ** 2 / len(av)
            diff_ind = TB.mean() - av.mean()
            t_ind, p_ind = stats.ttest_ind(TB, av, equal_var=False)
            df_ind = (var_ind ** 2) / ((sTB ** 2 / len(TB)) ** 2 / (len(TB) - 1)
                                       + (sA ** 2 / len(av)) ** 2 / (len(av) - 1))
            hw_ind = stats.t.ppf(0.975, df_ind) * math.sqrt(var_ind)

            dvec = ta - a
            t_par, p_par = stats.ttest_rel(ta, a)
            var_par = dvec.var(ddof=1) / n
            hw_par = stats.t.ppf(0.975, n - 1) * math.sqrt(var_par)
            rho = float(np.corrcoef(a, ta)[0, 1]) if sA > 0 and sTA > 0 else float("nan")
            vrf_emp = var_ind / var_par if var_par > 0 else float("inf")
            den = sA ** 2 + sTA ** 2 - 2 * rho * sA * sTA
            vrf_theo = (sA ** 2 + sTA ** 2) / den if den > 0 else float("inf")
            sign_agree = float(np.mean(np.sign(dvec) == np.sign(dvec.mean())))

            md += ["### %s" % label, "",
                   "| design | estimated difference (treatment - baseline) | Var(estimate) | 95% CI | t | p | significant at 5%? |",
                   "|---|---|---|---|---|---|---|",
                   "| independent seeds (Welch two-sample) | %+.3f | %.5g | [%+.3f, %+.3f] | %.3f | %.4g | %s |"
                   % (diff_ind, var_ind, diff_ind - hw_ind, diff_ind + hw_ind,
                      t_ind, p_ind, "YES" if p_ind < 0.05 else "no"),
                   "| common random numbers (paired) | %+.3f | %.5g | [%+.3f, %+.3f] | %.3f | %.4g | %s |"
                   % (dvec.mean(), var_par, dvec.mean() - hw_par,
                      dvec.mean() + hw_par, t_par, p_par,
                      "YES" if p_par < 0.05 else "no"),
                   "",
                   "* correlation between paired arms rho = **%.3f**" % rho,
                   "* VRF (empirical) = **%.2fx**; VRF (theoretical, from rho) = **%.2fx**"
                   % (vrf_emp, vrf_theo),
                   "* CI half-width shrinks by %.2fx (empirical)" % math.sqrt(vrf_emp),
                   "* a single CRN pair reproduces the sign of the 40-pair mean "
                   "effect in **%.0f%%** of the 40 pairs" % (100 * sign_agree),
                   ""]
            out["%s|%s" % (lvl, key)] = dict(
                level=lvl, metric=key, n=n, diff_ind=diff_ind, var_ind=var_ind,
                p_ind=p_ind, diff_par=float(dvec.mean()), var_par=var_par,
                p_par=p_par, rho=rho, vrf_empirical=vrf_emp,
                vrf_theoretical=vrf_theo, sign_agree=sign_agree,
                sd_base=float(sA), sd_diff_paired=float(dvec.std(ddof=1)),
                mean_base=float(av.mean()))

            if key == "mean_duration":
                ax = axes[0][j]
                ax.scatter(a, ta, s=24, alpha=.85, zorder=3)
                lo = min(a.min(), ta.min()); hi = max(a.max(), ta.max())
                ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="no effect")
                ax.set_xlabel("baseline mean trip duration (s)")
                ax.set_ylabel("cycle x0.8, same seed (s)")
                ax.set_title("%s   rho=%.2f   VRF=%.1fx" % (lvl, rho, vrf_emp),
                             fontsize=10)
                ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.suptitle("Common random numbers: paired baseline vs treatment, "
                 "one point per seed (n=40)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "crn_scatter.png"), dpi=130)
    plt.close(fig)

    recs = list(out.values())
    with open(os.path.join(OUT, "crn_vs_independent.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)
    open(os.path.join(OUT, "crn_vs_independent.md"), "w").write("\n".join(md) + "\n")
    return out


# ===========================================================================
# 6. single-run detectability
# ===========================================================================
def single_run_power(rows, crn):
    md = ["# What a single-seed comparison could legitimately have detected", "",
          "A single run per arm provides **zero degrees of freedom** -- no",
          "variance can be estimated from it, so strictly speaking no",
          "confidence interval and no test exist. The numbers below therefore",
          "*grant* the single-run analyst perfect knowledge of sigma (estimated",
          "here from 40 replications). They are an upper bound on how good a",
          "single-seed comparison could possibly be, not an achievable one.", "",
          "Minimum detectable difference (MDD) at 95% confidence, n=1 per arm:",
          "",
          "* independent seeds:      MDD = 1.96 * sqrt(2) * s",
          "* common random numbers:  MDD = 1.96 * s_D   (s_D = sd of the paired difference)",
          "",
          "| level | metric | mean | s (between-rep) | s_D (paired diff) | MDD, 1 indep seed | % of mean | MDD, 1 CRN pair | % of mean |",
          "|---|---|---|---|---|---|---|---|---|"]
    recs = []
    for lvl in LEVEL_ORDER:
        for key, label in CORE:
            c = ci95(vals(sel(rows, level=lvl, family="BOTH"), key))
            k = "%s|%s" % (lvl, key)
            sd_d = crn[k]["sd_diff_paired"] if k in crn else float("nan")
            mdd_i = 1.959964 * math.sqrt(2) * c["sd"]
            mdd_c = 1.959964 * sd_d
            recs.append(dict(level=lvl, metric=key, mean=c["mean"], s=c["sd"],
                             s_d=sd_d, mdd_indep=mdd_i,
                             mdd_indep_pct=100 * mdd_i / c["mean"] if c["mean"] else np.nan,
                             mdd_crn=mdd_c,
                             mdd_crn_pct=100 * mdd_c / c["mean"] if c["mean"] else np.nan))
            f = lambda v: ("%.3f" % v) if v == v else "n/a"
            g = lambda v: ("%.2f%%" % (100 * v / c["mean"])) if v == v and c["mean"] else "n/a"
            md.append("| %s | %s | %.2f | %.4g | %s | %s | %s | %s | %s |"
                      % (lvl, label, c["mean"], c["sd"], f(sd_d), f(mdd_i),
                         g(mdd_i), f(mdd_c), g(mdd_c)))
    with open(os.path.join(OUT, "single_run_detectability.csv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
        w.writeheader()
        for r in recs:
            w.writerow(r)
    open(os.path.join(OUT, "single_run_detectability.md"),
         "w").write("\n".join(md) + "\n")
    return recs


if __name__ == "__main__":
    rows = load()
    print("loaded %d replication records" % len(rows))
    results_table(rows);        print("  results_table.{csv,md}")
    variance_sources(rows);     print("  variance_sources.{csv,md}")
    wrecs, wmd = warmup_analysis(rows)
    truncation_curves(wrecs, wmd)
    print("  warmup_analysis.{csv,md}, warmup_truncation.csv, 3 warm-up plots")
    replication_count(rows)
    print("  required_n.{csv,md}, ci_halfwidth_vs_n.png, cv_vs_vc.png")
    crn = crn_experiment(rows)
    print("  crn_vs_independent.{csv,md}, crn_scatter.png")
    single_run_power(rows, crn)
    print("  single_run_detectability.{csv,md}")
