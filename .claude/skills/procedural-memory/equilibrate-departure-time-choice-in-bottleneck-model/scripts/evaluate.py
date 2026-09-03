"""
Step 3/4/5 support. Evaluate a CONVERGED departure profile:
  * multi-seed replication with Common Random Numbers across conditions
  * per-vehicle cost decomposition (queueing / early / late / toll)
  * bottleneck discharge check -- the toll must never touch the physics
  * marginal-traveller PROBE test of the equilibrium condition
"""
import os, sys, json, csv
import numpy as np
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
from equilibrate import largest_remainder

EVAL_SEEDS = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]   # CRN: identical list for every condition


def simulate_profile(counts, outdir, seed, tag="run"):
    """One fully instrumented simulation of a given departure profile."""
    os.makedirs(outdir, exist_ok=True)
    rou = os.path.join(outdir, "%s_s%d.rou.xml" % (tag, seed))
    ti = os.path.join(outdir, "%s_s%d.tripinfo.xml" % (tag, seed))
    add = os.path.join(outdir, "%s_s%d.add.xml" % (tag, seed))
    ed = os.path.join(outdir, "%s_s%d.edgedata.xml" % (tag, seed))
    loop = os.path.join(outdir, "%s_s%d.loop.xml" % (tag, seed))
    with open(add, "w") as f:
        f.write('<additional>\n')
        f.write('    <edgeData id="ed" freq="30" file="%s" excludeEmpty="false"/>\n' % os.path.abspath(ed))
        f.write('    <inductionLoop id="loopBN" lane="E2_0" pos="300" freq="30" file="%s"/>\n'
                % os.path.abspath(loop))
        f.write('</additional>\n')
    slot_of = write_routes(counts, rou)
    run_sumo(rou, ti, seed=seed, extra_add=[add])
    return dict(routes=rou, tripinfo=ti, edgedata=ed, loop=loop, slot_of=slot_of)


def bottleneck_discharge(loop_xml, lo=None, hi=None, min_speed_sat=None, edgedata=None):
    """Sustained discharge rate at the bottleneck, measured over the intervals during
    which the upstream approach is genuinely queued (so it is a CAPACITY measurement,
    not just a demand measurement)."""
    lr = ET.parse(loop_xml).getroot()
    ivs = [(float(i.get("begin")), float(i.get("end")), int(i.get("nVehContrib"))) for i in lr]
    e1speed = {}
    if edgedata:
        for b, e, edges in parse_edgedata(edgedata):
            v = edges.get("E1", {}).get("speed")
            e1speed[b] = float(v) if v is not None else -1.0
    sat = []
    for b, e, n in ivs:
        v1 = e1speed.get(b, -1.0)
        if v1 >= 0 and v1 < 12.0 and n > 0:
            sat.append(n * 3600.0 / (e - b))
    tot = sum(n for _, _, n in ivs)
    return dict(n_sat_intervals=len(sat),
                discharge_saturated_vph=float(np.mean(sat)) if sat else float("nan"),
                total_crossings=tot)


def queue_curves(rows, tf_free, dt=10.0):
    """Newell cumulative curves + vertical queue length, from the raw per-vehicle record.

    D(t)  = cumulative departures from the origin (intended departure time)
    V(t)  = D(t - Tf) = 'virtual arrivals', what arrivals WOULD be with no queue
    A(t)  = cumulative arrivals at the destination
    Q(t)  = V(t) - A(t)  (vehicles held in the queue)
    """
    dep = np.sort([r["depart"] for r in rows])
    arr = np.sort([r["arrival"] for r in rows])
    t0 = min(dep.min(), arr.min() - tf_free) - 120
    t1 = arr.max() + 120
    grid = np.arange(t0, t1 + dt, dt)
    D = np.searchsorted(dep, grid, side="right").astype(float)
    V = np.searchsorted(dep, grid - tf_free, side="right").astype(float)
    A = np.searchsorted(arr, grid, side="right").astype(float)
    Q = V - A
    return grid, D, V, A, np.maximum(Q, 0.0)


