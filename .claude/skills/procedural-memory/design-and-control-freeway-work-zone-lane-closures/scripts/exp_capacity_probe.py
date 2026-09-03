"""Queue-release capacity probe -- the correct unobstructed reference for H1.

WHY THIS EXISTS.  The first attempt measured the "unobstructed" 3-lane reference by
loading the corridor at 8400 veh/h and reading the activity-area E1 station.  That
measurement was INVALID: only 4650 of 8447 vehicles were ever inserted, and the upstream
station read the same ~4100 veh/h as the downstream one, i.e. the corridor was running at
SUMO's INSERTION throughput (~1370 veh/h/lane at departSpeed="max"), not at road
capacity.  A flat overloaded demand cannot saturate a free-flowing multilane freeway in
SUMO, because insertion at a single source edge is itself the binding constraint.

THE FIX, borrowed from `measure-saturation-flow-and-validate-webster-method`: create the
queue physically, then release it.  Blocker vehicles are parked across every lane at the
start of the termination area for a fixed window; a standing queue builds back over the
activity area; the blockers are removed and the E1 station at the activity-area exit then
records a genuine QUEUE-DISCHARGE rate for that segment.

Reported separately from the work-zone numbers on purpose: this probe measures the
capacity of the ROADWAY SEGMENT itself (no merge involved), whereas work-zone capacity is
set by the forced merge at the taper.  They are different quantities and mixing them is
the mistake this script exists to avoid.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo/tools")
import traci  # noqa: E402

import wz_common as W  # noqa: E402
import gen_demand  # noqa: E402
import gen_additional as GA  # noqa: E402
import analyze  # noqa: E402
import stats_util as S  # noqa: E402

OUTD = os.path.join(W.OUT, "capacity_probe")
os.makedirs(OUTD, exist_ok=True)
BLOCK_START, BLOCK_END, END = 600.0, 1500.0, 3600.0
STEP = 0.5


def probe(lanes_closed, wz_speed, seed, peak=4200, label=None):
    p = W.params(lanes_closed=lanes_closed, wz_speed_kmh=wz_speed)
    net = W.build_net(p, "geom", merge="priority")
    lab = label or f"probe_lc{lanes_closed}_v{wz_speed}_s{seed}"
    od = os.path.join(OUTD, lab)
    os.makedirs(od, exist_ok=True)
    rou, _ = gen_demand.gen(peak, 700 + seed, 0.0,
                            out=os.path.join(od, "dem.rou.xml"),
                            profile=[(0, 3000, 1.0)])
    add = GA.build(net, od, lab, e2=True)
    n_open = W.MAIN_LANES - lanes_closed

    traci.start([W.SUMO, "-n", net, "-r", rou, "-a", add, "--begin", "0",
                 "--end", str(END), "--step-length", str(STEP), "--seed", str(seed),
                 "--step-method.ballistic", "--time-to-teleport", "1200",   # MUST exceed the 900 s blockage or the
                 # probe manufactures teleports out of its own gate (teleport skill)
                 "--no-step-log", "true", "--no-warnings", "true",
                 "--summary-output", f"{od}/summary.xml",
                 "--tripinfo-output", f"{od}/tripinfo.xml",
                 "--collision-output", f"{od}/collisions.xml",
                 "--collision.action", "warn"], label=lab)
    c = traci.getConnection(lab)
    c.route.add("blk", ["fF", "fG"])
    blockers, placed, removed = [], False, False
    t = 0.0
    while t < END:
        c.simulationStep()
        t = c.simulation.getTime()
        if not placed and t >= BLOCK_START:
            for i in range(n_open):
                vid = f"blk{i}"
                c.vehicle.add(vid, "blk", typeID="car", depart="now",
                              departLane=str(i), departPos="5", departSpeed="0")
                c.vehicle.setStop(vid, "fF", pos=20.0, laneIndex=i,
                                  duration=BLOCK_END - BLOCK_START)
                c.vehicle.setSpeedMode(vid, 0)
                blockers.append(vid)
            placed = True
        if not removed and t >= BLOCK_END:
            for vid in blockers:
                try:
                    c.vehicle.remove(vid)
                except traci.TraCIException:
                    pass
            removed = True
    c.close()   # must close BEFORE parsing: SUMO only flushes its outputs on shutdown
    s = analyze.read_summary(f"{od}/summary.xml")

    # discharge over the release window, excluding a 120 s restart transient
    e1 = analyze.read_e1(os.path.join(od, "e1_disch.xml"))
    byt = defaultdict(float)
    for r in e1:
        if r["id"].startswith("det_disch"):
            byt[r["begin"]] += r["flow"]
    win = [byt[t0] for t0 in sorted(byt)
           if BLOCK_END + 120 <= t0 < BLOCK_END + 1200 and byt[t0] > 0]
    # verify a standing queue actually existed at release
    q, spd = analyze.queued_intervals(od)
    queued_at_release = any(BLOCK_START <= t0 <= BLOCK_END for t0 in q)
    return dict(lanes_closed=lanes_closed, wz_speed=wz_speed, seed=seed,
                n_open=n_open, series=[byt[t0] for t0 in sorted(byt)],
                cap_total=float(np.mean(win)) if win else np.nan,
                cap_per_lane=float(np.mean(win)) / n_open if win else np.nan,
                n_intervals=len(win), queued_at_release=bool(queued_at_release),
                teleports=s.get("teleports"), inserted=s.get("inserted"),
                loaded=s.get("loaded"), collisions=s.get("collisions"))


if __name__ == "__main__":
    rows = []
    for lc, v in ((0, 120), (0, 80), (1, 80), (2, 80)):
        for sd in (1, 2, 3):
            r = probe(lc, v, sd)
            rows.append(r)
            print(f"lc={lc} v={v} s={sd}: {r['cap_per_lane']:.0f} pc/h/ln "
                  f"(total {r['cap_total']:.0f}, n={r['n_intervals']}, "
                  f"queued={r['queued_at_release']}, tele={r['teleports']})", flush=True)
    json.dump(rows, open(os.path.join(OUTD, "probe_results.json"), "w"),
              indent=1, default=float)
    print()
    for lc, v in ((0, 120), (0, 80), (1, 80), (2, 80)):
        sel = [r["cap_per_lane"] for r in rows
               if r["lanes_closed"] == lc and r["wz_speed"] == v]
        c = S.mean_ci(sel)
        print(f"lc={lc} v={v}: {c['mean']:.0f} [{c['lo']:.0f}, {c['hi']:.0f}] pc/h/ln")
