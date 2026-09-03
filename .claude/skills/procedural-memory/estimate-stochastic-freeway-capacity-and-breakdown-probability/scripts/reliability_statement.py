#!/usr/bin/env python3
"""Task step 8/9: the reliability-based design statement, and the honest verdict on
whether SUMO's capacity distribution is degenerate relative to field data.

Field reference: empirical stochastic-capacity studies on freeway bottlenecks report a
capacity coefficient of variation of roughly 5-12% (Brilon/Geistefeldt German motorway
data; Elefteriadou et al. US ramp-merge data). The question this experiment was built
to answer is whether SUMO reproduces that at all, or collapses to a near-deterministic
number.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import km  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
A = os.path.join(ROOT, "analysis")
FIELD_CV_RANGE = [5.0, 12.0]
N_LANES = 2


def load(n):
    p = os.path.join(A, n)
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    kmres = load("km_main.json")
    det = load("deterministic_vs_stochastic_vs_hcm.json")
    dt = load("dt_convergence.json")
    sweep_cv, sweep_cv_ident = [], []
    import csv
    for r in csv.DictReader(open(os.path.join(A, "breakdown_definition_sweep.csv"))):
        if not r.get("weibull_cv_pct") or r["interval_min"] != "5":
            continue
        if int(r["n_uncensored"]) >= 100:
            sweep_cv.append(float(r["weibull_cv_pct"]))
        # "well-identified" cells: >=90% of days actually broke down, so the fitted
        # distribution is not an extrapolation
        if int(r["n_days_broke_down"]) >= 0.9 * int(r["n_days"]):
            sweep_cv_ident.append(float(r["weibull_cv_pct"]))
    w = kmres["weibull"]
    q05, q10 = kmres["weibull_q_at_p"]["p05"], kmres["weibull_q_at_p"]["p10"]
    bs = kmres["bootstrap"]

    cv_dt = [v["weibull_cv_pct"] for v in dt["per_dt"].values()] if dt else []

    degenerate = w["cv_pct"] < FIELD_CV_RANGE[0]
    res = dict(
        headline_question="Can SUMO reproduce field-observed freeway capacity variability?",
        verdict=("NO -- degenerate" if degenerate else "YES -- not degenerate"),
        field_reference_cv_pct_range=FIELD_CV_RANGE,
        measured=dict(
            base_definition="station mrg (at the merge), speed<80 km/h sustained 5 min, 5-min aggregation",
            n_days=kmres["n_days"], n_uncensored=kmres["n_uncensored"],
            n_censored=kmres["n_censored"],
            weibull_cv_pct=round(w["cv_pct"], 2),
            weibull_cv_noise_corrected_pct=kmres["poisson_counting_noise"]
            ["weibull_cv_after_removing_counting_noise_pct"],
            raw_uncensored_cv_pct=kmres["raw_uncensored"]["cv_pct"],
            weibull_shape_k=round(w["shape_k"], 3),
            shape_k_ci95=bs["shape_k_ci"],
            weibull_mean_vph=round(w["mean"], 1),
            weibull_mean_ci95=bs["mean_ci"]),
        robustness_of_the_CV_conclusion=dict(
            cv_across_5min_definition_cells_ge100_events=dict(
                n_cells=len(sweep_cv), min=round(min(sweep_cv), 2), max=round(max(sweep_cv), 2))
            if sweep_cv else None,
            cv_across_5min_WELL_IDENTIFIED_cells=dict(
                criterion=">=90% of days broke down, 5-min aggregation",
                n_cells=len(sweep_cv_ident), min=round(min(sweep_cv_ident), 2),
                max=round(max(sweep_cv_ident), 2))
            if sweep_cv_ident else None,
            cv_across_dt_sweep=dict(values=cv_dt, min=round(min(cv_dt), 2), max=round(max(cv_dt), 2))
            if cv_dt else None,
            frac_well_identified_cells_inside_field_band=round(
                float(np.mean([(FIELD_CV_RANGE[0] <= c <= FIELD_CV_RANGE[1])
                               for c in sweep_cv_ident])), 4) if sweep_cv_ident else None,
            frac_dt_cells_inside_field_band=round(
                float(np.mean([(FIELD_CV_RANGE[0] <= c <= FIELD_CV_RANGE[1])
                               for c in cv_dt])), 4) if cv_dt else None,
            note=("every dt cell (4/4) lands inside the field-observed 5-12% band. "
                  "Among the 47 well-identified 5-min definition cells, most land "
                  "inside the band and the remainder overshoot it (max 14.44%) -- the "
                  "CV is never BELOW the field band, so the distribution is nowhere "
                  "near degenerate under any definition tested. The capacity LEVEL, by "
                  "contrast, is strongly dt-dependent.")),
        reliability_based_design_statement=dict(
            flow_at_5pct_breakdown_probability=dict(
                total_vph=round(q05, 1), per_lane_vph=round(q05 / N_LANES, 1),
                ci95_total=[round(x, 1) for x in bs["q_at_p05_ci"]]),
            flow_at_10pct_breakdown_probability=dict(
                total_vph=round(q10, 1), per_lane_vph=round(q10 / N_LANES, 1),
                ci95_total=[round(x, 1) for x in bs["q_at_p10_ci"]]),
            weibull_mean_capacity=dict(
                total_vph=round(w["mean"], 1), per_lane_vph=round(w["mean"] / N_LANES, 1),
                breakdown_probability_at_this_flow=round(
                    100 * float(km.weibull_cdf(w, w["mean"])), 1)),
            km_median_capacity_vph=kmres["kaplan_meier"]["median_vph"],
            deterministic_capacity_for_the_same_bottleneck=dict(
                queue_release_probe_vph=det["deterministic_numbers"]
                ["memory_methodA_queue_release_mean5seeds"]["q_vph_total"],
                queue_release_probe_percentile=det["deterministic_numbers"]
                ["memory_methodA_queue_release_mean5seeds"]
                ["percentile_of_stochastic_capacity_distribution"],
                flat_oversaturation_vph=det["deterministic_numbers"]
                ["memory_methodB_flat_oversat_q_in_4200"]["q_vph_total"],
                flat_oversaturation_percentile=det["deterministic_numbers"]
                ["memory_methodB_flat_oversat_q_in_4200"]
                ["percentile_of_stochastic_capacity_distribution"]),
            hcm_reference_vph=det["hcm_reference"]["posted_limit_120kmh"]["capacity_veh_h_total"],
            statement=(
                f"For this 2-lane freeway on-ramp merge, a flow of "
                f"{q05:.0f} veh/h ({q05/N_LANES:.0f} veh/h/ln) can be sustained at a 5% "
                f"probability of breakdown per 5-min interval, and {q10:.0f} veh/h "
                f"({q10/N_LANES:.0f} veh/h/ln) at a 10% probability. The mean of the "
                f"capacity distribution, {w['mean']:.0f} veh/h, carries a "
                f"{100*float(km.weibull_cdf(w, w['mean'])):.0f}% breakdown probability and is "
                f"therefore NOT a safe design flow. The deterministic queue-discharge "
                f"'capacity' that memory's existing skills would report for this same "
                f"bottleneck, "
                f"{det['deterministic_numbers']['memory_methodA_queue_release_mean5seeds']['q_vph_total']:.0f} "
                f"veh/h, is close to the 5%-breakdown design flow (it sits at the "
                f"{det['deterministic_numbers']['memory_methodA_queue_release_mean5seeds']['percentile_of_stochastic_capacity_distribution']:.1f}th "
                f"percentile) -- it is a conservative near-worst-case number, not a "
                f"central estimate.")),
        implication_for_capacity_numbers_already_in_memory=(
            "Memory's stored deterministic freeway-bottleneck capacities (e.g. 1826 and "
            "1599 pc/h/ln in `design-and-control-freeway-work-zone-lane-closures`, "
            "1900.4/1791.3 veh/h in `compare-zipper-vs-default-merge-at-lane-drop`) are "
            "QUEUE-DISCHARGE rates measured after breakdown. Verified here: the "
            "queue-release probe's number matches the stochastic experiment's own "
            "post-breakdown discharge to 0.094%, while sitting at the ~3rd percentile of "
            "the PRE-breakdown capacity distribution. Those stored numbers are therefore "
            "valid as discharge rates and as conservative design flows, but they are NOT "
            "the mean capacity and must not be compared directly against an HCM capacity, "
            "which is a pre-breakdown quantity."),
        honest_caveats=[
            "The capacity LEVEL is NOT dt-converged: CRN-paired mean pre-breakdown flow "
            "was +14.76% at dt=1.0 s and +8.23% at dt=0.5 s (the dt used here) against a "
            "dt=0.25 s reference, and still fell a further -4.95% from dt=0.25 s to "
            "dt=0.1 s (all p<0.006, n=30 CRN days). Absolute veh/h figures should be "
            "treated as accurate to no better than ~10-15%.",
            f"The CV / distribution shape, which is what this study is actually about, is "
            f"far more robust: {min(cv_dt):.2f}-{max(cv_dt):.2f}% across the whole dt sweep, "
            f"{min(sweep_cv_ident):.2f}-{max(sweep_cv_ident):.2f}% across the "
            f"{len(sweep_cv_ident)} well-identified 5-min definition cells (>=90% of days "
            f"breaking down), and {min(sweep_cv):.2f}-{max(sweep_cv):.2f}% across all "
            f"{len(sweep_cv)} 5-min cells with >=100 events.",
            "SUMO reported large 'collision' counts (mean 1105/day, main arm), but "
            "99.859% of these are minGap-threshold violations rather than physical "
            "overlaps, and they provably do not affect the measurement (see "
            "collision_mechanism.json).",
        ])
    json.dump(res, open(os.path.join(A, "reliability_design_statement.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
