#!/usr/bin/env python3
"""Build every results table for FINDINGS.md from the collected metrics CSVs."""
import collections
import csv
import glob
import json
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from statlib import crn_variance_reduction, mean_ci, paired_diff, required_n  # noqa: E402

ANA = os.path.join(ROOT, "analysis")
OUT = []
MPS2MPH = 2.23694


def P(s=""):
    OUT.append(s)


def load(tag):
    p = os.path.join(ANA, f"metrics_{tag}.csv")
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []


def F(r, k, d=float("nan")):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return d


# =========================== 1. MAIN five-arm comparison ==================== #
def main_table():
    rows = load("MAIN")
    g = collections.defaultdict(dict)
    for r in rows:
        g[r["run"].split("_")[1]][int(F(r, "seed"))] = r
    order = ["A", "B", "Clo", "Chi", "D"]
    names = {"A": "A  all-4-GP", "B": "B  HOV-only", "Clo": "C-lo HOT $0.12",
             "Chi": "C-hi HOT $1.50", "D": "D  HOT dynamic"}
    metrics = [
        ("peak_persons_per_h", "corridor person throughput (persons/h, 900-3600 s)", 0),
        ("peak_veh_per_h", "corridor vehicle throughput (veh/h)", 0),
        ("all_pht_dd_h", "total person-hours travelled incl. insertion delay (h)", 1),
        ("all_phd_h", "total person-hours of DELAY incl. insertion delay (h)", 1),
        ("all_mean_dur", "mean in-network trip duration (s)", 1),
        ("all_mean_dd", "mean departDelay / insertion backlog (s)", 1),
        ("ld_m5_gp_speed", "GP-lane space-mean speed at m5 (m/s)", 2),
        ("ld_m5_l3_speed", "managed-lane space-mean speed at m5 (m/s)", 2),
        ("ld_m5_gp_flow", "GP-lane flow at m5 (veh/h, 3 lanes)", 0),
        ("ld_m5_l3_flow", "managed-lane flow at m5 (veh/h)", 0),
        ("ml_veh_per_h_peak", "managed-lane vehicle throughput (veh/h, peak)", 0),
        ("ml_persons_per_h_peak", "managed-lane person throughput (persons/h, peak)", 0),
        ("revenue", "toll revenue ($ / run)", 0),
        ("take_rate", "SOV take-rate", 3),
        ("completed", "vehicles completed", 0),
        ("never_inserted", "vehicles never inserted", 0),
        ("still_running_at_end", "vehicles still running at sim end", 0),
        ("teleports", "teleports", 0),
    ]
    P("### Table 1 — Five policy arms, 5 CRN replications (mean +/- 95% CI half-width)")
    P()
    P("| metric | " + " | ".join(names[a] for a in order) + " |")
    P("|---|" + "---|" * len(order))
    for k, lab, dec in metrics:
        cells = []
        for a in order:
            vals = [F(g[a][s], k) for s in sorted(g[a])]
            vals = [v for v in vals if not math.isnan(v)]
            if not vals:
                cells.append("n/a")
                continue
            m, hw, n = mean_ci(vals)
            cells.append(f"{m:.{dec}f} ± {hw:.{dec}f}" if n > 1 else f"{m:.{dec}f}")
        P(f"| {lab} | " + " | ".join(cells) + " |")
    P()
    P("### Table 2 — Paired (CRN) difference vs arm A, 5 replications")
    P()
    P("| arm | Δ person throughput (persons/h) | Δ% | Δ person-hours (h) | Δ% | significant at 95%? |")
    P("|---|---|---|---|---|---|")
    for a in ["B", "Clo", "Chi", "D"]:
        d1 = paired_diff({s: F(g[a][s], "peak_persons_per_h") for s in g[a]},
                         {s: F(g["A"][s], "peak_persons_per_h") for s in g["A"]})
        d2 = paired_diff({s: F(g[a][s], "all_pht_dd_h") for s in g[a]},
                         {s: F(g["A"][s], "all_pht_dd_h") for s in g["A"]})
        b1 = st.mean(F(g["A"][s], "peak_persons_per_h") for s in g["A"])
        b2 = st.mean(F(g["A"][s], "all_pht_dd_h") for s in g["A"])
        P(f"| {names[a]} | {d1['mean']:+.0f} ± {d1['hw']:.0f} | {100*d1['mean']/b1:+.2f}% | "
          f"{d2['mean']:+.1f} ± {d2['hw']:.1f} | {100*d2['mean']/b2:+.2f}% | "
          f"{'yes / yes' if d1['sig'] and d2['sig'] else ('%s / %s' % ('yes' if d1['sig'] else 'no', 'yes' if d2['sig'] else 'no'))} |")
    P()

    # ---- equity table -----------------------------------------------------
    P("### Table 3 — Equity: outcomes by VOT quartile (mean over 5 CRN replications)")
    P()
    P("Q1 = lowest-VOT 25% of the fleet, Q4 = highest. `generalised cost` = "
      "own travel time (incl. insertion delay) valued at own VOT, plus toll paid, per person.")
    P()
    hdr = "| arm | " + " | ".join(f"Q{q} gen.cost $/person" for q in (1, 2, 3, 4)) + \
          " | " + " | ".join(f"Q{q} % paying" for q in (1, 2, 3, 4)) + \
          " | " + " | ".join(f"Q{q} % using ML" for q in (1, 2, 3, 4)) + " |"
    P(hdr)
    P("|---|" + "---|" * 12)
    for a in order:
        gc = [st.mean(F(g[a][s], f"q{q}_gc") for s in g[a]) for q in (1, 2, 3, 4)]
        pay = [st.mean(F(g[a][s], f"q{q}_pay_share") for s in g[a]) for q in (1, 2, 3, 4)]
        ml = [st.mean(F(g[a][s], f"q{q}_ml_share") for s in g[a]) for q in (1, 2, 3, 4)]
        P(f"| {names[a]} | " + " | ".join(f"{x:.2f}" for x in gc) + " | " +
          " | ".join(f"{100*x:.1f}%" for x in pay) + " | " +
          " | ".join(f"{100*x:.1f}%" for x in ml) + " |")
    P()
    P("### Table 4 — Equity: change in generalised cost vs arm A, by VOT quartile ($/person, paired)")
    P()
    P("| arm | Q1 | Q2 | Q3 | Q4 | Q4−Q1 (regressivity gap) |")
    P("|---|---|---|---|---|---|")
    for a in ["B", "Clo", "Chi", "D"]:
        ds = []
        for q in (1, 2, 3, 4):
            d = paired_diff({s: F(g[a][s], f"q{q}_gc") for s in g[a]},
                            {s: F(g["A"][s], f"q{q}_gc") for s in g["A"]})
            ds.append(d)
        basq = [st.mean(F(g["A"][s], f"q{q}_gc") for s in g["A"]) for q in (1, 2, 3, 4)]
        P(f"| {names[a]} | " + " | ".join(
            f"{d['mean']:+.3f} ± {d['hw']:.3f} ({100*d['mean']/b:+.1f}%)"
            for d, b in zip(ds, basq)) + f" | {ds[3]['mean'] - ds[0]['mean']:+.3f} |")
    P()

    P("### Table 4b — Equity of CONVERTING THE HOV LANE TO HOT: change vs arm B, by VOT quartile")
    P()
    P("| arm (vs B) | Q1 Δ$ (Δ%) | Q2 Δ$ (Δ%) | Q3 Δ$ (Δ%) | Q4 Δ$ (Δ%) | "
      "Q1 Δ mean travel time (s) | Q4 Δ mean travel time (s) |")
    P("|---|---|---|---|---|---|---|")
    for a in ["Clo", "Chi", "D"]:
        cells = []
        for q in (1, 2, 3, 4):
            d = paired_diff({s: F(g[a][s], f"q{q}_gc") for s in g[a]},
                            {s: F(g["B"][s], f"q{q}_gc") for s in g["B"]})
            b = st.mean(F(g["B"][s], f"q{q}_gc") for s in g["B"])
            cells.append(f"{d['mean']:+.3f} ± {d['hw']:.3f} ({100*d['mean']/b:+.1f}%)")
        tt = []
        for q in (1, 4):
            d = paired_diff({s: F(g[a][s], f"q{q}_mean_tt") for s in g[a]},
                            {s: F(g["B"][s], f"q{q}_mean_tt") for s in g["B"]})
            tt.append(f"{d['mean']:+.1f} ± {d['hw']:.1f}")
        P(f"| {names[a]} | " + " | ".join(cells) + " | " + " | ".join(tt) + " |")
    P()

    # ---- CRN diagnostics --------------------------------------------------
    P("### Table 5 — CRN diagnostics and replication adequacy (5 seeds)")
    P()
    P("| metric | arm-A CV | required n for ±5% CI (arm A) | CRN variance-reduction factor (B vs A) | paired corr ρ |")
    P("|---|---|---|---|---|")
    for k, lab in [("peak_persons_per_h", "person throughput"),
                   ("all_pht_dd_h", "person-hours incl. delay"),
                   ("all_mean_dur", "mean trip duration")]:
        A = [F(g["A"][s], k) for s in sorted(g["A"])]
        vrf, rho = crn_variance_reduction({s: F(g["B"][s], k) for s in g["B"]},
                                          {s: F(g["A"][s], k) for s in g["A"]})
        P(f"| {lab} | {100*st.stdev(A)/st.mean(A):.2f}% | {required_n(A):.0f} | {vrf:.2f}x | {rho:+.3f} |")
    P()


