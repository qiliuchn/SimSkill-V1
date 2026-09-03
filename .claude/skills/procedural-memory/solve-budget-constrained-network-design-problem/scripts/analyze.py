#!/usr/bin/env python3
"""
Outer-loop analysis on top of the exhaustive enumeration:
  * true (enumerated) optimum per budget level
  * GA with binary genome + budget-violation penalty in the decoder
  * practitioner baseline 1: rank-by-worst-v/c greedy funding
  * practitioner baseline 2: rank-by-isolated-BCR greedy funding
  * 10x10 pairwise project-interaction matrix + heatmap
  * budget-vs-best-benefit Pareto frontier and its concavity test
  * results table in TSTT-seconds and NPV
"""
import os, sys, json, csv, math, random, itertools
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import (PROJECTS, PROJECT_IDS, NPROJ, subset_cost, subset_from_mask,
                     mask_from_subset, nid, eid)
import econ

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "outputs")
JSONL = os.path.join(ROOT, "work", "enum.jsonl")
BASE_SWEEP = os.path.join(ROOT, "work", "sweep", "n4000")
BUDGETS = [0.0, 3.0, 6.0, 9.0, 12.0, 15.0]   # 0.0 = do-nothing, so the
# concavity test can also see the FIRST budget increment (where the
# non-concavity actually lives on this testbed)
MAIN_BUDGET = 12.0


# ------------------------------------------------------------------- data ----
def load():
    best = {}
    with open(JSONL) as f:
        for line in f:
            d = json.loads(line)
            if d.get("error"):
                continue
            best[d["mask"]] = d
    return best


def vc_table():
    """v/c per directed edge in the DO-NOTHING equilibrium at the study demand."""
    sys.path.insert(0, HERE)
    from demand_sweep import edge_green_ratios, edge_lanes, peak_flows
    s_eff = json.load(open(os.path.join(OUT, "vc_calibration.json")))["s_eff_veh_h_lane"]
    net = os.path.join(BASE_SWEEP, "net.net.xml")
    gr = edge_green_ratios(net); ln = edge_lanes(net)
    fl = peak_flows(os.path.join(BASE_SWEEP, "rec", "edgedata.xml"))
    return {e: f / (ln.get(e, 1) * s_eff * gr.get(e, 1.0)) for e, f in fl.items()}, s_eff


def project_target_vc(vc):
    """Practitioner 'worst v/c' score per project.

    lane project  -> max v/c over the two directed edges being widened
    new link a-b  -> max v/c over every edge lying on a two-link existing path
                     between a and b (either direction): the corridor the new
                     link would relieve.  Rule is stated, not tuned.
    """
    score = {}
    for p in PROJECTS:
        if p["kind"] == "lane":
            score[p["id"]] = max(vc.get(e, 0.0) for e in p["edges"])
        else:
            a, b = p["pair"]
            ai, aj = int(a[1]), int(a[2]); bi, bj = int(b[1]), int(b[2])
            mids = [nid(bi, aj), nid(ai, bj)]
            edges = []
            for m in mids:
                edges += [eid(a, m), eid(m, b), eid(b, m), eid(m, a)]
            score[p["id"]] = max(vc.get(e, 0.0) for e in edges if e in vc)
    return score


# --------------------------------------------------------------- baselines ---
def greedy_by_rank(order, budget):
    """Fund in descending rank order, skipping anything that does not fit."""
    chosen, spent = [], 0.0
    for pid in order:
        c = PROJECTS[PROJECT_IDS.index(pid)]["cost"]
        if spent + c <= budget + 1e-9:
            chosen.append(pid); spent += c
    return chosen, round(spent, 4)


