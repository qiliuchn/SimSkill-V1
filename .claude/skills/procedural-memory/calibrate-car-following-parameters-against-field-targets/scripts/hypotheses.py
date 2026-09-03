#!/usr/bin/env python3
"""STEP 5 -- hypothesis tests H2..H7, all with CRN replication over >=8 seeds,
95% CIs, and explicit teleport/collision/completion accounting.

Usage: hypotheses.py <h2|h3|h4|h5|h6|h7|fwy>
"""
import os, sys, json, math, itertools, time
import numpy as np
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_common import (OUT, RUNS, TARGETS, PARAM_SPACE, params_for, full_params,
                       objective, geh, fd_probe, TARGET_SAT_HEADWAY, NETDIR)
from evalpool import evaluate, unit_to_params, params_to_unit, _one, key_of
import facilities as F

SEEDS = [42, 43, 44, 45, 46, 47, 48, 49]          # CRN seed list (8)
SEEDS_ALT = [142, 143, 144, 145, 146, 147, 148, 149]
NPROC = int(os.environ.get("CF_NPROC", "9"))
FEATS = ["v_free_kmh", "q_max", "k_crit", "k_jam", "w_kmh"]
TB = os.path.join(OUT, "tables")


def load(model, tag="main"):
    return json.load(open(os.path.join(TB, "calib_%s_%s.json" % (model, tag))))


# ---------------------------------------------------- multi-seed evaluation --
def _ms_job(a):
    model, p, seed = a
    _, r = _one((model, p, seed, key_of(model, p, seed), TARGETS, None))
    return seed, r


def multiseed(model, p, seeds=None, nproc=None):
    seeds = seeds or SEEDS
    jobs = [(model, p, s) for s in seeds]
    with ProcessPoolExecutor(max_workers=nproc or NPROC) as ex:
        out = dict(ex.map(_ms_job, jobs))
    rows = [out[s] for s in seeds]
    ok = [r for r in rows if r["ok"]]
    agg = dict(n=len(ok), n_failed=len(rows) - len(ok), seeds=seeds)
    for key in ["obj"] + FEATS:
        v = np.array([(r["obj"] if key == "obj" else r["feat"].get(key, np.nan))
                      for r in ok], dtype=float)
        v = v[np.isfinite(v)]
        if len(v) == 0:
            agg[key] = dict(mean=float("nan"), sd=float("nan"), ci=float("nan"))
            continue
        m = float(np.mean(v)); sd = float(np.std(v, ddof=1)) if len(v) > 1 else 0.0
        from scipy import stats
        hw = float(stats.t.ppf(0.975, len(v) - 1) * sd / math.sqrt(len(v))) if len(v) > 1 else 0.0
        agg[key] = dict(mean=m, sd=sd, ci=hw, cv=sd / m if m else float("nan"),
                        vals=[float(x) for x in v])
    agg["teleports"] = float(np.sum([r["feat"].get("teleports", 0) for r in ok]))
    agg["collisions"] = float(np.sum([r["feat"].get("collisions", 0) for r in ok]))
    agg["cells_failed"] = float(np.sum([r["feat"].get("n_failed", 0) for r in ok]))
    return agg


def scorecard(agg, label):
    """Practitioner acceptance scorecard: per-feature GEH-analogue + RMSN."""
    rows, errs = [], []
    for k in FEATS:
        t = TARGETS[k]["target"]; m = agg[k]["mean"]
        e = (m - t) / t
        errs.append((TARGETS[k]["weight"], e))
        rows.append(dict(feature=k, target=t, measured=m, ci=agg[k]["ci"],
                         rel_err_pct=100 * e,
                         geh=geh(m, t) if k in ("q_max",) else None,
                         within_tol=abs(m - t) <= TARGETS[k]["tol"]))
    num = sum(w * e * e for w, e in errs); den = sum(w for w, _ in errs)
    rmsn = math.sqrt(num / den)
    return dict(label=label, rows=rows, rmsn_pct=100 * rmsn,
                n_within_tol=sum(1 for r in rows if r["within_tol"]),
                geh_qmax=geh(agg["q_max"]["mean"], TARGETS["q_max"]["target"]),
                pass_rmsn_15=(100 * rmsn < 15.0),
                pass_geh5=(geh(agg["q_max"]["mean"], TARGETS["q_max"]["target"]) < 5.0))


