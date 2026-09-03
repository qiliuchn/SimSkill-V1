#!/usr/bin/env python3
"""Build a scenario comparison table + summary figure from a per-edge noise CSV
(as produced by sample_noise.py, run once per scenario with the same --out-csv),
and verify the volume-law / heavy-vehicle-penalty / energy-vs-arithmetic-averaging
claims directly from the raw data.

Usage:
    python analyze_and_plot.py --csv per_edge_noise.csv --outdir outputs/ \
        --scenario low:300 --scenario double:600 --scenario quad:1200 --scenario mixed:600

Each --scenario is "name:total_veh_per_h". The first three (in the order given)
are treated as the car-only volume sweep for the doubling-law comparison; any
scenario beyond the first three is compared against the sweep level with the
same total volume for the heavy-vehicle-penalty check.
"""
import csv, math, os, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def eavg(vals):
    return 10 * math.log10(sum(10 ** (v / 10) for v in vals) / len(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--scenario", action="append", required=True, help="name:total_veh_per_h")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    scen = [s.split(":")[0] for s in args.scenario]
    total = {s.split(":")[0]: int(s.split(":")[1]) for s in args.scenario}
    label = {s: f"{total[s]}/h" for s in scen}

    rows = list(csv.DictReader(open(args.csv)))

    leq_active, arith = {}, {}
    for s in scen:
        sr = [r for r in rows if r["scenario"] == s]
        leq_active[s] = {r["edge"]: float(r["leq_active_dBA"]) for r in sr}
        arith[s] = {r["edge"]: float(r["arith_mean_active_dBA"]) for r in sr}

    cor = {s: eavg(list(leq_active[s].values())) for s in scen}
    cor_arith = {s: sum(arith[s].values()) / len(arith[s]) for s in scen}

    with open(os.path.join(args.outdir, "scenario_comparison.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "total_veh_per_h", "corridor_Leq_dBA_energy",
                    "corridor_naive_arith_mean_dBA", "energy_minus_arith_dB"])
        for s in scen:
            w.writerow([s, total[s], round(cor[s], 2), round(cor_arith[s], 2),
                        round(cor[s] - cor_arith[s], 2)])

    lines = []
    sweep = scen[:3]
    lines.append("=== volume law (car-only, energy-averaged corridor Leq) ===")
    for a, b in zip(sweep, sweep[1:]):
        d = cor[b] - cor[a]
        lines.append(f"  {a} ({total[a]}/h) = {cor[a]:.2f} dB(A)  ->  {b} ({total[b]}/h) = "
                      f"{cor[b]:.2f} dB(A)   (+{d:.2f} dB per doubling)")
    lines.append(f"  full range {sweep[0]}->{sweep[-1]}: +{cor[sweep[-1]]-cor[sweep[0]]:.2f} dB "
                 f"(theory 10*log10({total[sweep[-1]]}/{total[sweep[0]]})="
                 f"{10*math.log10(total[sweep[-1]]/total[sweep[0]]):.2f})")

    lines.append("")
    lines.append("=== heavy-vehicle penalty (vs same-total-volume car-only sweep level) ===")
    for s in scen[3:]:
        same_vol = [x for x in sweep if total[x] == total[s]]
        if same_vol:
            base = same_vol[0]
            pen = cor[s] - cor[base]
            lines.append(f"  {s} ({total[s]}/h) = {cor[s]:.2f} dB(A)  vs car-only {base} "
                         f"({total[base]}/h) = {cor[base]:.2f} dB(A)   penalty = {pen:+.2f} dB")

    lines.append("")
    lines.append("=== why energy averaging is required (arith mean mis-states the level) ===")
    worst = max(rows, key=lambda r: float(r["energy_minus_arith_dB"]))
    lines.append(f"  worst single edge: scenario={worst['scenario']} edge={worst['edge']}: "
                 f"energy Leq={worst['leq_active_dBA']} dB vs naive arithmetic mean="
                 f"{worst['arith_mean_active_dBA']} dB -> naive UNDERSTATES by "
                 f"{worst['energy_minus_arith_dB']} dB")
    for s in scen:
        lines.append(f"  corridor {s:10s}: energy Leq={cor[s]:.2f} dB  vs  naive arith mean="
                     f"{cor_arith[s]:.2f} dB  (gap {cor[s]-cor_arith[s]:+.2f} dB)")
    lines.append("  Jensen: 10*log10(mean(10^(L/10))) >= mean(L); the arithmetic dB mean is always "
                 "<= the true energy Leq, understating acoustic exposure more the larger the "
                 "moment-to-moment fluctuation.")
    print("\n".join(lines))
    open(os.path.join(args.outdir, "verification.txt"), "w").write("\n".join(lines) + "\n")

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    x = [total[s] for s in sweep]
    y = [cor[s] for s in sweep]
    ax[0].plot(x, y, "o-", color="#1f77b4", lw=2, ms=9, label="measured corridor Leq")
    yt = [cor[sweep[0]] + 10 * math.log10(v / total[sweep[0]]) for v in x]
    ax[0].plot(x, yt, "k--", alpha=0.6, label="10*log10(V) law (+3 dB/doubling)")
    for s in scen[3:]:
        ax[0].scatter([total[s]], [cor[s]], color="#d62728", s=110, zorder=5, label=s)
    for s in scen:
        ax[0].annotate(f"{cor[s]:.1f}", (total[s], cor[s]), textcoords="offset points",
                       xytext=(6, 6), fontsize=9)
    ax[0].set_xscale("log", base=2)
    ax[0].set_xticks(x); ax[0].set_xticklabels([str(v) for v in x])
    ax[0].set_xlabel("insertion rate (veh/h, log2)"); ax[0].set_ylabel("corridor Leq  dB(A)")
    ax[0].set_title("Noise vs volume: ~3 dB per doubling (sub-linear)")
    ax[0].grid(alpha=0.3); ax[0].legend(fontsize=8)

    xi = np.arange(len(scen)); wbar = 0.36
    ax[1].bar(xi - wbar / 2, [cor[s] for s in scen], wbar, label="energy Leq (correct)", color="#2ca02c")
    ax[1].bar(xi + wbar / 2, [cor_arith[s] for s in scen], wbar, label="naive arithmetic mean", color="#ff7f0e")
    ax[1].set_xticks(xi); ax[1].set_xticklabels([label[s] for s in scen], rotation=15, fontsize=8)
    ax[1].set_ylabel("corridor level  dB(A)")
    ax[1].set_title("Energy vs arithmetic dB averaging")
    ax[1].grid(alpha=0.3, axis="y"); ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "noise_findings_summary.png"), dpi=130)
    print("\nwrote scenario_comparison.csv, verification.txt, noise_findings_summary.png")


if __name__ == "__main__":
    main()
