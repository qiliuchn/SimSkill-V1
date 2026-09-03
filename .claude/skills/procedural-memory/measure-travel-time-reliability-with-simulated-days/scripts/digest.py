#!/usr/bin/env python3
"""Print the headline numbers used to write FINDINGS.md, straight from the
deliverable CSVs in outputs/ (so the report and the files cannot drift)."""
import csv
import json
import os

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                   "..", "..", "..", "outputs"))
SC = ["A_base", "B_capacity", "C_info", "D_shoulder"]


def load(f):
    return list(csv.DictReader(open(os.path.join(OUT, f))))


def main():
    aud = json.load(open(os.path.join(OUT, "day_draw_audit.json")))
    print("### day draws")
    for k in ("n_days", "realised_E_mult", "realised_CV", "mult_min",
              "mult_max", "realised_p_incident", "n_incident_days",
              "inc_lanes_1", "inc_lanes_2", "inc_edge_CB1", "inc_edge_CB2"):
        print(f"  {k:22s} {aud[k]}")

    rt = load("reliability_table.csv")
    print("\n### vehicle-level pooled, subset=all  (value [95% CI])")
    hdr = ["mean", "median", "p80", "p95", "TTI", "PTI", "BI", "MiseryIndex",
           "ontime_1p10_ff", "ontime_1p25_ff"]
    for s in SC:
        print(f"  {s}")
        for m in hdr:
            r = [x for x in rt if x["level"] == "vehicle" and
                 x["subset"] == "all" and x["scenario"] == s and
                 x["metric"] == m][0]
            print(f"     {m:16s} {float(r['value']):10.3f}  "
                  f"[{float(r['ci_lo']):.3f}, {float(r['ci_hi']):.3f}]")

    print("\n### vehicle-level pooled by incident subset (point estimates)")
    for sub in ("no_incident_days", "incident_days"):
        print(f"  -- {sub}")
        for s in SC:
            v = {m: float([x for x in rt if x["level"] == "vehicle" and
                           x["subset"] == sub and x["scenario"] == s and
                           x["metric"] == m][0]["value"]) for m in hdr}
            print(f"     {s:12s} mean={v['mean']:8.1f} p95={v['p95']:8.1f} "
                  f"TTI={v['TTI']:.3f} PTI={v['PTI']:.3f} BI={v['BI']:.3f} "
                  f"MI={v['MiseryIndex']:8.1f} "
                  f"on1.10={v['ontime_1p10_ff']:.3f} "
                  f"on1.25={v['ontime_1p25_ff']:.3f}")

    print("\n### day-level (distribution of daily means), subset=all")
    for s in SC:
        vals = {}
        for m in ("day_mean_of_daily_means", "day_p95_of_daily_means",
                  "day_sd_of_daily_means", "day_cv_of_daily_means",
                  "day_TTI", "day_PTI", "day_BI", "day_MiseryIndex"):
            r = [x for x in rt if x["level"] == "day" and x["subset"] == "all"
                 and x["scenario"] == s and x["metric"] == m][0]
            vals[m] = (float(r["value"]), float(r["ci_lo"]),
                       float(r["ci_hi"]))
        print(f"  {s:12s} mean={vals['day_mean_of_daily_means'][0]:8.1f} "
              f"p95={vals['day_p95_of_daily_means'][0]:8.1f} "
              f"sd={vals['day_sd_of_daily_means'][0]:7.1f} "
              f"cv={vals['day_cv_of_daily_means'][0]:.4f} "
              f"TTI={vals['day_TTI'][0]:.3f} PTI={vals['day_PTI'][0]:.3f} "
              f"BI={vals['day_BI'][0]:.3f} "
              f"[BI CI {vals['day_BI'][1]:.3f},{vals['day_BI'][2]:.3f}]")

    print("\n### variance decomposition")
    for r in load("variance_decomposition.csv"):
        print(f"  {r['scenario']:12s} Var_total={float(r['var_total_FULL']):10.1f}"
              f" sd={float(r['sd_total_FULL']):7.1f} | seed "
              f"{100*float(r['frac_seed']):5.2f}%  demand "
              f"{100*float(r['frac_demand']):5.1f}%  incident "
              f"{100*float(r['frac_incident']):5.1f}%")
    print("  seed over-reporting:")
    for r in load("seed_noise_overreporting.csv"):
        print(f"    {r['scenario']:12s} seed-only day CV="
              f"{float(r['seedonly_day_cv']):.4f}  "
              f"seed-only vehicle PTI={float(r['seedonly_vehicle_PTI']):.3f} "
              f"BI={float(r['seedonly_vehicle_BI']):.3f}  |  full-study "
              f"PTI={float(r['full_vehicle_PTI']):.3f} "
              f"BI={float(r['full_vehicle_BI']):.3f}  "
              f"day-sd over-report {float(r['sd_overreport_pct']):.2f}%")

    print("\n### crossover / disagreement")
    for r in load("crossover_summary.csv"):
        print(f"  {r['pair']:28s} {r['metric']:32s} {r['crossings']}")
    dz = load("metric_disagreement_vs_p.csv")
    best = max(dz, key=lambda r: float(r["bootstrap_P_metrics_disagree"]))
    print(f"  peak P(metrics disagree) = "
          f"{best['bootstrap_P_metrics_disagree']} at p="
          f"{best['p_incident']}")
    print("  point-estimate disagreement at p in " + str(
        [r["p_incident"] for r in dz
         if r["point_estimate_metrics_disagree"] == "1"]))

    p = os.path.join(OUT, "metric_ranking_disagreements.csv")
    if os.path.exists(p):
        rows = load("metric_ranking_disagreements.csv")
        print(f"\n### significant metric-ranking disagreements ({len(rows)})")
        for r in rows:
            print(f"  [{r['subset']}] {r['scenario_1']} vs {r['scenario_2']}: "
                  f"{r['metric_1']} -> {r['metric_1_prefers']} "
                  f"({r['metric_1_pct_change']}%, CI {r['metric_1_ci']})  ||  "
                  f"{r['metric_2']} -> {r['metric_2_prefers']} "
                  f"({r['metric_2_pct_change']}%, CI {r['metric_2_ci']})")

    print("\n### buffer-index paradox")
    for r in load("buffer_index_paradox_bootstrap.csv"):
        print(f"  [{r['level']}/{r['subset']}] {r['treatment']} vs "
              f"{r['base']}: dmean CI {r['d_mean_ci']}  dp95 CI "
              f"{r['d_p95_ci']}  dBI CI {r['d_BI_ci']}  "
              f"P(mean)={r['P_mean_improves']} P(p95)={r['P_p95_improves']} "
              f"P(BI up)={r['P_BI_worsens']} P(all)={r['P_all_three_hold']}")
    print("  scan hits:")
    for r in load("buffer_index_paradox_scan.csv"):
        if r["paradox"] == "1":
            print(f"    [{r['level']}/{r['subset']}] {r['treatment']} vs "
                  f"{r['base']}  dmean={r['d_mean_pct']}%  "
                  f"dp95={r['d_p95_pct']}%  dBI={r['d_BI']}")

    print("\n### teleports / censoring")
    for r in load("teleport_audit.csv"):
        print(f"  {r['scenario']:12s} teleports={r['total_teleports']:>4} "
              f"corridor veh teleported={r['corridor_vehicles_teleported']:>4}"
              f" ({r['teleport_share_pct']}%)  unfinished="
              f"{r['unfinished_corridor_trips']}  not-inserted="
              f"{r['loaded_but_never_inserted']}  freeze-days="
              f"{r['gridlock_freeze_days']}")
    print("  horizon censoring:")
    for r in load("censoring_horizon_sensitivity.csv"):
        if r["horizon_s"] in ("4800", "5400"):
            print(f"    H={r['horizon_s']} {r['scenario']:12s} censored="
                  f"{r['n_censored']:>5} ({r['censored_pct']}%)  naive p95="
                  f"{r['naive_p95']:>8} vs lower-bound {r['lowerbound_p95']:>8}"
                  f"  bias {r['p95_bias_pct']}%")
    print("  ttt sensitivity (A_base):")
    for r in load("teleport_sensitivity.csv"):
        if r["scenario"] == "A_base":
            print(f"    day{r['day']:>4} mult={float(r['mult']):.3f} ttt="
                  f"{r['time_to_teleport']:>4} tel={r['teleports']:>3} "
                  f"unfin={r['n_unfinished']:>3} mean={r['mean']:>8} "
                  f"p95={r['p95']:>8}")

    print("\n### paired differences vs base, subset=all")
    for r in load("paired_differences.csv"):
        if (r["subset"] == "all" and r["base"] == "A_base"
                and r["metric"] in ("mean", "p95", "PTI", "BI",
                                    "MiseryIndex", "ontime_1p10_ff",
                                    "ontime_1p25_ff")):
            print(f"  {r['treatment']:12s} {r['metric']:15s} "
                  f"{float(r['pct_change']):+8.2f}%  CI[{r['ci_lo']},"
                  f"{r['ci_hi']}] sig={r['significant_95']}")


if __name__ == "__main__":
    main()