# ================================================================== H6 =======
def h6():
    """Objective noise floor, required replications, CRN vs independent seeds."""
    res = {}
    sets = {}
    for model in ("Krauss", "IDM"):
        c = load(model)
        sets[(model, "default")] = full_params(model)
        bk = "ga" if c["ga"]["best_obj"] <= c["nm"]["best_obj"] else "nm"
        sets[(model, "calibrated")] = full_params(model, c["%s_best_params" % bk])
    for (model, name), p in sets.items():
        a = multiseed(model, p, SEEDS)
        b = multiseed(model, p, SEEDS_ALT)
        sd = a["obj"]["sd"]; mean = a["obj"]["mean"]
        # required n for a half-width of 5% of the mean
        from scipy import stats
        n_req = None
        for n in range(2, 400):
            hw = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
            if hw <= 0.05 * mean:
                n_req = n; break
        res["%s_%s" % (model, name)] = dict(
            obj_mean=mean, obj_sd=sd, obj_cv=sd / mean, obj_ci=a["obj"]["ci"],
            n_required_for_5pct_halfwidth=n_req,
            feature_cv={k: a[k]["cv"] for k in FEATS},
            obj_mean_altseeds=b["obj"]["mean"], obj_sd_altseeds=b["obj"]["sd"],
            teleports=a["teleports"], collisions=a["collisions"])
    # --- CRN vs independent for a REAL treatment (default -> calibrated) ------
    for model in ("Krauss", "IDM"):
        c = load(model)
        bk = "ga" if c["ga"]["best_obj"] <= c["nm"]["best_obj"] else "nm"
        d = full_params(model); g = full_params(model, c["%s_best_params" % bk])
        A = multiseed(model, d, SEEDS)["obj"]["vals"]
        Bc = multiseed(model, g, SEEDS)["obj"]["vals"]          # CRN (same seeds)
        Bi = multiseed(model, g, SEEDS_ALT)["obj"]["vals"]      # independent
        A, Bc, Bi = np.array(A), np.array(Bc), np.array(Bi)
        n = min(len(A), len(Bc), len(Bi))
        dif_crn = A[:n] - Bc[:n]
        var_crn = float(np.var(dif_crn, ddof=1))
        var_ind = float(np.var(A[:n], ddof=1) + np.var(Bi[:n], ddof=1))
        rho = float(np.corrcoef(A[:n], Bc[:n])[0, 1]) if n > 2 else float("nan")
        res["crn_%s" % model] = dict(
            paired_corr=rho, var_diff_crn=var_crn, var_diff_independent=var_ind,
            variance_reduction_factor=var_ind / var_crn if var_crn > 0 else float("inf"),
            mean_effect_crn=float(np.mean(dif_crn)),
            mean_effect_independent=float(np.mean(A[:n]) - np.mean(Bi[:n])))
    json.dump(res, open(os.path.join(TB, "H6_noise.json"), "w"), indent=2, default=float)
    print(json.dumps(res, indent=2, default=float))


