#!/usr/bin/env python3
"""
Deliverable (iv): turn the measured quantities into a stated decision rule.

Three diagnostic signals decide whether isolated-BCR ranking (or any additive
appraisal of a project portfolio) is safe, or whether a full combinatorial
search is required:
  D1 interaction magnitude  -- max and 90th-percentile |I(i,j)| as a share of
                               |B(i)| + |B(j)|
  D2 paradox project        -- does any single project have a replicated,
                               statistically significant NEGATIVE benefit
  D3 frontier non-concavity -- does the marginal return on budget ever INCREASE
Emitted to outputs/decision_diagnostics.json with the resulting verdict.
"""
import os, sys, json, csv
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "outputs")

D1_SAFE = 10.0        # % -- below this, additivity is a tolerable approximation
D1_ALARM = 25.0       # % -- above this, additive appraisal is unusable


def main():
    pairs = json.load(open(os.path.join(OUT, "interaction_matrix.json")))["pairs"]
    rel = sorted(abs(p["interaction_pct_of_sum"]) for p in pairs
                 if p["interaction_pct_of_sum"] is not None)
    d1_max = rel[-1]
    d1_p90 = rel[int(0.9 * (len(rel) - 1))]
    d1_median = st.median(rel)
    n_over_10 = sum(1 for r in rel if r > 10.0)

    fr = list(csv.DictReader(open(os.path.join(OUT, "pareto_frontier.csv"))))
    nonconcave = [r for r in fr if r.get("concave_here") == "False"]
    d3 = bool(nonconcave)

    d2, d2_detail = False, []
    p = os.path.join(OUT, "paradox_replication_summary.json")
    if os.path.exists(p):
        for s in json.load(open(p)):
            d2_detail.append(dict(arm=s["arm"], mean_diff=s["mean_diff"],
                                  ci95=[s["ci95_lo"], s["ci95_hi"]],
                                  p_ttest=s["p_ttest"], dz=s["cohens_dz"],
                                  verdict=s["verdict"]))
            if s["verdict"].startswith("HARMFUL"):
                d2 = True

    res = list(csv.DictReader(open(os.path.join(OUT, "results_table.csv"))))
    bcr_gaps = [(float(r["budget"]), float(r["benefit_shortfall_pct"] or 0))
                for r in res if r["method"] == "greedy_isolated_bcr"]
    vc_gaps = [(float(r["budget"]), float(r["benefit_shortfall_pct"] or 0))
               for r in res if r["method"] == "greedy_worst_vc"]

    # --- seed-robustness screen -------------------------------------------
    # The enumeration uses ONE seed (CRN).  The capacity-paradox replication
    # measured the seed-to-seed s.d. of a CRN-PAIRED difference (design minus
    # do-nothing, same seed in both arms).  Any single-seed difference smaller
    # than 2x that s.d. is not robust to the choice of seed.
    sd_paired = None
    if os.path.exists(p):
        sds = [s["sd_diff"] for s in json.load(open(p))]
        sd_paired = st.mean(sds)
    robust = None
    if sd_paired:
        thr = 2 * sd_paired
        robust = dict(
            pooled_paired_difference_sd=round(sd_paired, 1),
            interpretability_threshold_2sd=round(thr, 1),
            threshold_as_pct_of_do_nothing_tstt=None,
            rows=[])
        for r in res:
            if r["method"] in ("enumerated_optimum", "do_nothing"):
                continue
            g = abs(float(r["gap_vs_opt_s"]))
            robust["rows"].append(dict(budget=float(r["budget"]), method=r["method"],
                                       gap_vs_opt_s=float(r["gap_vs_opt_s"]),
                                       exceeds_2sd=bool(g > thr)))
        n_pairs_robust = sum(1 for pr in pairs
                             if abs(pr["interaction_s"]) > 2 * thr)
        robust["n_interaction_pairs_exceeding_2sd_of_I"] = n_pairs_robust
        robust["interaction_2sd_threshold"] = round(2 * thr, 1)
        robust["note"] = ("I(i,j) is a difference of two paired differences, so "
                          "its own 2-sigma threshold is twice the single-difference one")

    trigger = (d1_max > D1_ALARM) or d2 or d3
    out = dict(
        D1_interaction_magnitude=dict(
            max_pct=round(d1_max, 2), p90_pct=round(d1_p90, 2),
            median_pct=round(d1_median, 2), n_pairs=len(rel),
            n_pairs_over_10pct=n_over_10,
            safe_threshold_pct=D1_SAFE, alarm_threshold_pct=D1_ALARM,
            verdict=("additivity tolerable" if d1_max <= D1_SAFE else
                     "additivity questionable" if d1_max <= D1_ALARM else
                     "additivity unusable")),
        D2_paradox_project=dict(present=d2, arms=d2_detail),
        D3_frontier_nonconcavity=dict(
            present=d3,
            budgets_where_marginal_return_increases=[float(r["budget"]) for r in nonconcave]),
        observed_cost_of_ignoring=dict(
            isolated_bcr_benefit_shortfall_pct_by_budget=bcr_gaps,
            worst_vc_benefit_shortfall_pct_by_budget=vc_gaps,
            worst_isolated_bcr_shortfall_pct=max((g for _, g in bcr_gaps), default=None),
            worst_worst_vc_shortfall_pct=max((g for _, g in vc_gaps), default=None)),
        seed_robustness=robust,
        DECISION=("RUN A FULL COMBINATORIAL SEARCH" if trigger else
                  "isolated-BCR ranking is defensible"),
        trigger_reasons=[r for r, c in
                         [("D1 interaction magnitude above alarm threshold", d1_max > D1_ALARM),
                          ("D2 a replicated capacity-paradox project exists", d2),
                          ("D3 the budget-benefit frontier is non-concave", d3)] if c],
    )
    with open(os.path.join(OUT, "decision_diagnostics.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
