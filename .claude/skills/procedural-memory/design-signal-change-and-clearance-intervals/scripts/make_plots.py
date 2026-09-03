"""Deliverable figures: decision curves, stop/go probability with analytic boundaries,
safety-capacity Pareto frontier, all-red exchange rate, lost-time comparison."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from common import ANA_DIR, FIG_DIR  # noqa: E402
import analytic  # noqa: E402

C = dict(blue="#3b6ea5", orange="#d1743a", green="#4a8b62", red="#b5423b",
         purple="#7a5c9e", grey="#7a7f87", dark="#2b2f36")
SPEED_C = {13.89: C["blue"], 19.44: C["orange"], 25.0: C["red"]}


def style(ax, title=None, xl=None, yl=None):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, alpha=0.25, linewidth=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=10.5, loc="left")
    if xl:
        ax.set_xlabel(xl, fontsize=9.5)
    if yl:
        ax.set_ylabel(yl, fontsize=9.5)
    ax.tick_params(labelsize=8.5)


def eb(ax, xs, ms, hs, **kw):
    hs = [h if h is not None else 0.0 for h in hs]
    ax.errorbar(xs, ms, yerr=hs, capsize=3, marker="o", markersize=4.5, linewidth=1.6, **kw)


def fig_decision_curve(res):
    """RLR rate and rear-end conflict rate vs yellow length."""
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.6))
    for col, drv in enumerate(("DEF", "ITE")):
        for row, (metric, lab) in enumerate((
                ("rlr_per_1000_veh", "Red-light running (per 1000 veh)"),
                ("rear_ttc15_per_1000_veh", "Rear-end conflicts TTC<1.5 s (per 1000 veh)"))):
            ax = axes[row][col]
            for v in (13.89, 19.44, 25.0):
                k = "%s|v=%.2f|low" % (drv, v)
                if k not in res["H2"]:
                    continue
                sq = res["H2"][k]["series"][metric]
                xs = [y for y, a in sq]
                ms = [a["mean"] for y, a in sq]
                hs = [a["hw"] for y, a in sq]
                eb(ax, xs, ms, hs, color=SPEED_C[v], label="%.0f km/h" % (v * 3.6))
                yite = analytic.ite_yellow(v)
                ax.axvline(yite, color=SPEED_C[v], linestyle=":", linewidth=1.2, alpha=0.7)
            style(ax, "%s driver model - %s" % (drv, lab), "yellow interval y (s)", lab)
            if row == 0 and col == 0:
                ax.legend(fontsize=8, frameon=False, title="approach speed",
                          title_fontsize=8)
    fig.suptitle("Decision curve: red-light running and rear-end conflicts vs yellow length\n"
                 "(dotted verticals = ITE-formula yellow for that speed; bars = 95% CI over "
                 "6 CRN replications)", fontsize=10.5, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(os.path.join(FIG_DIR, "fig1_decision_curve.png"), dpi=150)
    plt.close(fig)


def fig_stopgo(res):
    """Empirical stop/go probability vs distance, overlaid with analytic x_s / x_c."""
    keys = [("DEF", 19.44, 3.0), ("ITE", 19.44, 3.0), ("DEF", 25.0, 2.0), ("ITE", 25.0, 2.0),
            ("DEF", 25.0, 5.0), ("ITE", 25.0, 5.0)]
    fig, axes = plt.subplots(3, 2, figsize=(11, 10))
    for ax, (drv, v, y) in zip(axes.ravel(), keys):
        k = "%s|v=%.2f|y=%.1f" % (drv, v, y)
        d = res["stopgo_curves"].get(k)
        if not d:
            style(ax, k + " (no data)")
            continue
        cur = [c for c in d["curve"] if c["n"] >= 5]
        xs = [c["d_mid"] for c in cur]
        ps = [c["p_go"] for c in cur]
        lo = [c["ci_lo"] for c in cur]
        hi = [c["ci_hi"] for c in cur]
        ax.fill_between(xs, lo, hi, color=C["blue"], alpha=0.18, linewidth=0)
        ax.plot(xs, ps, color=C["blue"], linewidth=1.8, marker="o", markersize=3,
                label="empirical P(go)")
        ax.axvline(d["x_c_stopline"], color=C["green"], linestyle="--", linewidth=1.5,
                   label="$x_c = v\\cdot y$ = %.0f m" % d["x_c_stopline"])
        ax.axvline(d["x_s_sumo_kinematic"], color=C["orange"], linestyle="-.", linewidth=1.5,
                   label="$x_s^{SUMO}=v^2/2a$ = %.0f m" % d["x_s_sumo_kinematic"])
        ax.axvline(d["x_s_ite"], color=C["red"], linestyle=":", linewidth=1.8,
                   label="$x_s^{ITE}$ (PRT 1 s, a=3.05) = %.0f m" % d["x_s_ite"])
        iz = d["indecision"]
        if iz["lo"] is not None:
            ax.axvspan(iz["lo"], iz["hi"], color=C["purple"], alpha=0.13, linewidth=0)
        az = d["analytic_zone_ite"]
        ax.axvspan(min(az["x_s"], az["x_c"]), max(az["x_s"], az["x_c"]),
                   color=C["red"], alpha=0.06, linewidth=0)
        ax.set_ylim(-0.04, 1.04)
        style(ax, "%s | v=%.0f km/h | y=%.1f s  (analytic-ITE zone: %s, %.0f m wide)"
              % (drv, v * 3.6, y, az["zone_type"], az["zone_width"]),
              "distance to stop line at yellow onset (m)", "P(proceed)")
        ax.legend(fontsize=7, frameon=False, loc="center right")
    fig.suptitle("Empirical stop/go probability vs distance, with analytic boundaries\n"
                 "shaded purple = measured indecision zone (0.05<P<0.95); shaded red = "
                 "analytic ITE dilemma/option zone", fontsize=10.5, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(os.path.join(FIG_DIR, "fig2_stopgo_curve.png"), dpi=150)
    plt.close(fig)


def fig_pareto(res):
    """Safety-capacity Pareto frontier over (yellow, all-red)."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    ax = axes[0]
    for v in (13.89, 19.44, 25.0):
        k = "ITE|v=%.2f|high" % v
        pts = res["pareto_A"].get(k) or res["pareto_A"].get("ITE|v=%.2f|low" % v)
        if not pts:
            continue
        xs = [p["timeloss"] for p in pts]
        ys = [(p["safety_rlr"] or 0) + (p["safety_overlap"] or 0) for p in pts]
        ax.plot(xs, ys, "-o", color=SPEED_C[v], markersize=5, linewidth=1.5,
                label="%.0f km/h" % (v * 3.6))
        for p, x, yv in zip(pts, xs, ys):
            ax.annotate("y=%.0f" % p["y"], (x, yv), fontsize=7,
                        textcoords="offset points", xytext=(4, 4), color=C["dark"])
    style(ax, "(a) Yellow sweep at all-red = 1 s (ITE driver model, saturated demand)",
          "mean time loss per vehicle (s)  [capacity cost]",
          "RLR + right-angle overlap per 1000 veh  [safety cost]")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    mk = {2: "o", 4: "s"}
    for key, pts in sorted(res["pareto_B"].items()):
        v = float(key.split("|")[0].split("=")[1])
        lanes = int(key.split("lanes=")[1])
        xs = [p["timeloss"] for p in pts]
        ys = [p["overlap"] for p in pts]
        ax.plot(xs, ys, "-", color=SPEED_C.get(v, C["grey"]), linewidth=1.4,
                marker=mk[lanes], markersize=5,
                label="%.0f km/h, %d lanes" % (v * 3.6, lanes))
        for p, x, yv in zip(pts, xs, ys):
            ax.annotate("ar=%.0f" % p["ar"], (x, yv), fontsize=7,
                        textcoords="offset points", xytext=(4, 4), color=C["dark"])
    style(ax, "(b) All-red sweep at the ITE yellow",
          "mean time loss per vehicle (s)", "right-angle overlap events per 1000 veh")
    ax.legend(fontsize=8, frameon=False)
    fig.suptitle("Safety-capacity Pareto frontier over (yellow, all-red)",
                 fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(FIG_DIR, "fig3_pareto.png"), dpi=150)
    plt.close(fig)


