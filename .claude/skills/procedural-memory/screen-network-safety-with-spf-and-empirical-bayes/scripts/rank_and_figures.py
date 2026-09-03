"""
Frequency-vs-rate rank comparison + all deliverable figures.

Figure 1  RTM demonstration across years of data (the required RTM figure)
Figure 2  Screening method comparison (Spearman rho with 95% CI) for both problems
Figure 3  Frequency vs rate ranking (the "they rank sites differently" evidence)
Figure 4  Matched pair + phasing triplet: what the SSM sees that the SPF cannot
Figure 5  Conflict-to-crash transfer function with its prediction interval
"""
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import rankdata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hsm

C = dict(true="#26428B", naive="#C8553D", eb="#2A9D8F", sim="#8E6BBF",
         grey="#8A8F98", light="#D7DAE0")


def spearman(a, b):
    ra, rb = rankdata(a) - rankdata(a).mean(), rankdata(b) - rankdata(b).mean()
    return float((ra * rb).sum() / math.sqrt((ra * ra).sum() * (rb * rb).sum()))


def style(ax, title=None, xlabel=None, ylabel=None):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=C["light"], lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=10.5, loc="left", pad=9, weight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=8.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--fig-dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.fig_dir, exist_ok=True)
    A = a.analysis_dir

    tbl = list(csv.DictReader(open(os.path.join(A, "site_table.csv"))))
    sites = [r["site"] for r in tbl]
    ctrl = [r["control"] for r in tbl]
    f = lambda c: np.array([float(r[c]) for r in tbl])
    n_true, n_true_ang = f("n_true"), f("n_true_angle")
    conf_f, conf_r = f("sim_conflicts"), f("sim_conf_rate_mev")
    cross_f, cross_r = f("sim_conf_crossing"), f("sim_crossing_rate_mev")
    mev = f("mev_per_year")

    # ---------- frequency vs rate ----------
    rows = []
    rk = lambda v: (len(v) + 1 - rankdata(v)).astype(int)   # rank 1 = worst
    r_true, r_cf, r_cr = rk(n_true), rk(conf_f), rk(conf_r)
    r_xf, r_xr = rk(cross_f), rk(cross_r)
    r_crash_rate = rk(n_true / mev)
    for i, s in enumerate(sites):
        rows.append(dict(site=s, control=ctrl[i],
                         rank_true_crash_freq=r_true[i],
                         rank_true_crash_rate=r_crash_rate[i],
                         crash_freq_vs_rate_shift=int(r_crash_rate[i] - r_true[i]),
                         rank_conflict_freq=r_cf[i], rank_conflict_rate=r_cr[i],
                         conflict_freq_vs_rate_shift=int(r_cr[i] - r_cf[i]),
                         rank_crossing_freq=r_xf[i], rank_crossing_rate=r_xr[i],
                         conflicts=round(conf_f[i], 1),
                         conflict_rate_per_mev=round(conf_r[i], 0),
                         n_true=round(n_true[i], 3)))
    with open(os.path.join(A, "rank_frequency_vs_rate.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    summary = dict(
        spearman_conflict_freq_vs_conflict_rate=round(spearman(conf_f, conf_r), 4),
        spearman_crossing_freq_vs_crossing_rate=round(spearman(cross_f, cross_r), 4),
        spearman_true_crash_freq_vs_true_crash_rate=round(spearman(n_true, n_true / mev), 4),
        max_abs_rank_shift_conflict=int(np.abs(r_cr - r_cf).max()),
        mean_abs_rank_shift_conflict=round(float(np.abs(r_cr - r_cf).mean()), 3),
        max_abs_rank_shift_crash=int(np.abs(r_crash_rate - r_true).max()),
        mean_abs_rank_shift_crash=round(float(np.abs(r_crash_rate - r_true).mean()), 3),
        biggest_conflict_movers=[dict(site=sites[i], freq_rank=int(r_cf[i]),
                                      rate_rank=int(r_cr[i]), shift=int(r_cr[i] - r_cf[i]))
                                 for i in np.argsort(-np.abs(r_cr - r_cf))[:5]],
        biggest_crash_movers=[dict(site=sites[i], freq_rank=int(r_true[i]),
                                   rate_rank=int(r_crash_rate[i]),
                                   shift=int(r_crash_rate[i] - r_true[i]))
                              for i in np.argsort(-np.abs(r_crash_rate - r_true))[:5]])
    json.dump(summary, open(os.path.join(A, "rank_frequency_vs_rate_summary.json"), "w"), indent=2)
    print(json.dumps(summary, indent=2))

    # ================= FIGURE 1: RTM =================
    rtm = [r for r in csv.DictReader(open(os.path.join(A, "rtm_years_sweep.csv")))
           if r["problem"] == "A_total"]
    Y = [int(r["years"]) for r in rtm]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.1))
    ax = axes[0]
    # NOTE: the per-replication FP count is an integer in {0,1,2,3}; its 95%
    # percentile interval is therefore almost always the full [0,3] range and
    # conveys nothing.  The informative uncertainty is on the MEAN, so a
    # standard error of the mean is drawn instead (and the full percentile
    # interval is kept in rtm_years_sweep.csv).
    for key, col, mk, lab in (("naive_fp3", C["naive"], "o", "naive observed frequency"),
                              ("eb_fp3", C["eb"], "s", "Empirical Bayes")):
        mu = np.array([float(r[key]) for r in rtm])
        sem = np.array([(float(r[key + "_hi95"]) - float(r[key + "_lo95"])) / 3.92
                        for r in rtm]) / math.sqrt(int(rtm[0]["mc"]))
        ax.errorbar(Y, mu, yerr=1.96 * sem, fmt=mk + "-", color=col, lw=2,
                    capsize=3, elinewidth=1.1, label=lab)
    ax.set_ylim(0, 3)
    style(ax, "False positives in the top-3 list\n(mean over 2000 histories, 95% CI of the mean)",
          "years of crash data (Y)", "sites in top-3 that are NOT truly top-3")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    ax.plot(Y, [float(r["rtm_drop_naive_pct"]) for r in rtm], "o-", color=C["naive"], lw=2,
            label="naive-selected top-3")
    ax.plot(Y, [float(r["rtm_drop_eb_pct"]) for r in rtm], "s-", color=C["eb"], lw=2,
            label="EB-selected top-3")
    ax.axhline(0, color=C["grey"], lw=0.8)
    style(ax, "Regression to the mean", "years of crash data (Y)",
          "% drop in observed crashes,\nselection period -> next period")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[2]
    ew = [r for r in csv.DictReader(open(os.path.join(A, "eb_weights.csv")))]
    for ctl, mk in (("4SG", "o"), ("4ST", "s"), ("3ST", "^")):
        rs = [r for r in ew if r["control"] == ctl]
        ax.plot([int(r["years"]) for r in rs], [float(r["mean_eb_weight_w"]) for r in rs],
                mk + "-", lw=2, label="%s  (k=%s)" % (ctl, rs[0]["k"]))
    style(ax, "EB shrinkage weight w = 1/(1+k·N·Y)", "years of crash data (Y)",
          "mean weight on the SPF prediction")
    ax.legend(fontsize=8, frameon=False)
    fig.suptitle("Regression to the mean in crash-based hotspot identification "
                 "(20 sites, 2000 Monte-Carlo crash histories)", fontsize=11.5, y=1.0)
    fig.tight_layout()
    fig.savefig(os.path.join(a.fig_dir, "fig1_regression_to_the_mean.png"), dpi=170,
                bbox_inches="tight")
    plt.close(fig)

    # ================= FIGURE 2: method comparison =================
    sc = list(csv.DictReader(open(os.path.join(A, "screening_comparison.csv"))))
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.6))
    for ax, prob, ttl in ((axes[0], "A_total", "Problem A: total crashes\n(SPF is a correctly-specified ORACLE here — rho=1 is a tautology)"),
                          (axes[1], "B_angle", "Problem B: angle / left-turn crashes\n(SPF is phasing-blind — genuinely mis-specified)")):
        rs = [r for r in sc if r["problem"] == prob and r["years"] == "3"]
        names = [r["method"] for r in rs]
        vals = [float(r["spearman"]) for r in rs]
        lo = [float(r["spearman"]) - float(r["spearman_lo95"]) for r in rs]
        hi = [float(r["spearman_hi95"]) - float(r["spearman"]) for r in rs]
        cols = [C["sim"] if ("conf" in n or "cross" in n or "severe" in n)
                else (C["naive"] if n.startswith("obs") else
                      (C["eb"] if n.startswith("eb") else C["true"])) for n in names]
        yy = np.arange(len(names))
        ax.barh(yy, vals, xerr=[lo, hi], color=cols, height=0.66,
                error_kw=dict(lw=1.1, ecolor="#44484F", capsize=2.5), zorder=3)
        ax.set_yticks(yy); ax.set_yticklabels(names, fontsize=8.2)
        ax.invert_yaxis()
        ax.axvline(0, color=C["grey"], lw=0.8)
        style(ax, ttl, "Spearman rho vs TRUE mean crash frequency (95% CI)")
        ax.grid(axis="y", visible=False); ax.grid(axis="x", color=C["light"], lw=0.7)
    fig.suptitle("Screening-method accuracy, Y=3 years of crash data, 2000 Monte-Carlo replications",
                 fontsize=11.5, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(a.fig_dir, "fig2_screening_methods.png"), dpi=170, bbox_inches="tight")
    plt.close(fig)

    # ================= FIGURE 3: frequency vs rate =================
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    ax = axes[0]
    for i, s in enumerate(sites):
        ax.plot([0, 1], [r_cf[i], r_cr[i]], "-", color=C["grey"], lw=0.9, alpha=0.7, zorder=2)
        ax.plot(0, r_cf[i], "o", color=C["sim"], ms=5, zorder=3)
        ax.plot(1, r_cr[i], "o", color=C["true"], ms=5, zorder=3)
        ax.annotate(s, (0, r_cf[i]), textcoords="offset points", xytext=(-19, -3), fontsize=7)
        ax.annotate(s, (1, r_cr[i]), textcoords="offset points", xytext=(5, -3), fontsize=7)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["conflict FREQUENCY", "conflict RATE per MEV"], fontsize=9)
    ax.set_xlim(-0.35, 1.35); ax.invert_yaxis()
    style(ax, "Frequency and rate rank the same sites differently\n(rank 1 = worst; Spearman rho = %.3f)"
          % summary["spearman_conflict_freq_vs_conflict_rate"], None, "rank")
    ax.grid(axis="y", visible=False)

    ax = axes[1]
    ax.scatter(n_true, conf_r, s=46, c=[C["true"] if c == "4SG" else
                                        (C["eb"] if c == "4ST" else C["naive"]) for c in ctrl], zorder=3)
    for i, s in enumerate(sites):
        ax.annotate(s, (n_true[i], conf_r[i]), textcoords="offset points", xytext=(4, 3), fontsize=7)
    ax.set_xscale("log"); ax.set_yscale("log")
    style(ax, "Simulated conflict rate vs TRUE mean crash frequency",
          "true mean crashes / year (log)", "conflicts per million entering veh (log)")
    for lab, col in (("4SG", C["true"]), ("4ST", C["eb"]), ("3ST", C["naive"])):
        ax.scatter([], [], c=col, label=lab, s=40)
    ax.legend(fontsize=8, frameon=False, title="control", title_fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(a.fig_dir, "fig3_frequency_vs_rate.png"), dpi=170, bbox_inches="tight")
    plt.close(fig)

    # ================= FIGURE 4: operational blindness =================
    ba = list(csv.DictReader(open(os.path.join(A, "before_after_paired.csv"))))
    def g(comp, m):
        for r in ba:
            if r["comparison"] == comp and r["metric"] == m:
                return r
        return None

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.6))
    ax = axes[0]
    labels = ["35 s", "60 s\n(Webster)", "100 s", "140 s"]
    comps = ["matchedpair_cycle60_to_cycle35", None,
             "matchedpair_cycle60_to_cycle100", "matchedpair_cycle60_to_cycle140"]
    for metric, col, lab in (("conflicts", C["sim"], "total conflicts"),
                             ("conf_rear_end", C["naive"], "rear-end conflicts"),
                             ("conf_crossing", C["eb"], "crossing conflicts")):
        vals = []
        for c in comps:
            if c is None:
                vals.append(0.0)
            else:
                r = g(c, metric); vals.append(float(r["pct_change"]))
        ax.plot(range(4), vals, "o-", color=col, lw=2, label=lab)
    ax.axhline(0, color=C["grey"], lw=0.9)
    ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=8.5)
    style(ax, "Matched pair: IDENTICAL AADT, control, lanes, speed and phasing\n"
              "=> identical SPF prediction (11.05 crashes/yr) at every point",
          "signal cycle length", "% change in conflicts vs the 60 s baseline")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    trip = [("permissive\n(S07)", 1.0, 1.0, 1.0),
            ("prot/perm\n(S08)", None, None, None),
            ("protected\n(S09)", None, None, None)]
    sim_cross = [1.0, float(g("phasing_triplet_perm_to_protperm", "conf_crossing")["ratio"]),
                 float(g("phasing_triplet_perm_to_protonly", "conf_crossing")["ratio"])]
    sim_tot = [1.0, float(g("phasing_triplet_perm_to_protperm", "conflicts")["ratio"]),
               float(g("phasing_triplet_perm_to_protonly", "conflicts")["ratio"])]
    cmf_ang = [1.0, hsm.CMF_ANGLE["protperm"], hsm.CMF_ANGLE["prot"]]
    cmf_tot = [1.0, hsm.CMF_TOTAL["protperm"], hsm.CMF_TOTAL["prot"]]
    x = np.arange(3); w = 0.2
    ax.bar(x - 1.5 * w, sim_cross, w, color=C["eb"], label="SIM crossing conflicts", zorder=3)
    ax.bar(x - 0.5 * w, cmf_ang, w, color=C["eb"], alpha=0.45, label="published CMF, left-turn crashes", zorder=3)
    ax.bar(x + 0.5 * w, sim_tot, w, color=C["naive"], label="SIM total conflicts", zorder=3)
    ax.bar(x + 1.5 * w, cmf_tot, w, color=C["naive"], alpha=0.45, label="published CMF, total crashes", zorder=3)
    ax.axhline(1.0, color=C["grey"], lw=0.9, ls="--")
    ax.set_xticks(x); ax.set_xticklabels([t[0] for t in trip], fontsize=8.5)
    style(ax, "Simulated conflict ratio vs published CMF\n(matched-AADT phasing triplet, permissive = 1.0)",
          None, "ratio to permissive baseline")
    ax.legend(fontsize=7.6, frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(a.fig_dir, "fig4_operational_blindness_and_cmf.png"), dpi=170,
                bbox_inches="tight")
    plt.close(fig)

    # ================= FIGURE 5: transfer function =================
    tf = list(csv.DictReader(open(os.path.join(A, "transfer_function_per_site.csv"))))
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    xs = np.array([float(r["predictor_value"]) for r in tf])
    yt = np.array([float(r["n_true"]) for r in tf])
    yf = np.array([float(r["fitted"]) for r in tf])
    lo = np.array([float(r["pi95_lo"]) for r in tf])
    hi = np.array([float(r["pi95_hi"]) for r in tf])
    o = np.argsort(xs)
    ax.fill_between(xs[o], lo[o], hi[o], color=C["sim"], alpha=0.15, label="95% prediction interval")
    ax.plot(xs[o], yf[o], "-", color=C["sim"], lw=2, label="fitted transfer function")
    for ctl, col, mk in (("4SG", C["true"], "o"), ("4ST", C["eb"], "s"), ("3ST", C["naive"], "^")):
        m = [i for i, r in enumerate(tf) if r["control"] == ctl]
        ax.scatter(xs[m], yt[m], c=col, marker=mk, s=52, zorder=4, label=ctl)
    for i, r in enumerate(tf):
        ax.annotate(r["site"], (xs[i], yt[i]), textcoords="offset points", xytext=(5, 3), fontsize=7)
    ax.set_xscale("log"); ax.set_yscale("log")
    mod = [r for r in csv.DictReader(open(os.path.join(A, "transfer_function_models.csv")))
           if r["predictor"] == "sim_conf_rate_mev"][0]
    style(ax, "Conflict-to-crash transfer function\nR²=%s  LOO-R²=%s  prediction interval x/÷ %s"
          % (mod["r2"], mod["loo_r2"], mod["pred_interval_multiplicative"]),
          "simulated conflict rate (conflicts per million entering vehicles, log)",
          "TRUE mean crash frequency (crashes/year, log)")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(a.fig_dir, "fig5_transfer_function.png"), dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("\nfigures ->", a.fig_dir)


if __name__ == "__main__":
    main()
