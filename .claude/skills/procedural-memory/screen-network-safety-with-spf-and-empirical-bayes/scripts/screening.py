"""
SPF + Empirical Bayes + simulated-conflict network screening, scored against a
KNOWN synthetic ground truth, with a Monte-Carlo loop over crash histories so
every score carries a confidence interval.

TWO SCREENING PROBLEMS ARE RUN, because they have very different answers.

Problem A -- TOTAL crashes
    truth_A(i) = C * SPF_base(control_i, AADTmaj_i, AADTmin_i) * CMF_total(phasing_i)
    The screening SPF `spf` uses the SAME formula, so it is a perfectly
    specified ORACLE and necessarily scores Spearman rho = 1.000.  THIS IS A
    TAUTOLOGY, NOT A RESULT -- it is reported only as the ceiling against which
    the crash-data and simulation methods are measured.  `spf_nocmf` (SPF base
    with no phasing CMF) is the realistic phasing-blind variant.

Problem B -- ANGLE (left-turn-type) crashes
    truth_B(i) = C * SPF_base(i) * p_angle(control_i) * CMF_angle(phasing_i)
    Here the phasing CMF is large (1.000 / 0.862 / 0.300), so an agency SPF that
    lacks a left-turn-phasing inventory (`spf_angle_blind`) is GENUINELY
    MIS-SPECIFIED.  This is the non-tautological test of the task's central
    question: can a simulated crossing-conflict rate supply the operational
    information the SPF is missing?

Observed crash history: Y independent annual counts per site, drawn
NB(mean=truth, overdispersion=k(control)) via the Poisson-Gamma mixture
    lambda ~ Gamma(shape=1/k, scale=k*truth);   count ~ Poisson(lambda)
so Var = truth + k*truth^2, the HSM negative-binomial variance form.

--phi > 0 makes a fraction of the overdispersion a PERSISTENT unmeasured site
effect rather than year-to-year noise.  With phi = 0 (the main design, as
specified by the task) all excess variance is transient, which makes shrinkage
toward the SPF the exactly-correct Bayes operation and therefore maximally
favours EB.  The phi sensitivity quantifies how much of EB's advantage is an
artefact of that assumption.

Conflict methods are computed two ways:
    *_mean   -- averaged over the site's full seed replication family (what a
                properly replicated study would report); deterministic across
                MC reps, hence zero-width CIs on its rho.
    *_1seed  -- a single randomly chosen replication per MC rep, i.e. what an
                unreplicated simulation screening would have produced.
"""
import argparse
import csv
import json
import os
import statistics as st
import sys

import numpy as np
from scipy.stats import rankdata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hsm
from inventory import SITES

DAYS_PER_YEAR = 365.0


def spearman(a, b):
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean(); rb = rb - rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else float("nan")


SIM_COLS = ("conflicts", "conf_crossing", "conf_rear_end", "conf_merge", "severe_ttc",
            "severe_pet", "severe_drac", "severe_ttc_crossing", "entering",
            "conf_rate_mev", "crossing_rate_mev", "rear_end_rate_mev",
            "severe_ttc_rate_mev", "severe_crossing_rate_mev", "mean_timeloss",
            "mean_waiting", "teleports", "inserted", "loaded", "conflicts_raw")


def load_sim(metrics_csv):
    rows = list(csv.DictReader(open(metrics_csv)))
    by = {}
    for r in rows:
        by.setdefault(r["site"], []).append(r)
    mean_rec, per_seed = {}, {}
    for s, rs in by.items():
        rec = dict(n_seeds=len(rs))
        ps = {}
        for k in SIM_COLS:
            vals = [float(r[k]) for r in rs if r.get(k) not in (None, "", "None")]
            if vals:
                rec[k] = st.mean(vals)
                rec[k + "_sd"] = st.stdev(vals) if len(vals) > 1 else 0.0
                ps[k] = np.array(vals)
        mean_rec[s], per_seed[s] = rec, ps
    return mean_rec, per_seed


