#!/usr/bin/env python3
"""
Render every headline table as markdown straight from the CSV/JSON output files,
so that no number in the write-up is transcribed by hand.
Writes outputs/tables.md
"""
import os, sys, csv, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "outputs")


def md(rows, cols, headers=None, fmt=None):
    headers = headers or cols
    fmt = fmt or {}
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if c in fmt and v not in ("", None):
                try:
                    v = fmt[c] % float(v)
                except (TypeError, ValueError):
                    pass
            cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def rd(name):
    return list(csv.DictReader(open(os.path.join(OUT, name))))


def main():
    S = []
    A = S.append

    A("## T1  Candidate project set and compiled-network verification\n")
    A("_source: `outputs/project_verification.csv`_\n")
    A(md(rd("project_verification.csv"),
         ["project", "kind", "cost", "desc", "n_new_edges", "n_edges_lane_changed",
          "delta_lane_metres", "n_tls_programs_changed", "is_real_change"],
         ["id", "kind", "cost (MU)", "description", "new edges", "edges relaned",
          "Δ lane-m", "tlLogic programs changed", "real change?"]))

    A("\n## T2  Demand sweep: locating the flow-vs-demand knee (do-nothing network)\n")
    A("_source: `outputs/demand_sweep.csv`, v/c recomputed in `outputs/vc_calibration.json`_\n")
    vc = json.load(open(os.path.join(OUT, "vc_calibration.json")))
    lv = {r["nveh"]: r for r in vc["levels"]}
    rows = []
    for r in rd("demand_sweep.csv"):
        n = int(r["nveh"]); L = lv.get(n, {})
        t = [v for _, v in L.get("top12", [])]
        rows.append(dict(r, top4=("%.3f" % (sum(t[:4]) / 4)) if t else "",
                         top6=("%.3f" % (sum(t[:6]) / 6)) if t else "",
                         top12=("%.3f" % (sum(t) / 12)) if t else "",
                         maxvc=("%.3f" % max(t)) if t else ""))
    A(md(rows, ["nveh", "arrived", "not_inserted", "teleports", "mean_dur",
                "peak_served_flow_sum", "top4", "top6", "top12", "maxvc"],
         ["scheduled veh", "arrived", "never inserted", "teleports",
          "mean trip dur (s)", "Σ peak flow on top-12 edges (veh/h)",
          "mean v/c top-4", "top-6", "top-12", "max v/c"],
         {"mean_dur": "%.1f", "peak_served_flow_sum": "%.0f"}))
    A("\n(v/c uses the empirically calibrated effective saturation flow "
      "s_eff = %.0f veh/h/lane, the 95th percentile of flow/(lanes x g/C) over "
      "saturated grid edges at demand >= 4000 veh; n=%d samples, median %.0f, "
      "p90 %.0f.)\n" % (vc["s_eff_veh_h_lane"], vc["n_samples"], vc["median"], vc["p90"]))

    A("\n## T3  duaIterate convergence trace, cold start, do-nothing, 4000 veh\n")
    c = json.load(open(os.path.join(OUT, "convergence_study.json")))
    A("_source: `outputs/convergence_study.json` (%d iterations, %.1f s wall, "
      "%.2f s/iteration single-threaded)_\n"
      % (c["n_steps"], c["wall_s"], c["wall_s"] / c["n_steps"]))
    A(md(c["rows"], ["step", "rel_gap", "mean_dur"],
         ["iteration", "relative gap", "mean in-network trip duration (s)"]))

    A("\n## T4  Warm-start validation (REJECTED protocol)\n")
    A("_source: `outputs/warmstart_validation.csv`_\n")
    A(md(rd("warmstart_validation.csv"),
         ["subset", "cold_tstt", "warm_tstt", "diff_pct", "cold_sd_pct",
          "warm_sd_pct", "cold_gap", "warm_gap", "cold_wall_s", "warm_wall_s"],
         ["subset", "cold TSTT (veh-s)", "warm TSTT (veh-s)", "warm-cold %",
          "cold tail SD %", "warm tail SD %", "cold rel gap", "warm rel gap",
          "cold wall s", "warm wall s"]))

    A("\n## T5  Single projects appraised in isolation against do-nothing\n")
    A("_source: `outputs/singleton_projects.csv`_\n")
    A(md(rd("singleton_projects.csv"),
         ["project", "cost", "tstt", "benefit_s", "benefit_pct",
          "pv_benefits_mu", "npv_mu", "bcr", "rel_gap", "converged"],
         ["id", "cost (MU)", "TSTT (veh-s)", "benefit (veh-s)", "benefit %",
          "PV benefits (MU)", "NPV (MU)", "isolated BCR", "rel gap", "converged"],
         {"tstt": "%.0f", "benefit_s": "%.0f", "pv_benefits_mu": "%.3f",
          "npv_mu": "%.3f", "bcr": "%.3f"}))

    A("\n## T6  Design-search results at every budget level\n")
    A("_source: `outputs/results_table.csv`_\n")
    A(md(rd("results_table.csv"),
         ["budget", "method", "subset", "cost", "tstt_s", "benefit_s",
          "benefit_pct", "pv_benefits_mu", "npv_mu", "bcr", "gap_vs_opt_s",
          "gap_vs_opt_pct", "benefit_shortfall_pct", "npv_gap_mu"],
         ["budget", "method", "subset", "cost", "TSTT (veh-s)", "benefit (veh-s)",
          "benefit %", "PV ben (MU)", "NPV (MU)", "BCR", "TSTT gap vs opt (s)",
          "gap %", "benefit shortfall %", "NPV gap (MU)"],
         {"tstt_s": "%.0f", "benefit_s": "%.0f", "pv_benefits_mu": "%.3f",
          "npv_mu": "%.3f", "gap_vs_opt_s": "%.0f"}))

    A("\n## T7  Budget vs best achievable benefit (Pareto frontier)\n")
    A("_source: `outputs/pareto_frontier.csv`, figure `outputs/pareto_frontier.png`_\n")
    A(md(rd("pareto_frontier.csv"),
         ["budget", "n_feasible", "best_subset", "best_cost", "best_tstt_s",
          "best_benefit_s", "best_benefit_pct", "best_npv_mu",
          "marginal_benefit_in", "marginal_benefit_out", "concave_here"],
         ["budget", "# feasible subsets", "best subset", "cost", "TSTT (veh-s)",
          "benefit (veh-s)", "benefit %", "NPV (MU)",
          "marginal benefit in (veh-s/MU)", "marginal benefit out", "concave here?"],
         {"best_tstt_s": "%.0f", "best_benefit_s": "%.0f", "best_npv_mu": "%.3f"}))

    A("\n## T8  Strongest project interactions\n")
    A("_source: `outputs/interaction_matrix_pairs.csv`, figure "
      "`outputs/interaction_heatmap.png`_\n")
    pr = rd("interaction_matrix_pairs.csv")
    pr.sort(key=lambda r: -float(r["interaction_s"]))
    A("**Most complementary (I > 0: the pair is worth more than the sum of its parts)**\n")
    A(md(pr[:6], ["i", "j", "benefit_i", "benefit_j", "benefit_ij",
                  "interaction_s", "interaction_pct_of_sum"],
         ["i", "j", "B(i) veh-s", "B(j) veh-s", "B(i+j) veh-s", "I(i,j) veh-s",
          "I as % of |B(i)|+|B(j)|"],
         {"benefit_i": "%.0f", "benefit_j": "%.0f", "benefit_ij": "%.0f",
          "interaction_s": "%.0f"}))
    A("\n**Most substitutive (I < 0: the pair is worth less than the sum of its parts)**\n")
    A(md(pr[-6:], ["i", "j", "benefit_i", "benefit_j", "benefit_ij",
                   "interaction_s", "interaction_pct_of_sum"],
         ["i", "j", "B(i) veh-s", "B(j) veh-s", "B(i+j) veh-s", "I(i,j) veh-s",
          "I as % of |B(i)|+|B(j)|"],
         {"benefit_i": "%.0f", "benefit_j": "%.0f", "benefit_ij": "%.0f",
          "interaction_s": "%.0f"}))

    p = os.path.join(OUT, "paradox_replication_summary.json")
    if os.path.exists(p):
        A("\n## T9  Capacity-paradox replication (10 CRN seed pairs, cold start)\n")
        A("_source: `outputs/paradox_replication_summary.json`, per-run values in "
          "`outputs/paradox_replication_runs.csv`_\n")
        rows = json.load(open(p))
        for r in rows:
            r["ci95"] = "[%+.0f, %+.0f]" % (r["ci95_lo"], r["ci95_hi"])
            r["seeds_pos"] = "%d/%d" % (r["n_seeds_positive"], r["n"])
        A(md(rows, ["arm", "mean_base", "mean_arm", "mean_diff", "mean_diff_pct",
                    "sd_diff", "p_ttest", "p_wilcoxon", "cohens_dz", "ci95",
                    "seeds_pos", "verdict"],
             ["project", "mean TSTT do-nothing", "mean TSTT with project",
              "mean paired Δ (veh-s)", "Δ %", "SD of Δ", "p (paired t)",
              "p (Wilcoxon)", "Cohen's dz", "bootstrap 95% CI on Δ",
              "seeds with Δ>0", "verdict"],
             {"mean_base": "%.0f", "mean_arm": "%.0f", "mean_diff": "%+.0f",
              "mean_diff_pct": "%+.3f", "sd_diff": "%.0f", "p_ttest": "%.5f",
              "p_wilcoxon": "%.5f", "cohens_dz": "%+.3f"}))

    p = os.path.join(OUT, "noise_floor.json")
    if os.path.exists(p):
        A("\n## T10  Evaluation noise floor\n")
        nf = json.load(open(p))
        A("_source: `outputs/noise_floor.json` -- protocol: %s_\n" % nf["protocol"])
        A(md(nf["designs"], ["subset", "n", "mean", "sd", "cv_pct", "min", "max"],
             ["design", "n seeds", "mean TSTT", "SD", "CV %", "min", "max"],
             {"mean": "%.0f", "sd": "%.0f", "min": "%.0f", "max": "%.0f"}))

    A("\n## T11  Economic parameters and their provenance\n")
    A("_source: `outputs/econ_parameter_provenance.csv`_\n")
    A(md(rd("econ_parameter_provenance.csv"), ["name", "value", "unit", "provenance"],
         ["parameter", "value", "unit", "provenance"]))

    txt = "\n".join(S) + "\n"
    with open(os.path.join(OUT, "tables.md"), "w") as f:
        f.write("# DNDP result tables (auto-generated from the output files)\n\n" + txt)
    print("wrote", os.path.join(OUT, "tables.md"), len(txt), "chars")


if __name__ == "__main__":
    main()
