"""
THE OUTER LOOP. Departure-time user equilibrium with SUMO in the loop.

Same discipline as duaIterate.py's outer loop -- simulate, read realised cost, shift demand,
re-simulate, with a decreasing MSA step -- except that what gets rewritten between SUMO runs
is every commuter's `<vehicle depart=...>` time rather than its route, and the inner
"assignment" step is an equilibrium SOLVE rather than a response map, because this project
verified that the departure-time equilibrium is a REPELLING fixed point of naive response
dynamics (see FINDINGS.md).

Per outer iteration m:
  1. solve the vertical-queue surrogate's departure-time equilibrium exactly, using the
     independently MEASURED capacity s and free-flow time Tf plus the current learned
     per-slot correction `corr`;
  2. write those departure times into a SUMO route file and run SUMO;
  3. read every commuter's realised arrival from tripinfo, compute the realised generalized
     cost alpha*TT + beta*SDE + gamma*SDL + toll (TT includes departDelay, so no experienced
     delay is invisible to the cost function);
  4. MSA-update the correction with step 1/(m+1):
         corr <- (1 - w) * corr + w * (c_SUMO - c_surrogate_without_corr)
     so `corr` converges to exactly the systematic difference between SUMO's bottleneck and
     the idealised point queue (capacity drop at the queue head, finite acceleration,
     vehicle length/storage, lane changing).
At the fixed point the surrogate's equalised cost IS the SUMO-realised cost, i.e. the
equilibrium condition holds on real simulated experience, not on an idealised proxy.
"""
import os, sys, json, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
import vq
from equilibrate import largest_remainder


def measured_cost_curve(rows, h=45.0):
    """Nadaraya-Watson (Gaussian-kernel) smoother of realised cost vs departure time,
    evaluated at every slot centre. A fixed TIME bandwidth, not a fixed vehicle count --
    a vehicle-count window over-smooths the sparse late branch by hundreds of seconds."""
    t = np.array([r["depart"] for r in rows])
    c = np.array([r["cost"] for r in rows])
    mid = slot_starts() + SLOT / 2.0
    w = np.exp(-0.5 * ((mid[:, None] - t[None, :]) / h) ** 2)
    sw = w.sum(axis=1)
    out = np.where(sw > 1e-6, (w @ c) / np.maximum(sw, 1e-12), np.nan)
    inwin = (mid >= t.min() - SLOT) & (mid <= t.max() + SLOT) & (sw > 0.5)
    return out, inwin


def extend(v, mask):
    """Constant-extend a partially observed per-slot field outside the observed window."""
    v = np.array(v, float)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return np.zeros(NSLOT)
    out = np.copy(v)
    out[:idx[0]] = v[idx[0]]
    out[idx[-1] + 1:] = v[idx[-1]]
    bad = ~mask
    bad[:idx[0]] = False
    bad[idx[-1] + 1:] = False
    if bad.any():
        out[bad] = np.interp(np.where(bad)[0], idx, v[idx])
    return out


