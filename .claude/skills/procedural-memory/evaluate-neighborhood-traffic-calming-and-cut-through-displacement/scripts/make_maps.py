#!/usr/bin/env python3
"""Interior-volume spatial maps: one panel per variant, link width/colour = veh/h."""
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
import matplotlib.cm as cm               # noqa: E402
import matplotlib.colors as mcolors      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ANA = os.path.abspath(os.path.join(HERE, "..", "analysis"))
VARIANTS = list("ABCDEF")
LABEL = {"A": "A  baseline", "B": "B  interior 20 km/h", "C": "C  modal filter (centre)",
         "D": "D  diagonal diverters", "E": "E  one-way loop cells", "F": "F  filter + 20 km/h"}


def load(v):
    rows = []
    with open(os.path.join(ANA, "interior_volumes_%s.csv" % v)) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def main():
    data = {v: load(v) for v in VARIANTS if os.path.exists(
        os.path.join(ANA, "interior_volumes_%s.csv" % v))}
    # aggregate the two directions of each street segment for a cleaner map
    agg = {}
    vmax = 0
    for v, rows in data.items():
        seg = {}
        for r in rows:
            key = tuple(sorted([(float(r["x_from"]), float(r["y_from"])),
                                (float(r["x_to"]), float(r["y_to"]))]))
            seg[key] = seg.get(key, 0.0) + float(r["veh_per_hour_mean"])
        agg[v] = seg
        vmax = max(vmax, max(seg.values()))

    fig, axes = plt.subplots(2, 3, figsize=(16, 11))
    norm = mcolors.Normalize(0, vmax)
    cmap = cm.get_cmap("YlOrRd") if hasattr(cm, "get_cmap") else plt.get_cmap("YlOrRd")
    for ax, v in zip(axes.ravel(), VARIANTS):
        seg = agg.get(v, {})
        segs = [[a, b] for (a, b) in seg]
        vals = [seg[k] for k in seg]
        lc = LineCollection(segs, cmap=cmap, norm=norm,
                            linewidths=[1.0 + 5.0 * x / vmax for x in vals])
        lc.set_array(__import__("numpy").array(vals))
        ax.add_collection(lc)
        # ring outline
        ax.plot([50, 1000, 1000, 50, 50], [50, 50, 1000, 1000, 50], color="0.55", lw=2.5, zorder=0)
        ax.set_xlim(0, 1050)
        ax.set_ylim(0, 1050)
        ax.set_aspect("equal")
        ax.set_title("%s\ntotal interior veh-entries = %.0f" % (LABEL[v], sum(vals)), fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmap), ax=axes, shrink=0.7,
                 label="two-way street volume, veh/h (mean of 5 seeds)")
    fig.suptitle("Interior residential street volumes -- where the cut-through traffic goes",
                 fontsize=14)
    out = os.path.join(ANA, "interior_volume_maps.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
