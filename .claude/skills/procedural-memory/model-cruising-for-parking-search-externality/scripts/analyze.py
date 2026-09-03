"""Analysis for the cruising-for-parking study: H1-H6, figures, tables, validity.

Free-flow reference speed is the network's uniform 11.11 m/s limit, so per-phase
delay = VHT - VMT/11.11.  This (rather than tripinfo's `timeLoss`) is the primary
delay metric because a parker's tripinfo `duration` includes its parked dwell,
which would swamp any running-delay comparison.  tripinfo is retained and used
as an independent cross-check for through traffic, which never parks.
"""
import json
import math
import os
import glob
from collections import defaultdict

import numpy as np
from scipy import stats, optimize
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

from common import RUN_DIR, DATA_DIR, FIG_DIR   # noqa: E402

VFREE = 11.11
WIN = (1500, 3600)          # steady-state measurement window
OUT = {}


# --------------------------------------------------------------------------- #
def load(name):
    """Raw per-run records are stored gzipped (result.json.gz) to keep the
    512-run archive at a reasonable size; a plain result.json is still read if
    present, so a freshly-run campaign works without a compression step."""
    p = os.path.join(RUN_DIR, name, "result.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    pz = p + ".gz"
    if os.path.exists(pz):
        import gzip
        with gzip.open(pz, "rt") as f:
            return json.load(f)
    return None


def all_runs(prefix):
    names = [os.path.basename(os.path.dirname(p))
             for p in (glob.glob(os.path.join(RUN_DIR, prefix + "*", "result.json")) +
              glob.glob(os.path.join(RUN_DIR, prefix + "*", "result.json.gz")))]
    # calibration probe runs are not part of the 512-run campaign
    return sorted(n for n in names if not n.startswith("calib_"))


def curb_occ_series(r):
    kind = r["lot_kind"]
    ccap = sum(v for k, v in r["lot_cap"].items() if kind[k] == "curb")
    tcap = r["capacity"]
    cs, ts, tt = [], [], []
    for t, snap in r["occupancy"]:
        tt.append(t)
        cs.append(sum(v for k, v in snap.items() if kind[k] == "curb") / ccap)
        ts.append(sum(snap.values()) / tcap)
    return np.array(tt), np.array(cs), np.array(ts)


def summarize(r):
    """One run -> a flat dict of the metrics every hypothesis draws on."""
    t, cs, ts = curb_occ_series(r)
    m = (t >= WIN[0]) & (t <= WIN[1])
    P = r["parkers"]
    T = r["through"]
    served = [p for p in P if p["t_park"] is not None]
    win = [p for p in served if WIN[0] <= p["t_park"] <= WIN[1]]

    def dly(vht, vmt):
        return vht - vmt / VFREE

    par_vmt_app = sum(p["vmt_app"] for p in P)
    par_vmt_srch = sum(p["vmt_srch"] for p in P)
    par_vmt_egr = sum(p["vmt_egr"] for p in P)
    par_vht_app = sum(p["vht_app"] for p in P)
    par_vht_srch = sum(p["vht_srch"] for p in P)
    par_vht_egr = sum(p["vht_egr"] for p in P)
    thr_vmt = sum(x["vmt"] for x in T)
    thr_vht = sum(x["vht"] for x in T)
    ini_vmt = sum(v[0] for v in r.get("initveh", {}).values())
    ini_vht = sum(v[1] for v in r.get("initveh", {}).values())

    net_vmt = par_vmt_app + par_vmt_srch + par_vmt_egr + thr_vmt + ini_vmt
    net_vht = par_vht_app + par_vht_srch + par_vht_egr + thr_vht + ini_vht

    walk = [p["walk_t"] for p in win if p["walk_t"] is not None]
    gc = [p["gencost"] for p in win if p["gencost"] is not None]
    # a parker can reach a lot without ever entering the search zone (garages sit on
    # ring edges); those have no SEARCH phase and are excluded from search statistics
    srch = [p["search_t"] for p in win if p["search_t"] is not None]
    n_no_zone = sum(1 for p in win if p["search_t"] is None)

    # generalized cost decomposition for served, in-window parkers
    def gcparts(ps):
        iv = [(p["t_park"] - p["t_depart"]) * p["vot"] / 3600.0 for p in ps if p["walk_t"] is not None]
        wk = [p["walk_t"] * p["vot_walk"] / 3600.0 for p in ps if p["walk_t"] is not None]
        fe = [p["fee"] for p in ps if p["walk_t"] is not None]
        return iv, wk, fe
    iv, wk, fe = gcparts(win)

    n_bal = sum(1 for p in P if p.get("balked"))
    n_never = sum(1 for p in P if p["t_park"] is None and not p.get("balked")
                  and p["phase_end"] != "removed_nosearch")
    cons = np.array(r["consistency"]) if r["consistency"] else np.zeros((1, 5))
    cons_ok = int(np.all(cons[:, 1] == cons[:, 2])) if cons.shape[1] >= 3 else -1
    cons_phase_ok = int(np.all(cons[:, 1] == cons[:, 3] + cons[:, 4])) if cons.shape[1] >= 5 else -1

    return dict(
        cfg=r["config"], capacity=r["capacity"],
        curb_occ=float(cs[m].mean()), curb_occ_peak=float(cs[m].max()),
        tot_occ=float(ts[m].mean()),
        n_parkers=len(P), n_served=len(served), n_win=len(win),
        n_balk=n_bal, n_never=n_never, n_no_searchzone=n_no_zone,
        never_share=n_never / max(1, len(P)),
        search_mean=float(np.mean(srch)) if srch else np.nan,
        search_med=float(np.median(srch)) if srch else np.nan,
        search_p90=float(np.percentile(srch, 90)) if srch else np.nan,
        approach_mean=float(np.mean([p["approach_t"] for p in win if p["approach_t"] is not None]))
        if win else np.nan,
        walk_mean=float(np.mean(walk)) if walk else np.nan,
        gencost_mean=float(np.mean(gc)) if gc else np.nan,
        gc_invehicle=float(np.mean(iv)) if iv else np.nan,
        gc_walk=float(np.mean(wk)) if wk else np.nan,
        gc_fee=float(np.mean(fe)) if fe else np.nan,
        vmt_app=par_vmt_app, vmt_srch=par_vmt_srch, vmt_egr=par_vmt_egr,
        vht_app=par_vht_app, vht_srch=par_vht_srch, vht_egr=par_vht_egr,
        thr_vmt=thr_vmt, thr_vht=thr_vht, ini_vmt=ini_vmt, ini_vht=ini_vht,
        net_vmt=net_vmt, net_vht=net_vht,
        srch_vmt_share=par_vmt_srch / net_vmt if net_vmt else np.nan,
        srch_vht_share=par_vht_srch / net_vht if net_vht else np.nan,
        core_vmt_srch_share=par_vmt_srch / max(1e-9, par_vmt_srch + sum(x["vmt_core"] for x in T)),
        thr_delay_per_veh=dly(thr_vht, thr_vmt) / max(1, len(T)),
        thr_delay_total=dly(thr_vht, thr_vmt),
        par_delay_total=dly(par_vht_app + par_vht_srch + par_vht_egr,
                            par_vmt_app + par_vmt_srch + par_vmt_egr),
        srch_delay_total=dly(par_vht_srch, par_vmt_srch),
        ini_delay_total=dly(ini_vht, ini_vmt),
        thr_throughput=len(r["tripinfo"]) if r["tripinfo"] else np.nan,
        teleports=len(r["teleports"]), teleport_reasons=r["teleport_reasons"],
        ped_jams=r.get("pedestrian_jams", 0),
        standing=r.get("standing", {}),
        end_phase={k: sum(1 for p in P if p["phase_end"] == k)
                   for k in set(p["phase_end"] for p in P)},
        still_walking=sum(1 for p in P if p["t_park"] is not None and p["walk_t"] is None),
        final_fee=r["final_fee_curb"], reroute_stats=r.get("reroute_stats", {}),
        cons_stopstate_ok=cons_ok, cons_phase_ok=cons_phase_ok,
        cons_max_abs_dev=float(np.max(np.abs(cons[:, 1] - cons[:, 3] - cons[:, 4])))
        if cons.shape[1] >= 5 else np.nan,
    )


def ci(x, conf=0.95):
    x = np.asarray([v for v in x if v == v], dtype=float)
    if len(x) < 2:
        return (float(x.mean()) if len(x) else np.nan, np.nan, np.nan)
    m = x.mean()
    h = stats.t.ppf(0.5 + conf / 2, len(x) - 1) * x.std(ddof=1) / math.sqrt(len(x))
    return float(m), float(m - h), float(m + h)


def paired(a, b, conf=0.95):
    """Paired (CRN) difference a-b with CI and p-value."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = a - b
    d = d[~np.isnan(d)]
    m = d.mean()
    if len(d) < 2:
        return dict(mean=float(m), lo=np.nan, hi=np.nan, p=np.nan, n=len(d))
    h = stats.t.ppf(0.5 + conf / 2, len(d) - 1) * d.std(ddof=1) / math.sqrt(len(d))
    t, p = stats.ttest_rel(a[~np.isnan(a - b)], b[~np.isnan(a - b)])
    return dict(mean=float(m), lo=float(m - h), hi=float(m + h), p=float(p), n=len(d))


# --------------------------------------------------------------------------- #
SEEDS = list(range(1, 9))
OCC_LEVELS = [0.60, 0.70, 0.80, 0.88, 0.94, 1.00, 1.06, 1.15]
INFO_OCC = [0.80, 0.94, 1.06]

CACHE = {}


def S(name):
    if name not in CACHE:
        r = load(name)
        CACHE[name] = summarize(r) if r else None
    return CACHE[name]


def grid(fmt, occs=OCC_LEVELS):
    """{occ: [per-seed summary]}"""
    out = {}
    for o in occs:
        rows = [S(fmt % (o, s)) for s in SEEDS]
        out[o] = [x for x in rows if x]
    return out


# ============================ H1 ============================================ #
def h1():
    g = grid("base_occ%.2f_s%d")
    rho, srch, seeds_rho, seeds_srch = [], [], [], []
    rows = []
    for o in OCC_LEVELS:
        rr = [x["curb_occ"] for x in g[o]]
        ss = [x["search_mean"] for x in g[o]]
        rows.append(dict(occ_index=o, n_seeds=len(rr),
                         curb_occ=ci(rr), search_mean=ci(ss),
                         search_med=ci([x["search_med"] for x in g[o]]),
                         search_p90=ci([x["search_p90"] for x in g[o]]),
                         tot_occ=ci([x["tot_occ"] for x in g[o]]),
                         never=ci([x["never_share"] for x in g[o]])))
        rho.append(np.mean(rr))
        srch.append(np.mean(ss))
        seeds_rho += rr
        seeds_srch += ss
    rho = np.array(rho)
    srch = np.array(srch)
    X = np.array(seeds_rho)
    Y = np.array(seeds_srch)

    # divergent fit  T = a/(1-rho) + b     (fit on all seed-level points)
    def f_div(x, a, b):
        return a / np.maximum(1e-3, (1.0 - x)) + b

    pd_, _ = optimize.curve_fit(f_div, X, Y, p0=[5.0, 0.0], maxfev=20000)
    res_d = Y - f_div(X, *pd_)
    # linear alternative
    sl, ic_, rv, pv, se = stats.linregress(X, Y)
    res_l = Y - (sl * X + ic_)

    def r2(res):
        return 1 - np.sum(res ** 2) / np.sum((Y - Y.mean()) ** 2)

    def aic(res, k):
        n = len(res)
        return n * math.log(np.sum(res ** 2) / n) + 2 * k

    # a generalised power form T = a/(1-rho)^g + b : is the exponent really 1?
    def f_pow(x, a, g, b):
        return a / np.maximum(1e-3, (1.0 - x)) ** g + b
    try:
        pp_, cov = optimize.curve_fit(f_pow, X, Y, p0=[5.0, 1.0, 0.0], maxfev=40000)
        gse = float(np.sqrt(np.diag(cov))[1])
    except Exception:
        pp_, gse = [np.nan] * 3, np.nan
    res_p = Y - f_pow(X, *pp_) if pp_[0] == pp_[0] else res_l

    def knees(xx, yy):
        """Three scale-free knee definitions on a fitted a/(1-rho)+b curve."""
        try:
            pf, _ = optimize.curve_fit(f_div, xx, yy, p0=[5.0, 0.0], maxfev=20000)
        except Exception:
            return dict(slope4x=np.nan, doubling=np.nan, elbow=np.nan)
        g = np.linspace(0.55, 0.985, 4000)
        fy = f_div(g, *pf)
        dy = np.gradient(fy, g)
        s60 = float(np.interp(0.60, g, dy))
        k4 = float(g[np.argmax(dy > 4 * s60)]) if np.any(dy > 4 * s60) else np.nan
        y60 = float(np.interp(0.60, g, fy))
        kd = float(g[np.argmax(fy > 2 * y60)]) if np.any(fy > 2 * y60) else np.nan
        # normalised-elbow: max curvature after rescaling both axes to [0,1]
        lo, hi = xx.min(), xx.max()
        gg = np.linspace(lo, hi, 4000)
        yy2 = f_div(gg, *pf)
        xn = (gg - lo) / (hi - lo)
        yn = (yy2 - yy2.min()) / (yy2.max() - yy2.min())
        d1 = np.gradient(yn, xn)
        d2 = np.gradient(d1, xn)
        curv = np.abs(d2) / (1 + d1 ** 2) ** 1.5
        ke = float(gg[int(np.argmax(curv))])
        return dict(slope4x=k4, doubling=kd, elbow=ke)

    K = knees(X, Y)
    knee = K["slope4x"]
    knee_curv = K["elbow"]
    # per-seed refit -> CI on each knee definition
    per_seed = {"slope4x": [], "doubling": [], "elbow": []}
    for sd in SEEDS:
        xs_ = np.array([S("base_occ%.2f_s%d" % (o, sd))["curb_occ"] for o in OCC_LEVELS])
        ys_ = np.array([S("base_occ%.2f_s%d" % (o, sd))["search_mean"] for o in OCC_LEVELS])
        kk = knees(xs_, ys_)
        for k2 in per_seed:
            per_seed[k2].append(kk[k2])
    knee_ci = {k2: ci(v) for k2, v in per_seed.items()}

    OUT["H1"] = dict(
        rows=rows,
        fit_divergent=dict(a=float(pd_[0]), b=float(pd_[1]), r2=float(r2(res_d)),
                           aic=float(aic(res_d, 2))),
        fit_linear=dict(slope=float(sl), intercept=float(ic_), r2=float(r2(res_l)),
                        aic=float(aic(res_l, 2)), p=float(pv)),
        fit_power=dict(a=float(pp_[0]), gamma=float(pp_[1]), gamma_se=gse,
                       b=float(pp_[2]), r2=float(r2(res_p)), aic=float(aic(res_p, 3))),
        knee_slope4x=knee, knee_normalised_elbow=knee_curv,
        knee_slope4x_caveat=('DEGENERATE: for T=a/(1-rho)+b the slope ratio is '
                             '((1-0.6)/(1-rho))^2, so the 4x point is analytically rho=0.80 '
                             'regardless of the data. Reported for completeness only; the '
                             'doubling and normalised-elbow definitions carry the information.'),
        knee_doubling=K['doubling'], knee_ci_across_seeds=knee_ci,
        knee_definitions=dict(
            slope4x='rho at which the fitted curve slope first exceeds 4x its slope at rho=0.60',
            doubling='rho at which fitted mean search time first exceeds 2x its value at rho=0.60',
            normalised_elbow='max-curvature point after rescaling both axes to [0,1] over the observed rho range'),
        delta_aic_linear_minus_divergent=float(aic(res_l, 2) - aic(res_d, 2)),
        observed_rho_range=[float(X.min()), float(X.max())],
    )

    # ---- figure: search time vs curb occupancy with fits ------------------
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for o in OCC_LEVELS:
        ax[0].scatter([x["curb_occ"] for x in g[o]], [x["search_mean"] for x in g[o]],
                      s=14, c="#4C78A8", alpha=.65,
                      label="per-seed" if o == OCC_LEVELS[0] else None)
    m, lo, hi = zip(*[r["search_mean"] for r in rows])
    mo = [r["curb_occ"][0] for r in rows]
    ax[0].errorbar(mo, m, yerr=[np.array(m) - np.array(lo), np.array(hi) - np.array(m)],
                   fmt="o-", c="#111", lw=1.4, ms=5, capsize=3, label="mean (95% CI)")
    gx = np.linspace(min(mo) - .02, max(mo) + .02, 300)
    ax[0].plot(gx, f_div(gx, *pd_), "--", c="#E45756",
               label=r"$a/(1-\rho)+b$  $R^2$=%.3f" % r2(res_d))
    ax[0].plot(gx, sl * gx + ic_, ":", c="#54A24B", label="linear  $R^2$=%.3f" % r2(res_l))
    ax[0].axvline(knee, c="#B279A2", lw=1, ls="-.", label="knee (slope 4x) %.3f" % knee)
    ax[0].axvline(0.85, c="#999", lw=1, ls="-", label="canonical 85%")
    ax[0].set_xlabel("mean curb occupancy $\\rho$"), ax[0].set_ylabel("mean search time (s)")
    ax[0].set_title("H1: search time vs curb occupancy"), ax[0].legend(fontsize=7)

    ax[1].plot(mo, [r["search_med"][0] for r in rows], "o-", label="median")
    ax[1].plot(mo, [r["search_mean"][0] for r in rows], "s-", label="mean")
    ax[1].plot(mo, [r["search_p90"][0] for r in rows], "^-", label="p90")
    ax[1].set_xlabel("mean curb occupancy $\\rho$"), ax[1].set_ylabel("search time (s)")
    ax[1].set_title("search-time distribution shifts"), ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H1_search_vs_occupancy.png"), dpi=140)
    plt.close(fig)

    # ---- figure: stacked VMT/VHT decomposition ---------------------------
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    keys = [("vmt_app", "parker APPROACH"), ("vmt_srch", "parker SEARCH (cruising)"),
            ("vmt_egr", "parker EGRESS"), ("ini_vmt", "turnover departures"),
            ("thr_vmt", "THROUGH traffic")]
    bottom = np.zeros(len(OCC_LEVELS))
    xs = [np.mean([x["curb_occ"] for x in g[o]]) for o in OCC_LEVELS]
    for k, lab in keys:
        v = np.array([np.mean([x[k] for x in g[o]]) / 1000.0 for o in OCC_LEVELS])
        ax[0].bar(range(len(xs)), v, bottom=bottom, label=lab, width=.7)
        bottom += v
    ax[0].set_xticks(range(len(xs)))
    ax[0].set_xticklabels(["%.2f" % x for x in xs], rotation=45, fontsize=7)
    ax[0].set_xlabel("mean curb occupancy"), ax[0].set_ylabel("VMT (veh-km)")
    ax[0].set_title("VMT decomposition"), ax[0].legend(fontsize=7)

    keysh = [("vht_app", "parker APPROACH"), ("vht_srch", "parker SEARCH (cruising)"),
             ("vht_egr", "parker EGRESS"), ("ini_vht", "turnover departures"),
             ("thr_vht", "THROUGH traffic")]
    bottom = np.zeros(len(OCC_LEVELS))
    for k, lab in keysh:
        v = np.array([np.mean([x[k] for x in g[o]]) / 3600.0 for o in OCC_LEVELS])
        ax[1].bar(range(len(xs)), v, bottom=bottom, label=lab, width=.7)
        bottom += v
    ax[1].set_xticks(range(len(xs)))
    ax[1].set_xticklabels(["%.2f" % x for x in xs], rotation=45, fontsize=7)
    ax[1].set_xlabel("mean curb occupancy"), ax[1].set_ylabel("VHT (veh-h)")
    ax[1].set_title("VHT decomposition"), ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H1_vmt_vht_decomposition.png"), dpi=140)
    plt.close(fig)

    OUT["H1"]["cruising_share_note"] = (
        "vmt_share / vht_share are the SEARCH phase as a fraction of ALL vehicle-miles / "
        "vehicle-hours run anywhere on the network by any class. "
        "cruise_share_of_searchzone_vmt is search VMT divided by (search VMT + through-traffic "
        "VMT measured inside the search zone); it EXCLUDES parkers' egress VMT and turnover "
        "vehicles' VMT inside the zone, which are not tracked per-zone, so it is an upper "
        "bound on cruising's share of in-zone traffic.")
    OUT["H1"]["cruising_share"] = [
        dict(curb_occ=float(np.mean([x["curb_occ"] for x in g[o]])),
             vmt_share=ci([x["srch_vmt_share"] for x in g[o]]),
             vht_share=ci([x["srch_vht_share"] for x in g[o]]),
             cruise_share_of_searchzone_vmt=ci([x["core_vmt_srch_share"] for x in g[o]]))
        for o in OCC_LEVELS]

    # ---- figure: per-lot occupancy panel ----------------------------------
    r = load("base_occ1.06_s1")
    lots = sorted(r["lot_cap"], key=lambda k: (r["lot_kind"][k], k))
    M = np.array([[snap[l] / r["lot_cap"][l] for l in lots] for _, snap in r["occupancy"]])
    tt = [t for t, _ in r["occupancy"]]
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(M.T, aspect="auto", origin="lower", vmin=0, vmax=1, cmap="magma",
                   extent=[tt[0], tt[-1], -.5, len(lots) - .5])
    ax.set_yticks(range(len(lots)))
    ax.set_yticklabels(lots, fontsize=6)
    ax.set_xlabel("time (s)"), ax.set_title("Per-lot occupancy ratio, base arm occ=1.06 seed 1")
    fig.colorbar(im, label="occupancy / capacity")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H1_lot_occupancy_heatmap.png"), dpi=140)
    plt.close(fig)
    return g


def perf_by_class():
    """Task item (3): delay / travel time / throughput reported SEPARATELY for
    parkers and through traffic across the occupancy sweep."""
    rows = []
    for o in OCC_LEVELS:
        pk_tt, pk_dly, th_tt, th_dly, th_n, pk_n = [], [], [], [], [], []
        for sd in SEEDS:
            r = load("base_occ%.2f_s%d" % (o, sd))
            if not r:
                continue
            ti = r["tripinfo"]
            th = [x for x in r["through"]]
            th_tt.append(np.mean([ti[x["vid"]]["duration"] for x in th if x["vid"] in ti]))
            th_dly.append(np.mean([x["vht"] - x["vmt"] / VFREE for x in th]))
            th_n.append(sum(1 for x in th if x["vid"] in ti))
            P = [p for p in r["parkers"] if p["t_park"] is not None
                 and WIN[0] <= p["t_park"] <= WIN[1]]
            pk_tt.append(np.mean([p["t_park"] - p["t_depart"] for p in P]))
            pk_dly.append(np.mean([(p["vht_app"] + p["vht_srch"]) -
                                   (p["vmt_app"] + p["vmt_srch"]) / VFREE for p in P]))
            pk_n.append(len(P))
        rows.append(dict(occ_index=o,
                         curb_occ=ci([S("base_occ%.2f_s%d" % (o, sd))["curb_occ"] for sd in SEEDS]),
                         parker_origin_to_park_s=ci(pk_tt), parker_delay_s=ci(pk_dly),
                         parker_walk_s=ci([S("base_occ%.2f_s%d" % (o, sd))["walk_mean"] for sd in SEEDS]),
                         through_traveltime_s=ci(th_tt), through_delay_s=ci(th_dly),
                         through_completed=ci(th_n), parkers_served_in_window=ci(pk_n)))
    OUT["perf_by_class"] = dict(
        rows=rows,
        note=("through_traveltime_s comes from SUMO's own tripinfo `duration` (independent of the "
              "TraCI accumulators); through_delay_s and parker_delay_s are VHT - VMT/11.11 from the "
              "TraCI per-step accumulation. Parker travel time is origin -> parking manoeuvre start "
              "(tripinfo `duration` for a parker would include its parked dwell)."))


# ============================ H2 ============================================ #
def h2():
    rows = []
    for o in OCC_LEVELS:
        ext, priv, ratio, marg = [], [], [], []
        for s in SEEDS:
            a = load("base_occ%.2f_s%d" % (o, s))
            b = load("nosrch_occ%.2f_s%d" % (o, s))
            if not a or not b:
                continue
            cohort = set(p["vid"] for p in b["parkers"] if p["nosearch"])
            sa, sb = summarize(a), summarize(b)

            def others_delay(r, coh):
                d = 0.0
                for p in r["parkers"]:
                    if p["vid"] in coh:
                        continue
                    d += (p["vht_app"] + p["vht_srch"] + p["vht_egr"]) - \
                         (p["vmt_app"] + p["vmt_srch"] + p["vmt_egr"]) / VFREE
                for x in r["through"]:
                    d += x["vht"] - x["vmt"] / VFREE
                for v in r.get("initveh", {}).values():
                    d += v[1] - v[0] / VFREE
                return d

            def cohort_search_delay(r, coh):
                d, vm = 0.0, 0.0
                for p in r["parkers"]:
                    if p["vid"] in coh:
                        d += p["vht_srch"] - p["vmt_srch"] / VFREE
                        vm += p["vht_srch"]
                return d, vm

            e = others_delay(a, cohort) - others_delay(b, cohort)
            pv, cruise_vs = cohort_search_delay(a, cohort)
            ext.append(e)
            priv.append(pv)
            ratio.append(e / pv if pv > 0 else np.nan)
            marg.append(e / (cruise_vs / 60.0) if cruise_vs > 0 else np.nan)
        rows.append(dict(occ_index=o,
                         curb_occ=ci([S("base_occ%.2f_s%d" % (o, s))["curb_occ"] for s in SEEDS]),
                         external_delay_h=ci([x / 3600 for x in ext]),
                         private_search_delay_h=ci([x / 3600 for x in priv]),
                         ratio_ext_priv=ci(ratio),
                         marginal_ext_s_per_cruising_veh_min=ci(marg)))
    OUT["H2"] = dict(rows=rows, cohort_share=0.25,
                     method=("controlled removal: a fixed 25% CRN-matched cohort of parkers is "
                             "removed from the network at the instant it would enter the search "
                             "zone (identical origin, destination-lot and departure time; the "
                             "APPROACH phase is therefore identical in both arms). The difference "
                             "in total delay to ALL OTHER road users (through traffic, other "
                             "parkers, turnover departures) is the cohort's parking externality; "
                             "its own search-phase delay is the private cost."))

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    x = [r["curb_occ"][0] for r in rows]
    for key, lab, c in (("external_delay_h", "external delay on others", "#E45756"),
                        ("private_search_delay_h", "cohort's own search delay", "#4C78A8")):
        m = [r[key][0] for r in rows]
        lo = [r[key][1] for r in rows]
        hi = [r[key][2] for r in rows]
        ax[0].errorbar(x, m, yerr=[np.array(m) - lo, np.array(hi) - m], fmt="o-", c=c,
                       capsize=3, label=lab)
    ax[0].set_xlabel("mean curb occupancy"), ax[0].set_ylabel("veh-hours")
    ax[0].legend(fontsize=8), ax[0].set_title("H2: external vs private cost of cruising")
    m = [r["ratio_ext_priv"][0] for r in rows]
    lo = [r["ratio_ext_priv"][1] for r in rows]
    hi = [r["ratio_ext_priv"][2] for r in rows]
    ax[1].errorbar(x, m, yerr=[np.array(m) - lo, np.array(hi) - m], fmt="s-", c="#54A24B", capsize=3)
    ax[1].axhline(1.0, c="#999", ls="--", label="external = private")
    ax[1].set_xlabel("mean curb occupancy"), ax[1].set_ylabel("external : private")
    ax[1].legend(fontsize=8), ax[1].set_title("externality ratio")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H2_externality_ratio.png"), dpi=140)
    plt.close(fig)


# ============================ H3 ============================================ #
def h3():
    res = {}
    for o in INFO_OCC:
        arms = {"0.00_none": ["base_occ%.2f_s%d" % (o, s) for s in SEEDS],
                "native_visible": ["visall_occ%.2f_s%d" % (o, s) for s in SEEDS]}
        for pen in (0.25, 0.50, 0.75, 1.0):
            arms["naive_%.2f" % pen] = ["infoN_p%.2f_occ%.2f_s%d" % (pen, o, s) for s in SEEDS]
        for pen in (0.25, 1.0):
            arms["reserve_%.2f" % pen] = ["infoR_p%.2f_occ%.2f_s%d" % (pen, o, s) for s in SEEDS]
        for pen in (0.25, 1.0):
            arms["reserve_walk_%.2f" % pen] = ["infoW_p%.2f_occ%.2f_s%d" % (pen, o, s) for s in SEEDS]
        block = {}
        base = [S(n) for n in arms["0.00_none"]]
        for k, names in arms.items():
            xs = [S(n) for n in names if S(n)]
            if not xs:
                continue
            block[k] = dict(
                search_mean=ci([x["search_mean"] for x in xs]),
                curb_occ=ci([x["curb_occ"] for x in xs]),
                gencost=ci([x["gencost_mean"] for x in xs]),
                srch_vmt_share=ci([x["srch_vmt_share"] for x in xs]),
                walk_mean=ci([x["walk_mean"] for x in xs]),
                approach_mean=ci([x["approach_mean"] for x in xs]),
                thr_delay=ci([x["thr_delay_per_veh"] for x in xs]),
                vs_none_search=paired([x["search_mean"] for x in xs],
                                      [b["search_mean"] for b in base]))
        # informed vs uninformed subgroup split within each partial-penetration arm
        sub = {}
        for pen in (0.25, 0.50, 0.75):
            for mode, tag in (("naive", "infoN"), ("reserve", "infoR"),
                              ("reserve_walk", "infoW")):
                if mode != "naive" and pen != 0.25:
                    continue
                inf_, un_ = [], []
                for s in SEEDS:
                    r = load("%s_p%.2f_occ%.2f_s%d" % (tag, pen, o, s))
                    if not r:
                        continue
                    A = [p["search_t"] for p in r["parkers"]
                         if p["informed"] and p["search_t"] is not None
                         and WIN[0] <= (p["t_park"] or 0) <= WIN[1]]
                    B = [p["search_t"] for p in r["parkers"]
                         if not p["informed"] and p["search_t"] is not None
                         and WIN[0] <= (p["t_park"] or 0) <= WIN[1]]
                    if A and B:
                        inf_.append(np.mean(A))
                        un_.append(np.mean(B))
                if inf_:
                    sub["%s_%.2f" % (mode, pen)] = dict(
                        informed=ci(inf_), uninformed=ci(un_), diff=paired(inf_, un_))
        res["occ_%.2f" % o] = dict(arms=block, subgroups=sub,
                                   curb_occ_base=ci([b["curb_occ"] for b in base]))
    OUT["H3"] = res

    fig, ax = plt.subplots(1, len(INFO_OCC), figsize=(4.2 * len(INFO_OCC), 4.2), sharey=False)
    for i, o in enumerate(INFO_OCC):
        b = OUT["H3"]["occ_%.2f" % o]["arms"]
        pens = [0.0, 0.25, 0.5, 0.75, 1.0]
        nm = ["0.00_none", "naive_0.25", "naive_0.50", "naive_0.75", "naive_1.00"]
        m = [b[k]["search_mean"][0] for k in nm]
        lo = [b[k]["search_mean"][1] for k in nm]
        hi = [b[k]["search_mean"][2] for k in nm]
        ax[i].errorbar(pens, m, yerr=[np.array(m) - lo, np.array(hi) - m], fmt="o-",
                       capsize=3, label="naive guidance")
        rm = [b["0.00_none"]["search_mean"][0], b["reserve_0.25"]["search_mean"][0],
              b["reserve_1.00"]["search_mean"][0]]
        ax[i].plot([0, 0.25, 1.0], rm, "s--", c="#54A24B", label="reservation-aware")
        ax[i].axhline(b["native_visible"]["search_mean"][0], c="#E45756", ls=":",
                      label="native visible=true")
        ax[i].set_title("curb occ %.2f" % OUT["H3"]["occ_%.2f" % o]["curb_occ_base"][0])
        ax[i].set_xlabel("informed share"), ax[i].set_ylabel("mean search time (s)")
        ax[i].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H3_information_penetration.png"), dpi=140)
    plt.close(fig)


# ============================ H4 ============================================ #
H4_ARMS = ["flat_cheap", "curb_eq_gar", "perf_080", "perf_085", "perf_090", "perf_095",
           "supply_p12", "supply_p24", "guide_naive", "guide_resv", "guide_walk",
           "perf085_guidewalk"]


def h4():
    rows = {}
    per_q = {}
    for arm in H4_ARMS:
        xs = [S("h4_%s_s%d" % (arm, s)) for s in SEEDS]
        xs = [x for x in xs if x]
        if not xs:
            continue
        rows[arm] = dict(
            n=len(xs),
            curb_occ=ci([x["curb_occ"] for x in xs]),
            search_mean=ci([x["search_mean"] for x in xs]),
            gencost=ci([x["gencost_mean"] for x in xs]),
            gc_invehicle=ci([x["gc_invehicle"] for x in xs]),
            gc_walk=ci([x["gc_walk"] for x in xs]),
            gc_fee=ci([x["gc_fee"] for x in xs]),
            cruising_vmt_km=ci([x["vmt_srch"] / 1000 for x in xs]),
            cruise_vmt_share=ci([x["srch_vmt_share"] for x in xs]),
            thr_delay_per_veh=ci([x["thr_delay_per_veh"] for x in xs]),
            balk_rate=ci([x["n_balk"] / x["n_parkers"] for x in xs]),
            never_rate=ci([x["never_share"] for x in xs]),
            walk_mean=ci([x["walk_mean"] for x in xs]),
            final_fee=ci([x["final_fee"] for x in xs]),
            teleports=ci([x["teleports"] for x in xs]),
        )
        # ---- per-VOT-quartile equity -------------------------------------
        q = defaultdict(list)
        for s in SEEDS:
            r = load("h4_%s_s%d" % (arm, s))
            if not r:
                continue
            P = [p for p in r["parkers"] if p["gencost"] is not None]
            if not P:
                continue
            vots = np.array([p["vot"] for p in P])
            cuts = np.percentile(vots, [25, 50, 75])
            for p in P:
                k = int(np.searchsorted(cuts, p["vot"]))
                q[k].append(p)
        per_q[arm] = {}
        for k in range(4):
            ps = q.get(k, [])
            if not ps:
                continue
            per_q[arm]["Q%d" % (k + 1)] = dict(
                n=len(ps),
                gencost=float(np.mean([p["gencost"] for p in ps])),
                fee=float(np.mean([p["fee"] for p in ps])),
                fee_share=float(np.mean([p["fee"] / p["gencost"] for p in ps if p["gencost"] > 0])),
                search=float(np.mean([p["search_t"] for p in ps if p["search_t"] is not None])),
                garage_share=float(np.mean([1.0 if p["kind"] == "garage" else 0.0 for p in ps])),
                vot=float(np.mean([p["vot"] for p in ps])))
    # paired contrasts against the flat underpriced curb
    contrasts = {}
    for arm in H4_ARMS:
        if arm == "flat_cheap":
            continue
        for key in ("gencost_mean", "vmt_srch", "search_mean", "thr_delay_per_veh"):
            a = [S("h4_%s_s%d" % (arm, s))[key] for s in SEEDS if S("h4_%s_s%d" % (arm, s))]
            b = [S("h4_flat_cheap_s%d" % s)[key] for s in SEEDS if S("h4_flat_cheap_s%d" % s)]
            contrasts.setdefault(arm, {})[key] = paired(a, b)
    OUT["H4"] = dict(arms=rows, vot_quartiles=per_q, contrasts_vs_flat_cheap=contrasts)

    labels = H4_ARMS
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
    for j, (key, title, unit) in enumerate([
            ("gencost", "door-to-door generalized cost", "$/parker"),
            ("cruising_vmt_km", "cruising (search) VMT", "veh-km"),
            ("thr_delay_per_veh", "through-traffic delay", "s/veh")]):
        m = [rows[a][key][0] for a in labels]
        lo = [rows[a][key][1] for a in labels]
        hi = [rows[a][key][2] for a in labels]
        ax[j].barh(range(len(labels)), m, xerr=[np.array(m) - lo, np.array(hi) - m],
                   color="#4C78A8", capsize=3)
        ax[j].set_yticks(range(len(labels)))
        ax[j].set_yticklabels(labels, fontsize=8)
        ax[j].set_title(title, fontsize=10), ax[j].set_xlabel(unit)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H4_policy_comparison.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.4))
    w = 0.8 / len(labels)
    for i, a in enumerate(labels):
        v = [per_q[a].get("Q%d" % (k + 1), {}).get("gencost", np.nan) for k in range(4)]
        ax.bar(np.arange(4) + i * w, v, width=w, label=a)
    ax.set_xticks(np.arange(4) + 0.4)
    ax.set_xticklabels(["Q1 (low VOT)", "Q2", "Q3", "Q4 (high VOT)"])
    ax.set_ylabel("mean door-to-door generalized cost ($)")
    ax.legend(fontsize=7, ncol=2), ax.set_title("H4 equity: generalized cost by VOT quartile")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H4_equity_by_vot_quartile.png"), dpi=140)
    plt.close(fig)


# ============================ H5 ============================================ #
def h5():
    res = {}
    for sup in ("baseline", "curb_high", "curb_low"):
        on = [S("h5_%s_man1_s%d" % (sup, s)) for s in SEEDS]
        off = [S("h5_%s_man0_s%d" % (sup, s)) for s in SEEDS]
        on = [x for x in on if x]
        off = [x for x in off if x]
        if not on or not off:
            continue

        def curb_events(tag, man):
            v = []
            for s in SEEDS:
                r = load("h5_%s_man%d_s%d" % (tag, man, s))
                if r:
                    v.append(sum(1 for p in r["parkers"] if p["kind"] == "curb"))
            return v
        ce = curb_events(sup, 1)
        res[sup] = dict(
            curb_capacity_share=float(np.mean([x["cfg"] and 1 for x in on])) * 0 + {
                "baseline": 0.72, "curb_high": 0.96, "curb_low": 0.30}[sup],
            curb_park_events=ci(ce),
            search_on=ci([x["search_mean"] for x in on]),
            search_off=ci([x["search_mean"] for x in off]),
            thr_delay_on=ci([x["thr_delay_per_veh"] for x in on]),
            thr_delay_off=ci([x["thr_delay_per_veh"] for x in off]),
            d_thr_delay=paired([x["thr_delay_per_veh"] for x in on],
                               [x["thr_delay_per_veh"] for x in off]),
            d_search=paired([x["search_mean"] for x in on], [x["search_mean"] for x in off]),
            d_total_delay_h=paired([(x["thr_delay_total"] + x["par_delay_total"] +
                                     x["ini_delay_total"]) / 3600 for x in on],
                                   [(x["thr_delay_total"] + x["par_delay_total"] +
                                     x["ini_delay_total"]) / 3600 for x in off]),
            d_standing_curb_veh_s=paired([x["standing"].get("curb_edge_veh_s", np.nan) for x in on],
                                         [x["standing"].get("curb_edge_veh_s", np.nan) for x in off]),
            gencost_on=ci([x["gencost_mean"] for x in on]),
            gencost_off=ci([x["gencost_mean"] for x in off]),
            curb_occ_on=ci([x["curb_occ"] for x in on]),
            total_delay_off_h=ci([(x["thr_delay_total"] + x["par_delay_total"] +
                                   x["ini_delay_total"]) / 3600 for x in off]),
            search_delay_off_h=ci([x["srch_delay_total"] / 3600 for x in off]),
        )
        if res[sup]["curb_park_events"][0]:
            res[sup]["maneuver_delay_s_per_curb_park"] = (
                res[sup]["d_total_delay_h"]["mean"] * 3600 / res[sup]["curb_park_events"][0])
    OUT["H5"] = res

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    sups = [s for s in ("curb_low", "baseline", "curb_high") if s in res]
    x = np.arange(len(sups))
    m = [res[s]["d_total_delay_h"]["mean"] for s in sups]
    lo = [res[s]["d_total_delay_h"]["lo"] for s in sups]
    hi = [res[s]["d_total_delay_h"]["hi"] for s in sups]
    ax[0].bar(x, m, yerr=[np.array(m) - lo, np.array(hi) - m], capsize=4, color="#E45756")
    ax[0].set_xticks(x)
    ax[0].set_xticklabels(["%s\n(curb share %.2f)" % (s, res[s]["curb_capacity_share"])
                           for s in sups], fontsize=8)
    ax[0].axhline(0, c="#333", lw=.8)
    ax[0].set_ylabel("extra network delay, veh-h")
    ax[0].set_title("H5: delay attributable to the parking MANOEUVRE\n(--parking.maneuver on - off)")
    m = [res[s]["d_search"]["mean"] for s in sups]
    lo = [res[s]["d_search"]["lo"] for s in sups]
    hi = [res[s]["d_search"]["hi"] for s in sups]
    ax[1].bar(x, m, yerr=[np.array(m) - lo, np.array(hi) - m], capsize=4, color="#4C78A8")
    ax[1].set_xticks(x), ax[1].set_xticklabels(sups, fontsize=8)
    ax[1].axhline(0, c="#333", lw=.8)
    ax[1].set_ylabel("change in mean search time (s)")
    ax[1].set_title("manoeuvre's effect on search time")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H5_maneuver_externality.png"), dpi=140)
    plt.close(fig)


# ============================ H6 ============================================ #
def h6():
    levels = OCC_LEVELS + [1.30, 1.50, 1.75]
    rows = []
    for o in levels:
        pre = "base_occ%.2f_s%d" if o in OCC_LEVELS else "h6_occ%.2f_s%d"
        xs = [S(pre % (o, s)) for s in SEEDS]
        xs = [x for x in xs if x]
        if not xs:
            continue
        rows.append(dict(
            occ_index=o, curb_occ=ci([x["curb_occ"] for x in xs]),
            n_parkers=ci([x["n_parkers"] for x in xs]),
            served=ci([x["n_served"] / x["n_parkers"] for x in xs]),
            never_parked=ci([x["n_never"] for x in xs]),
            never_share=ci([x["never_share"] for x in xs]),
            still_searching=ci([x["end_phase"].get("search", 0) for x in xs]),
            still_parked=ci([x["end_phase"].get("parked", 0) for x in xs]),
            still_walking=ci([x["still_walking"] for x in xs]),
            teleports=ci([x["teleports"] for x in xs]),
            search_mean=ci([x["search_mean"] for x in xs]),
            thr_delay_per_veh=ci([x["thr_delay_per_veh"] for x in xs]),
            gencost=ci([x["gencost_mean"] for x in xs]),
            ped_jams=ci([x["ped_jams"] for x in xs]),
            teleport_reasons=_merge_reasons([x["teleport_reasons"] for x in xs]),
        ))
    OUT["H6"] = dict(rows=rows)

    fig, ax = plt.subplots(1, 3, figsize=(14, 4.0))
    x = [r["curb_occ"][0] for r in rows]
    for j, (k, lab) in enumerate([("never_share", "never-parked share of parkers"),
                                  ("search_mean", "mean search time (s)"),
                                  ("thr_delay_per_veh", "through-traffic delay (s/veh)")]):
        m = [r[k][0] for r in rows]
        lo = [r[k][1] for r in rows]
        hi = [r[k][2] for r in rows]
        ax[j].errorbar(x, m, yerr=[np.array(m) - lo, np.array(hi) - m], fmt="o-", capsize=3)
        ax[j].set_xlabel("mean curb occupancy"), ax[j].set_title(lab, fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H6_failure_mode.png"), dpi=140)
    plt.close(fig)


def _merge_reasons(ds):
    out = defaultdict(int)
    for d in ds:
        for k, v in (d or {}).items():
            out[k] += v
    return dict(out)


# ======================= validity / consistency ============================= #
def validity():
    names = all_runs("")
    tot = len(names)
    bad_stopstate, bad_phase, maxdev = 0, 0, 0.0
    tele_by_reason = defaultdict(int)
    tele_share = []
    for n in names:
        x = S(n)
        if not x:
            continue
        if x["cons_stopstate_ok"] == 0:
            bad_stopstate += 1
        if x["cons_phase_ok"] == 0:
            bad_phase += 1
        maxdev = max(maxdev, x["cons_max_abs_dev"] if x["cons_max_abs_dev"] == x["cons_max_abs_dev"] else 0)
        for k, v in (x["teleport_reasons"] or {}).items():
            tele_by_reason[k] += v
        tele_share.append(x["teleports"] / max(1, x["n_parkers"]))

    # teleport-exclusion re-test of H1 (matched common cohort across occupancy)
    h1_excl = []
    for o in OCC_LEVELS:
        a, b = [], []
        for s in SEEDS:
            r = load("base_occ%.2f_s%d" % (o, s))
            if not r:
                continue
            tel = set(r["teleports"])
            w = [p for p in r["parkers"] if p["search_t"] is not None
                 and WIN[0] <= p["t_park"] <= WIN[1]]
            a.append(np.mean([p["search_t"] for p in w]))
            wt = [p for p in w if p["vid"] not in tel]
            b.append(np.mean([p["search_t"] for p in wt]) if wt else np.nan)
        h1_excl.append(dict(occ_index=o, all_trips=ci(a), teleport_free=ci(b),
                            paired_diff=paired(a, b)))

    # parkingArea geometry verification straight out of SUMO (TraCI-read at t=0)
    r = load("base_occ1.06_s1")
    import build_parking as bp
    net = bp.load_net()
    lots = bp.build_supply(net, "baseline")
    geom_problems = []
    for l in lots:
        g = r["pa_geom"][l["id"]]
        if g["lane"] != l["lane"]:
            geom_problems.append("%s lane %s != %s" % (l["id"], g["lane"], l["lane"]))
        if abs(g["start"] - l["startPos"]) > 0.01 or abs(g["end"] - l["endPos"]) > 0.01:
            geom_problems.append("%s offsets (%.2f,%.2f) != (%.2f,%.2f)"
                                 % (l["id"], g["start"], g["end"], l["startPos"], l["endPos"]))
        lane_len = net.getLane(l["lane"]).getLength()
        if not (0 <= g["start"] < g["end"] <= lane_len):
            geom_problems.append("%s outside lane length %.2f" % (l["id"], lane_len))

    # capacity verification: max observed occupancy per lot in the most saturated arm
    rr = load("h6_occ1.75_s1")
    maxocc = defaultdict(int)
    for _, snap in rr["occupancy"]:
        for k, v in snap.items():
            maxocc[k] = max(maxocc[k], v)
    cap_check = {k: dict(intended=rr["lot_cap"][k], max_observed=maxocc[k]) for k in rr["lot_cap"]}
    over = [k for k, v in cap_check.items() if v["max_observed"] > v["intended"]]
    curb_reached = [k for k, v in cap_check.items()
                    if rr["lot_kind"][k] == "curb" and v["max_observed"] == v["intended"]]

    OUT["validity"] = dict(
        n_runs=tot,
        consistency_stopstate_violations=bad_stopstate,
        consistency_phase_violations=bad_phase,
        consistency_max_abs_deviation=maxdev,
        teleports_by_reason=dict(tele_by_reason),
        teleport_share_mean=float(np.mean(tele_share)),
        teleport_share_max=float(np.max(tele_share)),
        invalid_speed_samples_total=int(sum(x["standing"].get("invalid_speed_samples", 0)
                                            for x in (S(n) for n in names) if x)),
        h1_teleport_exclusion=h1_excl,
        parkingarea_geometry_problems=geom_problems,
        capacity_check_oversaturated_arm=dict(
            n_lots=len(cap_check), lots_exceeding_capacity=over,
            curb_lots_reaching_exactly_capacity=len(curb_reached),
            total_intended=sum(v["intended"] for v in cap_check.values()),
            total_max_observed=sum(v["max_observed"] for v in cap_check.values())),
    )


# ======================= completion accounting ============================== #
def accounting():
    rows = []
    for tag, names in [("base occ sweep", ["base_occ%.2f_s%d" % (o, s)
                                           for o in OCC_LEVELS for s in SEEDS]),
                       ("H6 oversaturated", ["h6_occ%.2f_s%d" % (o, s)
                                             for o in (1.30, 1.50, 1.75) for s in SEEDS]),
                       ("H4 policies", ["h4_%s_s%d" % (a, s) for a in H4_ARMS for s in SEEDS])]:
        xs = [S(n) for n in names if S(n)]
        agg = defaultdict(float)
        for x in xs:
            agg["parkers"] += x["n_parkers"]
            agg["served"] += x["n_served"]
            agg["balked"] += x["n_balk"]
            agg["never_parked"] += x["n_never"]
            for k, v in x["end_phase"].items():
                agg["end_" + k] += v
            agg["still_walking"] += x["still_walking"]
            agg["teleports"] += x["teleports"]
        rows.append(dict(group=tag, n_runs=len(xs), **{k: int(v) for k, v in agg.items()}))
    OUT["accounting"] = rows


def main():
    h1()
    perf_by_class()
    h2()
    h3()
    h4()
    h5()
    h6()
    validity()
    accounting()
    with open(os.path.join(DATA_DIR, "analysis.json"), "w") as f:
        json.dump(OUT, f, indent=2, default=float)
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else len(v))
                      for k, v in OUT.items()}, indent=2))


if __name__ == "__main__":
    main()
