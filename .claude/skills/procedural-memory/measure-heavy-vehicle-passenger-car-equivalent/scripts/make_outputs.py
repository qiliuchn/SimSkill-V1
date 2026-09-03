#!/usr/bin/env python3
"""STEP 4 -- write the compacted per-cell metrics CSVs and the plots."""
import os
import json
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import WORK, OUT, GRADES, HV_VARIANTS, SEEDS
from run_sweeps import SHARES, DECOMP_P

R = json.load(open(os.path.join(WORK, "pce_results.json")))
CAL = None
_cp = os.path.join(WORK, "calibration_results.json")
if os.path.exists(_cp):
    CAL = json.load(open(_cp))

HCM15, HCM20 = 1.5, 2.0


def w(name, header, rows):
    p = os.path.join(OUT, name)
    with open(p, "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(header)
        cw.writerows(rows)
    print("wrote", p)


# ------------------------------------------------------------------- CSVs ----
rows = []
for p in SHARES:
    a = R["signal_share_sweep"]["p%.2f" % p]
    b = R["freeway_share_sweep"]["p%.2f" % p]
    rows.append([p, round(a["p_realised"], 4), round(b["p_realised"], 4),
                 round(a["s_vph"], 1), round(a["s_ci95"], 1), round(a["regression_r2"], 6),
                 round(a["f_hv"], 4),
                 "" if a["ET_M1_capacity_ratio"] is None else round(a["ET_M1_capacity_ratio"], 4),
                 "" if a["ET_M1_ci95"] is None else round(a["ET_M1_ci95"], 4),
                 "" if a["ET_M1b_headway_ratio"] is None else round(a["ET_M1b_headway_ratio"], 4),
                 "" if a["ET_M1b_ci95"] is None else round(a["ET_M1b_ci95"], 4),
                 round(a["h_s"], 4), round(a["s_vph_greenreg"], 1),
                 round(a["regression_r2"], 6),
                 round(b["capacity_vph"], 1), round(b["capacity_ci95"], 1), round(b["f_hv"], 4),
                 "" if b["ET_M2_equal_capacity"] is None else round(b["ET_M2_equal_capacity"], 4),
                 "" if b["ET_M2_ci95"] is None else round(b["ET_M2_ci95"], 4),
                 a["queue_min"], round(b["upstream_space_mean_speed_ms"], 2),
                 b["teleports"], b["collisions"], a["n_approach_cycles"], int(b["n_discharged"])])
w("et_vs_truck_share.csv",
  ["p_nominal", "p_realised_signal", "p_realised_freeway",
   "signal_s_vph", "signal_s_ci95", "signal_regression_r2", "signal_f_HV",
   "ET_M1_signal_capacity_ratio", "ET_M1_ci95",
   "ET_M1b_signal_headway_ratio", "ET_M1b_ci95",
   "signal_h_s_s", "signal_s_vph_greenreg_secondary", "signal_greenreg_r2",
   "freeway_capacity_vph", "freeway_capacity_ci95", "freeway_f_HV",
   "ET_M2_freeway_equal_capacity", "ET_M2_ci95",
   "signal_min_queue_veh", "freeway_upstream_space_mean_speed_ms",
   "freeway_teleports", "freeway_collisions",
   "signal_n_approach_cycles", "freeway_n_discharged"], rows)

rows = []
for g in GRADES:
    r = R["freeway_grade"]["g%g" % g]
    rows.append([g, r["grade_verified"],
                 ";".join("%s=%s" % (k, v) for k, v in sorted(r["grade_pct_realised_from_compiled_net"].items())),
                 round(r["capacity_p0"], 1), round(r["capacity_p0_ci95"], 1),
                 round(r["capacity_p20"], 1), round(r["capacity_p20_ci95"], 1),
                 round(r["p_realised"], 4), round(r["ET_M2"], 4), round(r["ET_M2_ci95"], 4),
                 round(r["discharge_speed_p0"], 3), round(r["discharge_speed_p20"], 3),
                 r["teleports"], r["collisions"]])
w("et_vs_grade.csv",
  ["grade_pct_intended", "grade_verified_from_compiled_net", "realised_grade_per_edge_pct",
   "capacity_p0_vph", "capacity_p0_ci95", "capacity_p20_vph", "capacity_p20_ci95",
   "p_realised", "ET_M2", "ET_M2_ci95", "discharge_speed_p0_ms", "discharge_speed_p20_ms",
   "teleports", "collisions"], rows)

rows = []
for v in HV_VARIANTS:
    r = R["decomposition"][v]
    rows.append([v, ";".join("%s=%s" % (k, x) for k, x in sorted(r["differs_from_car_in"].items())),
                 r["n_params_changed"],
                 round(r["s_vph"], 1), round(r["s_ci95"], 1),
                 round(r["capacity_vph"], 1), round(r["capacity_ci95"], 1),
                 round(r["p_realised_sig"], 4), round(r["p_realised_fwy"], 4),
                 round(r["ET_M1_signal"], 4), round(r["ET_M1_ci95"], 4),
                 "" if r["ET_M1b_headway"] is None else round(r["ET_M1b_headway"], 4),
                 round(r["ET_M2_freeway"], 4), round(r["ET_M2_ci95"], 4),
                 r["queue_min"], round(r["fwy_upstream_speed_ms"], 2),
                 r["teleports"], r["collisions"]])
w("parameter_decomposition.csv",
  ["variant", "differs_from_car_in", "n_params_changed",
   "signal_s_vph", "signal_s_ci95", "freeway_capacity_vph", "freeway_capacity_ci95",
   "p_realised_signal", "p_realised_freeway",
   "ET_M1_signal", "ET_M1_ci95", "ET_M1b_signal_headway",
   "ET_M2_freeway", "ET_M2_ci95",
   "signal_min_queue_veh", "freeway_upstream_speed_ms", "teleports", "collisions"], rows)

# two-method agreement
rows = []
for p in [x for x in SHARES[1:] if x < 1.0]:
    a = R["signal_share_sweep"]["p%.2f" % p]
    b = R["freeway_share_sweep"]["p%.2f" % p]
    e1, e1b, e2 = a["ET_M1_capacity_ratio"], a["ET_M1b_headway_ratio"], b["ET_M2_equal_capacity"]
    rows.append([p, round(e1, 4), round(a["ET_M1_ci95"], 4),
                 round(e1b, 4), round(a["ET_M1b_ci95"], 4),
                 round(e2, 4), round(b["ET_M2_ci95"], 4),
                 round(e2 - e1, 4), round(100.0 * (e2 - e1) / e1, 2),
                 # do the 95% CIs of M1 and M2 overlap?
                 bool(max(e1 - a["ET_M1_ci95"], e2 - b["ET_M2_ci95"]) <=
                      min(e1 + a["ET_M1_ci95"], e2 + b["ET_M2_ci95"]))])
w("two_method_agreement.csv",
  ["p_nominal", "ET_M1_signal_capacity", "M1_ci95", "ET_M1b_signal_headway", "M1b_ci95",
   "ET_M2_freeway_equal_capacity", "M2_ci95", "M2_minus_M1", "pct_diff", "CIs_overlap"], rows)

if CAL:
    w("calibration.csv", CAL["csv_header"], CAL["csv_rows"])

# per-run raw metrics (one row per simulated cell x seed)
keys = ["testbed", "variant", "p_nominal", "grade", "seed", "p_realised",
        "h_s", "s_vph", "s_vph_greenreg", "greenreg_r2", "l1_s", "h_car", "h_hv",
        "n_headways", "n_max_position", "min_queue_veh", "min_veh_per_cycle",
        "n_approach_cycles", "capacity_vph", "n_discharged", "discharge_speed_ms",
        "upstream_space_mean_speed_ms", "upstream_occupancy_pct",
        "queue_meanJamVeh_lane2", "trend_vph_per_hour", "teleports", "collisions"]
w("per_run_metrics.csv", keys,
  [[("" if r.get(k) is None else (round(r[k], 5) if isinstance(r.get(k), float) else r.get(k, "")))
    for k in keys] for r in R["per_run_metrics"]])

# headway-vs-queue-position profile (the undershoot evidence) + window sensitivity
prof_ps = [0.0, 0.30, 1.00]
ns = sorted({int(n) for p in prof_ps for n in R["signal_share_sweep"]["p%.2f" % p]["headway_profile"]})
w("signal_headway_profile.csv",
  ["queue_position_n"] + ["mean_headway_s_p%.2f" % p for p in prof_ps]
  + ["n_obs_p%.2f" % p for p in prof_ps],
  [[n] + [R["signal_share_sweep"]["p%.2f" % p]["headway_profile"].get(str(n), "") for p in prof_ps]
   + [R["signal_share_sweep"]["p%.2f" % p]["profile_counts"].get(str(n), "") for p in prof_ps]
   for n in ns])

w("hcm_linearity_check.csv",
  ["p_nominal", "signal_h_measured_s", "signal_h_linear_blend_s", "signal_excess_pct",
   "freeway_h_measured_s", "freeway_h_linear_blend_s", "freeway_excess_pct"],
  [[p] + [round(R["hcm_linearity_check"]["p%.2f" % p][k], 5) for k in
          ("signal_h_measured", "signal_h_linear_blend", "signal_excess_pct",
           "freeway_h_measured", "freeway_h_linear_blend", "freeway_excess_pct")]
   for p in SHARES])

mech = R["mechanism_headway_increments"]
w("mechanism_headway_increments.csv",
  ["variant", "dh_signal_s", "dh_freeway_s"],
  [[v, round(mech[v]["dh_signal_s"], 5), round(mech[v]["dh_freeway_s"], 5)] for v in HV_VARIANTS]
  + [["SUM_of_4_single_params", round(mech["ADDITIVITY_CHECK"]["sum_dh_signal"], 5),
      round(mech["ADDITIVITY_CHECK"]["sum_dh_freeway"], 5)],
     ["MEASURED_hv_full", round(mech["ADDITIVITY_CHECK"]["measured_dh_signal_hv_full"], 5),
      round(mech["ADDITIVITY_CHECK"]["measured_dh_freeway_hv_full"], 5)]])

# ------------------------------------------------------------------ plots ----
C1, C2, C3 = "#2b6cb0", "#c05621", "#2f855a"
GREY = "#718096"


def style(ax, xl, yl, t):
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.set_title(t, fontsize=10)
    ax.grid(alpha=.25, lw=.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


ps = [x for x in SHARES[1:] if x < 1.0]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
ax = axes[0]
for key, lbl, col, mk in (("ET_M1_capacity_ratio", "M1 signal: capacity ratio (f_HV)", C1, "o"),
                          ("ET_M1b_headway_ratio", "M1b signal: disaggregate headway ratio", C3, "s")):
    y = [R["signal_share_sweep"]["p%.2f" % p][key] for p in ps]
    e = [R["signal_share_sweep"]["p%.2f" % p][key.replace("ET_M1_capacity_ratio", "ET_M1_ci95")
                                              .replace("ET_M1b_headway_ratio", "ET_M1b_ci95")] for p in ps]
    ax.errorbar([p * 100 for p in ps], y, yerr=e, marker=mk, color=col, capsize=3, lw=1.6, label=lbl)
y = [R["freeway_share_sweep"]["p%.2f" % p]["ET_M2_equal_capacity"] for p in ps]
e = [R["freeway_share_sweep"]["p%.2f" % p]["ET_M2_ci95"] for p in ps]
ax.errorbar([p * 100 for p in ps], y, yerr=e, marker="^", color=C2, capsize=3, lw=1.6,
            label="M2 freeway: equal-capacity equivalency")
ax.axhline(HCM15, ls="--", c=GREY, lw=1.2)
ax.text(51, HCM15 + .03, "HCM 2000 level E_T=1.5", fontsize=7, ha="right", color=GREY)
ax.axhline(HCM20, ls=":", c=GREY, lw=1.2)
ax.text(51, HCM20 + .03, "HCM 6th ed. level E_T=2.0", fontsize=7, ha="right", color=GREY)
ax.axhline(1.0, c="k", lw=.8)
style(ax, "heavy-vehicle share (%)", "E_T  (passenger cars per heavy vehicle)",
      "SUMO's emergent E_T for its DEFAULT truck vType\n(95% t-CI over 3 replication seeds)")
ax.legend(fontsize=7.5, loc="upper right")

ax = axes[1]
sx = [p * 100 for p in SHARES]
ax.plot(sx, [R["signal_share_sweep"]["p%.2f" % p]["f_hv"] for p in SHARES],
        marker="o", color=C1, lw=1.7, label="measured f_HV, signal (s(p)/s(0))")
ax.plot(sx, [R["freeway_share_sweep"]["p%.2f" % p]["f_hv"] for p in SHARES],
        marker="^", color=C2, lw=1.7, label="measured f_HV, freeway (C(p)/C(0))")
pp = [i / 100.0 for i in range(0, 101)]
ax.plot([x * 100 for x in pp], [1 / (1 + x * (HCM15 - 1)) for x in pp], ls="--", c=GREY, lw=1.3,
        label="HCM f_HV = 1/(1+p(E_T-1)), E_T=1.5")
ax.plot([x * 100 for x in pp], [1 / (1 + x * (HCM20 - 1)) for x in pp], ls=":", c=GREY, lw=1.3,
        label="HCM f_HV, E_T=2.0")
style(ax, "heavy-vehicle share (%)", "heavy-vehicle adjustment factor f_HV",
      "Measured f_HV vs the HCM model.\nSignal barely responds; freeway tracks E_T~1.5 up to p~30%")
ax.legend(fontsize=7.5, loc="lower left")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "et_vs_truck_share.png"), dpi=160)
print("wrote et_vs_truck_share.png")

