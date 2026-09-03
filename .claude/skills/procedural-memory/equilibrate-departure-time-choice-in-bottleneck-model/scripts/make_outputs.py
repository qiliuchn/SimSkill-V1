"""Produce every reported deliverable into episodic-memory/<ts>/outputs/."""
import os, sys, json, csv, shutil
import numpy as np
from scipy import stats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
from evaluate import queue_curves, EVAL_SEEDS
import analyze as AZ
from analyze import OUT, load, write_csv

CONDS_MAIN = ["no_toll", "flat_toll", "tv_toll"]
CONDS_ALL = ["no_toll", "tv_toll", "tv_toll2", "flat_toll", "zero_toll", "gamma4", "no_toll_alt"]


def ci(x, conf=0.95):
    x = np.asarray(x, float)
    m = x.mean()
    if len(x) < 2:
        return m, 0.0
    h = stats.t.ppf(0.5 + conf / 2, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))
    return m, h


def fmt(m, h, d=1):
    return "%.*f +/- %.*f" % (d, m, d, h)


def main():
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf = cap["free_flow"]["tf_mean"]
    s_vph = cap["capacity_vph"]
    s = cap["capacity_vps"]
    ev = json.load(open(os.path.join(WORK, "eval_per_seed.json")))
    an = vickrey_analytic(N_COMMUTERS, s, tf)
    present = [c for c in CONDS_ALL if os.path.exists(os.path.join(WORK, "eq_" + c, "result.json"))]

    # ---------------- capacity table
    rows = [dict(instrument="induction loop E2_0 (saturated intervals)",
                 mean_vph="%.1f" % cap["capacity_loop_vph"],
                 ci95_lo="%.1f" % cap["capacity_loop_ci"][0], ci95_hi="%.1f" % cap["capacity_loop_ci"][1],
                 n_seeds=len(cap["seeds"])),
            dict(instrument="edgeData 'left' on E2 (saturated intervals)",
                 mean_vph="%.1f" % cap["capacity_edge_vph"],
                 ci95_lo="%.1f" % cap["capacity_edge_ci"][0], ci95_hi="%.1f" % cap["capacity_edge_ci"][1],
                 n_seeds=len(cap["seeds"]))]
    for p in cap["per_seed"]:
        rows.append(dict(instrument="  seed %s (loop / edgeData)" % p["seed"],
                         mean_vph="%.1f / %.1f" % (p["cap_loop"], p["cap_edge"]),
                         ci95_lo="", ci95_hi="", n_seeds=p["n_sat_intervals"]))
    rows.append(dict(instrument="free-flow travel time Tf (20 isolated vehicles)",
                     mean_vph="%.2f s (min %.2f, max %.2f, sd %.3f)"
                     % (tf, cap["free_flow"]["tf_min"], cap["free_flow"]["tf_max"],
                        cap["free_flow"]["tf_sd"]),
                     ci95_lo="", ci95_hi="", n_seeds=20))
    write_csv(os.path.join(OUT, "capacity_measurement.csv"), rows)

    # ---------------- convergence traces
    for nm in present:
        r = load(nm)
        write_csv(os.path.join(OUT, "convergence_trace_%s.csv" % nm), r["trace"])

    # ---------------- per-seed metrics table (copy from work)
    shutil.copy(os.path.join(WORK, "metrics_by_seed.csv"),
                os.path.join(OUT, "metrics_by_seed.csv"))

    # ---------------- cost decomposition
    dec = []
    for nm in present:
        ps = ev[nm]["per_seed"]
        row = dict(condition=nm, n_seeds=len(ps))
        for key, lab in [("c_freeflow", "cost_freeflow_tt"), ("c_queue", "cost_queueing"),
                         ("c_early", "cost_schedule_early"), ("c_late", "cost_schedule_late"),
                         ("c_toll", "cost_toll"), ("mean_cost", "cost_TOTAL"),
                         ("mean_excess_cost", "cost_TOTAL_excl_freeflow")]:
            m, h = ci([p[key] for p in ps])
            row[lab] = "%.2f" % m
            row[lab + "_ci95"] = "%.2f" % h
        m, h = ci([p["mean_cost"] - p["c_toll"] for p in ps])
        row["cost_TOTAL_excl_toll"] = "%.2f" % m
        row["cost_TOTAL_excl_toll_ci95"] = "%.2f" % h
        for key, lab in [("mean_queue_delay", "mean_queue_delay_s"),
                         ("max_queue_delay", "max_queue_delay_s"),
                         ("total_queue_delay", "total_queue_delay_vehs"),
                         ("mean_depart_delay", "mean_origin_insertion_delay_s"),
                         ("discharge_saturated_vph", "bottleneck_discharge_vph"),
                         ("peak_len", "departure_window_s"),
                         ("total_toll_revenue", "total_toll_revenue")]:
            v = [p[key] for p in ps]
            m, h = ci(v)
            row[lab] = "%.2f" % m
            row[lab + "_ci95"] = "%.2f" % h
        dec.append(row)
    write_csv(os.path.join(OUT, "cost_decomposition.csv"), dec)

    # ---------------- equilibrium test (converged run) + probe results
    probe = json.load(open(os.path.join(WORK, "probe_results.json")))
    eqt = []
    for nm in present:
        r = load(nm)
        cnt = np.array(r["slot_cnt"]); mc = np.array(r["slot_mean_cost"])
        for lab, thr in [("used>=3veh", 3), ("core>=1%N", 0.01 * N_COMMUTERS)]:
            u = np.where(cnt >= thr)[0]
            if not len(u):
                continue
            w = np.average(mc[u], weights=cnt[u])
            eqt.append(dict(condition=nm, slot_set=lab, n_slots=len(u),
                            share_of_demand="%.3f" % (cnt[u].sum() / N_COMMUTERS),
                            mean_cost="%.2f" % w, min_cost="%.2f" % mc[u].min(),
                            max_cost="%.2f" % mc[u].max(),
                            rel_gap="%.4f" % ((mc[u].max() - mc[u].min()) / w),
                            rel_sd="%.4f" % (np.sqrt(np.average((mc[u] - w) ** 2,
                                                                weights=cnt[u])) / w)))
        if nm in probe and probe[nm]:
            pc = np.array([p["probe_cost"] for p in probe[nm]])
            u = np.where(cnt >= 3)[0]
            w = np.average(mc[u], weights=cnt[u])
            eqt.append(dict(condition=nm, slot_set="UNUSED slots (SUMO probe vehicles)",
                            n_slots=len(pc), share_of_demand="0",
                            mean_cost="%.2f" % pc.mean(), min_cost="%.2f" % pc.min(),
                            max_cost="%.2f" % pc.max(),
                            rel_gap="cheapest unused is %+.2f%% vs used mean"
                                    % (100 * (pc.min() - w) / w),
                            rel_sd="n_cheaper_than_used_mean=%d" % int((pc < w).sum())))
    write_csv(os.path.join(OUT, "equilibrium_test.csv"), eqt)

    prow = []
    for nm, ps in probe.items():
        r = load(nm)
        cnt = np.array(r["slot_cnt"]); mc = np.array(r["slot_mean_cost"])
        u = np.where(cnt >= 3)[0]
        w = np.average(mc[u], weights=cnt[u])
        for p in ps:
            prow.append(dict(condition=nm, slot_time_s="%.0f" % p["t"],
                             probe_cost="%.2f" % p["probe_cost"],
                             probe_queue_delay="%.2f" % p["probe_queue"],
                             probe_toll="%.2f" % p["probe_toll"],
                             used_slot_mean_cost="%.2f" % w,
                             diff_vs_used="%+.2f" % (p["probe_cost"] - w),
                             cheaper_than_used="YES" if p["probe_cost"] < w else "no"))
    write_csv(os.path.join(OUT, "probe_test.csv"), prow)

    # ---------------- toll effect / statistical test (CRN paired)
    tt = []
    base = np.array([p["mean_cost"] for p in ev["no_toll"]["per_seed"]])
    for nm in [c for c in ["tv_toll", "tv_toll2", "flat_toll", "zero_toll"] if c in ev]:
        x = np.array([p["mean_cost"] for p in ev[nm]["per_seed"]])
        d = x - base
        m, h = ci(d)
        t, pv = stats.ttest_rel(x, base)
        mb, hb = ci(base); mx, hx = ci(x)
        # cost NET of the toll transfer (what the traveller spends in time only)
        xt = np.array([p["mean_cost"] - p["c_toll"] for p in ev[nm]["per_seed"]])
        dt_, ht = ci(xt - base)
        tq, pq = stats.ttest_rel(np.array([p["mean_queue_delay"] for p in ev[nm]["per_seed"]]),
                                 np.array([p["mean_queue_delay"] for p in ev["no_toll"]["per_seed"]]))
        tt.append(dict(condition=nm,
                       mean_cost_no_toll=fmt(mb, hb, 2), mean_cost_this=fmt(mx, hx, 2),
                       paired_diff=fmt(m, h, 2),
                       paired_diff_pct="%+.2f%%" % (100 * m / mb),
                       paired_t="%.3f" % t, p_value="%.4f" % pv,
                       significant_at_5pct="YES" if pv < 0.05 else "no",
                       cost_excl_toll_diff=fmt(dt_, ht, 2),
                       queue_delay_no_toll="%.1f" % np.mean([p["mean_queue_delay"]
                                                             for p in ev["no_toll"]["per_seed"]]),
                       queue_delay_this="%.1f" % np.mean([p["mean_queue_delay"]
                                                          for p in ev[nm]["per_seed"]]),
                       queue_p_value="%.2e" % pq))
    write_csv(os.path.join(OUT, "toll_effect_tests.csv"), tt)

    # ---------------- analytic comparison
    nt = ev["no_toll"]["per_seed"]
    r_nt = load("no_toll")
    cnt = np.array(r_nt["counts"], float)
    st = slot_starts()
    used = np.where(cnt > 0)[0]
    obs_first, obs_last = st[used[0]], st[used[-1]] + SLOT
    def cmp_row(q, pred, obs, unit=""):
        gap = (obs - pred) / pred * 100 if pred else float("nan")
        return dict(quantity=q, vickrey_closed_form="%.2f" % pred,
                    sumo_equilibrium="%.2f" % obs, pct_gap="%+.1f%%" % gap, unit=unit)
    mq, _ = ci([p["mean_queue_delay"] for p in nt])
    xq, _ = ci([p["max_queue_delay"] for p in nt])
    tq, _ = ci([p["total_queue_delay"] for p in nt])
    mc, _ = ci([p["mean_cost"] for p in nt])
    fe, _ = ci([p["frac_early"] for p in nt])
    cq, _ = ci([p["c_queue"] for p in nt])
    cs_, _ = ci([p["c_early"] + p["c_late"] for p in nt])
    acmp = [
        cmp_row("bottleneck capacity s", s_vph, s_vph, "veh/h (measured, used as the prediction input)"),
        cmp_row("peak duration (last-first departure) = N/s", an["peak_len"], obs_last - obs_first, "s"),
        cmp_row("first departure t_s", an["t_first_depart"], obs_first, "s"),
        cmp_row("last departure t_e", an["t_last_depart"], obs_last, "s"),
        cmp_row("mean queueing delay", an["mean_queue_delay"], mq, "s"),
        cmp_row("max queueing delay = delta*N/(alpha*s)", an["max_queue_delay"], xq, "s"),
        cmp_row("total queueing delay", an["total_queue_delay"], tq, "veh-s"),
        cmp_row("equilibrium cost per traveller (incl. free-flow Tf)",
                an["excess_cost_per_traveller"] + tf, mc, "cost units (= s of alpha-time)"),
        cmp_row("equilibrium EXCESS cost = delta*N/s", an["excess_cost_per_traveller"], mc - tf,
                "cost units"),
        cmp_row("fraction arriving early = gamma/(beta+gamma)", an["frac_early"], fe, "-"),
        cmp_row("queueing share of excess cost (theory 0.5)", 0.5, cq / (cq + cs_), "-"),
        cmp_row("schedule-delay share of excess cost (theory 0.5)", 0.5, cs_ / (cq + cs_), "-"),
    ]
    write_csv(os.path.join(OUT, "analytic_vs_sumo.csv"), acmp)

    # ---------------- plots
    AZ.plot_convergence([c for c in ["no_toll", "tv_toll", "flat_toll", "gamma4", "no_toll_alt"] if c in present],
                        os.path.join(OUT, "fig_convergence.png"))
    rate_t = []
    rate_v = []
    r_e = ALPHA * s / (ALPHA - BETA) * 3600
    r_l = ALPHA * s / (ALPHA + GAMMA) * 3600
    tn = an["t_first_depart"] + an["frac_early"] * N_COMMUTERS / (ALPHA * s / (ALPHA - BETA))
    for a, b, v in [(an["t_first_depart"], tn, r_e), (tn, an["t_last_depart"], r_l)]:
        rate_t += [a, b]; rate_v += [v, v]
    AZ.plot_departure_rates([c for c in CONDS_MAIN if c in present],
                            dict(t=rate_t, rate=rate_v),
                            os.path.join(OUT, "fig_departure_rate.png"), s_vps=s)
    AZ.plot_cost_curves([c for c in CONDS_MAIN if c in present],
                        os.path.join(OUT, "fig_equilibrium_cost_by_slot.png"))
    rb = {}
    for nm in CONDS_MAIN:
        if nm not in present:
            continue
        r = load(nm)
        recs = parse_tripinfo(os.path.join(WORK, "eval_" + nm,
                                           "%s_s%d.tripinfo.xml" % (nm, EVAL_SEEDS[0])))
        counts = np.array(r["counts"], int)
        rou = os.path.join(WORK, "eval_" + nm, "%s_s%d.rou.xml" % (nm, EVAL_SEEDS[0]))
        slot_of = {}
        import xml.etree.ElementTree as ET
        for i, (t, k) in enumerate(counts_to_departs(counts)):
            slot_of["c%04d" % i] = k
        rb[nm] = vehicle_costs(recs, slot_of, tf, np.array(r["toll"], float), gamma=r["gamma"])
    AZ.plot_newell(rb, tf, os.path.join(OUT, "fig_newell_curves.png"))
    tau = np.load(os.path.join(WORK, "toll_timevarying.npy"))
    tau_an = np.load(os.path.join(WORK, "toll_analytic.npy"))
    ft = json.load(open(os.path.join(WORK, "flat_toll.json")))["flat_toll"]
    AZ.plot_toll(tau, tau_an, ft, os.path.join(OUT, "fig_toll_profiles.png"))

    # ---------------- departure profiles as data
    prof = []
    for k in range(NSLOT):
        row = dict(slot=k, t_start="%.0f" % st[k])
        for nm in present:
            row["n_" + nm] = int(load(nm)["counts"][k])
        row["toll_timevarying"] = "%.3f" % tau[k]
        row["toll_analytic"] = "%.3f" % tau_an[k]
        prof.append(row)
    write_csv(os.path.join(OUT, "departure_profiles.csv"), prof)

    print("outputs written to", OUT)
    for f in sorted(os.listdir(OUT)):
        print("   ", f)
    return dict(cap=cap, an=an, ev=ev, tf=tf, s=s, s_vph=s_vph, acmp=acmp,
                dec=dec, tt=tt, eqt=eqt, present=present, flat_toll=ft)


if __name__ == "__main__":
    main()
