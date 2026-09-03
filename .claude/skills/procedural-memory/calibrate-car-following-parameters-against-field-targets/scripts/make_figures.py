#!/usr/bin/env python3
"""Deliverable figures:
  fig1_fd_overlay_<model>.png  -- measured FD (ring) default vs calibrated vs
                                  target triangle, plus the freeway station points
  fig2_morris_<model>.png      -- Morris mu*/sigma screening plot
  fig3_equifinality.png        -- macro-tied candidates that differ microscopically
  fig4_convergence.png         -- GA vs multistart-NM convergence / budget
"""
import os, sys, json, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import OUT, TARGETS, full_params, fd_probe, RING_CELLS, ring_cell, RUNS
from concurrent.futures import ProcessPoolExecutor

TB = os.path.join(OUT, "tables"); FG = os.path.join(OUT, "figs")
os.makedirs(FG, exist_ok=True)
C = dict(default="#c0392b", calib="#2471a3", target="#117a4a", fwy="#8e44ad")
plt.rcParams.update({"figure.dpi": 130, "font.size": 8.5,
                     "axes.grid": True, "grid.alpha": 0.25})


def _cell(a):
    model, p, k, tag, seed = a
    return k, ring_cell(os.path.join(RUNS, "fig", tag, "k%d" % k), model, p, k, seed=seed)


def ring_curve(model, p, tag, seed=42):
    jobs = [(model, p, k, tag, seed) for k in RING_CELLS]
    with ProcessPoolExecutor(max_workers=9) as ex:
        out = sorted(ex.map(_cell, jobs), key=lambda x: x[0])
    return [c for _, c in out if c.get("ok")]


def target_triangle():
    t = {k: v["target"] for k, v in TARGETS.items()}
    kk = np.array([0, t["k_crit"], t["k_jam"]])
    qq = np.array([0, t["q_max"], 0])
    return kk, qq, t


def fig1():
    fv = json.load(open(os.path.join(TB, "freeway_validation.json")))
    for model in ("Krauss", "IDM"):
        c = json.load(open(os.path.join(TB, "calib_%s_main.json" % model)))
        best = "ga" if c["ga"]["best_obj"] <= c["nm"]["best_obj"] else "nm"
        pd_ = full_params(model)
        pc_ = full_params(model, c["%s_best_params" % best])
        cd = ring_curve(model, pd_, "%s_def" % model)
        cc = ring_curve(model, pc_, "%s_cal" % model)
        kt, qt, T = target_triangle()
        fig, ax = plt.subplots(1, 3, figsize=(11.5, 3.4))
        for a, (xk, yk, xl, yl) in zip(ax, [("k", "q", "density k (veh/km/ln)", "flow q (veh/h/ln)"),
                                            ("k", "v_kmh", "density k (veh/km/ln)", "space-mean speed (km/h)"),
                                            ("v_kmh", "q", "space-mean speed (km/h)", "flow q (veh/h/ln)")]):
            a.plot([x[xk] for x in cd], [x[yk] for x in cd], "o-", ms=3.5, lw=1.2,
                   color=C["default"], label="SUMO default")
            a.plot([x[xk] for x in cc], [x[yk] for x in cc], "s-", ms=3.5, lw=1.2,
                   color=C["calib"], label="calibrated")
            a.set_xlabel(xl); a.set_ylabel(yl)
        ax[0].plot(kt, qt, "--", lw=1.6, color=C["target"], label="empirical target FD")
        ax[0].plot([T["k_crit"]], [T["q_max"]], "*", ms=13, color=C["target"])
        # freeway station points (open road, same vType)
        for name, mk, lab in (("default", "^", "freeway (default)"),
                              ("calibrated", "v", "freeway (calibrated)")):
            key = "%s_%s" % (model, name)
            if key in fv:
                pts = [x for x in fv[key]["sweep"] if x.get("ok")]
                ax[0].plot([x["k_occ_per_lane"] for x in pts],
                           [x["q_per_lane"] for x in pts], mk, ms=4.5,
                           color=C["fwy"], alpha=0.65, label=lab)
        ax[0].legend(fontsize=6.5, loc="upper right")
        ax[1].axhline(T["v_free_kmh"], ls="--", lw=1.2, color=C["target"])
        ax[1].axvline(T["k_jam"], ls=":", lw=1.0, color=C["target"])
        fig.suptitle("%s: fundamental diagram - default vs calibrated vs empirical target "
                     "(ring instrument; triangles = open freeway station)" % model, fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(FG, "fig1_fd_overlay_%s.png" % model))
        plt.close(fig)
        print("fig1", model)


