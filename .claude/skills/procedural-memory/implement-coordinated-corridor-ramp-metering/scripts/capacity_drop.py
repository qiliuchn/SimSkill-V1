#!/usr/bin/env python3
"""Multi-seed measurement of the lane-drop bottleneck's CAPACITY DROP.

H6's premise (metering that PREVENTS breakdown retains capacity) is only real if
the bottleneck actually loses capacity once it breaks down.  The
[[variable-speed-limits-and-e2-detectors]] page records a verified NULL result for
exactly this on a 3->2 lane drop, so it must be re-measured here rather than
assumed.  Method: steady mainline-only demand at levels straddling the breakdown
threshold, 6 seeds each; classify each run as broken-down or not from the
upstream detector's speed; compare the discharge rate (s11) of the two classes.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_additional import build as build_add  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET = os.path.join(ROOT, "outputs", "net", "s3_160", "corridor.net.xml")
OUT = os.path.join(ROOT, "outputs", "capdrop")
LEVELS = [3000, 3300, 3500, 3600, 3700, 3800, 3900, 4000, 4200, 4600]
SEEDS = [1, 2, 3, 4, 5, 6]
WARM, DUR = 600, 2400


def one(job):
    lv, sd = job
    d = os.path.join(OUT, f"lv{lv}_s{sd}")
    os.makedirs(d, exist_ok=True)
    add = build_add(NET, d, period=60)
    rf = os.path.join(d, "r.rou.xml")
    n = int(lv * DUR / 3600)
    open(rf, "w").write(
        '<routes>\n<vType id="car" vClass="passenger" length="5.0" minGap="2.5" accel="2.6" '
        'decel="4.5" sigma="0.5" tau="1.0" maxSpeed="40.0" speedDev="0.1" carFollowModel="Krauss"/>\n'
        '<route id="ml" edges="ml_0 ml_1 ml_2 ml_3 ml_4 ml_5 ml_6"/>\n'
        f'<flow id="f" route="ml" type="car" begin="0" end="{DUR}" number="{n}" '
        'departLane="best" departSpeed="max"/>\n</routes>\n')
    r = subprocess.run(["sumo", "-n", NET, "-r", rf, "-a", add, "--begin", "0",
                        "--end", str(DUR + 900), "--seed", str(sd), "--no-step-log", "true",
                        "--duration-log.disable", "true", "--xml-validation", "never",
                        "--time-to-teleport", "300"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    agg = defaultdict(lambda: defaultdict(list))
    for iv in ET.parse(os.path.join(d, "det_e1.xml")).getroot():
        t0 = float(iv.get("begin"))
        if t0 < WARM or t0 >= DUR or not iv.get("id").startswith("e1_s"):
            continue
        st = iv.get("id").split("_")[1]
        agg[st]["flow"].append(float(iv.get("nVehContrib")) * 60.0)
        agg[st]["spd"].append(float(iv.get("speed")))
    nint = (DUR - WARM) / 60.0
    # breakdown is judged at s09 (800 m upstream of the drop): s10 sits inside the
    # lane drop's permanent merge-turbulence zone and reads low speed even in free flow
    v09 = [s for s in agg["s09"]["spd"] if s >= 0]
    v10 = [s for s in agg["s10"]["spd"] if s >= 0]
    return dict(level=lv, seed=sd,
                f11=sum(agg["s11"]["flow"]) / nint,
                v09=sum(v09) / len(v09) if v09 else None,
                v10=sum(v10) / len(v10) if v10 else None,
                broke=bool(v09 and sum(v09) / len(v09) < 25))


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [(lv, sd) for lv in LEVELS for sd in SEEDS]
    with ProcessPoolExecutor(max_workers=6) as ex:
        rows = [r for r in ex.map(one, jobs) if r]
    free = [r for r in rows if not r["broke"]]
    cong = [r for r in rows if r["broke"]]
    qmax = max(r["f11"] for r in free) if free else None
    qfree = sorted((r["f11"] for r in free), reverse=True)[:5]
    qcong = [r["f11"] for r in cong]
    res = dict(
        n_runs=len(rows), n_free=len(free), n_broken=len(cong),
        free_flow_max_discharge=qmax,
        free_flow_top5_mean=sum(qfree) / len(qfree) if qfree else None,
        congested_discharge_mean=sum(qcong) / len(qcong) if qcong else None,
        congested_discharge_min=min(qcong) if qcong else None,
        congested_discharge_max=max(qcong) if qcong else None,
        capacity_drop_pct=(100 * (qmax - sum(qcong) / len(qcong)) / qmax) if (qmax and qcong) else None,
        breakdown_prob_by_level={lv: sum(1 for r in rows if r["level"] == lv and r["broke"]) / len(SEEDS)
                                 for lv in LEVELS},
        rows=rows)
    for lv in LEVELS:
        sub = [r for r in rows if r["level"] == lv]
        print(f"  demand {lv}: broke {sum(r['broke'] for r in sub)}/{len(sub)} seeds | "
              f"discharge free {[round(r['f11']) for r in sub if not r['broke']]} "
              f"congested {[round(r['f11']) for r in sub if r['broke']]}")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    os.makedirs(os.path.join(ROOT, "outputs", "tables"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "outputs", "tables", "capacity_drop.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
