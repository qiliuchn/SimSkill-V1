#!/usr/bin/env python3
"""
Analysis of the CAV-penetration bottleneck-capacity experiment.

Per run it derives, from raw detector output only:
  * the empirical breakdown time (upstream speed collapse)
  * an MSER-5 warm-up truncation point on the post-breakdown discharge series
  * SUSTAINED QUEUE-DISCHARGE FLOW  (the capacity number reported everywhere)
  * PRE-BREAKDOWN PEAK FLOW and hence the capacity-drop magnitude
  * the flow-density fundamental diagram from the upstream E1 arrays
  * whether the ENTRY or the BOTTLENECK was the binding constraint

Across runs it produces replication statistics (mean, sd, 95% t-CI), pairwise
tests between adjacent penetration levels, and a linear/quadratic/cubic fit of
capacity vs. penetration with residual diagnostics.
"""
import os
import sys
import json
import glob
import math
import csv
import statistics as st

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as SC  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs")
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))

# Congestion is judged from the SPATIAL mean speed of the whole 2496 m approach
# (edgeData on E_app), not from a point detector and not from E2 jam length:
#   * a point detector 100 m upstream of the drop reads free-flow whenever the
#     jam head has receded further upstream (constant for the ACC/CACC fleets);
#   * E2 "jam length" only counts HALTING vehicles, so a moving 8 m/s queue -
#     which is exactly what the HUMAN fleet forms - registers as zero jam.
QUEUE_V = 15.0            # m/s : E_app spatial mean speed below this => queued
BREAKDOWN_V = 22.0        # m/s : ~75% of free flow => flow breakdown has begun
FREEFLOW_V = 27.0         # m/s : approach still genuinely uncongested
FREEFLOW_V = 25.0         # m/s : upstream speed above this => still uncongested


# --------------------------------------------------------------- statistics --
def tcrit(df):
    """two-sided 0.975 t quantile, small-sample table + normal fallback."""
    T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
         14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
         20: 2.086, 22: 2.074, 24: 2.064, 26: 2.056, 28: 2.048, 30: 2.042,
         40: 2.021, 60: 2.000, 120: 1.980}
    if df in T:
        return T[df]
    ks = sorted(T)
    for k in ks:
        if df < k:
            return T[k]
    return 1.96


