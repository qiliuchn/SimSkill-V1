#!/usr/bin/env python3
"""Measure the corridor's per-direction capacity as a function of the number of
open lanes, by loading one direction far above capacity and reading the SERVED
flow off the exit stop line (never the demand).

Follows `quantify-sumo-run-to-run-variability`: capacity is the peak of the
served-flow-vs-demand curve, not the flow at the highest demand tested.

Writes outputs/analysis/capacity_measurement.json
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NETDIR, DEMDIR, RUNDIR, ANADIR, SCRIPTS, ensure_dirs,
                    assignment, PHYS_LANES, DIR_EDGES, lane_id)

CONFIG_FOR_NLANES = {2: "2+4", 3: "3+3", 4: "4+2"}   # eastbound lane count


def run(nlanes, demand, seed=11):
    cfg = CONFIG_FOR_NLANES[nlanes]
    tag = f"cap_L{nlanes}_D{demand}"
    rou = os.path.join(DEMDIR, tag + ".rou.xml")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "gen_demand.py"),
                    "--out", rou, "--seed", str(seed),
                    "--period", f"0,600,{demand*2},1.0",
                    "--period", f"600,3600,{demand},1.0",
                    "--cross", "400", "--cross-end", "3600"],
                   check=True, capture_output=True)
    out = os.path.join(RUNDIR, tag)
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "reversible_controller.py"),
                    "--net", os.path.join(NETDIR, "encB_open.net.xml"),
                    "--routes", rou, "--outdir", out, "--policy", "A",
                    "--start-config", cfg, "--seed", str(seed), "--end", "5400"],
                   check=True, capture_output=True)
    # served flow = eastbound vehicles that completed, in the 600-3600 window
    served = 0
    for tr in ET.parse(os.path.join(out, "tripinfo.xml")).getroot():
        if not tr.get("id").startswith("EB."):
            continue
        arr = float(tr.get("arrival", -1))
        if 900.0 <= arr < 3600.0:
            served += 1
    flow = served * 3600.0 / (3600.0 - 900.0)
    return dict(open_lanes_EB=nlanes, config=cfg, demand_vph=demand,
                served_veh_900_3600=served, served_flow_vph=round(flow, 1),
                per_lane_vph=round(flow / nlanes, 1))


def main():
    ensure_dirs()
    res = []
    for nl in (2, 3, 4):
        for dem in (1600, 2400, 3200, 4000, 4800, 5600):
            r = run(nl, dem)
            res.append(r)
            print(r)
    # capacity = peak served flow over the demand sweep, per lane count
    cap = {}
    for nl in (2, 3, 4):
        rows = [r for r in res if r["open_lanes_EB"] == nl]
        best = max(rows, key=lambda r: r["served_flow_vph"])
        cap[nl] = dict(capacity_vph=best["served_flow_vph"],
                       at_demand_vph=best["demand_vph"],
                       per_lane_vph=best["per_lane_vph"])
    out = os.path.join(ANADIR, "capacity_measurement.json")
    with open(out, "w") as f:
        json.dump(dict(sweep=res, capacity_by_open_lane_count=cap), f, indent=2)
    print("\nCAPACITY:", json.dumps(cap, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
