"""Q5 part T2b: a GENUINE re-calibration at dt=1.0 s Euler, then transfer to dt=0.1 s ballistic.

The first T2 attempt started Nelder-Mead at the stored optimum and terminated after 15
evaluations essentially where it began, so it could not answer the transfer question.
This version starts from a NEUTRAL point (mid-box), runs a larger budget, and does the
test for IDM -- the model T1 showed to be the dt-sensitive one -- as well as Krauss.

Test: calibrate at (dt, method) = (1.0, euler); evaluate the resulting parameter vector at
(0.1, ballistic).  A dt-specific calibration shows up as RMSN degrading badly on transfer.
For a control, the reverse direction is also run: calibrate at (0.1, ballistic), evaluate at
(1.0, euler).
"""
import os
import sys
import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_q5_transfer as Q                              # noqa
import cf_common as CF                                   # noqa
from dtcommon import savejson                            # noqa

FREE = Q.FREE
LO, HI = Q.LO, Q.HI
BUDGET = 55


def calibrate(model, dt, method, seed=42, tag=""):
    base = CF.full_params(model, Q.STORED[model])
    hist = []

    def unpack(u):
        p = dict(base)
        for i, k in enumerate(FREE):
            p[k] = LO[k] + min(max(u[i], 0.0), 1.0) * (HI[k] - LO[k])
        return p

    def f(u):
        p = unpack(u)
        feat, obj, _ = Q.probe(model, p, dt, method, seed=seed,
                              tag="_%s%d" % (tag, len(hist)))
        r = Q._rmsn(obj)
        hist.append(dict(rmsn=r, params={k: float(p[k]) for k in FREE}))
        return r

    u0 = np.array([0.5, 0.5, 0.5, 0.5])          # NEUTRAL start, not the stored optimum
    res = minimize(f, u0, method="Nelder-Mead",
                   options=dict(maxfev=BUDGET, xatol=0.01, fatol=0.0008,
                                initial_simplex=np.vstack([u0, u0 + [0.25, 0, 0, 0],
                                                           u0 + [0, 0.25, 0, 0],
                                                           u0 + [0, 0, 0.25, 0],
                                                           u0 + [0, 0, 0, 0.25]])))
    best = min(hist, key=lambda h: h["rmsn"])
    p = dict(base)
    p.update(best["params"])
    return p, best, hist


if __name__ == "__main__":
    out = {"budget": BUDGET, "free_params": FREE, "targets":
           {k: v["target"] for k, v in CF.TARGETS.items()}}
    for model in ("Krauss", "IDM"):
        out[model] = {}
        for (cdt, cme), (edt, eme) in [((1.0, "euler"), (0.1, "ballistic")),
                                       ((0.1, "ballistic"), (1.0, "euler"))]:
            key = "calib_dt%g_%s" % (cdt, cme)
            print("\n%s: calibrating at dt=%g %s (neutral start, budget %d)"
                  % (model, cdt, cme, BUDGET))
            p, best, hist = calibrate(model, cdt, cme, tag="%s%g%s" % (model, cdt, cme))
            print("   best RMSN at calibration condition = %.4f  params=%s"
                  % (best["rmsn"], {k: round(v, 4) for k, v in best["params"].items()}))
            fe, ob, _ = Q.probe(model, p, edt, eme, tag="_xfer")
            r_home = best["rmsn"]
            r_away = Q._rmsn(ob)
            rep = Q.rep(fe, ob)
            print("   TRANSFER to dt=%g %s: RMSN = %.4f  (%.2fx the home RMSN)  "
                  "%d/5 features within tol" % (edt, eme, r_away, r_away / r_home,
                                                rep["n_within_tol"]))
            print("      feats:", {k: round(v, 2) for k, v in rep["feat"].items()
                                   if k in ("v_free_kmh", "q_max", "k_crit", "k_jam", "w_kmh")})
            out[model][key] = dict(calibrated_at=dict(dt=cdt, method=cme),
                                   evaluated_at=dict(dt=edt, method=eme),
                                   params=best["params"], rmsn_home=r_home,
                                   rmsn_transfer=r_away, degradation_x=r_away / r_home,
                                   transfer_report=rep, n_evals=len(hist))
    savejson("q5_recalibration.json", out)
    print("\nwritten -> outputs/tables/q5_recalibration.json")