# ---------------------------------------------------------------------- GA ---
def run_ga(tstt, budget, seed, pop=20, gens=30, pmut=0.10, tour=3):
    """Binary-genome GA.  The decoder applies a budget-violation penalty large
    enough that ANY infeasible genome is worse than EVERY feasible design, so an
    infeasible genome never needs an equilibrium evaluation (and never can be
    returned).  `evaluated` counts only the distinct FEASIBLE designs the GA
    actually had to simulate -- the honest evaluation count."""
    rng = random.Random(seed)
    T0 = tstt[0]
    PEN = 1e9                                   # per MU of budget violation
    evaluated = set()

    def fit(g):
        m = 0
        for k in range(NPROJ):
            if g[k]:
                m |= 1 << k
        viol = max(0.0, subset_cost(m) - budget)
        if viol > 0:
            return PEN * viol, m                # never simulated
        if m not in tstt:                       # must not happen: see the
            raise KeyError("feasible design %d (%s) was never evaluated - the "
                           "enumeration is incomplete for budget %.1f"
                           % (m, subset_from_mask(m), budget))
        evaluated.add(m)
        return tstt[m], m

    P = [[rng.randint(0, 1) for _ in range(NPROJ)] for _ in range(pop)]
    scored = [(fit(g)[0], g) for g in P]
    hist = []
    best = min(scored, key=lambda x: x[0])
    for gidx in range(gens):
        newP = [best[1][:]]                     # elitism
        while len(newP) < pop:
            def pick():
                cand = rng.sample(scored, min(tour, len(scored)))
                return min(cand, key=lambda x: x[0])[1]
            a, b = pick(), pick()
            child = [a[k] if rng.random() < 0.5 else b[k] for k in range(NPROJ)]
            for k in range(NPROJ):
                if rng.random() < pmut:
                    child[k] ^= 1
            newP.append(child)
        scored = [(fit(g)[0], g) for g in newP]
        gb = min(scored, key=lambda x: x[0])
        if gb[0] < best[0]:
            best = gb
        hist.append(dict(gen=gidx, best=best[0],
                         mean=sum(s for s, _ in scored) / len(scored),
                         n_unique_evals=len(evaluated)))
    m = 0
    for k in range(NPROJ):
        if best[1][k]:
            m |= 1 << k
    return dict(mask=m, subset=subset_from_mask(m), cost=subset_cost(m),
                tstt=tstt[m], n_unique_evals=len(evaluated),
                n_total_evals=pop * (gens + 1), history=hist)