# =========================== 2. H1 ========================================== #
def h1_tables():
    rows = load("H1all")
    grp = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in rows:
        p = r["run"].split("_")
        grp[(p[0], p[2][1:])][p[1]][int(F(r, "seed"))] = r

    def block(fam, xlab, title, conv=lambda k: k):
        keys = sorted({k for (f, k) in grp if f == fam}, key=float)
        P(f"**{title}**")
        P()
        P(f"| {xlab} | A persons/h | B persons/h | Δ persons/h (95% CI) | Δ% | "
          f"A person-h | B person-h | Δ person-h (95% CI) | Δ% | B managed-lane veh/h | B managed-lane persons/h |")
        P("|---|---|---|---|---|---|---|---|---|---|---|")
        cross = []
        for k in keys:
            d = grp[(fam, k)]
            if "A" not in d or "B" not in d:
                continue
            A, B = d["A"], d["B"]
            f = lambda x, c: {s: F(x[s], c) for s in x}          # noqa: E731
            d1 = paired_diff(f(B, "peak_persons_per_h"), f(A, "peak_persons_per_h"))
            d2 = paired_diff(f(B, "all_pht_dd_h"), f(A, "all_pht_dd_h"))
            ma = st.mean(f(A, "peak_persons_per_h").values())
            mb = st.mean(f(B, "peak_persons_per_h").values())
            pa = st.mean(f(A, "all_pht_dd_h").values())
            pb = st.mean(f(B, "all_pht_dd_h").values())
            cross.append((float(k), 100 * d1["mean"] / ma, 100 * d2["mean"] / pa))
            P(f"| {conv(k)} | {ma:.0f} | {mb:.0f} | {d1['mean']:+.0f} ± {d1['hw']:.0f} | "
              f"{100*d1['mean']/ma:+.2f}% | {pa:.1f} | {pb:.1f} | {d2['mean']:+.1f} ± {d2['hw']:.1f} | "
              f"{100*d2['mean']/pa:+.2f}% | {st.mean(f(B,'ml_veh_per_h_peak').values()):.0f} | "
              f"{st.mean(f(B,'ml_persons_per_h_peak').values()):.0f} |")
        P()
        # linear interpolation of the sign change
        for idx, what in ((1, "person throughput"), (2, "person-hours")):
            zc = None
            for i in range(len(cross) - 1):
                a, b = cross[i][idx], cross[i + 1][idx]
                if (a < 0) != (b < 0) and a != b:
                    zc = cross[i][0] + (cross[i + 1][0] - cross[i][0]) * (0 - a) / (b - a)
                    break
            P(f"- crossing where arm B stops losing on **{what}**: "
              + (f"`{xlab} ≈ {zc:.3f}`" if zc is not None else "not reached within the swept range"))
        P()
        return cross

    P("### Table 6 — H1 empty-lane paradox sweeps (arm B minus arm A, paired CRN, 3 seeds each)")
    P()
    block("H1cp", "carpool share", "6a. Carpool share, at demand scale 1.35 (104% of measured 4-lane capacity)")
    block("H1cp120", "carpool share", "6b. Carpool share, at demand scale 1.20 (92% of capacity)")
    block("H1bus", "buses/h", "6c. Transit intensity (buses/h, ~40 passengers each), carpool 15%, scale 1.35")
    block("H1dm", "demand scale", "6d. Demand level, carpool 15%",
          conv=lambda k: f"{k} ({100*5650*float(k)/7354:.0f}% of capacity)")


