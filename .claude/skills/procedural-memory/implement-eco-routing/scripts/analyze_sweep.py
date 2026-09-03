"""Analyse the eco-routing sweeps: tables, significance tests, Pareto plot,
and the explicit monotonicity / rebound test."""
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                        # noqa: E402
from scipy import stats                   # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT              # noqa: E402

SWEEP = os.path.join(WORK, "sweep")
R_SCALE = 1.238073e-03
SEEDS = [0, 1, 2, 3, 4]

# colour-blind-safe, print-safe
C_ECO, C_TT, C_BASE, C_EQ, C_UN = "#0F5EA8", "#C2571A", "#5B6670", "#0F5EA8", "#8A8F98"


def load():
    rows = []
    for f in sorted(glob.glob(os.path.join(SWEEP, "*_summary.json"))):
        with open(f) as fh:
            rows.append(json.load(fh))
    return rows


def paired(a, b):
    """paired (CRN) t-test of b-a over shared seeds -> (mean diff, p)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    if np.allclose(d, 0):
        return 0.0, 1.0
    t, p = stats.ttest_rel(b, a)
    return float(d.mean()), float(p)


def fmt(x, n=1):
    return ("%%.%df" % n) % x


def main():
    rows = load()
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    # ------------------------------------------------ (A) penetration sweep --
    pen_rows = [r for r in rows if r["tag"] == "pen"]
    tt_rows = [r for r in rows if r["tag"] == "tt"]
    pens = sorted({r["penetration"] for r in pen_rows})

    def col(rs, pen, f):
        return [f(r) for s in SEEDS for r in rs
                if r["penetration"] == pen and r["seed"] == s]

    metrics = {
        "netCO2_kg": lambda r: r["net_CO2_kg"],
        "netfuel_kg": lambda r: r["net_fuel_kg"],
        "mean_tt_s": lambda r: r["main"]["mean_dur"],
        "p90_tt_s": lambda r: r["main"]["p90_dur"],
        "bypass_share": lambda r: r["main"]["share_bypass"],
        "hybrid_share": lambda r: r["main"]["share_hybrid"],
        "CO2_per_veh_g": lambda r: r["main"]["CO2_g"],
    }

    out("=" * 100)
    out("(A) PENETRATION SWEEP  (alpha=1, beta=1*R  i.e. lam=1;  5 demand seeds, CRN)")
    out("=" * 100)
    out("%-6s %14s %14s %12s %12s %11s %11s" %
        ("pen", "netCO2 kg", "netfuel kg", "meanTT s", "p90TT s", "bypass", "hybrid"))
    table = {}
    for p in pens:
        table[p] = {k: np.array(col(pen_rows, p, f)) for k, f in metrics.items()}
        t = table[p]
        out("%-6.0f%% %7.1f+-%-5.1f %7.2f+-%-5.2f %6.1f+-%-4.1f %6.1f+-%-4.1f %6.3f%6s %6.3f" %
            (p * 100, t["netCO2_kg"].mean(), t["netCO2_kg"].std(ddof=1),
             t["netfuel_kg"].mean(), t["netfuel_kg"].std(ddof=1),
             t["mean_tt_s"].mean(), t["mean_tt_s"].std(ddof=1),
             t["p90_tt_s"].mean(), t["p90_tt_s"].std(ddof=1),
             t["bypass_share"].mean(), "", t["hybrid_share"].mean()))

    out()
    out("paired (CRN) tests vs 0%% penetration:")
    out("%-6s %22s %22s %22s" % ("pen", "d netCO2 kg (p)", "d meanTT s (p)", "d p90TT s (p)"))
    for p in pens[1:]:
        s = "%-6.0f%%" % (p * 100)
        for k in ("netCO2_kg", "mean_tt_s", "p90_tt_s"):
            d, pv = paired(table[pens[0]][k], table[p][k])
            s += " %14s (p=%.3f)" % (fmt(d, 2), pv)
        out(s)

    # -------------------------------- monotonicity / rebound (adjacent pairs) --
    out()
    out("MONOTONICITY / REBOUND TEST -- adjacent-penetration paired differences in netCO2:")
    reb = []
    for i in range(len(pens) - 1):
        d, pv = paired(table[pens[i]]["netCO2_kg"], table[pens[i + 1]]["netCO2_kg"])
        sig = "SIGNIFICANT" if pv < 0.05 else "n.s."
        arrow = "DOWN" if d < 0 else "UP  "
        out("   %3.0f%% -> %3.0f%% : %+8.2f kg  p=%.4f  %s  %s"
            % (pens[i] * 100, pens[i + 1] * 100, d, pv, arrow, sig))
        reb.append((pens[i], pens[i + 1], d, pv))
    ups = [r for r in reb if r[2] > 0 and r[3] < 0.05]
    out("   => %s" % ("REBOUND: at least one significant INCREASE in network CO2 with rising "
                      "penetration (%s)" % ", ".join("%.0f%%->%.0f%%" % (a * 100, b * 100)
                                                     for a, b, _, _ in ups)
                      if ups else
                      "network CO2 falls monotonically (no significant rebound leg)"))
    # Spearman monotonicity across the whole curve, per seed
    rhos = []
    for si, s in enumerate(SEEDS):
        y = [table[p]["netCO2_kg"][si] for p in pens]
        rhos.append(stats.spearmanr(pens, y).statistic)
    out("   per-seed Spearman rho(penetration, netCO2): %s  (mean %.3f)"
        % (", ".join("%.2f" % r for r in rhos), float(np.mean(rhos))))

    # ------------------------------------------- equipped vs unequipped ------
    out()
    out("=" * 100)
    out("(A2) EQUIPPED vs UNEQUIPPED (same runs, mean over 5 seeds)")
    out("=" * 100)
    out("%-6s %9s %9s %9s | %9s %9s %9s" %
        ("pen", "eq TT", "eq CO2g", "eq byp", "un TT", "un CO2g", "un byp"))
    for p in pens:
        rs = [r for r in pen_rows if r["penetration"] == p]
        def g(grp, k):
            v = [r[grp][k] for r in rs if r[grp]]
            return np.mean(v) if v else float("nan")
        out("%-6.0f%% %9.1f %9.1f %9.3f | %9.1f %9.1f %9.3f" %
            (p * 100, g("equipped", "mean_dur"), g("equipped", "CO2_g"),
             g("equipped", "share_bypass"),
             g("unequipped", "mean_dur"), g("unequipped", "CO2_g"),
             g("unequipped", "share_bypass")))
    mism = sum(r["vtype_mismatches"] for r in rows)
    out("   equipped/unequipped partition cross-check (vehroute vType vs tripinfo vType): "
        "%d mismatches across all %d runs" % (mism, len(rows)))

    # ------------------------------- (B) travel-time-only online control -----
    out()
    out("=" * 100)
    out("(B) CONTROL: online router with lam=0 (pure travel time) -- isolates 'rerouting at all'")
    out("=" * 100)
    out("%-6s %14s %12s %11s | %14s %12s" %
        ("pen", "netCO2 kg(tt)", "meanTT(tt)", "byp(tt)", "netCO2 kg(eco)", "meanTT(eco)"))
    for p in pens:
        if p == 0:
            e = table[p]
            out("%-6.0f%% %14.1f %12.1f %11.3f | %14.1f %12.1f"
                % (0, e["netCO2_kg"].mean(), e["mean_tt_s"].mean(),
                   e["bypass_share"].mean(), e["netCO2_kg"].mean(), e["mean_tt_s"].mean()))
            continue
        c = np.array(col(tt_rows, p, lambda r: r["net_CO2_kg"]))
        ct = np.array(col(tt_rows, p, lambda r: r["main"]["mean_dur"]))
        cb = np.array(col(tt_rows, p, lambda r: r["main"]["share_bypass"]))
        out("%-6.0f%% %14.1f %12.1f %11.3f | %14.1f %12.1f"
            % (p * 100, c.mean(), ct.mean(), cb.mean(),
               table[p]["netCO2_kg"].mean(), table[p]["mean_tt_s"].mean()))
    d, pv = paired(np.array(col(tt_rows, 1.0, lambda r: r["net_CO2_kg"])),
                   table[1.0]["netCO2_kg"])
    out("   eco(lam=1) minus tt-only at 100%% penetration: netCO2 %+.2f kg (p=%.4f)" % (d, pv))

    # --------------------------------------------- (C) alpha/beta sweep ------
    out()
    out("=" * 100)
    out("(C) ALPHA/BETA SWEEP at 100%% penetration  (beta = lam * R, R=1.238e-3 s/mg)")
    out("=" * 100)
    lam_tags = [("tt", 0.0), ("lam0.25", 0.25), ("lam0.5", 0.5), ("pen", 1.0),
                ("lam2", 2.0), ("lam4", 4.0), ("lam8", 8.0), ("lampure", float("inf"))]
    out("%-10s %14s %14s %12s %12s %11s" %
        ("lam", "netCO2 kg", "netfuel kg", "meanTT s", "p90TT s", "bypass"))
    pareto = []
    base = table[0.0]
    out("%-10s %7.1f+-%-5.1f %7.2f+-%-5.2f %6.1f+-%-4.1f %6.1f+-%-4.1f %6.3f"
        % ("0% pen", base["netCO2_kg"].mean(), base["netCO2_kg"].std(ddof=1),
           base["netfuel_kg"].mean(), base["netfuel_kg"].std(ddof=1),
           base["mean_tt_s"].mean(), base["mean_tt_s"].std(ddof=1),
           base["p90_tt_s"].mean(), base["p90_tt_s"].std(ddof=1),
           base["bypass_share"].mean()))
    for tag, lam in lam_tags:
        rs = [r for r in rows if r["tag"] == tag and r["penetration"] == 1.0]
        if not rs:
            continue
        co2 = np.array([r["net_CO2_kg"] for r in rs])
        fu = np.array([r["net_fuel_kg"] for r in rs])
        tt_ = np.array([r["main"]["mean_dur"] for r in rs])
        p90 = np.array([r["main"]["p90_dur"] for r in rs])
        by = np.array([r["main"]["share_bypass"] for r in rs])
        out("%-10s %7.1f+-%-5.1f %7.2f+-%-5.2f %6.1f+-%-4.1f %6.1f+-%-4.1f %6.3f"
            % (("inf" if lam == float("inf") else "%g" % lam),
               co2.mean(), co2.std(ddof=1), fu.mean(), fu.std(ddof=1),
               tt_.mean(), tt_.std(ddof=1), p90.mean(), p90.std(ddof=1), by.mean()))
        pareto.append((lam, co2.mean(), co2.std(ddof=1), tt_.mean(), tt_.std(ddof=1)))

    # ------------------------------------------------------------- plots -----
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 150})

    fig, ax = plt.subplots(1, 3, figsize=(12, 3.6))
    x = [p * 100 for p in pens]
    for a, key, lab in ((ax[0], "netCO2_kg", "network CO$_2$ (kg)"),
                        (ax[1], "mean_tt_s", "main-OD mean travel time (s)"),
                        (ax[2], "bypass_share", "bypass share of main OD")):
        m = [table[p][key].mean() for p in pens]
        e = [table[p][key].std(ddof=1) / np.sqrt(len(SEEDS)) for p in pens]
        a.errorbar(x, m, yerr=e, marker="o", color=C_ECO, capsize=3, lw=1.6, label="eco (lam=1)")
        if key != "bypass_share":
            ck = (lambda r: r["net_CO2_kg"]) if key == "netCO2_kg" else (lambda r: r["main"]["mean_dur"])
        else:
            ck = lambda r: r["main"]["share_bypass"]
        mt = [table[0.0][key].mean()] + [np.mean(col(tt_rows, p, ck)) for p in pens[1:]]
        a.plot(x, mt, marker="s", ls="--", color=C_TT, lw=1.3, label="travel-time only (lam=0)")
        a.set_xlabel("eco-router market penetration (%)")
        a.set_ylabel(lab)
        a.grid(alpha=.25, lw=.5)
    ax[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Eco-router market penetration (5 demand seeds, CRN; error bars = 1 s.e.)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "penetration_sweep.png"), bbox_inches="tight")

    fig, a = plt.subplots(figsize=(5.2, 4.2))
    offs = [(6, -12), (6, -12), (6, -12), (8, 2), (8, 2), (8, 2), (8, 2), (-6, 10)]
    for i, (lam, c, ce, t, te) in enumerate(pareto):
        a.errorbar(t, c, xerr=te / np.sqrt(5), yerr=ce / np.sqrt(5), marker="o",
                   color=C_ECO, capsize=2, ms=5, lw=1)
        a.annotate("$\\lambda$=%s" % ("$\\infty$" if lam == float("inf") else "%g" % lam),
                   (t, c), textcoords="offset points",
                   xytext=offs[i % len(offs)], fontsize=8, color=C_ECO,
                   ha="right" if offs[i % len(offs)][0] < 0 else "left")
    ps = sorted(pareto, key=lambda z: z[3])
    a.plot([p[3] for p in ps], [p[1] for p in ps], color=C_ECO, lw=1, alpha=.5)
    a.errorbar(base["mean_tt_s"].mean(), base["netCO2_kg"].mean(),
               xerr=base["mean_tt_s"].std(ddof=1) / np.sqrt(5),
               yerr=base["netCO2_kg"].std(ddof=1) / np.sqrt(5),
               marker="D", color=C_BASE, ms=7, capsize=2, lw=1)
    a.annotate("travel-time UE\n(0% penetration,\nno eco router)",
               (base["mean_tt_s"].mean(), base["netCO2_kg"].mean()),
               textcoords="offset points", xytext=(-10, -34), fontsize=8, color=C_BASE,
               ha="center")
    a.set_xlabel("main-OD mean travel time (s)")
    a.set_ylabel("network total CO$_2$ (kg)")
    a.set_title("CO$_2$ vs travel time across the $\\alpha/\\beta$ sweep\n"
                "(100% penetration, $\\beta=\\lambda R$, 5 seeds)\n"
                "the 'frontier' is degenerate: both objectives worsen with $\\lambda$",
                fontsize=9.5)
    a.grid(alpha=.25, lw=.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "pareto_co2_vs_traveltime.png"), bbox_inches="tight")

    fig, a = plt.subplots(figsize=(5.6, 3.8))
    eq = [np.mean([r["equipped"]["mean_dur"] for r in pen_rows
                   if r["penetration"] == p and r["equipped"]]) for p in pens]
    un = [np.mean([r["unequipped"]["mean_dur"] for r in pen_rows
                   if r["penetration"] == p and r["unequipped"]]) for p in pens]
    a.plot(x, eq, marker="o", color=C_EQ, label="equipped (eco-routed)")
    a.plot(x, un, marker="s", color=C_UN, label="unequipped")
    a.set_xlabel("eco-router market penetration (%)")
    a.set_ylabel("mean travel time (s)")
    a.set_title("Private outcome by equipage class", fontsize=10)
    a.legend(frameon=False, fontsize=8)
    a.grid(alpha=.25, lw=.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "equipped_vs_unequipped.png"), bbox_inches="tight")

    # ------------------------------------------------------------ csv/txt ----
    import csv
    with open(os.path.join(OUT, "sweep_results.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "penetration", "alpha", "beta", "lam", "seed", "net_CO2_kg",
                    "net_fuel_kg", "net_NOx_kg", "main_mean_tt", "main_p90_tt",
                    "main_CO2_g", "share_bypass", "share_arterial", "share_hybrid",
                    "eq_n", "eq_mean_tt", "eq_CO2_g", "eq_share_bypass",
                    "un_n", "un_mean_tt", "un_CO2_g", "un_share_bypass",
                    "reroute_calls", "route_changes", "vtype_mismatches"])
        for r in rows:
            lam = "inf" if r["alpha"] == 0 else "%g" % (r["beta"] / R_SCALE)
            e, u, m = r["equipped"], r["unequipped"], r["main"]
            w.writerow([r["tag"], r["penetration"], r["alpha"], r["beta"], lam, r["seed"],
                        r["net_CO2_kg"], r["net_fuel_kg"], r["net_NOx_kg"],
                        m["mean_dur"], m["p90_dur"], m["CO2_g"], m["share_bypass"],
                        m["share_arterial"], m["share_hybrid"],
                        e["n"] if e else 0, e["mean_dur"] if e else "", e["CO2_g"] if e else "",
                        e["share_bypass"] if e else "",
                        u["n"] if u else 0, u["mean_dur"] if u else "", u["CO2_g"] if u else "",
                        u["share_bypass"] if u else "",
                        r["reroute_calls"], r["route_changes"], r["vtype_mismatches"]])
    with open(os.path.join(OUT, "sweep_analysis.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
