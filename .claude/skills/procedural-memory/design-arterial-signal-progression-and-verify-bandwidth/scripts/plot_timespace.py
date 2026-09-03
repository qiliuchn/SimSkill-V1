#!/usr/bin/env python3
"""Publication-quality annotated time-space diagrams for the arterial.

Green/red bars per signal drawn from the tlLogic ACTUALLY in force, using the
verified SUMO offset convention (program position at time t is (t-offset) mod C,
so a program-coordinate span [a,b) appears in absolute time at k*C+offset+[a,b)
-- see data/verify_offsets.json), with real FCD vehicle trajectories overlaid
and the analytic MAXBAND band drawn as a translucent parallelogram so the three
measurement layers can be compared by eye.
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402

import matplotlib             # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt        # noqa: E402
from matplotlib.lines import Line2D    # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402


def windows(plan, i, direction, t0, t1):
    """Absolute-time green windows of the through movement at signal i."""
    p0, w = plan.through_window(i, direction)
    C, off = plan.C, plan.offs[i] % plan.C
    out = []
    k0 = int((t0 - off - p0) // C) - 1
    for k in range(k0, int((t1 - off - p0) // C) + 2):
        a, b = k * C + off + p0, k * C + off + p0 + w
        if b > t0 and a < t1:
            out.append((max(a, t0), min(b, t1)))
    return out


def traj(fcd, t0, t1, prefix):
    tr = defaultdict(list)
    for _, el in ET.iterparse(fcd, events=("end",)):
        # do NOT clear non-timestep elements: clearing a <vehicle> on its own
        # end event strips its attributes before the parent <timestep>'s end
        # event is reached, so the children read back as attribute-less stubs.
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        if t0 - 5 <= t <= t1 + 5:
            for v in el:
                if v.get("id").startswith(prefix):
                    tr[v.get("id")].append((t, float(v.get("x"))))
        el.clear()
    for v in tr.values():
        v.sort()
    return tr


def panel(ax, plan, xs, fcd, direction, t0, t1, v, band_set=None):
    prefix = "thruE" if direction == "EB" else "thruW"
    n = len(xs)
    for i in range(n):
        y = xs[i] - xs[0]
        ax.plot([t0, t1], [y, y], color="#c62828", lw=6, alpha=0.30,
                solid_capstyle="butt", zorder=1)
        for a, b in windows(plan, i, direction, t0, t1):
            ax.plot([a, b], [y, y], color="#2e7d32", lw=6, alpha=0.95,
                    solid_capstyle="butt", zorder=2)
        ax.text(t0 - (t1 - t0) * 0.015, y, "J%d" % i, ha="right", va="center",
                fontsize=8, weight="bold", color="#444444")
    # analytic band as a parallelogram, drawn from the exact feasible set
    if band_set:
        ref = xs[0] if direction == "EB" else xs[-1]
        y0 = ref - xs[0]
        yN = (xs[-1] if direction == "EB" else xs[0]) - xs[0]
        span = abs(xs[-1] - xs[0]) / v
        for k in range(int((t0 - plan.C) // plan.C), int(t1 // plan.C) + 2):
            for a, b in band_set:
                aa, bb = a + k * plan.C, b + k * plan.C
                if bb < t0 - span or aa > t1:
                    continue
                ax.add_patch(Polygon([(aa, y0), (bb, y0),
                                      (bb + span, yN), (aa + span, yN)],
                                     closed=True, facecolor="#1565c0",
                                     alpha=0.13, edgecolor="#1565c0",
                                     lw=0.8, zorder=1.5))
    nv = 0
    if fcd and os.path.exists(fcd):
        for vid, pts in traj(fcd, t0, t1, prefix).items():
            if len(pts) < 4:
                continue
            ax.plot([p[0] for p in pts], [p[1] - xs[0] for p in pts],
                    lw=0.7, color="#0d1b2a", alpha=0.55, zorder=3)
            nv += 1
    ax.set_xlim(t0, t1)
    ax.set_ylim(-40, xs[-1] - xs[0] + 40)
    ax.set_xlabel("simulation time (s)")
    ax.grid(axis="y", ls=":", alpha=0.25)
    return nv


def figure(plan, xs, fcd, out, title, v, t0=1200.0, t1=1560.0, band=None):
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.2), sharey=True)
    nE = panel(axes[0], plan, xs, fcd, "EB", t0, t1, v,
               band[0] if band else None)
    nW = panel(axes[1], plan, xs, fcd, "WB", t0, t1, v,
               band[1] if band else None)
    axes[0].set_ylabel("distance along corridor (m)")
    axes[0].set_title("EASTBOUND  (n=%d trajectories)" % nE, fontsize=11)
    axes[1].set_title("WESTBOUND  (n=%d trajectories)" % nW, fontsize=11)
    fig.suptitle(title, fontsize=13)
    fig.legend(handles=[
        Line2D([0], [0], color="#2e7d32", lw=6, label="through green"),
        Line2D([0], [0], color="#c62828", lw=6, alpha=0.35, label="through red"),
        Line2D([0], [0], color="#0d1b2a", lw=1.2, label="vehicle trajectory (FCD)"),
        Line2D([0], [0], color="#1565c0", lw=6, alpha=0.3,
               label="analytic two-way band")],
        loc="lower center", ncol=4, fontsize=9, frameon=False,
        bbox_to_anchor=(0.5, -0.005))
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)
