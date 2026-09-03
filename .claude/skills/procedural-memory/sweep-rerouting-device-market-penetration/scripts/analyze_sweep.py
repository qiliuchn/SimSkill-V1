#!/usr/bin/env python3
"""Aggregate, test and plot the market-penetration sweep.

Produces
  results_table.csv          per-cell means with 95% CI half-widths
  stats_tests.txt            paired (CRN) tests for the two headline claims
  plots/*.png

Statistics
  Cells share a seed list (Common Random Numbers), so every cross-penetration
  comparison is done PAIRED, seed by seed, with a paired t-test on the per-seed
  differences.  CIs on levels use the ordinary t interval across seeds; CIs on
  DIFFERENCES use the paired standard error, which is the number that actually
  decides whether a bump in the penetration curve is real.

Non-monotonicity test
  A U-shape / interior optimum is only claimed if BOTH legs are individually
  significant under the paired test: the drop from p=0 to the argmin, and the
  rise from the argmin to p=1.  Reporting a non-monotone-looking mean curve
  without testing both legs is exactly the failure mode this project's
  replication methodology warns about.
"""
import argparse
import csv
import math
import os
from collections import defaultdict

import numpy as np
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INC_B, INC_E = 900.0, 2400.0
C_MAIN, C_ALT, C_EQ, C_UN = "#3b6ea5", "#c86b3c", "#2f8f6b", "#8a5fb0"


def read_rows(path):
    with open(path) as f:
        return [r for r in csv.DictReader(f)]


def fnum(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def ci95(vals):
    v = np.asarray([x for x in vals if x is not None], float)
    if len(v) < 2:
        return (float(v.mean()) if len(v) else float("nan")), float("nan"), len(v)
    return float(v.mean()), float(stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v))), len(v)


def paired_test(by_seed_a, by_seed_b):
    """paired difference b - a over the seeds present in both."""
    seeds = sorted(set(by_seed_a) & set(by_seed_b))
    d = np.array([by_seed_b[s] - by_seed_a[s] for s in seeds], float)
    d = d[~np.isnan(d)]
    if len(d) < 2:
        return float("nan"), float("nan"), float("nan"), len(d)
    t, p = stats.ttest_rel(
        [by_seed_b[s] for s in seeds if not math.isnan(by_seed_b[s] - by_seed_a[s])],
        [by_seed_a[s] for s in seeds if not math.isnan(by_seed_b[s] - by_seed_a[s])])
    hw = stats.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / math.sqrt(len(d))
    return float(d.mean()), float(hw), float(p), len(d)


# ---------------------------------------------------------------- oscillation
def oscillation_metrics(csv_path, t0=INC_B, t1=INC_E + 1200):
    """Route-split oscillation, measured from the REAL 30 s route-split time series.

    Returns (sd, masd, rng, n) where
      sd   = standard deviation of the alternate's share of diverge flow
      masd = mean absolute successive difference of that share -- the flip-flop
             measure. A smooth ramp up and back down has a small masd; a series
             that bang-bangs between 0 and 1 has a large one. sd alone cannot
             tell those apart, which is why both are reported.
      rng  = max - min of the share
    """
    xs = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            t = float(r["t_begin"])
            if not (t0 <= t < t1):
                continue
            if r["alt_share"] == "":
                continue
            xs.append(float(r["alt_share"]))
    if len(xs) < 3:
        return float("nan"), float("nan"), float("nan"), len(xs)
    a = np.asarray(xs)
    return float(a.std(ddof=1)), float(np.abs(np.diff(a)).mean()), float(a.max() - a.min()), len(a)


