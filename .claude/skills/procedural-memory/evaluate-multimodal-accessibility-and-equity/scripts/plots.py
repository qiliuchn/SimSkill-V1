#!/usr/bin/env python3
"""Deliverable figures: accessibility choropleth over the network geometry
(one panel per mode x scenario), Lorenz curves, skim-validation scatter, and the
transit time-decomposition stacked bars."""
import os
import sys
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.cm import ScalarMappable

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402

WORK, OUTDIR = sys.argv[1], sys.argv[2]
os.makedirs(OUTDIR, exist_ok=True)
SCNS = ["base", "altA", "altB"]
LABEL = {"base": "Base", "altA": "A: road capacity", "altB": "B: transit service"}
# validated categorical palette (scripts/validate_palette.js, light mode: ALL PASS)
CAT = {"base": "#3b6fd4", "altA": "#d97706", "altB": "#0f9b8e"}
COMP = ["access", "wait", "invehicle", "transfer", "egress"]
COMP_LBL = {"access": "access walk", "wait": "initial wait", "invehicle": "in-vehicle",
            "transfer": "transfer (walk+wait)", "egress": "egress walk"}
COMP_COL = dict(zip(COMP, ["#3b6fd4", "#d97706", "#0f9b8e", "#a855c7", "#b0455e"]))
INK, MUTED, GRID = "#1f2328", "#5b6570", "#e3e6ea"

plt.rcParams.update({"font.size": 8.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK, "text.color": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.titlesize": 9, "figure.facecolor": "white",
                     "axes.facecolor": "white", "savefig.facecolor": "white"})

AC = json.load(open(os.path.join(WORK, "accessibility.json")))
EQ = json.load(open(os.path.join(WORK, "equity_bca.json")))
ZI = json.load(open(os.path.join(WORK, "zones.json")))["zones"]
DEM = json.load(open(os.path.join(WORK, "demand.json")))["demographics"]
ZONES = AC["zones"]
E2Z = {e: z for z in ZONES for e in ZI[z]["edges"]}

# single-hue sequential ramps (light -> dark), one hue per mode row
SEQ = {"car": LinearSegmentedColormap.from_list("carseq", ["#e8eefc", "#1e3f86"]),
       "pt": LinearSegmentedColormap.from_list("ptseq", ["#e2f4f1", "#0a5e56"])}


# ----------------------------------------------------------------- choropleth
def panel(ax, net, vals, cmap, norm, title):
    segs, cols = [], []
    for e in net.getEdges():
        if e.getID().startswith(":"):
            continue
        z = E2Z.get(e.getID())
        if z is None:
            continue
        sh = e.getShape()
        segs.append(sh)
        cols.append(cmap(norm(vals[z])))
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=1.8))
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_title(title, pad=3)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


netb = sumolib.net.readNet(os.path.join(WORK, "base.net.xml"))
neta = sumolib.net.readNet(os.path.join(WORK, "altA.net.xml"))
NET = {"base": netb, "altA": neta, "altB": netb}

fig, axes = plt.subplots(2, 3, figsize=(10.2, 7.0))
for row, (mode, key) in enumerate((("car", "grav_car_basebeta"),
                                   ("pt", "grav_pt_carbeta_basebeta"))):
    allv = [AC["results"][s]["A"][key][z] for s in SCNS for z in ZONES]
    norm = Normalize(min(allv), max(allv))
    for col, scn in enumerate(SCNS):
        panel(axes[row][col], NET[scn], AC["results"][scn]["A"][key],
              SEQ[mode], norm, "%s  |  %s" % (LABEL[scn],
                                              "car" if mode == "car" else "transit"))
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=SEQ[mode]),
                      ax=axes[row].tolist(), fraction=0.022, pad=0.01)
    cb.set_label("gravity accessibility (jobs, beta=%.4f/min)"
                 % (AC["results"]["base"]["beta_car_per_s"] * 60), fontsize=7.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, color=GRID)
fig.suptitle("Zone accessibility to jobs over the network geometry — congested skims, "
             "common beta", fontsize=10.5, y=0.97)