# ---- grade
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
ax = axes[0]
gy = [R["freeway_grade"]["g%g" % g]["ET_M2"] for g in GRADES]
ge = [R["freeway_grade"]["g%g" % g]["ET_M2_ci95"] for g in GRADES]
ax.errorbar(GRADES, gy, yerr=ge, marker="o", color=C2, capsize=3, lw=1.8,
            label="SUMO measured E_T (p=20%, verified grades)")
# HCM 2000 Exhibit 23-9 style escalation for ~20% trucks on >=1 km upgrades
hcm_g = {0.0: 1.5, 2.0: 1.5, 4.0: 2.5, 6.0: 4.5}
ax.plot(GRADES, [hcm_g[g] for g in GRADES], ls="--", marker="s", color=GREY, lw=1.4,
        label="HCM order-of-magnitude escalation (illustrative)")
style(ax, "sustained upgrade (%, verified from compiled net)", "E_T",
      "E_T vs grade: SUMO is FLAT because no SUMO\ncar-following model reads road grade")
ax.legend(fontsize=7.5)
ax = axes[1]
ax.errorbar(GRADES, [R["freeway_grade"]["g%g" % g]["capacity_p0"] for g in GRADES],
            yerr=[R["freeway_grade"]["g%g" % g]["capacity_p0_ci95"] for g in GRADES],
            marker="o", color=C1, capsize=3, lw=1.6, label="capacity, 0% trucks")
