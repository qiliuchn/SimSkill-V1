#!/usr/bin/env python3
"""
Fit and plot the MEASURED link performance functions produced by measure_lpf.py.

Two functional forms are fitted and BOTH are reported, because the honest answer is that
they do not fit equally well:

  (1) BPR      t(q) = t0 * (1 + alpha * (q/C)^beta)      -- the standard assignment form
  (2) queueing t(q) = t0 + s * max(0, q - C)             -- deterministic point-queue delay,
                                                            which is what SUMO's bottleneck
                                                            actually produces

Fits are restricted to the VALID regime -- the demand range over which the link's own
travel time is a genuine function of its own volume. Above that, the queue outgrows the
link's storage and the excess delay is pushed upstream (into the previous edge and into
origin `departDelay`), so the link's measured travel time saturates at a storage ceiling
and is no longer a link performance function at all. That ceiling is reported explicitly.
"""
import argparse
import csv
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# dataviz reference palette, categorical slots 1/7/2/3 -- validated with
# scripts/validate_palette.js --mode light: all checks PASS (the aqua contrast WARN is
# relieved by direct labels on every series).
COL = {"S->A (flow-dep)": "#2a78d6", "B->T (flow-dep)": "#4a3aa7",
       "A->T (flow-indep, isolated)": "#eb6834", "S->B (flow-indep, isolated)": "#1baf7a"}
MARK = {"S->A (flow-dep)": "o", "B->T (flow-dep)": "s",
        "A->T (flow-indep, isolated)": "^", "S->B (flow-indep, isolated)": "D"}
SHORT = {"S->A (flow-dep)": "S→A  flow-dependent",
         "B->T (flow-dep)": "B→T  flow-dependent",
         "A->T (flow-indep, isolated)": "A→T  flow-independent",
         "S->B (flow-indep, isolated)": "S→B  flow-independent"}
ORDER = ["S->A (flow-dep)", "B->T (flow-dep)",
         "A->T (flow-indep, isolated)", "S->B (flow-indep, isolated)"]


def _stats(t, pred):
    t, pred = np.asarray(t, float), np.asarray(pred, float)
    rmse = float(np.sqrt(np.mean((pred - t) ** 2)))
    ss = float(np.sum((t - t.mean()) ** 2))
    r2 = 1.0 - float(np.sum((t - pred) ** 2)) / ss if ss > 0 else float("nan")
    return round(rmse, 2), round(r2, 4)


def fit_bpr(q, t):
    q, t = np.asarray(q, float), np.asarray(t, float)
    t0 = float(t[np.argmin(q)])
    best = None
    for C in np.arange(200.0, 3000.0, 10.0):
        x = q / C
        for beta in np.arange(1.0, 16.05, 0.1):
            xb = x ** beta
            den = float(np.sum(xb * xb))
            if den <= 0:
                continue
            alpha = max(0.0, float(np.sum((t / t0 - 1.0) * xb)) / den)
            sse = float(np.sum((t0 * (1.0 + alpha * xb) - t) ** 2))
            if best is None or sse < best[0]:
                best = (sse, alpha, beta, C)
    _, alpha, beta, C = best
    rmse, r2 = _stats(t, t0 * (1 + alpha * (q / C) ** beta))
    return {"form": "BPR", "t0_s": round(t0, 1), "alpha": round(alpha, 4),
            "beta": round(beta, 2), "capacity_vph": round(C, 0), "rmse_s": rmse, "r2": r2}


