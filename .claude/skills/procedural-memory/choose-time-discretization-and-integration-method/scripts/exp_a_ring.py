"""Testbed (a): single-lane closed ring -> fundamental diagram / capacity / string stability.

On a closed ring density is EXACT (k = 1000*N/L), so q = k*v needs no detector estimate
(methodology from `validate-kinematic-wave-theory-across-car-following-models`).

Per factorial cell we sweep N over 12 density levels x CRN seeds, fit
  * capacity q_max (parabola through the peak cell and its two neighbours)
  * critical density k_crit
  * free-flow speed v_f (through-origin OLS over the three lowest-density cells)
  * jam-branch wave speed w (OLS on the congested branch)
and separately run a STRING-STABILITY probe (one vehicle brake-pulses at a
near-critical density; we measure the depth and persistence of the resulting wave).
"""
import os
import sys
import math
import shutil
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, SEEDS, cells, cell_id, cell_args, asl_value,
                      run_sumo, BASE_ARGS, read_summary, summary_totals,
                      vtype_xml, DEFAULT_CAR, mean, sd, ci95, savejson)

RING = os.path.join(NET, "ring.net.xml")
L = 1000.0
NEDGE = 16
EDGE_L = L / NEDGE
VFREE = 30.0
END, WARM = 600.0, 300.0
KS = [4, 8, 12, 16, 20, 25, 30, 40, 50, 65, 80, 100]     # vehicles on the ring == veh/km
BASE = os.path.join(RUNS, "a_ring")
os.makedirs(BASE, exist_ok=True)

RING_EDGES = " ".join("e%d" % i for i in range(NEDGE))


def route_str(laps):
    return " ".join([RING_EDGES] * laps)


