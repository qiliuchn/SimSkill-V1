"""
Step 2. Departure-time user equilibrium by an outer iteration loop.

Structurally the same discipline as duaIterate.py's outer loop (simulate -> read realised
cost -> shift a fraction of demand -> re-simulate, with a decreasing MSA step), except the
decision variable rewritten between runs is `<vehicle depart=...>` rather than the route.
Route choice is trivial here (a single path), so departure time is the ONLY decision variable.

Three stabilising devices, all needed to get a clean fixed point (each was added only after
the simpler version was observed to oscillate -- see FINDINGS.md):
  1. MSA averaging of the PROFILE with a decreasing step lambda_m = 1/(m+1)^lam_exp.
  2. MSA/exponential smoothing of the COST signal across iterations, because departure-time
     choice has a forward externality (extra departures in slot k raise the cost of slots
     k+1, k+2, ...) which makes a raw best-response map oscillate.
  3. A vehicle-level moving-average smoother on cost-vs-departure-time, which gives a much
     less noisy and higher-resolution cost curve than 20 s slot means with 1-3 vehicles in
     the tails.
"""
import os, sys, json, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *


# ------------------------------------------------------------------ helpers
def largest_remainder(x, total):
    """Round a real-valued profile to non-negative integers summing exactly to `total`."""
    x = np.maximum(np.asarray(x, float), 0.0)
    if x.sum() <= 0:
        x = np.ones_like(x)
    x = x * (total / x.sum())
    base = np.floor(x).astype(int)
    rem = int(total - base.sum())
    if rem > 0:
        order = np.argsort(-(x - base))
        base[order[:rem]] += 1
    elif rem < 0:
        order = np.argsort(x - base)
        idx = [i for i in order if base[i] > 0][:(-rem)]
        base[idx] -= 1
    return base


def smooth_cost_curve(rows, halfwin=25):
    """Smooth cost as a function of departure time using a centred moving average over
    departure-time-ordered vehicles, then evaluate at every slot centre.

    Returns (c_at_slot_centres, valid_mask) -- valid only inside the used departure window.
    """
    rr = sorted(rows, key=lambda r: r["depart"])
    t = np.array([r["depart"] for r in rr])
    c = np.array([r["cost"] for r in rr])
    n = len(rr)
    cs = np.cumsum(np.concatenate([[0.0], c]))
    lo = np.maximum(0, np.arange(n) - halfwin)
    hi = np.minimum(n, np.arange(n) + halfwin + 1)
    sm = (cs[hi] - cs[lo]) / (hi - lo)
    mid = slot_starts() + SLOT / 2.0
    out = np.interp(mid, t, sm, left=np.nan, right=np.nan)
    valid = (mid >= t.min()) & (mid <= t.max())
    return out, valid


def smooth_queue_curve(rows):
    rr = sorted(rows, key=lambda r: r["depart"])
    t = np.array([r["depart"] for r in rr])
    q = np.array([r["queue"] for r in rr])
    n = len(rr)
    hw = 25
    cs = np.cumsum(np.concatenate([[0.0], q]))
    lo = np.maximum(0, np.arange(n) - hw)
    hi = np.minimum(n, np.arange(n) + hw + 1)
    sm = (cs[hi] - cs[lo]) / (hi - lo)
    mid = slot_starts() + SLOT / 2.0
    qq = np.interp(mid, t, sm, left=0.0, right=0.0)
    qq[(mid < t.min()) | (mid > t.max())] = 0.0
    return np.maximum(qq, 0.0)


def build_cost_signal(rows, cnt, tf_free, toll, beta, gamma):
    """Cost of a marginal traveller in EVERY slot of the grid.

    Inside the used departure window: the vehicle-level smoothed realised cost curve.
    Outside it: the exact counterfactual for a lone traveller, who meets no queue
    (Q = 0 before the queue forms / after it clears) -- the textbook marginal-traveller
    argument, and the only way an unused slot can ever attract demand.
    """
    sm, valid = smooth_cost_curve(rows)
    q_hat = smooth_queue_curve(rows)
    mid = slot_starts() + SLOT / 2.0
    arr_ff = mid + tf_free
    cf = (ALPHA * tf_free
          + beta * np.maximum(0.0, T_STAR - arr_ff)
          + gamma * np.maximum(0.0, arr_ff - T_STAR)
          + np.asarray(toll, float))
    out = np.where(valid & np.isfinite(sm), sm, cf)
    return out, q_hat, cf, valid


