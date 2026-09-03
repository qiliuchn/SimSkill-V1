#!/usr/bin/env python3
"""Figures: SOC trajectories, feasibility frontier, energy decomposition."""
import os, sys, json, math, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as MT
import scenario as SC

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RUNS = os.path.join(ROOT, "runs")
OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "outputs"))
RESERVE = 0.20

FG, BG, GRID = "#1b1b1b", "#ffffff", "#d8d8d8"
PAL = ["#3d6fb4", "#c1553b", "#4e9b6b", "#9a6bb0", "#c9a227", "#4aa3b8", "#a05c7b"]


def style(ax):
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors=FG, labelsize=8)


def soc_figure(tags, path):
    n = len(tags)
    fig, axes = plt.subplots(n, 1, figsize=(9.5, 2.7 * n), sharex=True)
    if n == 1:
        axes = [axes]
    for ax, (tag, label) in zip(axes, tags):
        d = os.path.join(RUNS, tag)
        m = MT.run_metrics(d, keep_traces=True)
        cap = m["cfg"]["cap_kwh"] * 1000.0
        for i, (vid, b) in enumerate(sorted(m["energy"]["per_bus"].items(),
                                            key=lambda kv: int(kv[0].split("_")[1]))):
            tr = b["virtual_trace"]
            ax.plot([t / 3600.0 for t, _ in tr], [s / cap for _, s in tr],
                    lw=1.1, color=PAL[i % len(PAL)], label=vid)
        ax.axhline(RESERVE, color="#c1553b", ls="--", lw=1.2)
        ax.axhline(0.0, color=FG, lw=0.8)
        ax.set_ylabel("state of charge", color=FG, fontsize=9)
        ax.set_title(label, color=FG, fontsize=10, loc="left")
        ax.set_ylim(min(-0.15, ax.get_ylim()[0]), 1.05)
        style(ax)
    axes[-1].set_xlabel("simulation time (h)", color=FG, fontsize=9)
    axes[0].legend(ncol=7, fontsize=7, frameon=False, loc="lower left")
    fig.suptitle("Per-bus battery state of charge over the 5.6 h vehicle block\n"
                 "(unclamped: reconstructed from cumulative consumed/regenerated/charged counters)",
                 color=FG, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, dpi=140, facecolor=BG)
    plt.close(fig)


def frontier_figure(csvpath, path):
    import csv as _csv
    rows = list(_csv.DictReader(open(csvpath)))
    caps = sorted({int(r["cap_kwh"]) for r in rows})
    combos = [(0, "skip", "0 (depot-only)"), (1, "skip", "1 (truncation)"),
              (1, "queue", "1 (queueing)"), (2, "skip", "2")]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13.0, 5.2))
    grid = {}
    for r in rows:
        grid[(int(r["cap_kwh"]), int(r["chargers"]), r["policy"])] = r
    for j, (nch, pol, lab) in enumerate(combos):
        for i, cap in enumerate(caps):
            r = grid.get((cap, nch, pol))
            if r is None:
                continue
            nf, ns = int(r["n_seeds_feasible"]), int(r["n_seeds"])
            col = "#4e9b6b" if nf == ns else ("#c9a227" if nf > 0 else "#c1553b")
            ax.add_patch(plt.Rectangle((j - 0.46, i - 0.46), 0.92, 0.92,
                                       facecolor=col, alpha=0.75, edgecolor="white", lw=1.5))
            ax.text(j, i + 0.13, f'{float(r["min_soc_mean"]):.2f}', ha="center", va="center",
                    fontsize=9, color="white", fontweight="bold")
            ax.text(j, i - 0.20, f'+{float(r["mean_dep_dev_s"]):.0f}s / {float(r["missed_departures_mean"]):.1f} miss',
                    ha="center", va="center", fontsize=6.6, color="white")
    ax.set_xlim(-0.6, len(combos) - 0.4); ax.set_ylim(-0.6, len(caps) - 0.4)
    ax.set_xticks(range(len(combos))); ax.set_xticklabels([c[2] for c in combos], fontsize=8)
    ax.set_yticks(range(len(caps))); ax.set_yticklabels([f"{c} kWh" for c in caps], fontsize=8)
    ax.set_xlabel("terminal chargers per terminal", fontsize=9)
    ax.set_ylabel("battery capacity", fontsize=9)
    ax.set_title("Feasibility frontier: cell label = min SOC over fleet (mean of 3 CRN seeds)\n"
                 "second line = mean terminal departure delay / mean missed departures",
                 fontsize=9.5, loc="left")
    ax.grid(False)
    ax.legend(handles=[Patch(facecolor="#4e9b6b", label="feasible (min SOC >= 0.20) in all 3 seeds"),
                       Patch(facecolor="#c9a227", label="feasible in some seeds"),
                       Patch(facecolor="#c1553b", label="infeasible in all seeds")],
              fontsize=7.5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.13), ncol=3)
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    # right panel: min SOC vs capacity
    for j, (nch, pol, lab) in enumerate(combos):
        xs, ys, es = [], [], []
        for cap in caps:
            r = grid.get((cap, nch, pol))
            if r:
                xs.append(cap); ys.append(float(r["min_soc_mean"])); es.append(float(r["min_soc_ci95"]))
        ax2.errorbar(xs, ys, yerr=es, marker=("s" if pol == "queue" else "o"), ms=4, lw=1.5,
                     capsize=3, ls=("--" if pol == "queue" else "-"),
                     color=PAL[j], label=lab, alpha=(0.9 if pol != "queue" else 1.0))
    ax2.axhline(RESERVE, color="#c1553b", ls="--", lw=1.2)
    ax2.text(caps[0], RESERVE + 0.015, "20% reserve", color="#c1553b", fontsize=8)
    ax2.set_xlabel("battery capacity (kWh)", fontsize=9)
    ax2.set_ylabel("minimum state of charge over the fleet", fontsize=9)
    ax2.set_title("Minimum SOC vs capacity (95% CI, 3 CRN seeds)", fontsize=9.5, loc="left")
    ax2.legend(fontsize=8, frameon=False, title="chargers/terminal", title_fontsize=8,
               loc="lower right")
    style(ax2)
    fig.tight_layout()
    fig.savefig(path, dpi=140, facecolor=BG)
    plt.close(fig)