def write_ring_routes(path, n, vt, dep_scale, brake_pulse=False):
    laps = int(math.ceil(END * VFREE / L)) + 3
    rt = route_str(laps)
    sp = L / n
    veq = max(0.0, min(VFREE, sp - (float(DEFAULT_CAR["length"]) + float(DEFAULT_CAR["minGap"]))))
    v0 = max(0.0, veq * dep_scale)
    lines = ["<routes>", vt]
    for i in range(n):
        s = i * sp
        idx = int(s // EDGE_L) % NEDGE
        pos = s - idx * EDGE_L
        stop = ""
        if brake_pulse and i == 0:
            # one-shot perturbation: veh0 halts for 3 s at t~=WARM on its own edge
            stop = ('<stop edge="e%d" endPos="%.2f" duration="3" '
                    'until="%.1f"/>' % (idx, min(EDGE_L - 1.0, pos + 20.0), WARM))
        lines.append('  <vehicle id="v%d" type="car" depart="0" departLane="0" '
                     'departPos="%.3f" departSpeed="%.3f" departEdge="%d">'
                     '<route edges="%s"/>%s</vehicle>'
                     % (i, pos, v0, idx, rt, stop))
    lines.append("</routes>")
    open(path, "w").write("\n".join(lines))


def ring_cell(job):
    c, k, seed, pulse = job
    tag = "%s_k%d_s%d%s" % (cell_id(c), k, seed, "_p" if pulse else "")
    d = os.path.join(BASE, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    vt = vtype_xml("car", DEFAULT_CAR, asl=asl_value(c))
    rou = os.path.join(d, "r.rou.xml")
    smy = os.path.join(d, "s.xml")
    last = None
    for dep in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0):
        write_ring_routes(rou, k, vt, dep, brake_pulse=pulse)
        r = run_sumo(["-n", RING, "-r", rou, "--summary-output", smy,
                      "--begin", "0", "--end", str(END),
                      "--time-to-teleport", "-1",
                      "--collision.action", "warn",
                      "--seed", str(seed)] + cell_args(c) + BASE_ARGS, cwd=d)
        if r["rc"] != 0:
            last = "rc=%d %s" % (r["rc"], r["err"][-300:])
            continue
        rows = read_summary(smy)
        if rows and rows[-1]["running"] >= k:
            break
        last = "underfilled %s/%d at dep=%.1f" % (rows[-1]["running"] if rows else "?", k, dep)
    else:
        return dict(cell=cell_id(c), k=k, seed=seed, pulse=pulse, ok=False, err=last)
    rows = read_summary(smy)
    tot = summary_totals(smy)
    ss = [x for x in rows if x["time"] >= WARM and x["running"] >= k]
    if not ss:
        return dict(cell=cell_id(c), k=k, seed=seed, pulse=pulse, ok=False, err="no steady rows")
    v = mean([x["meanSpeed"] for x in ss])
    vsd = sd([x["meanSpeed"] for x in ss])
    q = k * v * 3.6                    # veh/km * m/s * 3.6 -> veh/h
    res = dict(cell=cell_id(c), dt=float(c[0]), method=c[1], asl=c[2], k=k, seed=seed,
               pulse=pulse, ok=True, wall=r["wall"], v=v, v_sd=vsd, q=q,
               teleports=tot["teleports"], collisions=tot["collisions"],
               running=tot["running"], insert_scale=dep)
    if pulse:
        after = [x for x in rows if WARM <= x["time"] <= WARM + 200]
        pre = [x for x in rows if WARM - 60 <= x["time"] < WARM]
        v_pre = mean([x["meanSpeed"] for x in pre]) if pre else float("nan")
        v_min = min([x["meanSpeed"] for x in after]) if after else float("nan")
        tail = [x for x in rows if x["time"] >= WARM + 200]
        res.update(v_pre=v_pre, v_min_after_pulse=v_min,
                   pulse_depth_frac=(v_pre - v_min) / v_pre if v_pre else float("nan"),
                   v_sd_tail=sd([x["meanSpeed"] for x in tail]) if tail else float("nan"),
                   v_tail=mean([x["meanSpeed"] for x in tail]) if tail else float("nan"))
    return res


# --------------------------------------------------------------- FD fitting
def fit_fd(cellrows):
    """cellrows: list of dicts with k,q,v (already averaged over seeds)."""
    pts = sorted([(r["k"], r["q"], r["v"]) for r in cellrows if r["ok"]])
    if len(pts) < 5:
        return None
    ks = [p[0] for p in pts]
    qs = [p[1] for p in pts]
    i = qs.index(max(qs))
    # parabola through peak and neighbours -> unquantised q_max, k_crit
    if 0 < i < len(pts) - 1:
        x1, x2, x3 = ks[i - 1], ks[i], ks[i + 1]
        y1, y2, y3 = qs[i - 1], qs[i], qs[i + 1]
        den = (x1 - x2) * (x1 - x3) * (x2 - x3)
        A = (x3 * (y2 - y1) + x2 * (y1 - y3) + x1 * (y3 - y2)) / den
        B = (x3 * x3 * (y1 - y2) + x2 * x2 * (y3 - y1) + x1 * x1 * (y2 - y3)) / den
        C = (x2 * x3 * (x2 - x3) * y1 + x3 * x1 * (x3 - x1) * y2 + x1 * x2 * (x1 - x2) * y3) / den
        kc = -B / (2 * A) if A < 0 else ks[i]
        qm = A * kc * kc + B * kc + C if A < 0 else qs[i]
    else:
        kc, qm = ks[i], qs[i]
    low = pts[:3]
    vf = sum(p[1] for p in low) / sum(p[0] for p in low)      # through-origin OLS q=vf*k
    cong = [p for p in pts if p[0] > kc]
    w = float("nan")
    r2 = float("nan")
    if len(cong) >= 3:
        xs = [p[0] for p in cong]
        ys = [p[1] for p in cong]
        mx, my = mean(xs), mean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        w = sxy / sxx if sxx else float("nan")
        yh = [my + w * (x - mx) for x in xs]
        sst = sum((y - my) ** 2 for y in ys)
        sse = sum((y - h) ** 2 for y, h in zip(ys, yh))
        r2 = 1 - sse / sst if sst else float("nan")
    return dict(q_max=qm, k_crit=kc, v_free_kmh=vf, w_kmh=w, cong_r2=r2,
                k_peak_grid=ks[i], q_peak_grid=qs[i])


if __name__ == "__main__":
    jobs = [(c, k, s, False) for c in cells() for k in KS for s in SEEDS[:3]]
    print("testbed (a): %d ring runs" % len(jobs))
    with ProcessPoolExecutor(max_workers=9) as ex:
        rows = list(ex.map(ring_cell, jobs))
    savejson("a_ring_runs.json", rows)
    bad = [r for r in rows if not r.get("ok")]
    print("failed:", len(bad), bad[:2])
    fits = {}
    print("\n%-24s %9s %8s %9s %9s %7s %6s %6s" %
          ("cell", "q_max", "k_crit", "v_f km/h", "w km/h", "congR2", "coll", "tele"))
    for c in cells():
        cid = cell_id(c)
        agg = []
        for k in KS:
            rr = [r for r in rows if r.get("ok") and r["cell"] == cid and r["k"] == k and not r["pulse"]]
            if rr:
                agg.append(dict(ok=True, k=k, q=mean([r["q"] for r in rr]),
                                v=mean([r["v"] for r in rr]),
                                q_sd=sd([r["q"] for r in rr]),
                                coll=sum(r["collisions"] for r in rr),
                                tele=sum(r["teleports"] for r in rr)))
        f = fit_fd(agg)
        fits[cid] = dict(fit=f, cells=agg,
                         collisions=sum(a["coll"] for a in agg),
                         teleports=sum(a["tele"] for a in agg))
        if f:
            print("%-24s %9.1f %8.2f %9.2f %9.2f %7.4f %6d %6d" %
                  (cid, f["q_max"], f["k_crit"], f["v_free_kmh"], f["w_kmh"], f["cong_r2"],
                   fits[cid]["collisions"], fits[cid]["teleports"]))
    savejson("a_ring_fits.json", fits)
    print("\n(string stability is measured separately by exp_a_stability.py, "
          "which applies the brake pulse via TraCI at t=WARM)")
