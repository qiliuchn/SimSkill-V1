"""Q5 TRANSFERABILITY: are calibrated car-following parameters dt-specific?

Reuses the ACTUAL pipeline from the stored calibration episode
(episodic-memory/2026-08-03_17-00-00 -> `calibrate-car-following-parameters-against-field-targets`):
its 2-lane controlled-density ring instrument, its `fd_features`, its TARGETS and its
weighted-RMSN `objective`.  cf_common.ring_cell hardcodes `--step-method.ballistic true`
and takes `step` as a kwarg, so run_sumo is wrapped to rewrite those two flags per cell.

IMPORTANT CORRECTION TO THE TASK PREMISE, verified by reading the stored scripts:
the archived calibration was NOT performed at dt=1.0 s Euler.  cf_common.ring_cell's
default is `step=0.5` WITH `--step-method.ballistic true`.  So the honest test is:
  T1  evaluate the STORED calibrated vTypes across the dt grid (does the archived optimum
      still hit its targets at other dt?)
  T2  RE-calibrate from scratch at dt=1.0 s Euler (the naive default a practitioner gets),
      then evaluate that new optimum at dt=0.1 s ballistic.
"""
import os
import sys
import json
import math
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CAL = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..",
                                   "2026-08-03_17-00-00", "attempts", "attempt-1", "scripts"))
sys.path.insert(0, CAL)
import cf_common as CF                                      # noqa
from dtcommon import savejson, mean, sd, RUNS, TAB          # noqa

# stored calibrated vTypes (outputs/CALIBRATION_SCORECARDS.md of the calibration episode)
STORED = {
    "Krauss": dict(accel=2.6, apparentDecel=3.162, decel=4.981, emergencyDecel=9.0,
                   length=4.356, minGap=2.81, sigma=0.04805, speedDev=0.1,
                   speedFactor=0.9819, tau=1.337),
    "IDM": dict(accel=2.489, decel=5.652, delta=6.259, length=4.119, minGap=3.89,
                speedDev=0.1, speedFactor=0.9895, tau=1.049),
}
GRID = [(1.0, "euler"), (1.0, "ballistic"), (0.5, "euler"), (0.5, "ballistic"),
        (0.25, "euler"), (0.25, "ballistic"), (0.1, "euler"), (0.1, "ballistic")]
CELLS = [4, 11, 19, 22, 25, 28, 32, 44, 70, 110]     # trimmed grid (runtime budget)
Q5ROOT = os.path.join(RUNS, "q5")
os.makedirs(Q5ROOT, exist_ok=True)

_ORIG_RUN = CF.run_sumo
_MODE = {"method": "ballistic"}


def _patched(args, cwd=None, timeout=600):
    a = [str(x) for x in args]
    if _MODE["method"] == "euler":
        while "--step-method.ballistic" in a:
            i = a.index("--step-method.ballistic")
            del a[i:i + 2]
    return _ORIG_RUN(a, cwd=cwd, timeout=timeout)


CF.run_sumo = _patched


def probe(model, p, dt, method, seed=42, tag=""):
    _MODE["method"] = method
    root = os.path.join(Q5ROOT, "%s_dt%g_%s%s" % (model, dt, method, tag))
    cells = []
    for n in CELLS:
        cells.append(CF.ring_cell(os.path.join(root, "k%03d" % n), model, p, n,
                                  seed=seed, end=420.0, warmup=180.0, step=dt))
    feat = CF.fd_features(cells)
    shutil.rmtree(root, ignore_errors=True)
    obj = CF.objective(feat)
    return feat, obj, cells


# ----------------------------------------------------------------- T2 recalibration
FREE = ["tau", "minGap", "length", "speedFactor"]        # top-ranked in the stored Morris screen
LO = dict(tau=0.5, minGap=1.0, length=3.5, speedFactor=0.85)
HI = dict(tau=2.2, minGap=5.0, length=6.0, speedFactor=1.15)


def recalibrate(model, dt, method, maxiter=45, seed=42):
    """Nelder-Mead on the 4 highest-influence parameters at a GIVEN dt/method."""
    from scipy.optimize import minimize
    import numpy as np
    base = CF.full_params(model, STORED[model])
    hist = []

    def unpack(u):
        p = dict(base)
        for i, k in enumerate(FREE):
            uu = min(max(u[i], 0.0), 1.0)
            p[k] = LO[k] + uu * (HI[k] - LO[k])
        return p

    def f(u):
        p = unpack(u)
        feat, obj, _ = probe(model, p, dt, method, seed=seed, tag="_cal%d" % len(hist))
        r = _rmsn(obj)
        hist.append(dict(u=list(map(float, u)), rmsn=r, params={k: p[k] for k in FREE}))
        return r

    u0 = np.array([(STORED[model].get(k, LO[k]) - LO[k]) / (HI[k] - LO[k]) for k in FREE])
    u0 = np.clip(u0, 0.02, 0.98)
    res = minimize(f, u0, method="Nelder-Mead",
                   options=dict(maxfev=maxiter, xatol=0.02, fatol=0.003))
    return unpack(res.x), hist


