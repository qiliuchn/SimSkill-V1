"""Testbed (a) part 2: STRING STABILITY via a TraCI brake pulse on the ring.

A route-file <stop> cannot express "brake for 3 s at t=300 s" on a 1 km ring (the
vehicle reaches the stop position on its first lap and then blocks the ring until
`until`), so the perturbation is applied through TraCI instead: at t=PULSE_T the lead
vehicle's speed is clamped to 0 for PULSE_DUR seconds, then released.

Outputs per cell: pulse depth (fractional drop in ring mean speed), recovery time,
and the residual speed dispersion in the tail (does the wave persist = string
instability, or wash out = string stability).

This script ALSO records TraCI wall-clock, feeding the runtime/cost layer.
"""
import os
import sys
import math
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (NET, RUNS, SEEDS, SUMO_HOME, cells, cell_id, cell_args, asl_value,
                      vtype_xml, DEFAULT_CAR, mean, sd, ci95, savejson)
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import traci                                        # noqa
import exp_a_ring as R                              # noqa

K_PULSE = 22          # near-critical density (k_crit ~ 26 veh/km)
PULSE_T, PULSE_DUR = 300.0, 4.0
END = 700.0
BASE = os.path.join(RUNS, "a_stab")
os.makedirs(BASE, exist_ok=True)


def stab_cell(job):
    c, seed = job
    d = os.path.join(BASE, "%s_s%d" % (cell_id(c), seed))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    vt = vtype_xml("car", DEFAULT_CAR, asl=asl_value(c))
    rou = os.path.join(d, "r.rou.xml")
    R.END = END
    R.write_ring_routes(rou, K_PULSE, vt, 0.9)
    dt = float(c[0])
    label = "stab_%s_%d" % (cell_id(c), seed)
    cmd = ["sumo", "-n", R.RING, "-r", rou, "--begin", "0", "--end", str(END),
           "--time-to-teleport", "-1", "--collision.action", "warn",
           "--no-step-log", "true", "--xml-validation", "never",
           "--duration-log.disable", "true", "--seed", str(seed)] + cell_args(c)
    t0 = time.perf_counter()
    traci.start(cmd, label=label)
    conn = traci.getConnection(label)
    ts, vs = [], []
    released = False
    t = 0.0
    nsteps = 0
    try:
        while t < END - dt / 2:
            conn.simulationStep()
            nsteps += 1
            t = conn.simulation.getTime()
            ids = conn.vehicle.getIDList()
            if ids:
                ts.append(t)
                vs.append(sum(conn.vehicle.getSpeed(v) for v in ids) / len(ids))
            if abs(t - PULSE_T) < dt / 2 and "v0" in ids:
                conn.vehicle.setSpeed("v0", 0.0)
            if not released and t >= PULSE_T + PULSE_DUR and "v0" in ids:
                conn.vehicle.setSpeed("v0", -1.0)     # -1 => hand control back to the CF model
                released = True
    finally:
        conn.close()
    wall = time.perf_counter() - t0
    pre = [v for tt, v in zip(ts, vs) if PULSE_T - 60 <= tt < PULSE_T]
    win = [(tt, v) for tt, v in zip(ts, vs) if PULSE_T <= tt <= PULSE_T + 250]
    tail = [v for tt, v in zip(ts, vs) if tt >= PULSE_T + 250]
    if not pre or not win:
        return dict(cell=cell_id(c), seed=seed, ok=False, err="empty windows")
    v_pre = mean(pre)
    v_min = min(v for _, v in win)
    t_min = [tt for tt, v in win if v == v_min][0]
    # recovery: first time after t_min that ring mean speed returns within 2% of v_pre
    rec = [tt for tt, v in win if tt > t_min and v >= 0.98 * v_pre]
    return dict(cell=cell_id(c), dt=dt, method=c[1], asl=c[2], seed=seed, ok=True,
                wall_traci=wall, n_steps=nsteps, v_pre=v_pre, v_min=v_min,
                depth_frac=(v_pre - v_min) / v_pre,
                t_to_min=t_min - PULSE_T,
                recovery_s=(rec[0] - PULSE_T) if rec else float("nan"),
                recovered=bool(rec),
                v_sd_pre=sd(pre), v_sd_tail=sd(tail) if tail else float("nan"),
                v_tail=mean(tail) if tail else float("nan"))


if __name__ == "__main__":
    jobs = [(c, s) for c in cells() for s in SEEDS[:3]]
    print("string stability: %d TraCI runs" % len(jobs))
    rows = [stab_cell(j) for j in jobs]     # serial: traci labels are process-global
    savejson("a_stability.json", rows)
    print("%-24s %14s %10s %10s %10s %9s" %
          ("cell", "depth_frac", "t_to_min", "recov_s", "sd_tail", "wall_s"))
    agg = {}
    for c in cells():
        cid = cell_id(c)
        rr = [r for r in rows if r.get("ok") and r["cell"] == cid]
        if not rr:
            continue
        m, h = ci95([r["depth_frac"] for r in rr])
        agg[cid] = dict(depth_frac=m, depth_ci=h,
                        t_to_min=mean([r["t_to_min"] for r in rr]),
                        recovery_s=mean([r["recovery_s"] for r in rr]),
                        n_recovered=sum(1 for r in rr if r["recovered"]),
                        v_sd_tail=mean([r["v_sd_tail"] for r in rr]),
                        v_sd_pre=mean([r["v_sd_pre"] for r in rr]),
                        wall_traci=mean([r["wall_traci"] for r in rr]),
                        n_steps=rr[0]["n_steps"])
        a = agg[cid]
        print("%-24s %8.4f+-%.4f %10.1f %10.1f %10.4f %9.2f" %
              (cid, m, h, a["t_to_min"], a["recovery_s"], a["v_sd_tail"], a["wall_traci"]))
    savejson("a_stability_agg.json", agg)