# =========================== 3. H2 ========================================== #
def h2_tables():
    def sweep(tag, pref, title, scale_note):
        rows = [r for r in load(tag) if r["run"].startswith(pref)]
        g = collections.defaultdict(list)
        for r in rows:
            g[float(r["run"].split("toll")[1].split("_")[0])].append(r)
        P(f"**{title}** ({scale_note})")
        P()
        P("| toll $ | SOV take-rate | managed-lane flow at m5 (veh/h) | managed-lane veh/h (peak) | "
          "managed-lane persons/h | corridor persons/h | person-hours (h) | revenue $ | ML occ % | ML speed mph | GP speed mph |")
        P("|---|---|---|---|---|---|---|---|---|---|---|")
        best = {}
        for t in sorted(g):
            rs = g[t]
            m = lambda k: st.mean(F(r, k) for r in rs)                       # noqa: E731
            P(f"| {t:.2f} | {m('take_rate'):.3f} | {m('ld_m5_l3_flow'):.0f} | {m('ml_veh_per_h_peak'):.0f} | "
              f"{m('ml_persons_per_h_peak'):.0f} | {m('peak_persons_per_h'):.0f} | {m('all_pht_dd_h'):.1f} | "
              f"{m('revenue'):.0f} | {m('ml_occ_peak_mean'):.2f} | {m('ml_speed_peak_mean')*MPS2MPH:.1f} | "
              f"{m('ld_m5_gp_speed')*MPS2MPH:.1f} |")
            for k in ("ld_m5_l3_flow", "ml_veh_per_h_peak", "peak_persons_per_h",
                      "ml_persons_per_h_peak", "revenue"):
                v = m(k)
                if k not in best or v > best[k][1]:
                    best[k] = (t, v)
            if "all_pht_dd_h" not in best or m("all_pht_dd_h") < best["all_pht_dd_h"][1]:
                best["all_pht_dd_h"] = (t, m("all_pht_dd_h"))
        P()
        P(f"- toll maximising **managed-lane VEHICLE throughput** (lane flow at m5): "
          f"**${best['ld_m5_l3_flow'][0]:.2f}** ({best['ld_m5_l3_flow'][1]:.0f} veh/h)")
        P(f"- toll maximising **corridor PERSON throughput**: **${best['peak_persons_per_h'][0]:.2f}** "
          f"({best['peak_persons_per_h'][1]:.0f} persons/h)")
        P(f"- toll maximising **managed-lane PERSON throughput**: ${best['ml_persons_per_h_peak'][0]:.2f}")
        P(f"- toll MINIMISING total person-hours: ${best['all_pht_dd_h'][0]:.2f} ({best['all_pht_dd_h'][1]:.1f} h)")
        P(f"- toll maximising **REVENUE**: **${best['revenue'][0]:.2f}** (${best['revenue'][1]:.0f})")
        P()
        return g, best

    P("### Table 7 — H2 static-toll sweeps")
    P()
    g1, b1 = sweep("H2all", "H2_toll", "7a. Continuous-access HOT lane at base demand",
                   "scale 1.35 = 104% of measured 4-lane capacity, carpool 15%, 3 CRN seeds/point")
    g2, b2 = sweep("H2all", "H2lo_toll", "7b. Continuous-access HOT lane at lower demand",
                   "scale 1.05 = 81% of capacity")
    g3, b3 = sweep("H2g", "H2g_toll", "7c. LIMITED-ACCESS (gated) HOT lane at base demand",
                   "scale 1.35, the one configuration in which the lane could plausibly be over-subscribed")

    # ---- price elasticity --------------------------------------------------
    P("### Table 8 — Empirical price-elasticity (demand) curve for the managed lane")
    P()
    pts = [(t, st.mean(F(r, "take_rate") for r in rs),
            st.mean(F(r, "est_saving_peak_mean") for r in rs))
           for t, rs in sorted(g1.items()) if t > 0]
    P("| toll $ | take-rate | ln(toll) | ln(take-rate) | point arc-elasticity | mean estimated time saving offered (s) |")
    P("|---|---|---|---|---|---|")
    for i, (t, q, sav) in enumerate(pts):
        if i == 0:
            e = ""
        else:
            t0, q0, _ = pts[i - 1]
            e = f"{(math.log(q)-math.log(q0))/(math.log(t)-math.log(t0)):+.2f}"
        P(f"| {t:.2f} | {q:.3f} | {math.log(t):+.3f} | {math.log(q):+.3f} | {e} | {sav:.0f} |")
    n = len(pts)
    sx = sum(math.log(t) for t, q, _ in pts)
    sy = sum(math.log(q) for t, q, _ in pts)
    sxx = sum(math.log(t) ** 2 for t, q, _ in pts)
    sxy = sum(math.log(t) * math.log(q) for t, q, _ in pts)
    beta = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    alpha = (sy - beta * sx) / n
    ybar = sy / n
    ss_tot = sum((math.log(q) - ybar) ** 2 for t, q, _ in pts)
    ss_res = sum((math.log(q) - (alpha + beta * math.log(t))) ** 2 for t, q, _ in pts)
    P()
    P(f"Constant-elasticity fit over the 13 positive-toll points: "
      f"**ln(take-rate) = {alpha:+.3f} {beta:+.3f}·ln(toll)**, i.e. a constant price elasticity of "
      f"**{beta:+.2f}** (R² = {1-ss_res/ss_tot:.3f}).")
    P()
    json.dump({"alpha": alpha, "beta": beta, "r2": 1 - ss_res / ss_tot,
               "points": [[t, q, s] for t, q, s in pts]},
              open(os.path.join(ANA, "price_elasticity_fit.json"), "w"), indent=1)
    return b1, b2, b3