def summarize(rows, tf_free, alpha=ALPHA):
    q = np.array([r["queue"] for r in rows])
    sde = np.array([r["sde"] for r in rows])
    sdl = np.array([r["sdl"] for r in rows])
    toll = np.array([r["toll"] for r in rows])
    cost = np.array([r["cost"] for r in rows])
    exc = np.array([r["excess"] for r in rows])
    dd = np.array([r["depart_delay"] for r in rows])
    dep = np.array([r["depart"] for r in rows])
    arr = np.array([r["arrival"] for r in rows])
    return dict(
        n=len(rows),
        mean_queue_delay=float(q.mean()), max_queue_delay=float(q.max()),
        total_queue_delay=float(q.sum()),
        mean_depart_delay=float(dd.mean()), max_depart_delay=float(dd.max()),
        mean_sde=float(sde.mean()), mean_sdl=float(sdl.mean()),
        frac_early=float((arr < T_STAR).mean()), frac_late=float((arr > T_STAR).mean()),
        c_queue=float(alpha * q.mean()), c_early=float(BETA * sde.mean()),
        c_late=float(GAMMA * sdl.mean()), c_toll=float(toll.mean()),
        c_freeflow=float(alpha * tf_free),
        mean_cost=float(cost.mean()), sd_cost=float(cost.std(ddof=1)),
        mean_excess_cost=float(exc.mean()),
        total_toll_revenue=float(toll.sum()),
        first_depart=float(dep.min()), last_depart=float(dep.max()),
        peak_len=float(dep.max() - dep.min()),
        first_arrival=float(arr.min()), last_arrival=float(arr.max()),
    )


def evaluate_condition(name, counts, toll, tf_free, outdir, seeds=EVAL_SEEDS,
                       beta=BETA, gamma=GAMMA):
    os.makedirs(outdir, exist_ok=True)
    toll = np.asarray(toll, float)
    per_seed, all_rows = [], {}
    for sd in seeds:
        f = simulate_profile(counts, outdir, sd, tag=name)
        recs = parse_tripinfo(f["tripinfo"])
        rows = vehicle_costs(recs, f["slot_of"], tf_free, toll, beta=beta, gamma=gamma)
        s = summarize(rows, tf_free)
        s.update(bottleneck_discharge(f["loop"], edgedata=f["edgedata"]))
        s["seed"] = sd
        s["condition"] = name
        per_seed.append(s)
        all_rows[sd] = rows
    return per_seed, all_rows


# ------------------------------------------------------------------ probe test
def probe_unused_slots(counts, toll, tf_free, outdir, seed=1, batch_gap=8,
                       beta=BETA, gamma=GAMMA, probes_per_slot=1):
    """Empirical marginal-traveller test: insert a handful of extra 'probe' commuters into
    slots the equilibrium does NOT use, and measure what they ACTUALLY experience in SUMO.

    Probes are added in small, widely-spaced batches (<=1% perturbation of the population)
    so they do not materially change the equilibrium they are probing.
    """
    os.makedirs(outdir, exist_ok=True)
    counts = np.asarray(counts, int)
    starts = slot_starts()
    used = np.where(counts > 0)[0]
    lo, hi = used[0] - 12, used[-1] + 12
    cand = [k for k in range(max(0, lo), min(NSLOT, hi + 1)) if counts[k] == 0]
    batches = []
    cur = []
    last = -999
    for k in cand:
        if k - last >= batch_gap:
            cur.append(k)
            last = k
        else:
            batches.append(cur) if False else None
    # build batches greedily: each batch takes every batch_gap-th remaining candidate
    remaining = list(cand)
    while remaining:
        b, last = [], -999
        rest = []
        for k in remaining:
            if k - last >= batch_gap:
                b.append(k); last = k
            else:
                rest.append(k)
        batches.append(b)
        remaining = rest

    out = []
    for bi, b in enumerate(batches):
        c2 = counts.copy()
        for k in b:
            c2[k] += probes_per_slot
        f = simulate_profile(c2, outdir, seed, tag="probe%02d" % bi)
        recs = parse_tripinfo(f["tripinfo"])
        rows = vehicle_costs(recs, f["slot_of"], tf_free, toll, beta=beta, gamma=gamma)
        by_slot = {}
        for r in rows:
            by_slot.setdefault(r["slot"], []).append(r)
        for k in b:
            rr = by_slot.get(k, [])
            if rr:
                out.append(dict(batch=bi, slot=int(k), t=float(starts[k]),
                                n_probe=len(rr),
                                probe_cost=float(np.mean([x["cost"] for x in rr])),
                                probe_queue=float(np.mean([x["queue"] for x in rr])),
                                probe_tt=float(np.mean([x["tt"] for x in rr])),
                                probe_arrival=float(np.mean([x["arrival"] for x in rr])),
                                probe_toll=float(np.mean([x["toll"] for x in rr]))))
        # also record the incumbent population's mean cost in this perturbed run,
        # so the comparison is within-run (no cross-run drift)
        inc = [r for r in rows if counts[r["slot"]] > 0]
        out[-1]["incumbent_mean_cost"] = float(np.mean([x["cost"] for x in inc])) if out else None
    return out, len(batches)
