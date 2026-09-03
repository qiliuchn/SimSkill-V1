#!/usr/bin/env python3
"""Assemble the small final deliverables into episodic-memory/<ts>/outputs/."""
import csv
import glob
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfgutil                                       # noqa: E402

ATT = os.path.dirname(HERE)
EP = os.path.dirname(os.path.dirname(ATT))
OUT = os.path.join(EP, "outputs")
W = cfgutil.WORK


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(src, dst)


def main():
    os.makedirs(OUT, exist_ok=True)
    A = json.load(open(os.path.join(W, "analysis", "analysis.json")))

    # ---- 1. figures ----
    for f in glob.glob(os.path.join(W, "figs", "*.png")):
        cp(f, os.path.join(OUT, "figures", os.path.basename(f)))

    # ---- 2. the detector/tlLogic XML for every variant (deduplicated) ----
    seen, n = {}, 0
    for f in sorted(glob.glob(os.path.join(W, "runs", "*", "*", "cell.add.xml"))):
        exp = f.split(os.sep)[-3]
        variant, level, seed = f.split(os.sep)[-2].split("__")
        if seed != "s1":
            continue
        body = open(f).read()
        h = hashlib.sha1(body.encode()).hexdigest()
        if h in seen:
            continue
        seen[h] = True
        cp(f, os.path.join(OUT, "detector_tls_xml", exp,
                           f"{variant}__{level}.add.xml"))
        n += 1
    # binding-verification variants
    for f in sorted(glob.glob(os.path.join(W, "binding", "V*", "cell.add.xml"))):
        v = f.split(os.sep)[-2]
        cp(f, os.path.join(OUT, "detector_tls_xml", "binding_verification",
                           f"{v}.add.xml"))
    cp(os.path.join(W, "net", "inter.net.xml"),
       os.path.join(OUT, "detector_tls_xml", "inter.net.xml"))

    # ---- 3. per-cell compacted metrics CSV ----
    cp(os.path.join(W, "analysis", "cell_metrics.csv"),
       os.path.join(OUT, "cell_metrics.csv"))
    cp(os.path.join(W, "cells_raw.csv"),
       os.path.join(OUT, "per_seed_metrics.csv"))

    # ---- 4. binding verification + webster plan + satflow + teleport ----
    cp(os.path.join(W, "binding", "binding_verification.json"),
       os.path.join(OUT, "binding_verification.json"))
    for f in sorted(glob.glob(os.path.join(W, "binding", "V*", "phase_trace.txt"))):
        cp(f, os.path.join(OUT, "binding_verification_traces",
                           f.split(os.sep)[-2] + ".phase_trace.txt"))
    cp(os.path.join(W, "webster_plans.json"),
       os.path.join(OUT, "webster_plans.json"))
    cp(os.path.join(W, "satflow", "satflow.json"),
       os.path.join(OUT, "measured_saturation_flows.json"))
    for f in ("teleport_check.csv", "teleport_check.json"):
        p = os.path.join(W, f)
        if os.path.exists(p):
            cp(p, os.path.join(OUT, f))
    cp(os.path.join(W, "analysis", "analysis.json"),
       os.path.join(OUT, "analysis.json"))
    cp(os.path.join(W, "best_tuned_choice.json"),
       os.path.join(OUT, "best_tuned_choice.json"))

    # ---- 5. one FULL raw output set ----
    src = os.path.join(W, "runs", "E1", "sb40_mg3__med__s1")
    for f in glob.glob(os.path.join(src, "*")):
        cp(f, os.path.join(OUT, "raw_example_sb40_mg3_med_s1",
                           os.path.basename(f)))
    cp(cfgutil.rou("med", 1),
       os.path.join(OUT, "raw_example_sb40_mg3_med_s1", "med_s1.rou.xml"))

    # ---- 6. fault-degradation table ----
    order = ["webster", "healthy", "stuckon_partial", "stuckon_major",
             "stuckoff_partial", "stuckoff_minor", "stuckoff_major",
             "failsafe_healthy", "failsafe_stuckon_major",
             "failsafe_stuckoff_major"]
    rows = []
    for key, tag in (("E4_E5_faults", "tuned_sb40_mg2"),
                     ("E4_E5_faults_alt", "tuned_sb25_mg3")):
        for lv in ("low", "med", "high"):
            T = A[key].get(lv, {})
            for nm in order:
                r = T.get(nm)
                if not r:
                    continue
                rows.append(dict(
                    tuning=tag, demand=lv, variant=nm,
                    delay_tripinfo=r["delay"], delay_tripinfo_ci=r.get("delay_ci"),
                    delay_censor_robust=r["delay_robust"],
                    delay_censor_robust_ci=r.get("delay_robust_ci"),
                    throughput=r["throughput"], completion_rate=r["completion"],
                    stops=r.get("stops"), teleports=r["teleports"],
                    A_mean_green=r.get("A_mean_green"),
                    A_f_maxout=r.get("A_f_maxout"),
                    stuckon_loop_max_time_since_detection=r.get("stuckon_max_tsd"),
                    vs_healthy_delta=r.get("vs_healthy_diff"),
                    vs_healthy_ci=r.get("vs_healthy_ci"),
                    vs_healthy_significant=r.get("vs_healthy_sig"),
                    vs_webster_delta=r.get("vs_webster_diff"),
                    vs_webster_ci=r.get("vs_webster_ci"),
                    vs_webster_significant=r.get("vs_webster_sig"),
                    WORSE_THAN_WEBSTER=r.get("WORSE_THAN_WEBSTER")))
    with open(os.path.join(OUT, "fault_degradation_table.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- 7. setback vs SUMO-default comparison ----
    rows = []
    for lv in ("low", "med", "high"):
        e = A["E2_default_vs_tuned"][lv]
        rows.append(dict(demand=lv, **{k: v for k, v in e.items()}))
    with open(os.path.join(OUT, "setback_vs_sumo_default.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    rows = []
    for k, d in A["E3_per_approach"].items():
        for r in d["rows"]:
            rows.append(dict(approach=d["road"], demand=d["level"],
                             speed_kmh=60 if d["road"] == "major" else 40,
                             sumo_default_setback_m=d["sumo_default_setback"],
                             empirical_best_setback_m=d["best_setback"],
                             setback_m=r["setback"], delay=r["delay"],
                             delay_ci=r["ci"],
                             diff_vs_best=r["diff_vs_best"],
                             diff_ci=r["diff_ci"],
                             significantly_worse_than_best=r["significant"],
                             f_premature_gapout=r["f_premature_gapout"],
                             mean_unseen_imminent_veh=r["mean_unseen_imminent"],
                             f_cut_with_blind_queue=r["f_cut_with_blind_queue"],
                             mean_blind_queued_veh=r["mean_blind_slow"],
                             mean_blind_veh=r["mean_blind_veh"],
                             f_gapout=r["f_gapout"], f_maxout=r["f_maxout"],
                             mean_green_s=r["mean_green"]))
    with open(os.path.join(OUT, "per_approach_setback_and_mechanisms.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- 8. delay surface as a flat CSV ----
    rows = []
    for lv in ("low", "med", "high"):
        for k, g in A["E1_surface"][lv]["grid"].items():
            sb, mg = k.split("|")
            c = A["E1_surface"][lv]["cells"][f"sb{sb}_mg{mg}"]
            rows.append(dict(demand=lv, setback_m=float(sb), max_gap_s=float(mg),
                             **g, diff_vs_best=c["diff_vs_best"],
                             diff_ci=c["diff_ci"],
                             significantly_worse_than_best=c[
                                 "worse_than_best_significant"]))
    with open(os.path.join(OUT, "delay_surface.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- 9. copy the scripts (small, and they ARE the method) ----
    for f in glob.glob(os.path.join(HERE, "*.py")):
        cp(f, os.path.join(OUT, "scripts", os.path.basename(f)))

    print(f"outputs assembled in {OUT}")
    print(f"  {n} unique detector/tlLogic additional files")
    for root, _, files in os.walk(OUT):
        for fn in sorted(files)[:0]:
            pass
    tot = sum(os.path.getsize(os.path.join(r, f))
              for r, _, fs in os.walk(OUT) for f in fs)
    print(f"  total size {tot/1e6:.1f} MB")


if __name__ == "__main__":
    main()
