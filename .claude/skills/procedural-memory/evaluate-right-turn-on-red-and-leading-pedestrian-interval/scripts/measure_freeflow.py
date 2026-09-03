#!/usr/bin/env python3
"""Measure the FREE-FLOW segment traversal time per movement, per geometry
variant, empirically.

hcm-control-delay-vs-sumo-delay-metrics requires the control-delay free-flow
datum to be MEASURED (a geometric datum computed from the posted speed inflates
every control delay by 1.7-4.9 s because of Krauss dawdling plus the turn-radius
speed limit on the internal junction lane) and requires speedFactor="1.0"
speedDev="0" so the desired speed is actually pinned.

Method: ONE ISOLATED micro-run per movement - only that single movement has
demand (30 veh/h), under an all-green program.  Isolating the movement removes
every possible interaction (an all-green program with all 12 movements loaded
gridlocks - verified).  Segment = 250 m upstream of the stop line to 100 m past
the junction on the receiving edge.  The datum is the 5th percentile; the
minimum is reported alongside.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci                              # noqa: E402
import traci.constants as tc              # noqa: E402
import numpy as np                        # noqa: E402

from linkmap import LinkMap               # noqa: E402
import gen_scenario                       # noqa: E402

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs", "freeflow")
REF_UP, REF_DOWN = 250.0, 100.0


def write_allgreen(lm, path):
    s = ["r"] * lm.n
    for li in lm.veh:
        s[li] = "G"
    with open(path, "w") as f:
        f.write('<additional>\n'
                '    <tlLogic id="C" type="static" programID="allgreen" offset="0">\n'
                f'        <phase duration="100000" state="{"".join(s)}"/>\n'
                '    </tlLogic>\n</additional>\n')


def write_single(path, a, m):
    dest = gen_scenario.MOVES[a][m]
    out = ['<routes>', gen_scenario.VTYPE,
           f'    <route id="rt" edges="in_{a} out_{dest}"/>',
           '    <flow id="f" type="car" route="rt" begin="0" end="1200" '
           'vehsPerHour="30" departLane="best" departSpeed="max"/>',
           '</routes>']
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def run_movement(net, prog, a, m, tag):
    rou = os.path.join(OUT, f"{tag}.rou.xml")
    write_single(rou, a, m)
    traci.start(["sumo", "-n", net, "-r", rou, "-a", prog,
                 "--step-length", "0.5", "--begin", "0", "--end", "1500",
                 "--no-step-log", "--no-warnings", "--seed", "7"], label=tag)
    conn = traci.getConnection(tag)
    conn.trafficlight.setProgram("C", "allgreen")
    ll = conn.lane.getLength(f"in_{a}_1")
    seg_enter, times = {}, []
    t = 0.0
    while t < 1500:
        conn.simulationStep()
        t = conn.simulation.getTime()
        for vid in conn.simulation.getDepartedIDList():
            conn.vehicle.subscribe(vid, [tc.VAR_LANE_ID, tc.VAR_LANEPOSITION])
        for vid, d in conn.vehicle.getAllSubscriptionResults().items():
            lane, lp = d[tc.VAR_LANE_ID], d[tc.VAR_LANEPOSITION]
            if vid not in seg_enter and lane.startswith("in_") and lp >= ll - REF_UP:
                seg_enter[vid] = t
            elif vid in seg_enter and lane.startswith("out_") and lp >= REF_DOWN:
                times.append(t - seg_enter.pop(vid))
        if t > 1200 and conn.simulation.getMinExpectedNumber() <= 0:
            break
    conn.close()
    return np.array(times), ll


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    allres, alldetail = {}, {}
    for variant in ("A_excl", "B_shared"):
        net = os.path.join(BASE, "outputs", "net", f"{variant}.net.xml")
        lm = LinkMap(net)
        prog = os.path.join(OUT, f"{variant}.allgreen.tll.xml")
        write_allgreen(lm, prog)
        res, det = {}, {}
        ll = None
        for a in "NESW":
            for m in ("r", "s", "l"):
                v, ll = run_movement(net, prog, a, m, f"ff_{variant}_{a}{m}")
                res[f"{a}{m}"] = float(np.percentile(v, 5))
                det[f"{a}{m}"] = {"n": int(len(v)), "min": float(v.min()),
                                  "p5": float(np.percentile(v, 5)),
                                  "median": float(np.median(v)),
                                  "mean": float(v.mean()), "max": float(v.max())}
        allres[variant] = res
        alldetail[variant] = {"detail": det, "approach_lane_length_m": ll,
                              "segment_def": {"upstream_m": REF_UP, "downstream_m": REF_DOWN},
                              "geometric_datum_s": (REF_UP + REF_DOWN) / 13.89}
    with open(os.path.join(OUT, "freeflow.json"), "w") as f:
        json.dump(allres, f, indent=2)
    with open(os.path.join(OUT, "freeflow_detail.json"), "w") as f:
        json.dump(alldetail, f, indent=2)
    for v in allres:
        d0 = alldetail[v]
        print(f"--- {v}  approach lane length={d0['approach_lane_length_m']:.2f} m, "
              f"geometric datum={d0['geometric_datum_s']:.2f} s")
        for k in sorted(allres[v]):
            d = d0["detail"][k]
            print(f"  {k}: p5={d['p5']:.2f}s min={d['min']:.2f}s median={d['median']:.2f}s "
                  f"max={d['max']:.2f}s n={d['n']}")
