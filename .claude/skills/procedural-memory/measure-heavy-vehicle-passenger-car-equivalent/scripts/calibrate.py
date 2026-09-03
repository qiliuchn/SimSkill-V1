#!/usr/bin/env python3
"""STEP 5 -- CALIBRATION: make a SUMO heavy-vehicle fleet reproduce an
HCM-consistent E_T on level terrain, then VERIFY by re-measuring.

Which knob?  From the parameter decomposition:
  * on the SIGNAL testbed only `length` and `tau` move E_T at all
    (`accel` moves it by ~0, `maxSpeed` by exactly 0);
  * on the FREEWAY testbed `accel`/`decel`/`maxSpeed` dominate and `length` is
    nearly inert.
`tau` is the ONLY attribute that raises E_T on BOTH testbeds, so it is the knob
that can give a transferable calibration.  It is also physically defensible: a
longer following time gap for an HGV is a real behavioural difference.

Procedure
  1. 3-point sweep of tau on top of SUMO's default truck, at p=30%.
  2. Linear solve of tau* for the target E_T on the SIGNAL testbed (the testbed
     where SUMO's default truck falls short).
  3. VERIFICATION: re-measure at tau* across p in {10,20,30}% on BOTH testbeds,
     with fresh CIs -- the calibration is only accepted if the target lies inside
     the verification CI.
  4. A second, non-parametric candidate is also measured: SUMO's own default
     `trailer` vClass (16.5 m articulated HGV), which is arguably the vType HCM's
     E_T actually describes.
"""
import os
import json
import time
from multiprocessing import Pool

from common import (WORK, CAR, TRUCK_DEFAULT, SEEDS, GREENS, mean_ci, ols)
import signal_rig as S
import freeway_rig as F
import analyze as A

TARGET = 1.5
CAL_P = 0.30
VERIFY_P = [0.10, 0.20, 0.30]
TAUS = [1.3, 1.6, 1.9]
RUNS = os.path.join(WORK, "runs_cal")

TRAILER_DEFAULT = dict(vClass="trailer", length=16.5, minGap=2.5, accel=1.1,
                       decel=4.0, tau=1.0, maxSpeed=36.11)


def attrs_for(name):
    if name == "trailer":
        return dict(TRAILER_DEFAULT)
    if name.startswith("tau"):
        d = dict(TRUCK_DEFAULT)
        d["tau"] = float(name[3:])
        return d
    raise KeyError(name)


def sdir(name, p, g, seed):
    return os.path.join(RUNS, "sig", "%s_p%03d_g%02d_s%d" % (name, round(p * 100), g, seed))


def fdir(name, p, seed):
    return os.path.join(RUNS, "fwy", "%s_p%03d_s%d" % (name, round(p * 100), seed))


def job(j):
    kind, name, p, x, seed = j
    a = attrs_for(name)
    if kind == "sig":
        d = sdir(name, p, x, seed)
        if not os.path.exists(os.path.join(d, "stats.xml")):
            S.run(d, float(x), p, seed, a, CAR)
    else:
        d = fdir(name, p, seed)
        if not os.path.exists(os.path.join(d, "stats.xml")):
            F.run(d, 0.0, p, seed, a, CAR)
    return j


def simulate(names_ps):
    jobs = []
    for name, p in names_ps:
        for s in SEEDS:
            jobs.append(("fwy", name, p, 0.0, s))
            for g in GREENS:
                jobs.append(("sig", name, p, g, s))
    jobs.sort(key=lambda j: 0 if j[0] == "fwy" else 1)
    print("  simulating %d cells ..." % len(jobs), flush=True)
    t0 = time.time()
    with Pool(8) as pool:
        for _ in pool.imap_unordered(job, jobs):
            pass
    print("  done in %.0f s" % (time.time() - t0), flush=True)


# --- measure a candidate against the SAME pure-car control arms as the main study
def measure(name, p, base_sig, base_fwy):
    sc = []
    for s in SEEDS:
        # reuse analyze.signal_cell's estimator by pointing it at our dirs
        orig = A.sig_dir
        A.sig_dir = lambda v, pp, g, ss, _n=name: sdir(_n, pp, g, ss)
        try:
            sc.append(A.signal_cell(name, p, s))
        finally:
            A.sig_dir = orig
    fc = []
    for s in SEEDS:
        fc.append(F.analyse_run(fdir(name, p, s)))
        fc[-1]["seed"] = s
    e_sig = A.et_series(sc, base_sig, "s_vph", "hv_share_realised")
    e_fwy = A.et_series(fc, base_fwy, "capacity_vph", "hv_share_discharged")
    m1, _, c1, _ = mean_ci(e_sig)
    m2, _, c2, _ = mean_ci(e_fwy)
    return dict(
        name=name, p_nominal=p,
        p_realised_sig=mean_ci([c["hv_share_realised"] for c in sc])[0],
        p_realised_fwy=mean_ci([c["hv_share_discharged"] for c in fc])[0],
        h_s=mean_ci([c["h_s"] for c in sc])[0],
        s_vph=mean_ci([c["s_vph"] for c in sc])[0],
        s_ci95=mean_ci([c["s_vph"] for c in sc])[2],
        capacity_vph=mean_ci([c["capacity_vph"] for c in fc])[0],
        capacity_ci95=mean_ci([c["capacity_vph"] for c in fc])[2],
        ET_signal=m1, ET_signal_ci95=c1, ET_signal_per_seed=e_sig,
        ET_freeway=m2, ET_freeway_ci95=c2, ET_freeway_per_seed=e_fwy,
        signal_queue_min=min(c["queue_min_over_greens"] for c in sc),
        fwy_upstream_speed=mean_ci([c["upstream_space_mean_speed_ms"] for c in fc])[0],
        teleports=sum(c["teleports"] for c in fc),
        collisions=sum(c["collisions"] for c in fc))