# -------------------------------------------------------------------- main ---
def main():
    data = load()
    n_ok = sum(1 for d in data.values() if d.get("accounting_ok"))
    conv = {m: d for m, d in data.items() if d.get("converged")}
    tstt = {m: d["tstt"] for m, d in data.items()}
    T0 = tstt[0]
    print("loaded %d/1024 subsets; accounting_ok on %d; meeting convergence "
          "criterion on %d" % (len(data), n_ok, len(conv)))
    print("do-nothing TSTT = %.1f veh-s (%.1f veh-h)" % (T0, T0 / 3600))
    missing = [m for m in range(1 << NPROJ)
               if subset_cost(m) <= max(BUDGETS) + 1e-9 and m not in tstt]
    if missing:
        raise SystemExit("ABORT: %d budget-feasible designs (cost <= %.1f) are "
                         "not in the enumeration, so the 'true optimum' would not "
                         "be true. First few: %s"
                         % (len(missing), max(BUDGETS), missing[:10]))
    print("all %d designs with cost <= %.1f MU are present -> the per-budget "
          "optimum below is EXACT"
          % (sum(1 for m in range(1 << NPROJ) if subset_cost(m) <= max(BUDGETS) + 1e-9),
             max(BUDGETS)))

    ben = {m: T0 - t for m, t in tstt.items()}

    # ---- singletons ---------------------------------------------------------
    single = {}
    for k, p in enumerate(PROJECTS):
        m = 1 << k
        single[p["id"]] = dict(project=p["id"], cost=p["cost"], mask=m,
                               tstt=tstt[m], benefit_s=round(ben[m], 1),
                               benefit_pct=round(100 * ben[m] / T0, 3),
                               pv_benefits_mu=round(econ.pv_benefits_mu(ben[m]), 4),
                               npv_mu=round(econ.npv_mu(ben[m], p["cost"]), 4),
                               bcr=round(econ.bcr(ben[m], p["cost"]), 4),
                               rel_gap=data[m].get("rel_gap_tail_mean"),
                               tt_stab=data[m].get("tt_stab"),
                               tstt_sd_tail=data[m].get("tstt_sd_tail"),
                               converged=data[m].get("converged"),
                               teleports=data[m].get("teleports_max"),
                               accounting_ok=data[m].get("accounting_ok"))
    with open(os.path.join(OUT, "singleton_projects.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(single.values())).keys()))
        w.writeheader(); w.writerows(single.values())

    # ---- interaction matrix -------------------------------------------------
    I = [[0.0] * NPROJ for _ in range(NPROJ)]
    rows = []
    for i in range(NPROJ):
        for j in range(NPROJ):
            if i == j:
                I[i][j] = float("nan"); continue
            m = (1 << i) | (1 << j)
            v = ben[m] - ben[1 << i] - ben[1 << j]
            I[i][j] = v
            if i < j:
                bi, bj = ben[1 << i], ben[1 << j]
                denom = abs(bi) + abs(bj)
                rows.append(dict(i=PROJECT_IDS[i], j=PROJECT_IDS[j],
                                 benefit_i=round(bi, 1), benefit_j=round(bj, 1),
                                 benefit_ij=round(ben[m], 1),
                                 interaction_s=round(v, 1),
                                 interaction_pct_of_sum=round(100 * v / denom, 2)
                                 if denom > 0 else None,
                                 sign="complementary" if v > 0 else "substitutive"))
    rows.sort(key=lambda r: -r["interaction_s"])
    with open(os.path.join(OUT, "interaction_matrix_pairs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(OUT, "interaction_matrix.json"), "w") as f:
        json.dump(dict(project_ids=PROJECT_IDS,
                       matrix=[[None if v != v else round(v, 2) for v in r] for r in I],
                       pairs=rows), f, indent=2)

    # ---- v/c ranking and baselines -----------------------------------------
    vc, s_eff = vc_table()
    tvc = project_target_vc(vc)
    order_vc = sorted(PROJECT_IDS, key=lambda p: -tvc[p])
    order_bcr = sorted(PROJECT_IDS, key=lambda p: -single[p]["bcr"])

    # ---- per-budget results -------------------------------------------------
    results, frontier = [], []
    for B in BUDGETS:
        feas = [m for m in tstt if subset_cost(m) <= B + 1e-9]
        opt = min(feas, key=lambda m: tstt[m])
        gas = [run_ga(tstt, B, seed=1000 + s) for s in range(20)]
        ga_best = min(gas, key=lambda g: g["tstt"])
        n_hit = sum(1 for g in gas if g["mask"] == opt)
        gvc, cvc = greedy_by_rank(order_vc, B)
        gbc, cbc = greedy_by_rank(order_bcr, B)
        mvc, mbc = mask_from_subset(gvc), mask_from_subset(gbc)

        def row(label, m, extra=None):
            b = ben[m]
            d = dict(budget=B, method=label, subset="+".join(subset_from_mask(m)) or "(none)",
                     mask=m, cost=subset_cost(m), tstt_s=round(tstt[m], 1),
                     benefit_s=round(b, 1), benefit_pct=round(100 * b / T0, 3),
                     pv_benefits_mu=round(econ.pv_benefits_mu(b), 4),
                     npv_mu=round(econ.npv_mu(b, subset_cost(m)), 4),
                     bcr=round(econ.bcr(b, subset_cost(m)), 4) if subset_cost(m) > 0 else None,
                     gap_vs_opt_s=round(tstt[m] - tstt[opt], 1),
                     gap_vs_opt_pct=round(100 * (tstt[m] - tstt[opt]) / tstt[opt], 4),
                     benefit_shortfall_pct=(round(100 * (ben[opt] - b) / ben[opt], 2)
                                            if ben[opt] > 0 else None),
                     npv_gap_mu=round(econ.npv_mu(ben[opt], subset_cost(opt))
                                      - econ.npv_mu(b, subset_cost(m)), 4),
                     converged=data[m].get("converged"),
                     rel_gap=data[m].get("rel_gap_tail_mean"),
                     tstt_sd_tail=data[m].get("tstt_sd_tail"),
                     accounting_ok=data[m].get("accounting_ok"))
            if extra:
                d.update(extra)
            return d

        results.append(row("enumerated_optimum", opt,
                           dict(n_feasible=len(feas))))
        results.append(row("GA_best_of_20_seeds", ga_best["mask"],
                           dict(ga_unique_evals=ga_best["n_unique_evals"],
                                ga_seeds_hitting_optimum="%d/20" % n_hit,
                                ga_median_unique_evals=sorted(g["n_unique_evals"] for g in gas)[10])))
        results.append(row("greedy_worst_vc", mvc))
        results.append(row("greedy_isolated_bcr", mbc))
        results.append(row("do_nothing", 0))
        frontier.append(dict(budget=B, n_feasible=len(feas),
                             best_mask=opt, best_subset="+".join(subset_from_mask(opt)),
                             best_cost=subset_cost(opt),
                             best_tstt_s=round(tstt[opt], 1),
                             best_benefit_s=round(ben[opt], 1),
                             best_benefit_pct=round(100 * ben[opt] / T0, 3),
                             best_npv_mu=round(econ.npv_mu(ben[opt], subset_cost(opt)), 4)))

    with open(os.path.join(OUT, "results_table.csv"), "w", newline="") as f:
        keys = sorted({k for r in results for k in r})
        keys = ["budget", "method", "subset", "cost", "tstt_s", "benefit_s", "benefit_pct",
                "pv_benefits_mu", "npv_mu", "bcr", "gap_vs_opt_s", "gap_vs_opt_pct",
                "benefit_shortfall_pct", "npv_gap_mu", "converged", "rel_gap",
                "accounting_ok", "tstt_sd_tail", "mask", "n_feasible", "ga_unique_evals",
                "ga_median_unique_evals", "ga_seeds_hitting_optimum"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(results)

    # frontier concavity
    for k in range(1, len(frontier) - 1):
        prev, cur, nxt = frontier[k - 1], frontier[k], frontier[k + 1]
        d1 = (cur["best_benefit_s"] - prev["best_benefit_s"]) / (cur["budget"] - prev["budget"])
        d2 = (nxt["best_benefit_s"] - cur["best_benefit_s"]) / (nxt["budget"] - cur["budget"])
        cur["marginal_benefit_in"] = round(d1, 1)
        cur["marginal_benefit_out"] = round(d2, 1)
        cur["concave_here"] = bool(d2 <= d1 + 1e-9)
    with open(os.path.join(OUT, "pareto_frontier.csv"), "w", newline="") as f:
        keys = ["budget", "n_feasible", "best_subset", "best_cost", "best_tstt_s",
                "best_benefit_s", "best_benefit_pct", "best_npv_mu",
                "marginal_benefit_in", "marginal_benefit_out", "concave_here", "best_mask"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(frontier)

    with open(os.path.join(OUT, "baseline_rankings.json"), "w") as f:
        json.dump(dict(s_eff_veh_h_lane=s_eff,
                       project_target_vc={p: round(tvc[p], 4) for p in PROJECT_IDS},
                       order_worst_vc=order_vc,
                       project_isolated_bcr={p: single[p]["bcr"] for p in PROJECT_IDS},
                       order_isolated_bcr=order_bcr), f, indent=2)

    with open(os.path.join(OUT, "econ_parameter_provenance.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "value", "unit", "provenance"])
        w.writeheader(); w.writerows(econ.PARAMS)
        f.write("annuity_factor,%.6f,dimensionless,derived from DISCOUNT_RATE and HORIZON\n"
                % econ.ANNUITY)

    # ---- console summary ----------------------------------------------------
    print("\n=== singleton projects (isolated, vs do-nothing) ===")
    print("%-4s %6s %12s %9s %10s %9s %8s" %
          ("proj", "cost", "benefit_s", "ben_%", "PVben_MU", "NPV_MU", "BCR"))
    for p in PROJECT_IDS:
        s = single[p]
        print("%-4s %6.1f %12.1f %9.3f %10.3f %9.3f %8.3f" %
              (p, s["cost"], s["benefit_s"], s["benefit_pct"],
               s["pv_benefits_mu"], s["npv_mu"], s["bcr"]))
    print("\nworst-v/c order :", order_vc, {p: round(tvc[p], 3) for p in order_vc})
    print("isolated-BCR order:", order_bcr)
    print("\n=== results at each budget ===")
    for r in results:
        print("B=%5.1f %-20s %-22s cost=%5.1f TSTT=%11.1f ben=%9.1f (%.2f%%) "
              "NPV=%8.3f gap_vs_opt=%+8.1f s (%+.3f%%)" %
              (r["budget"], r["method"], r["subset"], r["cost"], r["tstt_s"],
               r["benefit_s"], r["benefit_pct"], r["npv_mu"],
               r["gap_vs_opt_s"], r["gap_vs_opt_pct"]))
    print("\n=== frontier ===")
    for fr in frontier:
        print("B=%5.1f best=%-24s cost=%5.1f benefit=%10.1f s (%.2f%%) NPV=%8.3f  "
              "dB/dB_in=%s out=%s concave=%s" %
              (fr["budget"], fr["best_subset"], fr["best_cost"], fr["best_benefit_s"],
               fr["best_benefit_pct"], fr["best_npv_mu"],
               fr.get("marginal_benefit_in"), fr.get("marginal_benefit_out"),
               fr.get("concave_here")))
    print("\n=== strongest interactions ===")
    for r in rows[:5] + rows[-5:]:
        print("%-3s+%-3s  b_i=%9.1f b_j=%9.1f b_ij=%10.1f  I=%+10.1f (%+.1f%% of |b_i|+|b_j|)  %s"
              % (r["i"], r["j"], r["benefit_i"], r["benefit_j"], r["benefit_ij"],
                 r["interaction_s"], r["interaction_pct_of_sum"] or 0, r["sign"]))
    return dict(single=single, tstt=tstt, ben=ben, T0=T0, results=results,
                frontier=frontier, pairs=rows, I=I, order_vc=order_vc,
                order_bcr=order_bcr, data=data)


if __name__ == "__main__":
    main()