def mean_ci(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(xs)
    if n == 0:
        return dict(n=0, mean=float("nan"), sd=float("nan"), ci=float("nan"))
    if n == 1:
        return dict(n=1, mean=xs[0], sd=0.0, ci=float("nan"))
    m, s = st.mean(xs), st.stdev(xs)
    return dict(n=n, mean=m, sd=s, ci=tcrit(n - 1) * s / math.sqrt(n))


def _isnum(x):
    return x is not None and isinstance(x, (int, float)) and not math.isnan(x)


def paired_t(a, b):
    """Paired (Common Random Numbers) t-test on matched seeds.
    a and b are either equal-length lists (already seed-aligned) or dicts
    keyed by seed; NaN pairs are dropped and the surviving n is reported."""
    if isinstance(a, dict) and isinstance(b, dict):
        ks = sorted(set(a) & set(b))
        pairs = [(a[k], b[k]) for k in ks]
    else:
        pairs = list(zip(a, b))
    pairs = [(x, y) for x, y in pairs if _isnum(x) and _isnum(y)]
    d = [x - y for x, y in pairs]
    n = len(d)
    if n < 2:
        return None
    m, s = st.mean(d), st.stdev(d)
    if s == 0:
        return dict(n=n, diff=m, ci=0.0, t=float("inf") if m else 0.0, sig=bool(m))
    se = s / math.sqrt(n)
    t = m / se
    hw = tcrit(n - 1) * se
    return dict(n=n, diff=m, ci=hw, t=t, sig=abs(t) > tcrit(n - 1))


def mser5(series):
    """MSER-5 truncation point (White 1997) on a batched series.
    Returns (index_into_batches, flag) where flag warns if the optimum pins to
    the end of the search range -> no stationary regime detected."""
    x = np.asarray(series, dtype=float)
    b = 5
    nb = len(x) // b
    if nb < 4:
        return 0, "too_short"
    batches = x[:nb * b].reshape(nb, b).mean(axis=1)
    best, bestd = None, np.inf
    lim = max(1, int(nb * 0.75))
    for d in range(lim):
        tail = batches[d:]
        n = len(tail)
        if n < 3:
            break
        z = n * np.var(tail, ddof=0) / (n * n)
        if z < bestd:
            bestd, best = z, d
    flag = "pinned_at_search_limit" if best is not None and best >= lim - 1 else "ok"
    return (best or 0) * b, flag


# ------------------------------------------------------------- per-run work --
def parse_edgedata(path):
    """-> {edge: [(t, speed, density_total, entered, left), ...]}"""
    import xml.etree.ElementTree as ET
    out = {}
    if not os.path.exists(path):
        return out
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            continue
        t = float(el.get("begin"))
        for e in el.findall("edge"):
            out.setdefault(e.get("id"), []).append((
                t, float(e.get("speed", -1)), float(e.get("density", -1)),
                float(e.get("entered", 0)), float(e.get("left", 0))))
        el.clear()
    return out


def analyse_run(m, rundir=None):
    """m = parsed metrics.json -> dict of scalar metrics for this run."""
    bn = m.get("bn_flow", [])
    fdx = m.get("fd", {}).get("x100", [])
    src = m.get("src_flow", [])
    dn = m.get("dn_flow", [])
    if not bn or not fdx:
        return None
    t = [r[0] for r in bn]
    qbn = [r[1] for r in bn]
    vup = [r[2] for r in fdx]            # upstream space-mean speed, 100 m before drop
    qup = [r[1] for r in fdx]
    kup = [r[3] for r in fdx]
    qsrc = [r[1] for r in src] if src else []
    vdn = [r[2] for r in dn] if dn else []

    # ---- CONGESTION STATE from spatial edgeData on the approach ----
    ed = parse_edgedata(os.path.join(rundir, "edgedata.xml")) if rundir else {}
    app = {int(r[0]): r for r in ed.get("E_app", [])}
    bne = {int(r[0]): r for r in ed.get("E_bn", [])}
    if not app:
        return None
    vapp = [app[int(tt)][1] if int(tt) in app else -1 for tt in t]
    kapp = [app[int(tt)][2] if int(tt) in app else -1 for tt in t]
    vbn = [bne[int(tt)][1] if int(tt) in bne else -1 for tt in t]

    queued = [0 <= v < QUEUE_V for v in vapp]

    t_bd = None
    for i in range(len(t) - 2):
        if all(0 <= vapp[i + k] < BREAKDOWN_V for k in range(3)):
            t_bd = t[i]
            break

    # --- pre-breakdown peak: approach still genuinely uncongested ---
    pre = [qbn[i] for i in range(len(t))
           if t[i] >= 120 and vapp[i] >= FREEFLOW_V and (t_bd is None or t[i] < t_bd)]
    pre_peak = max(pre) if pre else float("nan")

    # --- queue discharge: queued intervals, after an MSER-5 warm-up truncation ---
    idx = [i for i in range(len(t)) if queued[i]]
    disc, warm_flag, t_warm = float("nan"), "no_queue_formed", None
    disc_series = []
    if len(idx) >= 8:
        i0 = idx[0]
        cut, warm_flag = mser5(qbn[i0:])
        t_warm = t[min(i0 + cut, len(t) - 1)]
        disc_series = [qbn[i] for i in range(len(t)) if i >= i0 + cut and queued[i]]
        if disc_series:
            disc = st.mean(disc_series)

    # A "capacity drop" is only meaningful if the bottleneck was actually PUSHED
    # to capacity while still uncongested.  If the approach slowed down before
    # demand ever reached the eventual discharge rate (which is what the CACC
    # fleets do), the pre-breakdown peak is NOT a capacity estimate and the drop
    # is reported as not estimable rather than as a spurious negative number.
    pre_times = [t[i] for i in range(len(t))
                 if t[i] >= 120 and vapp[i] >= FREEFLOW_V and (t_bd is None or t[i] < t_bd)]
    demand_at_pre_end = SC.demand_rate(max(pre_times)) if pre_times else float("nan")
    drop_estimable = bool(pre_times and disc == disc and demand_at_pre_end >= disc)
    cap_drop = (pre_peak - disc) if (drop_estimable and pre_peak == pre_peak) else float("nan")

    # --- oscillation / stop-and-go diagnostics in the discharge window ---
    osc_cv = float("nan")
    if len(disc_series) >= 3 and st.mean(disc_series):
        osc_cv = st.stdev(disc_series) / st.mean(disc_series)
    frac_queued = sum(queued) / len(queued) if queued else float("nan")
    max_k_app = max([k for k in kapp if k > 0], default=float("nan"))
    min_v_app = min([v for v in vapp if v >= 0], default=float("nan"))
    # downstream-of-the-drop speed WHILE the queue discharges: the decisive
    # evidence that the drop itself, not anything downstream, is the constraint
    vbn_q = [vbn[i] for i in idx if vbn[i] > 0]
    bn_speed_queued = st.mean(vbn_q) if vbn_q else float("nan")

    # --- is the ENTRY or the BOTTLENECK binding? ---
    free_i = [i for i in range(len(t)) if t[i] >= 120 and vapp[i] >= FREEFLOW_V]
    src_free_max = max((qsrc[i] for i in free_i), default=float("nan")) if qsrc else float("nan")
    src_max = max(qsrc) if qsrc else float("nan")
    dn_v_late = st.mean([vdn[i] for i in range(len(t)) if t[i] >= 1500 and vdn[i] > 0]) \
        if vdn else float("nan")

    # --- fundamental diagram from SPATIAL edgeData (density is measured, not q/v) ---
    fd_pts = [(r[2] / 3.0, r[2] * r[1] * 3.6 / 3.0, r[1])       # (k/lane, q/lane, v)
              for r in ed.get("E_app", []) if r[2] > 0 and r[1] >= 0]

    tri = m.get("tripinfo", {})
    lead = m.get("leader", {}) or {}
    return dict(
        discharge=disc, pre_peak=pre_peak, cap_drop=cap_drop,
        cap_drop_pct=(100.0 * cap_drop / pre_peak) if pre_peak == pre_peak and pre_peak else float("nan"),
        t_breakdown=t_bd if t_bd is not None else float("nan"),
        # the demand level at which flow broke down = the "breakdown flow"
        demand_at_breakdown=SC.demand_rate(t_bd) if t_bd is not None else float("nan"),
        broke_down=1 if t_bd is not None else 0,
        warm_flag=warm_flag, t_warm=t_warm,
        drop_estimable=1 if drop_estimable else 0,
        demand_at_pre_end=demand_at_pre_end,
        osc_cv=osc_cv, frac_queued=frac_queued,
        n_disc_intervals=len(disc_series),
        src_max=src_max, src_free_max=src_free_max, dn_speed_late=dn_v_late,
        max_k_up=max_k_app, min_v_up=min_v_app, bn_speed_queued=bn_speed_queued,
        n_trips=tri.get("n", 0), mean_duration=tri.get("mean_duration", float("nan")),
        mean_timeloss=tri.get("mean_timeloss", float("nan")),
        mean_departdelay=tri.get("mean_departdelay", float("nan")),
        by_type=tri.get("by_type", {}), collisions=m.get("collisions", 0),
        p_leader_av_given_av=lead.get("p_leader_av_given_av"),
        p_leader_av_overall=lead.get("p_leader_av_overall"),
        realized_av_share_obs=lead.get("realized_av_share_obs"),
        mean_gap_av_behind_av=lead.get("mean_gap_av_behind_av"),
        mean_gap_av_behind_hv=lead.get("mean_gap_av_behind_hv"),
        tg_av_behind_av=lead.get("mean_timegap_av_behind_av"),
        tg_av_behind_hv=lead.get("mean_timegap_av_behind_hv"),
        fd=fd_pts,
    )


def load_all():
    cells = {}
    for mj in sorted(glob.glob(os.path.join(RUNS, "*", "s*", "metrics.json"))):
        try:
            m = json.load(open(mj))
        except Exception:
            continue
        meta = m.get("meta", {})
        if meta.get("rc") != 0:
            continue
        r = analyse_run(m, os.path.dirname(mj))
        if r is None:
            continue
        r["meta"] = meta
        cells.setdefault(meta.get("cell", "?"), []).append((meta.get("seed"), r))
    for c in cells:
        cells[c].sort()
    return cells


# ------------------------------------------------------------- curve fitting --
def polyfit_report(p, y):
    """Fit capacity vs penetration with degree 1/2/3; report residuals, adjusted
    R^2 and an F-test of quadratic-over-linear, plus the SIGN of the quadratic
    coefficient (>0 convex, <0 concave)."""
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    out = {}
    n = len(p)
    for deg in (1, 2, 3):
        if n <= deg + 1:
            continue
        c = np.polyfit(p, y, deg)
        yh = np.polyval(c, p)
        res = y - yh
        ss_res = float(np.sum(res ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        adj = 1 - (1 - r2) * (n - 1) / (n - deg - 1) if n - deg - 1 > 0 else float("nan")
        out[deg] = dict(coef=c.tolist(), ss_res=ss_res, r2=r2, adj_r2=adj,
                        rmse=float(np.sqrt(ss_res / n)),
                        max_abs_resid=float(np.max(np.abs(res))),
                        resid=res.tolist())
    if 1 in out and 2 in out:
        df2 = n - 3
        if df2 > 0 and out[2]["ss_res"] > 0:
            F = ((out[1]["ss_res"] - out[2]["ss_res"]) / 1.0) / (out[2]["ss_res"] / df2)
            out["F_quad_over_lin"] = float(F)
            out["F_df"] = (1, df2)
            # 0.95 critical values of F(1, df)
            FC = {1: 161.4, 2: 18.51, 3: 10.13, 4: 7.71, 5: 6.61, 6: 5.99, 7: 5.59,
                  8: 5.32, 9: 5.12, 10: 4.96, 12: 4.75, 15: 4.54, 20: 4.35, 30: 4.17}
            fc = FC.get(df2) or FC[min(FC, key=lambda k: abs(k - df2))]
            out["F_crit_0.95"] = fc
            out["quadratic_justified"] = bool(F > fc)
        out["quad_coef_sign"] = ("convex (curving upward)" if out[2]["coef"][0] > 0
                                 else "concave (curving downward)")
    return out


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    cells = load_all()
    print("cells with data: %d ; total runs: %d"
          % (len(cells), sum(len(v) for v in cells.values())))

    # ---------------- per-cell compacted CSV ----------------
    rows = []
    FIELDS = ["cell", "n_seeds", "av_type", "p", "arrangement", "net", "demand_mode",
              "discharge_mean", "discharge_sd", "discharge_ci95",
              "pre_peak_mean", "pre_peak_ci95", "cap_drop_mean", "cap_drop_pct_mean",
              "cap_drop_estimable_frac", "demand_at_pre_end_mean",
              "breakdown_frac", "t_breakdown_mean", "demand_at_breakdown_mean", "demand_at_breakdown_ci95",
              "duration_mean", "duration_ci95", "timeloss_mean", "departdelay_mean",
              "src_max_mean", "src_free_max_mean", "dn_speed_late_mean",
              "max_k_up_mean", "n_trips_mean", "collisions_total",
              "frac_queued_mean", "bn_speed_queued_mean", "discharge_osc_cv_mean",
              "p_leader_av_given_av", "p_leader_av_overall", "realized_av_share_obs",
              "gap_av_behind_av", "gap_av_behind_hv",
              "timegap_av_behind_av", "timegap_av_behind_hv", "warm_flags"]
    percell = {}
    for cell, rs in sorted(cells.items()):
        meta = rs[0][1]["meta"]
        g = lambda k: [r[k] for _, r in rs]  # noqa: E731
        d = mean_ci(g("discharge"))
        pp = mean_ci(g("pre_peak"))
        du = mean_ci(g("mean_duration"))
        row = dict(
            cell=cell, n_seeds=len(rs), av_type=meta.get("av_type"), p=meta.get("p"),
            arrangement=meta.get("arrangement"), net=meta.get("net", "bneck.net.xml"),
            demand_mode=meta.get("demand_mode"),
            discharge_mean=round(d["mean"], 1), discharge_sd=round(d["sd"], 1),
            discharge_ci95=round(d["ci"], 1) if d["ci"] == d["ci"] else "",
            pre_peak_mean=round(pp["mean"], 1),
            pre_peak_ci95=round(pp["ci"], 1) if pp["ci"] == pp["ci"] else "",
            cap_drop_mean=round(mean_ci(g("cap_drop"))["mean"], 1),
            cap_drop_pct_mean=round(mean_ci(g("cap_drop_pct"))["mean"], 2),
            cap_drop_estimable_frac=round(st.mean(g("drop_estimable")), 3),
            demand_at_pre_end_mean=round(mean_ci(g("demand_at_pre_end"))["mean"], 0),
            breakdown_frac=round(st.mean(g("broke_down")), 3),
            t_breakdown_mean=round(mean_ci(g("t_breakdown"))["mean"], 1),
            demand_at_breakdown_mean=round(mean_ci(g("demand_at_breakdown"))["mean"], 0),
            demand_at_breakdown_ci95=round(mean_ci(g("demand_at_breakdown"))["ci"], 0)
            if mean_ci(g("demand_at_breakdown"))["ci"] == mean_ci(g("demand_at_breakdown"))["ci"] else "",
            duration_mean=round(du["mean"], 1),
            duration_ci95=round(du["ci"], 1) if du["ci"] == du["ci"] else "",
            timeloss_mean=round(mean_ci(g("mean_timeloss"))["mean"], 1),
            departdelay_mean=round(mean_ci(g("mean_departdelay"))["mean"], 1),
            src_max_mean=round(mean_ci(g("src_max"))["mean"], 1),
            src_free_max_mean=round(mean_ci(g("src_free_max"))["mean"], 1),
            dn_speed_late_mean=round(mean_ci(g("dn_speed_late"))["mean"], 2),
            max_k_up_mean=round(mean_ci(g("max_k_up"))["mean"], 1),
            n_trips_mean=round(mean_ci(g("n_trips"))["mean"], 1),
            collisions_total=sum(g("collisions")),
            frac_queued_mean=round(mean_ci(g("frac_queued"))["mean"], 3),
            bn_speed_queued_mean=round(mean_ci(g("bn_speed_queued"))["mean"], 2),
            discharge_osc_cv_mean=round(mean_ci(g("osc_cv"))["mean"], 4),
            p_leader_av_given_av=round(mean_ci(g("p_leader_av_given_av"))["mean"], 4)
            if any(x is not None for x in g("p_leader_av_given_av")) else "",
            p_leader_av_overall=round(mean_ci(g("p_leader_av_overall"))["mean"], 4)
            if any(x is not None for x in g("p_leader_av_overall")) else "",
            realized_av_share_obs=round(mean_ci(g("realized_av_share_obs"))["mean"], 4)
            if any(x is not None for x in g("realized_av_share_obs")) else "",
            gap_av_behind_av=round(mean_ci(g("mean_gap_av_behind_av"))["mean"], 2)
            if any(x is not None for x in g("mean_gap_av_behind_av")) else "",
            gap_av_behind_hv=round(mean_ci(g("mean_gap_av_behind_hv"))["mean"], 2)
            if any(x is not None for x in g("mean_gap_av_behind_hv")) else "",
            timegap_av_behind_av=round(mean_ci(g("tg_av_behind_av"))["mean"], 4)
            if any(x is not None for x in g("tg_av_behind_av")) else "",
            timegap_av_behind_hv=round(mean_ci(g("tg_av_behind_hv"))["mean"], 4)
            if any(x is not None for x in g("tg_av_behind_hv")) else "",
            warm_flags=";".join(sorted(set(g("warm_flag")))),
        )
        rows.append(row)
        percell[cell] = dict(row=row, runs=rs)
    with open(os.path.join(OUTDIR, "cell_metrics.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print("wrote cell_metrics.csv (%d cells)" % len(rows))

    report = {}

    # ---------------- (a) is the bottleneck the binding constraint? -----------
    ctl = {}
    for cell, d in percell.items():
        if cell.startswith("entryctl__"):
            ctl[cell.split("__")[1]] = d["row"]
    bind = []
    for cell, d in percell.items():
        if not cell.startswith("homo__"):
            continue
        ty = cell.split("__")[1]
        c = ctl.get(ty, {})
        bind.append(dict(
            fleet=ty,
            bottleneck_discharge=d["row"]["discharge_mean"],
            entry_served_while_freeflow=d["row"]["src_free_max_mean"],
            entry_max_this_run=d["row"]["src_max_mean"],
            downstream_speed_while_queue_discharges=d["row"]["bn_speed_queued_mean"],
            entry_capacity_nodrop_control=c.get("src_max_mean"),
            downstream_speed_late=d["row"]["dn_speed_late_mean"],
            max_upstream_density=d["row"]["max_k_up_mean"],
            verdict=("BOTTLENECK binds" if (c.get("src_max_mean") or 0) >
                     d["row"]["discharge_mean"] * 1.10 else "CHECK - entry may bind")))
    report["bottleneck_is_binding"] = bind

    # ---------------- (b) homogeneous baselines -------------------------------
    homo = {}
    for cell, d in percell.items():
        if cell.startswith("homo__"):
            homo[cell.split("__")[1]] = d
    base = homo.get("HUMAN", {}).get("row", {}).get("discharge_mean", float("nan"))
    hb = []
    for ty in ["HUMAN", "HUMAN_SIGMA0", "HUMAN_FAST", "ACC", "CACC", "CACC_TIGHT"]:
        if ty not in homo:
            continue
        r = homo[ty]["row"]
        hb.append(dict(fleet=ty, tau=S_TAU.get(ty), model=S_MODEL.get(ty),
                       discharge=r["discharge_mean"], ci95=r["discharge_ci95"],
                       per_lane=round(r["discharge_mean"] / 2.0, 1),
                       vs_human_pct=round(100 * (r["discharge_mean"] - base) / base, 2),
                       pre_breakdown_peak=r["pre_peak_mean"],
                       capacity_drop=r["cap_drop_mean"],
                       capacity_drop_pct=r["cap_drop_pct_mean"],
                       capacity_drop_estimable_frac=r["cap_drop_estimable_frac"],
                       demand_when_prebreakdown_window_ended=r["demand_at_pre_end_mean"],
                       breakdown_frac=r["breakdown_frac"],
                       demand_at_breakdown=r["demand_at_breakdown_mean"],
                       demand_at_breakdown_ci95=r["demand_at_breakdown_ci95"],
                       frac_time_queued=r["frac_queued_mean"],
                       max_density_approach=r["max_k_up_mean"],
                       bottleneck_speed_while_queued=r["bn_speed_queued_mean"],
                       discharge_oscillation_cv=r["discharge_osc_cv_mean"],
                       mean_travel_time=r["duration_mean"]))
    report["homogeneous_baselines"] = hb

    # mechanism decomposition, with paired tests on matched seeds
    def seedmap(cell, key="discharge"):
        """{seed: value} so every paired comparison is aligned on the SAME seed."""
        if cell not in percell:
            return {}
        return {sd: r[key] for sd, r in percell[cell]["runs"]}

    def seedvals(cell, key="discharge"):
        m = seedmap(cell, key)
        return [m[k] for k in sorted(m)]
    mech = {}
    pairs = [("HUMAN", "HUMAN_SIGMA0", "removing driver imperfection only (sigma 0.5->0, tau 1.3)"),
             ("HUMAN_SIGMA0", "HUMAN_FAST", "shortening tau only (1.3->0.9, sigma already 0)"),
             ("HUMAN", "HUMAN_FAST", "TOTAL effect of the Krauss mechanism control"),
             ("HUMAN_FAST", "ACC", "swapping Krauss->ACC at the SAME tau (pure model structure)"),
             ("HUMAN_FAST", "CACC", "swapping Krauss->CACC at the SAME tau (pure model structure)"),
             ("ACC", "CACC", "ACC->CACC at the same tau"),
             ("CACC", "CACC_TIGHT", "CACC tau 0.9->0.6")]
    for a, b, why in pairs:
        ca, cb = "homo__" + a, "homo__" + b
        ma, mb = seedmap(ca), seedmap(cb)
        va, vb = seedvals(ca), seedvals(cb)
        t = paired_t(mb, ma) if (ma and mb) else None
        if t:
            mech["%s -> %s" % (a, b)] = dict(
                why=why, n_pairs=t["n"],
                mean_a=round(mean_ci(va)["mean"], 1), mean_b=round(mean_ci(vb)["mean"], 1),
                diff=round(t["diff"], 1), ci95=round(t["ci"], 1),
                pct=round(100 * t["diff"] / mean_ci(va)["mean"], 2),
                significant_at_95=t["sig"])
    report["mechanism_decomposition_paired"] = mech

    # ---------------- (c) penetration sweep + curve fit -----------------------
    sweeps = {}
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        pts = []
        pts.append((0.0, "homo__HUMAN"))
        for pp_ in [20, 40, 60, 80]:
            pts.append((pp_ / 100.0, "sweep__%s__p%02d" % (arm, pp_)))
        pts.append((1.0, "homo__%s" % arm))
        levels, means, cis, allseed = [], [], [], {}
        for pv, cell in pts:
            if cell not in percell:
                continue
            sm = seedmap(cell)
            m = mean_ci(list(sm.values()))
            levels.append(pv)
            means.append(m["mean"])
            cis.append(m["ci"])
            allseed[pv] = sm
        if len(levels) < 4:
            continue
        fit = polyfit_report(levels, means)
        # adjacent-level significance, paired on seeds (CRN)
        adj = []
        for i in range(len(levels) - 1):
            a, b = allseed[levels[i]], allseed[levels[i + 1]]
            t = paired_t(b, a)
            if t:
                adj.append(dict(from_p=levels[i], to_p=levels[i + 1], n_pairs=t["n"],
                                diff=round(t["diff"], 1), ci95=round(t["ci"], 1),
                                distinguishable_at_95=t["sig"]))
        # is the whole curve within noise of p=0?
        vs0 = []
        base0 = allseed.get(0.0, {})
        for pv in levels:
            if pv == 0.0 or not base0:
                continue
            t = paired_t(allseed[pv], base0)
            if t:
                vs0.append(dict(p=pv, n_pairs=t["n"], diff=round(t["diff"], 1),
                                ci95=round(t["ci"], 1),
                                distinguishable_from_p0=t["sig"]))
        sweeps[arm] = dict(p=levels, discharge_mean=[round(x, 1) for x in means],
                           ci95=[round(x, 1) if x == x else None for x in cis],
                           travel_time=[round(mean_ci([r["mean_duration"] for _, r in
                                                       percell[c]["runs"]])["mean"], 1)
                                        for _, c in pts if c in percell],
                           breakdown_frac=[percell[c]["row"]["breakdown_frac"]
                                           for _, c in pts if c in percell],
                           demand_at_breakdown=[percell[c]["row"]["demand_at_breakdown_mean"]
                                                for _, c in pts if c in percell],
                           fit=fit, adjacent_tests=adj, vs_p0_tests=vs0,
                           seed_values={str(k): v for k, v in allseed.items()})
    report["penetration_sweeps"] = sweeps

    # ---------------- (d) arrangement effect ----------------------------------
    arr = {}
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        cr, cp = "arr__%s__p50__random" % arm, "arr__%s__p50__platoon" % arm
        if cr not in percell or cp not in percell:
            continue
        vr, vp = seedvals(cr), seedvals(cp)
        t = paired_t(seedmap(cp), seedmap(cr))
        if not t:
            continue
        h0 = homo.get("HUMAN", {}).get("row", {}).get("discharge_mean", float("nan"))
        h1 = homo.get(arm, {}).get("row", {}).get("discharge_mean", float("nan"))
        full = h1 - h0
        mr, mp = mean_ci(vr)["mean"], mean_ci(vp)["mean"]
        d = dict(random_mean=round(mr, 1), platoon_mean=round(mp, 1),
                 n_pairs=t["n"], diff=round(t["diff"], 1), ci95=round(t["ci"], 1),
                 significant_at_95=t["sig"],
                 p0_capacity=h0, p100_capacity=h1,
                 full_penetration_benefit=round(full, 1),
                 recovered_by_random_pct=round(100 * (mr - h0) / full, 1) if full else None,
                 recovered_by_platoon_pct=round(100 * (mp - h0) / full, 1) if full else None,
                 arrangement_share_of_full_benefit_pct=round(100 * t["diff"] / full, 1) if full else None)
        for lab, cell in [("random", "fcd__%s__p50__random" % arm),
                          ("platoon", "fcd__%s__p50__platoon" % arm)]:
            if cell in percell:
                r = percell[cell]["row"]
                d["leader_av_given_av_" + lab] = r["p_leader_av_given_av"]
                d["gap_av_behind_av_" + lab] = r["gap_av_behind_av"]
                d["gap_av_behind_hv_" + lab] = r["gap_av_behind_hv"]
                d["timegap_av_behind_av_" + lab] = r["timegap_av_behind_av"]
                d["timegap_av_behind_hv_" + lab] = r["timegap_av_behind_hv"]
        arr[arm] = d
    report["arrangement_effect"] = arr

    # ---------------- (e) leader-is-AV fraction vs p --------------------------
    lead = {}
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        seq = []
        for pv in [20, 40, 50, 60, 80]:
            cell = "fcd__%s__p%02d__random" % (arm, pv)
            if cell in percell:
                r = percell[cell]["row"]
                seq.append(dict(p=pv / 100.0, measured=r["p_leader_av_given_av"],
                                naive_p=pv / 100.0, naive_p_squared=(pv / 100.0) ** 2,
                                realized_share_in_zone=r["realized_av_share_obs"],
                                overall_leader_av=r["p_leader_av_overall"],
                                timegap_behind_av=r["timegap_av_behind_av"],
                                timegap_behind_human=r["timegap_av_behind_hv"]))
        pl = "fcd__%s__p50__platoon" % arm
        if pl in percell:
            seq.append(dict(p=0.5, arrangement="platoon",
                            measured=percell[pl]["row"]["p_leader_av_given_av"],
                            naive_p=0.5, naive_p_squared=0.25,
                            realized_share_in_zone=percell[pl]["row"]["realized_av_share_obs"],
                            overall_leader_av=percell[pl]["row"]["p_leader_av_overall"]))
        if seq:
            lead[arm] = seq
    report["leader_is_av_fraction"] = lead

    # ---------------- (f) vTypeDistribution cross-check -----------------------
    if "vtdist__ACC__p40" in percell and "sweep__ACC__p40" in percell:
        a = seedvals("sweep__ACC__p40")
        b = seedvals("vtdist__ACC__p40")
        report["vtypedistribution_crosscheck"] = dict(
            explicit_assignment=mean_ci(a), sumo_vTypeDistribution=mean_ci(b),
            note="independent designs (the vTypeDistribution arm does not share the "
                 "explicit demand stream), so an unpaired comparison of the CIs is used")

    # ---------------- (g) warm-up / stationarity honesty ----------------------
    wf = {}
    for cell, d in percell.items():
        for f in d["row"]["warm_flags"].split(";"):
            wf[f] = wf.get(f, 0) + 1
    report["warmup_flags"] = wf

    # ---------------- (h) CRN effectiveness -----------------------------------
    crn = {}
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        m0, m1 = seedmap("homo__HUMAN"), seedmap("sweep__%s__p40" % arm)
        ks = sorted(k for k in set(m0) & set(m1) if _isnum(m0[k]) and _isnum(m1[k]))
        c0 = [m0[k] for k in ks]
        c1 = [m1[k] for k in ks]
        if len(c0) >= 3:
            r = float(np.corrcoef(c0, c1)[0, 1])
            var_paired = st.variance([x - y for x, y in zip(c1, c0)])
            var_indep = st.variance(c1) + st.variance(c0)
            crn[arm] = dict(paired_correlation=round(r, 3),
                            var_of_diff_paired=round(var_paired, 1),
                            var_of_diff_if_independent=round(var_indep, 1),
                            variance_reduction_factor=round(var_indep / var_paired, 2)
                            if var_paired > 0 else None)
    report["crn_effectiveness_p40_vs_p0"] = crn

    # ---- (i) how much of each fleet's PURE car-following capacity does the
    #          bottleneck actually deliver?  The shortfall is the part of the
    #          outcome that car-following alone does NOT explain -- i.e. the
    #          lane-change / merge-turbulence penalty at the drop.
    probe_p = os.path.join(ROOT, "probe", "probe_results.json")
    if os.path.exists(probe_p):
        PR = json.load(open(probe_p))
        eff_tau = {}
        for k, v in PR.items():
            lead, foll = k.split("->")
            if lead == foll:                       # homogeneous fleet => own-type leader
                eff_tau[foll] = (v["gap"] - 2.5) / v["settled_speed"]
        eff_tau.setdefault("HUMAN", (PR["HUMAN->HUMAN"]["gap"] - 2.5) / PR["HUMAN->HUMAN"]["settled_speed"])
        cf = []
        for ty, d in sorted(homo.items()):
            r = d["row"]
            tau_e = eff_tau.get(ty)
            v_bn = r["bn_speed_queued_mean"]
            if tau_e is None or not v_bn or v_bn != v_bn:
                continue
            # single-lane car-following capacity at the OBSERVED discharge speed
            q_lane = 3600.0 / (tau_e + 7.5 / v_bn)
            q_2lane = 2 * q_lane
            cf.append(dict(fleet=ty, effective_tau_from_probe=round(tau_e, 3),
                           observed_discharge_speed=v_bn,
                           pure_carfollowing_capacity_2lane=round(q_2lane, 0),
                           measured_bottleneck_discharge=r["discharge_mean"],
                           efficiency_pct=round(100.0 * r["discharge_mean"] / q_2lane, 1),
                           shortfall_veh_per_h=round(q_2lane - r["discharge_mean"], 0),
                           discharge_oscillation_cv=r["discharge_osc_cv_mean"]))
        report["carfollowing_vs_network_capacity"] = cf
        report["probe_effective_time_gaps"] = PR

    with open(os.path.join(OUTDIR, "results.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    print("wrote results.json")

    # fundamental-diagram points per homogeneous fleet, for plotting
    fdout = {}
    for ty, d in homo.items():
        pts = []
        for _, r in d["runs"]:
            pts.extend(r["fd"])
        fdout[ty] = pts
    json.dump(fdout, open(os.path.join(ROOT, "fd_points.json"), "w"))
    return report


S_TAU = {"HUMAN": 1.3, "HUMAN_SIGMA0": 1.3, "HUMAN_FAST": 0.9,
         "ACC": 0.9, "CACC": 0.9, "CACC_TIGHT": 0.6}
S_MODEL = {"HUMAN": "Krauss sigma=0.5", "HUMAN_SIGMA0": "Krauss sigma=0",
           "HUMAN_FAST": "Krauss sigma=0", "ACC": "ACC", "CACC": "CACC",
           "CACC_TIGHT": "CACC"}

if __name__ == "__main__":
    main()
