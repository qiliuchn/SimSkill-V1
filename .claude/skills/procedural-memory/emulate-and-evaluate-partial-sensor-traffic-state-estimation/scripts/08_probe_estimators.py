#!/usr/bin/env python3
"""
08_probe_estimators.py -- ESTIMATOR C (probe / floating-car travel time) and
BIAS HYPOTHESIS 1 (presence-sampling length bias).

Method note on CRN
------------------
The penetration sweep is done by OFFLINE SUBSAMPLING of the master run's 100 % /
1 Hz FCD, not by re-running SUMO per penetration level.  Rationale: (a) it makes
the underlying traffic identical by construction across every penetration level,
(b) it permits N Monte-Carlo resamples per level, which a single SUMO run per
level cannot give and which RMSE-vs-penetration requires.  The real SUMO
`--device.fcd.probability` arms are retained and used to VALIDATE the offline
emulation (each real arm's probe-mean must land inside the offline Monte-Carlo
distribution for the same (p, T)).

GPS ping period is emulated faithfully: each probe gets a uniformly random ping
phase, and its observed corridor travel time is (last ping on corridor - first
ping on corridor).  A probe seen at fewer than two pings on the corridor is
UNOBSERVED -- which is itself a source of bias at long ping periods.
"""
import csv
import json
import math
import os
import random
import re
import gzip
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))

PENS = [0.5, 1, 2, 5, 10, 20, 50, 100]
PERIODS = [1, 10, 30, 60]
NREP = 400
SEED = 20260802
ACC_TARGET = 0.10        # +/-10 %
CONF = 0.95


def load_corridor():
    """completed EB corridor traversals: (enter, exit, tt)"""
    rows = []
    for r in csv.DictReader(open(os.path.join(RES, "gt_corridor.csv"))):
        if r["completed"] == "1" and r["corridor_tt"]:
            rows.append((float(r["enter"]), float(r["exit"]), float(r["corridor_tt"]), r["veh"]))
    rows.sort()
    return rows