def fig_allred(res):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
    for key, row in sorted(res["H4"].items()):
        v = float(key.split("|")[0].split("=")[1])
        lanes = int(key.split("lanes=")[1])
        lab = "%.0f km/h, W=%.1f m" % (v * 3.6, row["W"])
        ls = "-" if lanes == 2 else "--"
        for ax, m, yl in ((axes[0], "overlap_per_1000_veh",
                           "right-angle overlaps / 1000 veh"),
                          (axes[1], "mean_timeloss", "mean time loss (s)"),
                          (axes[2], "completed", "vehicles completed")):
            sq = row["series"][m]
            eb(ax, [a for a, _ in sq], [b["mean"] for _, b in sq],
               [b["hw"] for _, b in sq], color=SPEED_C.get(v, C["grey"]),
               linestyle=ls, label=lab)
            style(ax, None, "all-red duration (s)", yl)
    for key, row in sorted(res["H4"].items()):
        v = float(key.split("|")[0].split("=")[1])
        axes[0].axvline(row["ite_allred"], color=SPEED_C.get(v, C["grey"]),
                        linestyle=":", alpha=0.6, linewidth=1.2)
    axes[0].legend(fontsize=7.5, frameon=False)
    fig.suptitle("H4: all-red exchange rate (dotted = ITE-formula all-red (W+L)/v)",
                 fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(os.path.join(FIG_DIR, "fig4_allred.png"), dpi=150)
    plt.close(fig)


def fig_losttime():
    p = os.path.join(ANA_DIR, "lost_time.json")
    if not os.path.exists(p):
        return
    lt = json.load(open(p))
    base = [r for r in lt if r["green"] == 30.0 and r["truck_share"] == 0.0]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
    ax = axes[0]
    for ar in sorted(set(r["allred"] for r in base)):
        sub = sorted([r for r in base if r["allred"] == ar], key=lambda r: r["yellow"])
        ax.plot([r["yellow"] for r in sub], [r["L_total"] for r in sub], "-o",
                markersize=4.5, label="all-red %.0f s" % ar)
        ax.plot([r["yellow"] for r in sub], [r["assumed_intergreen"] for r in sub],
                "--", color=C["grey"], linewidth=1, alpha=0.5)
    style(ax, "(a) measured TOTAL lost time L vs the assumed intergreen (grey dashed)",
          "yellow (s)", "seconds")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    for ar in sorted(set(r["allred"] for r in base)):
        sub = sorted([r for r in base if r["allred"] == ar], key=lambda r: r["yellow"])
        ax.plot([r["yellow"] for r in sub], [r["L_minus_intergreen"] for r in sub], "-o",
                markersize=4.5, label="all-red %.0f s" % ar)
    ax.axhline(0, color=C["dark"], linewidth=1)
    style(ax, "(b) error if L is assumed = yellow + all-red", "yellow (s)",
          "L - (y + ar)  (s)")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[2]
    r0 = base[0]
    prof = r0["profile"]
    ax.plot([p[0] for p in prof], [p[1] for p in prof], "-o", color=C["blue"], markersize=4)
    ax.axhline(r0["h_s"], color=C["red"], linestyle="--",
               label="saturation headway h_s = %.3f s" % r0["h_s"])
    style(ax, "(c) discharge headway by queue position (y=%.0f, ar=%.0f)"
          % (r0["yellow"], r0["allred"]), "queue position n", "mean headway h_n (s)")
    ax.legend(fontsize=8, frameon=False)
    fig.suptitle("H3: measured start-up + clearance lost time vs the assumed intergreen",
                 fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(os.path.join(FIG_DIR, "fig5_losttime.png"), dpi=150)
    plt.close(fig)


def fig_boundary():
    p = os.path.join(ANA_DIR, "stopgo_boundary.json")
    if not os.path.exists(p):
        return
    b = json.load(open(p))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    ax = axes[0]
    for decel, col in ((4.5, C["blue"]), (3.05, C["orange"]), (2.5, C["green"])):
        sub = sorted([r for r in b if r["decel"] == decel and r["actionStepLength"] == 0.05
                      and r["ballistic"] and r["sumo_boundary"]], key=lambda r: r["v"])
        if sub:
            ax.plot([r["v"] * 3.6 for r in sub], [r["sumo_boundary"] for r in sub], "-o",
                    color=col, markersize=4.5, label="SUMO measured, decel=%.2f" % decel)
            ax.plot([r["v"] * 3.6 for r in sub], [r["kinematic_no_prt"] for r in sub], "--",
                    color=col, linewidth=1, alpha=0.6)
    sub = sorted([r for r in b if r["decel"] == 4.5 and r["actionStepLength"] == 0.05
                  and r["ballistic"]], key=lambda r: r["v"])
    if sub:
        ax.plot([r["v"] * 3.6 for r in sub], [r["ite_x_stop"] for r in sub], ":",
                color=C["red"], linewidth=2, label="ITE $x_s$ (PRT 1 s, a=3.05)")
        ax.plot([r["v"] * 3.6 for r in sub], [r["x_c_stopline_y3"] for r in sub], "-",
                color=C["dark"], linewidth=1.2, label="$x_c$ at y=3 s")
    style(ax, "(a) SUMO's own stop/go boundary vs the ITE stopping distance",
          "approach speed (km/h)", "distance to stop line (m)")
    ax.legend(fontsize=7.5, frameon=False)

    ax = axes[1]
    for asl, col in ((0.05, C["blue"]), (1.0, C["purple"])):
        for ball, ls in ((True, "-"), (False, "--")):
            sub = sorted([r for r in b if r["decel"] == 3.05
                          and r["actionStepLength"] == asl and r["ballistic"] == ball
                          and r["sumo_boundary"]], key=lambda r: r["v"])
            if sub:
                ax.plot([r["v"] * 3.6 for r in sub], [r["sumo_boundary"] for r in sub],
                        ls, color=col, marker="o", markersize=3.5,
                        label="asl=%.2f s, %s" % (asl, "ballistic" if ball else "Euler"))
    style(ax, "(b) effect of actionStepLength (PRT proxy) and integration method",
          "approach speed (km/h)", "SUMO stop/go boundary (m)")
    ax.legend(fontsize=7.5, frameon=False)
    fig.suptitle("SUMO's decision boundary at yellow onset, measured by single-vehicle "
                 "bisection", fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(os.path.join(FIG_DIR, "fig6_sumo_boundary.png"), dpi=150)
    plt.close(fig)


def fig_h5(res):
    h5 = res.get("H5", {}).get("cells", {})
    if not h5:
        return
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
    combos = [(0.0, 0.0, "cars, flat"), (0.30, 0.0, "30% trucks, flat"),
              (0.0, -4.0, "cars, -4% grade"), (0.30, -4.0, "30% trucks, -4% grade")]
    cols = [C["blue"], C["orange"], C["green"], C["red"]]
    for ax, m, yl in ((axes[0], "rlr_per_1000_veh", "RLR / 1000 veh"),
                      (axes[1], "hard_per_1000_decisions",
                       "hard braking (>3 m/s2) / 1000 decisions"),
                      (axes[2], "emg_stop_red",
                       "unphysical emergency stops at red (count/run)")):
        for (ts, g, lab), col in zip(combos, cols):
            ys, ms, hs = [], [], []
            for y in (3.0, 5.0):
                k = "t=%.2f|g=%+.0f|y=%.1f" % (ts, g, y)
                if k in h5:
                    ys.append(y)
                    ms.append(h5[k][m]["mean"])
                    hs.append(h5[k][m]["hw"])
            if ys:
                eb(ax, ys, ms, hs, color=col, label=lab)
        style(ax, None, "yellow (s)", yl)
    axes[0].legend(fontsize=7.5, frameon=False)
    fig.suptitle("H5: heavy vehicles and grade (95% CI over 6 CRN replications)",
                 fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(os.path.join(FIG_DIR, "fig7_trucks_grade.png"), dpi=150)
    plt.close(fig)


def main():
    res = json.load(open(os.path.join(ANA_DIR, "results.json")))
    for f in (fig_decision_curve, fig_stopgo, fig_pareto, fig_allred, fig_h5):
        try:
            f(res)
        except Exception as e:
            print("plot failed:", f.__name__, e)
    for f in (fig_losttime, fig_boundary):
        try:
            f()
        except Exception as e:
            print("plot failed:", f.__name__, e)
    print("figures ->", FIG_DIR)


if __name__ == "__main__":
    main()
