#!/usr/bin/env python3
"""Figures for H1-H6 from the CSVs in data/ (run after the h*.py scripts)."""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import expbase as B          # noqa: E402

import matplotlib            # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

CB = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]


def rd(name):
    p = os.path.join(B.DATA, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        out = []
        for r in csv.DictReader(f):
            d = {}
            for k, v in r.items():
                try:
                    d[k] = float(v) if v not in ("", "None") else None
                except ValueError:
                    d[k] = v
            out.append(d)
        return out


def style(ax, xl, yl, ti):
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.set_title(ti, fontsize=11)
    ax.grid(ls=":", alpha=0.35)


def fig_h1():
    a = rd("h1_analytic.csv")
    s = rd("h1_sim_agg.csv")
    if not a:
        return
    fig, ax = plt.subplots(2, 2, figsize=(13.5, 9))
    for k, C in enumerate([45.0, 60.0, 90.0]):
        g = sorted([r for r in a if r["cycle"] == C], key=lambda r: r["L"])
        ax[0][0].plot([r["L"] for r in g], [r["b_two_way"] for r in g],
                      color=CB[k], lw=1.6, label="C=%.0f s (gT=%.0f)"
                      % (C, g[0]["gT"]))
        n = 1
        while n * B.VPROG * C / 2 <= 800:
            ax[0][0].axvline(n * B.VPROG * C / 2, color=CB[k], ls="--",
                             lw=0.8, alpha=0.6)
            n += 1
    style(ax[0][0], "uniform block spacing L (m)", "analytic two-way band b (s)",
          "H1: two-way band is PERIODIC in L\n(dashed = predicted resonances "
          "L = n*v*C/2, v=13.0 m/s)")
    ax[0][0].legend(fontsize=8)

    g = sorted([r for r in a if r["cycle"] == 90.0], key=lambda r: r["L"])
    ax[0][1].plot([r["L"] for r in g], [r["attainability"] for r in g],
                  color=CB[0], lw=1.6, label="MAXBAND search (exact)")
    ax[0][1].plot([r["L"] for r in g],
                  [r["b_two_way_closedform"] / r["gT"] for r in g],
                  color=CB[1], lw=1.2, ls="--",
                  label="closed form  1 - (n-1)|delta|/(2 gT)")
    style(ax[0][1], "L (m)", "attainability  b / gT", "H1: attainability, C=90 s")
    ax[0][1].legend(fontsize=8)

    sh = rd("h1_peak_sharpness.csv")
    if sh:
        sh = sorted(sh, key=lambda r: r["L"])
        ax[1][0].plot([r["L"] for r in sh], [r["b_two_way"] for r in sh],
                      color=CB[2], lw=1.8)
        ax[1][0].axvline(585, color="k", ls="--", lw=0.9)
        style(ax[1][0], "L (m)", "two-way band b (s)",
              "H1: peak sharpness around the resonance (1 m resolution)")

    if s:
        for k, tag in enumerate(("maxband", "uncoord")):
            g = sorted([r for r in s if r["tag"] == tag and r["C"] == 90.0],
                       key=lambda r: r["L"])
            for j, (f, ls) in enumerate((("zeroEB", "-"), ("zeroWB", "--"))):
                ax[1][1].errorbar([r["L"] for r in g], [r[f] for r in g],
                                  yerr=[r[f + "_hw"] for r in g], ls=ls,
                                  color=CB[k], marker="o", ms=3, lw=1.3,
                                  capsize=2, label="%s %s" % (tag, f[-2:]))
        ax2 = ax[1][1].twinx()
        g = sorted([r for r in s if r["tag"] == "maxband" and r["C"] == 90.0],
                   key=lambda r: r["L"])
        ax2.plot([r["L"] for r in g], [r["b_two_way_analytic"] for r in g],
                 color="#888888", lw=1.0, ls=":")
        ax2.set_ylabel("analytic band (s), dotted grey")
        style(ax[1][1], "L (m)", "measured zero-stop fraction",
              "H1: MEASURED progression tracks the analytic band\n"
              "(mean +/- 95% t CI, 6 CRN replications)")
        ax[1][1].legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h1_resonance.png"), dpi=140)
    plt.close(fig)
    print("h1 figure")


def fig_h2():
    a = rd("h2_agg.csv")
    if not a:
        return
    lv = [r for r in a if r["tag"] in ("maxband", "tlscoord", "sil", "uncoord")]
    lvls = []
    for r in lv:
        if r["lvl"] not in lvls:
            lvls.append(r["lvl"])
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    w = 0.2
    for k, tag in enumerate(("uncoord", "tlscoord", "maxband", "sil")):
        g = [next(r for r in lv if r["lvl"] == L and r["tag"] == tag)
             for L in lvls]
        x = [i + (k - 1.5) * w for i in range(len(lvls))]
        ax[0].bar(x, [r["total_tl"] / 1000.0 for r in g], w, color=CB[k],
                  yerr=[r["total_tl_hw"] / 1000.0 for r in g], capsize=2,
                  label=tag)
        ax[1].bar(x, [r["zeroEB"] for r in g], w, color=CB[k],
                  yerr=[r["zeroEB_hw"] for r in g], capsize=2, label=tag + " EB")
    for a_ in ax[:2]:
        a_.set_xticks(range(len(lvls)))
        a_.set_xticklabels(lvls)
    style(ax[0], "demand level", "total network time loss (10^3 s)",
          "H2: total delay by offset source")
    ax[0].legend(fontsize=8)
    style(ax[1], "demand level", "measured EB zero-stop fraction",
          "H2: progression quality by offset source")
    ax[1].legend(fontsize=8)
    d = [r for r in a if isinstance(r["tag"], str)
         and r["tag"].startswith("DIFF maxband-minus-sil")]
    if d:
        ax[2].bar(range(len(d)), [r["mean_tl"] for r in d], 0.55, color=CB[3],
                  yerr=[100.0 * r["total_tl_hw"] / max(abs(r["total_tl"]), 1e-9)
                        * abs(r["mean_tl"]) / 100.0 for r in d], capsize=3)
        ax[2].set_xticks(range(len(d)))
        ax[2].set_xticklabels([r["lvl"] for r in d])
        ax[2].axhline(0, color="k", lw=0.8)
        style(ax[2], "demand level", "extra total delay of MAXBAND vs SIL (%)",
              "H2: the price of maximising bandwidth")
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h2_band_vs_delay.png"), dpi=140)
    plt.close(fig)
    print("h2 figure")


def fig_h3():
    a = rd("h3_analytic.csv")
    s = rd("h3_agg.csv")
    if not a:
        return
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    for k, L in enumerate(sorted(set(r["L"] for r in a))):
        g = sorted([r for r in a if r["L"] == L], key=lambda r: r["C"])
        ax[0].plot([r["C"] for r in g], [r["b"] for r in g], color=CB[k],
                   lw=1.6, label="L=%.0f m" % L)
        ax[1].plot([r["C"] for r in g], [r["eff"] for r in g], color=CB[k],
                   lw=1.6, label="L=%.0f m" % L)
    style(ax[0], "cycle length C (s)", "analytic two-way band b (s)",
          "H3: absolute band grows with C")
    ax[0].legend(fontsize=8)
    style(ax[1], "cycle length C (s)", "bandwidth efficiency b / C",
          "H3: efficiency does not")
    ax[1].legend(fontsize=8)
    if s:
        for k, L in enumerate(sorted(set(r["L"] for r in s))):
            g = sorted([r for r in s if r["L"] == L], key=lambda r: r["C"])
            ax[2].errorbar([r["C"] for r in g], [r["mean_tl"] for r in g],
                           yerr=[r["mean_tl_hw"] for r in g], color=CB[k],
                           marker="o", ms=4, lw=1.4, capsize=2,
                           label="L=%.0f m" % L)
            bopt = max(g, key=lambda r: r["b"])["C"]
            dopt = min(g, key=lambda r: r["mean_tl"])["C"]
            ax[2].axvline(bopt, color=CB[k], ls="--", lw=1.0)
            ax[2].axvline(dopt, color=CB[k], ls=":", lw=1.6)
        style(ax[2], "cycle length C (s)", "mean network time loss (s/veh)",
              "H3: delay-optimal C (dotted) vs\nbandwidth-optimal C (dashed)")
        ax[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h3_cycle.png"), dpi=140)
    plt.close(fig)
    print("h3 figure")


def fig_h4():
    a = rd("h4_analytic.csv")
    s = rd("h4_agg.csv")
    if not a:
        return
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    g = sorted(a, key=lambda r: r["L"])
    x = range(len(g))
    ax[0].bar([i - 0.2 for i in x], [r["b_leadlead"] for r in g], 0.4,
              color=CB[0], label="lead-lead (symmetric)")
    ax[0].bar([i + 0.2 for i in x], [r["b_best"] for r in g], 0.4,
              color=CB[1], label="best lead-lag assignment")
    ax[0].set_xticks(list(x))
    ax[0].set_xticklabels(["%.0f" % r["L"] for r in g])
    style(ax[0], "block spacing L (m)", "analytic two-way band b (s)",
          "H4: lead-lag recovers band at non-resonant spacings")
    ax[0].legend(fontsize=8)
    if s:
        arms = [r for r in s if r["tag"] in ("leadlead", "best")]
        Ls = sorted(set(r["L"] for r in arms))
        for k, tag in enumerate(("leadlead", "best")):
            gg = [next(r for r in arms if r["L"] == L and r["tag"] == tag)
                  for L in Ls]
            ax[1].errorbar(Ls, [r["zeroEB"] for r in gg],
                           yerr=[r["zeroEB_hw"] for r in gg], color=CB[k],
                           marker="o", ms=4, lw=1.4, capsize=2, label=tag + " EB")
            ax[1].errorbar(Ls, [r["zeroWB"] for r in gg],
                           yerr=[r["zeroWB_hw"] for r in gg], color=CB[k],
                           marker="s", ms=4, lw=1.4, ls="--", capsize=2,
                           label=tag + " WB")
            ax[2].errorbar(Ls, [r["tl_artleft"] for r in gg],
                           yerr=[r["tl_artleft_hw"] for r in gg], color=CB[k],
                           marker="o", ms=4, lw=1.4, capsize=2,
                           label=tag + " arterial left turns")
        style(ax[1], "L (m)", "measured zero-stop fraction",
              "H4: measured progression")
        ax[1].legend(fontsize=7)
        style(ax[2], "L (m)", "mean time loss (s/veh)",
              "H4: what it costs the left turns")
        ax[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h4_leadlag.png"), dpi=140)
    plt.close(fig)
    print("h4 figure")


def fig_h5():
    a = rd("h5_dispersion.csv")
    c = rd("h5_spread_vs_band.csv")
    if not a:
        return
    fit = json.load(open(os.path.join(B.DATA, "h5_robertson_fit.json")))
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    ax[0].plot([r["d_m"] for r in a], [r["sd_tau"] for r in a], "o-",
               color=CB[0], lw=1.6)
    style(ax[0], "distance downstream of the stop line (m)",
          "platoon travel-time spread sigma (s)", "H5: platoon dispersion")
    ax[1].plot([r["cruise_T"] for r in a], [r["inv_F_minus1"] for r in a], "o",
               color=CB[1])
    xr = [0, max(r["cruise_T"] for r in a)]
    ax[1].plot(xr, [fit["alpha_beta"] * x for x in xr], "-", color=CB[1],
               label="fit: alpha*beta = %.4f  (R2=%.3f)"
               % (fit["alpha_beta"], fit["r2_through_origin"]))
    style(ax[1], "cruise travel time T (s)", "1/F - 1",
          "H5: Robertson F = 1/(1 + alpha*beta*T)")
    ax[1].legend(fontsize=8)
    if c:
        ax[2].plot([r["L"] for r in c], [r["b_two_way"] for r in c], "-",
                   color=CB[2], label="analytic two-way band b(L)")
        ax[2].plot([r["L"] for r in c], [r["two_sigma"] for r in c], "-",
                   color=CB[3], label="2 sigma (platoon spread)")
        style(ax[2], "block spacing L (m)", "seconds",
              "H5: where dispersion overwhelms the band")
        ax[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h5_dispersion.png"), dpi=140)
    plt.close(fig)
    print("h5 figure")


def fig_h6():
    a = rd("h6_agg.csv")
    if not a:
        return
    LL = sorted(set(r["L"] for r in a))[0]
    arms = [r for r in a if r["tag"] in ("maxband", "uncoord") and r["L"] == LL]
    ben = [r for r in a if isinstance(r["tag"], str)
           and r["tag"].startswith("BENEFIT") and r["L"] == LL]
    qs = sorted(set(r["thru"] for r in arms))
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    for k, tag in enumerate(("uncoord", "maxband")):
        g = [next(r for r in arms if r["thru"] == q and r["tag"] == tag)
             for q in qs]
        ax[0].errorbar(qs, [r["jam_max_EB"] for r in g],
                       yerr=[r["jam_max_EB_hw"] for r in g], color=CB[k],
                       marker="o", ms=4, lw=1.4, capsize=2, label=tag + " EB")
        ax[1].errorbar(qs, [r["tl_thruE"] for r in g],
                       yerr=[r["tl_thruE_hw"] for r in g], color=CB[k],
                       marker="o", ms=4, lw=1.4, capsize=2, label=tag + " EB")
    ax[0].axhline(arms[0]["link_len"], color="k", ls="--", lw=1.0,
                  label="link storage length")
    style(ax[0], "arterial through demand (veh/h/dir)",
          "max E2 jam length (m)", "H6: queues reach link storage (L=%.0f m)" % LL)
    ax[0].legend(fontsize=8)
    style(ax[1], "arterial through demand (veh/h/dir)",
          "corridor-through time loss (s/veh)", "H6: delay")
    ax[1].legend(fontsize=8)
    g = [r for r in ben if r["tag"].endswith("tl_thruE")]
    g = sorted(g, key=lambda r: r["thru"])
    ax[2].bar([str(int(r["thru"])) for r in g], [r["jam_max_EB"] for r in g],
              0.6, yerr=[r["jam_max_EB_hw"] for r in g], capsize=3, color=CB[4])
    ax[2].axhline(0, color="k", lw=0.9)
    style(ax[2], "arterial through demand (veh/h/dir)",
          "coordination benefit (s/veh, +ve = coordination helps)",
          "H6: the benefit collapses / reverses (L=%.0f m)" % LL)
    fig.tight_layout()
    fig.savefig(os.path.join(B.FIG, "h6_spillback.png"), dpi=140)
    plt.close(fig)
    print("h6 figure")


if __name__ == "__main__":
    for f in (fig_h1, fig_h2, fig_h3, fig_h4, fig_h5, fig_h6):
        try:
            f()
        except Exception as e:              # noqa: BLE001
            import traceback
            print("FIGURE FAILED", f.__name__, e)
            traceback.print_exc()
