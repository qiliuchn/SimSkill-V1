"""Figures: per-arm speed contours, queue time series, capacity table, diversion curve.

The speed-contour construction follows `implement-variable-speed-limits` /
[[variable-speed-limits-and-e2-detectors]]: E2 stations every ~500 m, lane-averaged mean
speed per interval, distance on y and simulation time on x.  A backward-tilting
low-speed band is the upstream-propagating shockwave.
"""
import json
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import wz_common as W
import analyze
import gen_additional as GA

C_TEXT = "#1a1a1a"
plt.rcParams.update({"figure.dpi": 130, "font.size": 8,
                     "axes.edgecolor": "#888", "axes.labelcolor": C_TEXT,
                     "text.color": C_TEXT, "xtick.color": C_TEXT,
                     "ytick.color": C_TEXT, "axes.titlesize": 9})


def contour_matrix(rundir, netfile):
    rows = analyze.read_e2(os.path.join(rundir, "e2.xml"))
    dists = GA.station_distances(netfile)
    cell = defaultdict(list)
    for r in rows:
        if not r["id"].startswith("e2_s") or r["speed"] < 0:
            continue
        s = int(r["id"].split("_")[1][1:])
        cell[(s, r["begin"])].append(r["speed"])
    times = sorted({t for _, t in cell})
    stations = sorted({s for s, _ in cell})
    M = np.full((len(stations), len(times)), np.nan)
    for i, s in enumerate(stations):
        for j, t in enumerate(times):
            v = cell.get((s, t))
            if v:
                M[i, j] = float(np.mean(v))
    y = np.array([dists.get(s, np.nan) for s in stations])
    return np.array(times), y, M


def speed_contours(runs, netfiles, out, wz_start=None, wz_end=None, title=""):
    n = len(runs)
    fig, axes = plt.subplots(1, n, figsize=(3.1 * n, 3.4), sharey=True,
                             constrained_layout=True)
    if n == 1:
        axes = [axes]
    im = None
    for ax, (lab, rd) in zip(axes, runs.items()):
        t, y, M = contour_matrix(rd, netfiles[lab])
        im = ax.pcolormesh(t / 60.0, y / 1000.0, M, cmap="RdYlGn", vmin=0, vmax=34,
                           shading="nearest")
        if wz_start is not None:
            ax.axhline(wz_start / 1000.0, color="k", lw=0.9, ls="--")
            ax.axhline(wz_end / 1000.0, color="k", lw=0.9, ls="--")
        ax.set_title(lab)
        ax.set_xlabel("time (min)")
    axes[0].set_ylabel("distance along corridor (km)")
    cb = fig.colorbar(im, ax=axes, shrink=0.9)
    cb.set_label("mean speed (m/s)")
    fig.suptitle(title, fontsize=10)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def queue_series(runs, out, title=""):
    """Upstream queue length (max jam length on the advance-warning control station)
    and running-vehicle count, per arm."""
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.6), sharex=True,
                             constrained_layout=True)
    for lab, rd in runs.items():
        rows = analyze.read_e2(os.path.join(rd, "e2_ctrl.xml"))
        by_t = defaultdict(float)
        for r in rows:
            by_t[r["begin"]] = max(by_t[r["begin"]], r["jam"])
        ts = sorted(by_t)
        axes[0].plot([t / 60 for t in ts], [by_t[t] for t in ts], lw=1.2, label=lab)
        s = analyze.read_summary(os.path.join(rd, "summary.xml"))
        ser = s.get("running_series") or []
        axes[1].plot([t / 60 for t, _ in ser], [v for _, v in ser], lw=1.0, label=lab)
    axes[0].set_ylabel("max jam length at\nadvance-warning station (m)")
    axes[1].set_ylabel("vehicles running")
    axes[1].set_xlabel("time (min)")
    axes[0].legend(fontsize=7, ncol=3, frameon=False)
    for a in axes:
        a.grid(alpha=0.25, lw=0.5)
        a.spines[["top", "right"]].set_visible(False)
    fig.suptitle(title, fontsize=10)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def line_ci(xs, series, out, xlabel, ylabel, title, hline=None, hlabel=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.5), constrained_layout=True)
    for lab, (m, lo, hi) in series.items():
        ax.plot(xs, m, marker="o", ms=3.5, lw=1.4, label=lab)
        ax.fill_between(xs, lo, hi, alpha=0.16, lw=0)
    if hline is not None:
        ax.axhline(hline, color="#555", ls="--", lw=1.0)
        if hlabel:
            ax.annotate(hlabel, (xs[0], hline), fontsize=7, color="#555",
                        va="bottom")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.25, lw=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def stacked_tstt(xs, comps, out, xlabel, title):
    fig, ax = plt.subplots(figsize=(5.8, 3.5), constrained_layout=True)
    bottom = np.zeros(len(xs))
    for lab, v in comps.items():
        ax.bar(range(len(xs)), v, bottom=bottom, label=lab, width=0.72)
        bottom += np.asarray(v)
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels([str(x) for x in xs], fontsize=7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("TSTT (vehicle-hours)")
    ax.set_title(title)
    ax.legend(fontsize=7, frameon=False, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out
