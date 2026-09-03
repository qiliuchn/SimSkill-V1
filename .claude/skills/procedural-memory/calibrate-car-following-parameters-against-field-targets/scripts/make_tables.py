#!/usr/bin/env python3
"""Render the deliverable markdown tables from the JSON results."""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import OUT, TARGETS
TB = os.path.join(OUT, "tables")
FEATS = ["v_free_kmh", "q_max", "k_crit", "k_jam", "w_kmh"]


def morris_md():
    L = ["# Morris elementary-effects sensitivity screening",
         "",
         "`mu*` = mean |elementary effect| (overall influence); `sigma` = sd of the",
         "elementary effects (non-linearity / interaction). Every response is",
         "normalised by its own empirical target, so mu* is comparable across",
         "features and across models. Screening was run BEFORE any optimisation.",
         ""]
    for model in ("Krauss", "IDM"):
        p = os.path.join(TB, "morris_%s.json" % model)
        if not os.path.exists(p):
            continue
        M = json.load(open(p))
        L += ["## %s  (k=%d parameters, r=%d trajectories, %d simulations, %d failed)"
              % (model, M["k"], M["r"], M["n_eval"], M["n_failed"]), ""]
        params = [r["param"] for r in M["table"]["obj"]]
        head = "| parameter | range | mu*(obj) | " + " | ".join(
            "mu*(%s)" % f.replace("_kmh", "").replace("v_free", "v_f") for f in FEATS) + " |"
        L += [head, "|" + "---|" * (len(FEATS) + 3)]
        for pr in params:
            rng = M["param_ranges"][pr]
            row = ["`%s`" % pr, "%g-%g (def %g)" % (rng[0], rng[1], rng[2])]
            o = next(r for r in M["table"]["obj"] if r["param"] == pr)
            row.append("**%.3f**" % o["mu_star"])
            for f in FEATS:
                r = next(x for x in M["table"][f] if x["param"] == pr)
                rank = [x["param"] for x in M["table"][f]].index(pr) + 1
                row.append("%.3f%s" % (r["mu_star"], " (1st)" if rank == 1 else ""))
            L.append("| " + " | ".join(row) + " |")
        L += ["", "Dominant control per feature: " + ", ".join(
            "%s -> `%s`" % (f, M["table"][f][0]["param"]) for f in FEATS), ""]
    open(os.path.join(OUT, "SENSITIVITY_TABLE.md"), "w").write("\n".join(L))
    print("wrote SENSITIVITY_TABLE.md")


def scorecards_md():
    p = os.path.join(TB, "H2_default_bias.json")
    if not os.path.exists(p):
        return
    H = json.load(open(p))
    L = ["# Calibration scorecards (8-seed CRN replication, 95% CI)", ""]
    for model, o in H.items():
        cal = o["calibrated_params"]
        L += ["## %s" % model, "",
              "Calibrated by: **%s**" % o["best_optimizer"], "",
              "| feature | target | SUMO default (95% CI) | err | calibrated (95% CI) | err | gap closed | within tol |",
              "|---|---|---|---|---|---|---|---|"]
        for k in FEATS:
            g = o["gap_analysis"][k]
            d, c = o["default"][k], o["calibrated"][k]
            tol = TARGETS[k]["tol"]
            L.append("| %s (%s) | %.1f | %.1f ± %.2f | %+.1f%% | %.1f ± %.2f | %+.1f%% | %.0f%% | %s |"
                     % (k, TARGETS[k]["unit"], TARGETS[k]["target"], d["mean"], d["ci"],
                        g["default_pct"], c["mean"], c["ci"], g["calib_pct"],
                        g["gap_closed_pct"],
                        "yes" if abs(c["mean"] - TARGETS[k]["target"]) <= tol else "NO"))
        sd_, sc_ = o["scorecard_default"], o["scorecard_calibrated"]
        L += ["",
              "- weighted RMSN: **%.1f%% -> %.1f%%**" % (sd_["rmsn_pct"], sc_["rmsn_pct"]),
              "- GEH(capacity): %.2f -> %.2f  (pass = <5)" % (sd_["geh_qmax"], sc_["geh_qmax"]),
              "- features within tolerance: %d/5 -> %d/5" % (sd_["n_within_tol"], sc_["n_within_tol"]),
              "- calibrated vType: `" + " ".join("%s=%.4g" % kv for kv in sorted(cal.items())) + "`",
              "- teleports across all replications: default %.0f, calibrated %.0f; collisions %.0f / %.0f"
              % (o["default"]["teleports"], o["calibrated"]["teleports"],
                 o["default"]["collisions"], o["calibrated"]["collisions"]), ""]
    open(os.path.join(OUT, "CALIBRATION_SCORECARDS.md"), "w").write("\n".join(L))
    print("wrote CALIBRATION_SCORECARDS.md")


if __name__ == "__main__":
    morris_md(); scorecards_md()
