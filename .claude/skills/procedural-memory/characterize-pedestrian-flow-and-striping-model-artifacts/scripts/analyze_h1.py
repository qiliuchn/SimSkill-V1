#!/usr/bin/env python3
"""H1: the pedestrian fundamental diagram (speed-density, flow-density).

Two run families are combined, for the reason the build-macroscopic-fundamental-diagram
skill gives for vehicles: a corridor with no downstream constraint only ever traces
the free-flow branch up to its own capacity.

  * `h1_uniform` (wide feed -> W -> wide exit): the measurement section IS the
    bottleneck, so the sweep traces the free-flow branch and pins capacity + critical
    density.
  * `h1_gated`   (wide feed -> W -> narrow exit gate of width Wg): the gate meters
    throughput below W's capacity, so the queue standing on the measurement section
    puts it on the CONGESTED branch; sweeping Wg walks that branch from near-capacity
    down toward standstill.

Fits Greenshields (v = v0(1 - k/kj)) and Weidmann's pedestrian form
(v = v0 (1 - exp(-gamma (1/k - 1/kj)))) to the speed-density cloud.
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt      # noqa: E402
from scipy.optimize import curve_fit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_util import mean_ci        # noqa: E402


def load(path):
    return json.load(open(path))["results"]


def group(res, keyfn):
    g = {}
    for name, m in res.items():
        g.setdefault(keyfn(name, m), []).append(m)
    return g


def greenshields(k, v0, kj):
    return v0 * np.clip(1.0 - k / kj, 0, None)


def weidmann(k, v0, kj, gamma):
    with np.errstate(divide="ignore", over="ignore"):
        return v0 * (1.0 - np.exp(-gamma * (1.0 / np.maximum(k, 1e-6) - 1.0 / kj)))


def r2(y, yhat):
    y = np.asarray(y, float)
    yhat = np.asarray(yhat, float)
    ss = np.sum((y - yhat) ** 2)
    st = np.sum((y - y.mean()) ** 2)
    return 1 - ss / st if st > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uniform", required=True)
    ap.add_argument("--gated", required=True)
    ap.add_argument("--gated-speed", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--plots", required=True)
    a = ap.parse_args()
    os.makedirs(a.plots, exist_ok=True)

    uni = load(a.uniform)
    gat = load(a.gated)
    gsp = load(a.gated_speed)
    W = 2.24

    # ---- per-demand-level replication means (CRN seeds 1..3) --------------------
    gu = group(uni, lambda n, m: m["config"]["rate"])
    upts = []
    for rate in sorted(gu):
        ms = gu[rate]
        upts.append({
            "rate": rate,
            "flow": mean_ci([m["flow_p_s"] for m in ms]),
            "dens": mean_ci([m["density_p_m2"] for m in ms]),
            "speed": mean_ci([m["speed_ms"] for m in ms]),
            "jamrate": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
            "jam_per_person": mean_ci([m["person_summary"]["jam_events_per_inserted_person"] for m in ms]),
            "coll": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
            "completion": mean_ci([m["accounting"]["completion_rate"] for m in ms]),
        })
    gg = group(gat, lambda n, m: m["config"]["w_exit"])
    gpts = []
    for wg in sorted(gg):
        ms = gg[wg]
        gpts.append({
            "gate_width": wg,
            "flow": mean_ci([m["flow_p_s"] for m in ms]),
            "dens": mean_ci([m["density_p_m2"] for m in ms]),
            "speed": mean_ci([m["speed_ms"] for m in ms]),
            "jamrate": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
            "jam_per_person": mean_ci([m["person_summary"]["jam_events_per_inserted_person"] for m in ms]),
            "coll": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
        })

    # speed-metered gate: same stripe count as EM, exit lane speed limit swept, which
    # meters throughput CONTINUOUSLY and so fills in the congested branch that a
    # stripe-quantized narrow gate can only sample at a few discrete points.
    gs = group(gsp, lambda n, m: m["config"]["speed_exit"])
    spts = []
    for sp in sorted(gs, reverse=True):
        ms = gs[sp]
        spts.append({
            "exit_speed_ms": sp,
            "flow": mean_ci([m["flow_p_s"] for m in ms]),
            "dens": mean_ci([m["density_p_m2"] for m in ms]),
            "speed": mean_ci([m["speed_ms"] for m in ms]),
            "jamrate": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
            "coll": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
        })

    # ---- free-flow speed: the lowest-density uniform point ---------------------
    lo = min(upts, key=lambda p: p["dens"]["mean"])
    v_free = lo["speed"]["mean"]

    # ---- capacity: the flow plateau of the uniform sweep ------------------------
    # (points whose measured flow no longer tracks demand -> the section is saturated)
    sat = [p for p in upts if p["flow"]["mean"] < 0.92 * p["rate"]]
    qmax = max(p["flow"]["mean"] for p in sat) if sat else max(p["flow"]["mean"] for p in upts)
    # the plateau = every saturated demand level within 2% of the peak saturated flow
    cap_pts = [p for p in sat if p["flow"]["mean"] >= 0.98 * qmax]
    capacity = sum(p["flow"]["mean"] for p in cap_pts) / len(cap_pts)
    k_crit = sum(p["dens"]["mean"] for p in cap_pts) / len(cap_pts)

    # ---- fits over the combined cloud ------------------------------------------
    allp = upts + gpts + spts
    ks = np.array([p["dens"]["mean"] for p in allp])
    vs = np.array([p["speed"]["mean"] for p in allp])
    qs = np.array([p["flow"]["mean"] / W for p in allp])
    order = np.argsort(ks)
    ks, vs, qs = ks[order], vs[order], qs[order]

    fits = {}
    try:
        pg, _ = curve_fit(greenshields, ks, vs, p0=[1.2, 4.0], maxfev=20000)
        fits["greenshields"] = {"v0": float(pg[0]), "k_jam": float(pg[1]),
                                "r2": float(r2(vs, greenshields(ks, *pg)))}
    except Exception as e:
        fits["greenshields"] = {"error": str(e)}
    try:
        pw, _ = curve_fit(weidmann, ks, vs, p0=[1.25, 5.0, 1.9],
                          bounds=([0.5, 1.5, 0.05], [2.0, 12.0, 20.0]), maxfev=40000)
        fits["weidmann"] = {"v0": float(pw[0]), "k_jam": float(pw[1]), "gamma": float(pw[2]),
                            "r2": float(r2(vs, weidmann(ks, *pw)))}
    except Exception as e:
        fits["weidmann"] = {"error": str(e)}

    slowest = max(gpts + spts, key=lambda p: p["dens"]["mean"])
    summary = {
        "width_m": W,
        "free_flow_speed_ms": v_free,
        "free_flow_speed_source": "lowest-density uniform run (rate=%g p/s, k=%.4f p/m2)"
                                  % (lo["rate"], lo["dens"]["mean"]),
        "capacity_p_s": capacity,
        "capacity_p_s_per_m": capacity / W,
        "capacity_demand_levels_on_plateau": [p["rate"] for p in cap_pts],
        "capacity_plateau_flows": [p["flow"]["mean"] for p in cap_pts],
        "capacity_plateau_jam_events_per_1000_ps": [p["jamrate"]["mean"] for p in cap_pts],
        "capacity_plateau_collisions": [p["coll"]["mean"] for p in cap_pts],
        "critical_density_p_m2": k_crit,
        "max_observed_density_p_m2": slowest["dens"]["mean"],
        "speed_at_max_observed_density_ms": slowest["speed"]["mean"],
        "jam_density_note": ("highest density actually OBSERVED with flow still >0; the "
                             "fitted k_jam values below are extrapolations past the last "
                             "flowing observation and are NOT a measurement"),
        "fits": fits,
        "benchmark_capacity_p_s_per_m": [1.2, 1.5],
        "benchmark_jam_density_p_m2": [4.0, 5.0],
        "n_fd_points": len(allp),
        "uniform_points": upts,
        "gated_points": gpts,
        "speed_gated_points": spts,
    }
    json.dump(summary, open(a.out_json, "w"), indent=2)

    # ---- plots -----------------------------------------------------------------
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    ku = [p["dens"]["mean"] for p in upts]
    vu = [p["speed"]["mean"] for p in upts]
    qu = [p["flow"]["mean"] / W for p in upts]
    kg = [p["dens"]["mean"] for p in gpts]
    vg = [p["speed"]["mean"] for p in gpts]
    qg = [p["flow"]["mean"] / W for p in gpts]
    kk = np.linspace(0.02, max(ks) * 1.05, 400)   # never extrapolate past the data

    ax[0].errorbar(ku, vu, yerr=[p["speed"]["ci_half"] or 0 for p in upts], fmt="o",
                   color="#2b6cb0", label="uniform (free-flow branch)", capsize=3)
    ax[0].errorbar(kg, vg, yerr=[p["speed"]["ci_half"] or 0 for p in gpts], fmt="s",
                   color="#c53030", label="narrow-gate (congested branch)", capsize=3)
    ax[0].errorbar([p["dens"]["mean"] for p in spts], [p["speed"]["mean"] for p in spts],
                   yerr=[p["speed"]["ci_half"] or 0 for p in spts], fmt="^",
                   color="#d69e2e", label="speed-metered gate (congested branch)", capsize=3)
    if "v0" in fits.get("weidmann", {}):
        ax[0].plot(kk, weidmann(kk, fits["weidmann"]["v0"], fits["weidmann"]["k_jam"],
                                fits["weidmann"]["gamma"]), "-", color="#2f855a",
                   label="Weidmann fit (R2=%.3f)" % fits["weidmann"]["r2"])
    if "v0" in fits.get("greenshields", {}):
        ax[0].plot(kk, greenshields(kk, fits["greenshields"]["v0"], fits["greenshields"]["k_jam"]),
                   "--", color="#975a16", label="Greenshields (R2=%.3f)" % fits["greenshields"]["r2"])
    ax[0].set_ylim(0, 1.45)
    ax[0].set_xlabel("density k [P/m$^2$]"); ax[0].set_ylabel("space-mean speed v [m/s]")
    ax[0].set_title("Speed-density"); ax[0].legend(fontsize=7); ax[0].grid(alpha=.3)

    ax[1].errorbar(ku, qu, yerr=[(p["flow"]["ci_half"] or 0) / W for p in upts], fmt="o",
                   color="#2b6cb0", capsize=3, label="uniform")
    ax[1].errorbar(kg, qg, yerr=[(p["flow"]["ci_half"] or 0) / W for p in gpts], fmt="s",
                   color="#c53030", capsize=3, label="narrow-gate")
    ax[1].errorbar([p["dens"]["mean"] for p in spts], [p["flow"]["mean"] / W for p in spts],
                   yerr=[(p["flow"]["ci_half"] or 0) / W for p in spts], fmt="^",
                   color="#d69e2e", capsize=3, label="speed-metered gate")
    ax[1].axhspan(1.2, 1.5, color="#48bb78", alpha=.18, label="real-world capacity 1.2-1.5 P/s/m")
    ax[1].axhline(capacity / W, ls=":", color="k", label="measured capacity %.3f" % (capacity / W))
    ax[1].axvline(k_crit, ls=":", color="#805ad5", label="critical density %.2f P/m$^2$" % k_crit)
    ax[1].set_xlabel("density k [P/m$^2$]"); ax[1].set_ylabel("specific flow q [P/s/m]")
    ax[1].set_title("Flow-density (fundamental diagram)"); ax[1].legend(fontsize=7); ax[1].grid(alpha=.3)

    ax[2].plot([p["rate"] for p in upts], [p["flow"]["mean"] for p in upts], "o-",
               color="#2b6cb0", label="measured flow through section")
    ax[2].plot([p["rate"] for p in upts], [p["rate"] for p in upts], "k--", lw=1, label="demand (y=x)")
    ax2 = ax[2].twinx()
    ax2.plot([p["rate"] for p in upts], [p["jamrate"]["mean"] for p in upts], "^-",
             color="#c53030", label="jam events")
    ax2.set_ylabel("jam events per 1000 walking person-seconds", color="#c53030")
    ax[2].set_xlabel("demand [P/s]"); ax[2].set_ylabel("flow [P/s]")
    ax[2].set_title("Demand-flow: capacity plateau + jam onset")
    ax[2].legend(fontsize=7, loc="upper left"); ax[2].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plots, "h1_fundamental_diagram.png"), dpi=140)
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("uniform_points", "gated_points")}, indent=2))


if __name__ == "__main__":
    main()