ax.errorbar(GRADES, [R["freeway_grade"]["g%g" % g]["capacity_p20"] for g in GRADES],
            yerr=[R["freeway_grade"]["g%g" % g]["capacity_p20_ci95"] for g in GRADES],
            marker="^", color=C2, capsize=3, lw=1.6, label="capacity, 20% trucks")
style(ax, "sustained upgrade (%)", "bottleneck queue-discharge capacity (veh/h)",
      "Measured capacity is grade-invariant in SUMO")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "et_vs_grade.png"), dpi=160)
print("wrote et_vs_grade.png")

# ---- decomposition
order = ["hv_len", "hv_accel", "hv_decel", "hv_vmax130", "hv_vmax90", "hv_tau14", "hv_full"]
order = [v for v in order if v in R["decomposition"]]
fig, ax = plt.subplots(figsize=(9.5, 4.6))
import numpy as np
x = np.arange(len(order))
e1 = [R["decomposition"][v]["ET_M1_signal"] for v in order]
c1 = [R["decomposition"][v]["ET_M1_ci95"] for v in order]
e2 = [R["decomposition"][v]["ET_M2_freeway"] for v in order]
c2 = [R["decomposition"][v]["ET_M2_ci95"] for v in order]
ax.bar(x - .19, e1, .36, yerr=c1, capsize=3, color=C1, label="E_T signal (M1)")
ax.bar(x + .19, e2, .36, yerr=c2, capsize=3, color=C2, label="E_T freeway (M2)")
ax.axhline(1.0, c="k", lw=.9)
ax.axhline(HCM15, ls="--", c=GREY, lw=1.1)
ax.set_xticks(x)
def _lab(v):
    d = R["decomposition"][v]["differs_from_car_in"]
    if len(d) > 2:
        return "%s\n(all 4 at once)" % v.replace("hv_", "")
    return "%s\n(%s)" % (v.replace("hv_", ""),
                         "\n".join("%s=%s" % (k, z) for k, z in sorted(d.items())))
