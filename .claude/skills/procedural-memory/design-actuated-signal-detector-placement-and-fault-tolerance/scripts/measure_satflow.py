#!/usr/bin/env python3
"""Measure saturation flow rate per movement group with an oversaturated probe run.

Method (per `measure-saturation-flow-and-validate-webster-method`):
  * flood every approach so queues never clear,
  * run a long fixed-time plan,
  * record every stop-line crossing with an <instantInductionLoop> (per-vehicle
    enter events, not interval aggregates),
  * for each green interval discard the first 4 discharging vehicles (start-up
    lost time) and take the mean headway of the remainder,
  * s = 3600 / mean_saturation_headway  [veh/h/lane].

Writes work/satflow/satflow.json
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tls_common import (ALL_DET_LANES, GREEN_ORDER, GREEN_PHASES, LANE2PHASE,
                        APPROACH_LEN, build_program)

HORIZON = 1800


def write_inputs(wd, net):
    os.makedirs(wd, exist_ok=True)
    # flood: 1200 veh/h per movement -> every lane permanently queued
    from make_demand import DEST
    rou = ['<routes>',
           '    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0"'
           ' minGap="2.5" maxSpeed="20.0" tau="1.0"/>']
    for ap, m in DEST.items():
        for mv, dst in m.items():
            rou.append(f'    <route id="r_{ap}_{mv}" edges="{ap} {dst}"/>')
    for ap, m in DEST.items():
        for mv in m:
            q = 1500 if mv == "t" else 900
            rou.append(f'    <flow id="f_{ap}_{mv}" route="r_{ap}_{mv}" '
                       f'begin="0" end="{HORIZON}" vehsPerHour="{q}" '
                       f'type="car" departLane="best" departSpeed="max"/>')
    rou.append('</routes>')
    open(os.path.join(wd, "flood.rou.xml"), "w").write("\n".join(rou))

    # long fixed greens so each phase reaches a fully saturated discharge regime
    durs = {0: 60, 3: 30, 6: 60, 9: 30}
    add = ['<additional>']
    for ln in ALL_DET_LANES:
        add.append(f'    <instantInductionLoop id="stop_{ln}" lane="{ln}" '
                   f'pos="{APPROACH_LEN - 0.5:.2f}" file="inst_{ln}.xml"/>')
    add.append(build_program(durs, tls_type="static", program_id="sat"))
    add.append('</additional>')
    open(os.path.join(wd, "sat.add.xml"), "w").write("\n".join(add))
    return durs


def run(wd, net):
    cmd = ["sumo", "-n", net, "-r", "flood.rou.xml", "-a", "sat.add.xml", "--begin", "0",
           "--end", str(HORIZON), "--step-length", "0.5",
           "--time-to-teleport", "300", "--no-step-log", "true",
           "--seed", "1", "--duration-log.statistics", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=wd)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        sys.exit(1)
    return r.stderr


def green_windows(durs):
    """Return list of (phase_green_index, t_start, t_end) over the horizon."""
    seq = []
    for gp in GREEN_ORDER:
        seq.append((gp, durs[gp]))
        seq.append((None, 3))
        seq.append((None, 1))
    cyc = sum(d for _, d in seq)
    out, t = [], 0.0
    while t < HORIZON:
        for gp, d in seq:
            if gp is not None and t + d <= HORIZON:
                out.append((gp, t, t + d))
            t += d
            if t >= HORIZON:
                break
    return out, cyc


def analyse(wd, durs):
    wins, cyc = green_windows(durs)
    res = {}
    for ln in ALL_DET_LANES:
        f = os.path.join(wd, f"inst_{ln}.xml")
        times = []
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == "instantOut" and el.get("state") == "enter":
                times.append(float(el.get("time")))
            el.clear()
        times.sort()
        gp = LANE2PHASE[ln]
        hdws = []
        nveh_used = 0
        for g, t0, t1 in wins:
            if g != gp or t0 < 300:      # skip the loading transient
                continue
            crossings = [t for t in times if t0 <= t <= t1 + 3.0]
            if len(crossings) < 8:       # need a genuinely saturated discharge
                continue
            core = crossings[4:]         # drop start-up lost-time vehicles
            hdws += [b - a for a, b in zip(core, core[1:]) if 0 < b - a < 6.0]
            nveh_used += len(core)
        if hdws:
            h = sum(hdws) / len(hdws)
            res[ln] = dict(headway=round(h, 4), sat_flow=round(3600.0 / h, 1),
                           n_headways=len(hdws), n_veh=nveh_used,
                           phase=GREEN_PHASES[gp]["name"])
        else:
            res[ln] = dict(headway=None, sat_flow=None, n_headways=0)
    return res


if __name__ == "__main__":
    wd, net = sys.argv[1], os.path.abspath(sys.argv[2])
    durs = write_inputs(wd, net)
    run(wd, net)
    res = analyse(wd, durs)
    json.dump(res, open(os.path.join(wd, "satflow.json"), "w"), indent=2)
    for ln, d in res.items():
        print(f"{ln:6s} {d.get('phase',''):14s} h={d['headway']} "
              f"s={d['sat_flow']} veh/h  (n={d['n_headways']})")
