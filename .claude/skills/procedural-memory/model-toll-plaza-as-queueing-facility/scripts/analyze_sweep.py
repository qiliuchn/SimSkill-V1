#!/usr/bin/env python3
"""
STEP 3/4 analysis: aggregate the rho sweep over seeds (mean +/- 95% t CI), compare against
closed-form M/M/c, M/D/c, Allen-Cunneen M/G/c and c-independent-M/M/1 predictions, check
Little's Law internally, and draw the delay-vs-rho and per-booth-utilisation figures.
"""
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plaza_lib as P

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(EP, "outputs")
C = 6

# validated categorical palette (dataviz skill: all six checks PASS, light surface #fcfcfb)
PAL = ["#3b6fd4", "#c85a1e", "#6b5bd2", "#2a9d6f", "#b5468f", "#8a6a00"]
INK, INK2, GRID = "#22201d", "#5b5651", "#dedbd5"


def style(ax):
    ax.set_facecolor("#fcfcfb")
    ax.grid(True, color=GRID, lw=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)


def main():
    D = json.load(open(os.path.join(OUT, "step3_sweep_raw.json")))
    rows = D["rows"]
    Seff, mu_eff = D["Seff"], D["mu_eff"]
    mech = json.load(open(os.path.join(OUT, "step2_mechanism_verification.json")))
    exp8 = [x for x in mech if x["variant"] == "exp8"][0]
    S_raw = exp8["realized_service_mean_s"]                 # 8.165 s: the pure booth service
    cs2_eff = exp8["CV_departure_headway"] ** 2             # CV^2 of the EFFECTIVE service time

    table = []
    for arm in ("random", "shortest_queue", "shortest_queue_late"):
        for rho in D["rhos"]:
            R = [r for r in rows if r["arm"] == arm and r["rho_nominal"] == rho]
            if not R:
                continue
            lam = np.mean([r["lam_vph"] for r in R]) / 3600.0
            rho_meas = lam / (C * mu_eff)
            wq_m, wq_h = P.mean_ci([r["Wq_mean"] for r in R])
            p95_m, p95_h = P.mean_ci([r["Wq_p95"] for r in R])
            lq_m, lq_h = P.mean_ci([r["Lq_curve"] for r in R])
            cvT_m, cvT_h = P.mean_ci([r["booth_throughput_CV"] for r in R])
            cvU_m, _ = P.mean_ci([r["booth_util_CV"] for r in R])
            lit_m, _ = P.mean_ci([r["littles_rel_err_pct"] for r in R])
            jam_m, _ = P.mean_ci([r["max_jam_app_m"] for r in R])
            jaml_m, _ = P.mean_ci([r["max_jam_lock_m"] for r in R])
            e3L, _ = P.mean_ci([r["e3_L_within"] for r in R])
            e3LL, _ = P.mean_ci([r["e3_littles_L"] for r in R])
            tel = int(sum(r["teleports"] for r in R))

            wq_mmc, lq_mmc = P.mmc(C, lam, mu_eff)
            wq_mdc, lq_mdc = P.mdc_cosmetatos(C, lam, mu_eff)
            wq_ac, lq_ac = P.allen_cunneen(C, lam, mu_eff, 1.0, cs2_eff)
            wq_c1, lq_c1 = P.c_mm1(C, lam, mu_eff)
            wq_g1, lq_g1 = P.c_mg1(C, lam, Seff, cs2_eff)
            wq_naive, _ = P.mmc(C, lam, 1.0 / S_raw)        # textbook mu = 1/E[S], no floor

            table.append(dict(
                arm=arm, rho_nominal=rho, rho_measured=rho_meas, lam_vph=lam * 3600.0,
                n_per_seed=int(np.mean([r["n"] for r in R])),
                Wq_sim=wq_m, Wq_ci=wq_h, Wq_p95_sim=p95_m, Wq_p95_ci=p95_h,
                Lq_sim=lq_m, Lq_ci=lq_h,
                Wq_MMc=wq_mmc, Wq_MDc=wq_mdc, Wq_AllenCunneen=wq_ac, Wq_cMM1=wq_c1,
                Wq_cMG1=wq_g1, Lq_cMG1=lq_g1,
                Wq_MMc_naive_no_floor=wq_naive,
                Lq_MMc=lq_mmc, Lq_MDc=lq_mdc, Lq_AC=lq_ac, Lq_cMM1=lq_c1,
                booth_throughput_CV=cvT_m, booth_throughput_CV_ci=cvT_h,
                booth_util_CV=cvU_m,
                littles_rel_err_pct=lit_m,
                e3_L_within=e3L, e3_littles_L=e3LL,
                max_jam_app_m=jam_m, max_jam_lock_m=jaml_m, teleports=tel,
                ratio_sim_over_MMc=wq_m / wq_mmc if wq_mmc else float("nan"),
                ratio_sim_over_cMM1=wq_m / wq_c1 if wq_c1 else float("nan"),
                ratio_sim_over_AC=wq_m / wq_ac if wq_ac else float("nan"),
                ratio_sim_over_cMG1=wq_m / wq_g1 if wq_g1 else float("nan"),
                Lq_detector_counts=float(np.mean([r["Lq_detector_counts"] for r in R])),
                e3_littles_rel_err_pct=float(np.mean([r["e3_littles_rel_err_pct"] for r in R])),
                Wq_frac_negative=float(np.mean([r["Wq_frac_negative"] for r in R])),
            ))

    json.dump(dict(Seff=Seff, S_raw=S_raw, cs2_eff=cs2_eff, table=table),
              open(os.path.join(OUT, "step3_results_table.json"), "w"), indent=1)

    # ---- CSV ----
    cols = ["arm", "rho_nominal", "rho_measured", "lam_vph", "n_per_seed",
            "Wq_sim", "Wq_ci", "Wq_p95_sim", "Wq_p95_ci", "Lq_sim", "Lq_ci",
            "Wq_MMc", "Wq_MDc", "Wq_AllenCunneen", "Wq_cMM1", "Wq_cMG1",
            "Wq_MMc_naive_no_floor",
            "Lq_MMc", "Lq_MDc", "Lq_AC", "Lq_cMM1", "Lq_cMG1", "Lq_detector_counts",
            "booth_throughput_CV", "booth_util_CV", "littles_rel_err_pct",
            "e3_L_within", "e3_littles_L", "max_jam_app_m", "max_jam_lock_m", "teleports",
            "ratio_sim_over_MMc", "ratio_sim_over_cMM1", "ratio_sim_over_AC",
            "ratio_sim_over_cMG1", "e3_littles_rel_err_pct", "Wq_frac_negative"]
    with open(os.path.join(OUT, "step3_results_table.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for r in table:
            f.write(",".join(("%.4f" % r[c] if isinstance(r[c], float) else str(r[c])) for c in cols) + "\n")

    for r in table:
        print("%-19s rho=%.3f  Wq_sim=%7.2f+-%5.2f p95=%7.1f | MMc=%6.2f MDc=%6.2f AC=%6.2f "
              "cMM1=%7.2f cMG1=%7.2f | /AC=%5.2f /cMG1=%4.2f  boothCV=%.3f e3Little=%+.2f%%"
              % (r["arm"], r["rho_measured"], r["Wq_sim"], r["Wq_ci"], r["Wq_p95_sim"],
                 r["Wq_MMc"], r["Wq_MDc"], r["Wq_AllenCunneen"], r["Wq_cMM1"], r["Wq_cMG1"],
                 r["ratio_sim_over_AC"], r["ratio_sim_over_cMG1"],
                 r["booth_throughput_CV"], r["e3_littles_rel_err_pct"]))

    # ---------------- FIGURE 1: delay vs rho ---------------- #
    # Theory curves form an ORDERED family (M/D/c < M/G/c < M/M/c < c.M/G/1 < c.M/M/1), so
    # they get a sequential blue ramp + distinct dashes + direct end labels. The three
    # SIMULATION arms are true categories and get the validated categorical hues.
    RAMP = ["#a8c2ee", "#7ba0e4", "#4d7bd8", "#2f57a8", "#1c3468"]
    SIM = {"random": "#b5468f", "shortest_queue": "#2a9d6f", "shortest_queue_late": "#c85a1e"}
    fig, ax = plt.subplots(figsize=(10.2, 6.4), dpi=170)
    fig.patch.set_facecolor("#fcfcfb")
    style(ax)
    grid = np.linspace(0.25, 0.965, 200)
    lamg = grid * C * mu_eff
    curves = [
        ("M/D/c (Cosmetatos)", [P.mdc_cosmetatos(C, l, mu_eff)[0] for l in lamg], RAMP[0], (0, (6, 3))),
        ("M/G/c Allen-Cunneen\n$C_s^2$=%.2f" % cs2_eff,
         [P.allen_cunneen(C, l, mu_eff, 1.0, cs2_eff)[0] for l in lamg], RAMP[1], (0, (1, 2))),
        ("M/M/c", [P.mmc(C, l, mu_eff)[0] for l in lamg], RAMP[2], (0, (1, 0))),
        ("6x M/G/1 (P-K)", [P.c_mg1(C, l, Seff, cs2_eff)[0] for l in lamg], RAMP[3], (0, (5, 1, 1, 1))),
        ("6x M/M/1", [P.c_mm1(C, l, mu_eff)[0] for l in lamg], RAMP[4], (0, (3, 1.5))),
    ]
    for lab, y, col, dash in curves:
        ax.plot(grid, y, lw=2.2, color=col, dashes=dash[1], label=lab)
        # SELECTIVE direct labels: only the two well-separated upper curves; the lower
        # three bunch together at the right edge and would collide, so the legend carries them.
        if lab.startswith("6x"):
            ax.annotate(lab, xy=(grid[-1], y[-1]), xytext=(5, 0), textcoords="offset points",
                        color=col, fontsize=9, va="center", ha="left", fontweight="medium")
    for arm, mk, lab in (("random", "o", "SUMO: random booth choice"),
                         ("shortest_queue", "s", "SUMO: join-shortest-queue, decide 600 m out"),
                         ("shortest_queue_late", "^", "SUMO: join-shortest-queue, decide 1150 m out")):
        col = SIM[arm]
        T = [r for r in table if r["arm"] == arm]
        ax.errorbar([r["rho_measured"] for r in T], [r["Wq_sim"] for r in T],
                    yerr=[r["Wq_ci"] for r in T], fmt=mk, ms=8.5, mfc=col, mec="#fcfcfb",
                    mew=1.7, ecolor=col, elinewidth=1.7, capsize=4, ls="none",
                    label=lab, zorder=5)
    ax.set_yscale("log")
    ax.set_xlim(0.25, 1.06)
    ax.set_xticks([0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    ax.set_xlabel("plaza utilisation  $\\rho = \\lambda\\,/\\,(c\\,\\mu_{eff})$", color=INK, fontsize=11)
    ax.set_ylabel("mean queue delay $W_q$  (s, log scale)", color=INK, fontsize=11)
    ax.set_title("Toll-plaza queue delay: SUMO vs. closed-form queueing theory",
                 color=INK, fontsize=13, loc="left", pad=16)
    ax.text(0, 1.015, "6 booths, exponential 8 s service; $\\mu_{eff}$=1/%.2f s measured from "
            "saturated departure headway; 5 seeds/point, 95%% CI" % Seff,
            transform=ax.transAxes, color=INK2, fontsize=9.5)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left", ncol=1)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig1_delay_vs_rho.png"), facecolor="#fcfcfb")
    print("wrote fig1")

    # ---------------- FIGURE 3: per-booth balance before/after ---------------- #
    # Busy fraction is nearly CONSERVED across assignment policies (the same total work has
    # to be done by the same servers), so utilisation alone is a weak diagnostic; the panel
    # that actually shows the imbalance is per-booth mean queue delay.
    hi = 0.80
    SIMC = {"random": "#b5468f", "shortest_queue": "#2a9d6f"}
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.9), dpi=170)
    fig.patch.set_facecolor("#fcfcfb")
    w = 0.38
    stats = {}
    for panel, (ax, key, ylab) in enumerate(
            ((axes[0], "per_booth_util", "booth busy fraction (service time / window)"),
             (axes[1], "per_booth_Wq", "per-booth mean queue delay $W_q$ (s)"))):
        style(ax)
        for j, arm in enumerate(("random", "shortest_queue")):
            R = [r for r in D["rows"] if r["arm"] == arm and r["rho_nominal"] == hi]
            U = np.array([r[key] for r in R])
            m, sd = U.mean(0), U.std(0, ddof=1)
            cv = float(m.std(ddof=0) / m.mean())
            stats[(key, arm)] = (m.tolist(), cv)
            ax.bar(np.arange(C) + (j - 0.5) * (w + 0.02), m, yerr=sd, width=w,
                   color=SIMC[arm], capsize=3, error_kw=dict(ecolor=INK2, elinewidth=1.1),
                   label="%s  (across-booth CV %.3f)" %
                         ("random booth choice" if arm == "random" else "join-shortest-queue", cv))
        ax.set_xticks(range(C))
        ax.set_xticklabels(["booth %d" % b for b in range(C)], fontsize=9)
        ax.set_ylabel(ylab, color=INK, fontsize=10)
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="upper left")
        ax.set_ylim(0, ax.get_ylim()[1] * 1.32)
    axes[0].set_title("server utilisation is conserved", color=INK, fontsize=11, loc="left")
    axes[1].set_title("queue delay is where the imbalance lives", color=INK, fontsize=11, loc="left")
    fig.suptitle("Per-booth balance at $\\rho$=%.2f, before vs. after the TraCI shortest-queue "
                 "assigner (5 seeds, error bars = SD across seeds)" % hi,
                 color=INK, fontsize=12, x=0.008, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(OUT, "fig3_booth_utilisation.png"), facecolor="#fcfcfb")
    json.dump({str(k): v for k, v in stats.items()},
              open(os.path.join(OUT, "fig3_booth_balance_values.json"), "w"), indent=1)
    print("wrote fig3")

    # ---- how much of the random->M/G/c gap does shortest-queue close? ----
    print("\n-- gap closure toward the single-queue (Allen-Cunneen M/G/c) ideal --")
    gc = []
    for rho in D["rhos"]:
        r0 = [r for r in table if r["arm"] == "random" and r["rho_nominal"] == rho][0]
        for arm in ("shortest_queue", "shortest_queue_late"):
            r1 = [r for r in table if r["arm"] == arm and r["rho_nominal"] == rho][0]
            denom = r0["Wq_sim"] - r0["Wq_AllenCunneen"]
            frac = (r0["Wq_sim"] - r1["Wq_sim"]) / denom if denom > 0 else float("nan")
            gc.append(dict(rho=rho, arm=arm, closed_frac=frac,
                           Wq_random=r0["Wq_sim"], Wq_arm=r1["Wq_sim"],
                           Wq_AC=r0["Wq_AllenCunneen"],
                           residual_over_AC=r1["Wq_sim"] / r0["Wq_AllenCunneen"]))
            print("  rho=%.3f %-20s closes %5.1f%% of the gap; residual %.2fx Allen-Cunneen"
                  % (rho, arm, 100 * frac, r1["Wq_sim"] / r0["Wq_AllenCunneen"]))
    json.dump(gc, open(os.path.join(OUT, "step4_gap_closure.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