# ================================================================== H2 =======
def h2():
    out = {}
    for model in ("Krauss", "IDM"):
        c = load(model)
        d = full_params(model)
        best = min([("GA", c["ga_best_params"], c["ga"]["best_obj"]),
                    ("NM", c["nm_best_params"], c["nm"]["best_obj"])],
                   key=lambda x: x[2])
        g = full_params(model, best[1])
        ad = multiseed(model, d); ag = multiseed(model, g)
        sd_ = scorecard(ad, "%s default" % model)
        sg_ = scorecard(ag, "%s calibrated (%s)" % (model, best[0]))
        gap = {}
        for k in FEATS:
            t = TARGETS[k]["target"]
            e0 = abs(ad[k]["mean"] - t); e1 = abs(ag[k]["mean"] - t)
            gap[k] = dict(default_abs_err=e0, calib_abs_err=e1,
                          default_pct=100 * (ad[k]["mean"] - t) / t,
                          calib_pct=100 * (ag[k]["mean"] - t) / t,
                          gap_closed_pct=100 * (e0 - e1) / e0 if e0 > 0 else float("nan"))
        out[model] = dict(default=ad, calibrated=ag, best_optimizer=best[0],
                          calibrated_params=g, default_params=d,
                          scorecard_default=sd_, scorecard_calibrated=sg_,
                          gap_analysis=gap)
    json.dump(out, open(os.path.join(TB, "H2_default_bias.json"), "w"),
              indent=2, default=float)
    for m, o in out.items():
        print("\n=== H2 %s ===" % m)
        print("  %-12s %9s %9s %9s %9s %9s" % ("feature", "target", "default",
                                               "calib", "def_err%", "cal_err%"))
        for k in FEATS:
            g = o["gap_analysis"][k]
            print("  %-12s %9.1f %9.1f %9.1f %9.1f %9.1f  gap closed %.0f%%"
                  % (k, TARGETS[k]["target"], o["default"][k]["mean"],
                     o["calibrated"][k]["mean"], g["default_pct"], g["calib_pct"],
                     g["gap_closed_pct"]))
        print("  RMSN: default %.1f%% -> calibrated %.1f%%"
              % (o["scorecard_default"]["rmsn_pct"], o["scorecard_calibrated"]["rmsn_pct"]))


# ================================================================== H3 =======
def _micro_job(a):
    model, p, tag, seed = a
    return tag, F.micro(os.path.join(RUNS, "micro", tag), model, p, seed=seed)