def fit_queue(q, t):
    """t(q) = t0 + s*max(0, q-C); grid on C, least squares on (t0, s)."""
    q, t = np.asarray(q, float), np.asarray(t, float)
    best = None
    for C in np.arange(200.0, 2600.0, 5.0):
        x = np.maximum(0.0, q - C)
        A = np.vstack([np.ones_like(x), x]).T
        try:
            coef, *_ = np.linalg.lstsq(A, t, rcond=None)
        except np.linalg.LinAlgError:
            continue
        t0, s = float(coef[0]), float(coef[1])
        if s < 0:
            continue
        sse = float(np.sum((A @ coef - t) ** 2))
        if best is None or sse < best[0]:
            best = (sse, t0, s, C)
    _, t0, s, C = best
    rmse, r2 = _stats(t, t0 + s * np.maximum(0.0, q - C))
    return {"form": "queueing", "t0_s": round(t0, 1), "capacity_vph": round(C, 0),
            "slope_s_per_vph": round(s, 4), "rmse_s": rmse, "r2": r2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out-fig", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--valid-max-vph", type=float, default=2100,
                    help="upper end of the regime where the link's queue is still contained")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.csv)))
    data = {}
    for r in rows:
        data.setdefault(r["link"], []).append(
            (float(r["assigned_volume_vph"]), float(r["tt_veh_s"]), float(r["tt_edgedata_s"]),
             float(r["mean_departDelay_s"])))
    for k in data:
        data[k].sort()

    fits = {}
    for k in ORDER:
        q_all = np.array([p[0] for p in data[k]])
        t_all = np.array([p[1] for p in data[k]])
        ed_all = np.array([p[2] for p in data[k]])
        m = q_all <= a.valid_max_vph
        f = {"valid_range_vph": [float(q_all[m].min()), float(q_all[m].max())],
             "bpr": fit_bpr(q_all[m], t_all[m]),
             "queueing": fit_queue(q_all[m], t_all[m]),
             "t_at_min_q_s": round(float(t_all[0]), 1),
             "t_at_max_q_s": round(float(t_all[-1]), 1),
             "flow_sensitivity_ratio_full_range": round(float(t_all.max() / t_all.min()), 3),
             "flow_sensitivity_ratio_valid_range": round(float(t_all[m].max() / t_all[m].min()), 3),
             "storage_saturation_ceiling_s": round(float(t_all.max()), 1),
             "n_points_total": int(len(q_all)), "n_points_valid": int(m.sum()),
             "edgedata_vs_pervehicle_mean_abs_pct": round(
                 float(np.mean(np.abs(ed_all - t_all) / t_all) * 100), 2)}
        fits[k] = f

    fig, ax = plt.subplots(figsize=(8.6, 5.6))
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    qq = np.linspace(200, a.valid_max_vph, 400)   # fits are only drawn over their valid range
    for k in ORDER:
        q = np.array([p[0] for p in data[k]])
        t = np.array([p[1] for p in data[k]])
        m = q <= a.valid_max_vph
        f = fits[k]["queueing"]
        ax.plot(qq, f["t0_s"] + f["slope_s_per_vph"] * np.maximum(0, qq - f["capacity_vph"]),
                color=COL[k], lw=2, alpha=0.8, zorder=2)
        ax.plot(q[m], t[m], MARK[k], color=COL[k], ms=7.5, mec="#fcfcfb", mew=1.6, ls="none",
                zorder=4, label=SHORT[k])
        ax.plot(q[~m], t[~m], MARK[k], mfc="none", mec=COL[k], mew=1.6, ms=7.5, ls="none", zorder=3)
    ax.axvspan(a.valid_max_vph, 3900, color="#52514e", alpha=0.055, zorder=0)
    ax.annotate("hollow markers: the link's queue outgrows its own storage, so the excess\n"
                "delay is pushed upstream (previous edge + origin departDelay) and the\n"
                "link's own travel time saturates — no longer a link performance function",
                (a.valid_max_vph + 60, 60), fontsize=8, color="#52514e", va="bottom")
    ax.set_ylim(0, 520)
    ax.set_xlim(0, 3900)
    ax.set_xlabel("assigned link volume  (veh/h)", color="#52514e")
    ax.set_ylabel("measured mean link travel time  (s)", color="#52514e")
    ax.set_title("Measured link performance functions, SUMO Braess network\n"
                 "markers = per-vehicle measurement (vehroute exit-times);  lines = fitted "
                 "deterministic-queueing form",
                 color="#0b0b0b", fontsize=11, loc="left")
    ax.grid(True, color="#e4e3df", lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c9c8c2")
    for k, xy, off in [("S->A (flow-dep)", (1800, 305), (-14, 24)),
                       ("B->T (flow-dep)", (2100, 372), (14, -6)),
                       ("A->T (flow-indep, isolated)", (600, 250.6), (0, 26)),
                       ("S->B (flow-indep, isolated)", (1200, 252.3), (0, -30))]:
        ax.annotate(SHORT[k], xy, textcoords="offset points", xytext=off,
                    ha="center" if off[0] == 0 else ("right" if off[0] < 0 else "left"), fontsize=9, color=COL[k], weight="bold")
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor="#52514e")
    lines = []
    for k in ORDER:
        f, b = fits[k]["queueing"], fits[k]["bpr"]
        lines.append(f"{SHORT[k]:26s} queueing: t0={f['t0_s']:6.1f}s C={f['capacity_vph']:5.0f} "
                     f"s={f['slope_s_per_vph']:.3f} s/(veh/h) R2={f['r2']:.3f}   |   "
                     f"BPR: t0={b['t0_s']:6.1f} a={b['alpha']:.3f} b={b['beta']:.1f} "
                     f"C={b['capacity_vph']:5.0f} R2={b['r2']:.3f}   |   "
                     f"t(max)/t(min)={fits[k]['flow_sensitivity_ratio_full_range']:.2f}")
    fig.text(0.012, -0.115, "\n".join(lines), fontsize=6.6, family="monospace", color="#52514e")
    fig.tight_layout()
    fig.savefig(a.out_fig, dpi=170, bbox_inches="tight", facecolor="#fcfcfb")
    json.dump(fits, open(a.out_json, "w"), indent=2)
    for k in ORDER:
        f = fits[k]
        print(f"{SHORT[k]:26s} queueing R2={f['queueing']['r2']:.3f} "
              f"(t0={f['queueing']['t0_s']}, C={f['queueing']['capacity_vph']}, "
              f"s={f['queueing']['slope_s_per_vph']})   BPR R2={f['bpr']['r2']:.3f}   "
              f"ratio_full={f['flow_sensitivity_ratio_full_range']}")
    print("wrote", a.out_fig, a.out_json)


if __name__ == "__main__":
    main()
