"""Build every deliverable table and the hypothesis verdicts from the experiment JSONs."""
import json
import os
import sys
from collections import defaultdict

import numpy as np

import wz_common as W
import stats_util as S
import analyze

TAB = W.TABLES


def load(path):
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def group(rows, key):
    g = defaultdict(list)
    for r in rows:
        if not r.get("ok", True):
            continue
        g[key(r)].append(r)
    return g


def col(rows, m):
    return [r.get(m, np.nan) for r in rows]


def by_seed(rows, m):
    return {r["seed"]: r.get(m, np.nan) for r in rows}


def paired_arm(g, a, b, m, seeds):
    ra = by_seed(g[a], m) if a in g else {}
    rb = by_seed(g[b], m) if b in g else {}
    xs = [s for s in seeds if s in ra and s in rb]
    return S.paired([ra[s] for s in xs], [rb[s] for s in xs])


# =============================================================== capacity (H1/H5/H6)
def capacity_report():
    rows = load(os.path.join(W.OUT, "capacity", "capacity_results.json"))
    if not rows:
        return "", {}
    g = group(rows, lambda r: r["tagname"])
    L = ["# Measured work-zone capacity vs the HCM reference", "",
         f"Definition: queue-discharge rate at the E1 station 15 m before the end of the",
         f"activity area, per OPEN lane, over queued 60 s intervals excluding the first",
         f"{analyze.QD_WARMUP:.0f} s after queue onset. Demand is 100% passenger cars, so",
         f"veh/h/ln == pc/h/ln and the HCM freeway work-zone value of "
         f"{analyze.HCM_WZ_REF:.0f} pc/h/ln is directly comparable (no PCE conversion).",
         "Overload demand 8400 veh/h, flat profile, 3 CRN seeds.", "",
         "## H1 -- per-open-lane capacity by lanes closed", "",
         "| config | open lanes | queue-discharge cap (pc/h/ln) 95% CI | sustained-max cap (pc/h/ln) | total discharge (veh/h) | vs HCM 1600 | teleports | collisions |",
         "|---|---:|---|---:|---:|---:|---:|---:|"]
    h1 = {}
    for name, open_lanes in (("H1_unobstructed", 3), ("H1_speedonly", 3),
                             ("H1_lc1", 2), ("H1_lc2", 1)):
        rs = g.get(name, [])
        if not rs:
            continue
        c = S.mean_ci(col(rs, "cap"))
        cs = S.mean_ci(col(rs, "cap_sust"))
        tot = S.mean_ci([r["cap"] * r["n_open_lanes"] for r in rs])
        use = c["mean"] if np.isfinite(c["mean"]) else cs["mean"]
        h1[name] = dict(cap=c, cap_sust=cs, use=use, open_lanes=open_lanes,
                        vs_hcm=S.onesample_vs(col(rs, "cap"), analyze.HCM_WZ_REF))
        capstr = ("n/a (no upstream queue formed)" if not np.isfinite(c["mean"])
                  else f"{c['mean']:.0f} [{c['lo']:.0f}, {c['hi']:.0f}]")
        L.append(f"| {name.replace('H1_','')} | {open_lanes} | {capstr} | "
                 f"{cs['mean']:.0f} | {tot['mean'] if np.isfinite(tot['mean']) else float('nan'):.0f} | "
                 f"{(use - analyze.HCM_WZ_REF):+.0f} | "
                 f"{np.mean(col(rs,'teleports')):.1f} | {np.mean(col(rs,'n_collisions')):.1f} |")

    L += ["",
          "**The `unobstructed` row's queue-discharge cell is deliberately blank.** A flat",
          "8400 veh/h overload does NOT saturate a free-flowing 3-lane freeway in SUMO:",
          "only 4650 of 8447 vehicles were inserted, and the upstream and downstream",
          "stations both read ~4100 veh/h, i.e. the corridor ran at SUMO's INSERTION",
          "throughput (~1370 veh/h/ln at departSpeed=\"max\"), not at road capacity. The",
          "sustained-max column for that row is an insertion rate, not a capacity, and is",
          "NOT used as the H1 reference.", ""]

    # ---- the corrected reference: queue-build-and-release probe
    probe = load(os.path.join(W.OUT, "capacity_probe", "probe_results.json"))
    pr = {}
    if probe:
        pg = defaultdict(list)
        for r in probe:
            pg[(r["lanes_closed"], r["wz_speed"])].append(r["cap_per_lane"])
        L += ["### Corrected reference: queue-build-and-release probe (same segment)", "",
              "Blocker vehicles parked across every lane at the start of the termination",
              "area for 900 s, then removed; discharge measured from release+120 s.",
              "`--time-to-teleport` raised to 1200 s so the gate cannot manufacture",
              "teleports (verified: 0 teleports in every cell but one, which had 2).", "",
              "| configuration | open lanes | queue-discharge capacity (pc/h/ln) 95% CI | vs unobstructed | vs HCM 1600 |",
              "|---|---:|---|---:|---:|"]
        base = float(np.mean(pg[(0, 120)])) if (0, 120) in pg else np.nan
        for (lc, v), nm in (((0, 120), "unobstructed, 3 lanes @120 km/h"),
                            ((0, 80), "speed reduction only, 3 lanes @80 km/h"),
                            ((1, 80), "1 lane closed, 2 open @80 km/h"),
                            ((2, 80), "2 lanes closed, 1 open @80 km/h")):
            if (lc, v) not in pg:
                continue
            c = S.mean_ci(pg[(lc, v)])
            pr[(lc, v)] = c
            L.append(f"| {nm} | {3-lc} | {c['mean']:.0f} [{c['lo']:.0f}, {c['hi']:.0f}] | "
                     f"{100*(c['mean']-base)/base:+.1f}% | "
                     f"{100*(c['mean']-analyze.HCM_WZ_REF)/analyze.HCM_WZ_REF:+.1f}% |")
        L += ["", "### H1 verdict", ""]
        for lc, name in ((1, "H1_lc1"), (2, "H1_lc2")):
            if name not in h1 or (lc, 80) not in pr:
                continue
            natural = h1[name]["use"]
            seg = pr[(lc, 80)]["mean"]
            L.append(f"- **{lc} lane{'s' if lc>1 else ''} closed**: work-zone "
                     f"queue-discharge capacity **{natural:.0f} pc/h/open-lane** "
                     f"({100*(natural-base)/base:+.1f}% vs the {base:.0f} pc/h/ln "
                     f"unobstructed reference, "
                     f"{100*(natural-analyze.HCM_WZ_REF)/analyze.HCM_WZ_REF:+.1f}% vs "
                     f"HCM 1600). The same segment's own release-probe capacity is "
                     f"{seg:.0f}, so **{seg-natural:.0f} pc/h/ln ({100*(seg-natural)/seg:.1f}%) "
                     f"of the deficit is the FORCED MERGE itself**, the rest is the "
                     f"roadway/speed environment.")
        L += ["",
              f"The deficit grows with lanes closed ("
              f"{100*(h1['H1_lc1']['use']-base)/base:+.1f}% -> "
              f"{100*(h1['H1_lc2']['use']-base)/base:+.1f}%), and so does the merge's own "
              "share of it, which is the mechanism H1 was really asking about."]

    # H6 -- posted work-zone speed
    L += ["", "## H6 -- posted work-zone speed vs per-open-lane capacity (1 lane closed)", "",
          "| posted WZ speed (km/h) | cap (pc/h/ln) 95% CI |", "|---:|---|"]
    vs, caps = [], []
    for v in (50, 65, 80, 95, 110):
        rs = g.get(f"H6_v{v}", [])
        if not rs:
            continue
        c = S.mean_ci(col(rs, "cap"))
        vs.append(v)
        caps.append(c["mean"])
        L.append(f"| {v} | {c['mean']:.0f} [{c['lo']:.0f}, {c['hi']:.0f}] |")
    h6 = {}
    if len(vs) >= 3:
        sl, ic = np.polyfit(vs, caps, 1)
        r = np.corrcoef(vs, caps)[0, 1]
        h6 = dict(slope_per_kmh=float(sl), per_10kmh=float(sl * 10), r2=float(r ** 2))
        L += ["", f"OLS slope: **{sl*10:+.1f} veh/h/lane per +10 km/h of posted work-zone "
                  f"speed** (R^2 = {r**2:.3f}).",
              f"i.e. a 10 km/h speed REDUCTION costs {abs(sl*10):.0f} veh/h/lane "
              f"({100*abs(sl*10)/np.mean(caps):.1f}% of mean capacity)."]

    # H5 -- taper / advance warning
    L += ["", "## H5 -- taper length and advance-warning distance", "",
          "| lanes closed | taper (m) | adv warning (m) | cap (pc/h/ln) 95% CI |",
          "|---:|---:|---:|---|"]
    h5 = defaultdict(dict)
    for lc in (1, 2):
        for tp in (80, 200, 500):
            for aw in (500, 1500, 3000):
                rs = g.get(f"H5_lc{lc}_tp{tp}_aw{aw}", [])
                if not rs:
                    continue
                c = S.mean_ci(col(rs, "cap"))
                h5[lc][(tp, aw)] = c
                L.append(f"| {lc} | {tp} | {aw} | {c['mean']:.0f} "
                         f"[{c['lo']:.0f}, {c['hi']:.0f}] |")
    # main effects at lc=1
    if 1 in h5:
        cells = h5[1]
        tp_eff, aw_eff = {}, {}
        for (tp, aw), c in cells.items():
            tp_eff.setdefault(tp, []).append(c["mean"])
            aw_eff.setdefault(aw, []).append(c["mean"])
        L += ["", "Marginal means at 1 lane closed:", "",
              "- taper: " + ", ".join(f"{k} m -> {np.mean(v):.0f}" for k, v in sorted(tp_eff.items())),
              "- advance warning: " + ", ".join(f"{k} m -> {np.mean(v):.0f}" for k, v in sorted(aw_eff.items()))]
    return "\n".join(L), dict(h1=h1, h6=h6, h5={str(k): {str(kk): vv for kk, vv in v.items()}
                                                for k, v in h5.items()})


