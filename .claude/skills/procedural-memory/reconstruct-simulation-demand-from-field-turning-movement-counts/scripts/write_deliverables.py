#!/usr/bin/env python3
"""Write the tabular deliverables. Every value is read from a report JSON or a
raw SUMO output file; nothing is typed in by hand."""
import csv
import json
import os
import statistics

from common import OUT, SCEN, RUNS, N_BINS, JUNCTIONS
import metrics as M
from export_tmc import movement_counts
from counts_to_demand import peak_hour_factor
import demand as D

VARIANTS = ["rec", "recq", "recqt", "recqj"]
LABEL = {"rec": "counts used directly", "recq": "queue-corr (storage)",
         "recqt": "queue-corr (storage)+trust-prop", "recqj": "queue-corr (jam length)"}
RT = json.load(open(os.path.join(OUT, "roundtrip_results.json")))


def balancing():
    for arm in ("under", "over"):
        rep = json.load(open(os.path.join(SCEN, "rec_%s_report.json" % arm)))
        p = os.path.join(OUT, "balancing_report_%s.csv" % arm)
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["link", "upstream_junction", "downstream_approach", "bin_start_s",
                        "U_upstream_departures", "A_downstream_arrivals",
                        "imbalance_U_minus_A", "relative_imbalance",
                        "B_balanced_link_volume"])
            for L in rep["balancing"]:
                for b in L["bins"]:
                    w.writerow([L["link"], L["upstream_junction"], L["downstream"],
                                b["bin_start_s"], "%.1f" % b["U"], "%.1f" % b["A"],
                                "%.1f" % b["imbalance"], "%.5f" % b["rel_imbalance"],
                                "%.1f" % b["B"]])
            w.writerow([])
            w.writerow(["link", "total_U", "total_A", "total_imbalance",
                        "total_rel_imbalance", "mean_abs_rel_imbalance_per_bin",
                        "max_abs_imbalance_veh", "link_travel_time_s"])
            for L in rep["balancing"]:
                w.writerow([L["link"], "%.0f" % L["total_U"], "%.0f" % L["total_A"],
                            "%.0f" % L["total_imbalance"],
                            "%.5f" % L["total_rel_imbalance"],
                            "%.5f" % L["mean_abs_rel_imbalance"],
                            "%.0f" % L["max_abs_imbalance"], L["bins"][0].get("link") and
                            rep["params"].get("offset_correct")])
            w.writerow([])
            w.writerow(["mid-block reconciliation (counted approach total minus "
                        "propagated volume)"])
            w.writerow(["approach", "propagated_total", "counted_total", "midblock_net",
                        "materialised_on_a_real_access_edge"])
            for m in rep["midblock_reconciliation"]:
                w.writerow([m["approach"], "%.1f" % m["propagated_total"],
                            "%.1f" % m["counted_total"], "%.1f" % m["midblock_net"],
                            m["materialised"]])
            w.writerow([])
            w.writerow(["mid-block access points detected in the network",
                        json.dumps(rep["midblock_access"])])
        print("wrote", p)


def demand_table():
    p = os.path.join(OUT, "demand_recovery_table.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "junction", "approach", "movement", "scope",
                    "true_demand_veh"] +
                   ["recovered_%s" % v for v in VARIANTS] +
                   ["err_pct_%s" % v for v in VARIANTS])
        for arm in ("under", "over"):
            for scope, field in (("peak_hour_bins_7_10", "demand_peak_hour"),
                                 ("4h_total", "demand_totals")):
                keys = RT["%s/rec" % arm][field]
                for k in sorted(keys):
                    j, app, m = k.split()
                    t = keys[k]["true"]
                    rec = [RT["%s/%s" % (arm, v)][field][k]["rec"] for v in VARIANTS]
                    err = [RT["%s/%s" % (arm, v)][field][k]["err_pct"] for v in VARIANTS]
                    w.writerow([arm, j, app, m, scope, "%.1f" % t] +
                               ["%.1f" % x for x in rec] + ["%.2f" % x for x in err])
    print("wrote", p)


