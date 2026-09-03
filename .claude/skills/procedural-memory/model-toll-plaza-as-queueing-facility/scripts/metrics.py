#!/usr/bin/env python3
"""
Per-run plaza queueing metrics, computed from RAW SUMO OUTPUT ONLY.

Definitions (all times in s):
  t_entry(i)  : instantInductionLoop 'enter' event on app_0/app_1 at pos 1190 (plaza-system
                entry line), matched to the vehicle by vehID.
  t_start(i)  : stop-output 'started' for that vehicle's booth stop  (= service start).
  t_end(i)    : stop-output 'ended'                                  (= service end).
  T_ff(b)     : free-flow entry-line -> service-start travel time for booth b, calibrated
                empirically as the MEDIAN of (t_start - t_entry) in a near-empty run.
  Wq(i)       = t_start(i) - t_entry(i) - T_ff(booth(i))     <- pure QUEUE delay, plaza-only
  Lq(t)       = # vehicles with t_entry+T_ff <= t < t_start   <- number waiting, not served
"""
import json
import os

import numpy as np

import plaza_lib as P


def entry_times(run_dir, booths):
    inst = P.parse_instant(os.path.join(run_dir, "instant.xml"))
    ent = {}
    for k in ("ent_0", "ent_1"):
        for t, v in inst.get(k, []):
            ent.setdefault(v, t)                      # first crossing only
    dep = {b: [t for t, _ in inst.get("dep_%d" % b, [])] for b in range(booths)}
    return ent, dep, inst


def calibrate_tff(run_dir, booths):
    """Median entry-line -> service-start time per booth from a near-empty run."""
    ent, _, _ = entry_times(run_dir, booths)
    st = P.parse_stops(os.path.join(run_dir, "stops.xml"))
    per = {b: [] for b in range(booths)}
    for s in st:
        if s["veh"] in ent:
            per[s["booth"]].append(s["started"] - ent[s["veh"]])
    # MEAN (not median): the delay estimator below is an unclipped difference, so T_ff must
    # be the mean free-flow traverse for the mean queue delay to be unbiased.
    return {b: float(np.mean(v)) for b, v in per.items() if v}


def calibrate_tff_bin(run_dir, booths):
    """Mean entry-line -> BOOTH-ENTRY-loop free-flow time (needed for the count-based Lq)."""
    inst = P.parse_instant(os.path.join(run_dir, "instant.xml"))
    ent = {}
    for k in ("ent_0", "ent_1"):
        for t, v in inst.get(k, []):
            ent.setdefault(v, t)
    per = {b: [] for b in range(booths)}
    for b in range(booths):
        for t, v in inst.get("bin_%d" % b, []):
            if v in ent:
                per[b].append(t - ent[v])
    return {b: float(np.mean(v)) for b, v in per.items() if v}