fig.savefig(os.path.join(OUTDIR, "accessibility_choropleth.png"), dpi=170,
            bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------------------- isochrone map
fig, axes = plt.subplots(1, 3, figsize=(10.2, 3.7))
band_edges = [5, 10, 15, 20, 30, 45]
iso_cmap = LinearSegmentedColormap.from_list("iso", ["#12324f", "#e8eefc"])
for col, scn in enumerate(SCNS):
    A = AC["results"][scn]["A"]
    band = {}
    for z in ZONES:
        b = len(band_edges)
        for k, t in enumerate(band_edges):
            if A["cum_car_%d" % t][z] >= 0.5 * 71400:
                b = k
                break
        band[z] = b
    panel(axes[col], NET[scn], band, iso_cmap,
          Normalize(0, len(band_edges) - 1),
          "%s: minutes by car to reach 50%% of all jobs" % LABEL[scn])
handles = [plt.Line2D([0], [0], color=iso_cmap(k / (len(band_edges) - 1)), lw=3,
                      label="<= %d min" % t) for k, t in enumerate(band_edges)]
axes[-1].legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5),
                frameon=False, fontsize=7)
fig.suptitle("Isochrone bands: time by car to reach half the metropolitan job total",
             fontsize=10.5)
fig.savefig(os.path.join(OUTDIR, "isochrone_map.png"), dpi=170, bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------------------- Lorenz
fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.1))
for ax, key, ttl in ((axes[0], "lorenz_person",
                      "Population-weighted accessibility\n(mode-weighted per person)"),
                     (axes[1], "lorenz_pt", "Transit-only accessibility")):
    ax.plot([0, 1], [0, 1], color=GRID, lw=1.4, zorder=1)
    ax.text(0.62, 0.56, "perfect equality", color=MUTED, fontsize=7.5, rotation=34)
    for scn in SCNS:
        pts = EQ["equity"][scn][key]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        ax.plot(xs, ys, color=CAT[scn], lw=2.0, zorder=3, label=LABEL[scn])
        ax.plot(xs[1:], ys[1:], "o", ms=3.2, color=CAT[scn], mec="white", mew=0.7,
                zorder=4)
    g = [EQ["equity"][s]["gini_person" if key == "lorenz_person" else "gini_pt"]
         for s in SCNS]
    for k, scn in enumerate(SCNS):
        ax.annotate("%s  Gini %.3f" % (LABEL[scn].split(":")[0], g[k]),
                    xy=(0.03, 0.93 - 0.07 * k), xycoords="axes fraction",
                    color=CAT[scn], fontsize=8)
    ax.set_xlabel("cumulative share of population (lowest accessibility first)")
    ax.set_ylabel("cumulative share of accessibility")
    ax.set_title(ttl)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
axes[0].legend(frameon=False, loc="lower right", fontsize=8)
fig.suptitle("Lorenz curves of accessibility to jobs", fontsize=10.5)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "lorenz_curves.png"), dpi=170, bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------------------- validation
fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.1))
V = {s: json.load(open(os.path.join(WORK, "verify_%s.json" % s))) for s in SCNS}
for scn in SCNS:
    r = V[scn]["car_rows"]
    axes[0].plot([x["skim_s"] / 60 for x in r], [x["sim_mean_s"] / 60 for x in r],
                 "o", ms=5, color=CAT[scn], alpha=0.8, mec="white", mew=0.6,
                 label=LABEL[scn])
    p = V[scn]["pt_rows"]
    axes[1].plot([x["dua_pred_s"] / 60 for x in p], [x["sim_mean_s"] / 60 for x in p],
                 "o", ms=3.0, color=CAT[scn], alpha=0.45, mec="none", label=LABEL[scn])
