#!/usr/bin/env python3
"""Render results.json into results_table.md (the human-readable results tables)."""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))


def f(x, nd=1, dash="n/a"):
    if x is None or x == "":
        return dash
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v != v:
        return dash
    return ("%%.%df" % nd) % v


def main():
    R = json.load(open(os.path.join(OUTDIR, "results.json")))
    L = []
    A = L.append
    A("# Results tables\n")
    A("All capacities are **total 2-lane bottleneck discharge flow in veh/h** measured at the "
      "E1 array 10 m downstream of the lane drop. `+/-` is a 95% t confidence half-width over "
      "replications.\n")

    # ---- Table 0: bottleneck really binds
    A("\n## Table 0 - The bottleneck, not the network entry, limits flow\n")
    A("| fleet | bottleneck discharge | entry served while approach free-flowing | max entry flow this run "
      "| entry capacity, NO-LANE-DROP control net | speed just downstream of the drop while the queue discharges | max approach density | verdict |")
    A("|---|---|---|---|---|---|---|---|")
    for b in R.get("bottleneck_is_binding", []):
        A("| %s | %s | %s | %s | %s | %s m/s | %s veh/km (3 lanes) | %s |" % (
            b["fleet"], f(b["bottleneck_discharge"]), f(b["entry_served_while_freeflow"]),
            f(b["entry_max_this_run"]), f(b.get("entry_capacity_nodrop_control")),
            f(b.get("downstream_speed_while_queue_discharges"), 2),
            f(b.get("max_upstream_density")), b["verdict"]))

    # ---- Table 1: homogeneous baselines
    A("\n## Table 1 - Homogeneous (100%) fleet baselines\n")
    A("| fleet | car-following model | tau (s) | discharge capacity | +/- 95% CI | per lane | vs HUMAN | "
      "pre-breakdown peak | capacity drop | drop estimable in | demand at breakdown | "
      "fraction of time queued | discharge oscillation CV | mean travel time (s) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in R.get("homogeneous_baselines", []):
        cd = h.get("capacity_drop_pct")
        cd_s = "%s%%" % f(cd, 1) if h.get("capacity_drop_estimable_frac", 0) >= 0.5 else "not estimable"
        A("| **%s** | %s | %s | **%s** | %s | %s | %s%% | %s | %s | %s of seeds | %s | %s | %s | %s |" % (
            h["fleet"], h["model"], f(h["tau"], 1), f(h["discharge"]), f(h["ci95"]),
            f(h["per_lane"]), f(h["vs_human_pct"], 2), f(h["pre_breakdown_peak"]), cd_s,
            f(100 * h.get("capacity_drop_estimable_frac", 0), 0) + "%",
            f(h.get("demand_at_breakdown"), 0),
            f(h.get("frac_time_queued"), 3), f(h.get("discharge_oscillation_cv"), 4),
            f(h["mean_travel_time"])))

    # ---- Table 2: mechanism decomposition
    A("\n## Table 2 - Mechanism decomposition (paired on matched seeds, Common Random Numbers)\n")
    A("| contrast | what it isolates | from | to | difference | +/- 95% CI | % | distinguishable at 95%? |")
    A("|---|---|---|---|---|---|---|---|")
    for k, v in R.get("mechanism_decomposition_paired", {}).items():
        A("| %s | %s | %s | %s | **%s** | %s | %s%% | %s |" % (
            k, v["why"], f(v["mean_a"]), f(v["mean_b"]), f(v["diff"]), f(v["ci95"]),
            f(v["pct"], 2), "YES" if v["significant_at_95"] else "**no**"))

    # ---- Table 3: penetration sweep
    A("\n## Table 3 - Penetration sweep: discharge capacity vs. AV share\n")
    for arm, d in R.get("penetration_sweeps", {}).items():
        A("\n### %s mixed into HUMAN traffic\n" % arm)
        A("| p | discharge | +/- 95% CI | mean travel time (s) | breakdown fraction | "
          "demand at breakdown (veh/h) |")
        A("|---|---|---|---|---|---|")
        for i, p in enumerate(d["p"]):
            A("| %.0f%% | %s | %s | %s | %s | %s |" % (
                p * 100, f(d["discharge_mean"][i]),
                f(d["ci95"][i]) if i < len(d["ci95"]) else "n/a",
                f(d["travel_time"][i]) if i < len(d["travel_time"]) else "n/a",
                f(d["breakdown_frac"][i], 2) if i < len(d["breakdown_frac"]) else "n/a",
                f(d.get("demand_at_breakdown", [])[i], 0)
                if i < len(d.get("demand_at_breakdown", [])) else "n/a"))
        A("\n**Adjacent-level tests** (paired on seed):\n")
        A("| step | difference | +/- 95% CI | n pairs | statistically distinguishable? |")
        A("|---|---|---|---|---|")
        for a in d.get("adjacent_tests", []):
            A("| %.0f%% -> %.0f%% | %s | %s | %d | %s |" % (
                a["from_p"] * 100, a["to_p"] * 100, f(a["diff"]), f(a["ci95"]),
                a.get("n_pairs", 0), "YES" if a["distinguishable_at_95"] else "**NO**"))
        A("\n**Each level vs. 0% AV** (paired):\n")
        A("| p | difference vs p=0 | +/- 95% CI | distinguishable from all-human? |")
        A("|---|---|---|---|")
        for a in d.get("vs_p0_tests", []):
            A("| %.0f%% | %s | %s | %s |" % (a["p"] * 100, f(a["diff"]), f(a["ci95"]),
                                             "YES" if a["distinguishable_from_p0"] else "**NO**"))
        fit = d.get("fit", {})
        A("\n**Curve-shape fit** (capacity vs p, fitted to the %d level means):\n" % len(d["p"]))
        A("| degree | RMSE (veh/h) | max abs residual | R2 | adj R2 | residuals |")
        A("|---|---|---|---|---|---|")
        for deg in ("1", "2", "3"):
            g = fit.get(deg) or fit.get(int(deg))
            if not g:
                continue
            A("| %s | %s | %s | %s | %s | %s |" % (
                deg, f(g["rmse"], 1), f(g["max_abs_resid"], 1), f(g["r2"], 4),
                f(g["adj_r2"], 4), ", ".join("%+.0f" % r for r in g["resid"])))
        if "F_quad_over_lin" in fit:
            A("\nF-test, quadratic over linear: F(%d,%d) = %s vs 0.95 critical %s -> "
              "quadratic term **%s**.  Sign of the quadratic coefficient: **%s**.\n"
              % (fit["F_df"][0], fit["F_df"][1], f(fit["F_quad_over_lin"], 2),
                 f(fit.get("F_crit_0.95"), 2),
                 "justified" if fit.get("quadratic_justified") else "NOT justified",
                 fit.get("quad_coef_sign", "n/a")))

    # ---- Table 4: arrangement
    A("\n## Table 4 - Arrangement effect at 50% penetration (identical AV count)\n")
    A("| arm | random | platooned | difference | +/- 95% CI | significant? | "
      "p=0 capacity | p=100% capacity | full-penetration benefit | recovered by random | "
      "recovered by platooning | arrangement's share of the full benefit |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for arm, d in R.get("arrangement_effect", {}).items():
        A("| **%s** | %s | %s | **%s** | %s | %s | %s | %s | %s | %s%% | %s%% | %s%% |" % (
            arm, f(d["random_mean"]), f(d["platoon_mean"]), f(d["diff"]), f(d["ci95"]),
            "YES" if d["significant_at_95"] else "**no**",
            f(d["p0_capacity"]), f(d["p100_capacity"]), f(d["full_penetration_benefit"]),
            f(d.get("recovered_by_random_pct")), f(d.get("recovered_by_platoon_pct")),
            f(d.get("arrangement_share_of_full_benefit_pct"))))

    A("\n### Why arrangement helps (or does not): measured leader composition and gaps\n")
    A("| arm | P(leader is AV \\| ego is AV), random | ... platooned | mean gap AV-behind-AV, random (m) | "
      "... platooned (m) | mean gap AV-behind-HUMAN, random (m) | ... platooned (m) |")
    A("|---|---|---|---|---|---|---|")
    for arm, d in R.get("arrangement_effect", {}).items():
        A("| %s | %s | %s | %s | %s | %s | %s |" % (
            arm, f(d.get("leader_av_given_av_random"), 4), f(d.get("leader_av_given_av_platoon"), 4),
            f(d.get("gap_av_behind_av_random"), 2), f(d.get("gap_av_behind_av_platoon"), 2),
            f(d.get("gap_av_behind_hv_random"), 2), f(d.get("gap_av_behind_hv_platoon"), 2)))

    # ---- Table 5: leader-is-AV
    A("\n## Table 5 - Directly measured leader-is-AV fraction (NOT assumed to be p or p^2)\n")
    A("| arm | p | arrangement | measured P(leader is AV \\| ego is AV) | naive p | naive p^2 | "
      "realised AV share in the measurement zone | P(leader is AV) over all vehicles | "
      "median time gap behind an AV (s) | median time gap behind a HUMAN (s) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for arm, seq in R.get("leader_is_av_fraction", {}).items():
        for s in seq:
            A("| %s | %.0f%% | %s | **%s** | %s | %s | %s | %s | %s | %s |" % (
                arm, s["p"] * 100, s.get("arrangement", "random"), f(s["measured"], 4),
                f(s["naive_p"], 2), f(s["naive_p_squared"], 3),
                f(s.get("realized_share_in_zone"), 4), f(s.get("overall_leader_av"), 4),
                f(s.get("timegap_behind_av"), 3), f(s.get("timegap_behind_human"), 3)))
    A("\nThe last two columns are the decisive in-traffic test of whether SUMO's CACC actually "
      "cooperates: a leader-aware model keeps a TIGHTER time gap behind an equipped leader than "
      "behind a human one.\n")

    A("\n## Table 5b - How much of each fleet's PURE car-following capacity does the bottleneck deliver?\n")
    A("The 2-vehicle probe gives each fleet's effective time gap with no lane changing and no "
      "network effects.  Evaluated at the discharge speed actually observed just downstream of "
      "the drop, that gives the capacity the fleet's car-following alone could sustain.  The "
      "shortfall is everything car-following does NOT explain - lane-change turbulence at the "
      "drop and stop-and-go oscillation.\n")
    A("| fleet | effective tau from probe (s) | observed discharge speed (m/s) | "
      "pure car-following capacity, 2 lanes | measured bottleneck discharge | efficiency | "
      "shortfall (veh/h) | discharge oscillation CV |")
    A("|---|---|---|---|---|---|---|---|")
    for c in R.get("carfollowing_vs_network_capacity", []):
        A("| **%s** | %s | %s | %s | %s | **%s%%** | %s | %s |" % (
            c["fleet"], f(c["effective_tau_from_probe"], 3), f(c["observed_discharge_speed"], 2),
            f(c["pure_carfollowing_capacity_2lane"], 0), f(c["measured_bottleneck_discharge"]),
            f(c["efficiency_pct"], 1), f(c["shortfall_veh_per_h"], 0),
            f(c["discharge_oscillation_cv"], 4)))

    # ---- Table 6: CRN + cross-check + warm-up
    A("\n## Table 6 - Statistical methodology diagnostics\n")
    A("\n### Common Random Numbers effectiveness (p=40% vs p=0, discharge)\n")
    A("| arm | paired correlation | Var(diff) paired | Var(diff) if independent | variance reduction factor |")
    A("|---|---|---|---|---|")
    for arm, d in R.get("crn_effectiveness_p40_vs_p0", {}).items():
        A("| %s | %s | %s | %s | %s |" % (arm, f(d["paired_correlation"], 3),
                                          f(d["var_of_diff_paired"]), f(d["var_of_diff_if_independent"]),
                                          f(d.get("variance_reduction_factor"), 2)))
    cc = R.get("vtypedistribution_crosscheck")
    if cc:
        A("\n### Cross-check: explicit per-vehicle type assignment vs SUMO's own `<vTypeDistribution>` "
          "(ACC, p=40%)\n")
        A("| method | n | mean discharge | sd | +/- 95% CI |")
        A("|---|---|---|---|---|")
        for k in ("explicit_assignment", "sumo_vTypeDistribution"):
            v = cc[k]
            A("| %s | %d | %s | %s | %s |" % (k, v["n"], f(v["mean"]), f(v["sd"]), f(v["ci"])))
        A("\n%s\n" % cc["note"])
    A("\n### Empirical warm-up (MSER-5) outcome across all cells\n")
    A("| flag | number of cells |")
    A("|---|---|")
    for k, v in sorted(R.get("warmup_flags", {}).items()):
        A("| `%s` | %d |" % (k, v))

    out = os.path.join(OUTDIR, "results_table.md")
    open(out, "w").write("\n".join(L) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
