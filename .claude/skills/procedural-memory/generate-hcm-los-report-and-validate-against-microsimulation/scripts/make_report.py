#!/usr/bin/env python3
"""
Build the comparison tables, LOS-agreement counts and plots from the analysed
sweep, plus a couple of example standard engineering LOS reports.
"""
import os, sys, json, math, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import hcm_lib as H
import los_report as LR

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", "runs"))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "outputs"))
PLOTS = os.path.join(OUT, "plots")
os.makedirs(PLOTS, exist_ok=True)
CFG = json.load(open(os.path.join(BASE, "sweep_config.json")))
RECS = json.load(open(os.path.join(OUT, "sweep_results.json")))
XS = CFG["XS"]

# validated categorical slots 1-3 (dataviz reference palette, light mode)
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#dedcd5"
LOS_BOUNDS = [10, 20, 35, 55, 80]


def sel(**kw):
    return [r for r in RECS if all(r[k] == v for k, v in kw.items())]


def avg(rs, k):
    v = [r[k] for r in rs if isinstance(r[k], (int, float)) and r[k] == r[k]]
    return sum(v) / len(v) if v else float("nan")


def curve(field, **kw):
    xs, ys = [], []
    for X in XS:
        rs = sel(X_nominal=X, **kw)
        if rs:
            xs.append(avg(rs, "X"))
            ys.append(avg(rs, field))
    return xs, ys


def style(ax, xlabel, ylabel, los_bands=False):
    ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    ax.grid(True, color=GRID, lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8, length=3)
    if los_bands:
        for b, letter in zip(LOS_BOUNDS, "ABCDE"):
            ax.axhline(b, color=GRID, lw=0.8, ls=":", zorder=0)
            ax.annotate(letter + "|" + "BCDEF"[LOS_BOUNDS.index(b)], (0.995, b),
                        xycoords=("axes fraction", "data"), va="center", ha="right",
                        fontsize=6, color=INK2)


def endlabel(ax, xs, ys, text, color):
    if xs:
        ax.annotate(text, (xs[-1], ys[-1]), textcoords="offset points",
                    xytext=(4, 0), fontsize=7.5, color=color, va="center")


