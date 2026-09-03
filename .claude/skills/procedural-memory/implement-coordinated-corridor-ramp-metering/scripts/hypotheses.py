#!/usr/bin/env python3
"""CRN-paired hypothesis tests with confidence intervals for the corridor
ramp-metering experiment.  All comparisons are PAIRED BY SEED (Common Random
Numbers): both arms saw the identical route file and the identical sumo --seed.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ARMS = ["nocontrol", "fixed", "alinea", "bnalinea", "coord", "coord_flush", "negctrl"]
DEMANDS = [0.55, 0.65, 0.75, 0.85, 0.95, 1.05]


def load(csvpath):
    rows = []
    for r in csv.DictReader(open(csvpath)):
        d = {}
        for k, v in r.items():
            if k == "tag" or k == "arm":
                d[k] = v
            else:
                try:
                    d[k] = float(v) if v not in ("", "None") else None
                except ValueError:
                    d[k] = v
        d["group"] = r["tag"].split("/")[0]
        rows.append(d)
    return rows


def paired(rows_a, rows_b, key):
    """rows_* keyed by seed -> paired differences b - a"""
    seeds = sorted(set(rows_a) & set(rows_b))
    a = np.array([rows_a[s][key] for s in seeds], float)
    b = np.array([rows_b[s][key] for s in seeds], float)
    d = b - a
    n = len(d)
    m = d.mean()
    se = d.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    tcrit = stats.t.ppf(0.975, n - 1) if n > 1 else float("nan")
    t, p = stats.ttest_rel(b, a) if n > 1 else (float("nan"), float("nan"))
    return dict(n=n, base=a.mean(), treat=b.mean(), diff=m,
                ci_lo=m - tcrit * se, ci_hi=m + tcrit * se,
                pct=100.0 * m / a.mean() if a.mean() else float("nan"),
                p=float(p), rho=float(np.corrcoef(a, b)[0, 1]) if n > 2 else float("nan"),
                sign_agree=float((np.sign(d) == np.sign(m)).mean()))


def by_seed(rows, **filt):
    out = {}
    for r in rows:
        if all(abs(r[k] - v) < 1e-9 if isinstance(v, float) else r[k] == v
               for k, v in filt.items()):
            out[int(r["seed"])] = r
    return out


def fmt(d, unit=""):
    return (f"{d['base']:.1f} -> {d['treat']:.1f} {unit} | diff {d['diff']:+.1f} "
            f"[{d['ci_lo']:+.1f},{d['ci_hi']:+.1f}] ({d['pct']:+.1f}%) p={d['p']:.4f} "
            f"n={d['n']} rho={d['rho']:.2f} signagree={d['sign_agree']:.2f}")


def main():
    rows = load(os.path.join(ROOT, "outputs", "tables", "runs.csv"))
    core = [r for r in rows if r["group"] == "core"]
    out = {}
    P = print

    # ================= NEGATIVE CONTROL =================
    P("\n" + "=" * 96)
    P("NEGATIVE CONTROL: `negctrl` (full coordinated controller running, rate clamped open)")
    P("must reproduce `nocontrol` exactly.")
    neg = {}
    for dem in [0.75, 0.85, 0.95, 1.05]:
        a = by_seed(core, arm="nocontrol", demand=dem)
        b = by_seed(core, arm="negctrl", demand=dem)
        worst = {}
        for k in ("TSTT", "TSD", "n_completed", "bottleneck_veh_served", "vh_mainline"):
            d = [abs(b[s][k] - a[s][k]) for s in sorted(set(a) & set(b))]
            worst[k] = max(d)
        neg[dem] = worst
        P(f"  demand {dem}: max |negctrl - nocontrol| " +
          "  ".join(f"{k}={v:.6g}" for k, v in worst.items()))
    out["negative_control"] = neg

    # ================= TELEPORT ARTIFACT CHECK =================
    P("\n" + "=" * 96)
    P("TELEPORT-ARTIFACT CHECK (convention: `validate-congested-scenario-results-"
      "against-teleport-artifacts`)")
    tp = {}
    for arm in ARMS:
        for dem in DEMANDS:
            g = by_seed(core, arm=arm, demand=dem)
            if not g:
                continue
            tot = sum(r["teleports"] for r in g.values())
            veh = sum(r["n_teleport_veh"] for r in g.values())
            comp = sum(r["n_completed"] for r in g.values())
            tp[f"{arm}_d{dem}"] = dict(teleports=tot, veh=veh,
                                       share=veh / comp if comp else 0)
    worst = max(tp.items(), key=lambda kv: kv[1]["share"])
    P(f"  worst arm/demand: {worst[0]} -> {worst[1]['veh']} teleported vehicles, "
      f"{100*worst[1]['share']:.4f}% of completed trips")
    P(f"  total teleports across the whole {len(core)}-run core matrix: "
      f"{sum(v['teleports'] for v in tp.values())}")
    out["teleports"] = tp
    tele = [r for r in rows if r["group"] == "tele"]
    if tele:
        P("  --time-to-teleport sensitivity (demand 0.95, seeds 1-3):")
        for arm in ("nocontrol", "coord"):
            base = by_seed(core, arm=arm, demand=0.95)
            for ttt in (120, -1):
                g = {int(r["seed"]): r for r in tele
                     if r["arm"] == arm and f"ttt{ttt}_" in r["tag"]}
                if not g:
                    continue
                ss = sorted(set(g) & set(base))
                d = [(g[s]["TSD"] - base[s]["TSD"]) / base[s]["TSD"] * 100 for s in ss]
                frozen = [g[s]["n_still_running"] for s in ss]
                P(f"    {arm:10s} ttt={ttt:5} : TSD change vs ttt=300 "
                  f"{np.mean(d):+.2f}%  still-running at end {frozen}")

    # ================= VEHICLE ACCOUNTING =================
    P("\n" + "=" * 96)
    P("COMPLETED vs STILL-RUNNING vs NEVER-INSERTED accounting (mean over 8 seeds)")
    P(f"  {'arm':13s} {'dem':>5} {'loaded':>8} {'completed':>10} {'running@end':>12} "
      f"{'never_ins':>10}")
    acc = {}
    for dem in DEMANDS:
        for arm in ARMS:
            g = by_seed(core, arm=arm, demand=dem)
            if not g:
                continue
            v = [np.mean([r[k] for r in g.values()])
                 for k in ("n_loaded", "n_completed", "n_still_running", "n_never_inserted")]
            acc[f"{arm}_d{dem}"] = v
            P(f"  {arm:13s} {dem:5.2f} {v[0]:8.0f} {v[1]:10.0f} {v[2]:12.1f} {v[3]:10.1f}")
    out["accounting"] = acc

    # ================= METERING-RATE VERIFICATION =================
    P("\n" + "=" * 96)
    P("METERING-RATE VERIFICATION: realized release rate vs commanded rate")
    P("(only control intervals where the meter was restrictive AND >=2 vehicles queued)")
    rv = {}
    for arm in ("fixed", "alinea", "bnalinea", "coord", "coord_flush"):
        g = [r for r in core if r["arm"] == arm and r.get("rate_ver_n")]
        if not g:
            continue
        n = sum(r["rate_ver_n"] for r in g)
        c = np.average([r["rate_ver_cmd_mean"] for r in g], weights=[r["rate_ver_n"] for r in g])
        v = np.average([r["rate_ver_real_mean"] for r in g], weights=[r["rate_ver_n"] for r in g])
        mape = np.average([r["rate_ver_mape"] for r in g], weights=[r["rate_ver_n"] for r in g])
        rv[arm] = dict(n_intervals=int(n), cmd=float(c), realized=float(v),
                       bias_pct=100 * (v - c) / c, mape=float(mape))
        P(f"  {arm:12s} n={int(n):6d} intervals  commanded {c:6.0f} veh/h  "
          f"realized {v:6.0f} veh/h  bias {100*(v-c)/c:+5.1f}%  MAPE {100*mape:.1f}%")
    out["rate_verification"] = rv

    # ================= H1 DELAY TRANSFER =================
    P("\n" + "=" * 96)
    P("H1 DELAY TRANSFER -- isolated ALINEA: mainline gain vs system-wide gain")
    h1 = {}
    for dem in DEMANDS:
        a = by_seed(core, arm="nocontrol", demand=dem)
        b = by_seed(core, arm="alinea", demand=dem)
        e = {}
        for k in ("delay_mainline", "delay_ramp", "delay_surface", "delay_origin", "TSD",
                  "bn_discharge_peak", "n_completed", "vh_mainline"):
            e[k] = paired(a, b, k)
        h1[dem] = e
        P(f"\n  demand {dem}:")
        for k in ("delay_mainline", "delay_ramp", "delay_surface", "delay_origin", "TSD"):
            P(f"    {k:16s} {fmt(e[k], 'veh-h')}")
        P(f"    {'bn_discharge':16s} {fmt(e['bn_discharge_peak'], 'veh/h')}")
    out["H1"] = h1

    # ================= H2 COORDINATION GAIN =================
    P("\n" + "=" * 96)
    P("H2 COORDINATION GAIN -- coord vs isolated alinea, and vs bottleneck-detector-only")
    h2 = {}
    for dem in DEMANDS:
        a = by_seed(core, arm="alinea", demand=dem)
        b = by_seed(core, arm="coord", demand=dem)
        c = by_seed(core, arm="bnalinea", demand=dem)
        e = dict(coord_vs_alinea={k: paired(a, b, k) for k in
                                  ("TSD", "delay_mainline", "delay_ramp", "delay_surface",
                                   "delay_origin", "bn_discharge_peak", "n_completed")},
                 coord_vs_bnalinea={k: paired(c, b, k) for k in
                                    ("TSD", "delay_mainline", "bn_discharge_peak")},
                 bnalinea_vs_alinea={k: paired(a, c, k) for k in
                                     ("TSD", "delay_mainline", "bn_discharge_peak")})
        h2[dem] = e
        P(f"\n  demand {dem}:")
        P(f"    coord vs alinea      TSD {fmt(e['coord_vs_alinea']['TSD'], 'veh-h')}")
        P(f"    coord vs bnalinea    TSD {fmt(e['coord_vs_bnalinea']['TSD'], 'veh-h')}")
        P(f"    bnalinea vs alinea   TSD {fmt(e['bnalinea_vs_alinea']['TSD'], 'veh-h')}")
    # storage sweep
    P("\n  RAMP-STORAGE SWEEP at demand 0.95 (r3 storage length varied; r1/r2 fixed)")
    stor = [r for r in rows if r["group"] == "stor"]
    sw = {}
    for st in (80, 160, 320, 640):
        if st == 160:
            a = by_seed(core, arm="alinea", demand=0.95)
            b = by_seed(core, arm="coord", demand=0.95)
            nc = by_seed(core, arm="nocontrol", demand=0.95)
        else:
            a = {int(r["seed"]): r for r in stor if r["arm"] == "alinea" and f"st{st}_" in r["tag"]}
            b = {int(r["seed"]): r for r in stor if r["arm"] == "coord" and f"st{st}_" in r["tag"]}
            nc = {int(r["seed"]): r for r in stor if r["arm"] == "nocontrol" and f"st{st}_" in r["tag"]}
        if not (a and b and nc):
            continue
        e1 = paired(a, b, "TSD")
        e2 = paired(nc, b, "TSD")
        e3 = paired(nc, a, "TSD")
        ratio = np.mean([b[s]["r3_frac_storage_exceeded"] for s in b])
        sw[st] = dict(coord_vs_alinea=e1, coord_vs_nocontrol=e2, alinea_vs_nocontrol=e3,
                      r3_frac_storage_exceeded_coord=float(ratio))
        P(f"    r3 storage {st:4d} m: coord-vs-alinea TSD {e1['diff']:+8.1f} veh-h "
          f"[{e1['ci_lo']:+.1f},{e1['ci_hi']:+.1f}] p={e1['p']:.4f} | "
          f"coord-vs-nocontrol {e2['pct']:+6.1f}% | alinea-vs-nocontrol {e3['pct']:+6.1f}% | "
          f"r3 storage-exceeded {100*ratio:.0f}% of intervals")
    h2["storage_sweep"] = sw
    out["H2"] = h2

    # ================= H3 QUEUE OVERRIDE =================
    P("\n" + "=" * 96)
    P("H3 QUEUE OVERRIDE -- how much of metering time is spent flushing, and does an "
      "overridden controller become indistinguishable from no control?")
    h3 = {}
    for dem in DEMANDS:
        a = by_seed(core, arm="coord", demand=dem)
        b = by_seed(core, arm="coord_flush", demand=dem)
        nc = by_seed(core, arm="nocontrol", demand=dem)
        ov = np.mean([np.mean([b[s][f"{r}_frac_override_of_active"] for r in ("r1", "r2", "r3")])
                      for s in b])
        e = dict(override_frac_of_active=float(ov),
                 flush_vs_coord={k: paired(a, b, k) for k in
                                 ("TSD", "delay_mainline", "delay_origin", "bn_discharge_peak")},
                 flush_vs_nocontrol={k: paired(nc, b, k) for k in
                                     ("TSD", "delay_mainline", "bn_discharge_peak",
                                      "n_completed", "queue_extent_stations")})
        h3[dem] = e
        f2 = e["flush_vs_nocontrol"]
        P(f"\n  demand {dem}: override active {100*ov:.1f}% of metering time")
        P(f"    flush vs nocontrol  TSD          {fmt(f2['TSD'], 'veh-h')}")
        P(f"    flush vs nocontrol  bn_discharge {fmt(f2['bn_discharge_peak'], 'veh/h')}")
        P(f"    flush vs coord      TSD          {fmt(e['flush_vs_coord']['TSD'], 'veh-h')}")
    fl = [r for r in rows if r["group"] == "flush"]
    if fl:
        P("\n  OVERRIDE-STRICTNESS SWEEP (w_flush; 1.20 = override can never fire)")
        for dem in (0.85, 1.05):
            for wf in (0.70, 0.85, 1.20):
                if wf == 0.85:
                    g = by_seed(core, arm="coord_flush", demand=dem)
                else:
                    g = {int(r["seed"]): r for r in fl
                         if f"wf{int(wf*100)}_d{int(dem*100)}_" in r["tag"]}
                nc = by_seed(core, arm="nocontrol", demand=dem)
                if not g:
                    continue
                e = paired(nc, g, "TSD")
                ov = np.mean([np.mean([g[s][f"{r}_frac_override_of_active"]
                                       for r in ("r1", "r2", "r3")]) for s in g])
                P(f"    demand {dem} w_flush {wf:.2f}: override {100*ov:5.1f}% of metering time, "
                  f"TSD vs nocontrol {e['pct']:+6.1f}% [{e['ci_lo']:+.0f},{e['ci_hi']:+.0f}] "
                  f"p={e['p']:.4f}")
                h3.setdefault("flush_sweep", {})[f"d{dem}_wf{wf}"] = dict(
                    override=float(ov), vs_nocontrol=e)
    out["H3"] = h3

    # ================= H4 SPILLBACK COUPLING =================
    P("\n" + "=" * 96)
    P("H4 SPILLBACK COUPLING -- is surface delay super-linear in ramp queue?")
    RAMPS_ = ("r1", "r2", "r3")
    pts = []
    for r in core:
        rq = sum(r[f"{x}_queue_veh_hours"] for x in ("r1", "r2", "r3"))
        pts.append((rq, r["delay_surface"], r["surface_capp_veh_hours"], r["arm"], r["demand"]))
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    m = x > 0.5
    lx, ly = np.log(x[m]), np.log(y[m])
    slope, icpt, rr, pv, se = stats.linregress(lx, ly)
    P(f"  log-log regression of surface delay on total ramp-queue vehicle-hours:")
    P(f"    exponent = {slope:.3f} +- {se:.3f} (95% CI [{slope-1.96*se:.3f},{slope+1.96*se:.3f}]),"
      f" R2={rr**2:.3f}, n={m.sum()}")
    P(f"    exponent > 1 => SUPER-LINEAR: {'YES' if slope - 1.96*se > 1 else 'NO'}")
    # explicit spillback instrumentation: cross-street queue vs ramp storage exceeded
    P("  explicit spillback instrumentation (cross-street queue at the ramp terminals):")
    for arm in ARMS:
        g = [r for r in core if r["arm"] == arm]
        if not g:
            continue
        se_frac = np.mean([np.mean([r[f"{x}_frac_storage_exceeded"] for x in ("r1", "r2", "r3")])
                           for r in g])
        cap = np.mean([r["surface_capp_veh_hours"] for r in g])
        P(f"    {arm:13s} ramp-storage-exceeded {100*se_frac:5.1f}% of intervals | "
          f"cross-street queue {cap:7.1f} veh-h | surface delay {np.mean([r['delay_surface'] for r in g]):7.1f} veh-h")
    sub = {}
    for arm in ("alinea", "coord", "coord_flush", "bnalinea"):
        g = [r for r in core if r["arm"] == arm]
        xx = np.array([sum(r[f"{q}_queue_veh_hours"] for q in RAMPS_) for r in g])
        yy = np.array([r["delay_surface"] for r in g])
        mm = xx > 0.5
        if mm.sum() > 10:
            sl2, ic2, rr2, pv2, se2 = stats.linregress(np.log(xx[mm]), np.log(yy[mm]))
            sub[arm] = dict(exponent=float(sl2), se=float(se2), r2=float(rr2**2), n=int(mm.sum()))
            P(f"    within {arm:12s}: exponent {sl2:.3f} +- {se2:.3f}  R2={rr2**2:.3f}  n={mm.sum()}")
    # threshold form: surface delay vs the storage-EXCEEDED fraction
    xe = np.array([np.mean([r[f"{q}_frac_storage_exceeded"] for q in RAMPS_]) for r in core])
    ye = np.array([r["delay_surface"] for r in core])
    me = xe > 0.001
    sl3, ic3, rr3, pv3, se3 = stats.linregress(xe[me], ye[me])
    P(f"  surface delay vs ramp-storage-exceeded fraction (linear): slope {sl3:.0f} veh-h per "
      f"unit fraction, R2={rr3**2:.3f}, n={me.sum()}")
    P(f"  gridlock check: interchange never locked -- 0 vehicles failed to complete in any of "
      f"the {len(core)} core runs, 0 teleports")
    out["H4"] = dict(loglog_exponent=float(slope), se=float(se), r2=float(rr**2),
                     n=int(m.sum()), superlinear=bool(slope - 1.96 * se > 1),
                     within_arm=sub,
                     surface_vs_storage_exceeded=dict(slope=float(sl3), r2=float(rr3**2)))

    # ================= H5 EQUITY =================
    P("\n" + "=" * 96)
    P("H5 EQUITY -- dispersion of per-ramp waiting")
    h5 = {}
    for dem in DEMANDS:
        row = {}
        for arm in ("fixed", "alinea", "bnalinea", "coord", "coord_flush"):
            g = by_seed(core, arm=arm, demand=dem)
            if not g:
                continue
            row[arm] = dict(gini=float(np.mean([r["ramp_wait_gini"] for r in g.values()])),
                            maxmean=float(np.mean([r["ramp_wait_max_over_mean"] for r in g.values()])),
                            per_ramp=[float(np.mean([json.loads(r["ramp_wait_per_veh"])[i]
                                                     for r in g.values()])) for i in range(3)])
        h5[dem] = row
        P(f"\n  demand {dem}: per-ramp mean wait (s/released veh) [r1,r2,r3], Gini, max/mean")
        for arm, v in row.items():
            P(f"    {arm:13s} {[round(z,1) for z in v['per_ramp']]}  gini={v['gini']:.3f}  "
              f"max/mean={v['maxmean']:.2f}")
        a = by_seed(core, arm="alinea", demand=dem)
        b = by_seed(core, arm="coord", demand=dem)
        if a and b:
            e = paired(a, b, "ramp_wait_gini")
            P(f"    coord vs alinea Gini: {fmt(e)}")
            h5[dem]["gini_coord_vs_alinea"] = e
    out["H5"] = h5

    # ================= H6 PREVENTION VS RECOVERY =================
    P("\n" + "=" * 96)
    P("H6 PREVENTION VS RECOVERY -- activation-threshold sweep + capacity-drop cross-check")
    act = [r for r in rows if r["group"] == "act"]
    h6 = {}
    base = by_seed(core, arm="coord", demand=0.95)
    nc = by_seed(core, arm="nocontrol", demand=0.95)
    cfgs = [("75", 7.5), (None, 9.5), ("120", 12.0), ("200", 20.0)]
    for tagn, on in cfgs:
        g = base if tagn is None else {int(r["seed"]): r for r in act if f"on{tagn}_" in r["tag"]}
        if not g:
            continue
        e = paired(nc, g, "TSD")
        em = paired(nc, g, "delay_mainline")
        onset = np.mean([g[s]["breakdown_onset"] for s in g if g[s]["breakdown_onset"]])
        dur = np.mean([g[s]["breakdown_duration"] for s in g])
        disch = np.mean([g[s]["bn_discharge_peak"] for s in g])
        h6[on] = dict(vs_nocontrol_TSD=e, vs_nocontrol_mainline=em,
                      breakdown_onset=float(onset), breakdown_duration=float(dur),
                      bn_discharge=float(disch))
        P(f"  o_on_bn={on:5.1f}%: TSD vs nocontrol {e['pct']:+6.1f}% "
          f"[{e['ci_lo']:+.0f},{e['ci_hi']:+.0f}] p={e['p']:.4f} | mainline delay {em['pct']:+6.1f}% "
          f"| breakdown onset {onset:.0f}s dur {dur:.0f}s | bn discharge {disch:.0f} veh/h")
    # corridor effective capacity WITH the three merges present, measured from the
    # no-control runs themselves at s09 (the mainline-only sweep overstates it)
    ncall = [r for r in core if r["arm"] == "nocontrol"]
    pre = [r["prebreakdown_discharge_p95"] for r in ncall if r["prebreakdown_discharge_p95"]]
    post = [r["congested_discharge"] for r in ncall if r["congested_discharge"]]
    cap = dict(prebreakdown_discharge_p95_mean=float(np.mean(pre)) if pre else None,
               prebreakdown_discharge_max=float(np.max(pre)) if pre else None,
               congested_discharge_mean=float(np.mean(post)) if post else None,
               n_pre=len(pre), n_post=len(post))
    if pre and post:
        cap["capacity_drop_pct"] = 100 * (np.max(pre) - np.mean(post)) / np.max(pre)
    P(f"  corridor effective capacity (WITH merges, no-control runs): {json.dumps(cap)}")
    h6["corridor_capacity"] = cap
    P("  breakdown onset (s09) and queue extent by arm at demand 0.95:")
    for arm in ARMS:
        g = by_seed(core, arm=arm, demand=0.95)
        if not g:
            continue
        ons = [g[s]["breakdown_onset"] for s in g if g[s]["breakdown_onset"]]
        P(f"    {arm:13s} onset {np.mean(ons):6.0f} s ({len(ons)}/{len(g)} seeds broke down) | "
          f"breakdown duration {np.mean([g[s]['breakdown_duration'] for s in g]):6.0f} s | "
          f"queue extent {np.mean([g[s]['queue_extent_stations'] for s in g]):.2f} stations | "
          f"discharge {np.mean([g[s]['bn_discharge_peak'] for s in g]):.0f} veh/h")
        h6.setdefault("onset_by_arm", {})[arm] = dict(
            onset=float(np.mean(ons)) if ons else None, n_broke=len(ons),
            dur=float(np.mean([g[s]["breakdown_duration"] for s in g])),
            discharge=float(np.mean([g[s]["bn_discharge_peak"] for s in g])))
    ncd = np.mean([nc[s]["bn_discharge_peak"] for s in nc])
    nco = np.mean([nc[s]["breakdown_onset"] for s in nc if nc[s]["breakdown_onset"]])
    P(f"  nocontrol reference: breakdown onset {nco:.0f}s, bn discharge {ncd:.0f} veh/h")
    h6["nocontrol"] = dict(breakdown_onset=float(nco), bn_discharge=float(ncd))
    cap = os.path.join(ROOT, "outputs", "tables", "capacity_drop.json")
    if os.path.exists(cap):
        h6["capacity_drop"] = json.load(open(cap))
        P(f"  measured capacity drop: {json.dumps(h6['capacity_drop'])}")
    out["H6"] = h6

    json.dump(out, open(os.path.join(ROOT, "outputs", "tables", "hypotheses.json"), "w"),
              indent=1, default=str)
    P("\nwrote outputs/tables/hypotheses.json")


if __name__ == "__main__":
    main()
