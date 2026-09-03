#!/usr/bin/env python3
"""Figure: equilibrium mean travel time LINK vs NOLINK by demand, and LINK route shares."""
import argparse
import csv
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C_NOLINK, C_LINK, C_ZIG, C_UP, C_LO = "#2a78d6", "#eb6834", "#4a3aa7", "#1baf7a", "#eda100"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.table)))
    s = json.load(open(a.summary))
    d = [float(r["demand_vph"]) for r in rows]
    nl = [float(r["nolink_mean_duration_s"]) for r in rows]
    lk = [float(r["link_mean_duration_s"]) for r in rows]
    zz = [float(r["link_share_zigzag_pct"]) for r in rows]
    up = [float(r["link_share_upper_pct"]) for r in rows]
    lo = [float(r["link_share_lower_pct"]) for r in rows]
    thr = s.get("paradox_threshold_vph")

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8.4, 7.6), sharex=True,
                                  gridspec_kw={"height_ratios": [1.5, 1]})
    fig.patch.set_facecolor(SURF)
    for x in (ax, ax2):
        x.set_facecolor(SURF)
        x.grid(True, color=GRID, lw=0.8)
        x.set_axisbelow(True)
        for sp in ("top", "right"):
            x.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            x.spines[sp].set_color("#c9c8c2")

    if thr:
        for x in (ax, ax2):
            x.axvline(thr, color=INK2, lw=1.2, ls=(0, (4, 3)), zorder=1)
    ax.fill_between(d, nl, lk, where=[b > c for b, c in zip(lk, nl)],
                    color=C_LINK, alpha=0.12, zorder=1, interpolate=True)
    ax.plot(d, nl, "-o", color=C_NOLINK, lw=2, ms=8, mec=SURF, mew=1.6, label="NOLINK  (no cross link)", zorder=3)
    ax.plot(d, lk, "-s", color=C_LINK, lw=2, ms=8, mec=SURF, mew=1.6, label="LINK  (cross link A→B added)", zorder=3)
    i_mid = len(d) // 2 + 1
    ax.annotate("NOLINK", (d[i_mid], nl[i_mid]), xytext=(0, -20), textcoords="offset points",
                ha="center", color=C_NOLINK, fontsize=9.5, weight="bold")
    ax.annotate("LINK", (d[i_mid], lk[i_mid]), xytext=(0, 22), textcoords="offset points",
                ha="center", color=C_LINK, fontsize=9.5, weight="bold")
    label_at = {900, 1200, 1500, 1700, 1800, 2100, 2400, 3000}
    for x, b, c in zip(d, nl, lk):
        if x not in label_at:
            continue
        pct = 100 * (c - b) / b
        above = c >= b
        ax.annotate(f"{pct:+.0f}%", (x, c), xytext=(0, 10 if above else -18),
                    textcoords="offset points", ha="center", fontsize=8, color=INK2)
    lo_y, hi_y = ax.get_ylim()
    ax.set_ylim(lo_y - 0.07 * (hi_y - lo_y), hi_y)
    if thr:
        ax.annotate(f"paradox threshold ≈ {thr:.0f} veh/h\nbelow: the extra link HELPS   ·   above: it HURTS",
                    (thr, lo_y), xytext=(10, 4), textcoords="offset points",
                    va="bottom", ha="left", fontsize=9, color=INK2)
    ax.set_ylabel("equilibrium mean in-network\ntravel time (s)", color=INK2)
    ax.set_title("Braess's paradox in SUMO: adding a link makes the user equilibrium worse\n"
                 "duaIterate DUE, identical demand / seed / departure schedule in both variants",
                 color=INK, fontsize=11, loc="left")
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK2)

    ax2.stackplot(d, zz, up, lo, colors=[C_ZIG, C_UP, C_LO], alpha=0.9,
                  labels=["zig-zag  S→A→B→T", "upper  S→A→T", "lower  S→B→T"], ec=SURF, lw=1.4)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("LINK equilibrium\nroute share (%)", color=INK2)
    ax2.set_xlabel("total S→T demand (veh/h)", color=INK2)
    ax2.legend(frameon=False, loc="upper right", fontsize=9, labelcolor=INK2, ncol=3)
    fig.tight_layout()
    fig.savefig(a.out, dpi=170, bbox_inches="tight", facecolor=SURF)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
