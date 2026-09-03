#!/usr/bin/env python3
"""Deliverable figures:
  fig_speed_contours.png   per-arm corridor time-space speed contour (E1 stations)
  fig_ramp_queues.png      per-ramp queue time series with the storage limit marked
  fig_tstt_decomposition.png  stacked TSTT/TSD decomposition by arm and demand level
  fig_h2_storage_sweep.png coordination gain vs ramp-storage length
  fig_h4_spillback.png     surface delay vs ramp-queue vehicle-hours (log-log)
"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FIG = os.path.join(ROOT, "outputs", "figs")
RUNS = os.path.join(ROOT, "outputs", "runs2")
STATIONS = [f"s{i:02d}" for i in range(1, 13)]
SX = [500, 1900, 2282.8, 3482.8, 4284.1, 5145.3, 6045.3, 6846.5, 7607.7, 8407.7, 8803.6, 9803.6]
RAMPS = ["r1", "r2", "r3"]
RAMP_X = {"r1": 2000, "r2": 5000, "r3": 7500}
DROP_X = 8600
ARMS = ["nocontrol", "fixed", "alinea", "bnalinea", "coord", "coord_flush"]
LBL = {"nocontrol": "no control", "fixed": "fixed-rate", "alinea": "isolated ALINEA",
       "bnalinea": "bottleneck-ALINEA (r3 only)", "coord": "coordinated (HERO-style)",
       "coord_flush": "coordinated + queue flush", "negctrl": "negative control"}
CLR = {"mainline": "#3B6FB6", "ramp": "#E08A2E", "surface": "#4C9A70", "origin": "#B5483D"}


def load_csv():
    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, "outputs", "tables", "runs.csv"))):
        d = {}
        for k, v in r.items():
            if k in ("tag", "arm", "ramp_wait_per_veh"):
                d[k] = v
            else:
                try:
                    d[k] = float(v) if v not in ("", "None") else None
                except ValueError:
                    d[k] = v
        d["group"] = r["tag"].split("/")[0]
        rows.append(d)
    return rows


def contour(demand=0.95, seed=1):
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 7.6), sharex=True, sharey=True)
    im = None
    for ax, arm in zip(axes.ravel(), ARMS):
        p = os.path.join(RUNS, "core", f"{arm}_d{int(demand*100)}_s{seed}", "ctl.json")
        log = json.load(open(p))["log"]
        t = np.array([r["t"] for r in log]) / 60.0
        Z = np.full((len(STATIONS), len(log)), np.nan)
        for j, r in enumerate(log):
            for i, s in enumerate(STATIONS):
                if r["spd"][s] is not None:
                    Z[i, j] = r["spd"][s] * 3.6
        for i in range(Z.shape[0]):     # forward-fill empty intervals
            row = Z[i]
            idx = np.where(~np.isnan(row))[0]
            if len(idx):
                row[:] = np.interp(np.arange(len(row)), idx, row[idx])
        im = ax.pcolormesh(t, np.array(SX) / 1000.0, Z, cmap="RdYlGn", vmin=0, vmax=120,
                           shading="auto")
        ax.axhline(DROP_X / 1000.0, color="k", lw=1.2, ls="--")
        for r, x in RAMP_X.items():
            ax.axhline(x / 1000.0, color="k", lw=0.6, ls=":", alpha=0.6)
            ax.text(t[-1] * 0.995, x / 1000.0 + 0.08, r, fontsize=7, ha="right")
        ax.text(t[-1] * 0.995, DROP_X / 1000.0 + 0.08, "lane drop", fontsize=7, ha="right")
        ax.set_title(LBL[arm], fontsize=10)
    for ax in axes[1]:
        ax.set_xlabel("time (min)")
    for ax in axes[:, 0]:
        ax.set_ylabel("distance along corridor (km)")
    fig.colorbar(im, ax=axes, label="mean speed (km/h)", fraction=0.02, pad=0.01)
    fig.suptitle(f"Corridor speed contours by control arm (demand x{demand}, seed {seed}) "
                 f"-- E1 stations, 30 s intervals", fontsize=12)
    fig.savefig(os.path.join(FIG, "fig_speed_contours.png"), dpi=135, bbox_inches="tight")
    plt.close(fig)


def ramp_queues(demand=0.95, seed=1):
    stor = {"r1": 280.0, "r2": 220.0, "r3": 160.0}
    fig, axes = plt.subplots(3, 1, figsize=(12, 9.5), sharex=True)
    for ax, r in zip(axes, RAMPS):
        for arm, c in zip(["nocontrol", "alinea", "coord", "coord_flush"],
                          ["#888888", "#E08A2E", "#3B6FB6", "#4C9A70"]):
            p = os.path.join(RUNS, "core", f"{arm}_d{int(demand*100)}_s{seed}", "ctl.json")
            log = json.load(open(p))["log"]
            t = [x["t"] / 60.0 for x in log]
            q = [x["ramp"][r]["jam_m"] for x in log]
            ax.plot(t, q, lw=1.3, color=c, label=LBL[arm])
        ax.axhline(stor[r], color="k", ls="--", lw=1.4)
        ax.text(1, stor[r] + 4, f"storage limit = {stor[r]:.0f} m", fontsize=8)
        ax.set_ylabel(f"{r} queue (m)")
        ax.set_ylim(0, stor[r] * 1.35)
        ax.grid(alpha=0.25)
    axes[0].legend(fontsize=8, ncol=4, loc="upper left")
    axes[-1].set_xlabel("time (min)")
    fig.suptitle(f"Ramp queue length vs storage limit (demand x{demand}, seed {seed}); "
                 f"r3 is the bottleneck-adjacent ramp", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_ramp_queues.png"), dpi=135, bbox_inches="tight")
    plt.close(fig)


def tstt_decomp(rows):
    core = [r for r in rows if r["group"] == "core"]
    dems = sorted({r["demand"] for r in core})
    fig, axes = plt.subplots(1, len(dems), figsize=(3.5 * len(dems), 5.2), sharey=True)
    for ax, dem in zip(np.atleast_1d(axes), dems):
        xs = np.arange(len(ARMS))
        bottom = np.zeros(len(ARMS))
        for comp in ("mainline", "ramp", "surface", "origin"):
            vals = []
            for a in ARMS:
                g = [r[f"delay_{comp}"] for r in core
                     if r["arm"] == a and abs(r["demand"] - dem) < 1e-9]
                vals.append(np.mean(g) if g else 0.0)
            ax.bar(xs, vals, bottom=bottom, color=CLR[comp], label=comp, width=0.68)
            bottom += np.array(vals)
        ax.set_xticks(xs)
        ax.set_xticklabels([LBL[a].replace(" (r3 only)", "") for a in ARMS],
                           rotation=38, ha="right", fontsize=8)
        ax.set_title(f"demand x{dem}", fontsize=10)
        ax.grid(axis="y", alpha=0.25)
        for i, b in enumerate(bottom):
            ax.text(i, b * 1.01, f"{b:.0f}", ha="center", fontsize=7)
    np.atleast_1d(axes)[0].set_ylabel("Total System Delay (vehicle-hours)")
    np.atleast_1d(axes)[0].legend(fontsize=8)
    fig.suptitle("Total System Delay decomposition by control arm and demand level "
                 "(mean of 8 CRN seeds)", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_tstt_decomposition.png"), dpi=135, bbox_inches="tight")
    plt.close(fig)


def storage_sweep(rows):
    core = [r for r in rows if r["group"] == "core"]
    stor = [r for r in rows if r["group"] == "stor"]
    sts = [80, 160, 320, 640]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    series = {}
    for arm in ("alinea", "coord"):
        ys, es = [], []
        for st in sts:
            if st == 160:
                g = {int(r["seed"]): r for r in core
                     if r["arm"] == arm and abs(r["demand"] - 0.95) < 1e-9}
                nc = {int(r["seed"]): r for r in core
                      if r["arm"] == "nocontrol" and abs(r["demand"] - 0.95) < 1e-9}
            else:
                g = {int(r["seed"]): r for r in stor if r["arm"] == arm and f"st{st}_" in r["tag"]}
                nc = {int(r["seed"]): r for r in stor
                      if r["arm"] == "nocontrol" and f"st{st}_" in r["tag"]}
            ss = sorted(set(g) & set(nc))
            d = np.array([100 * (g[s]["TSD"] - nc[s]["TSD"]) / nc[s]["TSD"] for s in ss])
            ys.append(d.mean())
            es.append(1.96 * d.std(ddof=1) / np.sqrt(len(d)))
        series[arm] = (ys, es)
        ax.errorbar(sts, ys, yerr=es, marker="o", capsize=4, label=LBL[arm], lw=1.8)
    ax.axhline(0, color="k", lw=1)
    ax.set_xscale("log")
    ax.set_xticks(sts)
    ax.set_xticklabels(sts)
    ax.set_xlabel("bottleneck-adjacent ramp (r3) storage length (m)")
    ax.set_ylabel("Total System Delay vs no control (%)")
    ax.set_title("H2: does coordination gain scale with ramp storage?", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    gain = np.array(series["alinea"][0]) - np.array(series["coord"][0])
    ax2.plot(sts, gain, marker="s", color="#B5483D", lw=1.8)
    ax2.axhline(0, color="k", lw=1)
    ax2.set_xscale("log")
    ax2.set_xticks(sts)
    ax2.set_xticklabels(sts)
    ax2.set_xlabel("r3 storage length (m)")
    ax2.set_ylabel("coordination gain (pp of TSD vs no control)")
    ax2.set_title("coordination advantage over isolated ALINEA", fontsize=10)
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_h2_storage_sweep.png"), dpi=135, bbox_inches="tight")
    plt.close(fig)


def spillback(rows):
    core = [r for r in rows if r["group"] == "core"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    for arm in ARMS:
        g = [r for r in core if r["arm"] == arm]
        x = [sum(r[f"{q}_queue_veh_hours"] for q in RAMPS) for r in g]
        y = [r["delay_surface"] for r in g]
        ax.scatter(x, y, s=16, alpha=0.7, label=LBL[arm])
    xs = np.array([sum(r[f"{q}_queue_veh_hours"] for q in RAMPS) for r in core])
    ys = np.array([r["delay_surface"] for r in core])
    m = xs > 0.5
    sl, ic = np.polyfit(np.log(xs[m]), np.log(ys[m]), 1)
    xx = np.linspace(np.log(xs[m].min()), np.log(xs[m].max()), 50)
    ax.plot(np.exp(xx), np.exp(ic + sl * xx), "k--", lw=1.5,
            label=f"power fit, exponent = {sl:.2f}")
    ax.plot(np.exp(xx), np.exp(ic + 1.0 * (xx - xx[0])) * np.exp(sl * xx[0]) / np.exp(0),
            color="grey", lw=0.8, alpha=0)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("total ramp-queue vehicle-hours")
    ax.set_ylabel("surface-street delay (veh-h)")
    ax.set_title(f"H4: surface delay vs ramp queue (exponent {sl:.2f})", fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, which="both")
    for arm in ARMS:
        g = [r for r in core if r["arm"] == arm]
        x = [np.mean([r[f"{q}_frac_storage_exceeded"] for q in RAMPS]) * 100 for r in g]
        y = [r["surface_capp_veh_hours"] for r in g]
        ax2.scatter(x, y, s=16, alpha=0.7, label=LBL[arm])
    ax2.set_xlabel("% of control intervals with ramp storage exceeded (>=95% full)")
    ax2.set_ylabel("cross-street queue at ramp terminals (veh-h)")
    ax2.set_title("explicit spillback instrumentation", fontsize=10)
    ax2.grid(alpha=0.25)
    ax2.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig_h4_spillback.png"), dpi=135, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(FIG, exist_ok=True)
    rows = load_csv()
    contour()
    ramp_queues()
    tstt_decomp(rows)
    storage_sweep(rows)
    spillback(rows)
    print("figures written to", FIG)