def h3():
    """Equifinality: distinct parameter vectors, statistically tied on the macro
    objective, that differ measurably in microscopic behaviour."""
    out = {}
    for model in ("Krauss", "IDM"):
        c = load(model); names = c["names"]
        log = json.load(open(os.path.join(TB, "callog_%s_main.json" % model)))
        cand = [e for e in log["ga"] + log["nm"] if e["ok"]]
        cand.sort(key=lambda e: e["obj"])
        best = cand[0]["obj"]
        noise = json.load(open(os.path.join(TB, "H6_noise.json")))
        sd = noise["%s_calibrated" % model]["obj_sd"]
        band = best + 2.0 * sd          # "statistically indistinguishable" band
        tied = [e for e in cand if e["obj"] <= band]
        # greedy max-min-distance selection of DISTINCT vectors in unit space
        U = [np.array(params_to_unit(model, e["p"], names=names)) for e in tied]
        sel = [0]
        while len(sel) < 5 and len(sel) < len(U):
            d = [min(np.linalg.norm(U[i] - U[j]) for j in sel) for i in range(len(U))]
            i = int(np.argmax(d))
            if d[i] < 0.15:
                break
            sel.append(i)
        reps = [tied[i] for i in sel]
        # confirm the tie with 8-seed CRN replication
        confirmed = []
        for i, e in enumerate(reps):
            p = full_params(model, e["p"])
            a = multiseed(model, p)
            confirmed.append(dict(idx=i, params=p, obj_single=e["obj"],
                                  obj_mean=a["obj"]["mean"], obj_ci=a["obj"]["ci"],
                                  feats={k: a[k]["mean"] for k in FEATS}))
        # microscopic signature
        jobs = [(model, full_params(model, e["p"]), "%s_%d" % (model, i), 42)
                for i, e in enumerate(reps)]
        with ProcessPoolExecutor(max_workers=min(NPROC, len(jobs))) as ex:
            mics = dict(ex.map(_micro_job, jobs))
        for i, ccc in enumerate(confirmed):
            ccc["micro"] = {k: v for k, v in mics["%s_%d" % (model, i)].items()
                            if k != "headways"}
        # --- does adding a MICRO target shrink the feasible set? -------------
        # micro target: median time headway 1.60 s (+-0.10) at k=22 veh/km/ln,
        # a value an observer could plausibly measure in the field.
        MICRO_T, MICRO_TOL = 1.60, 0.10
        for ccc in confirmed:
            h = ccc["micro"].get("headway_p50", float("nan"))
            ccc["micro_rel_err"] = (h - MICRO_T) / MICRO_T if h == h else float("nan")
            ccc["passes_micro"] = abs(h - MICRO_T) <= MICRO_TOL if h == h else False
        objs = [c2["obj_mean"] for c2 in confirmed]
        cis = [c2["obj_ci"] for c2 in confirmed]
        out[model] = dict(
            best_obj=best, noise_sd=sd, band=band, n_tied_in_band=len(tied),
            n_distinct_reps=len(reps),
            macro_obj_spread=float(max(objs) - min(objs)),
            macro_indistinguishable=bool(max(objs) - min(objs) <= 2 * max(cis)),
            micro_target=dict(metric="headway_p50_s", target=MICRO_T, tol=MICRO_TOL),
            n_pass_micro=sum(1 for c2 in confirmed if c2["passes_micro"]),
            feasible_set_shrinkage_pct=100 * (1 - sum(1 for c2 in confirmed
                                                      if c2["passes_micro"]) / len(confirmed)),
            candidates=confirmed)
    json.dump(out, open(os.path.join(TB, "H3_equifinality.json"), "w"),
              indent=2, default=float)
    for m, o in out.items():
        print("\n=== H3 %s ===  best=%.4f  noise_sd=%.4f  tied-in-band=%d  distinct=%d"
              % (m, o["best_obj"], o["noise_sd"], o["n_tied_in_band"], o["n_distinct_reps"]))
        print("  %-3s %8s %8s | %8s %8s %8s %8s | %s"
              % ("#", "obj", "ci", "h_p50", "h_cv", "oscAmp", "vSD", "params"))
        for c2 in o["candidates"]:
            mi = c2["micro"]
            print("  %-3d %8.4f %8.4f | %8.3f %8.3f %8.3f %8.3f | %s"
                  % (c2["idx"], c2["obj_mean"], c2["obj_ci"],
                     mi.get("headway_p50", float('nan')), mi.get("headway_cv", float('nan')),
                     mi.get("osc_amplitude", float('nan')),
                     mi.get("veh_speed_sd_mean", float('nan')),
                     {k: round(v, 3) for k, v in c2["params"].items()}))
        print("  macro-indistinguishable: %s ; pass micro target: %d/%d (feasible set -%.0f%%)"
              % (o["macro_indistinguishable"], o["n_pass_micro"],
                 len(o["candidates"]), o["feasible_set_shrinkage_pct"]))


# ================================================================== H4 =======
def _sat_job(a):
    model, p, tag, seed = a
    return tag, F.sat_flow(os.path.join(RUNS, "sat", tag), model, p, seed=seed)


