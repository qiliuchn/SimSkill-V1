"""Emit the exact numeric tables that FINDINGS.md cites, so every number in the report is
machine-generated from results.json / lost_time.json / stopgo_*.json and can be re-checked."""
import json
import os

from common import ANA_DIR
import analytic

OUT = os.path.join(ANA_DIR, "tables.md")


def f(x, n=2, dash="-"):
    if x is None:
        return dash
    try:
        return ("%%.%df" % n) % x
    except (TypeError, ValueError):
        return str(x)


def ci(a, n=2):
    if a is None or a.get("mean") is None:
        return "-"
    if a.get("hw") is None:
        return f(a["mean"], n)
    return "%s ± %s" % (f(a["mean"], n), f(a["hw"], n))


def pdiff(p, n=2):
    if p is None or p.get("diff") is None:
        return "-"
    star = "*" if p.get("sig") else ""
    return "%s ± %s%s (p=%s)" % (f(p["diff"], n), f(p["hw"], n), star,
                                 f(p.get("p"), 4) if p.get("p") is not None else "-")


L = []


def w(s=""):
    L.append(s)


def main():
    res = json.load(open(os.path.join(ANA_DIR, "results.json")))

    w("# Machine-generated result tables")
    w()
    w("Every number below comes straight from `analysis/results.json`, which is built by")
    w("`scripts/analyze.py` from the per-run `runs/*/metrics.json` + `runs/*/decision_log.csv`.")
    w()

    # ---- validity ----
    w("## 0. Run-validity accounting (all sweeps pooled)")
    w()
    v = res["validity"]
    w("| quantity | value |")
    w("|---|---|")
    for k in ("n_runs", "total_teleports", "runs_with_teleport", "total_still_running",
              "runs_with_still_running", "max_still_running_frac", "total_collisions",
              "total_junction_collisions", "runs_with_collision",
              "total_emergency_stops_red", "max_emergency_stop_decel"):
        w("| %s | %s |" % (k, f(v[k], 4) if isinstance(v[k], float) else v[k]))
    w()

    # ---- analytic reference ----
    w("## 1. Analytic reference (ITE / kinematic), independent of SUMO")
    w()
    w("`y = t_pr + v/(2a + 2gG)` with t_pr=1.0 s, a=3.05 m/s2; `r = (W+L)/v` with L=6.1 m.")
    w()
    w("| v (m/s) | v (km/h) | ITE y (s) | ITE r, W=20.8 m | ITE r, W=33.6 m | "
      "x_s ITE (m) | x_s SUMO-default v^2/2*4.5 (m) | x_c at y=3 s (m) |")
    w("|---|---|---|---|---|---|---|---|")
    for vv in (11.11, 13.89, 16.67, 19.44, 22.22, 25.0, 27.78):
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            f(vv), f(vv * 3.6, 0), f(analytic.ite_yellow(vv)),
            f(analytic.ite_allred(vv, 20.8)), f(analytic.ite_allred(vv, 33.6)),
            f(analytic.x_stop(vv, 1.0, 3.05)), f(analytic.x_stop(vv, 0.0, 4.5)),
            f(vv * 3.0)))
    w()
    w("### Dilemma vs option zone (convention: dilemma iff x_s > x_c)")
    w()
    w("| driver assumption | v (km/h) | y (s) | x_s (m) | x_c=v*y (m) | zone | width (m) |")
    w("|---|---|---|---|---|---|---|")
    for lab, tpr, a in (("ITE (PRT 1.0 s, a=3.05)", 1.0, 3.05),
                        ("SUMO default (PRT 0, a=4.5)", 0.0, 4.5)):
        for vv in (13.89, 19.44, 25.0):
            for y in (2.0, 3.0, 4.0, 5.0, 6.0):
                z = analytic.zone(vv, y, 1.0, 20.8, tpr, a)
                w("| %s | %s | %s | %s | %s | %s | %s |" % (
                    lab, f(vv * 3.6, 0), f(y, 1), f(z["x_s"]), f(z["x_c"]),
                    z["zone_type"], f(z["zone_width"])))
    w()

    # ---- SUMO boundary probe ----
    p = os.path.join(ANA_DIR, "stopgo_boundary.json")
    if os.path.exists(p):
        b = json.load(open(p))
        w("## 2. SUMO's OWN stop/go boundary (single-vehicle bisection, ±0.25 m)")
        w()
        w("| v (km/h) | vType decel | actionStepLength | integration | SUMO boundary (m) | "
          "v^2/2a (m) | v*asl + v^2/2a (m) | ITE x_s (m) |")
        w("|---|---|---|---|---|---|---|---|")
        for r in b:
            w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                f(r["v"] * 3.6, 0), f(r["decel"]), f(r["actionStepLength"]),
                "ballistic" if r["ballistic"] else "Euler",
                f(r["sumo_boundary"]) if r["sumo_boundary"] else r.get("note", "-"),
                f(r["kinematic_no_prt"]), f(r["kinematic_with_prt"]), f(r["ite_x_stop"])))
        w()

    p = os.path.join(ANA_DIR, "stopgo_params.json")
    if os.path.exists(p):
        pr = json.load(open(p))
        w("## 3. Which vType / junction-model parameters actually move the boundary")
        w()
        w("v = 22.22 m/s (80 km/h), y = 3 s. `x_c = v*y = 66.7 m`. "
          "`NEGCTRL` rows are negative controls that MUST NOT change the boundary.")
        w()
        cols = [k for k in pr[0] if k.startswith("d") and k[1].isdigit()]
        w("| variant | boundary (m) | " + " | ".join(cols) + " |")
        w("|---|---|" + "---|" * len(cols))
        for r in pr:
            w("| `%s` | %s | %s |" % (r["variant"],
                                      f(r["boundary"]) if r["boundary"] else r.get("note", "-"),
                                      " | ".join(str(r.get(c, "-")) for c in cols)))
        w()

    p = os.path.join(ANA_DIR, "stopgo_grade.json")
    if os.path.exists(p):
        g = json.load(open(p))
        w("## 4. Grade: analytic prediction vs SUMO's realized behaviour")
        w()
        w("| grade nominal | grade realized (from compiled net) | v (m/s) | decel | "
          "SUMO boundary (m) | realized stop distance (m) | analytic x_s flat (m) | "
          "analytic x_s with grade (m) | ITE y flat (s) | ITE y graded (s) |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for r in g:
            w("| %s%% | %s%% | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                f(r["grade_nominal"], 1), f(r["grade_realized"], 3), f(r["v"]),
                f(r["decel"]), f(r["sumo_boundary"]), f(r["realized_stop_dist"]),
                f(r["analytic_x_stop_flat"]), f(r["analytic_x_stop_grade"]),
                f(r["ite_y_flat"]), f(r["ite_y_grade"])))
        w()

    # ---- H1 ----
    w("## 5. H1 - red-light running vs yellow length and speed")
    w()
    for key in sorted(res["H1"]):
        row = res["H1"][key]
        w("### %s" % key)
        w()
        w("| y (s) | ITE y for this v | analytic-ITE zone | RLR /1000 veh | RLR events "
          "(pooled) | hard braking /1000 dec | severe braking /1000 dec | emerg. stops at "
          "red (per run) | right-angle overlaps /1000 veh | rear TTC<1.5 /1000 veh | "
          "mean time loss (s) |")
        w("|---|---|---|---|---|---|---|---|---|---|---|")
        for y in sorted(row, key=float):
            d = row[y]
            az = d["analytic_ite"]
            w("| %s | %s | %s %sm | %s | %d/%d | %s | %s | %s | %s | %s | %s |" % (
                f(float(y), 1), f(d["ite_yellow"]), az["zone"], f(az["width"], 0),
                ci(d["rlr_per_1000_veh"], 3), d["n_red_total"], d["n_decision_total"],
                ci(d["hard_per_1000_dec"], 1), ci(d["severe_per_1000_dec"], 1),
                ci(d["emg_stop_red"], 1), ci(d["overlap_per_1000_veh"], 2),
                ci(d["rear_ttc15_per_1000_veh"], 2), ci(d["mean_timeloss"], 2)))
        w()
    w("### H1 speed gradient and CRN-paired short-vs-ITE yellow contrasts")
    w()
    for k, vv in sorted(res["H1_speed_gradient"].items()):
        if k.startswith("paired_"):
            w("- `%s`: paired diff (ITE-yellow - y=2) = %s" % (k, pdiff(vv, 3)))
        else:
            w("- `%s`: " % k + ", ".join("v=%.0f km/h -> %s ± %s" % (a * 3.6, f(b, 3), f(c, 3))
                                         for a, b, c in vv))
    w()

    # ---- stop/go ----
    w("## 6. Measured indecision zone vs analytic boundaries")
    w()
    w("| cell | n decisions | measured indecision zone (m) | width (m) | x_s SUMO kinematic "
      "| x_s ITE | x_c = v*y | analytic-ITE zone | analytic-SUMO-default zone |")
    w("|---|---|---|---|---|---|---|---|---|")
    for k in sorted(res["stopgo_curves"]):
        d = res["stopgo_curves"][k]
        iz = d["indecision"]
        w("| %s | %d | %s-%s | %s | %s | %s | %s | %s %sm | %s %sm |" % (
            k, d["n"], f(iz["lo"], 0), f(iz["hi"], 0), f(iz["width"], 0),
            f(d["x_s_sumo_kinematic"]), f(d["x_s_ite"]), f(d["x_c_stopline"]),
            d["analytic_zone_ite"]["zone_type"], f(d["analytic_zone_ite"]["zone_width"], 0),
            d["analytic_zone_default"]["zone_type"],
            f(d["analytic_zone_default"]["zone_width"], 0)))
    w()

    # ---- H2 ----
    w("## 7. H2 - is safety non-monotonic in yellow?")
    w()
    w("| cell | metric | argmin y | min | argmax y | max | interior minimum? | "
      "monotone decreasing? | paired vs shortest y | paired vs longest y |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(res["H2"]):
        for m, vd in sorted(res["H2"][k]["verdict"].items()):
            pk = [x for x in vd if x.startswith("paired_vs_")]
            p1 = pdiff(vd[pk[0]], 3) if pk else "-"
            p2 = pdiff(vd[pk[1]], 3) if len(pk) > 1 else "-"
            w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                k, m, f(vd["argmin_y"], 1), f(vd["min"], 3), f(vd["argmax_y"], 1),
                f(vd["max"], 3), vd["interior_min"], vd["monotone_decreasing"], p1, p2))
    w()

    w("### H2 CRN-paired endpoint contrasts (positive = metric HIGHER at the longer yellow)")
    w()
    w("| cell | metric | y_lo -> y_hi | diff (paired) | y_lo -> ITE yellow | diff (paired) |")
    w("|---|---|---|---|---|---|")
    for k in sorted(res["H2"]):
        ep = res["H2"][k].get("endpoints", {})
        for m in sorted(ep):
            d = ep[m]
            w("| %s | %s | %s->%s | %s | %s->%s | %s |" % (
                k, m, f(d["y_lo"], 1), f(d["y_hi"], 1), pdiff(d["lo_to_hi"], 3),
                f(d["y_lo"], 1), f(d["y_ite"], 1), pdiff(d["lo_to_ite"], 3)))
    w()

    # ---- non-compliance ----
    w("## 8. Non-compliance decomposition (sweep A2, v=70 km/h, low demand)")
    w()
    w("| driver arm | y (s) | realized non-compliant share | RLR /1000 veh | "
      "hard braking /1000 dec | emerg. stops at red | right-angle overlaps /1000 veh | "
      "collisions | mean time loss (s) |")
    w("|---|---|---|---|---|---|---|---|---|")
    for drv in sorted(res["A2_noncompliance"]):
        for yk in sorted(res["A2_noncompliance"][drv]):
            d = res["A2_noncompliance"][drv][yk]
            w("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                drv, yk, ci(d["noncomp_share_realized"], 3), ci(d["rlr_per_1000_veh"], 3),
                ci(d["hard_per_1000_dec"], 1), ci(d["emg_stop_red"], 1),
                ci(d["overlap_per_1000_veh"], 2), ci(d["collisions"], 2),
                ci(d["mean_timeloss"], 2)))
    w()

    # ---- H3 ----
    p = os.path.join(ANA_DIR, "lost_time.json")
    if os.path.exists(p):
        lt = json.load(open(p))
        w("## 9. H3 - measured lost time vs the assumed intergreen")
        w()
        w("| y (s) | all-red (s) | green (s) | truck share | h_s (s) | sat flow (veh/h/ln) "
          "| l1 start-up (s) | N_d /cycle | g_eff (s) | L measured (s) | assumed y+ar (s) "
          "| L - (y+ar) (s) | l2 = L-l1 (s) | veh crossing in yellow | in all-red |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted(lt, key=lambda r: (r["truck_share"], r["green"], r["yellow"],
                                           r["allred"])):
            w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
              % (f(r["yellow"], 1), f(r["allred"], 1), f(r["green"], 0),
                 f(r["truck_share"], 2), f(r["h_s"], 3), f(r["sat_flow"], 0),
                 f(r["l1"], 2), f(r["N_d"], 2), f(r["g_eff"], 2), f(r["L_total"], 2),
                 f(r["assumed_intergreen"], 1), f(r["L_minus_intergreen"], 2),
                 f(r["l2"], 2), f(r["n_in_yellow"], 2), f(r["n_in_allred"], 2)))
        w()
        p2 = os.path.join(ANA_DIR, "webster_impact.json")
        if os.path.exists(p2):
            wi = json.load(open(p2))
            w("### Webster impact of using the assumed vs measured lost time")
            w()
            w("| case | L used (s) | Y | C_opt (s) | Webster delay at C_opt (s) | "
              "delay at the OTHER case's C_opt (s) | penalty (s) | penalty (%) |")
            w("|---|---|---|---|---|---|---|---|")
            for r in wi:
                w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    r["case"], f(r["L"], 2), f(r["Y"], 3), f(r["C_opt"], 1),
                    f(r["d_at_own"], 2), f(r["d_at_other"], 2), f(r["penalty"], 3),
                    f(r["penalty_pct"], 2)))
            w()

    # ---- H4 ----
    w("## 10. H4 - all-red exchange rate")
    w()
    for k in sorted(res["H4"]):
        row = res["H4"][k]
        w("### %s (W = %s m, ITE all-red = %s s, ITE yellow = %s s)"
          % (k, f(row["W"]), f(row["ite_allred"]), f(row["ite_yellow"])))
        w()
        w("| all-red (s) | right-angle overlaps /1000 veh | jPET<1 s /1000 veh | "
          "RLR /1000 veh | mean time loss (s) | completed | collisions |")
        w("|---|---|---|---|---|---|---|")
        ars = [a for a, _ in row["series"]["overlap_per_1000_veh"]]
        for i, ar in enumerate(ars):
            g = lambda m: ci(row["series"][m][i][1], 3)
            w("| %s | %s | %s | %s | %s | %s | %s |" % (
                f(ar, 1), g("overlap_per_1000_veh"), g("jpet_lt1_per_1000_veh"),
                g("rlr_per_1000_veh"), ci(row["series"]["mean_timeloss"][i][1], 2),
                ci(row["series"]["completed"][i][1], 1),
                ci(row["series"]["collisions"][i][1], 2)))
        w()
        w("Marginal, CRN-paired, per added second of all-red:")
        w()
        w("| step | d(overlaps/1000 veh) | d(jPET<1s /1000 veh) | d(time loss, s) | "
          "d(completed) |")
        w("|---|---|---|---|---|")
        for st, d in sorted(row["marginal"].items()):
            w("| %s | %s | %s | %s | %s |" % (st, pdiff(d["d_overlap"], 3),
                                              pdiff(d["d_jpet_lt1"], 3),
                                              pdiff(d["d_timeloss"], 3),
                                              pdiff(d["d_completed"], 2)))
        w()
        w("Exchange rate (right-angle overlaps avoided per 1000 veh, per second of "
          "per-vehicle delay bought):")
        w()
        w("| step | overlaps avoided /1000 veh | delay cost (s/veh) | overlaps avoided per "
          "s of delay | safety gain significant? |")
        w("|---|---|---|---|---|")
        for st, e in sorted(row.get("exchange", {}).items()):
            w("| %s | %s | %s | %s | %s |" % (
                st, f(e["overlaps_avoided_per_1000veh"], 3), f(e["delay_cost_s_per_veh"], 3),
                f(e["overlaps_avoided_per_second_of_delay"], 2),
                e["significant_safety_gain"]))
        w()

    # ---- H5 ----
    w("## 11. H5 - heavy vehicles and grade")
    w()
    w("| cell | realized truck share | RLR /1000 veh | hard braking /1000 dec | "
      "severe braking /1000 dec | emerg. stops at red | overlaps /1000 veh | "
      "mean time loss (s) |")
    w("|---|---|---|---|---|---|---|---|")
    for k in sorted(res["H5"]["cells"]):
        d = res["H5"]["cells"][k]
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k, ci(d["truck_share_realized"], 3), ci(d["rlr_per_1000_veh"], 3),
            ci(d["hard_per_1000_decisions"], 1), ci(d["severe_per_1000_decisions"], 1),
            ci(d["emg_stop_red"], 2), ci(d["overlap_per_1000_veh"], 2),
            ci(d["mean_timeloss"], 2)))
    w()
    w("### CRN-paired main effects (vs cars-on-the-flat at the same yellow)")
    w()
    for k in sorted(res["H5"]["paired"]):
        w("- `%s`: %s" % (k, pdiff(res["H5"]["paired"][k], 3)))
    w()
    if res.get("H5_curves"):
        w("### Stop/go indecision zone by vehicle class")
        w()
        w("| cell | n | indecision lo (m) | hi (m) | width (m) |")
        w("|---|---|---|---|---|")
        for k in sorted(res["H5_curves"]):
            d = res["H5_curves"][k]
            iz = d["indecision"]
            w("| %s | %d | %s | %s | %s |" % (k, d["n"], f(iz["lo"], 0), f(iz["hi"], 0),
                                              f(iz["width"], 0)))
        w()

    # ---- H6 ----
    w("## 12. H6 - capacity-optimal vs safety-optimal yellow")
    w()
    w("| cell | capacity-optimal y | safety-optimal y (equal wt) | safety-optimal y "
      "(right-angle wt 3x) | gap (s) | time loss at cap-opt (s) | at safety-opt (s) | "
      "delay penalty (s) | delay penalty (%) | safety index at cap-opt | at safety-opt | "
      "safety gain (%) | degenerate components |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(res["H6"]):
        d = res["H6"][k]
        tl = dict(d["timeloss_by_y"])
        si = dict((a, b) for a, b in d["safety_index_by_y"])
        cy, sy = d["capacity_optimal_y"], d["safety_optimal_y"]
        syw = d.get("safety_optimal_y_weighted")
        if cy is None or sy is None:
            continue
        dpen = (tl.get(sy) or 0) - (tl.get(cy) or 0)
        sgain = (100.0 * ((si.get(cy) or 0) - (si.get(sy) or 0)) / (si.get(cy) or 1)
                 if si.get(cy) else None)
        w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k, f(cy, 1), f(sy, 1), f(syw, 1), f(sy - cy, 1), f(tl.get(cy)), f(tl.get(sy)),
            f(dpen, 3), f(100.0 * dpen / (tl.get(cy) or 1), 2), f(si.get(cy), 3),
            f(si.get(sy), 3), f(sgain, 1), ", ".join(d.get("degenerate_components", []))))
    w()

    # ---- F ----
    w("## 13. Teleport-artifact sensitivity (`--time-to-teleport` sweep)")
    w()
    w("| cell | teleports | completed | still running | mean time loss (completed) | "
      "censoring-robust time loss | RLR /1000 veh | overlaps /1000 veh |")
    w("|---|---|---|---|---|---|---|---|")
    for k in sorted(res["F_teleport"]):
        d = res["F_teleport"][k]
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k, ci(d["teleports"], 2), ci(d["completed"], 1), ci(d["still_running"], 2),
            ci(d["mean_timeloss"], 2), ci(d["timeloss_robust"], 2),
            ci(d["rlr_per_1000_veh"], 3), ci(d["overlap_per_1000_veh"], 3)))
    w()

    # ---- crosscheck ----
    p = os.path.join(ANA_DIR, "crosscheck.json")
    if os.path.exists(p):
        cc = json.load(open(p))
        w("## 14. Item-6 cross-check: actuated control and detector placement")
        w()
        w("### (a) does actuation alter the yellow / all-red phases?")
        w()
        w("| run | tls type | realized phase durations (phase idx -> n, min, mean, max) |")
        w("|---|---|---|")
        seen = set()
        for r in cc:
            if not r["name"].startswith("X_") or "det" in r["name"] or "ver" in r["name"]:
                continue
            tt = r["cfg"].get("tls_type")
            y = r["cfg"].get("yellow")
            key = (tt, y)
            if key in seen:
                continue
            seen.add(key)
            pd = r["realized_phase_durations"]
            s = "; ".join("%s: n=%d min=%s mean=%s max=%s"
                          % (k, d["n"], f(d["min"], 2), f(d["mean"], 2), f(d["max"], 2))
                          for k, d in sorted(pd.items(), key=lambda t: int(t[0])))
            w("| y=%s | %s | %s |" % (f(y, 1), tt, s))
        w()
        w("### (b) detector-binding verification protocol")
        w()
        w("| run | trace SHA1 | phase changes | identical to baseline? |")
        w("|---|---|---|---|")
        base = next((r for r in cc if r["name"] == "X_ver_baseline"), None)
        for r in cc:
            if not r["name"].startswith("X_ver"):
                continue
            same = (base is not None and r["trace_sha1"] == base["trace_sha1"])
            w("| `%s` | `%s` | %d | %s |" % (r["name"], r["trace_sha1"][:12],
                                             r["n_phase_changes"], same))
        w()
        w("### (c) does a dilemma-zone detector placement reduce red-light running?")
        w()
        w("| placement | y (s) | n runs | RLR /1000 veh | mean time loss (s) | "
          "hard braking /1000 dec | unphysical emerg. stops at red |")
        w("|---|---|---|---|---|---|---|")
        import stats_util as SU
        from collections import defaultdict
        g = defaultdict(list)
        for r in cc:
            if "_det_" not in r["name"]:
                continue
            pn = r["name"].split("_det_")[1].rsplit("_y", 1)[0]
            y = float(r["name"].split("_y")[-1].split("_s")[0])
            g[(pn, y)].append(r)
        for (pn, y), rs in sorted(g.items()):
            veh = [(x["metrics"]["completed"] or 0) +
                   (x["metrics"]["still_running_at_end"] or 0) for x in rs]
            rlr = [1000.0 * x["outcomes"].get("RED_RUN", 0) / vv if vv else None
                   for x, vv in zip(rs, veh)]
            tls_ = [x["metrics"]["mean_timeloss"] for x in rs]
            hb = [1000.0 * (x["outcomes"].get("STOPPED_HARD", 0)
                            + x["outcomes"].get("STOPPED_SEVERE", 0)
                            + x["outcomes"].get("STOPPED_HARD_NOSTOP", 0)
                            + x["outcomes"].get("STOPPED_SEVERE_NOSTOP", 0))
                  / x["n_decision"] if x["n_decision"] else None for x in rs]
            emg = [x["metrics"].get("emg_stop_red") for x in rs]
            w("| %s | %s | %d | %s | %s | %s | %s |" % (
                pn, f(y, 1), len(rs), ci(SU.mean_ci(rlr), 3), ci(SU.mean_ci(tls_), 2),
                ci(SU.mean_ci(hb), 1), ci(SU.mean_ci(emg), 2)))
        w()

    open(OUT, "w").write("\n".join(L) + "\n")
    print("wrote", OUT, len(L), "lines")


if __name__ == "__main__":
    main()