def build_site_table(sim):
    tbl = []
    for s in SITES:
        c = s["control"]
        base = hsm.spf_base(c, s["aadt_major"], s["aadt_minor"])
        rec = dict(s)
        rec.update(
            spf_base=base,
            n_spf=hsm.n_predicted(c, s["aadt_major"], s["aadt_minor"], s["phasing"]),
            n_true=hsm.n_predicted(c, s["aadt_major"], s["aadt_minor"], s["phasing"]),
            n_spf_angle_blind=base * hsm.COLLISION_TYPE_SHARE[c]["angle"],
            n_true_angle=hsm.n_predicted_angle(c, s["aadt_major"], s["aadt_minor"], s["phasing"]),
            k=hsm.overdispersion(c),
            mev_per_year=(s["aadt_major"] + s["aadt_minor"]) * DAYS_PER_YEAR / 1e6,
            in_spf_range=hsm.in_range(c, s["aadt_major"], s["aadt_minor"]),
            spf_eq=hsm.SPF[c]["eq"], p_angle=hsm.COLLISION_TYPE_SHARE[c]["angle"],
            cmf_total=hsm.CMF_TOTAL[s["phasing"]], cmf_angle=hsm.CMF_ANGLE[s["phasing"]])
        rec.update({("sim_" + k): v for k, v in sim[s["site"]].items()})
        tbl.append(rec)
    return tbl


def draw_history(rng, truth, k, years, phi=0.0):
    n = len(truth)
    if phi <= 0:
        lam = rng.gamma(shape=1.0 / k[:, None], scale=(k * truth)[:, None], size=(n, years))
        return rng.poisson(lam), truth.copy()
    kp, kt = phi * k, (1.0 - phi) * k
    u = rng.gamma(shape=1.0 / kp, scale=kp)
    mu = truth * u
    if np.all(kt <= 0):
        lam = np.repeat(mu[:, None], years, axis=1)
    else:
        lam = rng.gamma(shape=1.0 / kt[:, None], scale=(kt * mu)[:, None], size=(n, years))
    return rng.poisson(lam), mu


