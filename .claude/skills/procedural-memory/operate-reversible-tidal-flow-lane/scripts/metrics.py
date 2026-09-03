#!/usr/bin/env python3
"""Censoring-robust corridor performance metrics for one run directory.

Following `validate-congested-scenario-results-against-teleport-artifacts` and
`design-actuated-signal-detector-placement-and-fault-tolerance`: `tripinfo`
records only vehicles that were actually inserted, so an oversaturated arm can
look artificially good.  Every vehicle present in the DEMAND file is therefore
accounted for:

  arrived      delay = duration + departDelay - freeflow
  inserted but not arrived (written by --tripinfo-output.write-unfinished)
               delay = (sim_end - depart_planned) - freeflow
  never inserted (absent from tripinfo entirely)
               delay = (sim_end - depart_planned)          [full censoring charge]

Free-flow reference time per route is computed from the compiled net
(edge length / edge speed), plus the two terminal signals' mean uniform delay.
"""
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PERSON_PER_VEH

DIR_OF = {"EB": "EB", "WB": "WB"}


def route_freeflow(netfile):
    """route id -> free-flow travel time (s), from the compiled net."""
    root = ET.parse(netfile).getroot()
    elen, espeed = {}, {}
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        lanes = edge.findall("lane")
        elen[edge.get("id")] = float(lanes[0].get("length"))
        espeed[edge.get("id")] = float(lanes[0].get("speed"))
    routes = {
        "EB": ["apW_in", "COR_EB", "apE_out"],
        "WB": ["apE_in", "COR_WB", "apW_out"],
        "XW_N": ["Ws_W", "W_Wn"], "XW_S": ["Wn_W", "W_Ws"],
        "XE_N": ["Es_E", "E_En"], "XE_S": ["En_E", "E_Es"],
    }
    out = {}
    for k, edges in routes.items():
        out[k] = sum(elen[e] / espeed[e] for e in edges)
    return out


def demand_departs(routefile):
    """vehicle id -> (planned depart, group)."""
    out = {}
    for ev, el in ET.iterparse(routefile, events=("end",)):
        if el.tag == "vehicle":
            vid = el.get("id")
            out[vid] = (float(el.get("depart")), vid.split(".")[0])
            el.clear()
    return out


def teleport_count(summaryfile):
    last = 0
    for ev, el in ET.iterparse(summaryfile, events=("end",)):
        if el.tag == "step":
            last = int(el.get("teleports"))
            el.clear()
    return last


def run_metrics(rundir, routefile, netfile, sim_end):
    ff = route_freeflow(netfile)
    demand = demand_departs(routefile)
    tri = os.path.join(rundir, "tripinfo.xml")

    per = defaultdict(lambda: dict(n=0, arrived=0, unfinished=0, never=0,
                                   veh_hours_delay=0.0, veh_hours_total=0.0,
                                   duration_sum=0.0, timeloss_sum=0.0,
                                   waiting_sum=0.0, departdelay_sum=0.0))
    seen = set()
    for ev, el in ET.iterparse(tri, events=("end",)):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        seen.add(vid)
        grp = vid.split(".")[0]
        p = per[grp]
        p["n"] += 1
        arrival = float(el.get("arrival"))
        dep = float(el.get("depart"))
        dd = float(el.get("departDelay"))
        planned = demand[vid][0] if vid in demand else dep - dd
        if arrival >= 0:
            p["arrived"] += 1
            total = arrival - planned
        else:
            p["unfinished"] += 1
            total = sim_end - planned
        p["veh_hours_total"] += total / 3600.0
        p["veh_hours_delay"] += max(total - ff.get(grp, 0.0), 0.0) / 3600.0
        p["duration_sum"] += float(el.get("duration"))
        p["timeloss_sum"] += float(el.get("timeLoss"))
        p["waiting_sum"] += float(el.get("waitingTime"))
        p["departdelay_sum"] += dd
        el.clear()

    for vid, (planned, grp) in demand.items():
        if vid in seen:
            continue
        p = per[grp]
        p["n"] += 1
        p["never"] += 1
        total = sim_end - planned
        p["veh_hours_total"] += total / 3600.0
        p["veh_hours_delay"] += max(total - ff.get(grp, 0.0), 0.0) / 3600.0

    tel = teleport_count(os.path.join(rundir, "summary.xml"))
    out = dict(groups={}, teleports=tel)
    for grp, p in per.items():
        d = dict(p)
        d["mean_delay_s"] = p["veh_hours_delay"] * 3600.0 / max(p["n"], 1)
        d["person_hours_delay"] = p["veh_hours_delay"] * PERSON_PER_VEH
        out["groups"][grp] = d

    corr = ["EB", "WB"]
    out["corridor"] = dict(
        veh_hours_delay=sum(out["groups"].get(g, {}).get("veh_hours_delay", 0.0) for g in corr),
        person_hours_delay=sum(out["groups"].get(g, {}).get("person_hours_delay", 0.0) for g in corr),
        demand=sum(out["groups"].get(g, {}).get("n", 0) for g in corr),
        arrived=sum(out["groups"].get(g, {}).get("arrived", 0) for g in corr),
        unfinished=sum(out["groups"].get(g, {}).get("unfinished", 0) for g in corr),
        never_inserted=sum(out["groups"].get(g, {}).get("never", 0) for g in corr),
    )
    out["network"] = dict(
        veh_hours_delay=sum(g["veh_hours_delay"] for g in out["groups"].values()),
        person_hours_delay=sum(g["person_hours_delay"] for g in out["groups"].values()),
        demand=sum(g["n"] for g in out["groups"].values()),
        never_inserted=sum(g["never"] for g in out["groups"].values()),
        unfinished=sum(g["unfinished"] for g in out["groups"].values()),
    )
    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--end", type=float, required=True)
    a = ap.parse_args()
    print(json.dumps(run_metrics(a.rundir, a.routes, a.net, a.end), indent=2))