def load_timeseries(work, scenario, pen, seed):
    p = os.path.join(work, scenario, "%s_p%03d_s%02d" % (scenario, int(round(pen * 100)), seed),
                     "route_split_timeseries.csv")
    return p if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--plotdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    os.makedirs(a.plotdir, exist_ok=True)

    rows = read_rows(a.metrics)
    scen = sorted(set(r["scenario"] for r in rows))
    pens = sorted(set(float(r["penetration"]) for r in rows))
    seeds = sorted(set(int(r["seed"]) for r in rows))

    METRICS = ["mean_tt_all", "mean_tt_equipped", "mean_tt_unequipped", "total_tt_all",
               "mean_tt_cohort_all", "mean_tt_cohort_equipped", "mean_tt_cohort_unequipped",
               "alt_share_equipped", "alt_share_overall", "cohort_alt_share_equipped",
               "mean_route_switches_equipped", "teleports"]

    # by_seed[scenario][pen][metric][seed] = value
    by_seed = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for r in rows:
        s, p, sd = r["scenario"], float(r["penetration"]), int(r["seed"])
        for m in METRICS:
            v = fnum(r.get(m))
            if v is not None:
                by_seed[s][p][m][sd] = v

    # oscillation, computed per run from the raw route-split series
    osc = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for s in scen:
        for p in pens:
            for sd in seeds:
                ts = load_timeseries(a.workdir, s, p, sd)
                if not ts:
                    continue
                sdv, masd, rng, n = oscillation_metrics(ts)
                osc[s][p]["osc_sd"][sd] = sdv
                osc[s][p]["osc_masd"][sd] = masd
                osc[s][p]["osc_range"][sd] = rng
    for s in scen:
        for p in pens:
            for k in ("osc_sd", "osc_masd", "osc_range"):
                by_seed[s][p][k] = osc[s][p][k]
    METRICS += ["osc_sd", "osc_masd", "osc_range"]

    # ---------------- results table ----------------
    tpath = os.path.join(a.outdir, "results_table.csv")
    with open(tpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "penetration", "n_seeds", "metric", "mean", "ci95_halfwidth"])
        for s in scen:
            for p in pens:
                for m in METRICS:
                    mu, hw, n = ci95(list(by_seed[s][p][m].values()))
                    w.writerow([s, p, n, m, "%.5f" % mu, "%.5f" % hw])
    print("wrote " + tpath)

    out = []

    def sec(t):
        out.append("")
        out.append("=" * 78)
        out.append(t)
        out.append("=" * 78)

    # ---------------- H1: private benefit decay ----------------
    sec("H1  PRIVATE BENEFIT OF BEING EQUIPPED, BY PENETRATION  (scenario incident_fast)")
    out.append("Paired per-seed gap  (unequipped mean TT) - (equipped mean TT), incident-exposed")
    out.append("cohort = vehicles departing inside the incident window [900, 2400) s.")
    out.append("A positive gap means being informed is privately worth something.")
    out.append("")
    out.append("  pen   n   gap [s]   95% CI      p (H0: gap=0)   equipped TT   unequipped TT")
    for p in pens:
        if p in (0.0,):
            out.append("  %.2f   -   (no equipped vehicles exist at p=0)" % p)
            continue
        eq = by_seed["incident_fast"][p]["mean_tt_cohort_equipped"]
        un = by_seed["incident_fast"][p]["mean_tt_cohort_unequipped"]
        if p >= 1.0 or not un:
            mu_e, hw_e, _ = ci95(list(eq.values()))
            out.append("  %.2f   -   (no unequipped vehicles exist at p=1)          %7.1f" % (p, mu_e))
            continue
        d, hw, pv, n = paired_test(eq, un)     # un - eq
        mu_e, _, _ = ci95(list(eq.values()))
        mu_u, _, _ = ci95(list(un.values()))
        out.append("  %.2f  %2d  %+8.1f  +/-%6.1f   p=%-9.2g   %9.1f   %9.1f"
                   % (p, n, d, hw, pv, mu_e, mu_u))

    # ---------------- H2: system-level non-monotonicity ----------------
    for metric, label in (("mean_tt_cohort_all", "incident-exposed cohort mean total travel time"),
                          ("mean_tt_all", "network-wide mean total travel time")):
        sec("H2  SYSTEM-LEVEL EFFECT OF PENETRATION -- %s (incident_fast)" % label)
        means = {p: ci95(list(by_seed["incident_fast"][p][metric].values())) for p in pens}
        out.append("  pen    mean [s]   95% CI      vs p=0 (paired)          p")
        base = by_seed["incident_fast"][0.0][metric]
        for p in pens:
            mu, hw, n = means[p]
            if p == 0.0:
                out.append("  %.2f  %9.1f  +/-%6.1f     (reference)" % (p, mu, hw))
            else:
                d, dhw, pv, nn = paired_test(base, by_seed["incident_fast"][p][metric])
                out.append("  %.2f  %9.1f  +/-%6.1f   %+8.1f +/-%6.1f   p=%.3g"
                           % (p, mu, hw, d, dhw, pv))
        best = min(pens, key=lambda p: means[p][0])
        out.append("")
        out.append("  argmin over the swept levels: p* = %.2f (mean %.1f s)" % (best, means[best][0]))
        if 0.0 < best < 1.0:
            d1, h1, p1, _ = paired_test(by_seed["incident_fast"][0.0][metric],
                                        by_seed["incident_fast"][best][metric])
            d2, h2, p2, _ = paired_test(by_seed["incident_fast"][best][metric],
                                        by_seed["incident_fast"][1.0][metric])
            out.append("  descending leg p=0    -> p=%.2f : %+.1f +/- %.1f s, p=%.3g" % (best, d1, h1, p1))
            out.append("  ascending  leg p=%.2f -> p=1.00 : %+.1f +/- %.1f s, p=%.3g" % (best, d2, h2, p2))
            verdict = ("NON-MONOTONIC (interior optimum), both legs significant at 5%"
                       if (p1 < 0.05 and d1 < 0 and p2 < 0.05 and d2 > 0)
                       else "interior argmin present but NOT both legs significant -- do not claim a U-shape")
            out.append("  VERDICT: " + verdict)
        else:
            out.append("  VERDICT: argmin sits at a swept endpoint -- no interior optimum detected.")

    # ---------------- H3: oscillation, fast vs smoothed ----------------
    sec("H3  ROUTE-SPLIT OSCILLATION, FAST vs SMOOTHED ADAPTATION")
    out.append("Measured from the 30 s route-split time series (alternate's share of flow past")
    out.append("the diverge), over [900, 3600) s. masd = mean |share(t+1)-share(t)|.")
    out.append("")
    out.append("  pen        osc_sd fast    osc_sd smooth   |   masd fast     masd smooth    paired p (masd)")
    for p in pens:
        if p == 0.0:
            continue
        f_sd, f_sdh, _ = ci95(list(by_seed["incident_fast"][p]["osc_sd"].values()))
        s_sd, s_sdh, _ = ci95(list(by_seed["incident_smooth"][p]["osc_sd"].values()))
        f_m, f_mh, _ = ci95(list(by_seed["incident_fast"][p]["osc_masd"].values()))
        s_m, s_mh, _ = ci95(list(by_seed["incident_smooth"][p]["osc_masd"].values()))
        d, hw, pv, n = paired_test(by_seed["incident_fast"][p]["osc_masd"],
                                   by_seed["incident_smooth"][p]["osc_masd"])
        out.append("  %.2f   %.3f+/-%.3f   %.3f+/-%.3f   |  %.3f+/-%.3f  %.3f+/-%.3f   %+.3f p=%.3g"
                   % (p, f_sd, f_sdh, s_sd, s_sdh, f_m, f_mh, s_m, s_mh, d, pv))
    out.append("")
    out.append("Per-vehicle intra-trip route flip-flops (mean number of times an equipped")
    out.append("vehicle's chosen route changed between main and alternate before arriving):")
    out.append("  pen     fast            smoothed        random-factor")
    for p in pens:
        if p == 0.0:
            continue
        r = []
        for s in ("incident_fast", "incident_smooth", "incident_rnd"):
            mu, hw, n = ci95(list(by_seed[s][p]["mean_route_switches_equipped"].values()))
            r.append("%.3f+/-%.3f" % (mu, hw))
        out.append("  %.2f    %-15s %-15s %-15s" % (p, r[0], r[1], r[2]))

    # ---------------- H3b: spurious pre-incident diversion ----------------
    sec("H3b  SPURIOUS DIVERSION BEFORE THE INCIDENT EVEN STARTS")
    out.append("Mean alternate share over [300, 900) s -- a window in which the network is")
    out.append("undisrupted and the alternate is genuinely ~21% slower, so the correct")
    out.append("alternate share is ZERO. Anything above zero is the device chasing noise in")
    out.append("its own travel-time estimate.")
    out.append("")
    out.append("  pen     fast             smoothed         no-incident/fast")
    for p in pens:
        if p == 0.0:
            continue
        cells = []
        for s in ("incident_fast", "incident_smooth", "noincident_fast"):
            vals = []
            for sd in seeds:
                ts = load_timeseries(a.workdir, s, p, sd)
                if not ts:
                    continue
                xs = []
                with open(ts) as f:
                    for r in csv.DictReader(f):
                        t = float(r["t_begin"])
                        if 300 <= t < 900 and r["alt_share"] != "":
                            xs.append(float(r["alt_share"]))
                if xs:
                    vals.append(float(np.mean(xs)))
            mu, hw, n = ci95(vals)
            cells.append("%.3f+/-%.3f" % (mu, hw))
        out.append("  %.2f    %-16s %-16s %-16s" % (p, cells[0], cells[1], cells[2]))

    # ---------------- H4: incident-free control ----------------
    sec("H4  HONEST CONTROL -- INCIDENT-FREE NETWORK (noincident_fast)")
    out.append("With no disruption the alternate is genuinely worse, so information should buy")
    out.append("little or nothing. Any large gain here would mean the network, not the incident,")
    out.append("is doing the work.")
    out.append("")
    out.append("  pen   mean TT [s]   95% CI    vs p=0 (paired)      p")
    base = by_seed["noincident_fast"][0.0]["mean_tt_all"]
    for p in pens:
        mu, hw, n = ci95(list(by_seed["noincident_fast"][p]["mean_tt_all"].values()))
        if p == 0.0:
            out.append("  %.2f  %10.2f  +/-%5.2f    (reference)" % (p, mu, hw))
        else:
            d, dhw, pv, _ = paired_test(base, by_seed["noincident_fast"][p]["mean_tt_all"])
            out.append("  %.2f  %10.2f  +/-%5.2f  %+7.2f +/-%5.2f   p=%.3g" % (p, mu, hw, d, dhw, pv))

    # ---------------- H5: mitigation ----------------
    sec("H5  HERDING MITIGATION -- --weights.random-factor 1.4 (incident_rnd vs incident_fast)")
    out.append("  pen   fast mean TT   rnd mean TT   paired diff (rnd-fast)      p")
    for p in pens:
        f, fh, _ = ci95(list(by_seed["incident_fast"][p]["mean_tt_cohort_all"].values()))
        rr, rh, _ = ci95(list(by_seed["incident_rnd"][p]["mean_tt_cohort_all"].values()))
        d, dhw, pv, _ = paired_test(by_seed["incident_fast"][p]["mean_tt_cohort_all"],
                                    by_seed["incident_rnd"][p]["mean_tt_cohort_all"])
        out.append("  %.2f  %10.1f    %10.1f    %+9.1f +/-%6.1f   p=%.3g" % (p, f, rr, d, dhw, pv))

    # ---------------- CRN diagnostics ----------------
    sec("CRN DIAGNOSTIC -- is pairing across penetration levels actually helping?")
    out.append("Correlation of per-seed outcomes between p=0.25 and p=0.50 (incident_fast),")
    out.append("and the variance-reduction factor of the paired vs unpaired difference estimate.")
    for m in ("mean_tt_cohort_all", "alt_share_overall"):
        A = by_seed["incident_fast"][0.25][m]
        B = by_seed["incident_fast"][0.50][m]
        ss = sorted(set(A) & set(B))
        x = np.array([A[s] for s in ss]);  y = np.array([B[s] for s in ss])
        if len(ss) > 2 and x.std() > 0 and y.std() > 0:
            rho = float(np.corrcoef(x, y)[0, 1])
            var_paired = (y - x).var(ddof=1)
            var_indep = x.var(ddof=1) + y.var(ddof=1)
            out.append("  %-22s rho=%+.3f  var(paired diff)=%.4g  var(indep diff)=%.4g  VRF=%.2fx"
                       % (m, rho, var_paired, var_indep, var_indep / var_paired if var_paired else float("nan")))

    txt = "\n".join(out)
    print(txt)
    with open(os.path.join(a.outdir, "stats_tests.txt"), "w") as f:
        f.write(txt + "\n")

    # =========================== PLOTS ===========================
    def band(ax, xs, mus, hws, color, label, marker="o"):
        mus = np.array(mus, float); hws = np.array(hws, float)
        ax.plot(xs, mus, marker=marker, color=color, lw=2, ms=5, label=label)
        ax.fill_between(xs, mus - hws, mus + hws, color=color, alpha=0.18, lw=0)

    # P1 equipped vs unequipped
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, metric_pair, ttl in (
            (axes[0], ("mean_tt_cohort_equipped", "mean_tt_cohort_unequipped"),
             "Incident-exposed cohort (depart 900-2400 s)"),
            (axes[1], ("mean_tt_equipped", "mean_tt_unequipped"), "All vehicles")):
        for key, col, lab in ((metric_pair[0], C_EQ, "equipped (has rerouting device)"),
                              (metric_pair[1], C_UN, "unequipped")):
            xs, mus, hws = [], [], []
            for p in pens:
                vals = list(by_seed["incident_fast"][p][key].values())
                if not vals:
                    continue
                mu, hw, n = ci95(vals)
                xs.append(p); mus.append(mu); hws.append(0 if math.isnan(hw) else hw)
            band(ax, xs, mus, hws, col, lab)
        xs, mus, hws = [], [], []
        for p in pens:
            mu, hw, n = ci95(list(by_seed["incident_fast"][p][
                "mean_tt_cohort_all" if "cohort" in metric_pair[0] else "mean_tt_all"].values()))
            xs.append(p); mus.append(mu); hws.append(hw)
        band(ax, xs, mus, hws, "#555555", "everyone (network-wide)", marker="s")
        ax.set_xlabel("rerouting-device market penetration")
        ax.set_ylabel("mean total travel time [s]")
        ax.set_title(ttl, fontsize=10)
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
    fig.suptitle("Private vs. system benefit of real-time information (incident, fast adaptation)\n"
                 "bands = 95% CI over 10 CRN seeds", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plotdir, "equipped_vs_unequipped_by_penetration.png"), dpi=140)
    plt.close(fig)

    # P2 network metric by penetration, all scenarios
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, metric, ttl in ((axes[0], "mean_tt_cohort_all", "incident-exposed cohort mean total TT"),
                            (axes[1], "alt_share_overall", "share of all vehicles using the alternate")):
        for s, col, mk in (("incident_fast", C_MAIN, "o"), ("incident_smooth", C_ALT, "^"),
                           ("incident_rnd", C_EQ, "v"), ("noincident_fast", "#999999", "s")):
            xs, mus, hws = [], [], []
            for p in pens:
                mu, hw, n = ci95(list(by_seed[s][p][metric].values()))
                xs.append(p); mus.append(mu); hws.append(0 if math.isnan(hw) else hw)
            band(ax, xs, mus, hws, col, s, marker=mk)
        ax.set_xlabel("rerouting-device market penetration")
        ax.set_ylabel(ttl)
        ax.grid(alpha=.25); ax.legend(fontsize=8)
    axes[0].set_title("System performance vs penetration (95% CI, 10 CRN seeds)", fontsize=10)
    axes[1].set_title("Diversion uptake vs penetration", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plotdir, "network_metric_by_penetration.png"), dpi=140)
    plt.close(fig)

    # P3 oscillation time series, fast vs smoothed, at p=1.0 and p=0.5
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, p in zip(axes, (0.5, 1.0)):
        for s, col in (("incident_fast", C_MAIN), ("incident_smooth", C_ALT)):
            ts = load_timeseries(a.workdir, s, p, 1)
            if not ts:
                continue
            T, S = [], []
            with open(ts) as f:
                for r in csv.DictReader(f):
                    if r["alt_share"] == "":
                        continue
                    t = float(r["t_begin"])
                    if 600 <= t < 4200:
                        T.append(t); S.append(float(r["alt_share"]))
            m, _, _ = ci95(list(by_seed[s][p]["osc_masd"].values()))
            ax.plot(T, S, color=col, lw=1.4, label="%s (masd=%.3f)" % (s, m))
        ax.axvspan(INC_B, INC_E, color="#d0d0d0", alpha=.55, zorder=0, label="incident window")
        ax.set_ylabel("alternate's share of\nflow past the diverge")
        ax.set_title("penetration = %.2f  (seed 1)" % p, fontsize=10)
        ax.grid(alpha=.25); ax.legend(fontsize=8, loc="upper right"); ax.set_ylim(-0.03, 1.03)
    axes[-1].set_xlabel("simulation time [s]")
    fig.suptitle("Route-split oscillation: fast vs smoothed travel-time adaptation", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plotdir, "route_split_oscillation_timeseries.png"), dpi=140)
    plt.close(fig)

    # P4 oscillation amplitude vs penetration
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for s, col, mk in (("incident_fast", C_MAIN, "o"), ("incident_smooth", C_ALT, "^"),
                       ("incident_rnd", C_EQ, "v")):
        xs, mus, hws = [], [], []
        for p in pens:
            if p == 0.0:
                continue
            mu, hw, n = ci95(list(by_seed[s][p]["osc_masd"].values()))
            xs.append(p); mus.append(mu); hws.append(0 if math.isnan(hw) else hw)
        band(ax, xs, mus, hws, col, s, marker=mk)
    ax.set_xlabel("rerouting-device market penetration")
    ax.set_ylabel("mean abs. successive difference\nof alternate-route share")
    ax.set_title("Route-split flip-flop amplitude (95% CI, 10 CRN seeds)", fontsize=10)
    ax.grid(alpha=.25); ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plotdir, "oscillation_amplitude_by_penetration.png"), dpi=140)
    plt.close(fig)
    print("\nwrote plots to " + a.plotdir)


if __name__ == "__main__":
    main()
