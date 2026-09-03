"""Generate every figure deliverable."""
import json
import os
from collections import defaultdict

import numpy as np

import wz_common as W
import plots
import analyze
import stats_util as S

ARMS = ["donothing", "early", "late", "dynamic", "vsl"]
MERGE = {"donothing": "priority", "early": "priority", "late": "zipper",
         "dynamic": "zipper", "vsl": "priority"}
p = W.params(lanes_closed=1)
g = W.geom(p)
NET = {a: W.build_net(p, "geom", merge=MERGE[a]) for a in ARMS}


def contours(peak=4000, seed=1):
    runs = {a: os.path.join(W.OUT, "control", f"lc1_{a}_q{peak}_s{seed}") for a in ARMS}
    runs = {k: v for k, v in runs.items() if os.path.exists(os.path.join(v, "e2.xml"))}
    nf = {k: NET[k] for k in runs}
    return plots.speed_contours(
        runs, nf, os.path.join(W.PLOTS, f"speed_contour_q{peak}.png"),
        wz_start=g["N4"], wz_end=g["N5"],
        title=f"Time-space speed contour by merge-control arm "
              f"(1 lane closed, peak {peak} veh/h, seed {seed}); "
              f"dashed = activity area")


def queues(peak=4000, seed=1):
    runs = {a: os.path.join(W.OUT, "control", f"lc1_{a}_q{peak}_s{seed}") for a in ARMS}
    runs = {k: v for k, v in runs.items()
            if os.path.exists(os.path.join(v, "e2_ctrl.xml"))}
    return plots.queue_series(
        runs, os.path.join(W.PLOTS, f"queue_series_q{peak}.png"),
        title=f"Upstream queue and network loading by arm (peak {peak} veh/h, seed {seed})")


def capacity_fig():
    rows = json.load(open(os.path.join(W.OUT, "capacity_probe", "probe_results.json")))
    gg = defaultdict(list)
    for r in rows:
        gg[(r["lanes_closed"], r["wz_speed"])].append(r["cap_per_lane"])
    labels = [("unobstructed\n3 lanes, 120 km/h", (0, 120)),
              ("speed only\n3 lanes, 80 km/h", (0, 80)),
              ("1 lane closed\n2 open, 80 km/h", (1, 80)),
              ("2 lanes closed\n1 open, 80 km/h", (2, 80))]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.0, 3.6), constrained_layout=True)
    xs = range(len(labels))
    ms = [S.mean_ci(gg[k]) for _, k in labels]
    ax.bar(xs, [m["mean"] for m in ms],
           yerr=[[m["mean"] - m["lo"] for m in ms], [m["hi"] - m["mean"] for m in ms]],
           color=["#4a7ebb", "#6fa8dc", "#e8a33d", "#c0504d"], capsize=3, width=0.62)
    # natural (merge-limited) work-zone discharge from the main capacity matrix
    cap = json.load(open(os.path.join(W.TABLES, "results_summary.json")))
    ax.axhline(analyze.HCM_WZ_REF, color="#333", ls="--", lw=1.2)
    ax.annotate("HCM freeway work-zone reference, 1600 pc/h/ln",
                (0.02, analyze.HCM_WZ_REF + 25), fontsize=7, color="#333")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([l for l, _ in labels], fontsize=7)
    ax.set_ylabel("queue-discharge capacity (pc/h/open lane)")
    ax.set_title("Measured segment queue-discharge capacity vs the HCM work-zone value",
                 fontsize=9)
    for x, m in zip(xs, ms):
        ax.annotate(f"{m['mean']:.0f}", (x, m["mean"] + 40), ha="center", fontsize=7.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, lw=0.5)
    out = os.path.join(W.PLOTS, "capacity_vs_hcm.png")
    fig.savefig(out, bbox_inches="tight", dpi=130)
    return out


def diversion_fig():
    rows = json.load(open(os.path.join(W.OUT, "diversion", "diversion_results.json")))
    gg = defaultdict(list)
    for r in rows:
        if r.get("ok"):
            gg[(r["peak"], r["phi"])].append(r)
    phis = sorted({k[1] for k in gg})
    series = {}
    for q in sorted({k[0] for k in gg}):
        m, lo, hi = [], [], []
        for ph in phis:
            c = S.mean_ci([x["TSTT_vh"] for x in gg[(q, ph)]])
            m.append(c["mean"])
            lo.append(c["lo"])
            hi.append(c["hi"])
        series[f"peak {q} veh/h"] = (m, lo, hi)
    f1 = plots.line_ci(phis, series, os.path.join(W.PLOTS, "diversion_tstt.png"),
                       "VMS/detour compliance share phi",
                       "corridor TSTT (vehicle-hours)",
                       "H4: corridor TSTT vs diversion share (inverted U at oversaturation)")
    # stacked decomposition at the oversaturated level
    q = max({k[0] for k in gg})
    comps = {}
    for lab, key in (("freeway", "vh_freeway"), ("ramps", "vh_ramp"),
                     ("detour arterial", "vh_detour"), ("internal", "vh_internal"),
                     ("origin insertion", "vh_origin")):
        comps[lab] = [float(np.mean([x[key] for x in gg[(q, ph)]])) for ph in phis]
    f2 = plots.stacked_tstt(phis, comps, os.path.join(W.PLOTS, "diversion_decomp.png"),
                            "compliance share phi",
                            f"TSTT decomposition vs diversion share (peak {q} veh/h)")
    return f1, f2


def arm_tstt_fig():
    rows = json.load(open(os.path.join(W.OUT, "control", "control_results_lc1.json")))
    gg = defaultdict(list)
    for r in rows:
        if r.get("ok"):
            gg[(r["peak"], r["arm"])].append(r)
    demands = sorted({k[0] for k in gg})
    series = {}
    for a in ARMS:
        m, lo, hi = [], [], []
        for q in demands:
            c = S.mean_ci([x["TSTT_vh"] for x in gg[(q, a)]])
            m.append(c["mean"])
            lo.append(c["lo"])
            hi.append(c["hi"])
        series[a] = (m, lo, hi)
    return plots.line_ci(demands, series, os.path.join(W.PLOTS, "arm_tstt.png"),
                         "mainline peak demand (veh/h)", "TSTT (vehicle-hours)",
                         "Merge-control arms: corridor TSTT vs demand (1 lane closed)")


if __name__ == "__main__":
    outs = []
    for fn in (capacity_fig,):
        try:
            outs.append(fn())
        except Exception as e:
            print("skip", fn.__name__, e)
    for q in (3200, 4000, 4400):
        for fn in (contours, queues):
            try:
                outs.append(fn(q))
            except Exception as e:
                print("skip", fn.__name__, q, e)
    for fn in (diversion_fig, arm_tstt_fig):
        try:
            r = fn()
            outs.extend(r if isinstance(r, tuple) else [r])
        except Exception as e:
            print("skip", fn.__name__, e)
    for o in outs:
        print(o)