def run(name, toll, tf, s, outer=12, beta=BETA, gamma=GAMMA, N=N_COMMUTERS, seed=1,
        outdir=None, restarts=1, maxiter=700, verbose=True, solver_seed=0):
    outdir = outdir or os.path.join(WORK, "eq_" + name)
    os.makedirs(outdir, exist_ok=True)
    toll = np.asarray(toll, float)
    corr = np.zeros(NSLOT)
    x0 = None
    trace = []
    prev_counts = None
    add = os.path.join(outdir, "ed.add.xml")
    ed = os.path.join(outdir, "edgedata.xml")
    write_edgedata_add(add, ed, freq=30)
    rou = os.path.join(outdir, "it.rou.xml")
    ti = os.path.join(outdir, "it.tripinfo.xml")

    for m in range(outer):
        n, c_sur, q_sur, info = vq.solve_equilibrium(
            s, tf, toll, corr, N=N, beta=beta, gamma=gamma, x0=x0,
            restarts=(restarts if m == 0 else 0), maxiter=maxiter, seed=solver_seed)
        x0 = np.array(info["x"])
        counts = largest_remainder(n, N)
        slot_of = write_routes(counts, rou)
        run_sumo(rou, ti, seed=seed, extra_add=[add])
        recs = parse_tripinfo(ti)
        assert len(recs) == N, "only %d of %d finished" % (len(recs), N)
        rows = vehicle_costs(recs, slot_of, tf, toll, beta=beta, gamma=gamma)
        cnt, mean_c, mean_q = slot_stats(rows)
        c_meas, inwin = measured_cost_curve(rows)

        # --- realised (SUMO) equilibrium diagnostics
        u = np.where(cnt > 0)[0]
        wbar = float(np.average(mean_c[u], weights=cnt[u]))
        gap = float((mean_c[u].max() - mean_c[u].min()) / wbar)
        sd = float(np.sqrt(np.average((mean_c[u] - wbar) ** 2, weights=cnt[u])) / wbar)
        core = np.where(cnt >= 0.01 * N)[0]
        cgap = float((mean_c[core].max() - mean_c[core].min()) / wbar) if len(core) else np.nan
        changed = (0.5 * np.abs(counts - prev_counts).sum() / N) if prev_counts is not None else 1.0
        prev_counts = counts.copy()

        # --- MSA update of the SUMO-vs-surrogate correction
        c_sur_nocorr = c_sur - corr
        resid = extend(np.where(inwin, c_meas, np.nan), inwin & np.isfinite(c_meas)) - c_sur_nocorr
        w = 1.0 / (m + 1)
        corr = (1 - w) * corr + w * resid

        trace.append(dict(
            iter=m, msa_step=w,
            surrogate_gap_function=info["gap_function"],
            surrogate_cost_gap_rel=info["cost_gap_rel"],
            sumo_mean_cost=float(np.mean([r["cost"] for r in rows])),
            sumo_used_cost_gap_rel=gap, sumo_used_cost_sd_rel=sd,
            sumo_core_cost_gap_rel=cgap,
            sumo_mean_queue=float(np.mean([r["queue"] for r in rows])),
            sumo_max_queue=float(np.max([r["queue"] for r in rows])),
            sumo_mean_depart_delay=float(np.mean([r["depart_delay"] for r in rows])),
            mean_toll=float(np.mean([r["toll"] for r in rows])),
            n_used_slots=int(len(u)),
            frac_changed_slot=float(changed),
            mean_abs_correction=float(np.mean(np.abs(corr[cnt > 0]))),
            correction_rms=float(np.sqrt(np.mean(resid[cnt > 0] ** 2)))))
        if verbose:
            print("  [%s] outer=%2d  SUMO meanCost=%7.1f  usedGap=%.4f  usedSd=%.4f  "
                  "meanQ=%6.1f  chg=%.3f  |corr|=%.1f" %
                  (name, m, trace[-1]["sumo_mean_cost"], gap, sd,
                   trace[-1]["sumo_mean_queue"], changed,
                   trace[-1]["mean_abs_correction"]), flush=True)

    # ---- final converged profile, simulated once more and kept in full
    rou_f = os.path.join(outdir, "final.rou.xml")
    ti_f = os.path.join(outdir, "final.tripinfo.xml")
    add_f = os.path.join(outdir, "final_ed.add.xml")
    ed_f = os.path.join(outdir, "final_edgedata.xml")
    write_edgedata_add(add_f, ed_f, freq=30)
    slot_of = write_routes(counts, rou_f)
    run_sumo(rou_f, ti_f, seed=seed, extra_add=[add_f])
    recs = parse_tripinfo(ti_f)
    rows = vehicle_costs(recs, slot_of, tf, toll, beta=beta, gamma=gamma)
    cnt, mean_c, mean_q = slot_stats(rows)
    c_meas, inwin = measured_cost_curve(rows)
    mid = slot_starts() + SLOT / 2.0
    qhat = np.zeros(NSLOT)
    uu = np.where(cnt > 0)[0]
    if len(uu):
        qhat = np.interp(mid, mid[uu], mean_q[uu], left=0.0, right=0.0)
        qhat[(mid < mid[uu[0]]) | (mid > mid[uu[-1]])] = 0.0

    res = dict(name=name, scheme="vq-solver + SUMO MSA correction", iters=outer, seed=seed,
               alpha=ALPHA, beta=beta, gamma=gamma, N=N, tf_free=tf, capacity_vps=s,
               counts=counts.tolist(), toll=toll.tolist(), correction=corr.tolist(),
               slot_cnt=cnt.tolist(), slot_mean_cost=mean_c.tolist(),
               slot_mean_queue=mean_q.tolist(),
               smoothed_cost=np.where(inwin, c_meas, np.nan).tolist(),
               smoothed_queue=qhat.tolist(),
               surrogate_cost=c_sur.tolist(),
               trace=trace, outdir=outdir, final_tripinfo=ti_f, final_routes=rou_f,
               final_edgedata=ed_f)
    with open(os.path.join(outdir, "result.json"), "w") as f:
        json.dump(res, f, indent=2, default=lambda o: None)
    np.save(os.path.join(outdir, "counts.npy"), counts)
    return res, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--outer", type=int, default=12)
    ap.add_argument("--toll", default="none")
    ap.add_argument("--gamma", type=float, default=GAMMA)
    ap.add_argument("--beta", type=float, default=BETA)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--solver-seed", type=int, default=0)
    a = ap.parse_args()
    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf, s = cap["free_flow"]["tf_mean"], cap["capacity_vps"]
    if a.toll in ("none", "zero"):
        toll = np.zeros(NSLOT)
    elif a.toll.startswith("file:"):
        toll = np.load(a.toll[5:])
    elif a.toll.startswith("flat:"):
        toll = np.full(NSLOT, float(a.toll[5:]))
    else:
        raise ValueError(a.toll)
    print("Equilibrating '%s' outer=%d beta=%.2f gamma=%.2f Tf=%.2f s=%.5f toll=%s"
          % (a.name, a.outer, a.beta, a.gamma, tf, s, a.toll), flush=True)
    res, rows = run(a.name, toll, tf, s, outer=a.outer, beta=a.beta, gamma=a.gamma, seed=a.seed,
                    solver_seed=a.solver_seed)
    t = res["trace"][-1]
    print("FINAL %s meanCost=%.2f usedGap=%.4f usedSd=%.4f meanQ=%.1f chg=%.4f"
          % (a.name, t["sumo_mean_cost"], t["sumo_used_cost_gap_rel"],
             t["sumo_used_cost_sd_rel"], t["sumo_mean_queue"], t["frac_changed_slot"]))