def performance_table():
    noise = json.load(open(os.path.join(OUT, "replication_noise_floor.json")))
    p = os.path.join(OUT, "performance_table.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "approach", "quantity", "ground_truth_seed42"] +
                   [LABEL[v] for v in VARIANTS] +
                   ["GT_mean_4_seeds", "GT_sd_4_seeds"])
        for arm in ("under", "over"):
            ns = {k: [r[k] for r in noise[arm]] for k in ("delay", "q95", "resid")}
            for ap in ["%s %s" % (j, a) for j in JUNCTIONS for a in ("EB", "WB", "NB", "SB")]:
                gt = RT["%s/rec" % arm]["performance_gt"].get(ap)
                if not gt:
                    continue
                for q, key in (("segment control delay (s/veh)", "delay"),
                               ("95th-pct back of queue (veh)", "q95_veh"),
                               ("LOS letter", "los"),
                               ("residual queue at end of peak (veh)",
                                "residual_end_peak")):
                    row = [arm, ap, q, gt[key] if key == "los" else "%.2f" % gt[key]]
                    for v in VARIANTS:
                        x = RT["%s/%s" % (arm, v)]["performance_rerun"][ap]
                        row.append(x[key] if key == "los" else "%.2f" % x[key])
                    if ap == "J1 EB" and key in ("delay", "q95_veh", "residual_end_peak"):
                        kk = {"delay": "delay", "q95_veh": "q95",
                              "residual_end_peak": "resid"}[key]
                        row += ["%.2f" % statistics.mean(ns[kk]),
                                "%.2f" % statistics.stdev(ns[kk])]
                    w.writerow(row)
    print("wrote", p)


def geh_table():
    p = os.path.join(OUT, "geh_pass_rate_table.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "variant", "level", "subset", "n", "mean_GEH", "p85_GEH",
                    "max_GEH", "pct_GEH_lt_5", "pct_GEH_lt_10"])
        for arm in ("under", "over"):
            for v in VARIANTS:
                r = RT["%s/%s" % (arm, v)]
                for lvl, label, subset in (
                        ("count_fit_all", "i COUNT FIT", "all movement-bins"),
                        ("count_fit_peak", "i COUNT FIT", "peak hour only"),
                        ("count_fit_J1EB", "i COUNT FIT", "J1 EB (saturated) only"),
                        ("demand_recovery_all", "ii DEMAND RECOVERY", "all movement-bins"),
                        ("demand_recovery_peak", "ii DEMAND RECOVERY", "peak hour only"),
                        ("demand_recovery_J1EB", "ii DEMAND RECOVERY",
                         "J1 EB (saturated) only")):
                    s = r[lvl]
                    w.writerow([arm, LABEL[v], label, subset, s["n"],
                                "%.3f" % s["mean"], "%.3f" % s["p85"], "%.3f" % s["max"],
                                "%.1f" % s["pct_lt5"], "%.1f" % s["pct_lt10"]])
    print("wrote", p)


def phf_table():
    p = os.path.join(OUT, "phf_table.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "approach", "true_injected_PHF", "PHF_from_stop_bar_counts",
                    "peak_hour_start_bin_from_counts", "true_peak_hour_start_bin",
                    "PHF_realized_in_rerun_rec", "PHF_realized_in_rerun_recqt"])
        for arm in ("under", "over"):
            g = RT["%s/rec" % arm]["gt_phf"]
            r1 = RT["%s/rec" % arm]["realized_phf"]
            r2 = RT["%s/recqt" % arm]["realized_phf"]
            for ap in sorted(g):
                if g[ap]["PHF"] is None:
                    continue
                w.writerow([arm, ap, "%.4f" % D.PHF_TRUE, "%.4f" % g[ap]["PHF"],
                            g[ap]["start_bin"], D.TRUE_PEAK_BINS[0],
                            "%.4f" % r1[ap]["PHF"], "%.4f" % r2[ap]["PHF"]])
    print("wrote", p)


def iterative_table():
    p = os.path.join(OUT, "iterative_scaling_table.csv")
    rows = []
    for tag in ("base", "infl"):
        for r in json.load(open(os.path.join(OUT, "iterative_over_%s.json" % tag))):
            rows.append([tag, r["iteration"], "%.0f" % r["J1EB_peak_demand_true"],
                         "%.0f" % r["J1EB_peak_demand_emitted"],
                         "%.2f" % r["J1EB_peak_demand_err_pct"],
                         r["J1EB_peak_counts_obs"], r["J1EB_peak_counts_sim"],
                         "%.3f" % r["count_fit_all"]["mean"],
                         "%.1f" % r["count_fit_all"]["pct_lt5"],
                         "%.2f" % r["J1EB_delay"], r["J1EB_los"],
                         "%.1f" % r["J1EB_q95"], "%.1f" % r["J1EB_residual"]])
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "iteration", "J1EB_peak_demand_TRUE",
                    "J1EB_peak_demand_emitted", "demand_err_pct",
                    "J1EB_peak_counts_observed", "J1EB_peak_counts_simulated",
                    "mean_GEH_all", "pct_GEH_lt5_all", "J1EB_delay_s", "J1EB_LOS",
                    "J1EB_Q95_veh", "J1EB_residual_veh"])
        w.writerows(rows)
    print("wrote", p)


if __name__ == "__main__":
    balancing(); demand_table(); performance_table(); geh_table()
    phf_table(); iterative_table()