def h4():
    """(a) regime transfer: calibrate on the uncongested+capacity branch only,
       validate on the congested branch.
       (b) facility transfer: freeway-calibrated params -> held-out signalised
       approach saturation headway."""
    out = {}
    UNCONG = {k: TARGETS[k] for k in ("v_free_kmh", "q_max", "k_crit")}
    for model in ("Krauss", "IDM"):
        c = load(model); names = c["names"]
        bk = "ga" if c["ga"]["best_obj"] <= c["nm"]["best_obj"] else "nm"
        cal_full = full_params(model, c["%s_best_params" % bk])
        # (a) re-calibrate on the uncongested subset only
        import calibrate as CAL
        ga = CAL.run_ga(model, names, UNCONG, pop=20, gens=12)
        p_unc = unit_to_params(model, ga["best_u"], names=names)
        p_unc = full_params(model, p_unc)
        a_unc = multiseed(model, p_unc); a_full = multiseed(model, cal_full)
        train_err = {k: 100 * (a_unc[k]["mean"] - TARGETS[k]["target"]) / TARGETS[k]["target"]
                     for k in UNCONG}
        valid_err = {k: 100 * (a_unc[k]["mean"] - TARGETS[k]["target"]) / TARGETS[k]["target"]
                     for k in ("k_jam", "w_kmh")}
        full_valid = {k: 100 * (a_full[k]["mean"] - TARGETS[k]["target"]) / TARGETS[k]["target"]
                      for k in ("k_jam", "w_kmh")}
        # (b) facility transfer to the signalised approach
        jobs = [(model, cal_full, "%s_cal" % model, 42),
                (model, full_params(model), "%s_def" % model, 42)]
        with ProcessPoolExecutor(max_workers=2) as ex:
            sats = dict(ex.map(_sat_job, jobs))
        sc, sdf = sats["%s_cal" % model], sats["%s_def" % model]
        out[model] = dict(
            regime=dict(train_features=list(UNCONG), train_err_pct=train_err,
                        validate_features=["k_jam", "w_kmh"],
                        validate_err_pct=valid_err,
                        full_calibration_validate_err_pct=full_valid,
                        params_uncong=p_unc, params_full=cal_full,
                        obj_uncong_on_full_objective=a_unc["obj"]["mean"],
                        obj_full=a_full["obj"]["mean"]),
            facility=dict(
                target_h=TARGET_SAT_HEADWAY["target"], tol=TARGET_SAT_HEADWAY["tol"],
                default=dict(h=sdf.get("h_sat"), s=sdf.get("s_vph"), l1=sdf.get("l1"),
                             cycles=sdf.get("n_cycles"), ok=sdf.get("ok"),
                             window_spread=sdf.get("h_sat_spread")),
                calibrated=dict(h=sc.get("h_sat"), s=sc.get("s_vph"), l1=sc.get("l1"),
                                cycles=sc.get("n_cycles"), ok=sc.get("ok"),
                                window_spread=sc.get("h_sat_spread")),
                default_err_pct=100 * (sdf["h_sat"] - 1.90) / 1.90 if sdf.get("ok") else None,
                calib_err_pct=100 * (sc["h_sat"] - 1.90) / 1.90 if sc.get("ok") else None))
    json.dump(out, open(os.path.join(TB, "H4_transfer.json"), "w"), indent=2, default=float)
    for m, o in out.items():
        r = o["regime"]; f = o["facility"]
        print("\n=== H4 %s ===" % m)
        print("  regime  TRAIN (uncong+cap) err%%: %s"
              % {k: round(v, 1) for k, v in r["train_err_pct"].items()})
        print("  regime  VALID (congested) err%%: %s   [full-calibration: %s]"
              % ({k: round(v, 1) for k, v in r["validate_err_pct"].items()},
                 {k: round(v, 1) for k, v in r["full_calibration_validate_err_pct"].items()}))
        print("  facility saturation headway: target %.2f s | default %.3f s (%.1f%%) "
              "| freeway-calibrated %.3f s (%.1f%%)"
              % (f["target_h"], f["default"]["h"] or float('nan'),
                 f["default_err_pct"] or float('nan'),
                 f["calibrated"]["h"] or float('nan'),
                 f["calib_err_pct"] or float('nan')))


