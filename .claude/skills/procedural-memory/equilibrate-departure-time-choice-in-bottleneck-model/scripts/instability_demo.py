"""
Negative-result deliverable: the departure-time equilibrium is a REPELLING fixed point of
naive day-to-day adjustment dynamics.

Started EXACTLY at the closed-form Vickrey equilibrium profile, a proportional-swap
(Smith-type) day-to-day dynamic -- the natural analogue of duaIterate's Gawron/logit
re-assignment, applied to departure time -- drifts away from it. This is why the outer loop
in equilibrate_hybrid.py solves an equilibrium gap function instead of iterating a response
map. Run on the fast vertical-queue surrogate so the experiment is cheap and unambiguous;
the same divergence was observed with SUMO in the loop.
"""
import os, sys, json, csv
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
import vq
from equilibrate import largest_remainder

OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_19-30-00/outputs"


def analytic_profile_counts(N, s, tf, beta=BETA, gamma=GAMMA, alpha=ALPHA):
    a = vickrey_analytic(N, s, tf, alpha, beta, gamma)
    ts, te = a["t_first_depart"], a["t_last_depart"]
    r_e = alpha * s / (alpha - beta)
    r_l = alpha * s / (alpha + gamma)
    tn = ts + (a["frac_early"] * N) / r_e
    st = slot_starts()
    dens = np.zeros(NSLOT)
    for k, t0 in enumerate(st):
        t1 = t0 + SLOT
        dens[k] = r_e * max(0.0, min(t1, tn) - max(t0, ts)) + r_l * max(0.0, min(t1, te) - max(t0, tn))
    return largest_remainder(dens, N).astype(float), a


def swap_step(n, cost, phi=0.9, gain_pow=0.5, diffuse=0.03):
    n = np.asarray(n, float); tot = n.sum()
    cbar = float(np.average(cost, weights=np.maximum(n, 1e-12)))
    mad = float(np.average(np.abs(cost - cbar), weights=np.maximum(n, 1e-12)))
    scale = max(2.0 * mad, 1e-9)
    excess = np.maximum(0.0, cost - cbar); deficit = np.maximum(0.0, cbar - cost)
    if excess.max() <= 0 or deficit.sum() <= 0:
        return n.copy()
    give = np.minimum(phi * n * np.minimum(1.0, excess / scale), n)
    gw = deficit ** gain_pow
    out = n - give + give.sum() * (gw / gw.sum())
    sm = np.copy(out); sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
    out = np.maximum((1 - diffuse) * out + diffuse * sm, 0.0)
    return out / out.sum() * tot


def dispersion(n, s, tf):
    c, q, a = vq.slot_cost(n, s, tf, np.zeros(NSLOT), np.zeros(NSLOT))
    w = np.maximum(n, 0.0)
    u = w > 0.05
    cbar = float(np.average(c[u], weights=w[u]))
    return (cbar,
            float((c[u].max() - c[u].min()) / cbar),
            float(np.sqrt(np.average((c[u] - cbar) ** 2, weights=w[u])) / cbar))


if __name__ == "__main__":
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    s, tf = cap["capacity_vps"], cap["free_flow"]["tf_mean"]
    n0, an = analytic_profile_counts(N_COMMUTERS, s, tf)
    rows = []
    for lam in (0.02, 0.005):
        n = n0.copy()
        for m in range(0, 2001):
            cbar, gap, sd = dispersion(n, s, tf)
            if m in (0, 5, 10, 25, 50, 100, 200, 400, 800, 1500, 2000):
                rows.append(dict(dynamic="proportional swap, MSA step %.3f" % lam, iteration=m,
                                 mean_cost="%.2f" % cbar, cost_gap_rel="%.4f" % gap,
                                 cost_sd_rel="%.4f" % sd))
                print("  lam=%.3f it=%4d mean=%7.1f gap=%.4f sd=%.4f" % (lam, m, cbar, gap, sd))
            c, q, a = vq.slot_cost(n, s, tf, np.zeros(NSLOT), np.zeros(NSLOT))
            n = (1 - lam) * n + lam * swap_step(n, c)
    ne, ce, qe, info = vq.solve_equilibrium(s, tf, np.zeros(NSLOT), np.zeros(NSLOT),
                                            x0=None, restarts=1, maxiter=700)
    cbar, gap, sd = dispersion(ne, s, tf)
    rows.append(dict(dynamic="gap-function SOLVER (used by the outer loop)", iteration="-",
                     mean_cost="%.2f" % cbar, cost_gap_rel="%.4f" % gap,
                     cost_sd_rel="%.4f" % sd))
    print("  SOLVER            mean=%7.1f gap=%.4f sd=%.4f" % (cbar, gap, sd))
    print("  closed form       mean=%7.1f" % (an["excess_cost_per_traveller"] + tf))
    rows.append(dict(dynamic="Vickrey closed form (reference)", iteration="-",
                     mean_cost="%.2f" % (an["excess_cost_per_traveller"] + tf),
                     cost_gap_rel="0 (continuum)", cost_sd_rel="0 (continuum)"))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "dynamics_instability.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("wrote", os.path.join(OUT, "dynamics_instability.csv"))
