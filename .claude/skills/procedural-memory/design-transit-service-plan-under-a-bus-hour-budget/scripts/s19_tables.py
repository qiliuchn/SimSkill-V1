"""Assemble the final deliverable tables (CSV) into outputs/."""
import os, json, csv, math
import tspcore as T
from tspcore import WORK, OUT, ensure
import harness as H

ensure(OUT)


def J(n):
    p = os.path.join(WORK, n)
    return json.load(open(p)) if os.path.exists(p) else None


def w(name, header, rows):
    p = os.path.join(OUT, name)
    with open(p, "w", newline="") as f:
        c = csv.writer(f); c.writerow(header); c.writerows(rows)
    print("wrote", p, f"({len(rows)} rows)")


def main():
    s4 = J("stage4_compare.json")
    if s4:
        rows = []
        for n, d in s4["summary"].items():
            rows.append([n, sum(d["buses"].values()), round(d["bus_hours"], 2),
                         round(d["max_concurrent_total"], 2),
                         round(d["gc_total_mean"]/3600, 2), round(d["gc_total_sd"]/3600, 3),
                         round(d["gc_incl_incomplete"]/3600, 2),
                         round(d["gc_per_person_mean"], 1), round(d["ridership"], 1),
                         round(d["walkonly"], 1), round(d["incomplete"], 1),
                         round(d["transfers_per_rider"], 3),
                         round(d["mean_access"], 1), round(d["mean_wait"], 1),
                         round(d["mean_ivt"], 1), round(d["mean_xwalk"], 1),
                         round(d["mean_xwait"], 1)])
        w("t1_equal_budget_comparison.csv",
          ["plan", "buses_nominal", "bus_hours", "realized_peak_fleet",
           "gc_total_pax_h", "gc_sd_pax_h", "gc_incl_incomplete_pax_h",
           "gc_per_completed_s", "riders", "walk_only", "incomplete",
           "transfers_per_rider", "mean_access_s", "mean_wait_s", "mean_ivt_s",
           "mean_xwalk_s", "mean_xwait_s"], rows)
        rows = []
        for n, d in s4["summary"].items():
            for p, v in d["gc_by_penalty"].items():
                rows.append([n, int(p), round(v/3600, 2)])
        w("t2_transfer_penalty_sensitivity.csv",
          ["plan", "transfer_penalty_s", "gc_total_pax_h"], sorted(rows))

    nf = J("noise_floor.json")
    if nf:
        rows = [[k, round(v["mean"]/3600, 2), round(v["sd"]/3600, 3),
                 round(100*v["cv"], 3)] for k, v in nf["per_design"].items()]
        w("t3_noise_floor_designs.csv",
          ["design", "gc_mean_pax_h", "gc_sd_pax_h", "cv_pct"], rows)
        rows = [[n, round(v["independent"]/3600, 2), round(v["independent_pct"], 3)]
                for n, v in nf["resolvable"].items()]
        w("t4_resolvable_difference.csv",
          ["n_replications", "resolvable_diff_pax_h", "pct_of_mean"], rows)
        rows = [[k, round(v["rho"], 4),
                 (round(v["var_reduction_analytic"], 3)
                  if v["var_reduction_analytic"] else "")]
                for k, v in nf["crn"].items()]
        w("t5_crn_correlation.csv", ["design_pair", "rho", "variance_reduction"], rows)

    ba = J("budget_audit_verified.json")
    if ba:
        rows = []
        for n, d in ba.items():
            for l, r in d["per_line"].items():
                rows.append([n, l, r["allocated"], round(r["headway"], 1),
                             round(r["cycle_mean"], 1), round(r["cycle_p90"], 1),
                             round(r["cycle_max"], 1), round(r["layover"], 1),
                             round(r["C"], 1), round(r["required"], 2),
                             round(r["observed"], 2)])
        w("t6_bus_hour_budget_audit.csv",
          ["plan", "line", "buses_allocated", "headway_s", "cycle_mean_s",
           "cycle_p90_s", "cycle_max_s", "layover_s", "C_s", "required_ceil",
           "observed_max_concurrent"], rows)

    s5 = J("stage5_optimize.json")
    if s5:
        rows = []
        for a, b in s5["allocations"].items():
            st_ = s5["heldout_stats"][a]
            rows.append([a] + [b[l] for l in sorted(b)]
                        + [round((s5["in_sample"].get(a) or 0)/3600, 2),
                           round(st_["mean"]/3600, 2), round(st_["sd"]/3600, 3),
                           round(st_["riders"], 1), round(st_["transfers"], 1),
                           round(st_["incomplete"], 1)])
        ids = sorted(next(iter(s5["allocations"].values())))
        w("t7_allocation_arms.csv",
          ["arm"] + ids + ["in_sample_pax_h", "heldout_mean_pax_h", "heldout_sd_pax_h",
                           "riders", "transfers", "incomplete"], rows)

    h1 = J("h1_frontier.json")
    if h1:
        rows = [[r["budget"], round(r["bus_hours"], 2), round(r["gc_total"]/3600, 2),
                 round(r["gc_per_completed"], 1), round(r["riders"], 1),
                 round(r["walkonly"], 1), round(r["benefit_pax_h"], 2),
                 ("" if r["marginal_per_bus_hour"] is None
                  else round(r["marginal_per_bus_hour"], 3)),
                 round(r["mean_wait"], 1), round(r["mean_ivt"], 1),
                 round(r["mean_access"], 1)] for r in h1["rows"]]
        w("t8_budget_benefit_frontier.csv",
          ["budget_buses", "bus_hours", "gc_total_pax_h", "gc_per_completed_s",
           "riders", "walk_only", "benefit_pax_h", "marginal_benefit_per_bus_hour",
           "mean_wait_s", "mean_ivt_s", "mean_access_s"], rows)

    post = J("h5_h6_post.json")
    if post:
        rows = [[r["plan"], r["line"], r["buses"], round(r["nominal_headway"], 1),
                 round(r["realized_mean_headway"], 1), round(r["headway_cv"], 4),
                 round(r["paired_share"], 4), round(r["half_headway"], 1),
                 round(r["corrected"], 1), round(r["realized_mean_wait"], 1),
                 round(r["err_half"], 1), round(r["err_corrected"], 1)]
                for r in post["h5"] if r["realized_mean_wait"]]
        w("t9_wait_vs_half_headway.csv",
          ["plan", "line", "buses", "nominal_headway_s", "realized_headway_s",
           "headway_cv", "paired_share", "half_headway_s", "corrected_s",
           "realized_wait_s", "err_half_s", "err_corrected_s"], rows)
        rows = []
        for n, c in post["coverage"].items():
            rows.append([n, round(c["share"], 4)]
                        + [round(c["by_zone"].get(z, 0), 4)
                           for z in sorted(c["by_zone"])])
        zs = sorted(next(iter(post["coverage"].values()))["by_zone"])
        w("t10_coverage.csv", ["plan", "coverage_share"] + zs, rows)
        rows = []
        for n, v in post["incidence"].items():
            for z, g in v["by_zone"].items():
                rows.append([n, "zone", z, round(g, 1), v["by_zone_n"][z]])
            for k, g in v["by_car_avail"].items():
                rows.append([n, "car_avail", k, round(g, 1), v["by_car_avail_n"][k]])
        w("t11_incidence.csv", ["plan", "dimension", "group", "mean_gc_s", "n"], rows)

    h4 = J("h4_interaction.json")
    if h4:
        rows = [[k.split("|")[0], k.split("|")[1], round(v["pair_benefit"]/3600, 3),
                 round(v["sum_singles"]/3600, 3), round(v["interaction"]/3600, 3),
                 ("" if v["interaction_pct_of_sum"] is None
                  else round(v["interaction_pct_of_sum"], 1))]
                for k, v in h4["interactions"].items()]
        w("t12_project_interactions.csv",
          ["project_i", "project_j", "pair_benefit_pax_h", "sum_of_singles_pax_h",
           "interaction_pax_h", "interaction_pct_of_sum"], rows)

    h3 = J("h3_congestion.json")
    if h3:
        rows = [[a, v["buses"], round(v["gc_mean"]/3600, 2), round(v["gc_sd"]/3600, 3),
                 round(v["riders"], 1), round(v["ivt"], 1), round(v["wait"], 1),
                 round(v["car_timeloss"], 1), round(v["car_dur"], 1),
                 round(v["incomplete"], 1)] for a, v in h3["arms"].items()]
        w("t13_h3_arms.csv",
          ["arm", "buses", "gc_pax_h", "gc_sd", "riders", "mean_ivt_s",
           "mean_wait_s", "car_timeloss_s", "car_duration_s", "incomplete"], rows)

    x = J("h2_crossover.json")
    if x:
        w("t14_crossover_budget.csv",
          ["plan", "budget", "gc_pax_h", "gc_per_pax_s", "riders", "walk_only"],
          [[r["plan"], r["budget"], round(r["gc"]/3600, 2), round(r["gc_per_pax"], 1),
            round(r["riders"], 1), round(r["walkonly"], 1)] for r in x["budget_axis"]])
        w("t15_crossover_density.csv",
          ["plan", "demand_scale", "gc_pax_h", "gc_per_pax_s", "riders",
           "transfers_per_rider"],
          [[r["plan"], r["scale"], round(r["gc"]/3600, 2), round(r["gc_per_pax"], 1),
            round(r["riders"], 1), round(r["transfers_per_rider"], 3)]
           for r in x["density_axis"]])

    gp = J("stage5_gap.json")
    if gp:
        w("t16_gap_decomposition.csv",
          ["component", "value_pax_h", "se_pax_h"],
          [["gap_total_sqrt_minus_optimizer", round(gp["gap_total"]["value"]/3600, 3),
            round(gp["gap_total"]["se"]/3600, 3)],
           ["congestion_dependent_cycle_time",
            round(gp["component_congestion"]["value"]/3600, 3),
            round(gp["component_congestion"]["se"]/3600, 3)],
           ["transfer_structure_demand_term",
            round(gp["component_transfer_structure"]["value"]/3600, 3),
            round(gp["component_transfer_structure"]["se"]/3600, 3)],
           ["noise_floor_resolvable", round((gp["noise_floor_resolvable"] or 0)/3600, 3), ""]])


if __name__ == "__main__":
    main()