# ---------------------------------------------------------------- figure 1 ---
def fig_hcm_vs_sim():
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.6), sharex=True)
    for i, lg in enumerate(("L", "TR")):
        for j, ctrl in enumerate(("pretimed", "actuated")):
            ax = axes[i][j]
            k = dict(arrivals="poisson", control=ctrl, lane_group=lg,
                     period="T1.0h_full")
            for field, col, lab in ((("delay"), C1, "HCM Ch.19 predicted"),
                                    ("sim_control_delay", C2, "Simulated (250 m segment)"),
                                    ("sim_delay_wholetrip", C3, "Simulated (whole trip)")):
                xs, ys = curve(field, **k)
                ax.plot(xs, ys, lw=2, color=col, marker="o", ms=4,
                        label=lab, zorder=3)
                endlabel(ax, xs, ys, f"{ys[-1]:.0f}", col)
            ax.set_title(f"{'Exclusive left' if lg=='L' else 'Through+right'}  -  {ctrl}",
                         fontsize=10, color=INK, loc="left")
            style(ax, "degree of saturation v/c" if i else "",
                  "control delay (s/veh)" if j == 0 else "", los_bands=True)
            ax.set_ylim(0, 620)
    axes[0][0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle("HCM 6th Ed. Ch.19 control delay vs SUMO microsimulation  "
                 "(Poisson arrivals, T = 1 h, measured s and lost time)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(os.path.join(PLOTS, "hcm_vs_sim_delay.png"), dpi=150,
                facecolor="#fcfcfb")
    plt.close(fig)


# ---------------------------------------------------------------- figure 2 ---
def fig_arrival_process():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    for j, lg in enumerate(("L", "TR")):
        ax = axes[j]
        k = dict(control="pretimed", lane_group=lg, period="T1.0h_full")
        xs, ys = curve("delay", arrivals="poisson", **k)
        ax.plot(xs, ys, lw=2, color=C1, marker="o", ms=4, label="HCM d1+d2 (total)")
        endlabel(ax, xs, ys, f"{ys[-1]:.0f}", C1)
        xs, ys = curve("sim_control_delay", arrivals="poisson", **k)
        ax.plot(xs, ys, lw=2, color=C2, marker="o", ms=4, label="Simulated - Poisson arrivals")
        endlabel(ax, xs, ys, f"{ys[-1]:.0f}", C2)
        xs, ys = curve("sim_control_delay", arrivals="uniform", **k)
        ax.plot(xs, ys, lw=2, color=C3, marker="o", ms=4, label="Simulated - uniform arrivals")
        endlabel(ax, xs, ys, f"{ys[-1]:.0f}", C3)
        xs, ys = curve("d1", arrivals="poisson", **k)
        ax.plot(xs, ys, lw=1.4, color=INK2, ls="--", label="HCM d1 only (reference)")
        ax.set_title(f"{'Exclusive left' if lg=='L' else 'Through+right'} lane group",
                     fontsize=10, color=INK, loc="left")
        style(ax, "degree of saturation v/c", "control delay (s/veh)" if j == 0 else "")
        ax.set_ylim(0, 420)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle("Why the arrival process decides whether HCM's incremental delay d2 is real",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(PLOTS, "arrival_process_effect.png"), dpi=150,
                facecolor="#fcfcfb")
    plt.close(fig)


# ---------------------------------------------------------------- figure 3 ---
def fig_delay_definitions():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    for j, lg in enumerate(("L", "TR")):
        ax = axes[j]
        k = dict(arrivals="poisson", control="pretimed", lane_group=lg,
                 period="T1.0h_full")
        for field, col, lab in (("sim_control_delay", C1, "(c) HCM control delay"),
                                ("sim_timeLoss", C2, "(a) tripinfo timeLoss"),
                                ("sim_waitingTime", C3, "(b) tripinfo waitingTime (stopped)")):
            xs, ys = curve(field, **k)
            ax.plot(xs, ys, lw=2, color=col, marker="o", ms=4, label=lab)
            endlabel(ax, xs, ys, f"{ys[-1]:.0f}", col)
        ax.set_title(f"{'Exclusive left' if lg=='L' else 'Through+right'} lane group",
                     fontsize=10, color=INK, loc="left")
        style(ax, "degree of saturation v/c", "delay (s/veh)" if j == 0 else "",
              los_bands=True)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle("Three delay definitions on identical runs (pretimed, Poisson, T = 1 h)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(PLOTS, "delay_definitions.png"), dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


# ---------------------------------------------------------------- figure 4 ---
def fig_queues():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    for j, lg in enumerate(("L", "TR")):
        ax = axes[j]
        k = dict(arrivals="poisson", control="pretimed", lane_group=lg,
                 period="T1.0h_full")
        for field, col, lab in (("Q_Q95", C1, "HCM 95th-%ile back of queue"),
                                ("sim_q95", C2, "Simulated 95th-%ile of per-cycle max"),
                                ("sim_qmax", C3, "Simulated max per-cycle back of queue")):
            xs, ys = curve(field, **k)
            ax.plot(xs, ys, lw=2, color=col, marker="o", ms=4, label=lab)
            endlabel(ax, xs, ys, f"{ys[-1]:.0f}", col)
        ax.set_title(f"{'Exclusive left' if lg=='L' else 'Through+right'} lane group",
                     fontsize=10, color=INK, loc="left")
        style(ax, "degree of saturation v/c", "back of queue (veh/lane)" if j == 0 else "")
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle("HCM back-of-queue estimate vs laneAreaDetector per-cycle measurement",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(PLOTS, "queue_comparison.png"), dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


# ---------------------------------------------------------------- figure 5 ---
def fig_residual_bias():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    for j, lg in enumerate(("L", "TR")):
        ax = axes[j]
        k = dict(arrivals="poisson", control="pretimed", lane_group=lg)
        xs, ys = curve("sim_control_delay", period="T1.0h_full", **k)
        ax.plot(xs, ys, lw=2, color=C1, marker="o", ms=4,
                label="corrected: simulation drained to 7200 s")
        endlabel(ax, xs, ys, f"{ys[-1]:.0f}", C1)
        xs2, ys2 = curve("sim_control_delay", period="T1.0h_trunc", **k)
        ax.plot(xs2, ys2, lw=2, color=C2, marker="o", ms=4,
                label="naive: run stopped at 3600 s (residual queue dropped)")
        endlabel(ax, xs2, ys2, f"{ys2[-1]:.0f}", C2)
        ax.set_title(f"{'Exclusive left' if lg=='L' else 'Through+right'} lane group",
                     fontsize=10, color=INK, loc="left")
        style(ax, "degree of saturation v/c", "control delay (s/veh)" if j == 0 else "",
              los_bands=True)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle("Residual-queue truncation bias: vehicles still queued at the end of the "
                 "analysis period emit no tripinfo record", fontsize=11, color=INK,
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(PLOTS, "residual_queue_bias.png"), dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


# ------------------------------------------------------------------- tables ---
def los_agreement():
    """LOS letter agreement HCM vs simulation, per (arrivals, control, delay def)."""
    out = []
    for arr in ("uniform", "poisson"):
        for ctrl in ("pretimed", "actuated"):
            for simfield, name in (("sim_control_delay", "segment control delay"),
                                   ("sim_delay_wholetrip", "whole-trip delay"),
                                   ("sim_timeLoss", "tripinfo timeLoss"),
                                   ("sim_waitingTime", "tripinfo waitingTime")):
                rs = sel(arrivals=arr, control=ctrl, period="T1.0h_full")
                diffs = []
                for r in rs:
                    a = H.los_letter(r["delay"])          # delay-threshold only,
                    b = H.los_letter(r[simfield])         # both sides
                    diffs.append("ABCDEF".index(a) - "ABCDEF".index(b))
                n = len(diffs)
                out.append(dict(arrivals=arr, control=ctrl, sim_definition=name,
                                n=n, agree=sum(1 for d in diffs if d == 0),
                                hcm_worse_by_1=sum(1 for d in diffs if d == 1),
                                hcm_worse_by_2plus=sum(1 for d in diffs if d >= 2),
                                hcm_better=sum(1 for d in diffs if d < 0),
                                max_grades_apart=max(abs(d) for d in diffs)))
    return out


def md_table(rows, cols, headers=None, fmt=None):
    headers = headers or cols
    fmt = fmt or {}
    L = ["| " + " | ".join(headers) + " |",
         "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r[c]
            f = fmt.get(c)
            cells.append(f(v) if f else (f"{v:.2f}" if isinstance(v, float) else str(v)))
        L.append("| " + " | ".join(cells) + " |")
    return "\n".join(L)


def main():
    fig_hcm_vs_sim(); fig_arrival_process(); fig_delay_definitions()
    fig_queues(); fig_residual_bias()
    print("plots written to", PLOTS)
    ag = los_agreement()
    with open(os.path.join(OUT, "los_agreement.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ag[0].keys())); w.writeheader(); w.writerows(ag)
    # example standard engineering reports
    for tag, ctrl in (("poisson/pretimed_X090", "pretimed"),
                      ("poisson/actuated_X090", "actuated"),
                      ("poisson/pretimed_X115", "pretimed")):
        arr, run = tag.split("/")
        d = os.path.join(BASE, "sweep_" + arr, run)
        res = LR.build(d, CFG, ctrl, 0.0, 3600.0)
        open(os.path.join(OUT, f"LOS_report_{arr}_{run}.md"), "w").write(
            LR.render_md(res, title=f"({arr} arrivals, {run})"))
    print("example LOS reports written")
    return ag


if __name__ == "__main__":
    for a in main():
        print(a)