def _rmsn(obj):
    """cf_common.objective returns a dict {obj, rmsn, parts, geh_qmax}."""
    if isinstance(obj, dict):
        return float(obj.get("rmsn", obj.get("obj")))
    if isinstance(obj, tuple):
        return float(obj[0])
    return float(obj)


def rep(feat, obj):
    return dict(rmsn=_rmsn(obj),
                geh_qmax=(obj.get("geh_qmax") if isinstance(obj, dict) else None),
                parts=(obj.get("parts") if isinstance(obj, dict) else {}),
                n_within_tol=sum(1 for v in (obj.get("parts", {}) if isinstance(obj, dict) else {}).values()
                                 if v.get("within_tol")),
                feat={k: (float(v) if isinstance(v, (int, float)) else v)
                      for k, v in (feat or {}).items()})


if __name__ == "__main__":
    out = dict(stored_params=STORED, targets={k: v["target"] for k, v in CF.TARGETS.items()},
               note="archived calibration ran at dt=0.5 s WITH ballistic (cf_common.ring_cell defaults)")
    print("TARGETS:", out["targets"])

    # ---- T1: stored optimum across the dt grid
    print("\nT1  stored calibrated vType evaluated across the dt grid")
    t1 = {}
    for model in ("Krauss", "IDM"):
        p = CF.full_params(model, STORED[model])
        print(" %s" % model)
        print("   %-16s %8s %9s %9s %9s %9s %9s" %
              ("cell", "RMSN", "v_free", "q_max", "k_crit", "k_jam", "w"))
        for dt, meth in GRID:
            feat, obj, _ = probe(model, p, dt, meth)
            r = rep(feat, obj)
            t1["%s_dt%g_%s" % (model, dt, meth)] = r
            f = r["feat"]
            print("   dt=%-5g %-9s %8.4f %9.2f %9.1f %9.2f %9.2f %9.2f   %d/5 within tol" %
                  (dt, meth, r["rmsn"], f.get("v_free_kmh", float("nan")),
                   f.get("q_max", float("nan")), f.get("k_crit", float("nan")),
                   f.get("k_jam", float("nan")), f.get("w_kmh", float("nan")),
                   r["n_within_tol"]))
    out["T1"] = t1

    # ---- T2: recalibrate at dt=1.0 euler, then test at dt=0.1 ballistic
    print("\nT2  re-calibrate at dt=1.0 s EULER (naive default), then test at dt=0.1 s ballistic")
    t2 = {}
    for model in ("Krauss",):
        pnew, hist = recalibrate(model, 1.0, "euler")
        print("   calibrated-at-dt1-euler params:",
              {k: round(pnew[k], 4) for k in FREE}, " (%d evals)" % len(hist))
        row = {}
        for dt, meth in [(1.0, "euler"), (0.5, "ballistic"), (0.1, "ballistic"), (0.1, "euler")]:
            feat, obj, _ = probe(model, pnew, dt, meth, tag="_T2")
            row["dt%g_%s" % (dt, meth)] = rep(feat, obj)
            f = row["dt%g_%s" % (dt, meth)]["feat"]
            rr = row["dt%g_%s" % (dt, meth)]
            print("     eval @ dt=%-5g %-9s RMSN=%.4f  v_free=%.2f q_max=%.1f k_crit=%.2f "
                  "k_jam=%.2f w=%.2f  %d/5 within tol" %
                  (dt, meth, rr["rmsn"],
                   f.get("v_free_kmh", float("nan")), f.get("q_max", float("nan")),
                   f.get("k_crit", float("nan")), f.get("k_jam", float("nan")),
                   f.get("w_kmh", float("nan")), rr["n_within_tol"]))
        t2[model] = dict(params={k: pnew[k] for k in FREE}, evals=len(hist),
                         full_params={k: float(v) for k, v in pnew.items()
                                      if isinstance(v, (int, float))},
                         results=row,
                         history=hist[-5:])
    out["T2"] = t2
    savejson("q5_transferability.json", out)
    print("\nwritten -> outputs/tables/q5_transferability.json")
