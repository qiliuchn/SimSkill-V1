"""
Step 3/5. Turn the converged equilibria into the reported deliverables:
convergence traces, departure-rate and Newell cumulative-curve plots, the cost-decomposition
table, the equilibrium test, the analytic-Vickrey comparison, and the per-seed metrics CSV.
"""
import os, sys, json, csv
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from vickrey_lib import *
from evaluate import queue_curves

OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_19-30-00/outputs"
os.makedirs(OUT, exist_ok=True)

C = dict(no_toll="#1f77b4", tv_toll="#d62728", flat_toll="#2ca02c",
         zero_toll="#9467bd", gamma4="#ff7f0e", no_toll_alt="#17becf", tv_toll2="#8c564b", analytic="#444444")
LBL = dict(no_toll="No toll", tv_toll="Time-varying toll", flat_toll="Flat toll (equal revenue)",
           zero_toll="Zero toll (negative control)", gamma4="No toll, gamma=4 (late-averse)",
           no_toll_alt="No toll, independent restart",
           tv_toll2="Time-varying toll, 2nd pass")


def load(name):
    return json.load(open(os.path.join(WORK, "eq_" + name, "result.json")))


def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ plots
def plot_convergence(names, path):
    fig, ax = plt.subplots(2, 2, figsize=(12, 7.5))
    for nm in names:
        r = load(nm)
        tr = r["trace"]
        it = [t["iter"] for t in tr]
        ax[0, 0].plot(it, [t["sumo_mean_cost"] for t in tr], color=C.get(nm), label=LBL.get(nm, nm), lw=1.3, marker="o", ms=3)
        ax[0, 1].plot(it, [t["sumo_used_cost_sd_rel"] for t in tr], color=C.get(nm), lw=1.3, marker="o", ms=3)
        ax[1, 0].plot(it, [t["frac_changed_slot"] for t in tr], color=C.get(nm), lw=1.3, marker="o", ms=3)
        ax[1, 1].plot(it, [t["sumo_mean_queue"] for t in tr], color=C.get(nm), lw=1.3, marker="o", ms=3)
    ax[0, 0].set_ylabel("SUMO mean generalized cost (s)"); ax[0, 0].set_xlabel("outer iteration")
    ax[0, 0].legend(fontsize=8)
    ax[0, 1].set_ylabel("rel. sd of SUMO cost across used slots"); ax[0, 1].set_yscale("log")
    ax[0, 1].set_xlabel("outer iteration"); ax[0, 1].axhline(0.05, ls=":", c="k", lw=0.8)
    ax[1, 0].set_ylabel("fraction of travellers changing slot"); ax[1, 0].set_yscale("log")
    ax[1, 0].set_xlabel("outer iteration")
    ax[1, 1].set_ylabel("SUMO mean queueing delay (s)"); ax[1, 1].set_xlabel("outer iteration")
    for a in ax.ravel():
        a.grid(alpha=0.3)
    fig.suptitle("Departure-time equilibrium: outer-loop convergence", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_departure_rates(names, analytic, path, s_vps=None):
    st = slot_starts()
    fig, ax = plt.subplots(figsize=(11, 5))
    for nm in names:
        r = load(nm)
        cnt = np.array(r["counts"], float)
        ax.step(st, cnt / SLOT * 3600.0, where="post", color=C.get(nm),
                label=LBL.get(nm, nm), lw=1.6)
    if analytic is not None:
        ax.plot(analytic["t"], analytic["rate"], color=C["analytic"], ls="--", lw=1.8,
                label="Vickrey closed form")
    if s_vps:
        ax.axhline(s_vps * 3600, color="k", ls=":", lw=1.2, label="measured capacity s")
    ax.axvline(T_STAR, color="0.5", ls="-.", lw=1.0)
    ax.annotate("t* (desired arrival)", (T_STAR, ax.get_ylim()[1] * 0.93),
                fontsize=8, ha="right", color="0.4")
    ax.set_xlabel("departure time (s)"); ax.set_ylabel("departure rate (veh/h)")
    ax.set_xlim(2000, 4200); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_title("Endogenous departure-rate profile at equilibrium")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_newell(rows_by_cond, tf, path):
    n = len(rows_by_cond)
    fig, axs = plt.subplots(2, n, figsize=(5.0 * n, 7.5), sharex=True)
    if n == 1:
        axs = axs.reshape(2, 1)
    for j, (nm, rows) in enumerate(rows_by_cond.items()):
        g, D, V, A, Q = queue_curves(rows, tf)
        a0, a1 = axs[0, j], axs[1, j]
        a0.plot(g, D, color="#888888", lw=1.2, label="cumulative departures D(t)")
        a0.plot(g, V, color="#1f77b4", lw=1.4, label="virtual arrivals D(t-Tf)")
        a0.plot(g, A, color="#d62728", lw=1.4, label="actual arrivals A(t)")
        a0.fill_between(g, A, V, where=(V > A), color="#d62728", alpha=0.15)
        a0.axvline(T_STAR, color="0.5", ls="-.", lw=1.0)
        a0.set_title(LBL.get(nm, nm), fontsize=11)
        a0.set_ylabel("cumulative vehicles"); a0.grid(alpha=0.3)
        if j == 0:
            a0.legend(fontsize=7.5, loc="upper left")
        a1.plot(g, Q, color=C.get(nm, "k"), lw=1.6)
        a1.fill_between(g, 0, Q, color=C.get(nm, "k"), alpha=0.15)
        a1.axvline(T_STAR, color="0.5", ls="-.", lw=1.0)
        a1.set_xlabel("time (s)"); a1.set_ylabel("queue (veh)"); a1.grid(alpha=0.3)
        a1.text(0.03, 0.9, "max queue = %.0f veh" % Q.max(), transform=a1.transAxes, fontsize=9)
        a1.set_xlim(2000, 4400)
    ymax = max(ax.get_ylim()[1] for ax in axs[1, :])
    for ax in axs[1, :]:
        ax.set_ylim(0, ymax)
    fig.suptitle("Newell cumulative curves and the vertical queue", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_cost_curves(names, path):
    st = slot_starts() + SLOT / 2.0
    fig, ax = plt.subplots(figsize=(11, 5))
    for nm in names:
        r = load(nm)
        cnt = np.array(r["slot_cnt"]); mc = np.array(r["slot_mean_cost"])
        u = cnt >= 3
        ax.plot(st[u], mc[u], "o-", ms=3, lw=1.3, color=C.get(nm), label=LBL.get(nm, nm))
        w = np.average(mc[u], weights=cnt[u])
        ax.axhline(w, color=C.get(nm), ls=":", lw=1.0)
    ax.set_xlabel("departure slot (s)")
    ax.set_ylabel("mean generalized cost incl. toll (s of travel-time equivalent)")
    ax.set_xlim(2000, 4200); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_title("Equilibrium test: cost of USED departure slots (dotted = demand-weighted mean)")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_toll(tau_emp, tau_an, tau_flat, path):
    st = slot_starts() + SLOT / 2.0
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(st, tau_emp, color="#d62728", lw=1.8, label="empirical time-varying toll = alpha*Q(t)")
    ax.plot(st, tau_an, color="#444444", ls="--", lw=1.5, label="closed-form Vickrey optimal toll")
    ax.axhline(tau_flat, color="#2ca02c", lw=1.6, label="flat toll (equal revenue)")
    ax.axvline(T_STAR, color="0.5", ls="-.", lw=1.0)
    ax.set_xlim(2000, 4200); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_xlabel("departure time (s)")
    ax.set_ylabel("toll (s of travel-time equivalent)")
    sec = ax.secondary_yaxis('right', functions=(lambda v: v * VOT_USD_PER_SEC,
                                                 lambda v: v / VOT_USD_PER_SEC))
    sec.set_ylabel("toll ($, at VOT $18/h)")
    ax.set_title("Toll profiles")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)