def topn_set(vals, n, ids):
    order = sorted(range(len(vals)), key=lambda i: (-vals[i], ids[i]))
    return set(order[:n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--mc", type=int, default=2000)
    ap.add_argument("--phi", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--year-sweep", default="1,3,5,10")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    sim_mean, per_seed = load_sim(a.metrics_csv)
    tbl = build_site_table(sim_mean)
    ids = [r["site"] for r in tbl]
    S = len(tbl)
    k = np.array([r["k"] for r in tbl])
    mev = np.array([r["mev_per_year"] for r in tbl])
    truth_A = np.array([r["n_true"] for r in tbl])
    truth_B = np.array([r["n_true_angle"] for r in tbl])
    spf_A = np.array([r["n_spf"] for r in tbl])
    spf_A_nocmf = np.array([r["spf_base"] for r in tbl])
    spf_B_blind = np.array([r["n_spf_angle_blind"] for r in tbl])
    spf_B_oracle = truth_B.copy()

    # ---------- site inventory table ----------
    cols = ["site", "control", "aadt_major", "aadt_minor", "lanes_major", "lanes_minor",
            "phasing", "speed_mph", "cycle_mode", "spf_eq", "in_spf_range", "spf_base",
            "cmf_total", "cmf_angle", "p_angle", "n_spf", "n_true",
            "n_spf_angle_blind", "n_true_angle", "k", "mev_per_year",
            "sim_n_seeds", "sim_entering", "sim_conflicts", "sim_conflicts_sd",
            "sim_conf_crossing", "sim_conf_rear_end", "sim_severe_ttc",
            "sim_severe_ttc_crossing", "sim_conf_rate_mev", "sim_crossing_rate_mev",
            "sim_severe_ttc_rate_mev", "sim_mean_timeloss", "sim_teleports",
            "sim_inserted", "sim_loaded"]
    with open(os.path.join(a.out_dir, "site_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in tbl:
            w.writerow({c: (round(r[c], 6) if isinstance(r.get(c), float) else r.get(c))
                        for c in cols})

    def sim_vec(col):
        return np.array([r["sim_" + col] for r in tbl])

    def sim_1seed(rng, col):
        return np.array([float(rng.choice(per_seed[s][col])) for s in ids])

    PROBLEMS = {
        "A_total": dict(
            truth=truth_A,
            spf=spf_A,
            spf_label="spf (ORACLE - correctly specified by construction)",
            extra_spf={"spf_nocmf": spf_A_nocmf},
            conflict_mean={"conf_rate": "conf_rate_mev", "conf_freq": "conflicts",
                           "severe_rate": "severe_ttc_rate_mev",
                           "crossing_rate": "crossing_rate_mev"},
            conflict_1seed={"conf_rate_1seed": "conf_rate_mev"}),
        "B_angle": dict(
            truth=truth_B,
            spf=spf_B_blind,
            spf_label="spf_angle_blind (MIS-SPECIFIED - no left-turn phasing inventory)",
            extra_spf={"spf_angle_oracle": spf_B_oracle},
            conflict_mean={"crossing_rate": "crossing_rate_mev",
                           "crossing_freq": "conf_crossing",
                           "severe_crossing_rate": "severe_crossing_rate_mev",
                           "conf_rate": "conf_rate_mev"},
            conflict_1seed={"crossing_rate_1seed": "crossing_rate_mev"}),
    }

    year_list = [int(x) for x in a.year_sweep.split(",")]
    rng = np.random.default_rng(a.seed)
    screening_rows, rtm_rows, weight_rows = [], [], []

    for prob, cfg in PROBLEMS.items():
        truth0 = cfg["truth"]
        methods = (["obs_freq", "obs_rate_mev", "spf"] + list(cfg["extra_spf"])
                   + ["eb", "eb_excess"] + list(cfg["conflict_mean"])
                   + list(cfg["conflict_1seed"]))
        for Y in year_list:
            acc = {m: dict(rho=[], hit3=[], hit5=[], fp3=[], fp5=[]) for m in methods}
            rtm = dict(naive_fp3=[], eb_fp3=[], naive_fp5=[], eb_fp5=[], rescued3=[],
                       naive_p1=[], naive_p2=[], eb_p1=[], eb_p2=[], shrink=[],
                       true_top3_mean=[])
            w_by_ctrl = {}
            for _ in range(a.mc):
                counts, mu_site = draw_history(rng, truth0, k, Y, a.phi)
                truth = mu_site if a.phi > 0 else truth0
                obs = counts.sum(axis=1) / Y
                spf = cfg["spf"]
                w = 1.0 / (1.0 + k * spf * Y)
                eb = w * spf + (1.0 - w) * obs

                sc = {"obs_freq": obs, "obs_rate_mev": obs / mev, "spf": spf,
                      "eb": eb, "eb_excess": eb - spf}
                sc.update(cfg["extra_spf"])
                for m, col in cfg["conflict_mean"].items():
                    sc[m] = sim_vec(col)
                for m, col in cfg["conflict_1seed"].items():
                    sc[m] = sim_1seed(rng, col)

                t3, t5 = topn_set(truth, 3, ids), topn_set(truth, 5, ids)
                for m in methods:
                    v = sc[m]
                    acc[m]["rho"].append(spearman(v, truth))
                    for N, kh, kf, ts in ((3, "hit3", "fp3", t3), (5, "hit5", "fp5", t5)):
                        hits = len(topn_set(v, N, ids) & ts)
                        acc[m][kh].append(hits / N)
                        acc[m][kf].append((N - hits) / (S - N))

                # ---- regression to the mean (independent second period) ----
                kt = k if a.phi <= 0 else (1.0 - a.phi) * k
                base_mu = truth0 if a.phi <= 0 else mu_site
                lam2 = rng.gamma(shape=1.0 / kt[:, None], scale=(kt * base_mu)[:, None],
                                 size=(S, Y))
                obs2 = rng.poisson(lam2).sum(axis=1) / Y

                n3, e3 = topn_set(obs, 3, ids), topn_set(eb, 3, ids)
                n5, e5 = topn_set(obs, 5, ids), topn_set(eb, 5, ids)
                rtm["naive_fp3"].append(len(n3 - t3)); rtm["eb_fp3"].append(len(e3 - t3))
                rtm["naive_fp5"].append(len(n5 - t5)); rtm["eb_fp5"].append(len(e5 - t5))
                rtm["rescued3"].append(len(n3 - t3) - len(e3 - t3))
                rtm["naive_p1"].append(float(obs[sorted(n3)].mean()))
                rtm["naive_p2"].append(float(obs2[sorted(n3)].mean()))
                rtm["eb_p1"].append(float(obs[sorted(e3)].mean()))
                rtm["eb_p2"].append(float(obs2[sorted(e3)].mean()))
                rtm["true_top3_mean"].append(float(truth[sorted(t3)].mean()))
                with np.errstate(divide="ignore", invalid="ignore"):
                    rtm["shrink"].append(float(np.nanmean(
                        np.where(obs > 0, np.abs(obs - eb) / obs, np.nan))))
                for r, wi in zip(tbl, w):
                    w_by_ctrl.setdefault(r["control"], []).append(wi)

            def ci(v):
                v = np.asarray(v, float)
                return (float(np.nanmean(v)), float(np.nanpercentile(v, 2.5)),
                        float(np.nanpercentile(v, 97.5)))

            for m in methods:
                row = dict(problem=prob, years=Y, phi=a.phi, mc=a.mc, method=m,
                           note=(cfg["spf_label"] if m == "spf" else ""))
                for key, lab in (("rho", "spearman"), ("hit3", "hit_rate_top3"),
                                 ("hit5", "hit_rate_top5"),
                                 ("fp3", "false_pos_rate_top3"),
                                 ("fp5", "false_pos_rate_top5")):
                    mu, lo, hi = ci(acc[m][key])
                    row[lab] = round(mu, 4); row[lab + "_lo95"] = round(lo, 4)
                    row[lab + "_hi95"] = round(hi, 4)
                screening_rows.append(row)

            rr = dict(problem=prob, years=Y, phi=a.phi, mc=a.mc)
            for key in rtm:
                mu, lo, hi = ci(rtm[key])
                rr[key] = round(mu, 4); rr[key + "_lo95"] = round(lo, 4)
                rr[key + "_hi95"] = round(hi, 4)
            rr["rtm_drop_naive_pct"] = round(100 * (rr["naive_p1"] - rr["naive_p2"]) / rr["naive_p1"], 3)
            rr["rtm_drop_eb_pct"] = round(100 * (rr["eb_p1"] - rr["eb_p2"]) / rr["eb_p1"], 3)
            rtm_rows.append(rr)

            if prob == "A_total":
                for ctrl, ws in sorted(w_by_ctrl.items()):
                    weight_rows.append(dict(years=Y, phi=a.phi, control=ctrl,
                                            k=hsm.overdispersion(ctrl),
                                            mean_eb_weight_w=round(float(np.mean(ws)), 4),
                                            min_w=round(float(np.min(ws)), 4),
                                            max_w=round(float(np.max(ws)), 4)))

    def dump(path, rows):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print("wrote", path)

    sfx = "" if a.phi == 0 else "_phi%g" % a.phi
    dump(os.path.join(a.out_dir, "screening_comparison%s.csv" % sfx), screening_rows)
    dump(os.path.join(a.out_dir, "rtm_years_sweep%s.csv" % sfx), rtm_rows)
    dump(os.path.join(a.out_dir, "eb_weights%s.csv" % sfx), weight_rows)

    det = []
    for r in tbl:
        for Y in year_list:
            det.append(dict(site=r["site"], control=r["control"], k=r["k"],
                            n_spf=round(r["n_spf"], 4), years=Y,
                            eb_weight_w=round(1.0 / (1.0 + r["k"] * r["n_spf"] * Y), 4)))
    dump(os.path.join(a.out_dir, "eb_weight_by_site%s.csv" % sfx), det)

    for prob in PROBLEMS:
        print("\n=== %s  (Y=%d, phi=%g, MC=%d) ===" % (prob, a.years, a.phi, a.mc))
        print("%-22s %26s %8s %8s %9s" % ("method", "spearman [95% CI]", "hit@3", "hit@5", "FPR@5"))
        for row in screening_rows:
            if row["problem"] != prob or row["years"] != a.years:
                continue
            print("%-22s %8.3f [%6.3f,%6.3f] %8.3f %8.3f %9.4f" %
                  (row["method"], row["spearman"], row["spearman_lo95"],
                   row["spearman_hi95"], row["hit_rate_top3"], row["hit_rate_top5"],
                   row["false_pos_rate_top5"]))


if __name__ == "__main__":
    main()