def decomposition_figure(csvpath, path):
    import csv as _csv
    rows = list(_csv.DictReader(open(csvpath)))
    rows = [r for r in rows if r["arm"] in
            ("D_tspoff_aux7000", "D_tspconditional_aux7000",
             "F_rec0.85_stride1", "F_rec0.0_stride1",
             "F_rec0.85_stride2", "F_rec0.0_stride2")]
    fig, ax = plt.subplots(figsize=(10.5, 4.4))
    labels = [r["label"] for r in rows]
    trac = [float(r["traction_gross_kwh"]) for r in rows]
    aux = [float(r["auxiliary_kwh"]) for r in rows]
    reg = [-float(r["regenerated_kwh"]) for r in rows]
    x = range(len(rows))
    ax.bar(x, trac, color=PAL[0], label="gross traction")
    ax.bar(x, aux, bottom=trac, color=PAL[4], label="auxiliary (HVAC etc.)")
    ax.bar(x, reg, color=PAL[2], label="regenerated (credit)")
    for i, r in enumerate(rows):
        ax.plot([i - 0.42, i + 0.42], [float(r["net_energy_kwh"])] * 2, color=FG, lw=2)
        ax.text(i, float(r["net_energy_kwh"]) + 25, f'net {float(r["net_energy_kwh"]):.0f} kWh',
                ha="center", fontsize=8, color=FG)
    ax.axhline(0, color=FG, lw=0.8)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=7.5, rotation=12, ha="right")
    ax.set_ylabel("fleet energy over the service period (kWh)", fontsize=9)
    ax.set_title("Energy decomposition (7-bus fleet, mean of 3 CRN seeds)\n"
                 "auxiliary = constantPowerIntake x time in network, validated by an aux=0 re-run",
                 fontsize=9.5, loc="left")
    ax.legend(fontsize=8, frameon=False)
    style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=140, facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    soc_figure([("A_cap200_ch0_s1", "A. depot-only, 200 kWh (no charging during the block)"),
                ("A_cap120_ch1_s1", "B. 1 terminal charger (session truncation), 120 kWh"),
                ("A_cap80_ch2_s1", "C. 2 terminal chargers, 80 kWh"),
                ("G_cap160_midday_s1", "D. depot-only + mid-day depot recharge, 160 kWh")],
               os.path.join(OUT, "soc_trajectories.png"))
    frontier_figure(os.path.join(OUT, "frontier_table.csv"),
                    os.path.join(OUT, "feasibility_frontier.png"))
    decomposition_figure(os.path.join(OUT, "energy_decomposition.csv"),
                         os.path.join(OUT, "energy_decomposition.png"))
    print("figures written to", OUT)
