#!/usr/bin/env python3
"""H3: counterflow capacity penalty + spontaneous lane formation.

At fixed TOTAL demand the directional split is swept 100/0 -> 50/50.  Two questions:

 1. Capacity penalty: how much total throughput is lost purely to opposing traffic?
 2. Lane formation: does the striping model reproduce the real self-organisation in
    which opposing streams segregate into lateral bands?  Measured by histogramming
    each FCD sample's lateral offset (y minus the lane centre) BY TRAVEL DIRECTION and
    reporting a segregation index = total-variation distance between the two
    normalised lateral distributions (0 = perfectly mixed, 1 = disjoint bands).

The 100/0 arm has no opposing stream, so its segregation index is undefined; the
control for "how much segregation would appear by chance" is the low-density 50/50
run, where nobody has to yield.
"""
import argparse
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_util import mean_ci, paired_diff   # noqa: E402


def collect(path):
    res = json.load(open(path))["results"]
    g = {}
    for m in res.values():
        g.setdefault(m["config"]["frac_fwd"], []).append(m)
    for k in g:
        g[k].sort(key=lambda m: m["config"]["seed"])
    return g


def summarise(ms):
    lat = [m["lateral"] for m in ms if "lateral" in m]
    return {
        "n_seeds": len(ms),
        "frac_fwd": ms[0]["config"]["frac_fwd"],
        "rate": ms[0]["config"]["rate"],
        "flow": mean_ci([m["flow_p_s"] for m in ms]),
        "speed": mean_ci([m["speed_ms"] for m in ms]),
        "dens": mean_ci([m["density_p_m2"] for m in ms]),
        "jamrate": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
        "coll": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
        "segregation": mean_ci([l["segregation_index"] for l in lat]),
        "separation_ratio": mean_ci([l["separation_ratio"] for l in lat]),
        "mean_lat_fwd": mean_ci([l["mean_lat_fwd"] for l in lat]),
        "mean_lat_bwd": mean_ci([l["mean_lat_bwd"] for l in lat]),
        "completion": mean_ci([m["accounting"]["completion_rate"] for m in ms]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counterflow", required=True)
    ap.add_argument("--lowdens", required=True)
    ap.add_argument("--reserve", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--plots", required=True)
    a = ap.parse_args()
    os.makedirs(a.plots, exist_ok=True)

    hi = collect(a.counterflow)
    lo = collect(a.lowdens)
    out = {"saturated": {}, "free_flow_control": {}}
    for f in sorted(hi, reverse=True):
        out["saturated"]["%g" % f] = summarise(hi[f])
    for f in sorted(lo, reverse=True):
        out["free_flow_control"]["%g" % f] = summarise(lo[f])

    # mechanism test: --pedestrian.striping.reserve-oncoming
    rv = json.load(open(a.reserve))["results"]
    gr = {}
    for n, m in rv.items():
        ro = float(n.split("_ro")[1].split("_s")[0])
        gr.setdefault((m["config"]["frac_fwd"], ro), []).append(m)
    out["reserve_oncoming"] = {}
    for (f, ro), ms in sorted(gr.items()):
        ms.sort(key=lambda m: m["config"]["seed"])
        out["reserve_oncoming"]["f%g_ro%g" % (f, ro)] = dict(summarise(ms), reserve=ro)
    out["reserve_oncoming_note"] = (
        "--pedestrian.striping.reserve-oncoming defaults to 0 on ordinary lanes "
        "(0.34 applies only on crossings/walkingareas) and its effect is additionally "
        "capped by --pedestrian.striping.reserve-oncoming.max = 1.28 m, which is why "
        "0.34 and 0.5 give identical results on a 2.24 m sidewalk.")

    base = out["saturated"]["1"]["flow"]["mean"]
    for f, s in out["saturated"].items():
        s["capacity_penalty_pct"] = 100.0 * (base - s["flow"]["mean"]) / base
    # CRN paired test of the 50/50 vs 100/0 capacity difference
    a100 = [m["flow_p_s"] for m in hi[1.0]]
    a50 = [m["flow_p_s"] for m in hi[0.5]]
    out["paired_capacity_test_100_vs_50"] = paired_diff(a100, a50)
    s100 = [m["lateral"]["segregation_index"] for m in hi[1.0]]
    s50 = [m["lateral"]["segregation_index"] for m in hi[0.5]]
    l50 = [m["lateral"]["segregation_index"] for m in lo[0.5]]
    out["segregation_saturated_50_vs_freeflow_50"] = paired_diff(s50, l50)
    out["segregation_note"] = (
        "The 100/0 arm's index compares the tiny set of samples whose inferred "
        "direction was negative (transient/no true opposing stream) against the rest, "
        "so it is a degenerate reference; the meaningful control is the free-flow 50/50 run.")

    json.dump(out, open(a.out_json, "w"), indent=2)

    # ---- plots ----
    fig, ax = plt.subplots(1, 3, figsize=(16.5, 4.6))
    fr = sorted(hi, reverse=True)
    ax[0].errorbar([100 * f for f in fr], [out["saturated"]["%g" % f]["flow"]["mean"] for f in fr],
                   yerr=[out["saturated"]["%g" % f]["flow"]["ci_half"] for f in fr],
                   fmt="o-", capsize=3, color="#2b6cb0")
    ax[0].set_xlabel("major-direction share [%]"); ax[0].set_ylabel("total flow [P/s]")
    ax[0].set_title("Counterflow capacity penalty\n(total demand held fixed)"); ax[0].grid(alpha=.3)
    for f in fr:
        s = out["saturated"]["%g" % f]
        ax[0].annotate("-%.1f%%" % s["capacity_penalty_pct"], (100 * f, s["flow"]["mean"]),
                       textcoords="offset points", xytext=(0, 9), fontsize=8, ha="center")

    ax[1].errorbar([100 * f for f in fr],
                   [out["saturated"]["%g" % f]["segregation"]["mean"] for f in fr],
                   yerr=[out["saturated"]["%g" % f]["segregation"]["ci_half"] for f in fr],
                   fmt="o-", capsize=3, color="#c53030", label="saturated (3.0 P/s)")
    fl = sorted(lo, reverse=True)
    ax[1].errorbar([100 * f for f in fl],
                   [out["free_flow_control"]["%g" % f]["segregation"]["mean"] for f in fl],
                   yerr=[out["free_flow_control"]["%g" % f]["segregation"]["ci_half"] for f in fl],
                   fmt="s--", capsize=3, color="#2f855a", label="free-flow control (0.5 P/s)")
    ax[1].set_xlabel("major-direction share [%]"); ax[1].set_ylabel("segregation index")
    ax[1].set_title("Lane formation (0=mixed, 1=disjoint bands)")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    out["completion_accounting_note"] = (
        "Every counterflow arm leaves 3200-3450 of ~3600 inserted pedestrians still "
        "walking at the end of the simulation, so its throughput number is a measurement "
        "of a deadlocked system, not of a served demand. Reported alongside, never alone.")

    m = json.load(open(a.counterflow))["results"]
    rep = next(v for v in m.values() if v["config"]["frac_fwd"] == 0.5 and v["config"]["seed"] == 1)
    L = rep["lateral"]
    e = L["bin_edges"]
    c = [(e[i] + e[i + 1]) / 2 for i in range(len(e) - 1)]
    nf, nb = max(L["n_fwd_samples"], 1), max(L["n_bwd_samples"], 1)
    ax[2].bar(c, [h / nf for h in L["hist_fwd"]], width=(e[1] - e[0]) * .9,
              alpha=.6, color="#2b6cb0", label="forward walkers")
    ax[2].bar(c, [-h / nb for h in L["hist_bwd"]], width=(e[1] - e[0]) * .9,
              alpha=.6, color="#c53030", label="opposing walkers")
    for k in range(-2, 3):
        ax[2].axvline(k * 0.64, color="k", ls=":", lw=.8, alpha=.5)
    ax[2].axhline(0, color="k", lw=.8)
    ax[2].set_xlabel("lateral offset from lane centre [m]")
    ax[2].set_ylabel("share of samples (mirrored)")
    ax[2].set_title("Lateral occupancy by direction, 50/50 saturated\n(seg. index %.3f; dotted = stripe boundaries)"
                    % L["segregation_index"])
    ax[2].legend(fontsize=8); ax[2].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plots, "h3_counterflow.png"), dpi=140)

    for f in fr:
        s = out["saturated"]["%g" % f]
        print("split %3d/%-3d  q=%.3f+-%.3f  penalty=%5.1f%%  v=%.3f  seg=%.3f+-%.3f  coll=%.1f"
              % (100 * f, 100 * (1 - f), s["flow"]["mean"], s["flow"]["ci_half"],
                 s["capacity_penalty_pct"], s["speed"]["mean"],
                 s["segregation"]["mean"], s["segregation"]["ci_half"] or 0, s["coll"]["mean"]))
    print("free-flow control 50/50 seg = %.3f" % out["free_flow_control"]["0.5"]["segregation"]["mean"])
    print("paired 100/0 vs 50/50 capacity diff:", json.dumps(out["paired_capacity_test_100_vs_50"]))


if __name__ == "__main__":
    main()
