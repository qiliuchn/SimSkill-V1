#!/usr/bin/env python3
"""Render the per-cell results tables (mean +/- 95 % CI over 10 seeds) and the
verification table from outputs/per_cell_metrics.json / per_run_metrics.json."""
import json
import os
import sys

import numpy as np
from scipy import stats

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")
CELLS = [("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
         ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
         ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")]
LBL = {"A_excl": "A (excl RT lane)", "B_shared": "B (shared T+R)"}


def f(a, k, d=1, scale=1.0):
    if k not in a:
        return "n/a"
    m, h = a[k]["mean"] * scale, a[k]["ci95"] * scale
    return f"{m:.{d}f} ± {h:.{d}f}"


def welch(runs, k, c1, c2):
    """Welch t-test between two cells on metric k (independent seeds)."""
    x = [r[k] for r in runs if (r["variant"], r["cell"]) == c1 and k in r
         and r[k] == r[k]]
    y = [r[k] for r in runs if (r["variant"], r["cell"]) == c2 and k in r
         and r[k] == r[k]]
    if len(x) < 2 or len(y) < 2:
        return None
    t, p = stats.ttest_ind(x, y, equal_var=False)
    return np.mean(y) - np.mean(x), p


def main():
    agg = json.load(open(os.path.join(OUT, "per_cell_metrics.json")))
    runs = json.load(open(os.path.join(OUT, "per_run_metrics.json")))
    L = []

    L.append("# RTOR / LPI results tables\n")
    L.append("All values are the mean over 10 independent simulation seeds "
             "+/- the half-width of a 95 % t confidence interval.\n")
    L.append("Analysis window 600-3600 s (0.8333 h); demand 0-3600 s; "
             "step-length 0.5 s; `--time-to-teleport -1`.\n")

    # ---------- verification ----------
    L.append("\n## Table 0 - MANDATORY VERIFICATION: did turns on red actually happen?\n")
    L.append("`hard_red` = right-turn stop-line crossings while the link showed a plain "
             "`r` (red-light running; must be 0 everywhere). "
             "`on-red` = crossings while the link showed `r` OR `s`. "
             "TraCI = signal character read at the step the vehicle's front enters the "
             "right turn's internal via lane. "
             "Detector = `instantInductionLoop` 1 m along that same internal lane, "
             "classified by an ANALYTIC reconstruction of the phase table (no TraCI).\n")
    L.append("| geometry | treatment | regime | RT crossings (TraCI) | RT crossings (detector) | "
             "on-red TraCI | on-red detector | per-veh class disagreements | hard_red | "
             "analytic-vs-TraCI state mismatches |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for regime in ("operational", "capacity"):
        for v, c in CELLS:
            k = f"{regime}|{v}|{c}"
            if k not in agg:
                continue
            a = agg[k]
            L.append(f"| {LBL[v]} | {c} | {regime} | "
                     f"{a['rt_total_count']['mean']:.1f} | {a['det_rt_total_count']['mean']:.1f} | "
                     f"{a['rt_onred_count']['mean']:.1f} | {a['det_rt_onred_count']['mean']:.1f} | "
                     f"{a['det_traci_class_disagree']['mean']:.2f} | "
                     f"{a['rt_hard_red_count']['mean']:.2f} | "
                     f"{a['analytic_state_mismatches']['mean']:.2f} |")

    # ---------- operational ----------
    L.append("\n## Table 1 - OPERATIONAL regime (right-turn demand 170 veh/h/approach, "
             "v/c = 0.78 against the measured NTOR capacity)\n")
    L.append("Right-turn volume and its on-red / on-green decomposition, summed over all "
             "four approaches.\n")
    L.append("| geometry | treatment | RT served (veh/h) | on-red (veh/h) | on-green (veh/h) | "
             "on-red share | RT control delay mean (s) | RT p95 (s) | through CD (s) | "
             "left CD (s) | intersection CD mean (s) | intersection p95 (s) |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v, c in CELLS:
        k = f"operational|{v}|{c}"
        if k not in agg:
            continue
        a = agg[k]
        L.append(f"| {LBL[v]} | {c} | {f(a,'rt_total_vph')} | {f(a,'rt_onred_vph')} | "
                 f"{f(a,'rt_ongreen_vph')} | {f(a,'rt_onred_share',3)} | "
                 f"{f(a,'cd_rt_mean')} | {f(a,'cd_rt_p95')} | {f(a,'cd_thru_mean')} | "
                 f"{f(a,'cd_left_mean')} | {f(a,'cd_int_mean')} | {f(a,'cd_int_p95')} |")

    L.append("\n## Table 2 - OPERATIONAL regime: pedestrians and conflict exposure\n")
    L.append("| geometry | treatment | ped vol per crossing (ped/h) | crossing wait mean (s) | "
             "crossing wait p95 (s) | ped walk timeLoss (s) | ped-veh conflicts /h | "
             "of which on-red | of which on-green | conflicts per 1000 RT | "
             "min TTC-like (s) | SSM RT merge conflicts /h |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v, c in CELLS:
        k = f"operational|{v}|{c}"
        if k not in agg:
            continue
        a = agg[k]
        L.append(f"| {LBL[v]} | {c} | {f(a,'ped_xing_vph_per_crossing')} | "
                 f"{f(a,'ped_cross_wait_mean',2)} | {f(a,'ped_cross_wait_p95',2)} | "
                 f"{f(a,'ped_timeloss_mean',2)} | {f(a,'pedveh_conflicts_per_h')} | "
                 f"{f(a,'pedveh_conflicts_onred')} | {f(a,'pedveh_conflicts_ongreen')} | "
                 f"{f(a,'pedveh_conflicts_per_1000rt')} | {f(a,'pedveh_min_ttc_mean',3)} | "
                 f"{f(a,'ssm_rt_merge_per_h',2)} |")

    # ---------- capacity ----------
    L.append("\n## Table 3 - CAPACITY regime (right-turn demand 1200 veh/h/approach; "
             "served volume = movement capacity)\n")
    L.append("| geometry | treatment | RT capacity all 4 approaches (veh/h) | "
             "per approach (veh/h/lane) | on-green component | on-red component | "
             "sat. headway on green (s) | sat. flow on green (veh/h/lane) | "
             "sat. headway on red (s) | discharge rate on red (veh/h/lane) |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v, c in CELLS:
        k = f"capacity|{v}|{c}"
        if k not in agg:
            continue
        a = agg[k]
        per = {kk: {"mean": a[kk]["mean"] / 4, "ci95": a[kk]["ci95"] / 4} for kk in
               ("rt_total_vph",)}
        L.append(f"| {LBL[v]} | {c} | {f(a,'rt_total_vph')} | {f(per,'rt_total_vph')} | "
                 f"{f(a,'rt_ongreen_vph')} | {f(a,'rt_onred_vph')} | "
                 f"{f(a,'sat_headway_green_med',3)} | {f(a,'sat_flow_green_vphpl',0)} | "
                 f"{f(a,'sat_headway_red_med',3)} | {f(a,'sat_flow_red_vphpl',0)} |")

    L.append("\n## Table 4 - `s` vs `g` stop-line behaviour inside the main runs\n")
    L.append("| geometry | treatment | regime | stop-line speed on-red (m/s) | "
             "min approach speed on-red (m/s) | full-stop fraction on-red | "
             "stop-line speed on-green (m/s) | min approach speed on-green (m/s) | "
             "full-stop fraction on-green |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for regime in ("operational", "capacity"):
        for v, c in CELLS:
            k = f"{regime}|{v}|{c}"
            if k not in agg:
                continue
            a = agg[k]
            L.append(f"| {LBL[v]} | {c} | {regime} | {f(a,'stopline_speed_onred',3)} | "
                     f"{f(a,'minappr_speed_onred',3)} | {f(a,'stopfrac_onred',3)} | "
                     f"{f(a,'stopline_speed_ongreen',3)} | {f(a,'minappr_speed_ongreen',3)} | "
                     f"{f(a,'stopfrac_ongreen',3)} |")

    L.append("\n## Table 5 - run health\n")
    L.append("| geometry | treatment | regime | teleports | collisions | "
             "vehicles completed | pedestrians |")
    L.append("|---|---|---|---:|---:|---:|---:|")
    for regime in ("operational", "capacity"):
        for v, c in CELLS:
            k = f"{regime}|{v}|{c}"
            if k not in agg:
                continue
            a = agg[k]
            L.append(f"| {LBL[v]} | {c} | {regime} | {a['teleports']['mean']:.2f} | "
                     f"{a['collisions']['mean']:.2f} | {a['veh_completed']['mean']:.0f} | "
                     f"{a['ped_n']['mean']:.0f} |")

    # ---------- contrasts ----------
    L.append("\n## Table 6 - treatment contrasts (Welch t-test, independent seeds)\n")
    L.append("| contrast | metric | regime | difference (2nd - 1st) | p |")
    L.append("|---|---|---|---:|---:|")
    contrasts = [
        ("A: NTOR -> RTOR (no LPI)", ("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI")),
        ("A: RTOR no-LPI -> RTOR+LPI", ("A_excl", "RTOR_noLPI"), ("A_excl", "RTOR_LPI")),
        ("A: NTOR no-LPI -> NTOR+LPI", ("A_excl", "NTOR_noLPI"), ("A_excl", "NTOR_LPI")),
        ("A: RTOR+LPI -> NTOR+LPI", ("A_excl", "RTOR_LPI"), ("A_excl", "NTOR_LPI")),
        ("B: NTOR -> RTOR (no LPI)", ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")),
    ]
    mets = ["rt_total_vph", "rt_onred_vph", "cd_rt_mean", "cd_int_mean",
            "pedveh_conflicts_per_h", "ped_cross_wait_mean", "ped_timeloss_mean",
            "ssm_rt_merge_per_h"]
    for regime in ("operational", "capacity"):
        rr = [r for r in runs if r["regime"] == regime]
        for name, c1, c2 in contrasts:
            for m in mets:
                if regime == "capacity" and m not in ("rt_total_vph", "rt_onred_vph"):
                    continue
                w = welch(rr, m, c1, c2)
                if w is None:
                    continue
                L.append(f"| {name} | {m} | {regime} | {w[0]:+.2f} | {w[1]:.2e} |")

    txt = "\n".join(L) + "\n"
    open(os.path.join(OUT, "RESULTS_TABLES.md"), "w").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