# =============================================================== control (H2/H3)
def control_report(lc=1):
    rows = load(os.path.join(W.OUT, "control", f"control_results_lc{lc}.json"))
    if not rows:
        return "", {}
    seeds = sorted({r["seed"] for r in rows if r.get("ok")})
    demands = sorted({r["peak"] for r in rows if r.get("ok")})
    gg = group(rows, lambda r: (r["peak"], r["arm"]))
    L = [f"# Merge-control arms ({lc} lane closed), CRN over {len(seeds)} seeds", "",
         "Headline traveller-cost metric is **TSTT (vehicle-hours, incl. the",
         "origin-insertion integral)**, not tripinfo timeLoss: the VSL arm changes the",
         "posted speed limit, and timeLoss is computed against the legally-observed limit,",
         "so it is confounded across arms (gotcha from `implement-variable-speed-limits`).",
         ""]
    arms = ["donothing", "early", "late", "dynamic", "vsl", "negctrl"]

    # negative control check
    L += ["## Negative control", ""]
    ncok = True
    for q in demands:
        a = paired_arm({k[1]: v for k, v in gg.items() if k[0] == q},
                       "negctrl", "donothing", "TSTT_vh", seeds)
        d = a["diff"]
        ok = abs(d) < 1e-6
        ncok &= ok
        L.append(f"- q={q}: negctrl - donothing TSTT = {d:+.3e} veh-h "
                 f"({'IDENTICAL' if ok else 'DIFFERS -- plumbing side effect!'})")

    L += ["", "## Throughput and delay by arm and demand", "",
          "| demand (veh/h) | arm | WZ cap (pc/h/ln) | TSTT (veh-h) | mean dur (s) | completed | still running | pending veh-h | hard brakes (near taper) | teleports | collisions |",
          "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    tab = {}
    for q in demands:
        for a in arms:
            rs = gg.get((q, a), [])
            if not rs:
                continue
            f = lambda m: np.nanmean(col(rs, m))
            tab[(q, a)] = {m: f(m) for m in
                           ("cap", "TSTT_vh", "TSD_vh", "mean_duration", "n",
                            "running", "vh_origin", "hard_brakes",
                            "hard_brakes_taper", "teleports", "n_collisions",
                            "CO2_kg", "mean_departdelay")}
            t = tab[(q, a)]
            L.append(f"| {q} | {a} | {t['cap']:.0f} | {t['TSTT_vh']:.1f} | "
                     f"{t['mean_duration']:.0f} | {t['n']:.0f} | {t['running']:.1f} | "
                     f"{t['vh_origin']:.2f} | {t['hard_brakes']:.0f} ({t['hard_brakes_taper']:.0f}) | "
                     f"{t['teleports']:.1f} | {t['n_collisions']:.1f} |")

    # H2: dynamic vs both statics, per demand, paired
    L += ["", "## H2 -- is there a demand band where DYNAMIC beats BOTH statics?", "",
          "Paired (CRN) mean difference in TSTT, veh-h; negative = dynamic better.", "",
          "| demand | dyn - early | 95% CI | p | dyn - late | 95% CI | p | dyn - donothing | beats both? |",
          "|---:|---:|---|---:|---:|---|---:|---:|---|"]
    h2 = {}
    for q in demands:
        gq = {k[1]: v for k, v in gg.items() if k[0] == q}
        de = paired_arm(gq, "dynamic", "early", "TSTT_vh", seeds)
        dl = paired_arm(gq, "dynamic", "late", "TSTT_vh", seeds)
        dn = paired_arm(gq, "dynamic", "donothing", "TSTT_vh", seeds)
        beats = (de["diff"] < 0 and de["sig"]) and (dl["diff"] < 0 and dl["sig"])
        h2[q] = dict(vs_early=de, vs_late=dl, vs_donothing=dn, beats_both=bool(beats))
        L.append(f"| {q} | {de['diff']:+.1f} | [{de['lo']:+.1f}, {de['hi']:+.1f}] | "
                 f"{de['p']:.3f} | {dl['diff']:+.1f} | [{dl['lo']:+.1f}, {dl['hi']:+.1f}] | "
                 f"{dl['p']:.3f} | {dn['diff']:+.1f} | "
                 f"{'**YES**' if beats else 'no'} |")
    band = [q for q in demands if h2[q]["beats_both"]]
    L += ["", (f"Band where dynamic significantly beats both statics: "
               f"**{min(band)}-{max(band)} veh/h**" if band else
               "**No demand level tested shows dynamic significantly beating both statics.**")]

    # best arm per demand
    L += ["", "## Best arm per demand (lowest mean TSTT)", "",
          "| demand | best arm | TSTT | 2nd | gap (veh-h) |", "|---:|---|---:|---|---:|"]
    best = {}
    for q in demands:
        cand = sorted([(tab[(q, a)]["TSTT_vh"], a) for a in arms
                       if (q, a) in tab and a != "negctrl"])
        best[q] = cand[0][1]
        L.append(f"| {q} | **{cand[0][1]}** | {cand[0][0]:.1f} | {cand[1][1]} | "
                 f"{cand[1][0]-cand[0][0]:.1f} |")

    # H3: throughput vs safety exchange rate for late merge
    L += ["", "## H3 -- late merge: throughput vs surrogate safety near the taper", "",
          "| demand | cap late - cap early (pc/h/ln) | p | near-taper hard brakes late - early | p | exchange rate (extra events per +100 pc/h/ln) | collisions late / early |",
          "|---:|---:|---:|---:|---:|---:|---|"]
    h3 = {}
    for q in demands:
        gq = {k[1]: v for k, v in gg.items() if k[0] == q}
        dc = paired_arm(gq, "late", "early", "cap", seeds)
        db = paired_arm(gq, "late", "early", "hard_brakes_taper", seeds)
        ex = db["diff"] / (dc["diff"] / 100.0) if dc["diff"] else np.nan
        cl = tab.get((q, "late"), {}).get("n_collisions", np.nan)
        ce = tab.get((q, "early"), {}).get("n_collisions", np.nan)
        h3[q] = dict(dcap=dc, dbrake=db, exchange=float(ex) if np.isfinite(ex) else None,
                     coll_late=cl, coll_early=ce)
        L.append(f"| {q} | {dc['diff']:+.0f} | {dc['p']:.3f} | {db['diff']:+.0f} | "
                 f"{db['p']:.3f} | {ex:+.1f} | {cl:.1f} / {ce:.1f} |")

    return "\n".join(L), dict(table={f"{k[0]}_{k[1]}": v for k, v in tab.items()},
                              h2=h2, h3=h3, best=best, negctrl_ok=bool(ncok),
                              demands=demands, seeds=seeds)


# =============================================================== diversion (H4)
def diversion_report():
    rows = load(os.path.join(W.OUT, "diversion", "diversion_results.json"))
    if not rows:
        return "", {}
    seeds = sorted({r["seed"] for r in rows if r.get("ok")})
    demands = sorted({r["peak"] for r in rows if r.get("ok")})
    phis = sorted({r["phi"] for r in rows if r.get("ok")})
    gg = group(rows, lambda r: (r["peak"], r["phi"]))
    L = ["# H4 -- diversion share vs corridor-wide TSTT", "",
         "TSTT = in-network vehicle-hours (edgeData sampledSeconds, all edges incl.",
         "internal) + origin-insertion integral int len(getPendingVehicles()) dt.", "",
         "| demand | phi | TSTT (veh-h) 95% CI | freeway | ramps | detour | internal | origin | detour flow (veh) | mean dur (s) |",
         "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    out = {}
    for q in demands:
        for phi in phis:
            rs = gg.get((q, phi), [])
            if not rs:
                continue
            c = S.mean_ci(col(rs, "TSTT_vh"))
            f = lambda m: np.nanmean(col(rs, m))
            out[(q, phi)] = dict(tstt=c, freeway=f("vh_freeway"), ramp=f("vh_ramp"),
                                 detour=f("vh_detour"), internal=f("vh_internal"),
                                 origin=f("vh_origin"), n_off=f("n_offramp"),
                                 dur=f("mean_duration"), tsd=f("TSD_vh"),
                                 tele=f("teleports"))
            o = out[(q, phi)]
            L.append(f"| {q} | {phi:.2f} | {c['mean']:.1f} [{c['lo']:.1f}, {c['hi']:.1f}] | "
                     f"{o['freeway']:.1f} | {o['ramp']:.1f} | {o['detour']:.1f} | "
                     f"{o['internal']:.1f} | {o['origin']:.2f} | {o['n_off']:.0f} | "
                     f"{o['dur']:.0f} |")
    h4 = {}
    L += ["", "## Optimum compliance share", "",
          "| demand | phi* (min TSTT) | TSTT at phi* | TSTT at phi=0 | TSTT at phi=1 | inverted-U? | phi* < 1 significantly? |",
          "|---:|---:|---:|---:|---:|---|---|"]
    for q in demands:
        avail = [(out[(q, p)]["tstt"]["mean"], p) for p in phis if (q, p) in out]
        if not avail:
            continue
        best_v, best_p = min(avail)
        t0 = out[(q, 0.0)]["tstt"]["mean"] if (q, 0.0) in out else np.nan
        t1 = out[(q, 1.0)]["tstt"]["mean"] if (q, 1.0) in out else np.nan
        # paired test phi* vs phi=1
        ra = by_seed(gg[(q, best_p)], "TSTT_vh")
        rb = by_seed(gg[(q, 1.0)], "TSTT_vh") if (q, 1.0) in gg else {}
        xs = [s for s in seeds if s in ra and s in rb]
        pt = S.paired([ra[s] for s in xs], [rb[s] for s in xs])
        inv = bool(best_p > 0 and best_p < 1 and t0 > best_v and t1 > best_v)
        h4[q] = dict(phi_star=best_p, tstt_star=best_v, tstt_0=t0, tstt_1=t1,
                     inverted_u=inv, vs_phi1=pt)
        L.append(f"| {q} | **{best_p:.2f}** | {best_v:.1f} | {t0:.1f} | {t1:.1f} | "
                 f"{'YES' if inv else 'no'} | {pt['diff']:+.1f} veh-h, p={pt['p']:.4f} "
                 f"{'(sig)' if pt['sig'] else '(ns)'} |")
    return "\n".join(L), dict(cells={f"{k[0]}_{k[1]}": v for k, v in out.items()}, h4=h4)


# =============================================================== schedule / RUC
def schedule_report():
    import exp_schedule as ES
    rows = load(os.path.join(W.OUT, "schedule", "schedule_results.json"))
    if not rows:
        return "", {}
    gg = group(rows, lambda r: (r["peak"], r["tagname"]))
    demands = sorted({r["peak"] for r in rows if r.get("ok")})
    seeds = sorted({r["seed"] for r in rows if r.get("ok")})
    L = ["# Closure scheduling: road-user cost of partial vs full closure", "",
         f"RUC = dTSTT x VOT ({ES.VOT}/veh-h) + dFuel x {ES.FUEL_PRICE}/L "
         f"+ dCO2 x {ES.CARBON_PRICE}/kg, each measured against the SAME demand with no",
         "work zone.  Fuel and CO2 are HBEFA3 edgeData sums over all edges incl. internal.",
         "", "| demand (veh/h) | strategy | TSTT (veh-h) | dTSTT | fuel (L) | CO2 (kg) | RUC | teleports |",
         "|---:|---|---:|---:|---:|---:|---:|---:|"]
    ruc = {}
    for q in demands:
        base = gg.get((q, "nowork"), [])
        if not base:
            continue
        bt = np.nanmean(col(base, "TSTT_vh"))
        bf = np.nanmean(col(base, "fuel_l"))
        bc = np.nanmean(col(base, "CO2_kg"))
        L.append(f"| {q} | nowork | {bt:.1f} | -- | {bf:.0f} | {bc:.0f} | -- | "
                 f"{np.nanmean(col(base,'teleports')):.1f} |")
        for strat in ("partial", "full"):
            rs = gg.get((q, strat), [])
            if not rs:
                continue
            t = np.nanmean(col(rs, "TSTT_vh"))
            fu = np.nanmean(col(rs, "fuel_l"))
            co = np.nanmean(col(rs, "CO2_kg"))
            cost = (t - bt) * ES.VOT + (fu - bf) * ES.FUEL_PRICE + (co - bc) * ES.CARBON_PRICE
            ruc[(q, strat)] = dict(TSTT=t, dTSTT=t - bt, fuel=fu, CO2=co, RUC=cost)
            L.append(f"| {q} | {strat} | {t:.1f} | {t-bt:+.1f} | {fu:.0f} | {co:.0f} | "
                     f"{cost:,.0f} | {np.nanmean(col(rs,'teleports')):.1f} |")
    L += ["", "## Threshold", "",
          "RUC here is the cost of ONE HOUR of closure at that demand.  A full closure is",
          "chosen in practice because it compresses the PROJECT, so the decision variable",
          "is the duration-compression factor `k` = (partial-closure project duration) /",
          "(full-closure project duration).  Full closure is justified when",
          "`k > RUC_full / RUC_partial`.", "",
          "| demand | RUC partial (per closure-hour) | RUC full | full - partial | cheaper at equal duration | break-even compression k* |",
          "|---:|---:|---:|---:|---|---:|"]
    thresh = None
    prev = None
    for q in demands:
        if (q, "partial") not in ruc or (q, "full") not in ruc:
            continue
        a, b = ruc[(q, "partial")]["RUC"], ruc[(q, "full")]["RUC"]
        cheaper = "full" if b < a else "partial"
        k = b / a if a > 0 else float("nan")
        ruc[(q, "partial")]["k_star"] = k
        L.append(f"| {q} | {a:,.0f} | {b:,.0f} | {b-a:+,.0f} | **{cheaper}** | "
                 f"{k:,.1f}x |" if np.isfinite(k) else
                 f"| {q} | {a:,.0f} | {b:,.0f} | {b-a:+,.0f} | **{cheaper}** | n/a |")
        if prev is not None and prev[1] != cheaper:
            thresh = (prev[0], q)
        prev = (q, cheaper)
    if thresh:
        L += ["", f"**Crossover between {thresh[0]} and {thresh[1]} veh/h** at equal "
                  "project duration."]
    else:
        L += ["", "**No crossover within the demand range tested at equal project "
                  "duration** -- the partial closure is cheaper at every demand level, "
                  "because this corridor's detour carries a large free-flow penalty "
                  "(~6.0 km of 60 km/h signalised arterial with three fixed-time signals "
                  "against 5.5 km of 120 km/h freeway) that every diverted vehicle pays "
                  "even when the arterial is uncongested. The scheduling decision therefore "
                  "turns entirely on duration compression `k*`, not on demand alone."]
    return "\n".join(L), dict(ruc={f"{k[0]}_{k[1]}": v for k, v in ruc.items()},
                              threshold=thresh)


if __name__ == "__main__":
    which = sys.argv[1:] or ["capacity", "control", "diversion", "schedule"]
    allj = {}
    for w in which:
        fn = dict(capacity=capacity_report, control=control_report,
                  diversion=diversion_report, schedule=schedule_report)[w]
        txt, dat = fn()
        if not txt:
            print(f"-- {w}: no results yet")
            continue
        p = os.path.join(TAB, f"{w.upper()}.md")
        with open(p, "w") as f:
            f.write(txt + "\n")
        allj[w] = dat
        print(txt)
        print(f"\nwrote {p}\n{'='*78}")
    json.dump(allj, open(os.path.join(TAB, "results_summary.json"), "w"),
              indent=1, default=str)