ax.set_xticklabels([_lab(v) for v in order], fontsize=7.5)
style(ax, "", "E_T at 30% heavy-vehicle share",
      "Which vType parameter actually drives SUMO's E_T?  (one attribute changed at a time)")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "parameter_decomposition.png"), dpi=160)
print("wrote parameter_decomposition.png")

if CAL:
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.errorbar(CAL["sweep_x"], CAL["sweep_et"], yerr=CAL["sweep_ci"], marker="o",
                color=C1, capsize=3, lw=1.6, label="SIGNAL E_T (the calibrated quantity), p=30%")
    ax.plot(CAL["sweep_x"], CAL["sweep_et_freeway"], marker="^", ls="-.", color=C2, lw=1.5,
            label="FREEWAY E_T with the same vType (transfer check)")
    ax.axhline(CAL["target_ET"], ls="--", c=GREY, lw=1.2, label="target E_T = %.2f" % CAL["target_ET"])
    ax.axvline(CAL["solved_value"], ls=":", c=C3, lw=1.4,
               label="solved %s = %.3f" % (CAL["param"], CAL["solved_value"]))
    for lbl, xx, yy, ee, col in CAL["verification_points"]:
        ax.errorbar([xx], [yy], yerr=[ee], marker="*", ms=15, color=col, capsize=4, label=lbl)
    style(ax, CAL["param"], "E_T, level terrain",
          "Calibrating SUMO's heavy vehicle to an HCM-consistent E_T")
    ax.legend(fontsize=7.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "calibration.png"), dpi=160)
    print("wrote calibration.png")
print("done")