def logit_map(total, cost, theta):
    z = -(cost - cost.min()) / theta
    w = np.exp(z - z.max())
    return w / w.sum() * total


def eg_map(n, cost, kappa, nu):
    """Exponentiated-gradient / replicator response (multiplicative)."""
    scale = float(np.mean(cost))
    w = np.maximum(n, nu) * np.exp(-kappa * (cost - cost.min()) / scale)
    return w / w.sum() * n.sum()


def msa_aon_map(total, cost):
    y = np.zeros_like(cost)
    y[int(np.argmin(cost))] = total
    return y



def advect_map(n, cost, eta, diffuse=0.04, frac_max=0.25):
    """PRIMARY update rule: a local, gradient-following shift of travellers along the
    departure-time axis, rather than a jump to the globally cheapest slot.

    Each slot's occupants are nudged by dt = -eta * dc/dt (clipped to at most one slot
    per iteration, a CFL condition), so a fraction |dt|/SLOT of them moves to the
    adjacent slot in the downhill direction. A small diffusion term keeps the profile
    smooth and lets travellers spread into an adjacent empty slot.

    Fixed point <=> dc/dt = 0 across every used slot <=> equal cost on used slots,
    which is exactly the departure-time user-equilibrium condition. Unlike a logit or
    all-or-nothing auxiliary this never creates spikes or holes, which is what made the
    earlier best-response variants oscillate on this strongly forward-coupled problem.
    """
    ns = len(n)
    g = np.zeros(ns)
    g[1:-1] = (cost[2:] - cost[:-2]) / (2.0 * SLOT)
    g[0] = (cost[1] - cost[0]) / SLOT
    g[-1] = (cost[-1] - cost[-2]) / SLOT
    dt = np.clip(-eta * g, -SLOT, SLOT)
    # cap the per-iteration migration: without it every slot with a steep gradient moves
    # 100% of its occupants in lockstep, which over-concentrates the profile and (verified)
    # drives it past equilibrium into a state where origin insertion itself becomes binding.
    frac = np.minimum(np.abs(dt) / SLOT, frac_max)
    move = n * frac
    out = n - move
    fwd = dt > 0
    out[1:] += np.where(fwd, move, 0.0)[:-1]
    out[:-1] += np.where(~fwd, move, 0.0)[1:]
    # mass that would leave the grid stays put
    out[0] += np.where(~fwd, move, 0.0)[0]
    out[-1] += np.where(fwd, move, 0.0)[-1]
    if diffuse > 0:
        sm = np.copy(out)
        sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        out = (1 - diffuse) * out + diffuse * sm
    return out / out.sum() * n.sum()



def swap_map(n, cost, phi=0.8, diffuse=0.05, gain_pow=0.5):
    """PRIMARY update rule: Smith-style PROPORTIONAL SWAP.

    Take a fraction of the travellers out of every departure slot whose realised cost is
    ABOVE the current demand-weighted mean and redistribute them across the slots whose
    cost is BELOW the mean.

    Fixed point <=> no slot above the mean and none below <=> every used slot has the same
    cost, i.e. exactly the departure-time user-equilibrium condition. Note the fixed point
    does not depend on `phi` or `gain_pow`; those only shape the dynamics.

    Two details that mattered in practice (both verified by failure of the naive version):
      * shedding is scaled by the weighted mean absolute deviation of cost, not by the
        single worst slot's excess -- otherwise one catastrophically expensive slot freezes
        every other slot's adjustment;
      * gains are allocated as deficit**gain_pow with gain_pow < 1, which spreads arriving
        travellers over the whole cheap region instead of piling them onto the argmin. With
        gain_pow = 1 the profile was verified to over-concentrate to ~3.6x capacity in the
        peak slot and stall with a large residual cost gap.

    Rules that were tried and do NOT work on this problem, for the record:
      * all-or-nothing / low-temperature logit best response -> oscillation, because a
        queue's externality runs forward in time and the response overshoots;
      * a purely LOCAL gradient ('advect') rule -> cannot escape a flat expensive plateau:
        verified leaving a thin tail at cost ~1800 while cost ~550 was available 1400 s
        earlier, since the local cost gradient in that tail was ~0.
    """
    n = np.asarray(n, float)
    tot = n.sum()
    w = n if n.sum() > 0 else np.ones_like(n)
    cbar = float(np.average(cost, weights=w))
    mad = float(np.average(np.abs(cost - cbar), weights=w))
    scale = max(2.0 * mad, 1e-6)
    excess = np.maximum(0.0, cost - cbar)
    deficit = np.maximum(0.0, cbar - cost)
    if excess.max() <= 0 or deficit.sum() <= 0:
        return n.copy()
    give = np.minimum(phi * n * np.minimum(1.0, excess / scale), n)
    moved = give.sum()
    gw = deficit ** gain_pow
    out = n - give + moved * (gw / gw.sum())
    if diffuse > 0:
        sm = np.copy(out)
        sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        out = (1 - diffuse) * out + diffuse * sm
    out = np.maximum(out, 0.0)
    return out / out.sum() * tot