# =========================== 4. H3 ========================================== #
def h3_tables():
    rows = load("H3")
    g = collections.defaultdict(dict)
    for r in rows:
        _, arm, acc, sd = r["run"].split("_")
        g[(arm, acc)][int(F(r, "seed"))] = r
    h3 = {}
    hp = os.path.join(ANA, "h3_weaving.json")
    if os.path.exists(hp):
        for rec in json.load(open(hp)):
            _, arm, acc, sd = rec["run"].split("_")
            h3[(arm, acc, int(sd[1:]))] = rec
    P("### Table 9 — H3 access design: continuous vs limited-access (gated) managed lane")
    P()
    P("Gates: mainline segments m2, m5, m8, m11 (4 x ~493 m ingress/egress windows). Elsewhere "
      "lane 2 carries `changeLeft=\"authority\"` and lane 3 `changeRight=\"authority\"`, i.e. a "
      "buffer only enforcement vehicles may cross. 3 CRN seeds per cell, SSM device on 20% of vehicles.")
    P()
    P("| arm | access | corridor persons/h | person-hours (h) | GP speed m5 (m/s) | ML speed m5 (m/s) | "
      "ML flow m5 (veh/h) | total lane changes (peak) | ML ingress+egress changes | ML-change spatial "
      "concentration (× uniform) | share of ML changes inside a gate | TTC conflicts /1000 equipped | DRAC conflicts /1000 equipped |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in ("B", "C"):
        for acc in ("cont", "gated"):
            d = g.get((arm, acc), {})
            if not d:
                continue
            m = lambda k: st.mean(F(d[s], k) for s in d)                      # noqa: E731
            hs = [h3.get((arm, acc, s)) for s in d]
            hs = [x for x in hs if x]
            hm = (lambda k: st.mean(x[k] for x in hs)) if hs else (lambda k: float("nan"))
            P(f"| {arm} | {'continuous' if acc=='cont' else 'gated'} | {m('peak_persons_per_h'):.0f} | "
              f"{m('all_pht_dd_h'):.1f} | {m('ld_m5_gp_speed'):.2f} | {m('ld_m5_l3_speed'):.2f} | "
              f"{m('ld_m5_l3_flow'):.0f} | {m('lc_total_peak'):.0f} | {hm('ml_changes'):.0f} | "
              f"{hm('ml_change_concentration_vs_uniform'):.2f} | {100*hm('ml_changes_in_gate_share'):.1f}% | "
              f"{hm('ssm_ttc_per_1000_equipped'):.1f} | {hm('ssm_drac_per_1000_equipped'):.1f} |")
    P()
    for arm in ("B", "C"):
        a, b = g.get((arm, "gated"), {}), g.get((arm, "cont"), {})
        if not a or not b:
            continue
        for k, lab in [("peak_persons_per_h", "person throughput"),
                       ("all_pht_dd_h", "person-hours"),
                       ("lc_total_peak", "total lane changes")]:
            d = paired_diff({s: F(a[s], k) for s in a}, {s: F(b[s], k) for s in b})
            base = st.mean(F(b[s], k) for s in b)
            P(f"- arm {arm}: gated − continuous, {lab}: {d['mean']:+.1f} ± {d['hw']:.1f} "
              f"({100*d['mean']/base:+.2f}%), significant={d['sig']}")
    P()


# =========================== 5. teleports / accounting ====================== #
def tp_table():
    rows = load("TP")
    if not rows:
        return
    P("### Table 10 — Teleport-artifact sensitivity (`--time-to-teleport` sweep, seed 1001)")
    P()
    P("| arm | time-to-teleport | teleports | teleport share of completed | completed | still running at end | "
      "never inserted | corridor persons/h | person-hours (h) | mean duration (s) |")
    P("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (r["run"].split("_")[1], F(r, "time_to_teleport"))):
        P(f"| {r['run'].split('_')[1]} | {F(r,'time_to_teleport'):.0f} | {F(r,'teleports'):.0f} | "
          f"{100*F(r,'teleport_share_of_completed'):.3f}% | {F(r,'completed'):.0f} | "
          f"{F(r,'still_running_at_end'):.0f} | {F(r,'never_inserted'):.0f} | "
          f"{F(r,'peak_persons_per_h'):.0f} | {F(r,'all_pht_dd_h'):.1f} | {F(r,'all_mean_dur'):.1f} |")
    P()


if __name__ == "__main__":
    P("# Managed-lane corridor — results tables")
    P()
    main_table()
    h1_tables()
    h2_tables()
    h3_tables()
    tp_table()
    dest = os.path.join(ANA, "tables.md")
    open(dest, "w").write("\n".join(OUT) + "\n")
    print("\n".join(OUT))
    print("\n-> " + dest)
