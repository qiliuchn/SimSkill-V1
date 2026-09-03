#!/usr/bin/env python3
"""H2: does measured capacity rise in DISCRETE STEPS at stripe boundaries?

The striping model segments a sidewalk into floor(width / stripe_width) parallel
stripes.  If capacity is set by the stripe COUNT rather than by the continuous
width, then capacity(W) should be a staircase with risers at integer multiples of
the stripe width, and the width increments between risers buy literally nothing.

Test: sweep W in quarter-stripe increments at a demand that saturates each width,
then (a) compare a staircase model  q = c * floor(W/s)  against a proportional
model  q = c * W , and (b) re-run with a CHANGED --pedestrian.striping.stripe-width
and check the risers move to multiples of the new value.
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_util import mean_ci    # noqa: E402


def collect(path):
    res = json.load(open(path))["results"]
    g = {}
    for m in res.values():
        g.setdefault(m["config"]["w_mid"], []).append(m)
    out = []
    for w in sorted(g):
        ms = g[w]
        out.append({"w": w,
                    "flow": mean_ci([m["flow_p_s"] for m in ms]),
                    "dens": mean_ci([m["density_p_m2"] for m in ms]),
                    "speed": mean_ci([m["speed_ms"] for m in ms]),
                    "jamrate": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
                    "rate": ms[0]["config"]["rate"],
                    "stripe": ms[0]["config"]["stripe_width"]})
    return out


def fit_models(pts, stripe):
    W = np.array([p["w"] for p in pts])
    q = np.array([p["flow"]["mean"] for p in pts])
    # SUMO's MSPModel_Striping computes numStripes = max(1, (int)floor(width/stripeWidth))
    # with RAW floating-point division, so e.g. 2.4/0.8 = 2.9999999999999996 -> 2 stripes.
    # Mirror that exactly rather than rounding, or the model mispredicts at the very
    # widths where the staircase hypothesis is being tested.
    n = np.maximum(np.floor(W / stripe), 1)
    n_eps = np.maximum(np.floor(W / stripe + 1e-9), 1)
    # least-squares scale for each 1-parameter model
    c_step = float(np.sum(q * n) / np.sum(n * n))
    c_prop = float(np.sum(q * W) / np.sum(W * W))
    def r2(pred):
        return float(1 - np.sum((q - pred) ** 2) / np.sum((q - q.mean()) ** 2))
    return {"stripe_width": stripe,
            "staircase": {"c_per_stripe_p_s": c_step, "r2": r2(c_step * n),
                          "rmse": float(np.sqrt(np.mean((q - c_step * n) ** 2)))},
            "proportional": {"c_per_m_p_s": c_prop, "r2": r2(c_prop * W),
                             "rmse": float(np.sqrt(np.mean((q - c_prop * W) ** 2)))},
            "capacity_per_stripe_p_s": c_step,
            "n_stripes_raw_floor": n.tolist(),
            "n_stripes_exact_arithmetic": n_eps.tolist(),
            "staircase_exact_arithmetic_r2": r2(
                float(np.sum(q * n_eps) / np.sum(n_eps * n_eps)) * n_eps)}


def risers(pts, tol_rel=0.04):
    """Locate width increments that produce a real capacity gain vs. ones that don't."""
    out = []
    for a, b in zip(pts, pts[1:]):
        fa, fb = a["flow"], b["flow"]
        rel = (fb["mean"] - fa["mean"]) / fa["mean"]
        # "significant" = the two replication CIs do not overlap
        sep = (fb["lo"] > fa["hi"]) if ("lo" in fa and "lo" in fb) else None
        out.append({"w_from": a["w"], "w_to": b["w"], "rel_gain": rel,
                    "is_riser": bool(rel > tol_rel and sep),
                    "ci_separated": bool(sep)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--default", required=True)
    ap.add_argument("--sw040", required=True)
    ap.add_argument("--sw080", required=True)
    ap.add_argument("--plateau")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--plots", required=True)
    a = ap.parse_args()
    os.makedirs(a.plots, exist_ok=True)

    fams = {"0.64 (SUMO default)": (collect(a.default), 0.64),
            "0.40": (collect(a.sw040), 0.40),
            "0.80": (collect(a.sw080), 0.80)}

    out = {"families": {}}
    for label, (pts, s) in fams.items():
        out["families"][label] = {
            "stripe_width": s,
            "points": [{"w": p["w"], "rate": p["rate"], "flow_mean": p["flow"]["mean"],
                        "flow_ci_half": p["flow"]["ci_half"], "flow_cv": p["flow"]["cv"],
                        "spec_flow": p["flow"]["mean"] / p["w"],
                        "density": p["dens"]["mean"], "speed": p["speed"]["mean"],
                        "jam_events_per_1000_ps": p["jamrate"]["mean"], "n_seeds": p["flow"]["n"]}
                       for p in pts],
            "model_comparison": fit_models(pts, s),
            "risers": risers(pts),
        }
        rs = out["families"][label]["risers"]
        out["families"][label]["riser_widths"] = [r["w_to"] for r in rs if r["is_riser"]]
        out["families"][label]["dead_increments"] = [
            [r["w_from"], r["w_to"]] for r in rs if not r["is_riser"]]

    if a.plateau:
        pl = json.load(open(a.plateau))["results"]
        g = {}
        for m in pl.values():
            g.setdefault((m["config"]["w_mid"], round(m["config"]["rate"] / m["config"]["w_mid"], 2)),
                         []).append(m["flow_p_s"])
        out["plateau_check"] = {"%g@x%g" % k: mean_ci(v) for k, v in sorted(g.items())}

    json.dump(out, open(a.out_json, "w"), indent=2)

    # ---------- plots ----------
    fig, ax = plt.subplots(1, 3, figsize=(16.5, 4.8))
    cols = {"0.64 (SUMO default)": "#2b6cb0", "0.40": "#c53030", "0.80": "#2f855a"}
    for label, (pts, s) in fams.items():
        W = [p["w"] for p in pts]
        q = [p["flow"]["mean"] for p in pts]
        e = [p["flow"]["ci_half"] or 0 for p in pts]
        ax[0].errorbar(W, q, yerr=e, fmt="o-", ms=4, capsize=2, color=cols[label],
                       label="stripe %s m" % label)
        for k in range(1, 9):
            if k * s <= max(W) + 0.05:
                ax[0].axvline(k * s, color=cols[label], ls=":", alpha=.35, lw=1)
    ax[0].set_xlabel("sidewalk width W [m]"); ax[0].set_ylabel("capacity [P/s]")
    ax[0].set_title("Capacity vs width\n(dotted = multiples of that family's stripe width)")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

    pts, s = fams["0.64 (SUMO default)"]
    W = np.array([p["w"] for p in pts]); q = np.array([p["flow"]["mean"] for p in pts])
    mc = out["families"]["0.64 (SUMO default)"]["model_comparison"]
    n = np.maximum(np.floor(W / s), 1)
    ax[1].errorbar(W, q, yerr=[p["flow"]["ci_half"] or 0 for p in pts], fmt="o", color="k",
                   capsize=2, label="measured")
    ax[1].step(W, mc["staircase"]["c_per_stripe_p_s"] * n, where="mid", color="#2b6cb0",
               label="staircase c*floor(W/0.64)  $R^2$=%.4f" % mc["staircase"]["r2"])
    ax[1].plot(W, mc["proportional"]["c_per_m_p_s"] * W, "--", color="#c53030",
               label="proportional c*W  $R^2$=%.4f" % mc["proportional"]["r2"])
    ax[1].set_xlabel("sidewalk width W [m]"); ax[1].set_ylabel("capacity [P/s]")
    ax[1].set_title("Staircase vs proportional (default stripe)")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    for label, (pts, s) in fams.items():
        W = [p["w"] for p in pts]
        ax[2].plot(W, [p["flow"]["mean"] / p["w"] for p in pts], "o-", ms=4,
                   color=cols[label], label="stripe %s m" % label)
    ax[2].set_xlabel("sidewalk width W [m]"); ax[2].set_ylabel("specific capacity [P/s/m]")
    ax[2].set_title("Specific capacity sawtooths:\nwidth added inside a stripe is wasted")
    ax[2].legend(fontsize=8); ax[2].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plots, "h2_stripe_quantization.png"), dpi=140)

    for label in fams:
        f = out["families"][label]
        print("%-20s staircase R2=%.4f rmse=%.4f | proportional R2=%.4f rmse=%.4f"
              % (label, f["model_comparison"]["staircase"]["r2"],
                 f["model_comparison"]["staircase"]["rmse"],
                 f["model_comparison"]["proportional"]["r2"],
                 f["model_comparison"]["proportional"]["rmse"]))
        print("   risers at W = %s" % f["riser_widths"])
        print("   dead width increments: %s" % f["dead_increments"])


if __name__ == "__main__":
    main()
