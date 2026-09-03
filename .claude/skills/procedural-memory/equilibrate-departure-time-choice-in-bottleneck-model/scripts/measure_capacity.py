"""
Step 1. Independently MEASURE the bottleneck's discharge capacity `s` from a genuinely
saturated run, and measure the free-flow travel time `Tf` from an uncongested run.
Nothing downstream assumes a textbook capacity number.
"""
import os, json, sys
import numpy as np
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *

OUT = os.path.join(WORK, "capacity")
os.makedirs(OUT, exist_ok=True)

SEEDS = list(range(1, 7))


def free_flow_run():
    """20 vehicles released 60 s apart -> no interaction at all."""
    rou = os.path.join(OUT, "ff.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n    <route id="r" edges="E0 E1 E2 E3"/>\n')
        for i in range(20):
            f.write('    <vehicle id="ff%02d" type="commuter" route="r" depart="%.1f" '
                    'departLane="free" departSpeed="max"/>\n' % (i, 100 + 60 * i))
        f.write('</routes>\n')
    ti = os.path.join(OUT, "ff.tripinfo.xml")
    run_sumo(rou, ti, seed=1, end=3000)
    recs = parse_tripinfo(ti)
    tts = np.array([r["tt"] for r in recs.values()])
    dds = np.array([r["depart_delay"] for r in recs.values()])
    return dict(n=len(tts), tf_mean=float(tts.mean()), tf_min=float(tts.min()),
                tf_max=float(tts.max()), tf_sd=float(tts.std(ddof=1)),
                max_depart_delay=float(dds.max()), tripinfo=ti, routes=rou)


def saturated_run(seed):
    d = os.path.join(OUT, "sat_seed%d" % seed)
    os.makedirs(d, exist_ok=True)
    rou = os.path.join(d, "sat.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n    <route id="r" edges="E0 E1 E2 E3"/>\n')
        # 2400 veh/h for 1800 s -> ~1.8x the single-lane bottleneck capacity. Saturation
        # is verified per interval below (approach-edge speed), not assumed from this number.
        f.write('    <flow id="sat" route="r" type="commuter" begin="0" end="1800" '
                'vehsPerHour="2400" departLane="free" departSpeed="max"/>\n')
        f.write('</routes>\n')
    add = os.path.join(d, "det.add.xml")
    ed = os.path.join(d, "edgedata.xml")
    loop = os.path.join(d, "loop.xml")
    with open(add, "w") as f:
        f.write('<additional>\n')
        f.write('    <edgeData id="ed" freq="60" file="%s" excludeEmpty="false"/>\n' % ed)
        f.write('    <inductionLoop id="loopBN" lane="E2_0" pos="300" freq="60" file="%s"/>\n' % loop)
        f.write('</additional>\n')
    ti = os.path.join(d, "tripinfo.xml")
    run_sumo(rou, ti, seed=seed, extra_add=[add], end=5400)

    # a 60 s interval counts as SATURATED iff the upstream approach E1 is genuinely
    # queued (mean speed well below free flow) AND the bottleneck is flowing.
    eds = parse_edgedata(ed)
    lr = ET.parse(loop).getroot()
    loop_iv = {float(i.get("begin")): (int(i.get("nVehContrib")), float(i.get("speed"))) for i in lr}

    rows = []
    for b, e, edges in eds:
        e1 = edges.get("E1", {})
        e2 = edges.get("E2", {})
        v1 = float(e1.get("speed", "-1") or -1)
        left = float(e2.get("left", 0) or 0)     # vehicles that left E2 in the interval
        n_loop, v_loop = loop_iv.get(b, (0, -1))
        rows.append(dict(begin=b, end=e, v_E1=v1, E2_left=left,
                         loop_n=n_loop, loop_speed=v_loop,
                         flow_edge=left * 3600.0 / (e - b),
                         flow_loop=n_loop * 3600.0 / (e - b),
                         saturated=bool(v1 >= 0 and v1 < 12.0 and n_loop > 0)))
    sat = [r for r in rows if r["saturated"]]
    return dict(seed=seed, dir=d, rows=rows,
                n_sat_intervals=len(sat),
                sat_window=(sat[0]["begin"], sat[-1]["end"]) if sat else None,
                cap_loop=float(np.mean([r["flow_loop"] for r in sat])) if sat else float("nan"),
                cap_edge=float(np.mean([r["flow_edge"] for r in sat])) if sat else float("nan"))


if __name__ == "__main__":
    ff = free_flow_run()
    print("FREE FLOW  n=%d  Tf mean=%.2f s  min=%.2f  max=%.2f  sd=%.3f  maxDepartDelay=%.2f"
          % (ff["n"], ff["tf_mean"], ff["tf_min"], ff["tf_max"], ff["tf_sd"], ff["max_depart_delay"]))

    res = [saturated_run(s) for s in SEEDS]
    cl = np.array([r["cap_loop"] for r in res])
    ce = np.array([r["cap_edge"] for r in res])
    m_l, h_l, ci_l = mean_ci(cl)
    m_e, h_e, ci_e = mean_ci(ce)
    print("\nSATURATED runs (%d seeds), saturation defined as approach-edge E1 mean speed < 12 m/s:"
          % len(SEEDS))
    for r in res:
        print("  seed %2d  sat intervals=%2d  window=%s  loop=%.1f veh/h  edgeLeft=%.1f veh/h"
              % (r["seed"], r["n_sat_intervals"], r["sat_window"], r["cap_loop"], r["cap_edge"]))
    print("\n  MEASURED CAPACITY (induction loop on E2_0):  %.1f +/- %.1f veh/h (95%% CI %.1f..%.1f)"
          % (m_l, h_l, ci_l[0], ci_l[1]))
    print("  MEASURED CAPACITY (edgeData 'left' on E2)  :  %.1f +/- %.1f veh/h (95%% CI %.1f..%.1f)"
          % (m_e, h_e, ci_e[0], ci_e[1]))

    out = dict(free_flow=ff,
               capacity_loop_vph=m_l, capacity_loop_ci=ci_l,
               capacity_edge_vph=m_e, capacity_edge_ci=ci_e,
               capacity_vph=m_l, capacity_vps=m_l / 3600.0,
               seeds=SEEDS,
               per_seed=[{k: v for k, v in r.items() if k != "rows"} for r in res])
    with open(os.path.join(OUT, "capacity.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    # keep the per-interval trace of seed 1 for the critic
    import csv
    with open(os.path.join(OUT, "capacity_intervals_seed1.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0]["rows"][0].keys()))
        w.writeheader()
        w.writerows(res[0]["rows"])
    print("\nwrote", os.path.join(OUT, "capacity.json"))