# ================================================================== H5 =======
def h5():
    """Acceptance criteria + the 'right answer for the wrong reason' test."""
    PLAUS = dict(tau=(0.7, 1.6), decel=(2.5, 5.0), minGap=(1.5, 4.0),
                 length=(4.0, 6.0), speedFactor=(0.85, 1.15),
                 apparentDecel=(2.5, 6.0), accel=(1.0, 3.5), delta=(2.0, 6.0))

    def implausible(p):
        bad = {}
        for k, v in p.items():
            if k in PLAUS and not (PLAUS[k][0] <= v <= PLAUS[k][1]):
                bad[k] = dict(value=v, plausible_range=PLAUS[k])
        return bad

    out = {}
    for model in ("Krauss", "IDM"):
        c = load(model)
        log = json.load(open(os.path.join(TB, "callog_%s_main.json" % model)))
        cand = sorted([e for e in log["ga"] + log["nm"] if e["ok"]], key=lambda e: e["obj"])
        rows = []
        for e in cand[:400]:
            p = full_params(model, e["p"])
            f = e["feat"]
            if not f:
                continue
            errs = [(TARGETS[k]["weight"], (f[k] - TARGETS[k]["target"]) / TARGETS[k]["target"])
                    for k in FEATS if f.get(k) == f.get(k)]
            if len(errs) < len(FEATS):
                continue
            rmsn = 100 * math.sqrt(sum(w * x * x for w, x in errs) / sum(w for w, _ in errs))
            g = geh(f["q_max"], TARGETS["q_max"]["target"])
            bad = implausible(p)
            rows.append(dict(obj=e["obj"], rmsn_pct=rmsn, geh_qmax=g,
                             passes=(rmsn < 15.0 and g < 5.0),
                             n_implausible=len(bad), implausible=bad, params=p))
        passing = [r for r in rows if r["passes"]]
        pass_imp = [r for r in passing if r["n_implausible"] > 0]
        worst = max(pass_imp, key=lambda r: r["n_implausible"]) if pass_imp else None
        best_ok = min([r for r in passing if r["n_implausible"] == 0],
                      key=lambda r: r["obj"]) if any(r["n_implausible"] == 0 for r in passing) else None
        out[model] = dict(
            n_candidates=len(rows), n_passing=len(passing),
            n_passing_but_implausible=len(pass_imp),
            pct_passing_but_implausible=100 * len(pass_imp) / len(passing) if passing else float("nan"),
            example_pass_but_implausible=worst,
            best_plausible_passing=best_ok)
    json.dump(out, open(os.path.join(TB, "H5_acceptance.json"), "w"), indent=2, default=float)
    for m, o in out.items():
        print("\n=== H5 %s ===  candidates=%d  passing(RMSN<15%% & GEH<5)=%d  "
              "of which physically implausible=%d (%.0f%%)"
              % (m, o["n_candidates"], o["n_passing"], o["n_passing_but_implausible"],
                 o["pct_passing_but_implausible"]))
        e = o["example_pass_but_implausible"]
        if e:
            print("  example 'right answer, wrong reason': RMSN=%.1f%% GEH=%.2f  violations=%s"
                  % (e["rmsn_pct"], e["geh_qmax"],
                     {k: (round(v["value"], 3), v["plausible_range"]) for k, v in e["implausible"].items()}))


