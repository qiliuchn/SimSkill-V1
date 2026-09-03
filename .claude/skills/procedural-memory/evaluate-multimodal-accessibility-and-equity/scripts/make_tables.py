#!/usr/bin/env python3
"""Assemble the CSV deliverables into outputs/."""
import os
import sys
import json
import csv
import shutil
import statistics

WORK, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
SCNS = ["base", "altA", "altB"]
LBL = {"base": "Base (do-nothing)", "altA": "A road capacity",
       "altB": "B transit service"}

AC = json.load(open(os.path.join(WORK, "accessibility.json")))
EB = json.load(open(os.path.join(WORK, "equity_bca.json")))
SV = json.load(open(os.path.join(WORK, "seed_variability.json")))
DEM = json.load(open(os.path.join(WORK, "demand.json")))["demographics"]
ZONES = AC["zones"]

# ------------------------------------------------------------ headline table
rows = []


def add(metric, unit, f, note=""):
    r = dict(metric=metric, unit=unit)
    for s in SCNS:
        r[LBL[s]] = f(s)
    r["note"] = note
    rows.append(r)


EQ = EB["equity"]
add("Mean population-weighted car accessibility", "jobs (gravity, common beta)",
    lambda s: round(EQ[s]["mean_pop_car"], 0))
add("Mean population-weighted transit accessibility", "jobs (gravity, common beta)",
    lambda s: round(EQ[s]["mean_pop_pt"], 0))
add("Mean per-person accessibility (mode-weighted by car ownership)", "jobs",
    lambda s: round(EQ[s]["mean_pop_person"], 0))
add("Mean accessibility, 4 low-income peripheral zones", "jobs",
    lambda s: round(EQ[s]["mean_lowincome_person"], 0))
add("Gini of per-person accessibility", "-", lambda s: round(EQ[s]["gini_person"], 4))
add("Gini (car only)", "-", lambda s: round(EQ[s]["gini_car"], 4))
add("Gini (transit only)", "-", lambda s: round(EQ[s]["gini_pt"], 4))
add("Palma ratio (top 10% / bottom 40% of population)", "-",
    lambda s: round(EQ[s]["palma_person"], 4))
add("Car-owner mean accessibility", "jobs", lambda s: round(EQ[s]["mean_carowner"], 0))
add("Carless mean accessibility", "jobs", lambda s: round(EQ[s]["mean_carless"], 0))
add("Carless gap (ratio car-owner / carless)", "-",
    lambda s: round(EQ[s]["carless_gap_ratio"], 3))
add("Zone-pairs with NO transit option (of 600)", "pairs",
    lambda s: 600 - sum(1 for k, v in
                        json.load(open(os.path.join(WORK, "skims_%s.json" % s)))["T_pt"]
                        .items() if v is not None))
add("Zone-pairs unroutable by car (of 600)", "pairs",
    lambda s: sum(AC["results"][s]["unroutable"]["car_cong"].values()))
add("Total peak-hour vehicle-hours (demand vehicles, 3-seed mean)", "veh-h",
    lambda s: round(statistics.fmean([t["veh_hours"] for t in EB["totals"][s]]), 1))
add("Total peak-hour bus-hours (3-seed mean)", "bus-h",
    lambda s: round(statistics.fmean([t["bus_hours"] for t in EB["totals"][s]]), 2))
add("Peak bus fleet", "vehicles", lambda s: EB["peak_fleet"][s])
add("PV of benefits (30 y, 4%)", "USD",
    lambda s: "-" if s == "base" else round(EB["bca"][s]["pv_benefits_usd"], 0))
add("PV of costs (30 y, 4%)", "USD",
    lambda s: "-" if s == "base" else round(EB["bca"][s]["pv_costs_usd"], 0))
add("Net present value", "USD",
    lambda s: "-" if s == "base" else round(EB["bca"][s]["npv_usd"], 0))
add("Benefit-cost ratio", "-",
    lambda s: "-" if s == "base" else round(EB["bca"][s]["bcr"], 3))
add("NPV at equal budget (road unit cost solved to match B)", "USD",
    lambda s: "-" if s != "altA" else round(EB["bca"]["altA"]["npv_at_equal_budget"], 0),
    "equal-budget control")
add("BCR at equal budget", "-",
    lambda s: "-" if s != "altA" else round(EB["bca"]["altA"]["bcr_at_equal_budget"], 3),
    "equal-budget control")