def fig2():
    for model in ("Krauss", "IDM"):
        M = json.load(open(os.path.join(TB, "morris_%s.json" % model)))
        keys = ["obj", "v_free_kmh", "q_max", "k_crit", "k_jam", "w_kmh"]
        fig, ax = plt.subplots(2, 3, figsize=(11.5, 6))
        for a, q in zip(ax.ravel(), keys):
            rows = M["table"][q]
            for r in rows:
                a.scatter(r["mu_star"], r["sigma"], s=26,
                          color="#c0392b" if r == rows[0] else "#2471a3")
                a.annotate(r["param"], (r["mu_star"], r["sigma"]), fontsize=6,
                           xytext=(3, 2), textcoords="offset points")
            lim = max([r["mu_star"] for r in rows] + [r["sigma"] for r in rows]) * 1.15 + 1e-6
            a.plot([0, lim], [0, lim], ":", lw=0.8, color="grey")
            a.set_xlim(0, lim); a.set_ylim(0, lim)
            a.set_title(q, fontsize=8); a.set_xlabel("mu* (influence)")
            a.set_ylabel("sigma (interaction)")
        fig.suptitle("%s: Morris elementary-effects screening (r=%d trajectories, "
                     "%d evaluations)" % (model, M["r"], M["n_eval"]), fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(FG, "fig2_morris_%s.png" % model)); plt.close(fig)
        print("fig2", model)


def fig3():
    H = json.load(open(os.path.join(TB, "H3_equifinality.json")))
    fig, ax = plt.subplots(2, 2, figsize=(9.5, 6.4))
    for row, model in enumerate(("Krauss", "IDM")):
        o = H[model]; cs = o["candidates"]
        x = np.arange(len(cs))
        a = ax[row, 0]
        a.errorbar(x, [c["obj_mean"] for c in cs], yerr=[c["obj_ci"] for c in cs],
                   fmt="o", color=C["calib"], capsize=3)
        a.axhline(o["best_obj"], ls="--", color="grey", lw=1)
        a.set_title("%s: MACRO objective (8-seed CRN, 95%% CI)" % model, fontsize=8)
        a.set_xlabel("candidate #"); a.set_ylabel("weighted RMSN")
        a2 = ax[row, 1]
        h = [c["micro"].get("headway_p50", np.nan) for c in cs]
        cv = [c["micro"].get("headway_cv", np.nan) for c in cs]
        a2.bar(x - 0.2, h, 0.4, color="#e67e22", label="median time headway (s)")
        a2.bar(x + 0.2, cv, 0.4, color="#16a085", label="headway CV")
        a2.axhline(o["micro_target"]["target"], ls="--", color=C["target"], lw=1.2)
        a2.set_title("%s: MICROscopic signature (same candidates)" % model, fontsize=8)
        a2.set_xlabel("candidate #"); a2.legend(fontsize=6.5)
    fig.suptitle("Equifinality: parameter vectors statistically tied on the macroscopic "
                 "objective diverge microscopically", fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(FG, "fig3_equifinality.png"))
    plt.close(fig); print("fig3")


def fig4():
    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.4))
    for i, model in enumerate(("Krauss", "IDM")):
        c = json.load(open(os.path.join(TB, "calib_%s_main.json" % model)))
        h = c["ga"]["history"]
        ax[i].plot([x["n_eval"] for x in h], [x["best"] for x in h], "-o", ms=3,
                   color=C["calib"], label="GA best-so-far")
        ax[i].plot([x["n_eval"] for x in h], [x["mean"] for x in h], "--", lw=1,
                   color="#95a5a6", label="GA generation mean")
        ax[i].axhline(c["nm"]["best_obj"], ls="-.", color="#e67e22",
                      label="multistart NM best (%d evals)" % c["nm"]["n_eval"])
        ax[i].set_yscale("log"); ax[i].set_xlabel("simulation evaluations")
        ax[i].set_ylabel("weighted RMSN"); ax[i].legend(fontsize=6.5)
        ax[i].set_title("%s  (GA %.0fs / NM %.0fs wall)"
                        % (model, c["ga"]["wall_s"], c["nm"]["wall_s"]), fontsize=8)
    fig.suptitle("Optimiser comparison: convergence vs evaluation budget", fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(FG, "fig4_convergence.png"))
    plt.close(fig); print("fig4")


if __name__ == "__main__":
    for f in (sys.argv[1:] or ["fig1", "fig2", "fig3", "fig4"]):
        globals()[f]()