# ================================================================== H7 =======
def h7():
    """Known-answer recovery against a synthetic ground-truth parameter vector."""
    import calibrate as CAL
    out = {}
    TRUTH = {
        "Krauss": dict(tau=1.25, decel=3.6, minGap=2.0, apparentDecel=3.2,
                       sigma=0.30, length=4.6, speedFactor=0.95),
        "IDM": dict(tau=1.35, minGap=2.2, decel=3.4, accel=1.6, length=4.6,
                    delta=3.0, speedFactor=0.95),
    }
    for model in ("Krauss", "IDM"):
        names = CAL.INFLUENTIAL[model]
        pt = full_params(model, TRUTH[model])
        feat, _ = fd_probe("truth_%s" % model, model, pt, seed=42)
        tgt = {k: dict(target=float(feat[k]), tol=abs(0.03 * feat[k]),
                       weight=TARGETS[k]["weight"], unit=TARGETS[k]["unit"])
               for k in FEATS}
        ga = CAL.run_ga(model, names, tgt, pop=24, gens=16)
        rec = unit_to_params(model, ga["best_u"], names=names)
        u_t = np.array(params_to_unit(model, pt, names=names))
        u_r = np.array(params_to_unit(model, full_params(model, rec), names=names))
        recov = {n: dict(true=pt[n], recovered=rec[n],
                         err_pct=100 * (rec[n] - pt[n]) / pt[n],
                         unit_err=abs(float(u_r[i] - u_t[i])))
                 for i, n in enumerate(names)}
        a_true = multiseed(model, pt)
        a_rec = multiseed(model, full_params(model, rec))
        out[model] = dict(
            truth_params=pt, truth_features=feat, recovered_params=rec,
            best_obj=ga["best_obj"], n_eval=ga["n_eval"],
            param_recovery=recov,
            mean_abs_unit_err=float(np.mean(np.abs(u_r - u_t))),
            max_abs_unit_err=float(np.max(np.abs(u_r - u_t))),
            feature_recovery={k: dict(true=feat[k], recovered=a_rec[k]["mean"],
                                      err_pct=100 * (a_rec[k]["mean"] - feat[k]) / feat[k])
                              for k in FEATS},
            objective_at_truth_multiseed=a_true["obj"]["mean"])
    json.dump(out, open(os.path.join(TB, "H7_recovery.json"), "w"), indent=2, default=float)
    for m, o in out.items():
        print("\n=== H7 %s ===  best_obj=%.5f (perfect=0)  mean|unit err|=%.3f  max=%.3f"
              % (m, o["best_obj"], o["mean_abs_unit_err"], o["max_abs_unit_err"]))
        for n, r in o["param_recovery"].items():
            print("   %-14s true=%7.3f  recovered=%7.3f  err=%7.1f%%  unit_err=%.3f"
                  % (n, r["true"], r["recovered"], r["err_pct"], r["unit_err"]))
        print("   feature recovery:",
              {k: round(v["err_pct"], 2) for k, v in o["feature_recovery"].items()})


# ============================================================== FREEWAY ======
def fwy():
    """Freeway validation sweeps: default vs calibrated vs target, both nets."""
    out = {}
    drop = os.path.join(NETDIR, "fwy_drop.net.xml")
    for model in ("Krauss", "IDM"):
        c = load(model)
        bk = "ga" if c["ga"]["best_obj"] <= c["nm"]["best_obj"] else "nm"
        for name, p in (("default", full_params(model)),
                        ("calibrated", full_params(model, c["%s_best_params" % bk]))):
            pts = F.fwy_sweep_par("%s_%s" % (model, name), model, p, nproc=NPROC)
            ft = F.fwy_features(pts)
            # congested branch from the SEVERE (lane-drop) variant
            jobs = [("%s_%s_drop" % (model, name), model, p, d, 500.0, 42, drop)
                    for d in (3000, 4200, 5000, 6000, 7000)]
            with ProcessPoolExecutor(max_workers=NPROC) as ex:
                dr = [r for _, r in ex.map(F._fwy_job, jobs)]
            out["%s_%s" % (model, name)] = dict(
                sweep=[{k: v for k, v in x.items() if k != "lanes"} for x in pts],
                lanes=[x.get("lanes") for x in pts],
                features=ft,
                drop_variant=[{k: v for k, v in x.items() if k != "lanes"} for x in dr])
            print("%-18s v_free=%.1f q_max=%.0f k_crit=%.1f  tel=%.0f col=%.0f"
                  % ("%s/%s" % (model, name), ft["v_free_kmh"], ft["q_max"],
                     ft["k_crit"], ft["teleports_total"], ft["collisions_total"]))
    json.dump(out, open(os.path.join(TB, "freeway_validation.json"), "w"),
              indent=2, default=float)


if __name__ == "__main__":
    globals()[sys.argv[1]]()