def run_metrics(run_dir, booths, tff, w0, w1, horizon, tff_bin=None):
    """w0,w1 = analysis window on ARRIVAL (entry-line) time."""
    ent, dep, inst = entry_times(run_dir, booths)
    st = P.parse_stops(os.path.join(run_dir, "stops.xml"))
    recs = []
    for s in st:
        v = s["veh"]
        if v not in ent:
            continue
        te = ent[v]
        if not (w0 <= te <= w1):
            continue
        b = s["booth"]
        qin = te + tff.get(b, np.median(list(tff.values())))
        recs.append((v, b, te, qin, s["started"], s["ended"], s["dur"]))
    if len(recs) < 30:
        return None
    b_arr = np.array([r[1] for r in recs])
    qin = np.array([r[3] for r in recs])
    tstart = np.array([r[4] for r in recs])
    tend = np.array([r[5] for r in recs])
    svc = np.array([r[6] for r in recs])
    # UNCLIPPED. Clipping at zero injects a positive bias of order E[max(-noise,0)] which,
    # with any free-flow travel-time noise at all, is comparable to the delay being measured
    # at low rho (verified: +1.13 s of pure bias at rho=0.30 before speedDev was zeroed).
    wq = tstart - qin
    frac_neg = float((wq < 0).mean())

    # ---- time-average Lq from the cumulative queue-in / queue-out curves ----
    T = w1 - w0
    Lq = float(np.sum(tstart - qin) / T)              # area under Lq(t) / window length
    Ls = float(np.sum(tend - qin) / T)                # number in SYSTEM (queue + service)
    lam = len(recs) / T                               # veh/s actually observed

    # ---- Lq from DETECTOR COUNTS ONLY (independent of the per-vehicle bookkeeping):
    #      A(t - T_ff) at the entry loops minus B(t) at the booth-entry loops.
    tff_mean = float(np.mean(list((tff_bin or tff).values())))
    a_t = np.sort(np.array([t for k in ("ent_0", "ent_1") for t, _ in inst.get(k, [])])) + tff_mean
    b_t = np.sort(np.array([t for b in range(booths) for t, _ in inst.get("bin_%d" % b, [])]))
    gridt = np.arange(w0 + tff_mean, w1, 5.0)
    Lq_det = float(np.mean(np.searchsorted(a_t, gridt, "right")
                           - np.searchsorted(b_t, gridt, "right")))

    # ---- per-booth throughput / utilisation / imbalance ----
    per_b_n = np.array([int((b_arr == b).sum()) for b in range(booths)])
    per_b_busy = np.array([float(svc[b_arr == b].sum()) for b in range(booths)])
    # busy time including the move-up gap == time the SERVER is unavailable
    util = per_b_busy / T
    per_b_wq = [float(wq[b_arr == b].mean()) if (b_arr == b).any() else float("nan")
                for b in range(booths)]
    per_b_idle = (1.0 - util).tolist()
    cv_thr = float(per_b_n.std(ddof=0) / per_b_n.mean()) if per_b_n.mean() > 0 else 0.0
    cv_util = float(util.std(ddof=0) / util.mean()) if util.mean() > 0 else 0.0

    # ---- e2: mainline spillback + in-plaza queue ----
    e2 = P.parse_e2(os.path.join(run_dir, "e2.xml"))
    def maxjam(pref):
        vals = [x[1] for k, v in e2.items() if k.startswith(pref) for x in v if w0 <= x[0] <= w1]
        return float(max(vals)) if vals else 0.0
    # ---- e3: independent Little's-law cross-check on the whole plaza zone ----
    e3 = [r for r in P.parse_e3(os.path.join(run_dir, "e3.xml"))
          if w0 <= r["begin"] <= w1 and r["vehicleSum"] > 0]
    e3_W = float(np.average([r["meanTravelTime"] for r in e3],
                            weights=[r["vehicleSum"] for r in e3])) if e3 else float("nan")
    e3_lam = float(sum(r["vehicleSum"] for r in e3) / (len(e3) * 60.0)) if e3 else float("nan")
    e3_L = float(np.mean([r["vehicleSumWithin"] for r in e3])) if e3 else float("nan")

    tri = P.parse_tripinfo(os.path.join(run_dir, "tripinfo.xml"))
    tri_ids = {t["id"] for t in tri}
    sel = [t for t in tri if t["id"] in {r[0] for r in recs}]
    return dict(
        n=len(recs), lam_vph=lam * 3600.0,
        Wq_mean=float(wq.mean()), Wq_p95=float(np.percentile(wq, 95)),
        Wq_max=float(wq.max()), Wq_sd=float(wq.std(ddof=1)),
        Wq_frac_negative=frac_neg,
        Lq_curve=Lq, L_system_curve=Ls, Lq_detector_counts=Lq_det,
        littles_Lq_from_Wq=float(lam * wq.mean()),
        littles_rel_err_pct=float(100.0 * (Lq - lam * wq.mean()) / Lq) if Lq > 1e-9 else 0.0,
        e3_meanTravelTime=e3_W, e3_lam_vps=e3_lam, e3_L_within=e3_L,
        e3_littles_L=float(e3_lam * e3_W) if e3 else float("nan"),
        e3_littles_rel_err_pct=(float(100.0 * (e3_L - e3_lam * e3_W) / e3_L) if e3 and e3_L else float("nan")),
        service_mean=float(svc.mean()), service_cv=float(svc.std(ddof=1) / svc.mean()),
        per_booth_n=per_b_n.tolist(), per_booth_util=util.tolist(),
        per_booth_Wq=per_b_wq, per_booth_idle=per_b_idle,
        booth_Wq_CV=float(np.std(per_b_wq) / np.mean(per_b_wq)) if np.mean(per_b_wq) > 0 else 0.0,
        booth_idle_CV=float(np.std(per_b_idle) / np.mean(per_b_idle)) if np.mean(per_b_idle) > 0 else 0.0,
        booth_throughput_CV=cv_thr, booth_util_CV=cv_util,
        max_jam_app_m=maxjam("q_app"), max_jam_lock_m=maxjam("q_lock"),
        tripinfo_mean_timeLoss=float(np.mean([t["timeLoss"] for t in sel])) if sel else float("nan"),
        tripinfo_mean_waitingTime=float(np.mean([t["waitingTime"] for t in sel])) if sel else float("nan"),
        tripinfo_mean_departDelay=float(np.mean([t["departDelay"] for t in sel])) if sel else float("nan"),
        n_completed=len(tri_ids),
        teleports=P.parse_summary_teleports(os.path.join(run_dir, "summary.xml")),
    )
