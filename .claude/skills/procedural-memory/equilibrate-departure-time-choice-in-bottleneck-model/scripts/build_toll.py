"""
Step 4a. Construct the time-varying (optimal) toll profile.

The theoretical optimal toll rises and falls exactly in step with the queueing delay it
replaces, AS A FUNCTION OF ARRIVAL TIME:

    tau(arrival a) = alpha * Q_notoll(a)

where Q_notoll(a) is the queueing delay suffered by the traveller who arrives at a in the
no-toll equilibrium. Under the toll the queue vanishes, so that traveller now departs at
a - Tf, and the toll charged on DEPARTURE time is

    tau(t_depart) = alpha * Q_notoll(t_depart + Tf).

CAUTION (a mistake made and corrected in this episode): using alpha * Q_notoll(t_depart)
-- the queueing delay as a function of DEPARTURE time -- is wrong. In the no-toll
equilibrium departure and arrival are separated by the queue, so the delay peak sits at the
departure time t_n whose ARRIVAL is t*, roughly 665 s earlier than t* - Tf. That mis-built
toll peaks ~630 s too early and does not reproduce the closed-form optimal toll.

We build the toll EMPIRICALLY from the measured no-toll equilibrium so it self-corrects for
whatever SUMO's real bottleneck does, and save the closed form alongside for comparison.

The toll is a pure generalized-cost term in the Python outer loop. It never touches speed,
capacity, or any SUMO physics.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *


def empirical_toll(no_toll_result, tf, alpha=ALPHA, h=40.0):
    """tau(t_depart) = alpha * Q_notoll(arrival = t_depart + Tf), kernel-smoothed."""
    recs = parse_tripinfo(no_toll_result["final_tripinfo"])
    arr = np.array([r["arrival"] for r in recs.values()])
    q = np.array([max(0.0, r["tt"] - tf) for r in recs.values()])
    target = slot_starts() + SLOT / 2.0 + tf          # the arrival time each slot maps to
    w = np.exp(-0.5 * ((target[:, None] - arr[None, :]) / h) ** 2)
    sw = w.sum(axis=1)
    qhat = np.where(sw > 1e-3, (w @ q) / np.maximum(sw, 1e-12), 0.0)
    qhat[(target < arr.min()) | (target > arr.max())] = 0.0
    tau = alpha * np.maximum(qhat, 0.0)
    tau[tau < 1.0] = 0.0                              # clean numerical dust off the shoulders
    return tau, arr, q


if __name__ == "__main__":
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf = cap["free_flow"]["tf_mean"]
    s_vps = cap["capacity_vps"]
    nt = json.load(open(os.path.join(WORK, "eq_no_toll", "result.json")))

    tau, arr, q = empirical_toll(nt, tf)
    tau_an, an = analytic_toll_profile(N_COMMUTERS, s_vps, tf)
    np.save(os.path.join(WORK, "toll_timevarying.npy"), tau)
    np.save(os.path.join(WORK, "toll_analytic.npy"), tau_an)
    np.save(os.path.join(WORK, "toll_zero.npy"), np.zeros(NSLOT))

    st = slot_starts()
    print("empirical time-varying toll : max=%.1f at t_depart=%.0f, nonzero slots=%d"
          % (tau.max(), st[int(np.argmax(tau))], int((tau > 0).sum())))
    print("analytic  time-varying toll : max=%.1f at t_depart=%.0f, nonzero slots=%d"
          % (tau_an.max(), st[int(np.argmax(tau_an))], int((tau_an > 0).sum())))
    print("closed form: toll_max = delta*N/s = %.1f ; peak should sit at t* - Tf = %.0f"
          % (an["toll_max"], T_STAR - tf))
    print("mean |empirical - analytic| over nonzero slots = %.1f cost units"
          % np.mean(np.abs(tau - tau_an)[(tau > 0) | (tau_an > 0)]))
