"""Turn the retained result JSONs into the markdown tables used by FINDINGS.md."""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "results")
HCM = dict(A=1130.0, B=0.001)


def interp(points, x, xk="vc_measured", yk="entry_cap"):
    pts = sorted((p[xk], p[yk]) for p in points)
    if x <= pts[0][0] or x >= pts[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            # log-linear interpolation (the curve is exponential)
            if y0 <= 0 or y1 <= 0:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
            return math.exp(math.log(y0) + (math.log(y1) - math.log(y0)) * (x - x0) / (x1 - x0))
    return None


def cap_tables(out):
    d = json.load(open(os.path.join(RES, "capacity", "capacity_results.json")))
    sl, tl = d["single_lane"], d["two_lane"]
    f = sl["fit_gap_limited"]
    out.append("### 2.1 Measured single-lane entry capacity vs measured circulating flow\n")
    out.append("| v_c requested | v_c MEASURED (veh/h) | entry capacity (veh/h) | sd (3 seeds) | gap-limited? | HCM 1130·e^(−0.001·v_c) | SUMO/HCM |")
    out.append("|---:|---:|---:|---:|:--|---:|---:|")
    for p, c in zip(sl["points"], sl["hcm_comparison"]):
        out.append(f"| {p['vc_requested']} | {p['vc_measured']:.0f} | {p['entry_cap']:.0f} | {p['entry_cap_sd']:.0f} | "
                   f"{'yes' if p['gap_limited'] else 'NO (queue cleared — saturation-flow-limited)'} | {c['hcm']:.0f} | {c['ratio']:.2f} |")
    out.append("")
    out.append(f"**Fit over the gap-limited points only (n={f['n']}):** "
               f"`c = {f['A']:.0f} · exp(−{f['B']:.5f} · v_c)`, R² = {f['R2']:.3f}, "
               f"95% CI on B = ±{f['B_95ci']:.5f}.\n")
    out.append(f"**Free-flow ceiling (v_c → 0):** {sl['free_flow_ceiling']:.0f} veh/h measured "
               f"(the approach's own saturation flow; the exponential's fitted A={f['A']:.0f} is an "
               f"extrapolation, not a physical intercept).\n")
    kink = math.log(f["A"] / sl["free_flow_ceiling"]) / f["B"]
    out.append(f"**Physically correct two-branch model:** "
               f"`c(v_c) = min({sl['free_flow_ceiling']:.0f}, {f['A']:.0f}·exp(−{f['B']:.5f}·v_c))`, "
               f"branches meeting at v_c ≈ {kink:.0f} veh/h.\n")
    out.append(f"**Crossover with HCM:** v_c ≈ {sl.get('hcm_crossover_vc')} veh/h.\n")

    out.append("### 2.2 Two-lane entry capacity as a multiple of single-lane, at MATCHED measured v_c\n")
    out.append("| v_c (veh/h) | single-lane c | two-lane c | multiple |")
    out.append("|---:|---:|---:|---:|")
    rows = []
    for p in tl["points"]:
        v = p["vc_measured"]
        s1 = interp(sl["points"], v) if v > 0 else sl["free_flow_ceiling"]
        if s1 is None:
            continue
        rows.append((v, s1, p["entry_cap"], p["entry_cap"] / s1))
        out.append(f"| {v:.0f} | {s1:.0f} | {p['entry_cap']:.0f} | {p['entry_cap']/s1:.2f} |")
    out.append("")
    cm = d["two_lane_multiplier_measured"]
    out.append(f"**At v_c = 0 (per-lane comparison, the number that answers "
               f"'is a 2-lane entry worth 2 single-lane entries?'): "
               f"{cm['two_ceiling']:.0f} / {cm['single_ceiling']:.0f} = "
               f"{cm['ceiling_multiple']:.2f}×** — a "
               f"{100*(2-cm['ceiling_multiple'])/2:.0f}% shortfall below 2.0.\n")

    out.append("### 2.3 Which parameter controls the fitted curve\n")
    out.append("| variant | fitted A | fitted B | R² | ΔA % | ΔB % | Δ capacity at v_c=600 % |")
    out.append("|:--|---:|---:|---:|---:|---:|---:|")
    s = d["sensitivity"]
    for k, v in sorted(s.items(), key=lambda kv: -abs(kv[1].get("dC600_pct", 0))):
        out.append(f"| `{k}` | {v['fit']['A']:.0f} | {v['fit']['B']:.5f} | {v['fit']['R2']:.3f} | "
                   f"{v.get('dA_pct')} | {v.get('dB_pct')} | {v.get('dC600_pct')} |")
    out.append("")
    bb = sorted(s.items(), key=lambda kv: -abs(kv[1].get("dB_pct", 0)))
    out.append(f"Largest effect on the **decay rate B**: " +
               ", ".join(f"`{k}` ({v['dB_pct']:+.1f}%)" for k, v in bb[:4] if k != "baseline") + ".\n")
    lv = sorted(s.items(), key=lambda kv: -abs(kv[1].get("dC600_pct", 0)))
    out.append(f"Largest effect on the **capacity level** (Δc at v_c=600): " +
               ", ".join(f"`{k}` ({v['dC600_pct']:+.1f}%)" for k, v in lv[:4] if k != "baseline") + ".\n")


def starv_tables(out):
    d = json.load(open(os.path.join(RES, "starvation", "starvation.json")))
    out.append("### 3.1 Unbalanced-demand sweep (single-lane roundabout, 5 CRN seeds, mean ± 95% CI)\n")
    out.append("| D (E approach veh/h) | dominant-axis share | planned v_c at N | N throughput | N delay (robust, s) | N served | agg delay (s) | agg served | max/min delay ratio | Gini(delay) | teleports |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in d["ladder"]:
        a, g = r["arms"], r["agg"]
        out.append(f"| {r['D']} | {r['dominant_axis_share']:.3f} | {r['planned_vc_at_N']:.0f} | "
                   f"{a['N']['throughput_vph']['mean']:.0f} ± {a['N']['throughput_vph']['ci95']:.0f} | "
                   f"{a['N']['delay_robust_s']['mean']:.1f} ± {a['N']['delay_robust_s']['ci95']:.1f} | "
                   f"{a['N']['served_frac']['mean']:.3f} | "
                   f"{g['delay_robust_s']['mean']:.1f} ± {g['delay_robust_s']['ci95']:.1f} | "
                   f"{g['served_frac']['mean']:.3f} | {g['equity_maxmin_delay_ratio']['mean']:.1f} | "
                   f"{g['equity_gini_delay']['mean']:.3f} | {g['teleports']['mean']:.1f} |")
    out.append("")
    out.append("Per-approach delay ratio N / mean(E,S,W): " +
               ", ".join(f"D={r['D']}→{r['N_over_others_ratio']:.2f}" for r in d["ladder"]) + "\n")
    t = d["starvation_threshold"]
    out.append(f"**Starvation threshold** (first rung with N delay ≥ 3× the mean of the other three "
               f"approaches AND N served < 0.99): **D = {t['D']} veh/h on the dominant approach, "
               f"dominant-axis demand share = {t['dominant_axis_share']:.3f}, planned circulating flow at "
               f"N = {t['planned_vc_at_N']:.0f} veh/h**.\n")


def meter_tables(out):
    p = os.path.join(RES, "metering", "metering.json")
    if not os.path.exists(p):
        return
    d = json.load(open(p))
    out.append("### 4.1 Metering parameter sweep (D = 900, 5 CRN seeds, paired vs the no-metering control on the SAME network)\n")
    out.append("| config | q threshold (veh) | red s | green s | duty cycle | N delay (s) | N served | E delay (s) | junction delay (s) | junction throughput (veh/h) | Gini(delay) | ΔN delay (paired) | Δjunction delay (paired) | Δjunction throughput (paired) |")
    out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|:--|:--|")
    for r in d["sweep"]:
        v = r.get("vs_nometer")
        def fmt(k):
            if not v:
                return "— (baseline)"
            x = v[k]
            return f"{x['mean_diff']:+.1f} ({x['pct']:+.1f}%){'*' if x['significant_95'] else ''}"
        out.append(f"| `{r['cfg']}` | {r['thr_on']} | {r['red']} | {r['green']} | {r['duty']['mean']:.3f} | "
                   f"{r['N_delay']['mean']:.1f} ± {r['N_delay']['ci95']:.1f} | {r['N_served']['mean']:.3f} | "
                   f"{r['E_delay']['mean']:.1f} | {r['agg_delay']['mean']:.1f} ± {r['agg_delay']['ci95']:.1f} | "
                   f"{r['agg_thr']['mean']:.0f} | {r['gini']['mean']:.3f} | "
                   f"{fmt('N_delay')} | {fmt('agg_delay')} | {fmt('agg_thr')} |")
    out.append("\n`*` = paired difference significant at 95%.\n")
    out.append(f"**Selected config:** `{d['best']}` = {d['best_cfg']}\n")
    out.append("### 4.2 Demand range over which metering is a net win\n")
    out.append("| D | N delay no-meter | N delay meter | ΔN delay | N served no-meter → meter | junction delay no-meter | junction delay meter | Δjunction delay | Δjunction throughput | ΔGini |")
    out.append("|---:|---:|---:|:--|:--|---:|---:|:--|:--|:--|")
    for r in d["demand_sweep"]:
        def f2(k):
            x = r[k]["paired"]
            return f"{x['mean_diff']:+.2f} ({x['pct']:+.1f}%){'*' if x['significant_95'] else ''}"
        out.append(f"| {r['D']} | {r['N_delay']['nometer']['mean']:.1f} | {r['N_delay']['meter']['mean']:.1f} | {f2('N_delay')} | "
                   f"{r['N_served']['nometer']['mean']:.3f} → {r['N_served']['meter']['mean']:.3f} | "
                   f"{r['agg_delay']['nometer']['mean']:.1f} | {r['agg_delay']['meter']['mean']:.1f} | {f2('agg_delay')} | "
                   f"{f2('agg_thr')} | {f2('gini')} |")
    out.append("")


def comp_tables(out):
    for p in sorted(glob.glob(os.path.join(RES, "comparison", "comparison_ttt*.json"))):
        d = json.load(open(p))
        for sname, sd in d.items():
            if sname == "meter_cfg":
                continue
            w = sd["webster"]
            out.append(f"### 5.x Scenario `{sname}` — Webster sizing of the signalized reference\n")
            out.append(f"Flow ratios {({k: round(v,4) for k,v in w['flow_ratios'].items()})}, "
                       f"Y = {w['Y']}, L = {w['L']} s, {w['note']}, greens = {w['greens']}, "
                       f"yellow = {w['yellow']} s.\n")
            for tkey, arms in sd["arms"].items():
                out.append(f"#### Scenario `{sname}`, `--time-to-teleport` = {tkey[3:]} "
                           f"(mean ± 95% CI over CRN seeds)\n")
                out.append("| variant | junction delay (s, censoring-robust) | delay, completed only (s) | throughput (veh/h) | served frac | min approach served | Gini(delay) | max/min delay | teleports | never inserted | still running |")
                out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
                for v, a in arms.items():
                    out.append(f"| `{v}` | {a['delay_robust_s']['mean']:.1f} ± {a['delay_robust_s']['ci95']:.1f} | "
                               f"{a['delay_completed_only_s']['mean']:.1f} | "
                               f"{a['throughput_vph']['mean']:.0f} ± {a['throughput_vph']['ci95']:.0f} | "
                               f"{a['served_frac']['mean']:.3f} | {a['min_approach_served_frac']['mean']:.3f} | "
                               f"{a['equity_gini_delay']['mean']:.3f} | {a['equity_maxmin_delay_ratio']['mean']:.1f} | "
                               f"{a['teleports']['mean']:.1f} | {a['never_inserted']['mean']:.0f} | "
                               f"{a['still_running']['mean']:.0f} |")
                out.append("")
                if any("ssm_total" in a for a in arms.values()):
                    out.append("| variant | SSM conflicts total | following | merging | crossing | genuine collisions | type-111 artifacts | TTC<1.5 s | PET<1.0 s | worst TTC | max DRAC |")
                    out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
                    for v, a in arms.items():
                        if "ssm_total" not in a:
                            continue
                        g = lambda k: a["ssm_" + k]["mean"]
                        out.append(f"| `{v}` | {g('total'):.0f} | {g('following'):.0f} | {g('merging'):.0f} | "
                                   f"{g('crossing'):.0f} | {g('collisions'):.1f} | {g('type111_artifacts'):.1f} | "
                                   f"{g('severe_ttc'):.0f} | {g('severe_pet'):.0f} | {g('worst_ttc'):.2f} | {g('max_drac'):.2f} |")
                    out.append("")
                out.append("| variant | N delay | E delay | S delay | W delay | N thr | E thr | S thr | W thr |")
                out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|")
                for v, a in arms.items():
                    out.append("| `" + v + "` | " +
                               " | ".join(f"{a[f'arm_{x}_delay']['mean']:.1f}" for x in "NESW") + " | " +
                               " | ".join(f"{a[f'arm_{x}_thr']['mean']:.0f}" for x in "NESW") + " |")
                out.append("")


if __name__ == "__main__":
    out = []
    for fn in (cap_tables, starv_tables, meter_tables, comp_tables):
        try:
            fn(out)
        except FileNotFoundError as e:
            out.append(f"_(missing: {e})_\n")
    txt = "\n".join(out)
    open(os.path.join(RES, "tables.md"), "w").write(txt)
    print(txt)