for ax, ttl, xl, yl in ((axes[0], "Car skim vs microsimulation\n(probe vehicles on the "
                                  "skim route)", "duarouter congested skim (min)",
                         "tripinfo duration + departDelay (min)"),
                        (axes[1], "Transit: duarouter plan cost vs realised\n"
                                  "door-to-door personinfo duration",
                         "duarouter a-priori plan cost (min)",
                         "realised personinfo duration (min)")):
    lim = [0, max(ax.get_xlim()[1], ax.get_ylim()[1])]
    ax.plot(lim, lim, color=MUTED, lw=1.2, ls="--", zorder=0)
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel(xl); ax.set_ylabel(yl); ax.set_title(ttl)
    ax.grid(color=GRID, lw=0.6); ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
axes[0].text(0.97, 0.05, "1:1 line", transform=axes[0].transAxes, ha="right",
             color=MUTED, fontsize=7.5)
fig.suptitle("Skim validation against raw simulation output", fontsize=10.5)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "skim_validation.png"), dpi=170, bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------------------- decomposition
dec = EQ["hypotheses"]["H4"]["decomposition"]
groups = [("base", "low_income_peripheral"), ("base", "core_and_inner"),
          ("altA", "low_income_peripheral"), ("altB", "low_income_peripheral"),
          ("altB", "core_and_inner")]
fig, ax = plt.subplots(figsize=(8.4, 4.0))
ypos = list(range(len(groups)))[::-1]
for k, (scn, grp) in enumerate(groups):
    left = 0.0
    for c in COMP:
        v = dec[scn][grp]["seconds"][c] / 60.0
        ax.barh(ypos[k], v, left=left, height=0.56, color=COMP_COL[c],
                edgecolor="white", linewidth=1.4,
                label=COMP_LBL[c] if k == 0 else None)
        if v > 4.5:
            ax.text(left + v / 2, ypos[k], "%.0f" % v, ha="center", va="center",
                    fontsize=7.5, color="white")
        left += v
    ax.text(left + 1.0, ypos[k], "%.0f min total" % left, va="center", fontsize=8,
            color=INK)
ax.set_yticks(ypos)
ax.set_yticklabels(["%s\n%s" % (LABEL[s].split(":")[0], g.replace("_", " "))
                    for s, g in groups], fontsize=7.8)
ax.set_xlabel("mean door-to-door transit time by component (minutes)")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.legend(frameon=False, ncol=5, fontsize=7.6, loc="upper center",
          bbox_to_anchor=(0.5, 1.13))
ax.set_title("Where transit door-to-door time goes (H4)", pad=26)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "pt_time_decomposition.png"), dpi=170,
            bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------------------- free-flow trap
fig, ax = plt.subplots(figsize=(7.4, 4.0))
ths = AC["thresholds_min"]
ff = AC["freeflow_trap"]["base"]
xs = list(range(len(ths)))
ax.plot(xs, [ff["cum%d" % t]["popw_congested"] for t in ths], "-o", ms=5, lw=2,
        color=CAT["base"], label="congested skim (equilibrium)")
ax.plot(xs, [ff["cum%d" % t]["popw_freeflow"] for t in ths], "-o", ms=5, lw=2,
        color=CAT["altA"], label="free-flow skim")
for k, t in enumerate(ths):
    o = ff["cum%d" % t]["overstatement_pct"]
    if o and o > 1:
        ax.annotate("+%.0f%%" % o, xy=(xs[k], ff["cum%d" % t]["popw_freeflow"]),
                    xytext=(0, 7), textcoords="offset points", ha="center",
                    fontsize=7.5, color=CAT["altA"])
ax.set_xticks(xs); ax.set_xticklabels(["%d" % t for t in ths])
ax.set_xlabel("cumulative-opportunity threshold t* (minutes by car)")
ax.set_ylabel("population-weighted jobs reachable")
ax.set_title("The free-flow trap: how much a free-flow skim overstates accessibility\n"
             "(base scenario; labels = overstatement)")
ax.grid(color=GRID, lw=0.6); ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend(frameon=False, fontsize=8.5)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "freeflow_trap.png"), dpi=170, bbox_inches="tight")
plt.close(fig)
print("wrote figures to", OUTDIR)