def main():
    base_sig = [A.signal_cell("hv_full", 0.0, s) for s in SEEDS]
    base_fwy = [A.freeway_cell("hv_full", 0.0, 0.0, s) for s in SEEDS]

    # -------------------------------------------------- 1. tau sweep at p=30%
    print("STEP 1: tau sweep at p=%.0f%%" % (CAL_P * 100))
    simulate([("tau%g" % t, CAL_P) for t in TAUS])
    sweep = [measure("tau%g" % t, CAL_P, base_sig, base_fwy) for t in TAUS]
    for t, r in zip(TAUS, sweep):
        print("   tau=%.2f  E_T signal=%.3f +/- %.3f   E_T freeway=%.3f +/- %.3f"
              % (t, r["ET_signal"], r["ET_signal_ci95"], r["ET_freeway"], r["ET_freeway_ci95"]))

    # -------------------------------------------------- 2. solve for target
    a, b, r2 = ols(TAUS, [r["ET_signal"] for r in sweep])
    tau_star = round((TARGET - a) / b, 2)
    print("STEP 2: E_T_signal(tau) = %.4f + %.4f*tau  (R2=%.5f)  ->  tau* = %.2f for E_T=%.2f"
          % (a, b, r2, tau_star, TARGET))

    # ------------------------------- 3. verification + trailer alternative
    print("STEP 3: verification at tau*=%.2f and the `trailer` alternative" % tau_star)
    names = [("tau%g" % tau_star, p) for p in VERIFY_P] + [("trailer", p) for p in VERIFY_P]
    simulate(names)
    verify = [measure("tau%g" % tau_star, p, base_sig, base_fwy) for p in VERIFY_P]
    trailer = [measure("trailer", p, base_sig, base_fwy) for p in VERIFY_P]

    for lbl, rows in (("tau*=%.2f" % tau_star, verify), ("trailer", trailer)):
        for r in rows:
            hit = (r["ET_signal"] - r["ET_signal_ci95"] <= TARGET <=
                   r["ET_signal"] + r["ET_signal_ci95"])
            print("   %-12s p=%.0f%%  E_T signal=%.3f +/- %.3f  [target in CI: %s]"
                  "   E_T freeway=%.3f +/- %.3f"
                  % (lbl, r["p_nominal"] * 100, r["ET_signal"], r["ET_signal_ci95"],
                     hit, r["ET_freeway"], r["ET_freeway_ci95"]))

    header = ["candidate", "p_nominal", "p_realised_signal", "p_realised_freeway",
              "signal_h_s_s", "signal_s_vph", "signal_s_ci95",
              "freeway_capacity_vph", "freeway_capacity_ci95",
              "ET_signal", "ET_signal_ci95", "target_in_signal_CI",
              "ET_freeway", "ET_freeway_ci95", "signal_min_queue_veh",
              "freeway_upstream_speed_ms", "teleports", "collisions"]
    rows = []
    for r in sweep + verify + trailer:
        rows.append([r["name"], r["p_nominal"], round(r["p_realised_sig"], 4),
                     round(r["p_realised_fwy"], 4), round(r["h_s"], 4),
                     round(r["s_vph"], 1), round(r["s_ci95"], 1),
                     round(r["capacity_vph"], 1), round(r["capacity_ci95"], 1),
                     round(r["ET_signal"], 4), round(r["ET_signal_ci95"], 4),
                     bool(r["ET_signal"] - r["ET_signal_ci95"] <= TARGET <=
                          r["ET_signal"] + r["ET_signal_ci95"]),
                     round(r["ET_freeway"], 4), round(r["ET_freeway_ci95"], 4),
                     r["signal_queue_min"], round(r["fwy_upstream_speed"], 2),
                     r["teleports"], r["collisions"]])

    vpts = []
    for r in verify:
        if abs(r["p_nominal"] - CAL_P) < 1e-9:
            vpts.append(["verification @ tau*=%.2f, p=30%%" % tau_star, tau_star,
                         r["ET_signal"], r["ET_signal_ci95"], "#2f855a"])
    out = dict(
        param="tau (heavy-vehicle following time gap, s)",
        target_ET=TARGET, calibration_share=CAL_P,
        fit_intercept=a, fit_slope=b, fit_r2=r2, solved_value=tau_star,
        sweep_x=TAUS, sweep_et=[r["ET_signal"] for r in sweep],
        sweep_ci=[r["ET_signal_ci95"] for r in sweep],
        sweep_et_freeway=[r["ET_freeway"] for r in sweep],
        verification_points=vpts,
        calibrated_vtype=attrs_for("tau%g" % tau_star),
        trailer_vtype=TRAILER_DEFAULT,
        sweep=sweep, verify=verify, trailer=trailer,
        csv_header=header, csv_rows=rows)
    with open(os.path.join(WORK, "calibration_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    print("written", os.path.join(WORK, "calibration_results.json"))


if __name__ == "__main__":
    main()
