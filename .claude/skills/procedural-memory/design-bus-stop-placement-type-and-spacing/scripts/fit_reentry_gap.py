"""Fit the CRITICAL GAP implied by SUMO's own bay re-entry behaviour.

verify_dwell_model.py measured the extra fixed dwell a parking="true" stop costs
as a function of the per-lane flow the bus must re-enter.  Classical gap
acceptance predicts an expected wait

    E[W](q, tau) = (exp(q*tau) - 1) / q - tau

for a Poisson stream of rate q and critical gap tau.  Solve for the tau that best
reproduces the measured overheads -> a single interpretable number describing
what SUMO's bay re-entry actually behaves like.
"""
import os
import sys
import json
import math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")


def EW(q, tau):
    if q <= 0:
        return 0.0
    return (math.exp(q * tau) - 1.0) / q - tau


def main():
    d = json.load(open(os.path.join(RES, "verify_dwell_model.json")))
    pts = [(r["q_per_lane"] / 3600.0, r["overhead_s"], r["lanes_art"], r["q_art"])
           for r in d["parking_overhead_vs_flow"] if r["q_per_lane"] > 0]
    # per-point implied tau
    per_point = []
    for q, w, L, qa in pts:
        lo, hi = 0.01, 30.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if EW(q, mid) < w:
                lo = mid
            else:
                hi = mid
        per_point.append({"lanes": L, "q_art": qa, "q_per_lane_veh_s": round(q, 5),
                          "measured_overhead_s": w, "implied_tau_s": round((lo + hi) / 2, 3)})
    # single global tau by least squares
    best = None
    tau = 0.5
    while tau <= 15.0:
        ss = sum((EW(q, tau) - w) ** 2 for q, w, _, _ in pts)
        if best is None or ss < best[1]:
            best = (tau, ss)
        tau += 0.01
    fit = {"global_tau_s": round(best[0], 2), "sse": round(best[1], 3),
           "predicted_vs_measured": [
               {"q_per_lane_veh_h": round(q * 3600, 1), "measured_s": w,
                "predicted_s": round(EW(q, best[0]), 2)} for q, w, _, _ in pts]}
    out = {"per_point_implied_critical_gap": per_point, "global_fit": fit}
    json.dump(out, open(os.path.join(RES, "fit_reentry_gap.json"), "w"), indent=1)
    print("per-point implied critical gap (s):")
    for p in per_point:
        print(f"  lanes={p['lanes']} q/lane={p['q_per_lane_veh_s']*3600:6.1f} veh/h  "
              f"overhead={p['measured_overhead_s']:6.2f}s  -> tau={p['implied_tau_s']:.2f}s")
    print(f"\nglobal least-squares critical gap: tau = {fit['global_tau_s']} s")
    for r in fit["predicted_vs_measured"]:
        print(f"  q/lane={r['q_per_lane_veh_h']:6.1f}  measured={r['measured_s']:6.2f}  "
              f"predicted={r['predicted_s']:6.2f}")


if __name__ == "__main__":
    main()