def regimes(rows):
    """derive a free-flow and an oversaturated entry-time window from ground truth"""
    per = defaultdict(list)
    for (en, ex, tt, v) in rows:
        per[int(en // 300) * 300].append(tt)
    means = {b: sum(v) / len(v) for b, v in per.items() if len(v) >= 10}
    lo = min(means, key=means.get)
    hi = max(means, key=means.get)
    return dict(freeflow_bins=[b for b in sorted(means) if means[b] <= 1.15 * means[lo]],
                oversat_bins=[b for b in sorted(means) if means[b] >= 0.85 * means[hi]],
                bin_means=means, min_bin=lo, max_bin=hi)


def observed_tt(en, ex, T, phase):
    """naive ping-to-ping corridor travel time; None if < 2 pings on the corridor"""
    if T <= 1:
        return ex - en
    first = math.ceil((en - phase) / T) * T + phase
    last = math.floor((ex - 1e-9 - phase) / T) * T + phase
    if last <= first:
        return None
    return last - first


def main():
    rng = random.Random(SEED)
    rows = load_corridor()
    reg = regimes(rows)
    out = {"n_completed_corridor_traversals": len(rows),
           "regime_definition": {k: v for k, v in reg.items() if k != "bin_means"}}
    ff_bins = set(reg["freeflow_bins"]); os_bins = set(reg["oversat_bins"])
    print(f"{len(rows)} completed EB corridor traversals; "
          f"free-flow bins={sorted(ff_bins)} oversat bins={sorted(os_bins)}")

    pop = {
        "all": rows,
        "freeflow": [r for r in rows if int(r[0] // 300) * 300 in ff_bins],
        "oversat": [r for r in rows if int(r[0] // 300) * 300 in os_bins],
    }
    truth = {k: sum(r[2] for r in v) / len(v) for k, v in pop.items()}
    out["ground_truth_mean_corridor_tt_s"] = truth
    out["population_sizes"] = {k: len(v) for k, v in pop.items()}
    out["ground_truth_tt_cv"] = {}
    for k, v in pop.items():
        m = truth[k]
        sd = math.sqrt(sum((r[2] - m) ** 2 for r in v) / (len(v) - 1))
        out["ground_truth_tt_cv"][k] = dict(sd_s=sd, cv=sd / m)
    # exact length-bias identity over each whole population (weight = trip duration)
    out["H1_exact_length_bias_by_population"] = {}
    for k, v in pop.items():
        m = truth[k]
        var = sum((r[2] - m) ** 2 for r in v) / len(v)
        lb = sum(r[2] ** 2 for r in v) / sum(r[2] for r in v)
        out["H1_exact_length_bias_by_population"][k] = dict(
            n=len(v), departure_mean_s=m, length_biased_mean_s=lb,
            gap_s=lb - m, gap_pct=100 * (lb - m) / m,
            variance_over_mean_s=var / m,
            identity_holds=abs((lb - m) - var / m) < 1e-6)
    print("  ground truth mean corridor TT:",
          {k: round(v, 2) for k, v in truth.items()}, "n:", out["population_sizes"])

    # ================================================= ESTIMATOR C: penetration sweep
    sweep = []
    for regname, sub in pop.items():
        for p in PENS:
            for T in PERIODS:
                ests, nobs, nsel = [], [], []
                for _ in range(NREP):
                    tot = 0.0; cnt = 0; sel = 0
                    for (en, ex, tt, v) in sub:
                        if rng.random() * 100.0 >= p:
                            continue
                        sel += 1
                        o = observed_tt(en, ex, T, rng.random() * T)
                        if o is None:
                            continue
                        tot += o; cnt += 1
                    nsel.append(sel); nobs.append(cnt)
                    if cnt > 0:
                        ests.append(tot / cnt)
                if not ests:
                    continue
                tr = truth[regname]
                mean_e = sum(ests) / len(ests)
                bias = mean_e - tr
                rmse = math.sqrt(sum((e - tr) ** 2 for e in ests) / len(ests))
                sd = math.sqrt(sum((e - mean_e) ** 2 for e in ests) / max(1, len(ests) - 1))
                within = sum(1 for e in ests if abs(e - tr) <= ACC_TARGET * tr) / len(ests)
                sweep.append(dict(regime=regname, pen_pct=p, ping_s=T,
                                  n_reps_with_data=len(ests), n_reps=NREP,
                                  mean_selected=sum(nsel) / len(nsel),
                                  mean_observed=sum(nobs) / len(nobs),
                                  obs_loss_frac=1 - (sum(nobs) / max(1e-9, sum(nsel))),
                                  truth_s=tr, mean_est_s=mean_e, bias_s=bias,
                                  bias_pct=100 * bias / tr, sd_s=sd, rmse_s=rmse,
                                  rmse_pct=100 * rmse / tr,
                                  frac_within_10pct=within,
                                  meets_target=bool(within >= CONF)))
    with open(os.path.join(RES, "estC_penetration_sweep.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sweep[0].keys()))
        w.writeheader()
        for r in sweep:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()})
    out["C_sweep_rows"] = len(sweep)

    # minimum penetration meeting the accuracy target, per regime and ping period
    minpen = {}
    for regname in pop:
        for T in PERIODS:
            cand = [r for r in sweep if r["regime"] == regname and r["ping_s"] == T
                    and r["meets_target"]]
            minpen[f"{regname}_T{T}"] = min((r["pen_pct"] for r in cand), default=None)
    out["C_min_penetration_for_pm10pct_at_95pct"] = minpen

    # ---- ping-period BIAS FLOOR: the systematic error at 100 % penetration, which
    #      no amount of extra penetration can remove.  The naive ping-to-ping
    #      estimator loses on average ~T seconds; TT_corrected = TT_naive + T.
    floor = {}
    for regname in pop:
        for T in PERIODS:
            r = [x for x in sweep if x["regime"] == regname and x["ping_s"] == T
                 and x["pen_pct"] == 100]
            if r:
                floor[f"{regname}_T{T}"] = dict(bias_s=r[0]["bias_s"], bias_pct=r[0]["bias_pct"],
                                                exceeds_10pct_target=abs(r[0]["bias_pct"]) > 100 * ACC_TARGET)
    out["C_ping_period_bias_floor_at_100pct_penetration"] = floor

    corr = []
    for regname in pop:
        for T in PERIODS:
            ests = []
            for _ in range(NREP):
                tot = 0.0; cnt = 0
                for (en, ex, tt, v) in pop[regname]:
                    o = observed_tt(en, ex, T, rng.random() * T)
                    if o is None:
                        continue
                    tot += o + (T if T > 1 else 0); cnt += 1
                if cnt:
                    ests.append(tot / cnt)
            tr = truth[regname]
            m = sum(ests) / len(ests)
            corr.append(dict(regime=regname, ping_s=T, corrected_mean_s=m,
                             residual_bias_s=m - tr, residual_bias_pct=100 * (m - tr) / tr))
    out["C_plus_T_correction_at_100pct_penetration"] = corr

    # ---- 1/sqrt(n) decay fit (T=1, i.e. no ping-period contamination)
    def loglogfit(pts):
        xs = [math.log(a) for a, _ in pts]; ys = [math.log(b) for _, b in pts]
        n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a = my - b * mx
        ss_t = sum((y - my) ** 2 for y in ys)
        ss_r = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
        return dict(exponent=b, intercept_log=a, r2=1 - ss_r / ss_t, n_points=n)

    fits = {}
    for regname in pop:
        N = len(pop[regname])
        sigma = math.sqrt(sum((r[2] - truth[regname]) ** 2 for r in pop[regname]) / (N - 1))
        base = [(r["mean_selected"], r["sd_s"], r["pen_pct"]) for r in sweep
                if r["regime"] == regname and r["ping_s"] == 1 and r["mean_selected"] >= 2]
        allp = [(a, b) for a, b, pp in base if pp < 100]
        lowp = [(a, b) for a, b, pp in base if pp <= 10]
        # finite-population-corrected residual: sd * sqrt(n) / sqrt(1 - n/N) should be
        # a constant equal to the population sd if the 1/sqrt(n) law (with FPC) holds
        fpc = [(pp, b * math.sqrt(a) / math.sqrt(max(1e-9, 1 - a / N)))
               for a, b, pp in base if pp < 100]
        fits[regname] = dict(
            fit_all_pen_lt_100=loglogfit(allp),
            fit_pen_le_10=loglogfit(lowp),
            theoretical_exponent=-0.5,
            population_sd_s=sigma, population_N=N,
            fpc_normalised_sd_by_pen={str(pp): v for pp, v in fpc},
            fpc_normalised_mean=sum(v for _, v in fpc) / len(fpc),
            fpc_normalised_max_dev_pct=100 * max(abs(v - sigma) for _, v in fpc) / sigma)
    out["C_sqrt_n_fit"] = fits

    # ---- validate the offline emulation against the REAL SUMO probe arms
    val = []
    for p in PENS:
        for T in PERIODS:
            arm = os.path.join(RUNS, f"p{p}_T{T}", "fcd.xml.gz")
            if not os.path.exists(arm):
                continue
            seen = defaultdict(lambda: [None, None])
            RT = re.compile(r'<timestep time="([\d.]+)"')
            RV = re.compile(r'<vehicle id="([^"]+)" speed="[-\d.]+" pos="[-\d.]+" lane="([^"]+)"')
            t = None
            for line in gzip.open(arm, "rt"):
                m = RT.search(line)
                if m:
                    t = float(m.group(1)); continue
                m = RV.search(line)
                if not m:
                    continue
                vid, lane = m.group(1), m.group(2)
                if not vid.startswith("f_eb"):
                    continue
                if lane.startswith("eb_") or (lane.startswith(":J") ):
                    s = seen[vid]
                    if s[0] is None:
                        s[0] = t
                    s[1] = t
            gt = {r[3]: r[2] for r in rows}
            obs = [(v, s[1] - s[0]) for v, s in seen.items() if s[0] is not None and s[1] > s[0]
                   and v in gt]
            if not obs:
                continue
            real_mean = sum(o[1] for o in obs) / len(obs)
            mc = [r for r in sweep if r["regime"] == "all" and r["pen_pct"] == p
                  and r["ping_s"] == T]
            mc = mc[0] if mc else None
            val.append(dict(pen_pct=p, ping_s=T, n_real_probes_observed=len(obs),
                            real_arm_mean_observed_tt_s=real_mean,
                            offline_mc_mean_est_s=mc["mean_est_s"] if mc else None,
                            offline_mc_sd_s=mc["sd_s"] if mc else None,
                            abs_diff_s=(real_mean - mc["mean_est_s"]) if mc else None,
                            rel_diff_pct=(100 * (real_mean - mc["mean_est_s"]) / mc["mean_est_s"])
                                         if mc else None,
                            z_score=((real_mean - mc["mean_est_s"]) / mc["sd_s"])
                                    if mc and mc["sd_s"] > 0 else None))
    out["C_real_arm_validation"] = val
    inside = [v for v in val if v["z_score"] is not None and abs(v["z_score"]) <= 2]
    out["C_real_arm_validation_summary"] = dict(
        n=len(val), n_within_2sd=len(inside),
        frac_within_2sd=len(inside) / len(val) if val else None,
        max_abs_z=max((abs(v["z_score"]) for v in val if v["z_score"] is not None), default=None),
        max_abs_rel_diff_pct=max(abs(v["rel_diff_pct"]) for v in val),
        note=("z can be large where the Monte-Carlo sd is sub-second (high penetration). "
              "The offline emulation gives each probe an independent uniform ping phase, "
              "whereas SUMO's --device.fcd.period records on a single global grid; this is "
              "the residual model difference visible at p=100%, T=30/60."))
    with open(os.path.join(RES, "estC_real_arm_validation.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(val[0].keys())); w.writeheader()
        for r in val:
            w.writerow(r)

    # ================================== BIAS HYPOTHESIS 1: presence vs departure
    # Population: all corridor traversals overlapping the oversaturated window.
    W0, W1 = min(os_bins), max(os_bins) + 300
    # exact analytic test on trips FULLY CONTAINED in the window, where the presence
    # weight is exactly the trip's own travel time, so the length-biased mean is
    # exactly E[T^2]/E[T] = mean + Var/mean
    inside = [r for r in rows if r[0] >= W0 and r[1] <= W1]
    m_in = sum(r[2] for r in inside) / len(inside)
    var_in = sum((r[2] - m_in) ** 2 for r in inside) / len(inside)
    lb_in = sum(r[2] ** 2 for r in inside) / sum(r[2] for r in inside)
    out["H1_exact_length_bias_fully_contained_trips"] = dict(
        n=len(inside), departure_mean_s=m_in, length_biased_mean_s=lb_in,
        gap_s=lb_in - m_in, gap_pct=100 * (lb_in - m_in) / m_in,
        variance_over_mean_s=var_in / m_in,
        prediction_matches=abs((lb_in - m_in) - var_in / m_in) < 1e-6)

    veh = [(en, ex, tt, v) for (en, ex, tt, v) in rows if ex > W0 and en < W1]
    dep_mean = sum(r[2] for r in veh) / len(veh)
    # exact length-biased (presence-weighted) mean: weight_i = time present in window
    wts = [min(ex, W1) - max(en, W0) for (en, ex, tt, v) in veh]
    pres_mean_exact = sum(w * r[2] for w, r in zip(wts, veh)) / sum(wts)
    # Horvitz-Thompson correction: weight each presence-sampled obs by 1/presence
    ht_mean = sum((w * r[2]) / w for w, r in zip(wts, veh) if w > 0) / \
              sum(1 for w in wts if w > 0)

    # empirical snapshot sampling at several probe penetrations
    hyp1 = []
    for p in [1, 5, 20, 100]:
        d_est, pr_est, ht_est = [], [], []
        for _ in range(NREP):
            probes = [(i, r) for i, r in enumerate(veh) if rng.random() * 100.0 < p]
            if len(probes) < 3:
                continue
            d_est.append(sum(r[2] for _, r in probes) / len(probes))
            # snapshot sampling: draw 200 snapshot times, pick a random present probe
            picks = []
            for _ in range(200):
                ts = rng.uniform(W0, W1)
                present = [(i, r) for i, r in probes if r[0] <= ts < r[1]]
                if present:
                    picks.append(rng.choice(present))
            if len(picks) < 5:
                continue
            pr_est.append(sum(r[2] for _, r in picks) / len(picks))
            # HT / inverse-presence-weighted correction on the SAME picks
            ws = [1.0 / max(1e-6, min(r[1], W1) - max(r[0], W0)) for _, r in picks]
            ht_est.append(sum(w * r[2] for w, (_, r) in zip(ws, picks)) / sum(ws))
        if not pr_est:
            continue
        hyp1.append(dict(pen_pct=p,
                         departure_sampled_mean_s=sum(d_est) / len(d_est),
                         presence_sampled_mean_s=sum(pr_est) / len(pr_est),
                         presence_minus_departure_s=sum(pr_est) / len(pr_est) - sum(d_est) / len(d_est),
                         presence_minus_departure_pct=100 * (sum(pr_est) / len(pr_est) -
                                                             sum(d_est) / len(d_est)) /
                                                       (sum(d_est) / len(d_est)),
                         ht_corrected_mean_s=sum(ht_est) / len(ht_est),
                         ht_residual_bias_s=sum(ht_est) / len(ht_est) - dep_mean,
                         n_reps=len(pr_est)))
    cv = math.sqrt(sum((r[2] - dep_mean) ** 2 for r in veh) / (len(veh) - 1)) / dep_mean
    out["H1_presence_vs_departure"] = dict(
        window=[W0, W1], n_vehicles=len(veh),
        departure_mean_exact_s=dep_mean,
        presence_weighted_mean_exact_s=pres_mean_exact,
        exact_gap_s=pres_mean_exact - dep_mean,
        exact_gap_pct=100 * (pres_mean_exact - dep_mean) / dep_mean,
        predicted_gap_from_variance_s=(cv ** 2) * dep_mean,   # E[T^2]/E[T] - E[T] = Var/E[T]
        travel_time_cv=cv,
        empirical=hyp1)

    # ---- ping-period-induced length bias (short trips lose all their pings)
    #      Corridor trips (200-350 s) always survive a 60 s ping period, so the test
    #      is run at LINK level, where free-flow traversal (~30 s) is comparable to
    #      the ping period and short (fast) traversals lose all their pings.
    links = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(RES, "gt_links.csv"))):
        links[int(r["link"])].append((float(r["enter"]), float(r["tt"])))
    hyp1b = []
    for T in PERIODS:
        for lk in sorted(links):
            kept, lost = [], []
            for (en, tt) in links[lk]:
                o = observed_tt(en, en + tt, T, rng.random() * T)
                (kept if o is not None else lost).append(tt)
            allm = sum(t for _, t in links[lk]) / len(links[lk])
            hyp1b.append(dict(ping_s=T, link=lk, n=len(links[lk]),
                              lost_frac=len(lost) / len(links[lk]),
                              true_mean_all_s=allm,
                              true_mean_observable_s=(sum(kept) / len(kept)) if kept else None,
                              true_mean_lost_s=(sum(lost) / len(lost)) if lost else None,
                              selection_bias_s=(sum(kept) / len(kept) - allm) if kept else None,
                              selection_bias_pct=(100 * (sum(kept) / len(kept) - allm) / allm)
                                                 if kept else None))
    out["H1b_ping_period_selection_bias_link_level"] = hyp1b
    with open(os.path.join(RES, "H1b_ping_selection_bias.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(hyp1b[0].keys())); w.writeheader()
        for r in hyp1b:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})

    json.dump(out, open(os.path.join(RES, "probe_estimators.json"), "w"), indent=1)
    print("  min penetration for +/-10% @95%:", minpen)
    print("  sqrt-n fit exponent (all pen<100):",
          {k: round(v["fit_all_pen_lt_100"]["exponent"], 3) for k, v in fits.items()})
    print("  sqrt-n fit exponent (pen<=10):",
          {k: round(v["fit_pen_le_10"]["exponent"], 3) for k, v in fits.items()})
    print("  FPC-normalised sd vs population sd (max dev %):",
          {k: round(v["fpc_normalised_max_dev_pct"], 1) for k, v in fits.items()})
    print("  H1 exact presence-vs-departure gap: %.2f s (%.1f%%), variance prediction %.2f s"
          % (out["H1_presence_vs_departure"]["exact_gap_s"],
             out["H1_presence_vs_departure"]["exact_gap_pct"],
             out["H1_presence_vs_departure"]["predicted_gap_from_variance_s"]))
    for T in PERIODS:
        g = [h for h in hyp1b if h["ping_s"] == T]
        lf = sum(h["lost_frac"] for h in g) / len(g)
        sb = [h["selection_bias_pct"] for h in g if h["selection_bias_pct"] is not None]
        print(f"  ping {T:3d}s (link level): {100*lf:5.1f}% of link traversals unobservable, "
              f"mean selection bias {sum(sb)/len(sb):+.1f}%")
    print("  H1 exact (fully-contained trips):", out["H1_exact_length_bias_fully_contained_trips"])
    print("  ping bias floor @100%%:", {k: round(v["bias_pct"], 2)
                                        for k, v in out["C_ping_period_bias_floor_at_100pct_penetration"].items()})
    print("  real-arm validation:", out["C_real_arm_validation_summary"])
    print("wrote", os.path.join(RES, "probe_estimators.json"))


if __name__ == "__main__":
    main()
