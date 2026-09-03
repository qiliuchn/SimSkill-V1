#!/usr/bin/env python3
"""H4: how much of the measured high-density result is real, and how much is
produced by the striping model's jam push-through ("squeezing") mechanism?

Structurally identical to the vehicle teleport-artifact validation: sweep the
gridlock-resolution parameter as a treatment variable and quantify how much of the
result moves with it.

  --pedestrian.striping.jamtime           default 300 s  (ordinary lanes)
  --pedestrian.striping.jamtime.crossing  default  10 s  (on crossings)
  --pedestrian.striping.jamtime.narrow    default   1 s  (on narrow lanes)
Non-positive values disable squeezing entirely -- the pedestrian analogue of
--time-to-teleport -1, and it carries the same survivorship-censoring hazard, so
completed-vs-still-walking accounting is reported alongside every flow number.

Evidence sources, all from retained files:
  * `jammed` from --person-summary-output.  VERIFIED to be a CUMULATIVE event
    counter, not an instantaneous state count (monotone non-decreasing; observed to
    exceed the peak `walking` count 2.6x in one run).  Differenced across the
    measurement window, never integrated.
  * distinct pedestrians warned as jammed, parsed from the retained sumo log
  * person-person collision warnings -- the unambiguous signature that the model has
    been pushed past what it can physically represent
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_util import mean_ci, paired_diff   # noqa: E402

DEFAULT_JAMTIME = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jamtime", required=True)
    ap.add_argument("--jamtime-crossing")
    ap.add_argument("--uniform", required=True)
    ap.add_argument("--gated", required=True)
    ap.add_argument("--event-locations", help="event_locations.json from scan_events.py")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--plots", required=True)
    a = ap.parse_args()
    os.makedirs(a.plots, exist_ok=True)

    res = json.load(open(a.jamtime))["results"]
    g = {}
    for m in res.values():
        g.setdefault((m["config"]["rate"], m["config"]["jamtime"]), []).append(m)
    for k in g:
        g[k].sort(key=lambda m: m["config"]["seed"])

    out = {"default_jamtime_s": DEFAULT_JAMTIME, "cells": {}, "by_rate": {}}
    for (rate, jt), ms in sorted(g.items()):
        out["cells"]["r%g_jt%g" % (rate, jt)] = {
            "rate": rate, "jamtime": jt, "n_seeds": len(ms),
            "flow": mean_ci([m["flow_p_s"] for m in ms]),
            "speed": mean_ci([m["speed_ms"] for m in ms]),
            "dens": mean_ci([m["density_p_m2"] for m in ms]),
            "jam_events_window": mean_ci([float(m["person_summary"]["jam_events_in_window"]) for m in ms]),
            "jam_events_per_1000_ps": mean_ci([m["person_summary"]["jam_events_per_1000_person_seconds"] for m in ms]),
            "jam_events_per_person": mean_ci([m["person_summary"]["jam_events_per_inserted_person"] for m in ms]),
            "jammed_persons_logged": mean_ci([float(m["events"]["log_jammed_persons"]) for m in ms]),
            "collisions": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
            "completion_rate": mean_ci([m["accounting"]["completion_rate"] for m in ms]),
            "still_walking_at_end": mean_ci([float(m["accounting"]["still_walking_at_end"]) for m in ms]),
            "completed": mean_ci([float(m["accounting"]["completed_persons"]) for m in ms]),
        }
    rates = sorted(set(r for r, _ in g))
    jts = sorted(set(j for _, j in g))
    for rate in rates:
        C = lambda j: out["cells"]["r%g_jt%g" % (rate, j)]      # noqa: E731
        ref = C(DEFAULT_JAMTIME)["flow"]["mean"]
        dis = C(-1)["flow"]["mean"]
        spread = [C(j)["flow"]["mean"] for j in jts]
        out["by_rate"]["%g" % rate] = {
            "flow_at_default_jamtime_300s": ref,
            "flow_with_squeezing_disabled": dis,
            "flow_range_over_jamtime_sweep": [min(spread), max(spread)],
            "max_rel_sensitivity_pct": 100.0 * (max(spread) - min(spread)) / ref,
            "push_through_share_of_default_flow_pct": 100.0 * (ref - dis) / ref,
            "jam_events_per_1000_ps_at_default": C(DEFAULT_JAMTIME)["jam_events_per_1000_ps"]["mean"],
            "jam_events_per_1000_ps_at_10s": C(10)["jam_events_per_1000_ps"]["mean"],
            "density_at_default": C(DEFAULT_JAMTIME)["dens"]["mean"],
            "completion_rate_default": C(DEFAULT_JAMTIME)["completion_rate"]["mean"],
            "completion_rate_disabled": C(-1)["completion_rate"]["mean"],
            "collisions_default": C(DEFAULT_JAMTIME)["collisions"]["mean"],
            "paired_default_vs_disabled_flow": paired_diff(
                [m["flow_p_s"] for m in g[(rate, DEFAULT_JAMTIME)]],
                [m["flow_p_s"] for m in g[(rate, -1)]]),
            "paired_default_vs_10s_flow": paired_diff(
                [m["flow_p_s"] for m in g[(rate, DEFAULT_JAMTIME)]],
                [m["flow_p_s"] for m in g[(rate, 10)]]),
        }

    # ---- jamtime.crossing, measured where there actually IS a crossing ----------
    if a.jamtime_crossing:
        jc = json.load(open(a.jamtime_crossing))["results"]
        # the swept value isn't in result.json's config block, so recover it from the
        # run name, which sweep_egress builds as h4c_jtc<value>_s<seed>
        gg = {}
        for name, r in jc.items():
            tag = float(name.split("_jtc")[1].split("_s")[0])
            gg.setdefault(tag, []).append(r)
        out["jamtime_crossing"] = {}
        for tag, ms in sorted(gg.items()):
            out["jamtime_crossing"]["%g" % tag] = {
                "clearance_p95": mean_ci([m["clearance"]["clearance_p95"] for m in ms]),
                "clearance_p100": mean_ci([m["clearance"]["clearance_p100"] for m in ms]),
                "mean_walk_speed": mean_ci([m["clearance"]["mean_walk_speed_ms"] for m in ms]),
                "jam_events_total": mean_ci([float(m["person_summary"]["jam_events_total"]) for m in ms]),
                "completed": mean_ci([float(m["accounting"]["completed"]) for m in ms]),
                "still_walking": mean_ci([float(m["accounting"]["still_walking_at_end"]) for m in ms]),
                "collisions": mean_ci([float(m["events"]["log_collision_lines"]) for m in ms]),
                "veh_timeloss": mean_ci([m["vehicles"]["mean_veh_timeloss_s"] for m in ms]),
            }
        ref = out["jamtime_crossing"]["10"]["clearance_p95"]["mean"]
        vals = [v["clearance_p95"]["mean"] for v in out["jamtime_crossing"].values()]
        out["jamtime_crossing_summary"] = {
            "default_10s_p95": ref,
            "range_over_sweep": [min(vals), max(vals)],
            "max_rel_sensitivity_pct": 100.0 * (max(vals) - min(vals)) / ref,
            "disabled_vs_default_pct": 100.0 * (
                out["jamtime_crossing"]["-1"]["clearance_p95"]["mean"] - ref) / ref,
        }

    # ---- trustworthiness ceiling ------------------------------------------------
    pts = []
    for path, kind in ((a.uniform, "uniform"), (a.gated, "gated")):
        for m in json.load(open(path))["results"].values():
            pts.append({"kind": kind, "density": m["density_p_m2"],
                        "jam_events_per_1000_ps": m["person_summary"]["jam_events_per_1000_person_seconds"],
                        "jam_events_per_person": m["person_summary"]["jam_events_per_inserted_person"],
                        "collisions": m["events"]["log_collision_lines"],
                        "completion": m["accounting"]["completion_rate"],
                        "flow": m["flow_p_s"], "speed": m["speed_ms"]})
    # WHERE the artifacts happen decides whether the measurement is usable.  The
    # corridor's wide feed edge EA is an artificial reservoir holding unserved excess
    # demand; artifacts confined to it do not contaminate the measurement section EM.
    if a.event_locations:
        ev = json.load(open(a.event_locations))
        out["artifact_locations"] = ev["per_experiment"]
        def _verdict(v):
            j = 100 * (v["jam_share_on_measurement_section"] or 0)
            c = 100 * (v["collision_share_on_measurement_section"] or 0)
            tag = "CLEAN" if (j < 1.0 and c < 1.0) else "CONTAMINATED"
            return ("measurement section %s: %.2f%% of jam warnings and %.2f%% of "
                    "person-collision warnings occurred on EM itself "
                    "(the rest on the upstream feed reservoir EA / junction walkingareas)"
                    % (tag, j, c))
        out["artifact_location_verdict"] = {e: _verdict(v) for e, v in ev["per_experiment"].items()}
    THRESH = 1.0    # jam events per 1000 walking person-seconds
    clean = [p for p in pts if p["jam_events_per_1000_ps"] < THRESH and p["collisions"] == 0]
    dirty = [p for p in pts if p["jam_events_per_1000_ps"] >= THRESH or p["collisions"] > 0]
    out["trust_ceiling"] = {
        "criterion": "fewer than %g jam events per 1000 walking person-seconds AND zero "
                     "person-person collision warnings" % THRESH,
        "n_clean_runs": len(clean), "n_contaminated_runs": len(dirty),
        "max_clean_density_p_m2": max((p["density"] for p in clean), default=None),
        "min_contaminated_density_p_m2": min((p["density"] for p in dirty), default=None),
        "highest_collision_free_density_p_m2": max(
            (p["density"] for p in pts if p["collisions"] == 0), default=None),
        "lowest_density_with_collisions_p_m2": min(
            (p["density"] for p in pts if p["collisions"] > 0), default=None),
        "n_runs_with_collisions": sum(1 for p in pts if p["collisions"] > 0),
        "IMPORTANT": ("measured density in the section is NOT the right predictor of "
                      "contamination: the densest runs (standing queue at 2.27 P/m^2 "
                      "behind a narrow gate) are among the cleanest, while some runs "
                      "with a low in-section density are contaminated because their "
                      "unserved excess demand piles up in the upstream reservoir. "
                      "Demand/capacity ratio and the artifact LOCATION are the right "
                      "diagnostics -- see artifact_locations."),
    }
    # demand/capacity based ceiling for the unidirectional corridor
    uni = json.load(open(a.uniform))["results"]
    byrate = {}
    for m in uni.values():
        byrate.setdefault(m["config"]["rate"], []).append(m)
    CAP = 2.438
    dc = []
    for r in sorted(byrate):
        ms = byrate[r]
        dc.append({"demand_p_s": r, "demand_over_capacity": r / CAP,
                   "completion_rate": sum(m["accounting"]["completion_rate"] for m in ms) / len(ms),
                   "collisions": sum(m["events"]["log_collision_lines"] for m in ms) / len(ms),
                   "flow": sum(m["flow_p_s"] for m in ms) / len(ms)})
    out["demand_capacity_ceiling"] = {
        "capacity_used_p_s": CAP, "rows": dc,
        "highest_collision_free_demand_over_capacity": max(
            (d["demand_over_capacity"] for d in dc if d["collisions"] == 0), default=None),
        "lowest_demand_over_capacity_with_collisions": min(
            (d["demand_over_capacity"] for d in dc if d["collisions"] > 0), default=None)}
    out["all_run_points"] = pts
    json.dump(out, open(a.out_json, "w"), indent=2)

    # ---------------------------- plots -----------------------------------------
    n_ax = 3 if not a.jamtime_crossing else 4
    fig, ax = plt.subplots(1, n_ax, figsize=(5.4 * n_ax, 4.6))
    cols = {3.0: "#2b6cb0", 6.0: "#c53030"}
    xs = list(range(len(jts)))
    lab = ["off" if j < 0 else "%g" % j for j in jts]
    for rate in rates:
        y = [out["cells"]["r%g_jt%g" % (rate, j)]["flow"]["mean"] for j in jts]
        e = [out["cells"]["r%g_jt%g" % (rate, j)]["flow"]["ci_half"] for j in jts]
        ax[0].errorbar(xs, y, yerr=e, fmt="o-", capsize=3, color=cols.get(rate, "k"),
                       label="demand %g P/s" % rate)
    ax[0].axvline(jts.index(DEFAULT_JAMTIME), ls="--", color="k", lw=1, label="SUMO default 300 s")
    ax[0].set_xticks(xs); ax[0].set_xticklabels(lab)
    ax[0].set_xlabel("--pedestrian.striping.jamtime [s]"); ax[0].set_ylabel("measured flow [P/s]")
    ax[0].set_title("Is the measured capacity a\njam-resolution artifact?")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

    for rate in rates:
        y = [out["cells"]["r%g_jt%g" % (rate, j)]["jam_events_per_1000_ps"]["mean"] for j in jts]
        ax[1].plot(xs, y, "o-", color=cols.get(rate, "k"), label="demand %g P/s" % rate)
    ax[1].axvline(jts.index(DEFAULT_JAMTIME), ls="--", color="k", lw=1)
    ax[1].set_xticks(xs); ax[1].set_xticklabels(lab)
    ax[1].set_xlabel("--pedestrian.striping.jamtime [s]")
    ax[1].set_ylabel("jam events per 1000 walking person-seconds")
    ax[1].set_title("Push-through activity"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    ok = [p for p in pts if p["collisions"] == 0]
    bad = [p for p in pts if p["collisions"] > 0]
    ax[2].scatter([p["density"] for p in ok], [max(p["jam_events_per_1000_ps"], 1e-3) for p in ok],
                  s=18, color="#2f855a", label="no person collisions")
    ax[2].scatter([p["density"] for p in bad], [max(p["jam_events_per_1000_ps"], 1e-3) for p in bad],
                  s=34, color="#c53030", marker="x", label="person-person collisions")
    ax[2].axhline(THRESH, ls="--", color="k", lw=1, label="contamination threshold")
    if out["trust_ceiling"]["max_clean_density_p_m2"]:
        ax[2].axvline(out["trust_ceiling"]["max_clean_density_p_m2"], ls=":", color="#805ad5",
                      label="trust ceiling %.2f P/m$^2$" % out["trust_ceiling"]["max_clean_density_p_m2"])
    ax[2].set_yscale("log")
    ax[2].set_xlabel("measured density [P/m$^2$]")
    ax[2].set_ylabel("jam events / 1000 person-s")
    ax[2].set_title("Where results stop being trustworthy")
    ax[2].legend(fontsize=8); ax[2].grid(alpha=.3)

    if a.jamtime_crossing:
        tags = sorted(float(k) for k in out["jamtime_crossing"])
        xs2 = range(len(tags))
        ax[3].errorbar(list(xs2), [out["jamtime_crossing"]["%g" % t]["clearance_p95"]["mean"] for t in tags],
                       yerr=[out["jamtime_crossing"]["%g" % t]["clearance_p95"]["ci_half"] for t in tags],
                       fmt="s-", capsize=3, color="#805ad5")
        ax[3].axvline(tags.index(10), ls="--", color="k", lw=1, label="SUMO default 10 s")
        ax[3].set_xticks(list(xs2))
        ax[3].set_xticklabels(["off" if t < 0 else "%g" % t for t in tags])
        ax[3].set_xlabel("--pedestrian.striping.jamtime.crossing [s]")
        ax[3].set_ylabel("95% egress clearance [s]")
        ax[3].set_title("Crossing push-through:\negress scenario sensitivity")
        ax[3].legend(fontsize=8); ax[3].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.plots, "h4_jam_artifact.png"), dpi=140)
    print(json.dumps({k: out[k] for k in out
                      if k not in ("cells", "all_run_points", "jamtime_crossing")}, indent=2))


if __name__ == "__main__":
    main()