def initial_profile(N, lo=2000.0, hi=4200.0):
    """Deliberately NOT the analytical answer: a broad uniform block."""
    starts = slot_starts()
    return largest_remainder((starts >= lo) & (starts < hi), N)


# ------------------------------------------------------------------ main loop
def equilibrate(name, toll_by_slot, tf_free, iters=400, scheme="swap",
                theta_hi=120.0, theta_lo=6.0, anneal_iters=250,
                lam_exp=0.6, rho=0.30, kappa=6.0, nu=0.6,
                eta0=40.0, eta_m0=60.0, diffuse=0.04, frac_max=0.25, phi=0.8, gain_pow=0.5,
                beta=BETA, gamma=GAMMA, N=N_COMMUTERS, seed=1,
                outdir=None, init=None, verbose_every=25):
    outdir = outdir or os.path.join(WORK, "eq_" + name)
    os.makedirs(outdir, exist_ok=True)
    toll_by_slot = np.asarray(toll_by_slot, float)
    assert len(toll_by_slot) == NSLOT

    n = (initial_profile(N) if init is None else np.asarray(init, float).copy()).astype(float)
    trace = []
    prev_int = largest_remainder(n, N)
    c_bar = None

    ed_add = os.path.join(outdir, "ed.add.xml")
    ed_out = os.path.join(outdir, "edgedata.xml")
    write_edgedata_add(ed_add, ed_out, freq=30)
    rou = os.path.join(outdir, "it.rou.xml")
    ti = os.path.join(outdir, "it.tripinfo.xml")

    for m in range(iters):
        counts = largest_remainder(n, N)
        slot_of = write_routes(counts, rou)
        run_sumo(rou, ti, seed=seed, extra_add=[ed_add])
        recs = parse_tripinfo(ti)
        assert len(recs) == N, "only %d of %d vehicles finished" % (len(recs), N)
        rows = vehicle_costs(recs, slot_of, tf_free, toll_by_slot, beta=beta, gamma=gamma)
        cnt, mean_c, mean_q = slot_stats(rows)
        c_now, q_hat, cf, valid = build_cost_signal(rows, cnt, tf_free, toll_by_slot, beta, gamma)

        # --- device 2: MSA/exponential smoothing of the cost signal across iterations
        c_bar = c_now if c_bar is None else (1 - rho) * c_bar + rho * c_now

        # --- convergence diagnostics on the CURRENT (pre-update) profile
        allc = np.array([r["cost"] for r in rows])
        core = np.where(cnt >= 0.01 * N)[0]          # slots holding >= 1% of the population
        used3 = np.where(cnt >= 3)[0]
        def spread(idx):
            if len(idx) == 0:
                return float("nan"), float("nan"), float("nan")
            cc = mean_c[idx]
            mu = float(np.average(cc, weights=cnt[idx]))
            return ((cc.max() - cc.min()) / mu,
                    float(np.sqrt(np.average((cc - mu) ** 2, weights=cnt[idx]))) / mu, mu)
        core_gap, core_sd, core_mu = spread(core)
        u3_gap, u3_sd, u3_mu = spread(used3)
        unused = np.where(cnt == 0)[0]
        cheapest_unused = float(cf[unused].min()) if len(unused) else float("nan")

        # --- device 1/3: auxiliary profile + MSA blend
        lam = 1.0 / (m + 1) ** lam_exp
        frac = min(1.0, m / max(1.0, anneal_iters))
        th = theta_hi * (theta_lo / theta_hi) ** frac      # geometric annealing
        eta = eta0 / (1.0 + m / eta_m0)
        if scheme == "swap":
            aux = swap_map(n, c_bar, phi=phi, diffuse=diffuse, gain_pow=gain_pow)
        elif scheme == "swap_advect":
            aux = advect_map(swap_map(n, c_bar, phi=phi, diffuse=diffuse, gain_pow=gain_pow),
                             c_bar, eta, 0.0, frac_max)
        elif scheme == "advect":
            # Strong local response, then MSA averaging with a decreasing step. The MSA
            # step -- not the response -- is what makes this converge: the bare advection
            # (lam == 1) was verified to settle into a LIMIT CYCLE that straddles the
            # equilibrium (over-concentrate -> queue builds -> spread out -> queue drains).
            aux = advect_map(n, c_bar, eta, diffuse, frac_max)
        elif scheme == "logit":
            aux = logit_map(N, c_bar, th)
        elif scheme == "eg":
            aux = eg_map(n, c_bar, kappa, nu)
        elif scheme == "hybrid":
            aux = 0.5 * logit_map(N, c_bar, th) + 0.5 * eg_map(n, c_bar, kappa, nu)
        elif scheme == "msa_aon":
            aux = msa_aon_map(N, c_bar)
            lam = 1.0 / (m + 1)
        else:
            raise ValueError(scheme)
        newn = (1 - lam) * n + lam * aux
        new_int = largest_remainder(newn, N)
        changed = 0.5 * np.abs(new_int - prev_int).sum() / N

        trace.append(dict(iter=m, lam=float(lam), theta=float(th),
                          mean_cost=float(allc.mean()),
                          sd_cost=float(allc.std(ddof=1)),
                          mean_excess=float(np.mean([r["excess"] for r in rows])),
                          mean_queue=float(np.mean([r["queue"] for r in rows])),
                          max_queue=float(np.max([r["queue"] for r in rows])),
                          mean_toll=float(np.mean([r["toll"] for r in rows])),
                          mean_depart_delay=float(np.mean([r["depart_delay"] for r in rows])),
                          n_used_slots=int((cnt > 0).sum()), n_core_slots=int(len(core)),
                          eta=float(eta),
                          core_gap_rel=core_gap, core_sd_rel=core_sd, core_mean_cost=core_mu,
                          core_share=float(cnt[core].sum() / N) if len(core) else float("nan"),
                          used3_gap_rel=u3_gap, used3_sd_rel=u3_sd,
                          mean_used_cost=u3_mu,
                          cheapest_unused_cost=cheapest_unused,
                          frac_changed_slot=float(changed)))
        prev_int = new_int
        n = newn
        if verbose_every and (m % verbose_every == 0 or m == iters - 1):
            print("  [%s] it=%3d lam=%.3f th=%5.1f meanCost=%7.1f coreGap=%.4f coreSd=%.4f "
                  "used=%3d chg=%.3f meanQ=%6.1f dd=%.2f"
                  % (name, m, lam, th, allc.mean(), core_gap, core_sd,
                     (cnt > 0).sum(), changed, np.mean([r["queue"] for r in rows]),
                     np.mean([r["depart_delay"] for r in rows])), flush=True)

    # ---------------- final converged profile, simulated once more and kept
    counts = largest_remainder(n, N)
    rou_f = os.path.join(outdir, "final.rou.xml")
    ti_f = os.path.join(outdir, "final.tripinfo.xml")
    add_f = os.path.join(outdir, "final_ed.add.xml")
    ed_f = os.path.join(outdir, "final_edgedata.xml")
    write_edgedata_add(add_f, ed_f, freq=30)
    slot_of = write_routes(counts, rou_f)
    run_sumo(rou_f, ti_f, seed=seed, extra_add=[add_f])
    recs = parse_tripinfo(ti_f)
    rows = vehicle_costs(recs, slot_of, tf_free, toll_by_slot, beta=beta, gamma=gamma)
    cnt, mean_c, mean_q = slot_stats(rows)
    c_sig, q_hat, cf, valid = build_cost_signal(rows, cnt, tf_free, toll_by_slot, beta, gamma)

    res = dict(name=name, scheme=scheme, iters=iters, seed=seed,
               alpha=ALPHA, beta=beta, gamma=gamma, N=N, tf_free=tf_free,
               theta_hi=theta_hi, theta_lo=theta_lo, anneal_iters=anneal_iters,
               lam_exp=lam_exp, rho=rho, eta0=eta0, eta_m0=eta_m0, diffuse=diffuse,
               frac_max=frac_max, phi=phi, gain_pow=gain_pow,
               counts=counts.tolist(), toll=toll_by_slot.tolist(),
               slot_cnt=cnt.tolist(), slot_mean_cost=mean_c.tolist(),
               slot_mean_queue=mean_q.tolist(),
               smoothed_cost=c_sig.tolist(), smoothed_queue=q_hat.tolist(),
               counterfactual_cost=cf.tolist(),
               trace=trace, outdir=outdir,
               final_tripinfo=ti_f, final_routes=rou_f, final_edgedata=ed_f)
    with open(os.path.join(outdir, "result.json"), "w") as f:
        json.dump(res, f, indent=2)
    np.save(os.path.join(outdir, "counts.npy"), counts)
    return res, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--scheme", default="swap")
    ap.add_argument("--toll", default="none")
    ap.add_argument("--gamma", type=float, default=GAMMA)
    ap.add_argument("--beta", type=float, default=BETA)
    ap.add_argument("--theta-lo", type=float, default=6.0)
    ap.add_argument("--theta-hi", type=float, default=120.0)
    ap.add_argument("--anneal", type=int, default=250)
    ap.add_argument("--lam-exp", type=float, default=0.6)
    ap.add_argument("--rho", type=float, default=0.30)
    ap.add_argument("--kappa", type=float, default=6.0)
    ap.add_argument("--eta0", type=float, default=40.0)
    ap.add_argument("--eta-m0", type=float, default=60.0)
    ap.add_argument("--diffuse", type=float, default=0.04)
    ap.add_argument("--frac-max", type=float, default=0.25)
    ap.add_argument("--phi", type=float, default=0.8)
    ap.add_argument("--gain-pow", type=float, default=0.5)
    a = ap.parse_args()

    cap = json.load(open(os.path.join(WORK, "capacity", "capacity.json")))
    tf = cap["free_flow"]["tf_mean"]
    if a.toll in ("none", "zero"):
        toll = np.zeros(NSLOT)
    elif a.toll.startswith("file:"):
        toll = np.load(a.toll[5:])
    elif a.toll.startswith("flat:"):
        toll = np.full(NSLOT, float(a.toll[5:]))
    else:
        raise ValueError(a.toll)

    print("Equilibrating '%s' scheme=%s iters=%d beta=%.2f gamma=%.2f Tf=%.2f toll=%s"
          % (a.name, a.scheme, a.iters, a.beta, a.gamma, tf, a.toll), flush=True)
    res, rows = equilibrate(a.name, toll, tf, iters=a.iters, scheme=a.scheme,
                            beta=a.beta, gamma=a.gamma, theta_lo=a.theta_lo,
                            theta_hi=a.theta_hi, anneal_iters=a.anneal,
                            lam_exp=a.lam_exp, rho=a.rho, kappa=a.kappa,
                            eta0=a.eta0, eta_m0=a.eta_m0, diffuse=a.diffuse,
                            frac_max=a.frac_max, phi=a.phi, gain_pow=a.gain_pow)
    t = res["trace"][-1]
    print("FINAL %s: meanCost=%.1f coreGap=%.4f coreSd=%.4f used=%d chg=%.4f"
          % (a.name, t["mean_cost"], t["core_gap_rel"], t["core_sd_rel"],
             t["n_used_slots"], t["frac_changed_slot"]))