with open(os.path.join(OUT, "results_table.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["metric", "unit"] + [LBL[s] for s in SCNS] + ["note"])
    w.writeheader()
    w.writerows(rows)

# ------------------------------------------------------------ per-zone table
with open(os.path.join(OUT, "accessibility_by_zone.csv"), "w", newline="") as f:
    cols = ["zone", "label", "population", "jobs", "car_ownership", "low_income"]
    for s in SCNS:
        cols += ["%s_cum_car_10min" % s, "%s_cum_car_15min" % s,
                 "%s_cum_pt_30min" % s, "%s_cum_pt_45min" % s,
                 "%s_grav_car" % s, "%s_grav_pt" % s, "%s_grav_person" % s,
                 "%s_pt_pairs_unreachable" % s]
    cols += ["base_cum_carff_10min", "base_cum_carff_15min", "base_grav_carff"]
    w = csv.writer(f)
    w.writerow(cols)
    for z in ZONES:
        r = [z, DEM[z]["label"], DEM[z]["pop"], DEM[z]["jobs"],
             DEM[z]["car_ownership"], DEM[z]["low_income"]]
        for s in SCNS:
            A = AC["results"][s]["A"]
            r += [A["cum_car_10"][z], A["cum_car_15"][z], A["cum_pt_30"][z],
                  A["cum_pt_45"][z], round(A["grav_car_basebeta"][z], 1),
                  round(A["grav_pt_carbeta_basebeta"][z], 1),
                  round(EB["equity"][s]["A_person"][z], 1),
                  AC["results"][s]["unroutable"]["pt"][z]]
        Ab = AC["results"]["base"]["A"]
        r += [Ab["cum_carff_10"][z], Ab["cum_carff_15"][z],
              round(Ab["grav_carff_basebeta"][z], 1)]
        w.writerow(r)

# ------------------------------------------------------------ skim matrices
for s in SCNS:
    SK = json.load(open(os.path.join(WORK, "skims_%s.json" % s)))
    for key, name in (("T_car_cong", "skim_car_congested"),
                      ("T_car_ff", "skim_car_freeflow"), ("T_pt", "skim_transit")):
        with open(os.path.join(OUT, "%s_%s.csv" % (name, s)), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["origin"] + ZONES)
            for i in ZONES:
                row = [i]
                for j in ZONES:
                    if i == j:
                        row.append("")
                        continue
                    v = SK[key]["%s|%s" % (i, j)]
                    row.append("" if v is None else round(v, 1))
                w.writerow(row)

# ------------------------------------------------------------ verification + misc
for s in SCNS:
    for f in ("verify_car_%s.csv" % s, "verify_pt_%s.csv" % s):
        shutil.copy(os.path.join(WORK, f), os.path.join(OUT, f))
shutil.copy(os.path.join(WORK, "zone_table.csv"), os.path.join(OUT, "zone_table.csv"))
for f in ("accessibility.json", "equity_bca.json", "seed_variability.json",
          "pt_lines.json", "zones.json", "demand.json"):
    shutil.copy(os.path.join(WORK, f), os.path.join(OUT, f))
for s in SCNS:
    shutil.copy(os.path.join(WORK, "verify_%s.json" % s),
                os.path.join(OUT, "verify_%s.json" % s))
    shutil.copy(os.path.join(WORK, "%s.net.xml" % s), os.path.join(OUT, "%s.net.xml" % s))
    shutil.copy(os.path.join(WORK, "%s_busstops.add.xml" % s),
                os.path.join(OUT, "%s_busstops.add.xml" % s))
    shutil.copy(os.path.join(WORK, "%s_ptvehicles.rou.xml" % s),
                os.path.join(OUT, "%s_ptvehicles.rou.xml" % s))
shutil.copy(os.path.join(WORK, "taz.add.xml"), os.path.join(OUT, "taz.add.xml"))
shutil.copy(os.path.join(WORK, "peak.od"), os.path.join(OUT, "peak.od"))

# ------------------------------------------------------------ provenance table
with open(os.path.join(OUT, "parameter_provenance.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["parameter", "value", "provenance"])
    for k, v in EB["params"].items():
        w.writerow([k, v, EB["provenance"][k]])
    w.writerow(["beta_car_per_min", round(AC["results"]["base"]["beta_car_per_min"], 5),
                "CALIBRATED by bisection to observed tripinfo mean interzonal car time"])
    w.writerow(["beta_pt_per_min", round(AC["results"]["base"]["beta_pt_per_min"], 5),
                "CALIBRATED by bisection to observed personinfo transit time "
                "(transit-trip-table weighted)"])
    w.writerow(["equal_budget_road_unit_cost_usd_per_lane_km",
                round(EB["bca"]["altA"]["equal_budget_unit_cost_usd_per_lane_km"], 0),
                "DERIVED so PV(cost A) == PV(cost B): an experimental control"])
print("tables written to", OUT)
for r in rows:
    print("%-62s %-28s %14s %14s %14s" % (r["metric"][:62], r["unit"][:28],
                                          r[LBL["base"]], r[LBL["altA"]], r[LBL["altB"]]))
