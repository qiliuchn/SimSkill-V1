#!/usr/bin/env python3
"""Application: widen the sidewalk bottleneck vs. re-time the pedestrian signal,
plus the Fruin LOS map, the pedestrian time-space diagram, and the reverse
coupling onto vehicle throughput.  Also H5 (pedestrian model choice).

The retiming arm is zero-sum at a fixed 90 s cycle, so extra pedestrian green is
paid for out of the crossed street's vehicle green -- the decision rule that comes
out of it therefore prices both sides of the trade.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.colors import ListedColormap, BoundaryNorm   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_util import mean_ci, paired_diff   # noqa: E402

LOS_COLORS = ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"]
LOS_NAMES = list("ABCDEF")
LOS_EDGES = [0, 0.3086, 0.4310, 0.7194, 1.0753, 2.1739, 6.0]


def cell(res, key):
    g = {}
    for name, r in res.items():
        g.setdefault(key(r), []).append(r)
    for k in g:
        g[k].sort(key=lambda r: r["config"]["seed"])
    return g


def stat(ms):
    return {
        "n_seeds": len(ms),
        "clearance_p95": mean_ci([m["clearance"]["clearance_p95"] for m in ms]),
        "clearance_p100": mean_ci([m["clearance"]["clearance_p100"] for m in ms]),
        "mean_egress_duration": mean_ci([m["clearance"]["mean_egress_duration_s"] for m in ms]),
        "mean_walk_speed": mean_ci([m["clearance"]["mean_walk_speed_ms"] for m in ms]),
        "veh_timeloss": mean_ci([m["vehicles"]["mean_veh_timeloss_s"] for m in ms]),
        "veh_completed": mean_ci([float(m["vehicles"]["n_vehicles_completed"]) for m in ms]),
        "peak_density": mean_ci([max((p["peak_density"] for p in m["los_profile"]), default=0)
                                 for m in ms]),
        "completed": mean_ci([float(m["accounting"]["completed"]) for m in ms]),
        "still_walking": mean_ci([float(m["accounting"]["still_walking_at_end"]) for m in ms]),
        "veh_teleports": mean_ci([float(m["accounting"]["vehicle_teleports"]) for m in ms]),
        "person_teleports": mean_ci([float(m["accounting"]["person_teleports"]) for m in ms]),
        "jam_events_per_person": mean_ci([m["person_summary"]["jam_events_per_inserted_person"] for m in ms]),
        "jam_events_total": mean_ci([float(m["person_summary"]["jam_events_total"]) for m in ms]),
        "collisions": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--h5", required=True)
    ap.add_argument("--veh-baseline", required=True)
    ap.add_argument("--h5-reduced")
    ap.add_argument("--losmap", required=True, help="losmap.csv of the reference run")
    ap.add_argument("--traj", required=True, help="traj.json of the reference run")
    ap.add_argument("--ref-result", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--plots", required=True)
    a = ap.parse_args()
    os.makedirs(a.plots, exist_ok=True)

    app = json.load(open(a.app))["results"]
    grid = cell(app, lambda r: (r["config"]["w_bottleneck"], r["config"]["ped_green"]))
    widths = sorted(set(w for w, _ in grid))
    greens = sorted(set(g for _, g in grid))
    out = {"grid": {}, "widths": widths, "ped_greens": greens}
    for (w, g), ms in sorted(grid.items()):
        out["grid"]["w%g_g%d" % (w, g)] = dict(w_bottleneck=w, ped_green=g, **stat(ms))

    # ---- marginal effects: widening vs retiming, each from the same base cell ----
    def m95(w, g):
        return out["grid"]["w%g_g%d" % (w, g)]["clearance_p95"]["mean"]

    marg = {"widen": [], "retime": []}
    for g in greens:
        for w1, w2 in zip(widths, widths[1:]):
            marg["widen"].append({"ped_green": g, "from_w": w1, "to_w": w2,
                                  "d_p95_s": m95(w2, g) - m95(w1, g),
                                  "rel_pct": 100 * (m95(w2, g) - m95(w1, g)) / m95(w1, g)})
    for w in widths:
        for g1, g2 in zip(greens, greens[1:]):
            marg["retime"].append({"w_bottleneck": w, "from_g": g1, "to_g": g2,
                                   "d_p95_s": m95(w, g2) - m95(w, g1),
                                   "rel_pct": 100 * (m95(w, g2) - m95(w, g1)) / m95(w, g1),
                                   "d_veh_timeloss_s":
                                       out["grid"]["w%g_g%d" % (w, g2)]["veh_timeloss"]["mean"] -
                                       out["grid"]["w%g_g%d" % (w, g1)]["veh_timeloss"]["mean"]})
    out["marginal_effects"] = marg

    # CRN paired tests of the two single-step interventions from the base design
    base_w, base_g = 2.0, 20
    wider = [m["clearance"]["clearance_p95"] for m in grid[(4.0, base_g)]]
    basec = [m["clearance"]["clearance_p95"] for m in grid[(base_w, base_g)]]
    longer = [m["clearance"]["clearance_p95"] for m in grid[(base_w, 40)]]
    out["paired_tests_from_base_w2_g20"] = {
        "widen_2m_to_4m": paired_diff(wider, basec),
        "retime_20s_to_40s": paired_diff(longer, basec),
    }

    # ---- binding-constraint diagnosis -----------------------------------------
    # If the sidewalk is binding, widening helps and extra green does little.
    # If the crossing is binding, extra green helps and widening does little.
    diag = []
    for g in greens:
        gains = [100 * (m95(widths[0], g) - m95(w, g)) / m95(widths[0], g) for w in widths]
        diag.append({"ped_green": g, "p95_by_width": [m95(w, g) for w in widths],
                     "max_widening_gain_pct": max(gains),
                     "saturating_width_m": widths[int(np.argmax(gains))]})
    out["widening_diagnosis"] = diag
    diag2 = []
    for w in widths:
        gains = [100 * (m95(w, greens[0]) - m95(w, g)) / m95(w, greens[0]) for g in greens]
        diag2.append({"w_bottleneck": w, "p95_by_green": [m95(w, g) for g in greens],
                      "max_retiming_gain_pct": max(gains)})
    out["retiming_diagnosis"] = diag2

    # ---- reverse coupling: vehicle cost of the pedestrian surge ---------------
    vb = json.load(open(a.veh_baseline))["results"]
    vbg = cell(vb, lambda r: r["config"]["ped_green"])
    out["reverse_coupling"] = {}
    for g in greens:
        base_tl = mean_ci([m["vehicles"]["mean_veh_timeloss_s"] for m in vbg[g]])
        base_n = mean_ci([float(m["vehicles"]["n_vehicles_completed"]) for m in vbg[g]])
        surge = out["grid"]["w%g_g%d" % (3.0, g)]
        out["reverse_coupling"]["g%d" % g] = {
            "veh_timeloss_no_surge": base_tl, "veh_timeloss_with_surge": surge["veh_timeloss"],
            "delta_s": surge["veh_timeloss"]["mean"] - base_tl["mean"],
            "pct": 100 * (surge["veh_timeloss"]["mean"] - base_tl["mean"]) / base_tl["mean"],
            "veh_completed_no_surge": base_n, "veh_completed_with_surge": surge["veh_completed"],
            "throughput_delta_veh": surge["veh_completed"]["mean"] - base_n["mean"],
        }

    # ---- H5: model choice ------------------------------------------------------
    h5 = json.load(open(a.h5))["results"]
    h5g = cell(h5, lambda r: (r["config"]["model"], r["config"]["w_bottleneck"],
                              r["config"]["ped_green"]))
    out["h5"] = {}
    for (mo, w, g), ms in sorted(h5g.items()):
        out["h5"]["%s_w%g_g%d" % (mo, w, g)] = dict(model=mo, w=w, g=g, **stat(ms))
    out["h5_errors_vs_striping"] = {}
    for (mo, w, g) in h5g:
        if mo == "striping":
            continue
        ref = h5g[("striping", w, g)]
        alt = h5g[(mo, w, g)]
        def rel(f):
            r = sum(f(m) for m in ref) / len(ref)
            v = sum(f(m) for m in alt) / len(alt)
            return {"striping": r, mo: v, "abs_error": v - r,
                    "pct_error": 100 * (v - r) / r if r else float("nan")}
        out["h5_errors_vs_striping"]["%s_w%g_g%d" % (mo, w, g)] = {
            "clearance_p95": rel(lambda m: m["clearance"]["clearance_p95"]),
            "clearance_p100": rel(lambda m: m["clearance"]["clearance_p100"]),
            "mean_walk_speed": rel(lambda m: m["clearance"]["mean_walk_speed_ms"]),
            "peak_density": rel(lambda m: max((p["peak_density"] for p in m["los_profile"]),
                                              default=0)),
            "veh_timeloss": rel(lambda m: m["vehicles"]["mean_veh_timeloss_s"]),
        }

    # ---- H5 three-way at reduced scale, the only scale jupedsim can reach ------
    if a.h5_reduced:
        hr = json.load(open(a.h5_reduced))["results"]
        hrg = cell(hr, lambda r: r["config"]["model"])
        out["h5_reduced"] = {m: stat(ms) for m, ms in hrg.items()}
        ref = hrg["striping"]
        out["h5_reduced_errors_vs_striping"] = {}
        for mo, ms in hrg.items():
            if mo == "striping":
                continue
            def rel(f):
                r = sum(f(m) for m in ref) / len(ref)
                v = sum(f(m) for m in ms) / len(ms)
                return {"striping": r, mo: v, "abs_error": v - r,
                        "pct_error": 100 * (v - r) / r if r else float("nan")}
            out["h5_reduced_errors_vs_striping"][mo] = {
                "clearance_p95": rel(lambda m: m["clearance"]["clearance_p95"]),
                "clearance_p100": rel(lambda m: m["clearance"]["clearance_p100"]),
                "mean_egress_duration": rel(lambda m: m["clearance"]["mean_egress_duration_s"]),
                "mean_walk_speed": rel(lambda m: m["clearance"]["mean_walk_speed_ms"]),
                "peak_density": rel(lambda m: max((p["peak_density"] for p in m["los_profile"]),
                                                  default=0)),
                "veh_timeloss": rel(lambda m: m["vehicles"]["mean_veh_timeloss_s"]),
                "vehicle_teleports": rel(lambda m: float(m["accounting"]["vehicle_teleports"])),
            }
        out["h5_reduced_validity"] = {
            m: {"vehicle_teleports": out["h5_reduced"][m]["veh_teleports"]["mean"],
                "vehicles_completed": out["h5_reduced"][m]["veh_completed"]["mean"],
                "teleport_share_of_completed_vehicles_pct":
                    100 * out["h5_reduced"][m]["veh_teleports"]["mean"]
                    / max(out["h5_reduced"][m]["veh_completed"]["mean"], 1),
                "persons_completed": out["h5_reduced"][m]["completed"]["mean"]}
            for m in out["h5_reduced"]}

    json.dump(out, open(a.out_json, "w"), indent=2)

    # =============================== plots ====================================
    # 1. widen-vs-retime heat map + curves
    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    M = np.array([[m95(w, g) for g in greens] for w in widths])
    im = ax[0].imshow(M, origin="lower", aspect="auto", cmap="viridis_r")
    ax[0].set_xticks(range(len(greens))); ax[0].set_xticklabels(greens)
    ax[0].set_yticks(range(len(widths))); ax[0].set_yticklabels(widths)
    ax[0].set_xlabel("pedestrian green [s] (of a fixed 90 s cycle)")
    ax[0].set_ylabel("sidewalk bottleneck width [m]")
    ax[0].set_title("95% egress clearance time [s]")
    for i in range(len(widths)):
        for j in range(len(greens)):
            ax[0].text(j, i, "%.0f" % M[i, j], ha="center", va="center",
                       color="w" if M[i, j] > M.mean() else "k", fontsize=8)
    fig.colorbar(im, ax=ax[0])

    for j, g in enumerate(greens):
        ax[1].plot(widths, M[:, j], "o-", label="ped green %d s" % g)
    ax[1].set_xlabel("sidewalk bottleneck width [m]"); ax[1].set_ylabel("95% clearance [s]")
    ax[1].set_title("Widening the sidewalk"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
    for i, w in enumerate(widths):
        ax[2].plot(greens, M[i, :], "s-", label="width %g m" % w)
    ax[2].set_xlabel("pedestrian green [s]"); ax[2].set_ylabel("95% clearance [s]")
    ax[2].set_title("Re-timing the crossing"); ax[2].legend(fontsize=8); ax[2].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plots, "app_widen_vs_retime.png"), dpi=140)

    # 2. LOS map + time-space diagram
    rows = list(csv.DictReader(open(a.losmap)))
    xs = sorted(set(float(r["x"]) for r in rows))
    ts = sorted(set(float(r["t"]) for r in rows))
    K = np.full((len(xs), len(ts)), np.nan)
    xi = {v: i for i, v in enumerate(xs)}
    ti = {v: i for i, v in enumerate(ts)}
    for r in rows:
        if int(r["n_samples"]) > 0:
            K[xi[float(r["x"])], ti[float(r["t"])]] = float(r["density_p_m2"])
    ref = json.load(open(a.ref_result))
    cyc = ref["net_verification"]["cycle_s"]
    pg = ref["net_verification"]["ped_green_s"]
    wb = ref["config"]["w_bottleneck"]

    fig2, ax2 = plt.subplots(1, 2, figsize=(15.5, 6))
    cmap = ListedColormap(LOS_COLORS)
    norm = BoundaryNorm(LOS_EDGES, cmap.N)
    im = ax2[0].pcolormesh(np.array(ts), np.array(xs), K, cmap=cmap, norm=norm, shading="nearest")
    cb = fig2.colorbar(im, ax=ax2[0], ticks=[(LOS_EDGES[i] + LOS_EDGES[i + 1]) / 2 for i in range(6)])
    cb.ax.set_yticklabels(["LOS " + n for n in LOS_NAMES])
    ax2[0].axhline(-60, color="k", lw=1.2, ls="--")
    ax2[0].axhline(0, color="k", lw=1.2, ls="--")
    ax2[0].text(ax2[0].get_xlim()[1] * .02, -150, "plaza  12 m", fontsize=8)
    ax2[0].text(ax2[0].get_xlim()[1] * .02, -35, "bottleneck %g m" % wb, fontsize=8)
    ax2[0].text(ax2[0].get_xlim()[1] * .02, 30, "far side  4 m", fontsize=8)
    ax2[0].set_xlabel("time [s]"); ax2[0].set_ylabel("distance along egress path [m]")
    ax2[0].set_title("Fruin LOS map (density, Edie cells 10 m x 30 s)\n"
                     "bottleneck %g m, ped green %.0f s of %.0f s cycle" % (wb, pg, cyc))

    trj = json.load(open(a.traj))
    for i, (pid, pts) in enumerate(sorted(trj.items())):
        t = [p[0] for p in pts]
        x = [p[1] for p in pts]
        ax2[1].plot(t, x, lw=.6, alpha=.7, color="#2b6cb0")
    tmax = max(max(p[0] for p in v) for v in trj.values())
    n_cyc = int(tmax / cyc) + 1
    for c in range(n_cyc):
        t0 = c * cyc + (cyc - pg - 2)          # phase 2 (ped green) starts after veh+yellow
        ax2[1].axvspan(t0, t0 + pg, color="#48bb78", alpha=.20, lw=0)
    ax2[1].axhline(-60, color="k", lw=1, ls="--")
    ax2[1].axhline(0, color="r", lw=1.2, ls="-")
    ax2[1].set_xlabel("time [s]"); ax2[1].set_ylabel("distance along egress path [m]")
    ax2[1].set_title("Pedestrian time-space diagram\n(green bands = crossing walk phase, "
                     "red line = the signalised crossing)")
    ax2[1].set_xlim(0, min(tmax, 1600))
    fig2.tight_layout()
    fig2.savefig(os.path.join(a.plots, "app_los_and_timespace.png"), dpi=140)

    # 3. H5 model comparison
    fig3, ax3 = plt.subplots(1, 3, figsize=(16, 4.4))
    keys = sorted(set((w, g) for _, w, g in h5g))
    models = ["striping", "nonInteracting", "jupedsim"]
    mcol = {"striping": "#2b6cb0", "nonInteracting": "#c53030", "jupedsim": "#2f855a"}
    metrics = [("clearance_p95", "95% clearance [s]"),
               ("mean_walk_speed", "mean walk speed [m/s]"),
               ("peak_density", "peak density [P/m$^2$]")]
    for ai, (mk, lab) in enumerate(metrics):
        xpos = np.arange(len(keys))
        for k, mo in enumerate(models):
            ys, es = [], []
            for (w, g) in keys:
                key = "%s_w%g_g%d" % (mo, w, g)
                if key in out["h5"]:
                    ys.append(out["h5"][key][mk]["mean"]); es.append(out["h5"][key][mk]["ci_half"] or 0)
                else:
                    ys.append(np.nan); es.append(0)
            ax3[ai].bar(xpos + (k - 1) * .27, ys, .26, yerr=es, capsize=2,
                        color=mcol[mo], label=mo)
        ax3[ai].set_xticks(xpos)
        ax3[ai].set_xticklabels(["W=%gm\ngreen=%ds" % k for k in keys], fontsize=8)
        ax3[ai].set_ylabel(lab); ax3[ai].grid(alpha=.3, axis="y")
        if ai == 0:
            ax3[ai].legend(fontsize=8)
    fig3.suptitle("H5: what the non-congesting pedestrian model throws away")
    fig3.tight_layout()
    fig3.savefig(os.path.join(a.plots, "h5_model_choice.png"), dpi=140)

    print("clearance p95 grid (rows=width, cols=ped green):")
    print("        " + "".join("%9d" % g for g in greens))
    for i, w in enumerate(widths):
        print("W=%4.1f  " % w + "".join("%9.0f" % M[i, j] for j in range(len(greens))))
    print()
    print(json.dumps(out["h5_errors_vs_striping"], indent=1))


if __name__ == "__main__":
    main()
